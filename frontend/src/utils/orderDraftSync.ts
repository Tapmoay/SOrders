import { fetchOrders } from '@/api/orders'
import { clearOrderDraft, loadOrderDraft } from '@/constants/orderDraft'

/**
 * 货主首页：若服务端已有「创建时间晚于本地草稿保存时间」的订单（含派单中等任意状态），
 * 说明草稿对应内容已提交过或已过时，清除本地草稿，避免与「我的订单」里真实订单混淆。
 */
export async function reconcileShipperOrderDraftStale(): Promise<void> {
  const draft = loadOrderDraft('shipper')
  if (!draft) return
  const saved = draft.lastSavedAt ?? 0
  try {
    const orders = await fetchOrders()
    const hasNewerSubmitted = orders.some((o) => Date.parse(o.created_at) > saved)
    if (hasNewerSubmitted) clearOrderDraft('shipper')
  } catch {
    /* 离线时仅依赖 orderDraft 内锚点比较 */
  }
}
