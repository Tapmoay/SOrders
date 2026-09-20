package com.tapmoay.sorders.ai

import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import java.math.BigDecimal

/**
 * 「我的账本」两个手写处理器：**核销**与**撤销核销**（恢复走 [restoreAction] 的声明式路径）。
 *
 * ## 为什么这两个必须手写（不能走声明式 CRUD）
 * 1. **核销写的是新的一条**，金额得按"这一行还可核销多少"算出来——声明式那一套收的是
 *    "一条已有记录 + 要改的字段"，形状对不上；
 * 2. **普通货主没有这本账**：`prepare` 里先问一句 `is_member`，不是批发商就**不发卡**
 *    （发一张点了必然 403 的卡，是这个项目明确列为最坏的一类 bug）。
 *
 * ## 两张卡上都必须有的一句话
 * 「只记在你自己这一本账上，公司那边的账不变」——用户最怕的就是"我在这儿点一下，
 * 公司账跟着变了"。见 [SETTLE_LINES]。
 */
private val SETTLE_LINES = listOf(
    "只记在你自己这一本账上：公司（派单员）那边的账一个数字都不会变，",
    "也不会把这一单标成「已收款」——那笔钱是他向你要的，跟这一笔是两回事。",
)

/** 我的账本：核销一笔（整单 / 按商品）。 */
class SettleMyLedgerHandler(
    private val ds: AiWriteDataSource,
    private val store: AiWritePreviewStore,
) : AiWriteHandler {

    override val actionId = AiWrites.MY_LEDGER_SETTLE

    override suspend fun prepare(params: JsonObject): AiWriteOutcome {
        requireMemberShipper(ds)

        val orderNo = AiWriteArgs.required(
            params,
            "order_no",
            "是哪一张单？把**完整单号**告诉我（如 SO202609201234567890）。",
        ).trim()

        val order = ds.mySettleOrder(orderNo)
            ?: throw AiWriteArgException(
                "在你自己的订单里没找到单号「$orderNo」。" +
                    "请让用户确认单号（要写全），或者换个说法（如「上周送到罗伟东那单」）——" +
                    "**不要拿别的单顶替**。",
            )

        // 归属核对：用户说了是谁的单，就得**真的是他的**。
        // 核错人对用户来说是"钱记到别人头上"，而这种事要到对账那天才会被发现。
        AiWriteArgs.str(params, "customer")?.trim()?.takeIf { it.isNotEmpty() }?.let { want ->
            if (AiWriteArgs.norm(want) != AiWriteArgs.norm(order.customer)) {
                throw AiWriteArgException(
                    "订单 $orderNo 的货主是「${order.customer}」，不是「$want」。" +
                        "请让用户确认是不是记错了单——我不会把这一笔记到别人头上。",
                )
            }
        }

        val statusCn = order.statusCn()
        if (order.status != "DELIVERED") {
            throw AiWriteArgException(
                "订单 $orderNo 现在是「$statusCn」，不能核销。" +
                    if (order.status == "RETURNED") {
                        "整单退货之后货款已经冲平了，没有可收的钱。"
                    } else {
                        "货还没送到客户手上时这笔应收还不存在——送达之后再说。"
                    },
            )
        }

        // 按商品核销：把用户点名的商品在这张单里对上（对不上/多义就**拒绝并列候选**，不自己挑）
        val pickedNames = AiWriteArgs.str(params, "products")
            ?.split(',', '，', '、')
            ?.map { it.trim() }
            ?.filter { it.isNotEmpty() }
            .orEmpty()

        val picked = if (pickedNames.isEmpty()) {
            order.lines.filter { it.remaining > BigDecimal.ZERO }
        } else {
            pickedNames.map { raw ->
                val hit = order.lines.filter { AiWriteArgs.norm(it.name).contains(AiWriteArgs.norm(raw)) }
                when {
                    hit.isEmpty() -> throw AiWriteArgException(
                        "订单 $orderNo 里没有叫「$raw」的商品。这一单是：" +
                            order.lines.joinToString("、") { it.name } +
                            "。请让用户说清楚要核哪几样。",
                        candidates = order.lines.map { it.name },
                    )
                    hit.size > 1 -> throw AiWriteArgException(
                        "「$raw」在这一单里对上了 ${hit.size} 样商品（" +
                            hit.joinToString("、") { it.name } + "），请让用户说全名。",
                        candidates = hit.map { it.name },
                    )
                    hit.first().remaining <= BigDecimal.ZERO -> throw AiWriteArgException(
                        "「${hit.first().name}」这一样已经收齐了，不用再核销。",
                    )
                    else -> hit.first()
                }
            }
        }

        if (picked.isEmpty()) {
            throw AiWriteArgException("订单 $orderNo 已经核销完了（这一单没有还可核销的金额）。")
        }

        val amount = picked.fold(BigDecimal.ZERO) { a, l -> a + l.remaining }
        val method = methodOf(params)

        return AiWriteOutcome.NeedConfirm(
            store.offer(
                actionId = actionId,
                title = AiWrites.titleOf(actionId),
                risk = AiWrites.byId(actionId)!!.risk,
                summary = "核销：订单 $orderNo 的 ${AiWriteArgs.money(amount)} 元（${order.customer}）",
                detailLines = buildList {
                    add("订单：$orderNo（$statusCn）")
                    add(
                        "货主：${order.customer}" +
                            if (order.customerPhone.isBlank()) "" else "（${order.customerPhone}）"
                    )
                    add("———— 这一笔核的是 ————")
                    picked.forEach { l ->
                        add(
                            "· ${l.name}：${AiWriteArgs.money(l.remaining)} 元" +
                                if (l.settled > BigDecimal.ZERO) {
                                    "（这一样原本 ${AiWriteArgs.money(l.receivable)}，已核销过 ${AiWriteArgs.money(l.settled)}）"
                                } else {
                                    ""
                                }
                        )
                    }
                    if (pickedNames.isEmpty()) {
                        add("（没有点名商品 = **整单核销**：这一单还欠的全收）")
                    } else {
                        add("（按商品核销：只核上面这几样，其余还挂着）")
                    }
                    add("本次合计：${AiWriteArgs.money(amount)} 元 · 收款方式：$method")
                    add("———— 这一笔不碰什么 ————")
                    addAll(SETTLE_LINES)
                },
                payload = buildJsonObject {
                    put("order_id", order.id)
                    put("order_no", orderNo)
                    put("customer", order.customer)
                    put("amount", AiWriteArgs.money(amount))
                    put("method", method)
                    AiWriteArgs.str(params, "note")?.trim()?.takeIf { it.isNotEmpty() }?.let { put("note", it) }
                    if (pickedNames.isNotEmpty()) {
                        // 逐行金额由**这里**算好（与卡片上印的是同一个数）：提交时不再重算，
                        // 否则"用户看到的"和"真正写进去的"就成了两条路径。
                        put(
                            "lines",
                            buildJsonArray {
                                picked.forEach { l ->
                                    add(
                                        buildJsonObject {
                                            put("order_product_id", l.id)
                                            put("amount", AiWriteArgs.money(l.remaining))
                                        }
                                    )
                                }
                            },
                        )
                    }
                },
            ),
        )
    }

    override suspend fun commit(payload: JsonObject, idempotencyKey: String) {
        val lines = (payload["lines"] as? kotlinx.serialization.json.JsonArray)
            ?.mapNotNull { it as? JsonObject }
            ?.map { it.reqLong("order_product_id") to (it.str("amount") ?: "0") }
            .orEmpty()
        ds.createMySettlement(
            orderId = payload.reqLong("order_id"),
            lines = lines,
            method = payload.str("method") ?: "cash",
            note = payload.str("note") ?: "",
        )
    }

    private fun methodOf(params: JsonObject): String {
        val raw = AiWriteArgs.str(params, "method")?.trim()?.lowercase()?.takeIf { it.isNotEmpty() }
            ?: return "cash"
        if (raw !in AiWriteShipperLedger.METHODS) {
            throw AiWriteArgException(
                "收款方式只认 ${AiWriteShipperLedger.METHODS.joinToString(" / ")}，你说的「$raw」不在里面。",
            )
        }
        return raw
    }
}

/** 我的账本：撤销一笔核销（软删，可恢复）。 */
class RevokeMySettlementHandler(
    private val ds: AiWriteDataSource,
    private val store: AiWritePreviewStore,
) : AiWriteHandler {

    override val actionId = AiWrites.MY_LEDGER_REVOKE

    override suspend fun prepare(params: JsonObject): AiWriteOutcome {
        requireMemberShipper(ds)

        val orderNo = AiWriteArgs.required(
            params,
            "order_no",
            "要撤哪一张单的核销？把**完整单号**告诉我。",
        ).trim()
        val order = ds.mySettleOrder(orderNo)
            ?: throw AiWriteArgException(
                "在你自己的订单里没找到单号「$orderNo」，请让用户确认单号（要写全）。",
            )

        val all = ds.mySettlements(order.id).filter { !it.isDeleted }
        if (all.isEmpty()) {
            throw AiWriteArgException("订单 $orderNo 还没有记过核销，没有可撤销的。")
        }

        // 同一单记过多笔时**让用户自己挑**（用金额区分），不许自己挑一笔
        val amountWant = AiWriteArgs.str(params, "amount")
            ?.let { AiWriteArgs.parseMoney(it, "amount", mustPositive = true) }
        val pool = amountWant?.let { a -> all.filter { it.amount.toBigDecimalOrNull()?.compareTo(a) == 0 } } ?: all
        val target = when {
            pool.isEmpty() -> throw AiWriteArgException(
                "订单 $orderNo 记过的核销里没有 ${AiWriteArgs.money(amountWant!!)} 元那一笔。这几笔是：" +
                    all.joinToString("；") { it.label() } + "。请让用户指认是哪一笔。",
                candidates = all.map { it.label() },
            )
            pool.size > 1 -> throw AiWriteArgException(
                "订单 $orderNo 记过 ${pool.size} 笔一样金额的核销，撤销要指认是哪一笔：" +
                    pool.joinToString("；") { it.label() } + "。请让用户补一句（时间或收款方式）。",
                candidates = pool.map { it.label() },
            )
            else -> pool.first()
        }

        return AiWriteOutcome.NeedConfirm(
            store.offer(
                actionId = actionId,
                title = AiWrites.titleOf(actionId),
                risk = AiWrites.byId(actionId)!!.risk,
                summary = "撤销核销：订单 $orderNo 的 ${target.amount} 元（${target.customer}）",
                detailLines = buildList {
                    add("订单：$orderNo")
                    add("这笔核销：${target.label()}")
                    add("涉及的商品：" + target.productNames().ifBlank { "（整单）" })
                    add("———— 撤销之后 ————")
                    add("这一笔从「已收」里撤掉，那一单又变成「还欠我钱」")
                    add("记录不会消失（后台是伪删除），执行完这条消息上会出现「撤回」，点了就放回来")
                    addAll(SETTLE_LINES)
                },
                payload = buildJsonObject {
                    put("settlement_id", target.id)
                    put("order_no", orderNo)
                    put("amount", target.amount)
                    put("customer", target.customer)
                },
            ),
        )
    }

    override suspend fun commit(payload: JsonObject, idempotencyKey: String) {
        ds.revokeMySettlement(payload.reqLong("settlement_id"))
    }
}

// ---------------------------------------------------------------- 共用小工具

/**
 * 只有**批发商货主**才有这本账。
 *
 * 为什么在 `prepare` 里拦而不是靠角色门：两种货主是**同一个角色**（`shipper`），
 * 角色门分不出来；而"发一张点了必然 403 的卡"是这个项目明确列为最坏的一类 bug。
 */
private suspend fun requireMemberShipper(ds: AiWriteDataSource) {
    if (!ds.isMemberShipper()) {
        throw AiWriteArgException(
            "你这个账号是**普通货主**，没有「给货主核销」这本账 —— " +
                "普通货主是给自己下单、收自己的货，没有第二个债务人。" +
                "（如果你是替别人下单的批发商，请让派单员在「货主管理」里把你设成批发商。）",
        )
    }
}
