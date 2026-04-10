import type { AppNotification } from '@/api/notifications'

function recipientMatches(n: AppNotification, recipientId: number | null): boolean {
  if (recipientId == null) return true
  return Number(n.recipient_id) === Number(recipientId)
}

/**
 * 未读消息列表（用于 Tab 角标）。
 * - 派单员：必须带 userId 且按 recipient 过滤（全站通知列表可能含他人）。
 * - 货主/司机：接口已限定本人；userId 尚未写入时仍按未读统计，避免角标恒为 0。
 */
function unreadForRecipient(
  items: AppNotification[],
  recipientId: number | null,
  role: string | null,
) {
  if (role === 'dispatcher') {
    if (recipientId == null) return []
    return items.filter((n) => n.read_at == null && recipientMatches(n, recipientId))
  }
  if (recipientId != null) {
    return items.filter((n) => n.read_at == null && recipientMatches(n, recipientId))
  }
  return items.filter((n) => n.read_at == null)
}

const DRIVER_OPEN_TYPES = new Set(['order.assigned', 'order.revoked', 'order.cancelled'])
const DRIVER_COMPLETED_TYPES = new Set(['order.delivered_driver'])

/** 派单端：与后端现有 type 对齐；无对应类型的 Tab 保持 0，后续可扩展 */
const DISPATCHER_PENDING_TYPES = new Set<string>([
  // 例如将来：待派单池提醒、异常待处理
])
const DISPATCHER_COMPLETED_TYPES = new Set<string>([
  // 例如将来：全站送达汇总通知给派单员
])
const DISPATCHER_DASHBOARD_TYPES = new Set<string>([])
const DISPATCHER_PRICES_TYPES = new Set<string>([])
const DISPATCHER_LEDGER_TYPES = new Set(['ledger_export'])

function capBadge(n: number): number | string | undefined {
  if (n <= 0) return undefined
  return n > 99 ? '99+' : n
}

export function driverOpenTabBadge(
  items: AppNotification[],
  recipientId: number | null,
  role: string | null,
) {
  const c = unreadForRecipient(items, recipientId, role).filter((n) =>
    DRIVER_OPEN_TYPES.has(n.type),
  ).length
  return capBadge(c)
}

export function driverCompletedTabBadge(
  items: AppNotification[],
  recipientId: number | null,
  role: string | null,
) {
  const c = unreadForRecipient(items, recipientId, role).filter((n) =>
    DRIVER_COMPLETED_TYPES.has(n.type),
  ).length
  return capBadge(c)
}

export function dispatcherPendingTabBadge(
  items: AppNotification[],
  recipientId: number | null,
  role: string | null,
) {
  const c = unreadForRecipient(items, recipientId, role).filter((n) =>
    DISPATCHER_PENDING_TYPES.has(n.type),
  ).length
  return capBadge(c)
}

export function dispatcherCompletedTabBadge(
  items: AppNotification[],
  recipientId: number | null,
  role: string | null,
) {
  const c = unreadForRecipient(items, recipientId, role).filter((n) =>
    DISPATCHER_COMPLETED_TYPES.has(n.type),
  ).length
  return capBadge(c)
}

export function dispatcherDashboardTabBadge(
  items: AppNotification[],
  recipientId: number | null,
  role: string | null,
) {
  const c = unreadForRecipient(items, recipientId, role).filter((n) =>
    DISPATCHER_DASHBOARD_TYPES.has(n.type),
  ).length
  return capBadge(c)
}

export function dispatcherPricesTabBadge(
  items: AppNotification[],
  recipientId: number | null,
  role: string | null,
) {
  const c = unreadForRecipient(items, recipientId, role).filter((n) =>
    DISPATCHER_PRICES_TYPES.has(n.type),
  ).length
  return capBadge(c)
}

export function dispatcherLedgerTabBadge(
  items: AppNotification[],
  recipientId: number | null,
  role: string | null,
) {
  const c = unreadForRecipient(items, recipientId, role).filter((n) =>
    DISPATCHER_LEDGER_TYPES.has(n.type),
  ).length
  return capBadge(c)
}
