import { http } from './client'

import type { Order, OrderProduct, OrderStatus } from '@/types/order'

export async function fetchOrders(
  status?: OrderStatus,
  q?: string,
  shipperId?: number | null,
  tempShipperName?: string | null,
) {
  const params: Record<string, string> = {}
  if (status) params.status = status
  if (q && q.trim()) params.q = q.trim()
  if (shipperId != null) params.shipper_id = String(shipperId)
  if (tempShipperName != null && tempShipperName.trim()) params.temp_shipper_name = tempShipperName.trim()
  const { data } = await http.get<Order[]>('/orders', { params })
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
