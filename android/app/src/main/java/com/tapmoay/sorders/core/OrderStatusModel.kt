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
    )

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
