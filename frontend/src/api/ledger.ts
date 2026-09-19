import { http } from './client'

export type LedgerSource = 'order' | 'manual'

export interface LedgerEntry {
  id: number
  shipper_id: number | null
  temp_shipper_name?: string | null
  entry_date: string
  product_name: string
  quantity: number
  unit_price: string | number
  total: string | number
  order_id: number | null
  /** 与订单明细行绑定（送达自动记账时写入） */
  order_product_id?: number | null
  product_id: number | null
  order_no?: string | null
  /** 关联订单送货说明（规格/定制摘要等） */
  order_delivery_description?: string | null
  source: LedgerSource
  note: string
  created_at: string
}

export async function fetchLedgerEntries(params: {
  shipper_id?: number
  temp_shipper_name?: string
  date_from?: string
  date_to?: string
}) {
  const { data } = await http.get<LedgerEntry[]>('/ledger/entries', { params })
  return data
}

/** 派单员：系统中曾出现的临时货主称呼（用于账本筛选快捷选择） */
export async function fetchTempShipperNames() {
  const { data } = await http.get<string[]>('/ledger/temp-shipper-names')
  return data
}

export async function createLedgerEntry(body: {
  shipper_id?: number
  temp_shipper_name?: string
  entry_date: string
  product_name: string
  quantity: number
  unit_price: number | string
  total?: number | string
  order_id?: number | null
  product_id?: number | null
  source?: LedgerSource
  note?: string
}) {
  const { data } = await http.post<LedgerEntry>('/ledger/entries', {
    ...body,
    source: body.source ?? 'manual',
  })
  return data
}

export async function syncLedgerFromDeliveredOrders(body?: {
  shipper_id?: number | null
  temp_shipper_name?: string | null
}) {
  const { data } = await http.post<{ orders_synced: number; shippers_notified: number }>(
    '/ledger/sync-from-delivered-orders',
    body ?? {},
  )
  return data
}

export async function updateLedgerEntry(
  id: number,
  body: {
    note?: string
    /** 仅手动行可传 */
    entry_date?: string
    product_name?: string
    quantity?: number
    unit_price?: number | string
    total?: number | string
    order_id?: number | null
    product_id?: number | null
  },
) {
  const { data } = await http.patch<LedgerEntry>(`/ledger/entries/${id}`, body)
  return data
}

export async function deleteLedgerEntry(id: number) {
  await http.delete(`/ledger/entries/${id}`)
}

export type ExportFormat = 'excel' | 'pdf'

export interface LedgerExportJob {
  id: number
  created_by_id: number
  shipper_id: number
  file_format: ExportFormat
  date_from: string
  date_to: string
  status: 'pending' | 'processing' | 'done' | 'failed'
  file_path: string | null
  error_message: string | null
  completed_at: string | null
  created_at: string
}

export async function createLedgerExportJob(body: {
  shipper_id: number
  date_from: string
  date_to: string
  export_format: ExportFormat
}) {
  const { data } = await http.post<LedgerExportJob>('/ledger/export-jobs', body)
  return data
}

export async function getLedgerExportJob(jobId: number) {
  const { data } = await http.get<LedgerExportJob>(`/ledger/export-jobs/${jobId}`)
  return data
}

/**
 * 下载导出产物（2026-09-19 审计 H5）——**必须走这个端点、并且带着 token 取**。
 *
 * ### 原来为什么永远下不下来
 * `ShipperLedger.vue` 原来是 `window.open(origin + job.file_path)`，而
 * `file_path` 存的是**产物文件名**（`ledger_2_5_rgtt4-aHvnGtA9aF.xlsx`，实测库里的样子），
 * 不是 URL → 拼出来是 `http://host/ledger_2_5_rgtt4-….xlsx` → **404**；
 * 就算拼对了，`window.open` 也**带不上 `Authorization` 头**（下载端点要鉴权）→ 401。
 * 而界面照样弹「导出完成」——**用户以为导出成功了，其实什么都没有**。
 *
 * 做法与 `/stats/export` 同一套（`api/stats.ts::downloadStatsExport`）：
 * 以 blob 取回（axios 会自动带 token）→ 从 `Content-Disposition` 取文件名（拿不到就用兜底名）→
 * `<a download>` 触发保存。
 */
export async function downloadLedgerExportFile(job: {
  id: number
  date_from?: string
  date_to?: string
  file_format?: ExportFormat
}) {
  const res = await http.get(`/ledger/export-jobs/${job.id}/download`, { responseType: 'blob' })
  const blob = res.data as Blob
  // 文件名：**先用"人看得懂的名字"**（`账本_2026-09-01_2026-09-19.xlsx`）。
  // 后端 `Content-Disposition` 给的是产物文件名（`ledger_2_1_F2LB-X4mBOcYhR3A.xlsx`），
  // 那串随机后缀对用户没有任何意义 —— 只在拿不到日期区间时才退回它。
  const ext = job.file_format === 'pdf' ? 'pdf' : 'xlsx'
  let name =
    job.date_from && job.date_to ? `账本_${job.date_from}_${job.date_to}.${ext}` : ''
  if (!name) {
    const cd = res.headers['content-disposition'] as string | undefined
    name = `ledger-export-${job.id}.${ext}`
    if (cd) {
      const m = /filename="?([^";]+)"?/i.exec(cd)
      if (m?.[1]) name = m[1]
    }
  }
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = name
  a.click()
  URL.revokeObjectURL(url)
}
