package com.tapmoay.sorders.ai

import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import java.math.BigDecimal
import java.time.LocalDate

/**
 * 账本域的写动作（改流水 / 删流水 / 客户收款 / 补进账本）。
 *
 * ### 这一批和其它域最大的不同：**要操作的那一行没有名字**
 * 订单有单号、账号有姓名、商品有商品名——账本流水什么都没有，它就是
 * "某天 + 某货主 + 某摘要 + 某金额"的一行。而 AI 拿不到任何编号（第一条硬规矩），
 * 所以这里只能靠**人说的特征**去对：摘要关键词（必填）+ 日期（可选）+ 金额（可选）。
 *
 * ### 对不上或对上多条 → 一律拒绝并列候选
 * 账本是钱。改错一行**不会立刻被发现**（要等对账那天），所以宁可让用户多说一句
 * "是哪一条"，也不许挑一条最像的。这条纪律在 [LedgerWriteHandler.resolveEntry] 里。
 */
abstract class LedgerWriteHandler(
    protected val ds: AiWriteDataSource,
    protected val store: AiWritePreviewStore,
) : AiWriteHandler {

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

    /**
     * 按"人说的特征"定位**唯一一条**流水。
     *
     * 三步：定日期窗口 → 拿候选 → 逐条件收窄到唯一。
     * 收窄用的三个特征：摘要包含（必填）、日期相等（给了才比）、金额相等（给了才比）。
     */
    protected suspend fun resolveEntry(params: JsonObject): AiLedgerRef {
        val keyword = AiWriteArgs.required(
            params,
            "product",
            "要动的是哪一行？把那一行的摘要或商品名告诉我（越独特越好）。",
        )
        val shipper = AiWriteArgs.str(params, "shipper")?.trim()?.takeIf { it.isNotEmpty() }
        val date = AiWriteArgs.parseDate(AiWriteArgs.str(params, "date"), "date")
        val amount = AiWriteArgs.str(params, "amount")
            ?.let { AiWriteArgs.parseMoney(it, "amount", mustPositive = false) }

        // 日期窗口：用户说了就那一天，没说就最近这些天。
        // ⚠️ 必须给窗口：`GET /ledger/entries` 不传日期时后端返回**全部**流水
        // （派单员视角下是几万行），那种请求又慢又容易撞上旧账。
        val from = (date ?: LocalDate.now().minusDays(LEDGER_WINDOW_DAYS)).toString()
        val to = (date ?: LocalDate.now()).toString()

        val all = ds.ledgerEntries(shipper, from, to, LEDGER_PROBE_LIMIT)
        val key = AiWriteArgs.norm(keyword)
        val byProduct = all.filter { AiWriteArgs.norm(it.product).contains(key) }
        val byDate = date?.let { d -> byProduct.filter { it.date.startsWith(d.toString()) } } ?: byProduct
        val pool = amount?.let { a -> byDate.filter { it.total.toBigDecimalOrNull()?.compareTo(a) == 0 } } ?: byDate

        return when {
            all.isEmpty() -> throw AiWriteArgException(
                "在 $from ~ $to 这段里没找到" +
                    (shipper?.let { "「$it」的" } ?: "") + "账本流水。" +
                    "请让用户确认货主名和日期（或先说清楚是哪一天/哪个货主），不要凭空改别的行。",
            )

            pool.isEmpty() -> throw AiWriteArgException(
                "没找到摘要像「$keyword」的流水" +
                    (date?.let { "（$it 那天）" } ?: "") + (amount?.let { "（${AiWriteArgs.money(it)} 元）" } ?: "") + "。" +
                    "这几天的流水里有这些，请让用户挑一条：\n" +
                    all.take(AiWriteArgs.MAX_CANDIDATES).joinToString("\n") { "· " + it.label() },
                candidates = all.take(AiWriteArgs.MAX_CANDIDATES).map { it.label() },
            )

            pool.size == 1 -> pool.first()

            else -> throw AiWriteArgException(
                "「$keyword」对上了 ${pool.size} 条流水，改错一行要到对账那天才会发现。" +
                    "请让用户补一个条件（哪一天、或者金额是多少）：\n" +
                    pool.take(AiWriteArgs.MAX_CANDIDATES).joinToString("\n") { "· " + it.label() },
                candidates = pool.take(AiWriteArgs.MAX_CANDIDATES).map { it.label() },
            )
        }
    }

    /** 卡片上"这是哪一行"的几行——改/删都必须有，用户靠它核对。 */
    protected fun entryLines(e: AiLedgerRef): List<String> = buildList {
        add("日期：${e.date.ifBlank { "（无）" }}")
        add("摘要：${e.product.ifBlank { "（无）" }}")
        if (e.shipper.isNotBlank()) add("货主：${e.shipper}")
        add("金额：${e.total} 元")
        add("来源：${AiLedgerRef.sourceLabel(e.source)}")
        if (e.note.isNotBlank()) add("备注：${e.note}")
        if (e.orderNo != null) add("⚠️ 这一行是订单 ${e.orderNo} 入账来的")
    }

    companion object {
        /** 用户没说日期时往外看多少天。**窗口越窄越快也越不容易撞**。 */
        const val LEDGER_WINDOW_DAYS = 31L

        /** 一次最多拉多少行来筛（后端这个接口没有 limit 参数，只能在客户端截）。 */
        const val LEDGER_PROBE_LIMIT = 200
    }
}

// ============================================================== 改流水

/**
 * 改账本流水的一行。
 *
 * ### 为什么是 HIGH：它可能**连带改订单**
 * 后端在改"订单来源"的行时会 `sync_order_product_from_ledger` 把明细回写到订单商品行。
 * 也就是说用户以为在改账本，实际把订单的货也改了——卡片必须把这件事写在明面上。
 *
 * ### 卡片写「改前 → 改后」
 * 与改单同理：只显示新值，用户没法发现模型听错了数字。
 */
class UpdateLedgerEntryHandler(
    ds: AiWriteDataSource,
    store: AiWritePreviewStore,
) : LedgerWriteHandler(ds, store) {

    override val actionId = AiWrites.LEDGER_UPDATE_ENTRY

    override suspend fun prepare(params: JsonObject): AiWriteOutcome {
        val entry = resolveEntry(params)

        val changes = buildList {
            newOf(params, "new_amount", "合计金额")?.let {
                add(Change("合计金额", entry.total, AiWriteArgs.money(it), "total", it.toPlainString()))
            }
            newOf(params, "new_quantity", "数量")?.let {
                add(Change("数量", "", it.toPlainString(), "quantity", it.toPlainString()))
            }
            newOf(params, "new_unit_price", "单价")?.let {
                add(Change("单价", "", AiWriteArgs.money(it), "unit_price", it.toPlainString()))
            }
            AiWriteArgs.parseDate(AiWriteArgs.str(params, "new_date"), "new_date")?.let {
                add(Change("日期", entry.date, it.toString(), "entry_date", it.toString()))
            }
            AiWriteArgs.str(params, "new_product")?.trim()?.takeIf { it.isNotEmpty() }?.let {
                add(Change("摘要", entry.product, AiWriteArgs.text(it, "摘要", max = 200), "product_name", it))
            }
            AiWriteArgs.str(params, "note")?.let {
                val t = AiWriteArgs.text(it, "备注", max = 200)
                if (t != entry.note) add(Change("备注", entry.note, t, "note", t))
            }
        }
        if (changes.isEmpty()) {
            throw AiWriteArgException(
                "你还没说要改成什么。可以改：合计金额、数量、单价、日期、摘要、备注。" +
                    "请让用户说清楚改哪一项、改成多少。",
            )
        }
        // 后端只在 manual / order 两种来源上允许改明细（其它来源改明细会 400）。
        val detailKeys = setOf("total", "quantity", "unit_price", "entry_date", "product_name")
        if (entry.source.lowercase() !in setOf("manual", "order") && changes.any { it.key in detailKeys }) {
            throw AiWriteArgException(
                "这一行的来源是「${AiLedgerRef.sourceLabel(entry.source)}」，后端只允许改备注。" +
                    "请如实告诉用户，不要去掉几个字段硬试。",
            )
        }

        return card(
            summary = "改账本流水：${entry.date} ${entry.product}（改 ${changes.size} 项）",
            details = buildList {
                addAll(entryLines(entry))
                add("———— 改动 ————")
                changes.forEach { add("${it.cn}：${it.from.ifBlank { "（原值未载入）" }} → ${it.to}") }
                if (entry.source.equals("order", ignoreCase = true)) {
                    add("⚠️ 这行来自订单，改商品与金额会同时回写那张订单的商品明细")
                }
            },
            payload = buildJsonObject {
                put("entry_id", entry.id)
                changes.forEach { put(it.key, it.value) }
            },
        )
    }

    /** 新值：数字类走金额/数量解析，返回 null = 用户没提这一项。 */
    private fun newOf(params: JsonObject, key: String, cn: String): BigDecimal? =
        AiWriteArgs.str(params, key)?.let { AiWriteArgs.parseMoney(it, cn, mustPositive = false) }

    private data class Change(
        val cn: String,
        val from: String,
        val to: String,
        val key: String,
        val value: String,
    )

    override suspend fun commit(payload: JsonObject, idempotencyKey: String) {
        ds.updateLedgerEntry(payload.reqLong("entry_id"), payload)
    }
}

// ============================================================== 删流水

/**
 * 删一行流水。
 *
 * 为什么卡片要专门写"订单明细不会跟着回滚"：后端 `delete_entry` 只删账本行，
 * **不动订单**。用户很容易以为"删了这条账，那单的账就清了"——那是两回事。
 */
class DeleteLedgerEntryHandler(
    ds: AiWriteDataSource,
    store: AiWritePreviewStore,
) : LedgerWriteHandler(ds, store) {

    override val actionId = AiWrites.LEDGER_DELETE_ENTRY

    override suspend fun prepare(params: JsonObject): AiWriteOutcome {
        val entry = resolveEntry(params)
        return card(
            summary = "删账本流水：${entry.date} ${entry.product} ${entry.total} 元",
            details = buildList {
                addAll(entryLines(entry))
                add("———— 删掉之后 ————")
                add("这一行从账本里消失，撤不回来，只能重新记一笔")
                if (entry.source.equals("order", ignoreCase = true)) {
                    add("这张订单本身及其明细不会变（订单的钱要改请用「改单」或订单商品行）")
                }
            },
            payload = buildJsonObject { put("entry_id", entry.id) },
        )
    }

    override suspend fun commit(payload: JsonObject, idempotencyKey: String) {
        ds.deleteLedgerEntry(payload.reqLong("entry_id"))
    }
}

// ============================================================== 记客户收款

/**
 * 记一笔客户收款（可核销到订单）。
 *
 * ### 为什么是 HIGH
 * 它**动钱**：写一条收款单 + 资金流水，指定的订单还会被标成 `paid=1`。
 * 一旦写错，货主的账面上就多了一笔不存在的收款——而账目错了，人要按它去收钱的。
 *
 * ### ⚠️ 后端的两档结算模式（真机实测撞出来的）
 * `POST /ledger/receipts` 只认两种 `settle_mode`：
 * - `itemized`（逐单核销，**默认**）：必须绑订单，而且**收款金额必须等于所选订单的合计**，
 *   否则 400「逐单核销需绑定订单」/「收款金额与所选订单合计不一致」；
 * - `rolling`（滚动收款）：不绑订单，就是"先收一笔钱、以后再说"。
 *
 * 所以这里按"用户有没有点名订单"来选模式，并且**在卡片之前**就把金额对平——
 * 否则用户点了确认才吃一个 400，那张卡就是白弹的（第一版就是这么被真机抓出来的：
 * 用户没点订单，我却按默认的 itemized 发出去，后端直接拒了）。
 */
class CreateReceiptHandler(
    ds: AiWriteDataSource,
    store: AiWritePreviewStore,
) : LedgerWriteHandler(ds, store) {

    override val actionId = AiWrites.LEDGER_CREATE_RECEIPT

    override suspend fun prepare(params: JsonObject): AiWriteOutcome {
        val customerName = AiWriteArgs.required(params, "customer", "是哪个客户付的钱？把客户名字告诉我。")
        val customer = AiWriteArgs.strict(customerName, ds.customers(), "客户")

        val amountRaw = AiWriteArgs.required(params, "amount", "收到多少钱？")
        val amount = AiWriteArgs.parseMoney(amountRaw, "amount", mustPositive = true)

        val method = AiWriteArgs.str(params, "method")?.trim()?.lowercase()?.takeIf { it.isNotEmpty() }
            ?.also {
                if (it !in METHODS) {
                    throw AiWriteArgException(
                        "收款方式只认 ${METHODS.joinToString(" / ")}，你说的「$it」不在里面。",
                    )
                }
            } ?: "cash"
        val date = AiWriteArgs.parseDate(AiWriteArgs.str(params, "date"), "date") ?: LocalDate.now()
        val note = AiWriteArgs.text(AiWriteArgs.str(params, "note"), "备注")

        // 核销订单：用户点名了才带；逐个解析。
        val rawOrders = AiWriteArgs.str(params, "orders")?.trim()?.takeIf { it.isNotEmpty() }
        val orderRefs = rawOrders?.split(',', '，', ' ', '\n', '、')
            ?.map { it.trim() }?.filter { it.isNotEmpty() }.orEmpty()
        val orders = orderRefs.map { no ->
            val hits = ds.findOrders(no, 5)
            val q = AiWriteArgs.normCode(no)
            hits.firstOrNull { AiWriteArgs.normCode(it.orderNo) == q }
                ?: throw AiWriteArgException("没找到订单「$no」。请让用户确认单号，**不要自己挑一单**。")
        }
        if (orders.size > AiWrites.MAX_RECEIPT_ORDERS) {
            throw AiWriteArgException("一笔收款最多核销 ${AiWrites.MAX_RECEIPT_ORDERS} 张单，你说的太多了，请分批。")
        }

        // 逐单核销必须全额：先把两边的数摆出来，不等后端 400。
        val settleMode = if (orders.isEmpty()) "rolling" else "itemized"
        if (orders.isNotEmpty()) {
            val sum = orders
                .fold(BigDecimal.ZERO) { a, o -> a.add(o.amount.toBigDecimalOrNull() ?: BigDecimal.ZERO) }
                .setScale(2, java.math.RoundingMode.HALF_UP)
            if (sum.compareTo(amount) != 0) {
                throw AiWriteArgException(
                    "逐单核销必须**全额**：这几张单合计 ${AiWriteArgs.money(sum)} 元，" +
                        "而收款金额是 ${AiWriteArgs.money(amount)} 元，两边对不上（后端也会拒）。" +
                        "请让用户确认金额，或者不要点名订单（那就是一笔滚动收款，不核销到单上）。",
                )
            }
        }

        return card(
            summary = "记客户收款：${customer!!.label} ${AiWriteArgs.money(amount)} 元",
            details = buildList {
                add("客户：${customer.label}")
                add("收款金额：${AiWriteArgs.money(amount)} 元")
                add("收款方式：${methodLabel(method)}")
                add("收款日期：$date")
                if (note.isNotBlank()) add("备注：$note")
                if (orders.isEmpty()) {
                    add("———— 核销 ————")
                    add("不核销到具体订单（滚动收款）：只记一笔收到的钱，不会把任何订单标成已收")
                    // ⚠️ 这句是真机实测出来的（不是推测）：后端的现金流水只在**逐单核销**时逐单生成，
                    // 不绑订单的滚动收款不写现金流水。钱没丢（在「收款记录」里），但用户必须知道去哪找。
                    add("这笔钱会记在「收款记录」里，不进「现金流水」")
                } else {
                    add("———— 核销到这些单（逐单核销）————")
                    orders.forEach { add("· ${it.label()}｜${it.amount} 元") }
                    add("这些订单会被标记成已收；这几张单必须都属于这个客户（后端会校验）")
                }
            },
            payload = buildJsonObject {
                put("customer_id", customer.id)
                put("amount", amount.toPlainString())
                put("method", method)
                put("received_at", date.toString())
                put("settle_mode", settleMode)
                // ⚠️ 空列表就**不放这个键**：payload 的读取约定是"空字符串 = 没给"
                // （见 `JsonObject.str`），放一个 "" 进去会被判成"缺少必填字段"。
                if (orders.isNotEmpty()) put("order_ids", orders.joinToString(",") { it.id.toString() })
                put("note", note)
            },
        )
    }

    private fun methodLabel(code: String): String = when (code) {
        "cash" -> "现金"
        "transfer" -> "转账"
        "wechat" -> "微信"
        "arrears_settle" -> "挂账结清"
        else -> code
    }

    override suspend fun commit(payload: JsonObject, idempotencyKey: String) {
        ds.createReceipt(
            customerId = payload.reqLong("customer_id"),
            amount = payload.req("amount"),
            method = payload.req("method"),
            receivedAt = payload.req("received_at"),
            orderIds = payload.str("order_ids")
                ?.split(",")?.mapNotNull { it.trim().toLongOrNull() }
                .orEmpty(),
            settleMode = payload.req("settle_mode"),
            note = payload.str("note"),
        )
    }

    private companion object {
        val METHODS = listOf("cash", "transfer", "wechat", "arrears_settle")
    }
}

// ============================================================== 补进账本

/**
 * 把已送达订单补进账本（幂等）。
 *
 * 为什么是 MEDIUM：它不改任何订单、不删任何东西，**只补缺的行**，而且后端是幂等的
 * （重复跑不会重复入账）。但它会按货主推送账本更新通知，所以卡片要写明"会给谁推"。
 */
class SyncDeliveredLedgerHandler(
    ds: AiWriteDataSource,
    store: AiWritePreviewStore,
) : LedgerWriteHandler(ds, store) {

    override val actionId = AiWrites.LEDGER_SYNC_DELIVERED

    override suspend fun prepare(params: JsonObject): AiWriteOutcome {
        val shipperName = AiWriteArgs.str(params, "shipper")?.trim()?.takeIf { it.isNotEmpty() }
        val shipper = shipperName?.let { AiWriteArgs.strict(it, ds.searchShippers(it, 20), "货主") }

        return card(
            summary = if (shipper == null) "补进账本：全部货主" else "补进账本：${shipper.label}",
            details = buildList {
                add(if (shipper == null) "范围：所有货主" else "范围：${shipper.label}")
                add("做法：把已送达但账本里还没有的订单补进去")
                add("幂等：已经入过账的不会重复入（重复跑是安全的）")
                add("已有流水不会被改动或删除")
                if (shipper != null) add("会给这个货主推一条账本更新通知")
            },
            payload = buildJsonObject {
                if (shipper != null) put("shipper_id", shipper.id) else put("all", "true")
            },
        )
    }

    override suspend fun commit(payload: JsonObject, idempotencyKey: String) {
        ds.syncDeliveredOrders(payload.str("shipper_id")?.toLongOrNull())
    }
}
