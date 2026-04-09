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
