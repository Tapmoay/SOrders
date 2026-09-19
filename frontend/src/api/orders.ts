import { http } from './client'

import type { Order, OrderProduct, OrderStatus } from '@/types/order'

/**
 * 一页订单 + **这次是不是被服务端截断了**。
 *
 * 为什么必须有（2026-09-19 审计 H2）：`GET /orders` 现在对**所有角色**都有缺省上限 300
 * （数据保留 3 年，一年后就是几万单），截断与否写在响应头 `X-Truncated` / `X-Result-Limit` 里
 * （响应体是裸数组，加不了元数据）。旧版 H5 只取 `data`、从不看这两个头 ——
 * 于是**派单员在「全部」里以为看到了全部订单，其实只是最近 300 条**，
 * 他会据此判断"这单不存在"，然后让用户重新下单。这比"慢"糟得多。
 */
export interface OrdersPage {
  items: Order[]
  /** 服务端还有更多（`X-Truncated: 1`） */
  truncated: boolean
  /** 本次的服务端上限（`X-Result-Limit`），读不到时为 null */
  limit: number | null
}

/** 读不到这两个头时**不能**当成"没截断"：要如实说"不知道"。 */
function readPageHeaders(headers: Record<string, unknown>): {
  truncated: boolean
  limit: number | null
} {
  const raw = headers['x-truncated']
  const lim = headers['x-result-limit']
  const limit = lim != null && String(lim).trim() !== '' ? Number(lim) : null
  return {
    truncated: raw === '1' || raw === 'true' || raw === true,
    limit: Number.isFinite(limit as number) ? (limit as number) : null,
  }
}

export async function fetchOrdersPage(
  status?: OrderStatus,
  q?: string,
  shipperId?: number | null,
  tempShipperName?: string | null,
): Promise<OrdersPage> {
  const params: Record<string, string> = {}
  if (status) params.status = status
  if (q && q.trim()) params.q = q.trim()
  if (shipperId != null) params.shipper_id = String(shipperId)
  if (tempShipperName != null && tempShipperName.trim()) {
    params.temp_shipper_name = tempShipperName.trim()
  }
  const res = await http.get<Order[]>('/orders', { params })
  return { items: res.data, ...readPageHeaders(res.headers as Record<string, unknown>) }
}

export async function fetchOrders(
  status?: OrderStatus,
  q?: string,
  shipperId?: number | null,
  tempShipperName?: string | null,
) {
  const page = await fetchOrdersPage(status, q, shipperId, tempShipperName)
  return page.items
}

/**
 * **一屏要显示两档状态时用这个**（例如司机的「进行中」= 已派单 + 已接单，
 * 派单员的「运输中」= 已派单 + 已接单）。
 *
 * 为什么不让各页面自己写循环：`GET /orders` 一次只认一个 `status`，"少查一档"在界面上
 * 的表现是**这一档订单整批不存在**（不报错、不空列表提示，就是没有），
 * 正确性完全靠"写这段代码的人记得后端一共有五个状态"。抽到一处之后，
 * 谁调用它、调了几档，静态红线 `_tools/qa/_check_client_contract.py` 能逐处对账。
 *
 * 同一张单不会同时属于两档，去重只是防"接口偶发重复行"；
 * 排序按 id 倒序，与后端缺省排序一致（否则合并后新旧混排）。
 * **任意一档被截断，整页就算被截断**（用户看到的仍是"不完整的一屏"）。
 */
export async function fetchOrdersByStatuses(
  statuses: OrderStatus[],
  q?: string,
): Promise<OrdersPage> {
  const pages = await Promise.all(statuses.map((st) => fetchOrdersPage(st, q)))
  const seen = new Set<number>()
  const items: Order[] = []
  for (const p of pages) {
    for (const o of p.items) {
      if (seen.has(o.id)) continue
      seen.add(o.id)
      items.push(o)
    }
  }
  items.sort((a, b) => b.id - a.id)
  const limits = pages.map((p) => p.limit).filter((n): n is number => n != null)
  return {
    items,
    truncated: pages.some((p) => p.truncated),
    limit: limits.length ? Math.min(...limits) : null,
  }
}

/** 派单员：当前「派单中」订单总数（工作台角标） */
export async function fetchPendingDispatchCount() {
  const { data } = await http.get<{ count: number }>('/orders/pending-dispatch-count')
  return data
}

export interface OrderUpdateBody {
  delivery_description?: string | null
  address_detail?: string | null
  address_lat?: string | number | null
  address_lng?: string | number | null
  contact_dongjia_phone?: string | null
  contact_boss_phone?: string | null
  remark?: string | null
  internal_notes?: string | null
}

export async function updateOrder(id: number, body: OrderUpdateBody) {
  const { data } = await http.patch<Order>(`/orders/${id}`, body)
  return data
}

/** 派单员编辑订单商品行：商品名称、数量、单价、行金额（与后端 OrderProductUpdate 对齐） */
export interface OrderProductUpdateBody {
  product_id?: number | null
  product_name_snapshot?: string
  quantity?: number
  unit_price?: string | number
  line_total?: string | number
}

export async function updateOrderProduct(lineId: number, body: OrderProductUpdateBody) {
  const { data } = await http.patch<OrderProduct>(`/order-products/${lineId}`, body)
  return data
}

export interface OrderExceptionBody {
  is_exception?: boolean
  exception_reason?: string
  exception_resolution?: string
  expected_deliver_before?: string | null
}

export async function patchOrderException(id: number, body: OrderExceptionBody) {
  const { data } = await http.patch<Order>(`/orders/${id}/exception`, body)
  return data
}

export async function assignOrder(orderId: number, driverId: number, internalNote?: string) {
  const { data } = await http.post<Order>(`/orders/${orderId}/assign`, {
    driver_id: driverId,
    internal_note: internalNote?.trim() || undefined,
  })
  return data
}

export async function recallOrder(orderId: number, reason: string) {
  const { data } = await http.post<Order>(`/orders/${orderId}/recall`, { reason })
  return data
}

export interface BatchAssignResult {
  order_id: number
  success: boolean
  detail?: string | null
}

export async function batchAssignOrders(orderIds: number[], driverId: number, internalNote?: string) {
  const { data } = await http.post<{ results: BatchAssignResult[] }>('/orders/batch-assign', {
    order_ids: orderIds,
    driver_id: driverId,
    internal_note: internalNote?.trim() || undefined,
  })
  return data
}

export async function fetchOrder(id: number) {
  const { data } = await http.get<Order>(`/orders/${id}`)
  return data
}

export interface OrderLineInput {
  product_id?: number | null
  product_name_snapshot: string
  quantity: number
  unit_price: string | number
  line_total?: string | number
}

export interface CreateOrderBody {
  lines: OrderLineInput[]
  order_date?: string
  delivery_description?: string
  address_detail?: string
  address_lat?: string | number | null
  address_lng?: string | number | null
  contact_dongjia_phone?: string
  contact_boss_phone?: string
  remark?: string
  /** 派单员代下单时可选；不传表示订单暂无归属货主 */
  shipper_id?: number
  /** 与 shipper_id 互斥：临时货主称呼（不创建登录账号） */
  temp_shipper_name?: string
}

export async function createOrder(body: CreateOrderBody) {
  const { data } = await http.post<Order>('/orders', body)
  return data
}

export async function cancelOrder(id: number) {
  const { data } = await http.post<Order>(`/orders/${id}/cancel`)
  return data
}

/** 仅已撤销订单可删除；204 No Content */
export async function deleteCancelledOrder(id: number) {
  await http.delete(`/orders/${id}`)
}

export async function driverAckOrder(orderId: number) {
  const { data } = await http.post<Order>(`/orders/${orderId}/driver-ack`)
  return data
}

export async function appendDriverNote(orderId: number, note: string) {
  const { data } = await http.post<Order>(`/orders/${orderId}/driver-note`, { note })
  return data
}

export async function uploadDeliveryPhotos(orderId: number, files: File[]) {
  const form = new FormData()
  for (const f of files) {
    form.append('files', f)
  }
  const { data } = await http.post<{ urls: string[] }>(`/orders/${orderId}/delivery-photos`, form)
  return data.urls
}

export async function completeOrder(orderId: number, delivery_photo_urls: string[], driver_remark = '') {
  const { data } = await http.post<Order>(`/orders/${orderId}/complete`, {
    delivery_photo_urls,
    driver_remark,
  })
  return data
}

export async function completeOrderWithUpload(
  orderId: number,
  files: File[],
  driverRemark: string,
  onProgress?: (pct: number) => void,
) {
  const form = new FormData()
  form.append('driver_remark', driverRemark)
  for (const f of files) {
    form.append('files', f)
  }
  const { data } = await http.post<Order>(`/orders/${orderId}/complete-with-upload`, form, {
    onUploadProgress: (ev) => {
      if (ev.total != null && onProgress) {
        onProgress(Math.round((ev.loaded / ev.total) * 100))
      }
    },
  })
  return data
}
