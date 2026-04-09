import type { OrderStatus } from '@/types/order'

export const ORDER_STATUS_LABEL: Record<OrderStatus, string> = {
  PENDING_DISPATCH: '派单中',
  ACCEPTED: '已接单',
  DELIVERED: '已送达',
  CANCELLED: '已撤销',
}

/** van-tag type */
export function orderStatusTagType(
  s: OrderStatus,
): 'primary' | 'success' | 'warning' | 'danger' | 'default' {
  switch (s) {
    case 'PENDING_DISPATCH':
      return 'warning'
    case 'ACCEPTED':
      return 'primary'
    case 'DELIVERED':
      return 'success'
    case 'CANCELLED':
      return 'danger'
    default:
      return 'default'
  }
}
