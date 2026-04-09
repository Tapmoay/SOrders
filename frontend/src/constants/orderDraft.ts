/**
 * 未提交订单的本地草稿（货主 / 派单员代下单分键存储）。
 *
 * 范围说明：仅覆盖「尚未调用创建订单接口」的表单快照。
 * 已提交订单无论状态为派单中 / 已接单 / 已送达等，均由服务端管理，不属于本草稿机制。
 */

export type OrderDraftRole = 'shipper' | 'dispatcher'

const STORAGE: Record<OrderDraftRole, string> = {
  shipper: 'sorders_v1_order_draft_shipper',
  dispatcher: 'sorders_v1_order_draft_dispatcher',
}

export interface OrderDraftLine {
  product_name_snapshot: string
  quantity: number
  unit_price: number
  product_id: number | null
}

export interface OrderDraftV1 {
  v: 1
  deliveryDescription: string
  addressDetail: string
  addressLng: number | null
  addressLat: number | null
  dongjiaPhone: string
  bossPhone: string
  remark: string
  lines: OrderDraftLine[]
  /** 派单员代下单：所选货主 id */
  shipperId: number | null
  /** 派单员代下单：临时货主称呼（无系统账号），与 shipperId 互斥 */
  tempShipperName?: string
  /**
   * 用户是否曾主动编辑（不含仅自动带出默认地址/电话）。
   * 仅当为 true 时首页才显示「草稿」入口；提交成功后不应再显示。
   */
  userEdited?: boolean
  /** 最近一次保存草稿的本地时间戳（ms），用于与已提交订单的创建时间比较 */
  lastSavedAt?: number
}

/** 最近一次成功创建订单的服务端时间锚点（与草稿对比，用于隐藏「继续草稿」） */
const ANCHOR_MS: Record<OrderDraftRole, string> = {
  shipper: 'sorders_order_created_anchor_ms_shipper',
  dispatcher: 'sorders_order_created_anchor_ms_dispatcher',
}

export function getOrderCreatedAnchorMs(role: OrderDraftRole): number {
  try {
    const raw = localStorage.getItem(ANCHOR_MS[role])
    if (!raw) return 0
    const n = Number(raw)
    return Number.isFinite(n) ? n : 0
  } catch {
    return 0
  }
}

/** 创建订单成功后调用：以服务端 `created_at` 为锚，使早于该时间的本地草稿视为已作废 */
export function recordOrderCreatedAnchor(role: OrderDraftRole, createdAtIso: string) {
  const ms = Date.parse(createdAtIso)
  if (Number.isNaN(ms)) return
  const prev = getOrderCreatedAnchorMs(role)
  if (ms > prev) {
    try {
      localStorage.setItem(ANCHOR_MS[role], String(ms))
    } catch {
      /* quota */
    }
  }
}

function emptyDraft(): OrderDraftV1 {
  return {
    v: 1,
    deliveryDescription: '',
    addressDetail: '',
    addressLng: null,
    addressLat: null,
    dongjiaPhone: '',
    bossPhone: '',
    remark: '',
    lines: [{ product_name_snapshot: '', quantity: 1, unit_price: 0, product_id: null }],
    shipperId: null,
    tempShipperName: '',
    userEdited: false,
  }
}

/** 旧数据：无 userEdited 时，用「非仅地址簿」启发式推断是否算用户草稿 */
function inferLegacyUserEdited(d: OrderDraftV1): boolean {
  if (d.userEdited === true) return true
  if (d.userEdited === false) return false
  if (d.shipperId != null && d.shipperId > 0) return true
  if ((d.tempShipperName || '').trim()) return true
  if (d.deliveryDescription.trim() || d.remark.trim()) return true
  if (d.bossPhone.trim()) return true
  for (const ln of d.lines) {
    if (ln.product_name_snapshot.trim()) return true
    if (ln.quantity !== 1 || ln.unit_price !== 0) return true
  }
  return false
}

export function loadOrderDraft(role: OrderDraftRole): OrderDraftV1 | null {
  try {
    const raw = localStorage.getItem(STORAGE[role])
    if (!raw) return null
    const o = JSON.parse(raw) as OrderDraftV1
    if (!o || o.v !== 1 || !Array.isArray(o.lines)) return null
    const userEdited = o.userEdited !== undefined ? o.userEdited : inferLegacyUserEdited(o)
    return { ...o, userEdited }
  } catch {
    return null
  }
}

export function saveOrderDraft(role: OrderDraftRole, data: OrderDraftV1) {
  try {
    localStorage.setItem(STORAGE[role], JSON.stringify(data))
  } catch {
    /* quota */
  }
}

export function clearOrderDraft(role: OrderDraftRole) {
  try {
    localStorage.removeItem(STORAGE[role])
  } catch {
    /* ignore */
  }
}

/** 是否有「值得保留」的草稿（用于离开页时是否写入/删除） */
export function orderDraftHasMeaningfulContent(role: OrderDraftRole, d: OrderDraftV1 | null = loadOrderDraft(role)): boolean {
  if (!d) return false
  if (d.deliveryDescription.trim()) return true
  if (d.addressDetail.trim()) return true
  if (d.remark.trim()) return true
  if (d.dongjiaPhone.trim() || d.bossPhone.trim()) return true
  if (role === 'dispatcher' && d.shipperId != null && d.shipperId > 0) return true
  if (role === 'dispatcher' && (d.tempShipperName || '').trim()) return true
  for (const ln of d.lines) {
    if (ln.product_name_snapshot.trim()) return true
    if (ln.quantity !== 1 || ln.unit_price !== 0) return true
  }
  return false
}

/** 首页/派单台是否显示「继续编辑草稿」入口（须用户编辑过且有内容，且未被已提交订单覆盖） */
export function orderDraftIsResumable(role: OrderDraftRole): boolean {
  const d = loadOrderDraft(role)
  if (!d || !d.userEdited) return false
  if (!orderDraftHasMeaningfulContent(role, d)) return false
  const saved = d.lastSavedAt ?? 0
  const anchor = getOrderCreatedAnchorMs(role)
  if (anchor > 0 && saved < anchor) {
    clearOrderDraft(role)
    return false
  }
  return true
}

export function normalizeDraft(d: OrderDraftV1): OrderDraftV1 {
  const lines =
    d.lines?.length > 0
      ? d.lines.map((ln) => ({
          product_name_snapshot: ln.product_name_snapshot ?? '',
          quantity: Math.max(1, Number(ln.quantity) || 1),
          unit_price: Number(ln.unit_price) || 0,
          product_id: ln.product_id ?? null,
        }))
      : emptyDraft().lines
  return {
    v: 1,
    deliveryDescription: d.deliveryDescription ?? '',
    addressDetail: d.addressDetail ?? '',
    addressLng: d.addressLng ?? null,
    addressLat: d.addressLat ?? null,
    dongjiaPhone: d.dongjiaPhone ?? '',
    bossPhone: d.bossPhone ?? '',
    remark: d.remark ?? '',
    lines,
    shipperId: d.shipperId ?? null,
    tempShipperName: d.tempShipperName ?? '',
    userEdited: d.userEdited ?? false,
    lastSavedAt: d.lastSavedAt,
  }
}

export { emptyDraft }
