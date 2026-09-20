package com.tapmoay.sorders.core

/**
 * 订单状态模型：**客户端唯一一份「哪一档能做什么」的事实**（2026-09-19 审计 H1）。
 *
 * ### 为什么要有这个文件
 * 同一条状态规则在客户端原来散成一堆字面量：
 * `DispatcherOrdersScreen` 的撤回按钮写 `status == "ACCEPTED"`、
 * 货主撤销按钮写 `(status == "PENDING_DISPATCH" || status == "DISPATCHED")`、
 * 司机接单写 `status == "DISPATCHED"`……而**真源在后端**（`order_flow.py` / `orders.py` 的状态门）。
 * 真源改了、字面量没跟着改，表现不是报错，而是：
 * - **界面少一个按钮**（点了本来能成的操作没入口）；
 * - 或者**多一个按钮**（点了必然 400，用户以为系统坏了）。
 *
 * 实测抓到的一例：派单员撤回派单的按钮只认 `ACCEPTED`，而后端 `recall_dispatch` 允许
 * `(DISPATCHED, ACCEPTED)` —— 于是**派错司机的第一时间撤不回来**，必须等司机先点接单
 * （司机不接就永远撤不回来），而这段时间正是最需要改派的时候。
 *
 * ### 判据怎么保持同源
 * 静态红线 `_tools/qa/_check_client_contract.py` 从**后端源码**解析每个动作允许的状态集合，
 * 与本文件的集合逐值对账；少一档/多一档都红。改了后端状态门就必须同步改这里。
 *
 * ⚠️ 中文名**不在这里**：本项目目前存在两套中文口径（`docs/DOMAIN_MODEL.md` 与 H5 用
 * 「派单中 = PENDING_DISPATCH」，AI 卡片与 App 列表用「待派单 = PENDING_DISPATCH」），
 * 统一口径是**用户要拍的板**（见 `_archive/audit/FINDINGS.md` §待拍板），
 * 本文件只承载"能不能做"，不承载"叫什么"。
 */
object OrderStatusModel {

    /** 后端 `backend/app/models/enums.py::OrderStatus` 的全部取值（少一个＝那一档在客户端"查无此单"）。 */
    val ALL: List<String> = listOf(
        "PENDING_DISPATCH",
        "DISPATCHED",
        "ACCEPTED",
        "DELIVERED",
        "CANCELLED",
        // 已退货（2026-09-20）：货物送达之后客户又把货退回来。⛔ 与「已撤销」是两回事
        // （撤销＝这单没发生过；退货＝单发生过、事后货退回来了），后端也是两个枚举值。
        "RETURNED",
    )

    /**
     * 可退货：后端 `services/order_return.py::return_order` 只认「已送达」。
     * 货还没送到的单要走「撤销」（那条路不动钱、不动库存，只把还没发生的单作废）。
     */
    val RETURNABLE: Set<String> = setOf("DELIVERED")

    /** 撤销整单：后端 `order_flow.cancel_pending`（货主/派单员共用同一对取值）。 */
    val CANCELLABLE: Set<String> = setOf("PENDING_DISPATCH", "DISPATCHED")

    /** 撤回派单（回到待派单）：后端 `order_flow.recall_dispatch`。 */
    val RECALLABLE: Set<String> = setOf("DISPATCHED", "ACCEPTED")

    /** 派单/拆分：后端 `order_flow.assign_driver` 的 CAS 与拆单的状态门。 */
    val ASSIGNABLE: Set<String> = setOf("PENDING_DISPATCH")

    /** 改商品行：后端 `order_products._order_allows_line_edit`。 */
    val LINE_EDITABLE: Set<String> = setOf("PENDING_DISPATCH", "DISPATCHED", "ACCEPTED")

    /** 司机确认接单：后端 `orders.driver_ack_view`。 */
    val ACKABLE: Set<String> = setOf("DISPATCHED")

    /** 司机提交送达：后端 `order_flow.complete_delivery`。 */
    val COMPLETABLE: Set<String> = setOf("ACCEPTED")

    /** 改订单外围信息（地址/电话/备注）：后端 `orders.update_order` 只拒「已送达/已撤销」。 */
    val EDITABLE: Set<String> = setOf("PENDING_DISPATCH", "DISPATCHED", "ACCEPTED")

    /**
     * **货主**在**界面上**能把单移进回收站的状态：后端 `orders.delete_cancelled_order`
     * （`role == shipper` 时 `status not in (CANCELLED, DELIVERED) → 400`）。
     *
     * ⛔ 「异常」**不是**通行证（2026-09-19 审计）：原来后端那个 `and not is_exception`
     * 让被标过异常的在途单也能删 —— 一删，司机端列表里它直接消失，
     * 司机拿着打不开的单跑车，到现场发现单子没了、也拿不到钱。
     * 这是**后端授权的上限**（界面订单详情页的 `canDelete` 用它）；
     * ⚠️ AI 侧比它**更严**，见 [SHIPPER_AI_DELETABLE] —— 两处不要混，理由写在那边。
     * **派单员不适用**（他能删任意状态，含待派单）。
     */
    val SHIPPER_DELETABLE: Set<String> = setOf("CANCELLED", "DELIVERED")

    /**
     * **AI** 能替货主删的状态 —— 比界面**更严**：只认「已撤销」。
     *
     * ### 用户 2026-09-21 的原话（口述）
     * > 「他**不能删他的订单**……凡事有关订单信息，他的 AI 是不能做的。
     * >   货主和批发商都一样，**除非是那个已撤销的订单信息，这个是可以删的**。」
     *
     * ### 为什么 AI 要比界面严一档（这条不是洁癖）
     * 「已送达」是**已经发生过的一趟生意**：它有账本流水、司机账单、库存扣减、
     * 可能还有收款记录挂在同一张单上。软删它只是"看不见"，但用户对 AI 说的是一句
     * 「把这单删了」——他多半以为那是"这条记录没用了"，而不是"把一趟生意从列表里拿掉"。
     * 「已撤销」不一样：那趟生意**本来就没发生**，删掉只是把一条废记录清走。
     * ⛔ 所以 AI 侧不给「已送达」这条路；**界面上那个按钮仍然保留**（那是用户自己点、
     *    自己看得见上下文，且这一档是 2026-09-04 定过的数据保留策略）。
     */
    val SHIPPER_AI_DELETABLE: Set<String> = setOf("CANCELLED")

    /** 可改运费：后端 `orders.update_order_freight` 只拒「已送达/已撤销」（`in (DELIVERED, CANCELLED)`）。 */
    val FREIGHT_EDITABLE: Set<String> = setOf("PENDING_DISPATCH", "DISPATCHED", "ACCEPTED")

    /**
     * 「只拒已撤销」的这一档：后端 `orders._payment_scoped_order`（收款/挂账）的判据是
     * `status == CANCELLED → 400`，允许集就是"除已撤销以外全部"。
     * 标异常沿用同一档（`PATCH /orders/{id}/exception` 后端**没有**状态门，客户端比它更严一点，
     * 理由：给一张已撤销的单标"异常待处理"会把它推进待处理列表，而那件事已经不存在了）。
     */
    val NOT_CANCELLED: Set<String> =
        setOf("PENDING_DISPATCH", "DISPATCHED", "ACCEPTED", "DELIVERED")

    /**
     * 司机端「进行中」列表 = **已派单（还没接）+ 已接单**。
     * 只查 ACCEPTED 会让新派来的单在司机端根本不出现（司机看不到、接不了，这一趟卡死）。
     * 它必须**至少覆盖** [ACKABLE] ∪ [COMPLETABLE]，否则司机进不了"接单"或"送达"这两帧。
     */
    val DRIVER_OPEN: List<String> = listOf("DISPATCHED", "ACCEPTED")
}
