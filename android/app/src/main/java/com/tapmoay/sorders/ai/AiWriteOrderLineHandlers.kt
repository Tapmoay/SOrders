package com.tapmoay.sorders.ai

import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import java.math.BigDecimal
import java.math.RoundingMode

/**
 * 订单域的第三批：**商品行**（加/改/删）与**回收站**（移入/恢复）。
 *
 * ### 商品行与"改单"的分工
 * 「改单」改的是地址、电话、备注这些**外围信息**；商品行改的是**货本身**。
 * 两者共用同样的状态门（待派单 / 派单中 / 已接单），因为后端就是这么定的
 * （`_order_allows_line_edit`）。
 *
 * ### 为什么商品行的卡片必须算"金额从多少变成多少"
 * 行改了，订单金额就跟着变——而**钱是这个系统里最容易被忽略的连带后果**：
 * 用户只说了"少两件"，他不会想到司机运费按单量结、账本按金额入账。
 * 卡片把前后金额都算出来，他才有机会发现"这不是我要的"。
 */

/** 商品行三个动作共用的骨架：查单 → 核对状态 → 定位行。 */
abstract class OrderLineWriteHandler(
    protected val ds: AiWriteDataSource,
    protected val store: AiWritePreviewStore,
) : AiWriteHandler {

    /** 与订单处理器同一套状态门（后端 `_order_allows_line_edit` 的取值）。 */
    protected suspend fun resolveEditableOrder(params: JsonObject): AiOrderRef {
        val ref = AiWriteArgs.required(params, "order", "是哪一张订单？把订单号告诉我。")
        val hits = ds.findOrders(ref, OrderWriteHandler.ORDER_PROBE_LIMIT)
        val q = AiWriteArgs.normCode(ref)
        val exact = hits.filter { AiWriteArgs.normCode(it.orderNo) == q }
        val pool = if (exact.isNotEmpty()) exact else hits
        val order = when {
            pool.isEmpty() -> throw AiWriteArgException(
                "没找到订单「$ref」。请让用户确认单号（他说的可能不是单号），或先查一下再问。",
            )
            pool.size == 1 -> pool.first()
            else -> throw AiWriteArgException(
                "「$ref」对上了多张订单：${pool.take(AiWriteArgs.MAX_CANDIDATES).joinToString("、") { it.label() }}。" +
                    "请让用户说清楚是哪一张，**不要自己挑一个**。",
                candidates = pool.take(AiWriteArgs.MAX_CANDIDATES).map { it.label() },
            )
        }
        if (order.statusCn !in EDITABLE_STATUSES) {
            throw AiWriteArgException(
                "这单现在是「${order.statusCn}」，**已送达或已撤销的单不能改商品明细**。" +
                    "请如实告诉用户，不要换一张单去操作。",
            )
        }
        return order
    }

    /** 订单里的一行：按商品名对，对不上或对上多行就拒绝。 */
    protected suspend fun resolveLine(order: AiOrderRef, keyword: String): AiOrderLine {
        val lines = ds.orderLines(order.id)
        if (lines.isEmpty()) {
            throw AiWriteArgException("这张订单现在**没有任何商品行**，没法按名字找。请让用户先确认要哪一张单。")
        }
        val key = AiWriteArgs.norm(keyword)
        val pool = lines.filter { AiWriteArgs.norm(it.product).contains(key) }
        return when {
            pool.isEmpty() -> throw AiWriteArgException(
                "这单里没有商品名像「$keyword」的行。它现在有这些行，请让用户挑一行：\n" +
                    lines.joinToString("\n") { "· " + it.label() },
                candidates = lines.map { it.label() },
            )
            pool.size == 1 -> pool.first()
            else -> throw AiWriteArgException(
                "「$keyword」在这单里对上了 ${pool.size} 行，删错/改错一行金额就跟着错。" +
                    "请让用户说清楚是哪一行：\n" + pool.joinToString("\n") { "· " + it.label() },
                candidates = pool.map { it.label() },
            )
        }
    }

    protected fun card(summary: String, details: List<String>, payload: JsonObject): AiWriteOutcome =
        AiWriteOutcome.NeedConfirm(
            store.offer(
                actionId = actionId,
                title = AiWrites.titleOf(actionId),
                risk = AiWrites.byId(actionId)!!.risk,
                summary = summary,
                detailLines = details,
                payload = payload,
            ),
        )

    protected fun orderLines(o: AiOrderRef): List<String> = buildList {
        add("订单号：${o.orderNo}")
        add("货主：${o.shipper.ifBlank { "（未填）" }}")
        add("当前状态：${o.statusCn}")
        add("当前金额：${o.amount} 元")
    }

    /** 金额加减（两位小数）。 */
    protected fun money(v: BigDecimal): String = v.setScale(2, RoundingMode.HALF_UP).toPlainString()

    protected fun amountOf(o: AiOrderRef): BigDecimal = o.amount.toBigDecimalOrNull() ?: BigDecimal.ZERO

    protected companion object {
        val EDITABLE_STATUSES = setOf("待派单", "派单中", "已接单")
    }
}

// ============================================================== 加一行商品

/**
 * 加一行商品。
 *
 * 单价不给就按**商品库里的默认价**补——但要在卡片上写明"这是按商品库取的"，
 * 让用户有机会改。商品库里没有这个名字时**不去猜价**，而是让用户给一个。
 */
class AddOrderLineHandler(
    ds: AiWriteDataSource,
    store: AiWritePreviewStore,
) : OrderLineWriteHandler(ds, store) {

    override val actionId = AiWrites.ORDERS_ADD_LINE

    override suspend fun prepare(params: JsonObject): AiWriteOutcome {
        val order = resolveEditableOrder(params)
        val name = AiWriteArgs.required(params, "product", "要加什么货？把商品名告诉我。")
        val product = AiWriteArgs.text(name, "商品名", max = 60)
        val qty = AiWriteArgs.parseQuantity(
            AiWriteArgs.required(params, "quantity", "加几件？"),
        )
        if (qty <= 0) throw AiWriteArgException("件数要大于 0。")

        val typed = AiWriteArgs.str(params, "unit_price")
        // 用户没给价就按**商品库的默认价**补；库里没有这个商品就**不猜价**。
        val known = if (typed == null) {
            ds.productPrices().firstOrNull { it.name.trim().equals(product.trim(), ignoreCase = true) }
        } else {
            null
        }
        val unitPrice: BigDecimal = when {
            typed != null -> AiWriteArgs.parseMoney(typed, "unit_price", mustPositive = false)
            known != null -> known.defaultPrice.toBigDecimalOrNull()
                ?: throw AiWriteArgException("商品库里取不到「$product」的默认价，请让用户直接说一件多少钱。")

            else -> throw AiWriteArgException(
                "商品库里没有叫「$product」的商品，我也没法猜单价。请让用户说一件多少钱。",
            )
        }
        val lineTotal = unitPrice.multiply(BigDecimal(qty))

        return card(
            summary = "加一行商品：${order.orderNo} ＋$product × $qty",
            details = buildList {
                addAll(orderLines(order))
                add("———— 加这一行 ————")
                add("商品：$product")
                add("数量：$qty 件")
                add("单价：${money(unitPrice)} 元/件" + if (typed == null) "（按商品库的默认价取的）" else "")
                add("小计：${money(lineTotal)} 元")
                add("———— 金额变化 ————")
                add("订单金额：${order.amount} → ${money(amountOf(order).add(lineTotal))} 元")
            },
            payload = buildJsonObject {
                put("order_id", order.id)
                put("product", product)
                put("quantity", qty.toString())
                put("unit_price", unitPrice.toPlainString())
            },
        )
    }

    override suspend fun commit(payload: JsonObject, idempotencyKey: String) {
        ds.addOrderLine(
            orderId = payload.reqLong("order_id"),
            product = payload.req("product"),
            quantity = payload.req("quantity").toInt(),
            unitPrice = payload.req("unit_price"),
        )
    }
}

// ============================================================== 改一行商品

class UpdateOrderLineHandler(
    ds: AiWriteDataSource,
    store: AiWritePreviewStore,
) : OrderLineWriteHandler(ds, store) {

    override val actionId = AiWrites.ORDERS_UPDATE_LINE

    override suspend fun prepare(params: JsonObject): AiWriteOutcome {
        val order = resolveEditableOrder(params)
        val keyword = AiWriteArgs.required(params, "product", "要改哪一行？把那一行的商品名告诉我。")
        val line = resolveLine(order, keyword)

        val newQty = AiWriteArgs.str(params, "quantity")?.let { AiWriteArgs.parseQuantity(it) }
        val newPrice = AiWriteArgs.str(params, "unit_price")?.let {
            AiWriteArgs.parseMoney(it, "unit_price", mustPositive = false)
        }
        val newName = AiWriteArgs.str(params, "new_product")?.trim()?.takeIf { it.isNotEmpty() }
            ?.let { AiWriteArgs.text(it, "商品名", max = 60) }

        if (newQty == null && newPrice == null && newName == null) {
            throw AiWriteArgException(
                "你还没说要改成什么。这一行可以改：数量、单价、商品名。请让用户说清楚改哪一项、改成多少。",
            )
        }
        if (newQty != null && newQty <= 0) throw AiWriteArgException("数量要大于 0；要清零请用「删一行商品」。")

        val qty = newQty ?: line.quantity
        val price = newPrice ?: (line.unitPrice.toBigDecimalOrNull() ?: BigDecimal.ZERO)
        val newTotal = price.multiply(BigDecimal(qty))
        val oldTotal = line.lineTotal.toBigDecimalOrNull() ?: BigDecimal.ZERO

        return card(
            summary = "改一行商品：${order.orderNo} ${line.product}",
            details = buildList {
                addAll(orderLines(order))
                add("———— 这一行 ————")
                add("商品：${line.product}${if (newName != null) " → $newName" else ""}")
                if (newQty != null) add("数量：${line.quantity} → $newQty")
                if (newPrice != null) add("单价：${line.unitPrice} → ${money(newPrice)}")
                add("小计：${line.lineTotal} → ${money(newTotal)} 元")
                add("———— 金额变化 ————")
                add("订单金额：${order.amount} → ${money(amountOf(order).subtract(oldTotal).add(newTotal))} 元")
            },
            payload = buildJsonObject {
                put("line_id", line.id)
                newName?.let { put("product_name", it) }
                if (newQty != null) put("quantity", newQty.toString())
                if (newPrice != null) put("unit_price", newPrice.toPlainString())
            },
        )
    }

    override suspend fun commit(payload: JsonObject, idempotencyKey: String) {
        ds.updateOrderLine(payload.reqLong("line_id"), payload)
    }
}

// ============================================================== 删一行商品

/**
 * 删一行商品。
 *
 * 为什么它比"改"高一档（HIGH）：**删掉就没了**，而"改错"还能再改回来。
 * 而且用户说"这货不要了"时，往往没意识到金额、运费、账本都会跟着变——
 * 卡片要把删掉之后的订单金额算给他看。
 */
class DeleteOrderLineHandler(
    ds: AiWriteDataSource,
    store: AiWritePreviewStore,
) : OrderLineWriteHandler(ds, store) {

    override val actionId = AiWrites.ORDERS_DELETE_LINE

    override suspend fun prepare(params: JsonObject): AiWriteOutcome {
        val order = resolveEditableOrder(params)
        val keyword = AiWriteArgs.required(params, "product", "要删哪一行？把那一行的商品名告诉我。")
        val line = resolveLine(order, keyword)
        val lines = ds.orderLines(order.id)
        val left = amountOf(order).subtract(line.lineTotal.toBigDecimalOrNull() ?: BigDecimal.ZERO)
        val empty = lines.size <= 1

        return card(
            summary = "删一行商品：${order.orderNo} −${line.product}",
            details = buildList {
                addAll(orderLines(order))
                add("———— 删掉这一行 ————")
                add("商品：${line.label()}")
                add("———— 金额变化 ————")
                add("订单金额：${order.amount} → ${money(left)} 元")
                if (empty) {
                    add("⚠️ 这是最后一行商品：删完这张订单就没有货了（订单本身还在）")
                }
                add("删掉之后只能重新加一行，撤不回来")
            },
            payload = buildJsonObject { put("line_id", line.id) },
        )
    }

    override suspend fun commit(payload: JsonObject, idempotencyKey: String) {
        ds.deleteOrderLine(payload.reqLong("line_id"))
    }
}

// ============================================================== 移入回收站 / 恢复

/**
 * 把订单移进回收站（软删）。
 *
 * 为什么卡片必须写"30 天内可恢复"：用户按下去的那一刻，这单子就从**所有人**的列表里
 * 消失了（货主、司机、内勤都看不到）。如果他不确定这是不是"永久删除"，就会不敢用；
 * 反过来，他要是以为是永久删除，就会去做更危险的事。
 * 说清"可恢复 + 到期物理清理"，他才能做对决定。
 */
class SoftDeleteOrderHandler(
    ds: AiWriteDataSource,
    store: AiWritePreviewStore,
) : OrderWriteHandler(ds, store) {

    override val actionId = AiWrites.ORDERS_SOFT_DELETE

    override suspend fun prepare(params: JsonObject): AiWriteOutcome {
        val order = resolveOrder(params)
        return card(
            summary = "移入回收站：${order.orderNo}",
            details = buildList {
                addAll(orderLines(order))
                add("———— 移入之后 ————")
                add("这单从所有人的列表里消失（货主、司机、内勤都看不到）")
                add("${AiWrites.RECYCLE_DAYS} 天内可以恢复（在订单回收站里），到期系统才会物理清理")
                add("订单的账目、消息记录不会跟着删")
            },
            payload = buildJsonObject { put("order_id", order.id) },
        )
    }

    override suspend fun commit(payload: JsonObject, idempotencyKey: String) {
        ds.softDeleteOrder(payload.reqLong("order_id"))
    }

    /**
     * ⚠️ v3.27 起**这里不再手写撤回**：撤回只有一处（[AiRevert] + [AiResources]）。
     * 软删 ↔ 从回收站恢复现在只是那边的一行 `delete(...)` + `restore = ...` 声明。
     *
     * 顺带多出来一件事：**「撤回的撤回」现在真的存在**——`orders.restore` 自己也声明了
     * 逆操作（再移入回收站一次），所以撤回执行完那条消息上还会再挂一个撤回入口。
     * 这不是特意做的，是"撤回＝普通动作"这个形状白送的。
     */
}

/**
 * 从回收站恢复订单（仅派单员）。
 *
 * 定位方式与其它订单动作**不同**：它必须在**回收站**里找（普通查询看不到软删的单）。
 * 所以这里不复用 `resolveOrder`，而是走 `findDeletedOrders`。
 */
class RestoreOrderHandler(
    ds: AiWriteDataSource,
    store: AiWritePreviewStore,
) : OrderWriteHandler(ds, store) {

    override val actionId = AiWrites.ORDERS_RESTORE

    override suspend fun prepare(params: JsonObject): AiWriteOutcome {
        val ref = AiWriteArgs.required(params, "order", "要恢复哪一张订单？把订单号告诉我。")
        if (AiWriteArgs.normCode(ref).length < MIN_REF_CHARS) {
            throw AiWriteArgException("「$ref」太短了，没法定位到具体订单。请让用户给完整订单号。")
        }
        val hits = ds.findDeletedOrders(ref, ORDER_PROBE_LIMIT)
        val q = AiWriteArgs.normCode(ref)
        val pool = hits.filter { AiWriteArgs.normCode(it.orderNo) == q }.ifEmpty { hits }

        val order = when {
            pool.isEmpty() -> throw AiWriteArgException(
                "回收站里没有订单「$ref」。它可能**没被删过**（那就不需要恢复），" +
                    "或者已经被系统清理掉了。请如实告诉用户，并用查询工具确认这一单现在的状态。",
            )
            pool.size == 1 -> pool.first()
            else -> throw AiWriteArgException(
                "回收站里对上了多张：${pool.take(AiWriteArgs.MAX_CANDIDATES).joinToString("、") { it.label() }}。" +
                    "请让用户说清楚是哪一张。",
                candidates = pool.take(AiWriteArgs.MAX_CANDIDATES).map { it.label() },
            )
        }

        return card(
            summary = "从回收站恢复：${order.orderNo}",
            details = buildList {
                addAll(orderLines(order))
                add("———— 恢复之后 ————")
                add("这单重新出现在各端的列表里（状态、司机、金额都保持原样）")
                add("它原来的账目与消息记录一直都在，不会重复生成")
            },
            payload = buildJsonObject { put("order_id", order.id) },
        )
    }

    override suspend fun commit(payload: JsonObject, idempotencyKey: String) {
        ds.restoreOrder(payload.reqLong("order_id"))
    }
}
