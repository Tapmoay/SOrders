package com.tapmoay.sorders.ai

import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.put

/**
 * 基础动作的处理器（消息 / 支出 / 账本流水）。
 *
 * 订单域的动作在 [AiWriteOrderHandlers] 那个文件里——按域分文件是为了让
 * "改订单派单"和"改记账"永远不会改到同一个文件里去。
 */

/**
 * 消息全部标为已读。**LOW 档 → 不经确认直接执行。**
 *
 * 判据是"不留业务记录"：已读标记只影响你自己看到的红点，不删消息、不进报表、
 * 不影响任何第三方。为它弹一次确认，只会训练用户无脑点确认——
 * 而那个习惯一旦养成，真正危险的确认（派单、收款、撤销）也就一起失效了。
 */
class NotificationsReadAllHandler(
    private val ds: AiWriteDataSource,
) : AiWriteHandler {

    override val actionId = AiWrites.NOTIFICATIONS_READ_ALL

    override suspend fun prepare(params: JsonObject): AiWriteOutcome {
        val result = ds.readAllNotifications()
        val n = (result["count"] as? JsonPrimitive)?.contentOrNull
            ?: (result["updated"] as? JsonPrimitive)?.contentOrNull
        val what = if (n != null) "$n 条消息" else "全部未读消息"
        return AiWriteOutcome.Done(actionId, AiWrites.titleOf(actionId), "已把 $what 标为已读。")
    }

    /**
     * 走不到这里：LOW 档动作在 [prepare] 里就执行完了，不会产生确认卡。
     * 留一个空实现是为了让接口成立；**不要**把"执行"挪到这里来——
     * 那意味着它以后要经过一张卡，而 LOW 档的整套理由就是"它不值得打断用户"。
     */
    override suspend fun commit(payload: JsonObject, idempotencyKey: String) = Unit
}

/** 记一笔支出（油费/维修/过路费…）。MEDIUM 档。 */
class ExpenseWriteHandler(
    private val ds: AiWriteDataSource,
    private val store: AiWritePreviewStore,
) : AiWriteHandler {

    override val actionId = AiWrites.EXPENSES_CREATE

    override suspend fun prepare(params: JsonObject): AiWriteOutcome {
        val (code, cn) = resolveCategory(
            AiWriteArgs.required(
                params, "category",
                "这笔支出是油费、维修还是别的？只能是：" +
                    AiWrites.EXPENSE_CATEGORIES.entries.joinToString("、") { it.value } + "。",
            ),
        )
        val amount = AiWriteArgs.parseMoney(AiWriteArgs.str(params, "amount"), "amount", mustPositive = true)
        val expDate = AiWriteArgs.parseDate(AiWriteArgs.str(params, "exp_date"), "exp_date") ?: java.time.LocalDate.now()

        // ⚠️ 「查不到」在这两个参数上**必须报错，不能当没填**。
        // 反例（改之前就是这样）：用户说「记一笔油费 300，算王师傅的」，而系统里没有王师傅 →
        // 参数被静默丢掉 → 支出记成了"没有司机的支出"。摘要上少一行，用户很难发现，
        // 但月底按司机算油耗时这笔就凭空消失了。宁可让他现在说清楚。
        val driver = AiWriteArgs.str(params, "driver")?.let {
            AiWriteArgs.strict(it, ds.drivers(), "司机")
        }
        val vehicle = AiWriteArgs.str(params, "vehicle")?.let {
            AiWriteArgs.strict(it, ds.vehicles(), "车辆", code = true)
        }
        val note = AiWriteArgs.text(AiWriteArgs.str(params, "note"), "备注")

        return AiWriteOutcome.NeedConfirm(
            store.card(
                actionId,
                summary = "支出：$cn ${AiWriteArgs.money(amount)} 元",
                detailLines = buildList {
                    add("日期：$expDate")
                    if (driver != null) add("司机：${driver.label}")
                    if (vehicle != null) add("车辆：${vehicle.label}")
                    if (note.isNotBlank()) add("备注：$note")
                },
                payload = buildJsonObject {
                    put("exp_date", expDate.toString())
                    put("category", code)
                    put("amount", amount.toPlainString())
                    driver?.id?.let { put("driver_id", it) }
                    vehicle?.id?.let { put("vehicle_id", it) }
                    put("note", note)
                },
            ),
        )
    }

    override suspend fun commit(payload: JsonObject, idempotencyKey: String) {
        ds.createExpense(payload.toExpenseRequest(), idempotencyKey)
    }

    /** 支出分类归一：收英文 code 也收中文名。 */
    private fun resolveCategory(raw: String): Pair<String, String> {
        val v = raw.trim()
        val code = if (AiWrites.EXPENSE_CATEGORIES.containsKey(v.lowercase())) {
            v.lowercase()
        } else {
            AiWrites.EXPENSE_CATEGORIES.entries.firstOrNull { it.value == v }?.key
        }
        if (code == null) {
            throw AiWriteArgException(
                "category「$raw」不是有效的支出类别。只能是：" +
                    AiWrites.EXPENSE_CATEGORIES.entries.joinToString("、") { "${it.key}（${it.value}）" } + "。",
            )
        }
        return code to AiWrites.EXPENSE_CATEGORIES.getValue(code)
    }
}

/** 账本记一笔。MEDIUM 档。 */
class LedgerEntryWriteHandler(
    private val ds: AiWriteDataSource,
    private val store: AiWritePreviewStore,
) : AiWriteHandler {

    override val actionId = AiWrites.LEDGER_CREATE_ENTRY

    override suspend fun prepare(params: JsonObject): AiWriteOutcome {
        val shipperRaw = AiWriteArgs.required(params, "shipper", "这一笔记在谁名下？")
        val product = AiWriteArgs.required(params, "product", "记的是什么货？")

        // 记账对象：注册货主 → 用编号；没注册 → 按「临时客户」记（后端本来就有 temp_shipper_name）。
        // 货主是**唯一允许"查不到"**的实体：后端本来就有这个字段，
        // "来收一趟货、没建过档"是真实业务。但摘要里会写明，用户一眼能看出系统认没认出这个人。
        val shipper = AiWriteArgs.strict(
            shipperRaw,
            ds.searchShippers(shipperRaw, SHIPPER_PROBE_LIMIT),
            "货主",
            allowMissing = true,
        )

        val quantity = AiWriteArgs.str(params, "quantity")?.let { AiWriteArgs.parseQuantity(it) } ?: 1
        val unitPrice = AiWriteArgs.parseMoney(AiWriteArgs.str(params, "unit_price"), "unit_price", mustPositive = false)
        val total = unitPrice.multiply(java.math.BigDecimal(quantity))
            .setScale(2, java.math.RoundingMode.HALF_UP)
        val entryDate = AiWriteArgs.parseDate(AiWriteArgs.str(params, "entry_date"), "entry_date")
            ?: java.time.LocalDate.now()
        val note = AiWriteArgs.text(AiWriteArgs.str(params, "note"), "备注")

        return AiWriteOutcome.NeedConfirm(
            store.card(
                actionId,
                summary = "记账：$product $quantity 件，合计 ${AiWriteArgs.money(total)} 元",
                detailLines = buildList {
                    add(
                        if (shipper != null) "记账对象：${shipper.label}（系统里的货主）"
                        else "记账对象：$shipperRaw（系统里没有这个名字，将按「临时客户」记）",
                    )
                    add("数量：$quantity × 单价 ${AiWriteArgs.money(unitPrice)} 元")
                    add("日期：$entryDate")
                    if (note.isNotBlank()) add("备注：$note")
                },
                payload = buildJsonObject {
                    shipper?.id?.let { put("shipper_id", it) }
                    if (shipper == null) put("temp_shipper_name", shipperRaw)
                    put("entry_date", entryDate.toString())
                    put("product_name", product)
                    put("quantity", quantity)
                    put("unit_price", unitPrice.toPlainString())
                    put("total", total.toPlainString())
                    put("note", note)
                },
            ),
        )
    }

    override suspend fun commit(payload: JsonObject, idempotencyKey: String) {
        ds.createLedgerEntry(payload.toLedgerRequest())
    }

    companion object {
        /** 查货主名册时一次拉多少条（够判断唯一性即可）。 */
        const val SHIPPER_PROBE_LIMIT = 20
    }
}
