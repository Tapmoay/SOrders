package com.tapmoay.sorders.ui.common

import com.tapmoay.sorders.core.ReturnRules
import com.tapmoay.sorders.data.remote.dto.OrderProductDto
import com.tapmoay.sorders.data.remote.dto.ReturnRequestDto

/**
 * 「改这张退货申请」的**纯逻辑**（2026-10-15 CHG-0130）—— 没有 Compose、没有网络，所以能直接单测。
 *
 * 用户口径：「退货是可以改的…主要改的是退货的商品…商品种类、商品数量，派单员可以更改，
 * 货主和批发商他们也是可以进行更改的」「改完之后只会重新发个信息给派单员说此退货订单发生了改动」。
 *
 * 这里只放**判据与文案**，两端（派单端 / 货主端）共用同一份；界面在
 * [com.tapmoay.sorders.ui.common.ReturnRequestAmendDialog]，状态在
 * [ReturnRequestsViewModel] 的 amend 那一组字段里（同样是两端共用一份）。
 */

/** 改明细的人：派单员。发通知时"另外两方"就是货主与批发商。 */
const val AMEND_ACTOR_DISPATCHER = "dispatcher"

/** 改明细的人：货主 / 批发商（后端两边都记 `shipper` —— 都是买货那一侧）。 */
const val AMEND_ACTOR_SHIPPER = "shipper"

/**
 * 这张申请现在能不能改。
 *
 * 规则（与后端 `_check_pending` 同一口径，⛔ 别在界面上另立一套）：
 * **只要派单员还没确认**（申请还是待处理）三方都能改；已办理 / 已驳回 / 已自动关闭 / 已撤回
 * 都是终点，改不了 —— 终态就是终态。
 *
 * ⚠️ 这个函数同时管两件事，是刻意的：派单端用它决定"待办里这张单能不能改"，
 *    货主端用它决定"我的退货申请里这张单要不要露出改动入口"。两端的判据必须一模一样，
 *    否则会出现"一边能点、一边点进去被后端拒"的错觉。
 */
fun canAmendReturnRequest(req: ReturnRequestDto): Boolean = req.isPending

/**
 * 这一行最多还能退几件 —— 直接调**全仓唯一那份**可退规则 [ReturnRules.maxReturnable]。
 *
 * ⛔ 不要在 amend 里另写一遍 `下单 − 货损 − 已退`：这条规则已经有三处消费点
 *    （填数量块的上限、AI 确认卡、账本页），改明细是第四处，多一份就会多一种口径。
 */
fun amendMaxReturnable(line: OrderProductDto): Int =
    ReturnRules.maxReturnable(line.quantity, line.damageQuantity, line.returnedQuantity)

/** 勾中的行（按订单行的原顺序）——提交给后端的就这几行，其余行等于"不要了"。 */
fun amendPickedIds(lines: List<OrderProductDto>, qty: Map<Long, Int>): List<Long> =
    lines.filter { (qty[it.id] ?: 0) > 0 }.map { it.id }

/**
 * 改完之后长什么样，一句话（与后端 `lines_summary`、与申请单上的 `linesSummary` 同一个形状：
 * `商品名×数量` 用「、」连）。空 = 一行都没留。
 */
fun amendPickedSummary(lines: List<OrderProductDto>, qty: Map<Long, Int>): String =
    lines.filter { (qty[it.id] ?: 0) > 0 }
        .joinToString("、") { "${it.productNameSnapshot}×${qty[it.id]}" }

/**
 * 改完只发**一条**通知，这句话就是给用户看的那条：发给谁、有几条。
 *
 * 用户口径要的就是"只发一条"（「只不过我们会发个通知」「只会重新发个信息给派单员」），
 * 所以文案里把"一条"说出来 —— 免得用户以为改一次数量就刷屏一次。
 */
fun amendNoticeLine(actorRole: String): String =
    if (actorRole == AMEND_ACTOR_DISPATCHER) {
        "改完只发一条通知给货主和批发商：他看到的会是「原来是…现在是…」。"
    } else {
        // 「此退货订单发生了改动」是用户自己的原话（2026-10-15），照它说 ——
        // 括号里那句是派单员那边实际收到的内容（后端 `publish_return_request_amended`）。
        "改完只发一条通知给派单员：此退货订单发生了改动" +
            "（他看到的会是「原来是…现在是…」，并按新的数量办理）。"
    }

/** 改成功后的提示（Snackbar）：现在是哪几行、通知发给谁。⛔ 不写"一切顺利"这种空话。 */
fun amendDoneMessage(actorRole: String, after: String): String {
    val now = after.ifBlank { "（一行都没留）" }
    val who = if (actorRole == AMEND_ACTOR_DISPATCHER) "货主和批发商" else "派单员"
    // ⚠️ 后面要紧跟中文时必须写 ${who}：Kotlin 的标识符允许 CJK 字符，
    //    `$who发一条通知` 会被整个当成一个变量名（编译期报 Unresolved reference）。
    return "改好了：现在是 $now。已给${who}发一条通知。"
}

/**
 * 提交前先在本地拦一道（后端那两道仍然在，客户端**不替代**它）：
 * 空明细、行数超上限都别白跑一次网络。
 *
 * 返回 null = 可以提交；否则是要显示在弹层底部的中文。
 */
fun amendSubmitError(lines: List<OrderProductDto>, qty: Map<Long, Int>): String? {
    val picked = amendPickedIds(lines, qty)
    return when {
        picked.isEmpty() ->
            "至少要留一行商品、数量大于 0 —— 一行都不要就变成撤销申请了，那要走「撤回申请」。"
        picked.size > AMEND_MAX_LINES ->
            "一次最多改 $AMEND_MAX_LINES 行商品，请分几次改。"
        else -> null
    }
}

/** 后端 `ReturnRequestAmendBody.items` 的上限（`min_length=1, max_length=20`）。 */
const val AMEND_MAX_LINES = 20
