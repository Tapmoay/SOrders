import { http } from './client'

export interface NotificationItem {
  id: number
  recipient_id: number
  type: string
  title: string
  content: string
  payload: Record<string, unknown> | null
  read_at: string | null
  created_at: string
}

export async function notifyPriceChange(body: {
  shipper_ids: number[]
  product_id: number
  product_name: string
  price_type: 'default' | 'special'
  new_price: string | number
  old_price?: string | number | null
  /** 可选，货主端展示商品图 */
  product_image_url?: string | null
}) {
  const { data } = await http.post<NotificationItem[]>('/notifications/price-notify', body)
  return data
}
