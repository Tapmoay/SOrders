package com.tapmoay.sorders.ai

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.put
import java.math.BigDecimal
import java.math.RoundingMode
import java.time.LocalDate

/**
 * 发票台账六条（CHG-0086 / 台账 L-55，2026-10-08）。
 *
 * ### 为什么是「六条」而不是「三个动作」
 * 后端这六个写端点干的是六件不同的事，用户嘴里也是六件事：
 * 登记一张票 / 改一张票 / 开具 / 作废 / 撤票 / 恢复。
 * 其中三件最容易被合成一件，而它们**互相不能替代**：
 *
 * 1. **未税票（登记时没填税率）≠ 零税率票**：零税率的票进税汇、只是税额是 0；
 *    未税票压根不进税汇（`tax_service.counts_in_tax` 判的是 `tax_rate is not None`）。
 *    而「有没有税」在**登记那一刻**就定了 —— 后端 `update` 改不了它，要改只能作废重开一张。
 * 2. **作废 ≠ 撤票**：作废的票**留在台账里**（那是一个状态）、票号一直占着、退出税汇；
 *    撤票是进回收站（软删），台账列表里默认看不见，但票号**还是占着**，随时能原样恢复。
 * 3. **开具 ≠ 进税汇**：一张票进不进税汇，只看「有没有税率、有没有作废、有没有在回收站」，
 *    「开没开」不改变它。开具真正的后果是**冻结**：之后一个字都改不动（要改就作废重开一张）。
 *
 * 合成一个动作的后果是可预见的：模型会把「作废」和「撤票」当成同一件事，
 * 用户点完才发现票还在台账里、或者票号被一直占着。
 *
 * 这一条由 `_tools/qa/_check_ai_invoices.py` 逐条钉住（反向破坏用例见
 * `_tools/qa/_reverse_verify_ai_invoices.py`）。
 *
 * ### 为什么六条都只给派单员
 * 后端这六个写端点全部要 `Permission.LEDGER_EDIT`（`backend/app/api/v1/invoices.py:56`），
 * 而 `backend/app/core/rbac.py` 里只有派单员有 `ledger:edit`（`:117`），货主与司机都没有
 * ⇒ 它们**不进** [AiWrites.SHIPPER_ACTIONS]。这不是保守：货主连自己的票都看不见
 * （那三个读端点的读门是 `order:dispatch`）。
 *
 * ### 定位口径（改 / 开具 / 作废 / 撤票四条共用）
 * 用户说得出「是哪一张」的特征只有五个：票号、销项还是进项、开票日期、价税合计、对方是谁。
 * [InvoiceWriteHandler.resolveInvoice] 按这五个收窄，**对不上就拒绝并列候选**，绝不挑一条最像的 ——
 * 改错一张票要到对账那天才会发现（与账本 [LedgerWriteHandler.resolveEntry] 同一条理由）。
 * 票号是唯一精确的键：后端在同一方向内唯一，而且**回收站里的票也占着号**。
 *
 * ### 税额算法只有一份
 * 只给税率、不给税额时，这里按 [taxOf] 算一个并**显式写进 payload**：算法与
 * `backend/app/services/tax_service.py::tax_of_amount` 逐字对齐（`合计 − 合计 ÷ (1 + 税率)`，
 * 到分、四舍五入）。这样卡片上给用户看的数与真正落库的数是同一个 —— 否则用户核对的是一个数、
 * 库里存的是另一个数，而两张卡片看起来说的是同一件事。
 */

/**
 * 台账里一张票的**可核对形状**。
 *
 * 为什么不用 [InvoiceDto]：定位卡片要写「你指的是不是这一张」，需要的是
 * 人认得出的五样（方向 / 票号 / 日期 / 金额 / 对方）＋ 两个状态（票的状态、在不在回收站），
 * 而不是后端那一整份 DTO。撤回快照走的是另一条路（[AiRevertRead.invoice] 直接吃 DTO）。
 */
data class AiInvoiceRef(
    val id: Long,
    val direction: String,
    val invoiceNo: String,
    val invoiceDate: String,
    val amount: String,
    val taxRate: String?,
    val taxAmount: String?,
    val status: String,
    val partyName: String,
    val note: String,
    val isDeleted: Boolean,
) {
    val directionCn: String get() = if (direction == DIR_INPUT) "进项" else "销项"

    val statusCn: String
        get() = when (status) {
            ST_ISSUED -> "已开具"
            ST_VOIDED -> "已作废"
            else -> "已登记"
        }

    /** 未税票：登记时就没填税率。它照常留在台账里，但**不进税汇**。 */
    val untaxed: Boolean get() = taxRate.isNullOrBlank()

    companion object {
        const val DIR_OUTPUT = "OUTPUT"
        const val DIR_INPUT = "INPUT"
        const val ST_REGISTERED = "REGISTERED"
        const val ST_ISSUED = "ISSUED"
        const val ST_VOIDED = "VOIDED"
    }
}

/** 要登记的一张票：处理器把参数解析成确定的值、核过名册之后交给数据源。 */
data class AiInvoiceDraft(
    val direction: String,
    val invoiceNo: String,
    val invoiceDate: String,
    val amount: String,
    val taxRate: String?,
    val taxAmount: String?,
    val supplierId: Long?,
    val customerId: Long?,
    val purchaseOrderIds: List<Long>,
    val note: String,
)

/**
 * 发票台账这一域的动作清单（六个）。
 *
 * ⛔ 六条都**不进** [AiWrites.SHIPPER_ACTIONS]：后端要 `ledger:edit`，只有派单员有（见文件头）。
 */
internal object AiWriteInvoices {

    /**
     * 「是哪一张票」——改 / 开具 / 作废 / 撤票四条共用。
     *
     * 顺序按**准不准**排：票号是唯一精确的键，后面几样只能把它收窄到「可能就那么几张」，
     * 所以模型应当优先向用户要票号。
     */
    private fun locateParams(vararg extra: AiWriteParam): List<AiWriteParam> = listOf(
        AiWriteParam(
            name = "invoice_no",
            cn = "票号",
            hint = "最准的定位方式。票号还没拿到就用 date + amount，或者对方的名字",
        ),
        AiWriteParam(
            name = "direction",
            cn = "销项还是进项",
            kind = AiWriteParamKind.ENUM,
            enumValues = listOf("OUTPUT", "INPUT"),
            hint = "票号撞不出来时才需要：OUTPUT = 销项（我们开给客户）、INPUT = 进项（供应商开给我们）",
        ),
        AiWriteParam(name = "date", cn = "开票日期", kind = AiWriteParamKind.DATE, hint = "YYYY-MM-DD，比对时含前后 31 天"),
        AiWriteParam(name = "amount", cn = "价税合计", kind = AiWriteParamKind.NUMBER, hint = "票面上那个总金额（含税）"),
        AiWriteParam(name = "party", cn = "对方", hint = "销项票写客户名、进项票写供应商名"),
    ) + extra

    val ACTIONS: List<AiWriteAction> = listOf(
        AiWriteAction(
            id = AiWrites.INVOICES_CREATE,
            title = "登记一张发票",
            risk = AiWriteRisk.HIGH,
            group = AiWrites.G_INVOICE,
            blurb = "把一张票登进发票台账：销项票（我们开给客户）或者进项票（供应商开给我们）。" +
                "进项票要挂采购单、销项票要挂客户；票号还没拿到可以先空着。" +
                "「未税票」（没填税率）和「有税票」在登记这一刻就定了，之后要改只能作废重开一张。",
            params = listOf(
                AiWriteParam(
                    name = "direction",
                    cn = "销项还是进项",
                    required = true,
                    kind = AiWriteParamKind.ENUM,
                    enumValues = listOf("OUTPUT", "INPUT"),
                    hint = "OUTPUT = 销项（我们开给客户，要填 customer）；INPUT = 进项（供应商开给我们，要填 supplier 与 purchase_orders）",
                ),
                AiWriteParam(name = "invoice_no", cn = "票号", hint = "发票上印的号码。还没拿到就留空（空票号照样能登记，之后再补）"),
                AiWriteParam(name = "date", cn = "开票日期", required = true, kind = AiWriteParamKind.DATE, hint = "YYYY-MM-DD"),
                AiWriteParam(name = "amount", cn = "价税合计", required = true, kind = AiWriteParamKind.NUMBER, hint = "票面上那个总金额（含税），例如 1200 或 1200.50"),
                AiWriteParam(name = "tax_rate", cn = "税率", kind = AiWriteParamKind.NUMBER, hint = "百分数：3 表示 3%、13 表示 13%。不给 = 未税票（未税票不进税汇）"),
                AiWriteParam(name = "tax_amount", cn = "税额", kind = AiWriteParamKind.NUMBER, hint = "票面上印的税额。只给税率时按「合计 ÷ (1 + 税率)」倒推"),
                AiWriteParam(name = "supplier", cn = "供应商", hint = "进项票是谁开给我们的（供应商名册里的名字）"),
                AiWriteParam(name = "customer", cn = "客户", hint = "销项票开给谁（客户名册里的名字）"),
                AiWriteParam(name = "purchase_orders", cn = "挂哪几张采购单", hint = "进项票必填，一单或多单，用「、」或「,」分开，例如 12、15"),
                AiWriteParam(name = "note", cn = "备注"),
            ),
        ),
        AiWriteAction(
            id = AiWrites.INVOICES_UPDATE,
            title = "改一张发票",
            risk = AiWriteRisk.MEDIUM,
            group = AiWrites.G_INVOICE,
            blurb = "改一张还没开具的票：票号、开票日期、价税合计、税额、备注。" +
                "只有「已登记」的票能改（已开具 / 已作废的票要改就作废重开一张）。" +
                "票的「有没有税」在登记那一刻定了，这里改不了。",
            params = locateParams(
                AiWriteParam(name = "new_invoice_no", cn = "新票号"),
                AiWriteParam(name = "new_date", cn = "新开票日期", kind = AiWriteParamKind.DATE, hint = "YYYY-MM-DD"),
                AiWriteParam(name = "new_amount", cn = "新价税合计", kind = AiWriteParamKind.NUMBER, hint = "含税总金额"),
                AiWriteParam(name = "new_tax_rate", cn = "新税率", kind = AiWriteParamKind.NUMBER, hint = "百分数，3 = 3%。只给税率时税额按同一算法重算"),
                AiWriteParam(name = "new_tax_amount", cn = "新税额", kind = AiWriteParamKind.NUMBER),
                AiWriteParam(name = "note", cn = "新备注", hint = "传空串 = 把备注清空"),
            ),
        ),
        AiWriteAction(
            id = AiWrites.INVOICES_ISSUE,
            title = "开具一张发票",
            risk = AiWriteRisk.HIGH,
            group = AiWrites.G_INVOICE,
            blurb = "把「已登记」的票标记成「已开具」：真实世界里票已经开出去、寄给对方了。" +
                "开具之后这张票就冻结了 —— 一个字都改不动，要改只能作废重开一张。" +
                "它进不进税汇与「开没开」无关（看的是有没有税率、有没有作废）。",
            params = locateParams(),
        ),
        AiWriteAction(
            id = AiWrites.INVOICES_VOID,
            title = "作废一张发票",
            risk = AiWriteRisk.HIGH,
            group = AiWrites.G_INVOICE,
            blurb = "把一张票标记成「已作废」：票还留在台账里、票号一直占着、但不再进税汇" +
                "（销项 / 进项合计算不上它，税额也不算了）。「已登记」与「已开具」的票都能作废；" +
                "作废撤不回来，要重开就新登记一张。",
            params = locateParams(),
        ),
        AiWriteAction(
            id = AiWrites.INVOICES_DELETE,
            title = "撤票（放进回收站）",
            risk = AiWriteRisk.MEDIUM,
            group = AiWrites.G_INVOICE,
            blurb = "把一张票从台账里撤掉（软删）：默认看不见它，但票号还是占着。" +
                "它和「作废」不是一件事：作废是留在台账里（那是一个状态），撤票是进回收站、随时能原样恢复。",
            params = locateParams(),
        ),
        // 恢复：**撤回专用**（`undoOnly`）——回收站里的票已经不在台账列表里，
        // 按票号/日期都解析不到它（[AiWriteAction.undoOnly] 的注释讲的就是这条），
        // 而撤回路径手里拿着**确定的编号**。
        restoreAction(
            cn = "发票",
            id = AiWrites.INVOICES_RESTORE,
            group = AiWrites.G_INVOICE,
            call = { ds, id -> ds.restoreInvoice(id) },
        ),
    )
}

// ============================================================ 共用小工具

/** 定位时往前 / 往后看多少天：一张票的日期用户常记成前后几天（与账本的 31 天同口径）。 */
private const val INVOICE_WINDOW_DAYS = 31L

/** 票号长度上限（与后端 `InvoiceCreate.invoice_no` 的 64 一致）。 */
private const val MAX_INVOICE_NO_CHARS = 64

/** 一张进项票最多挂多少张采购单：纯粹是卡片可读性的上限，真到 50 张也该换个做法了。 */
private const val MAX_ORDER_LINKS = 50

/** 台账列表一次拉多少张（`GET /invoices` 的默认分页就是 100）。 */
private const val PROBE_LIMIT = 100

/**
 * 税额 = 价税合计 − 不含税金额，到分、四舍五入。
 *
 * ⚠️ 这是 `backend/app/services/tax_service.py::tax_of_amount` 的**第二份实现**，
 * 两份必须逐字对齐：后端算的是 `yuan(amount) - yuan(amount / (1 + rate/100))`。
 * 为什么不直接让后端算：卡片上要写出「这一下会存进去多少税」，而卡片是提交**之前**画的 ——
 * 拿不到后端的数。宁可在这里写第二份、并把它钉在判据里，也不要让卡片上的数是个猜的。
 *
 * `rate.movePointLeft(2)` 就是 `rate / 100`，对两位小数的税率是精确的（3.00 → 0.03）。
 * 除法取 20 位再截断：正数上「先截断再四舍五入到分」与「直接四舍五入到分」等价，
 * 且不会因为中间那一步把结果抬上去。
 */
internal fun taxOf(amount: BigDecimal, rate: BigDecimal): BigDecimal {
    val divisor = BigDecimal.ONE + rate.movePointLeft(2)
    val net = amount.divide(divisor, 20, RoundingMode.DOWN).setScale(2, RoundingMode.HALF_UP)
    return amount.setScale(2, RoundingMode.HALF_UP) - net
}

/** 「销项还是进项」：收中英文两种说法，归一成后端要的 code，**既不猜也不报错**。 */
private fun normalizeDirection(raw: String): String = when (raw.trim().uppercase()) {
    "OUTPUT", "销项", "销项票", "我们开的", "开出去的", "开给客户" -> AiInvoiceRef.DIR_OUTPUT
    "INPUT", "进项", "进项票", "收到的", "别人开给我们的", "供应商开的" -> AiInvoiceRef.DIR_INPUT
    else -> throw AiWriteArgException(
        "direction 只能是 OUTPUT（销项：我们开给客户）或者 INPUT（进项：供应商开给我们），收到「$raw」。",
    )
}

private fun requiredDirection(params: JsonObject): String {
    val raw = AiWriteArgs.str(params, "direction")
        ?: throw AiWriteArgException(
            "缺少 direction：这张是销项票（我们开给客户，填 OUTPUT）还是进项票（供应商开给我们，填 INPUT）？",
        )
    return normalizeDirection(raw)
}

private fun optionalDirection(params: JsonObject): String? =
    AiWriteArgs.str(params, "direction")?.let { normalizeDirection(it) }

/** 日期参数：空 = 没提；格式不对**当场报错**，不倒推、不猜。 */
private fun dateOf(params: JsonObject, key: String, cn: String): LocalDate? {
    val raw = AiWriteArgs.str(params, key) ?: return null
    return AiWriteArgs.parseDate(raw, cn)
        ?: throw AiWriteArgException("$cn 必须是 YYYY-MM-DD（如 2026-09-15），收到「$raw」。")
}

/** 税率：百分数（3 = 3%）。容忍「3%」「3个点」，但只认 0~100。 */
private fun rateOf(params: JsonObject, key: String, cn: String): BigDecimal? {
    val raw = AiWriteArgs.str(params, key) ?: return null
    val cleaned = raw.trim().removeSuffix("%").removeSuffix("％").removeSuffix("个点").trim()
    val v = toBig(cleaned) ?: throw AiWriteArgException("$cn 要是数字（百分数：3 = 3%），收到「$raw」。")
    if (v < BigDecimal.ZERO || v > BigDecimal("100")) {
        throw AiWriteArgException("$cn 是百分数（3.00 = 3%），只能在 0 到 100 之间，收到「$raw」。")
    }
    return v
}

/** 票号：空串合法（「还没拿到」），但**超长直接拒绝** —— 悄悄截断会存下一个错的票号。 */
private fun invoiceNoOf(raw: String?, cn: String): String {
    val v = raw?.trim().orEmpty()
    if (v.length > MAX_INVOICE_NO_CHARS) {
        throw AiWriteArgException(
            "$cn 最多 $MAX_INVOICE_NO_CHARS 个字符，收到 ${v.length} 个 —— 是不是把别的号码贴上来了？",
        )
    }
    return v
}

/** 备注：空 = 没提（要**清空**备注走 [UpdateInvoiceHandler] 那条空串的路）。 */
private fun noteOf(params: JsonObject, key: String): String {
    val v = AiWriteArgs.str(params, key) ?: return ""
    if (v.length > AiWriteArgs.MAX_TEXT_CHARS) {
        throw AiWriteArgException(
            "备注最多 ${AiWriteArgs.MAX_TEXT_CHARS} 个字，收到 ${v.length} 个 —— 请缩短一点。",
        )
    }
    return v
}

/** 采购单编号表：「12、15」这种写法要能拆开，拆不开就拒绝（不猜）。 */
private fun orderIdsOf(raw: String): List<Long> {
    val parts = raw.split("、", ",", "，", ";", "；", " ", "/").map { it.trim() }.filter { it.isNotEmpty() }
    if (parts.isEmpty()) {
        throw AiWriteArgException("purchase_orders 是空的：进项票至少要挂一张采购单。")
    }
    val out = mutableListOf<Long>()
    parts.forEach { p ->
        val digits = p.removePrefix("#").removePrefix("No.").removePrefix("NO.").removePrefix("no.").trim()
        val id = digits.toLongOrNull()
            ?: throw AiWriteArgException(
                "采购单编号「$p」不是数字 —— 我要的是采购单列表里那个编号（例如 12、15）。",
            )
        if (!out.contains(id)) out += id
    }
    if (out.size > MAX_ORDER_LINKS) {
        throw AiWriteArgException("一张进项票最多挂 $MAX_ORDER_LINKS 张采购单，收到 ${out.size} 张。")
    }
    return out
}

/** 按名字在名册里找唯一一条：找不到 / 撞上多条都**列候选**，绝不挑一条最像的。 */
private fun matchName(roster: List<AiName>, raw: String, cn: String): AiName {
    val exact = roster.filter { it.label == raw }
    if (exact.size == 1) return exact[0]
    val loose = roster.filter { it.label.contains(raw, ignoreCase = true) || raw.contains(it.label) }
    return when {
        loose.size == 1 -> loose[0]
        loose.isEmpty() -> throw AiWriteArgException(
            "名册里没有这个$cn：「$raw」。先把它在名册里建好，或者把名字说全。",
            roster.take(AiWriteArgs.MAX_CANDIDATES).map { it.label },
        )
        else -> throw AiWriteArgException(
            "「$raw」对上了不止一个$cn，请说全名。",
            loose.take(AiWriteArgs.MAX_CANDIDATES).map { it.label },
        )
    }
}

private fun toBig(raw: String): BigDecimal? = runCatching { BigDecimal(raw.trim()) }.getOrNull()

private fun sameMoney(raw: String?, want: BigDecimal): Boolean =
    raw != null && toBig(raw)?.compareTo(want) == 0

private fun moneyOrDash(v: BigDecimal?): String = if (v == null) "（空）" else AiWriteArgs.moneyText(v) + " 元"

/** 卡片与候选里「这一张」的写法：五样人认得出的特征 + 两个状态。 */
private fun label(inv: AiInvoiceRef): String {
    val no = if (inv.invoiceNo.isBlank()) "票号还没填" else inv.invoiceNo
    val tax = if (inv.untaxed) "未税票" else "含税 ${AiWriteArgs.moneyText(inv.taxRate)}%"
    val party = if (inv.partyName.isBlank()) "" else " · ${inv.partyName}"
    val bin = if (inv.isDeleted) " · 在回收站里" else ""
    return "${inv.directionCn}票 $no · ${inv.invoiceDate} · ${AiWriteArgs.moneyText(inv.amount)} 元 · $tax · ${inv.statusCn}$party$bin"
}

/** 摘要里的抬头：「销项票 12345678」/「销项票（票号还没拿到）」。 */
private fun noHead(inv: AiInvoiceRef): String =
    if (inv.invoiceNo.isBlank()) "（票号还没拿到）" else " ${inv.invoiceNo}"

private fun describeQuery(
    no: String?,
    dir: String?,
    date: LocalDate?,
    amount: BigDecimal?,
    party: String?,
): String {
    val bits = mutableListOf<String>()
    if (no != null) bits += "票号「$no」"
    if (dir != null) bits += (if (dir == AiInvoiceRef.DIR_INPUT) "进项票" else "销项票")
    if (date != null) bits += "开票日期 $date"
    if (amount != null) bits += "价税合计 ${AiWriteArgs.moneyText(amount)} 元"
    if (party != null) bits += "对方「$party」"
    return bits.joinToString(" + ")
}

private data class Change(val cn: String, val from: String, val to: String)

// ============================================================ 处理器

/**
 * 发票四条（改 / 开具 / 作废 / 撤票）共用的底座：**先认出是哪一张票**，再画卡。
 */
internal abstract class InvoiceWriteHandler(
    protected val ds: AiWriteDataSource,
    protected val store: AiWritePreviewStore,
) : AiWriteHandler {

    /** 卡片只在这一处造：`detailLines` 给用户看、`payload` 落库，两者由**同一次调用**产生。 */
    protected fun card(summary: String, details: List<String>, payload: JsonObject): AiWriteOutcome =
        AiWriteOutcome.NeedConfirm(
            store.card(actionId, summary = summary, detailLines = details, payload = payload),
        )

    /**
     * 认出用户说的是哪一张票。
     *
     * 三条口径：
     * 1. **至少给一个能收窄的**：一个都不给就直接问回去（列最近几张让它挑）；
     * 2. **对不上就拒绝**：0 条列最近几张、多条列候选，绝不 take(1)（票号除外 ——
     *    它在后端同一方向内唯一，撞出多张只可能是同一张的重复读写）；
     * 3. **回收站里的票照找**（`includeDeleted = true`）：找到之后由调用方说清楚
     *    「它在回收站里、改不动」，而不是让用户以为系统里根本没有这张票。
     */
    protected suspend fun resolveInvoice(params: JsonObject): AiInvoiceRef {
        val no = AiWriteArgs.str(params, "invoice_no")
        val dir = optionalDirection(params)
        val date = dateOf(params, "date", "开票日期")
        val amount = AiWriteArgs.str(params, "amount")
            ?.let { AiWriteArgs.parseMoney(it, "价税合计", mustPositive = true) }
        val party = AiWriteArgs.str(params, "party")

        if (no == null && dir == null && date == null && amount == null && party == null) {
            throw AiWriteArgException(
                "要动的是哪一张票？给我票号（最准），或者开票日期 + 价税合计，或者对方的名字。",
                listOf("先看一眼发票台账：这张票的票号 / 日期 / 金额 / 对方是谁"),
            )
        }

        val from = date?.minusDays(INVOICE_WINDOW_DAYS)
        val to = date?.plusDays(INVOICE_WINDOW_DAYS)
        val pool = ds.invoices(
            direction = dir,
            keyword = no ?: party,
            dateFrom = from?.toString(),
            dateTo = to?.toString(),
            includeDeleted = true,
        )
        var hits = pool
        if (no != null) hits = hits.filter { it.invoiceNo.equals(no, ignoreCase = true) }
        if (date != null) hits = hits.filter { it.invoiceDate == date.toString() }
        if (amount != null) hits = hits.filter { sameMoney(it.amount, amount) }
        if (party != null) {
            hits = hits.filter { it.partyName.isNotBlank() && (it.partyName.contains(party) || party.contains(it.partyName)) }
        }
        val what = describeQuery(no, dir, date, amount, party)
        val scope = if (from == null) {
            "最近 $PROBE_LIMIT 张里"
        } else {
            "$from 到 $to 这 ${INVOICE_WINDOW_DAYS * 2 + 1} 天里"
        }
        return when {
            // 票号唯一：撞出多张只可能是回收站与在册那张同号（后端拦着不让建，但历史数据可能有）
            no != null && hits.isNotEmpty() -> hits[0]
            hits.size == 1 -> hits[0]
            hits.isEmpty() -> throw AiWriteArgException(
                "台账里没找到这样一张票：$what（我在${scope}找的）。不要凭空动别的票 —— 把票号或者日期说准一点。",
                pool.take(AiWriteArgs.MAX_CANDIDATES).map { label(it) },
            )
            else -> throw AiWriteArgException(
                "$what 对上了 ${hits.size} 张票，请说清楚是哪一张（票号最准）。",
                hits.take(AiWriteArgs.MAX_CANDIDATES).map { label(it) },
            )
        }
    }
}

/**
 * 登记一张发票（`POST /invoices`）。
 *
 * 卡片要写全五件事，缺一件用户就没法核对：方向 / 票号 / 日期 / 合计 + 税 / 对方与挂单。
 * 「有没有税」**在登记这一刻定死**，所以卡片必须把这件事说明白（未税票不进税汇）。
 */
internal class CreateInvoiceHandler(
    ds: AiWriteDataSource,
    store: AiWritePreviewStore,
) : InvoiceWriteHandler(ds, store) {

    override val actionId = AiWrites.INVOICES_CREATE

    private var pendingNote: String? = null

    override suspend fun prepare(params: JsonObject): AiWriteOutcome {
        val direction = requiredDirection(params)
        val isInput = direction == AiInvoiceRef.DIR_INPUT
        val no = invoiceNoOf(AiWriteArgs.str(params, "invoice_no"), "票号")
        val date = dateOf(params, "date", "开票日期")
            ?: throw AiWriteArgException("缺少 date：这张票是哪一天开的？（YYYY-MM-DD，例如 2026-09-15）")
        val amount = AiWriteArgs.parseMoney(
            AiWriteArgs.required(params, "amount", "价税合计"),
            "价税合计",
            mustPositive = true,
        )
        val rate = rateOf(params, "tax_rate", "税率")
        val givenTax = AiWriteArgs.str(params, "tax_amount")
            ?.let { AiWriteArgs.parseMoney(it, "税额", mustPositive = false) }
        if (givenTax != null && rate == null) {
            throw AiWriteArgException(
                "只给了税额、没给税率：这张票到底算不算税？要进税汇就把税率一起给上（未税票不该有税额）。",
            )
        }
        val tax = when {
            rate == null -> null
            givenTax != null -> givenTax
            else -> taxOf(amount, rate)
        }
        if (tax != null && tax > amount) {
            throw AiWriteArgException(
                "税额（${AiWriteArgs.moneyText(tax)} 元）比价税合计（${AiWriteArgs.moneyText(amount)} 元）还大 —— 这两个数是不是填反了？",
            )
        }

        val supplierRaw = AiWriteArgs.str(params, "supplier")
        val customerRaw = AiWriteArgs.str(params, "customer")
        val ordersRaw = AiWriteArgs.str(params, "purchase_orders")
        val supplierId: Long?
        val customerId: Long?
        val supplierLabel: String
        val customerLabel: String
        val orders: List<Long>
        if (isInput) {
            if (customerRaw != null) {
                throw AiWriteArgException(
                    "进项票是供应商开给我们的，不该填客户（customer）—— 把 customer 去掉，改填 supplier。",
                )
            }
            if (supplierRaw == null) {
                throw AiWriteArgException("缺少 supplier：这张进项票是谁开给我们的？（供应商名册里的名字）")
            }
            if (ordersRaw == null) {
                throw AiWriteArgException(
                    "缺少 purchase_orders：进项票必须挂至少一张采购单 —— 不然答不出「这批货有没有票」。" +
                        "给我采购单列表里那个编号，例如 12、15。",
                )
            }
            val supplier = matchName(ds.suppliers(), supplierRaw, "供应商")
            supplierId = supplier.id
            customerId = null
            supplierLabel = supplier.label
            customerLabel = ""
            orders = orderIdsOf(ordersRaw)
        } else {
            if (supplierRaw != null) {
                throw AiWriteArgException(
                    "销项票是我们开给客户的，不该填供应商（supplier）—— 把 supplier 去掉，改填 customer。",
                )
            }
            if (customerRaw == null) {
                throw AiWriteArgException("缺少 customer：这张销项票开给谁？（客户名册里的名字）")
            }
            if (ordersRaw != null) {
                throw AiWriteArgException("销项票不该挂采购单（采购单是进货那一侧的东西）—— 把 purchase_orders 去掉。")
            }
            val customer = matchName(ds.customers(), customerRaw, "客户")
            customerId = customer.id
            supplierId = null
            customerLabel = customer.label
            supplierLabel = ""
            orders = emptyList()
        }
        orders.forEach { id ->
            if (ds.purchaseOrder(id) == null) {
                throw AiWriteArgException(
                    "采购单 #$id 不在系统里（编号对不对？）—— 进项票只能挂在真实存在的采购单上。",
                )
            }
        }
        val note = noteOf(params, "note")

        val payload = buildJsonObject {
            put("direction", direction)
            put("invoice_no", no)
            put("invoice_date", date.toString())
            put("amount", AiWriteArgs.money(amount))
            if (rate != null) put("tax_rate", AiWriteArgs.money(rate))
            if (tax != null) put("tax_amount", AiWriteArgs.money(tax))
            if (isInput) {
                put("supplier_id", supplierId)
                // 名字只进卡片正文（同采购单那条口径）：撤回是"把 payload 里的键写回旧值"，
                // 而名字不在这个资源的 readKeys 里 —— 放进来只会在撤回卡上多一行读不懂的裸键。
                put("supplier_name", supplierLabel)
                put("purchase_order_ids", buildJsonArray { orders.forEach { add(JsonPrimitive(it)) } })
            } else {
                put("customer_id", customerId)
                put("customer_name", customerLabel)
            }
            put("note", note)
        }

        val details = mutableListOf<String>()
        details += "方向：${if (isInput) "进项（供应商开给我们）" else "销项（我们开给客户）"}"
        details += if (no.isBlank()) {
            "票号：还没拿到，先空着（登记之后可以在台账里补上）"
        } else {
            "票号：$no"
        }
        details += "开票日期：$date"
        details += "价税合计：${AiWriteArgs.moneyText(amount)} 元"
        if (rate == null) {
            details += "税率：没填 —— 这是一张未税票：它照常留在台账里，但不进税汇"
        } else {
            // rate 不为空时 tax 一定算出来了（上面那个 when 只有 rate == null 才会给 null），
            // 这里写 `?: ZERO` 只是让编译器也看得出来，不是真有"有税率却没税额"的票。
            val t = tax ?: BigDecimal.ZERO
            val how = if (givenTax != null) "票面上印的数" else "按「合计 ÷ (1 + 税率)」倒推，与后端同一个算法"
            details += "税率：${AiWriteArgs.moneyText(rate)}%；税额：${AiWriteArgs.moneyText(t)} 元（$how）"
            details += "不含税金额：${AiWriteArgs.moneyText(amount - t)} 元"
        }
        if (isInput) {
            details += "供应商：$supplierLabel"
            details += "挂的采购单：" + orders.joinToString("、") { "#${it}" }
        } else {
            details += "客户：$customerLabel"
        }
        if (no.isBlank()) {
            details += "空票号不参与查重：等票号拿到之后记得补上（补之前这张票没法按号找）"
        } else {
            details += "票号一旦登记就唯一占号：同一个方向、同一个票号只能有一张票"
        }
        details += "票的「有没有税」在登记这一刻就定了：以后改不动税率 —— 要改只能作废重开一张"

        val head = if (no.isBlank()) "（票号还没拿到）" else " $no"
        val summary = "登记${if (isInput) "进项" else "销项"}票$head：${AiWriteArgs.moneyText(amount)} 元" +
            (if (rate == null) "（未税）" else "（含税 ${AiWriteArgs.moneyText(rate)}%）")
        pendingNote = "票已登记（${if (isInput) "进项" else "销项"}${if (no.isBlank()) "、票号还没填" else " $no"}、" +
            "${AiWriteArgs.moneyText(amount)} 元）"
        return card(summary, details, payload)
    }

    override suspend fun commit(payload: JsonObject, idempotencyKey: String) {
        ds.createInvoice(
            AiInvoiceDraft(
                direction = AiWriteArgs.required(payload, "direction", "方向"),
                invoiceNo = AiWriteArgs.str(payload, "invoice_no") ?: "",
                invoiceDate = AiWriteArgs.required(payload, "invoice_date", "开票日期"),
                amount = AiWriteArgs.required(payload, "amount", "价税合计"),
                taxRate = AiWriteArgs.str(payload, "tax_rate"),
                taxAmount = AiWriteArgs.str(payload, "tax_amount"),
                supplierId = longOf(payload, "supplier_id"),
                customerId = longOf(payload, "customer_id"),
                purchaseOrderIds = (payload["purchase_order_ids"] as? JsonArray)
                    ?.mapNotNull { (it as? JsonPrimitive)?.contentOrNull?.toLongOrNull() }
                    ?: emptyList(),
                note = AiWriteArgs.str(payload, "note") ?: "",
            ),
        )
    }

    override fun commitNote(): String? = pendingNote.also { pendingNote = null }
}

/** `payload` 里的编号（Long）——`AiWriteArgs.int` 是给"数量"那种小整数用的，编号走这里。 */
private fun longOf(args: JsonObject, key: String): Long? =
    (args[key] as? JsonPrimitive)?.contentOrNull?.toLongOrNull()

/**
 * 改一张发票（`PATCH /invoices/{id}`）。
 *
 * 三道门（都在后端也有，这里提前说清楚，省一次来回）：
 * 1. **只有「已登记」能改** —— 已开具（冻结）与已作废要改就作废重开一张；
 * 2. **回收站里的票改不动**（后端 `ensure_alive` 挡成 400）—— 先恢复再说；
 * 3. **「有没有税」改不了** —— 未税票加不上税率（那是重开一张的事）。
 */
internal class UpdateInvoiceHandler(
    ds: AiWriteDataSource,
    store: AiWritePreviewStore,
) : InvoiceWriteHandler(ds, store) {

    override val actionId = AiWrites.INVOICES_UPDATE

    private var pendingNote: String? = null

    override suspend fun prepare(params: JsonObject): AiWriteOutcome {
        val inv = resolveInvoice(params)
        if (inv.isDeleted) {
            throw AiWriteArgException(
                "这张票在回收站里：${label(inv)}。回收站里的票改不动 —— 先到「发票台账」页顶部切到" +
                    "「回收站」，把它恢复回来再来改。",
            )
        }
        if (inv.status != AiInvoiceRef.ST_REGISTERED) {
            throw AiWriteArgException(
                "这张票已经是「${inv.statusCn}」了，改不动。只有「已登记」状态的票能改；要改就作废重开一张。",
            )
        }

        // ⚠️ 这一条的 payload 是**边判断边攒**的（用户可能只说改两样中的一样），
        //    所以用可变 Map 攒、最后再包成 JsonObject 交给卡片；
        //    kotlinx 那套 `put(k, v)` 扩展正好也认 MutableMap<String, JsonElement>。
        val payload: MutableMap<String, JsonElement> = mutableMapOf("invoice_id" to JsonPrimitive(inv.id))
        val changes = mutableListOf<Change>()
        var amountAfter = toBig(inv.amount) ?: BigDecimal.ZERO
        var rateAfter = inv.taxRate?.let { toBig(it) }
        var taxAfter = inv.taxAmount?.let { toBig(it) }
        var taxGiven = false
        // 「用户到底说没说新值」得单独记一笔，**不能**拿 payload 的键数当依据：用户给了一个
        // 和现在一模一样的值时 payload 里不会多出键，那时该说的是"没什么可改的"，
        // 而不是"你还没说要改成什么"（两句话对用户是两件事）。
        var offered = false

        AiWriteArgs.str(params, "new_invoice_no")?.let { raw ->
            offered = true
            val next = invoiceNoOf(raw, "新票号")
            if (next != inv.invoiceNo) {
                payload["invoice_no"] = JsonPrimitive(next)
                changes += Change("票号", inv.invoiceNo.ifBlank { "（空）" }, next.ifBlank { "（空）" })
            }
        }
        dateOf(params, "new_date", "新开票日期")?.let { d ->
            offered = true
            if (d.toString() != inv.invoiceDate) {
                payload["invoice_date"] = JsonPrimitive(d.toString())
                changes += Change("开票日期", inv.invoiceDate, d.toString())
            }
        }
        AiWriteArgs.str(params, "new_amount")?.let { raw ->
            offered = true
            val v = AiWriteArgs.parseMoney(raw, "新价税合计", mustPositive = true)
            if (v.compareTo(amountAfter) != 0) {
                payload["amount"] = JsonPrimitive(AiWriteArgs.money(v))
                changes += Change("价税合计", moneyOrDash(amountAfter), moneyOrDash(v))
                amountAfter = v
            }
        }
        rateOf(params, "new_tax_rate", "新税率")?.let { v ->
            offered = true
            if (inv.untaxed) {
                throw AiWriteArgException(
                    "这张票是未税票（登记时没填税率），现在加不上税率：票的「有没有税」在登记那一刻就定了。" +
                        "要给它加税率，就作废重开一张。",
                )
            }
            if (rateAfter == null || rateAfter.compareTo(v) != 0) {
                payload["tax_rate"] = JsonPrimitive(AiWriteArgs.money(v))
                changes += Change("税率", pct(inv.taxRate), pct(v.toPlainString()))
                rateAfter = v
            }
        }
        AiWriteArgs.str(params, "new_tax_amount")?.let { raw ->
            offered = true
            if (inv.untaxed) {
                throw AiWriteArgException(
                    "这张票是未税票（登记时没填税率），不该有税额：要进税汇就作废重开一张、登记时把税率填上。",
                )
            }
            val v = AiWriteArgs.parseMoney(raw, "新税额", mustPositive = false)
            if (v > amountAfter) {
                throw AiWriteArgException(
                    "新税额（${AiWriteArgs.moneyText(v)} 元）比价税合计（${AiWriteArgs.moneyText(amountAfter)} 元）还大 —— 这两个数是不是填反了？",
                )
            }
            if (taxAfter == null || taxAfter.compareTo(v) != 0) {
                payload["tax_amount"] = JsonPrimitive(AiWriteArgs.money(v))
                changes += Change("税额", moneyOrDash(taxAfter), moneyOrDash(v))
                taxAfter = v
            }
            taxGiven = true
        }
        // 合计或税率变了、而用户**没有**显式给新税额 ⇒ 按同一算法重算（后端在「改了合计」时也是这么干的）。
        // 显式写进 payload 的好处：卡片上的数与库里存的数由同一个值产生。
        if (!taxGiven && rateAfter != null && (payload.containsKey("amount") || payload.containsKey("tax_rate"))) {
            val recomputed = taxOf(amountAfter, rateAfter)
            if (taxAfter == null || taxAfter.compareTo(recomputed) != 0) {
                payload["tax_amount"] = JsonPrimitive(AiWriteArgs.money(recomputed))
                changes += Change("税额", moneyOrDash(taxAfter), moneyOrDash(recomputed))
                taxAfter = recomputed
            }
        }
        // 备注用「键在不在」判断：键在、值是空串 = 用户要把备注清掉（后端也认这个口径）。
        if (params.containsKey("note")) {
            offered = true
            val v = noteOf(params, "note")
            if (v != inv.note) {
                payload["note"] = JsonPrimitive(v)
                changes += Change("备注", inv.note.ifBlank { "（空）" }, v.ifBlank { "（清空）" })
            }
        }

        if (changes.isEmpty()) {
            throw AiWriteArgException(
                if (!offered) {
                    "你还没说要改成什么。这张票能改：票号（new_invoice_no）、开票日期（new_date）、" +
                        "价税合计（new_amount）、税额（new_tax_amount）、备注（note）。"
                } else {
                    "你给的新值和现在一模一样，没什么可改的（这张票现在是：${label(inv)}）。"
                },
            )
        }

        val details = mutableListOf<String>()
        details += "这张票现在是：${label(inv)}"
        details += "———— 这一下改什么 ————"
        changes.forEach { details += "${it.cn}：${it.from} → ${it.to}" }
        details += "改完这张票还是「已登记」：还能接着改，也可以开具它"
        if (payload.containsKey("invoice_no")) {
            details += "票号换了之后旧号就空出来了（别的票可以再用它）"
        }
        details += "票的「有没有税」改不了：含税的票一直是含税的，未税票也一直是未税票"

        val first = changes[0]
        val summary = "改${inv.directionCn}票${noHead(inv)}：${first.cn} ${first.from} → ${first.to}" +
            (if (changes.size > 1) "（共 ${changes.size} 处）" else "")
        pendingNote = "票已改（${changes.joinToString("、") { it.cn }}）"
        return card(summary, details, JsonObject(payload))
    }

    override suspend fun commit(payload: JsonObject, idempotencyKey: String) {
        // ⚠️ 整份 changes 原样交给数据源：它只挑自己认得的键（票号/日期/合计/税率/税额/备注），
        //    `invoice_id` 是定位用的、不属于「要改的字段」。
        ds.updateInvoice(AiWriteArgs.required(payload, "invoice_id", "发票").toLong(), payload)
    }

    override fun commitNote(): String? = pendingNote.also { pendingNote = null }
}

/** 百分数在卡片上的写法：「3%」（没有「%」就补一个，绝不出现 3.00% 这种带两位小数的怪写法）。 */
private fun pct(raw: String?): String {
    val v = raw?.let { toBig(it) } ?: return "（空）"
    return AiWriteArgs.moneyText(v) + "%"
}

/**
 * 开具一张发票（`POST /invoices/{id}/issue`）。
 *
 * ⚠️ 一个常见的误解要被这张卡片按住：**开具不等于进税汇**。
 * 进税汇看的是「有没有税率、有没有作废、有没有在回收站」，登记那天起就定了；
 * 开具真正的后果是**冻结**（之后一个字都改不动）。
 */
internal class IssueInvoiceHandler(
    ds: AiWriteDataSource,
    store: AiWritePreviewStore,
) : InvoiceWriteHandler(ds, store) {

    override val actionId = AiWrites.INVOICES_ISSUE

    private var pendingNote: String? = null

    override suspend fun prepare(params: JsonObject): AiWriteOutcome {
        val inv = resolveInvoice(params)
        if (inv.isDeleted) {
            throw AiWriteArgException(
                "这张票在回收站里：${label(inv)}。先恢复出来，再开具。",
            )
        }
        when (inv.status) {
            AiInvoiceRef.ST_ISSUED -> throw AiWriteArgException(
                "这张票已经开具过了（${label(inv)}）。",
            )
            AiInvoiceRef.ST_VOIDED -> throw AiWriteArgException(
                "这张票已经作废了，作废的票不能再开具；要重开就新登记一张。",
            )
        }
        val payload = buildJsonObject { put("invoice_id", inv.id) }
        val details = mutableListOf<String>()
        details += "这张票：${label(inv)}"
        details += "真实世界里这一下对应的是：票已经开出去、寄给对方了"
        details += "开具之后这张票就冻结了：一个字都改不动（要改只能作废重开一张）"
        details += if (inv.untaxed) {
            "它进不进税汇和「开没开」无关：这张是未税票，一直不进税汇"
        } else {
            "它进不进税汇和「开没开」无关：这张有税率，登记那天起就已经在税汇里了"
        }
        pendingNote = "票已开具（${label(inv)}）"
        return card("开具${inv.directionCn}票${noHead(inv)}：${AiWriteArgs.moneyText(inv.amount)} 元", details, payload)
    }

    override suspend fun commit(payload: JsonObject, idempotencyKey: String) {
        ds.issueInvoice(AiWriteArgs.required(payload, "invoice_id", "发票").toLong())
    }

    override fun commitNote(): String? = pendingNote.also { pendingNote = null }
}

/**
 * 作废一张发票（`POST /invoices/{id}/void`）。
 *
 * 作废是**留在台账里**的那种「不算数」：票还在、票号一直占着、只是退出税汇。
 * 与撤票（进回收站）不是一件事，卡片必须把两者的差别写出来。
 */
internal class VoidInvoiceHandler(
    ds: AiWriteDataSource,
    store: AiWritePreviewStore,
) : InvoiceWriteHandler(ds, store) {

    override val actionId = AiWrites.INVOICES_VOID

    private var pendingNote: String? = null

    override suspend fun prepare(params: JsonObject): AiWriteOutcome {
        val inv = resolveInvoice(params)
        if (inv.isDeleted) {
            throw AiWriteArgException(
                "这张票在回收站里：${label(inv)}。作废一个已经在回收站里的票没有意义 —— 要留痕就先恢复它、再作废。",
            )
        }
        if (inv.status == AiInvoiceRef.ST_VOIDED) {
            throw AiWriteArgException("这张票已经作废过了（${label(inv)}）。")
        }
        val payload = buildJsonObject { put("invoice_id", inv.id) }
        val details = mutableListOf<String>()
        details += "这张票：${label(inv)}"
        details += "作废之后：票还留在台账里（作废是一个状态，不是删掉）、票号一直占着、退出税汇"
        if (inv.untaxed) {
            details += "它本来就是未税票（不进税汇），所以作废只影响一件事：这张票从此不能再开具"
        } else {
            details += "税账上的变化：销项 / 进项合计里不再算它，它的税额也不再算"
        }
        if (inv.status == AiInvoiceRef.ST_ISSUED) {
            details += "它现在是「已开具」：作废是已开具的票唯一的出路（开具之后本来也改不动了）"
        }
        details += "作废撤不回来；要重开就新登记一张（同一张票号只能登记一次）"
        details += "它和「撤票」不是一件事：撤票是进回收站（列表里看不见、可以原样恢复）；作废是留在台账里、不可逆"
        pendingNote = "票已作废（${label(inv)}）"
        return card("作废${inv.directionCn}票${noHead(inv)}：${AiWriteArgs.moneyText(inv.amount)} 元", details, payload)
    }

    override suspend fun commit(payload: JsonObject, idempotencyKey: String) {
        ds.voidInvoice(AiWriteArgs.required(payload, "invoice_id", "发票").toLong())
    }

    override fun commitNote(): String? = pendingNote.also { pendingNote = null }
}

/**
 * 撤票：把一张票放进回收站（`DELETE /invoices/{id}`，软删）。
 *
 * 三条容易被忽略的事实，卡片都要写：
 * 1. **票号还占着**（同一张票再登记一次会被后端拒掉）；
 * 2. **回收站里的票一律不算进税汇**（后端的 `counts_in_tax` 第一句就是 `is_deleted → False`），
 *    恢复回来之后照原样算（有税率就重新进税汇）；
 * 3. 它**不再挡着**采购单删除（后端判「挂着没作废的进项票」时不看回收站里的票），
 *    但真正的正路是作废那张票，而不是把它藏起来。
 */
internal class DeleteInvoiceHandler(
    ds: AiWriteDataSource,
    store: AiWritePreviewStore,
) : InvoiceWriteHandler(ds, store) {

    override val actionId = AiWrites.INVOICES_DELETE

    private var pendingNote: String? = null

    override suspend fun prepare(params: JsonObject): AiWriteOutcome {
        val inv = resolveInvoice(params)
        if (inv.isDeleted) {
            throw AiWriteArgException("这张票已经在回收站里了（${label(inv)}）。")
        }
        val payload = buildJsonObject { put("invoice_id", inv.id) }
        val details = mutableListOf<String>()
        details += "这张票：${label(inv)}"
        details += "撤票 = 放进回收站：台账列表里默认看不见它了"
        details += "但票号仍然占着 —— 同一张票再登记一次会被后端拒掉（号没释放）"
        details += "放回去随时可以：聊天里那条结果消息上会有一个「撤回」，点它、再确认一次就恢复 —— " +
            "票号、日期、金额、税额、备注都会原样回来"
        details += if (inv.untaxed) {
            "税汇上没什么变化：它本来就是未税票，不进税汇"
        } else {
            "税汇上的变化：回收站里的票一律不算数（它退出税汇）；恢复回来就照原样算"
        }
        details += "它和「作废」不是一件事：作废留在台账里、不可逆；撤票进回收站、可原样恢复"
        details += "如果这是挂在采购单上的进项票：撤票之后那张单就能删了（回收站里的票不算挂着）—— " +
            "但更干净的做法是作废它，别把票藏起来"
        pendingNote = "票已撤（${label(inv)}）"
        return card("撤票（进回收站）${inv.directionCn}票${noHead(inv)}：${AiWriteArgs.moneyText(inv.amount)} 元", details, payload)
    }

    override suspend fun commit(payload: JsonObject, idempotencyKey: String) {
        ds.deleteInvoice(AiWriteArgs.required(payload, "invoice_id", "发票").toLong())
    }

    override fun commitNote(): String? = pendingNote.also { pendingNote = null }
}
