/**
 * 与 `backend/app/models/enums.py::OrderStatus` **逐值对齐**（五个，不是四个）。
 *
 * ⚠️ 少一个取值不是"类型不够全"，而是**这一档状态的订单在客户端上整体消失**：
 *    `DISPATCHED`（已派单·司机未接单）曾经就不在这里，于是 H5 全站没有任何入口能列出它
 *    （2026-09-19 审计 H1）。红线 `_tools/qa/_check_client_contract.py` 从后端枚举逐值对账。
 */
export type OrderStatus =
  | 'PENDING_DISPATCH'
  | 'DISPATCHED'
  | 'ACCEPTED'
  | 'DELIVERED'
  | 'CANCELLED'

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
  /** 撤销时间；已撤销/软删除订单进隔离区保留 **30 天**（`data_retention.py`），不是 10 天 */
  cancelled_at?: string | null
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
