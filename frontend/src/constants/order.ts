import type { OrderStatus } from '@/types/order'

/**
 * 后端 `OrderStatus` **六个**取值的唯一中文名（与 `docs/DOMAIN_MODEL.md` §订单状态机一致）。
 *
 * ⚠️ 这里必须是 `Record<OrderStatus, string>`（全量映射，少一个取值类型检查就报错）——
 *    旧版 H5 当初正是漏掉了 `DISPATCHED`（2026-09-19 审计 H1）：
 *    司机端只查 `ACCEPTED`、派单员页签只有「待派单/运输中」、`ORDER_STATUS_LABEL` 没有这一档，
 *    后果是**已经派出去、司机还没接单的订单在 H5 上任何列表里都不存在**：
 *    司机看不到新单（接不了单 → 这一趟卡死）、派单员看不到也撤不回、账本行直接印出 `undefined`。
 *    静态红线 `_tools/qa/_check_client_contract.py` 现在拿 `enums.py::OrderStatus` 逐值对账。
 */
export const ORDER_STATUS_LABEL: Record<OrderStatus, string> = {
  PENDING_DISPATCH: '派单中',
  DISPATCHED: '已派单',
  ACCEPTED: '已接单',
  DELIVERED: '已送达',
  CANCELLED: '已撤销',
  // 2026-09-20：退货（送了、入了账、事后货退回来了）。与「已撤销」是两件事。
  RETURNED: '已退货',
}

/**
 * 「这一单还撤得掉吗」——**唯一判据**，真源是后端 `POST /orders/{id}/cancel` 的状态门
 * （`order_flow.cancel_pending`：`allowed = (PENDING_DISPATCH, DISPATCHED)`）与
 * `orders.py` 里同一对取值。司机接单之后（ACCEPTED）货主/派单员都不能再撤。
 *
 * 为什么要抽成常量：原先三个页面各写一遍 `o.status !== 'PENDING_DISPATCH'`，
 * 五个状态里漏掉 `DISPATCHED` 之后**界面少一个按钮、接口其实允许**——用户只会以为"系统坏了"。
 * 按钮的显示条件与提交前的守卫都读这一个表，红线逐页对账。
 */
export const CANCELLABLE_STATUSES: readonly OrderStatus[] = ['PENDING_DISPATCH', 'DISPATCHED']

/** 「派单员还撤得回这张单吗」——`recall_dispatch`：`allowed = (DISPATCHED, ACCEPTED)`。 */
export const RECALLABLE_STATUSES: readonly OrderStatus[] = ['DISPATCHED', 'ACCEPTED']

/** van-tag type。六个状态取六种，互不撞色（同屏要能一眼分开）。 */
export function orderStatusTagType(
  s: OrderStatus,
): 'primary' | 'success' | 'warning' | 'danger' | 'default' {
  switch (s) {
    case 'PENDING_DISPATCH':
      return 'warning'
    // 「已派单」用中性灰：它既不是"等派单"（黄）也不是"已接单"（蓝），
    // 语义由文字承担，颜色只负责"和隔壁两档不撞"。
    case 'DISPATCHED':
      return 'default'
    case 'ACCEPTED':
      return 'primary'
    case 'DELIVERED':
      return 'success'
    case 'CANCELLED':
      return 'danger'
    // 2026-09-20：已退货。van-tag 只有这五种 type，六档状态必然有一档与别人共用 ——
    // 挑 danger 与「已撤销」同色是**故意的**：两者都是"这单的钱不作数了"，
    // 而它们靠文字分得开（新加一个 type 需要改主题，收益只有一点点颜色差异）。
    case 'RETURNED':
      return 'danger'
    default:
      return 'default'
  }
}
