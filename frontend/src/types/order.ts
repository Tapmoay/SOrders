export type OrderStatus = 'PENDING_DISPATCH' | 'ACCEPTED' | 'DELIVERED' | 'CANCELLED'

export interface OrderProduct {
  id: number
  order_id: number
  product_id: number | null
  product_name_snapshot: string
  quantity: number
  unit_price: string | number
  line_total: string | number
}

export interface Order {
  id: number
  order_no: string
  status: OrderStatus
  shipper_id: number | null
  /** 派单员代下单：无系统货主账号时的临时称呼 */
  temp_shipper_name?: string | null
  driver_id: number | null
  order_date: string
  delivery_description: string
  address_detail: string
  address_lat?: string | number | null
  address_lng?: string | number | null
  contact_dongjia_phone: string
  contact_boss_phone: string
  remark: string
  internal_notes: string
  driver_remark: string
  delivery_photo_urls: string[] | null
  created_at: string
  dispatched_at: string | null
  driver_acknowledged_at?: string | null
  delivered_at: string | null
  order_products: OrderProduct[]
  driver_phone: string | null
  driver_name: string | null
  shipper_name?: string | null
  is_new_for_driver?: boolean
  expected_deliver_before?: string | null
  is_exception?: boolean
  exception_reason?: string
  exception_resolution?: string
}
