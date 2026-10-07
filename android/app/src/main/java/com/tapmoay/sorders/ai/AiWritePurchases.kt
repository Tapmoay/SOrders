package com.tapmoay.sorders.ai

import com.tapmoay.sorders.data.remote.dto.PurchaseOrderDto
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import java.math.BigDecimal
import java.math.RoundingMode
import java.time.LocalDate

/**
 * **一张进货单照片（或挂进来的表格）→ 一张采购单**（CHG-0074 / 台账 L-42）。
 *
 * ### 为什么表格必须由 App 解析，而不是让模型拆成参数
 * 与 [AiProductTable] / [AiPriceTable] 同一个理由：只要模型**必须重打一遍**，
 * 就多一次出错的机会，而漏行、串列、把"金额"当"单价"**在卡片上看起来都是对的**。
 * 让模型把单子上的表**原样**放进 "rows"，由这里的确定性解析器读，好处是三件事：
 * 1. 解析器是纯函数、能单测（模型不是）；
 * 2. 卡片上写的是"我读到的 N 行、分别是什么"，用户能和自己那张单子逐行对上；
 * 3. 读不出来的行**带行号**报错，模型据此能问得很具体。
 *
 * ### 这一张单会同时改三处钱的事实（这就是它的全部价值）
 * 建单 = 库存「+数量」、这几个商品的**成本价**按这一单重算、供应商**欠款 + 合计**
 * —— 三件事由后端 purchase_service 在**同一个事务**里落（见 [AiWriteDataSource.createPurchaseOrder]）。
 * ⛔ AI 不自己拼这三步，也**不写** "inventory_movements"：入库记录由那次入库**自然产生**，
 * AI 只负责读（用户口径 m13365 ⑤：「入库记录不用 AI 搞」= 就是那个意思）。
 *
 * ### 三条"宁可拒绝也不猜"
 * 1. **认不出哪一列是商品名 / 数量 / 单价** → 整张卡不发（靠表头认列；认不出就报错，
 *    绝不"按第一列猜"——猜错就是把单价写成商品名，而用户要翻 30 行才发现）。
 * 2. **一行读不出来** → 整张卡不发（部分成功的批量最难核对：用户不会去数少了几行）。
 * 3. **表里的商品名在名册里找不到** → 整张卡不发，如实说"名册里没有这个商品，先建商品"。
 *
 * ### 撤回：建单没有"一键撤回"，但**有出路**
 * 新建出来的那一条在写之前**没有编号**，所以给不出可回滚的快照（见 AiRevert.kt 的既有口径）。
 * 这一条不是"撤不回来"就完事：卡片完成后会**点名**那条出路 —— 说一句「撤掉采购单 #N」
 * → 走 [AiWrites.PURCHASE_ORDERS_DELETE]，冲库存 ＋ 撤应付 ＋ 重算成本价。
 */
internal object AiPurchaseTable {

    /** 一次最多读几行。与建商品/调价表同一个折中：30 行"能一眼核对完 + 不会连打几十个请求"。 */
    const val MAX_ROWS = 30

    /** 商品名长度上限（与商品档案上的 name 一致）。 */
    const val MAX_NAME = 64

    /** 数量上限（与 [AiWriteArgs.MAX_QUANTITY] 同源，不另立一个数）。 */
    val MAX_QUANTITY: Int = AiWriteArgs.MAX_QUANTITY

    /** 单价上限（超过一定是多打了零）。 */
    val MAX_PRICE: BigDecimal = AiWriteArgs.MAX_AMOUNT

    /** 表里的一行。数量与单价都**必须**有：进货单没有"多少钱"就不叫进货单。 */
    data class Row(
        val lineNo: Int,
        val name: String,
        val quantity: Int,
        val unitPrice: BigDecimal,
    ) {
        /** 这一行的金额（数量 × 单价）。只用于在卡片上给用户核对。 */
        val amount: BigDecimal
            get() = unitPrice.multiply(BigDecimal(quantity)).setScale(2, RoundingMode.HALF_UP)
    }

    /** 解析结果 + 那些"要说给用户听"的话（例如"表里的单位列没有写进去"）。 */
    data class Parsed(val rows: List<Row>, val notes: List<String>) {
        /** 合计（卡片上要写它，供应商欠款 + 的就是这个数）。 */
        val total: BigDecimal
            get() = rows.fold(BigDecimal.ZERO) { acc, r -> acc.add(r.amount) }.setScale(2, RoundingMode.HALF_UP)
    }

    // ------------------------------------------------------------------ 列名
    private val NAME_WORDS = listOf("商品", "商品名", "品名", "名称", "产品", "产品名", "货名", "货品", "名字")
    private val QTY_WORDS = listOf("数量", "件数", "数目", "进货量", "入库量", "本次数量")
    private val PRICE_WORDS = listOf("单价", "进货价", "进价", "价格", "单价(元)", "单价（元）")
    /** 认出来但**不会写进去**的列：光是"认出来了"不够，还要在卡片上说清楚为什么。 */
    private val IGNORED_WORDS = listOf(
        "单位", "规格", "计量单位",
        "金额", "小计", "合计", "总额", "总价",
        "备注", "编码", "条码", "序号", "货号",
    )

    /**
     * 把一张表读成若干行。
     *
     * @throws AiWriteArgException 读不出来时（message 里带**行号**与那一行的原文）
     */
    fun parse(text: String): Parsed {
        val lines = AiTable.splitCells(text)
        if (lines.isEmpty()) {
            throw AiWriteArgException(
                "这张单子我一行内容都没读到。请让用户把表格**原样**放进 rows" +
                    "（一行一条，列之间用 Tab/逗号/竖线/多个空格分开都行）。",
            )
        }
        val header = lines.firstOrNull { it.cells.any { c -> c.isNotBlank() } }
            ?: throw AiWriteArgException("这张单子是空的。")
        val cols = mapColumns(header.cells)

        val body = lines.dropWhile { it.lineNo <= header.lineNo }.filter { it.cells.any { c -> c.isNotBlank() } }
        if (body.isEmpty()) {
            throw AiWriteArgException(
                "我只读到一行表头「" + header.cells.joinToString(" | ") + "」，后面没有数据行。" +
                    "请让用户把表头和内容一起放进来。",
            )
        }
        if (body.size > MAX_ROWS) {
            throw AiWriteArgException(
                "这张单子有 " + body.size + " 行数据，超过一次 " + MAX_ROWS + " 行的上限。" +
                    "请让用户分批来（先做前 " + MAX_ROWS + " 行），或者去「库存管理 → 采购单」页面上建。",
            )
        }

        val notes = ArrayList<String>(2)
        cols.ignored.forEach { (idx, label) ->
            val sample = body.firstNotNullOfOrNull { it.cells.getOrNull(idx)?.trim()?.takeIf { s -> s.isNotEmpty() } }
            notes += ignoredNote(label, sample)
        }

        val rows = ArrayList<Row>(body.size)
        val seen = HashMap<String, Int>()
        for (r in body) {
            try {
                rows += readRow(r, cols, seen)
            } catch (e: AiWriteArgException) {
                // ⚠️ **只有这一处**给错误补"第几行 + 那一行原文"（与 AiProductTable 同一处分寸）：
                // 模型和用户手里唯一能定位的信息就是这两样，而 [readRow] 里的每一处校验都不带行号。
                val rowText = r.cells.joinToString(" | ")
                throw AiWriteArgException(
                    "表格第 " + r.lineNo + " 行读不出来：" + e.message + "。那一行原文是「" + rowText + "」。",
                    e.candidates,
                )
            }
        }
        if (rows.isEmpty()) throw AiWriteArgException("这张单子里没有可进货的行。")
        return Parsed(rows, notes)
    }

    /** 那些"认出来了但不会写进去"的列，各自说一句**为什么**（静默丢掉一列比报错更糟）。 */
    private fun ignoredNote(label: String, sample: String?): String {
        val what = sample?.let { "如「" + it + "」" } ?: "整列都是空的"
        val n = AiWriteArgs.norm(label)
        return when {
            n.contains(AiWriteArgs.norm("单位")) || n.contains(AiWriteArgs.norm("规格")) ->
                "表里的「" + label + "」列没有写进去（" + what + "）：系统按商品档案上的单位记，" +
                    "要改单位请去「商品管理 → 编辑」。"
            n.contains(AiWriteArgs.norm("金额")) || n.contains(AiWriteArgs.norm("小计")) ||
                n.contains(AiWriteArgs.norm("合计")) || n.contains(AiWriteArgs.norm("总")) ->
                "表里的「" + label + "」列没有写进去（" + what + "）：金额由系统按 数量 × 单价 自己算，" +
                    "所以单子上写错了也不影响入库。"
            else ->
                "表里的「" + label + "」列没有写进去（" + what + "）：这张单只认 商品名 / 数量 / 单价 三列。"
        }
    }

    /**
     * 读一行。**抛出的信息里不带行号**——补行号是调用方的事（见上面那段 catch）。
     */
    private fun readRow(r: AiTable.Line, cols: Cols, seen: MutableMap<String, Int>): Row {
        fun cell(i: Int?): String? = i?.let { r.cells.getOrNull(it) }?.trim()?.takeIf { it.isNotEmpty() }

        val raw = cell(cols.name) ?: throw AiWriteArgException("没读到商品名")
        if (raw.length > MAX_NAME) {
            throw AiWriteArgException("商品名太长（" + raw.length + " 字，上限 " + MAX_NAME + "）：" + raw)
        }
        val qty = cell(cols.qty)?.let { parseCount(it) }
            ?: throw AiWriteArgException("这一行没写数量")
        val price = cell(cols.price)?.let { parsePrice(it) }
            ?: throw AiWriteArgException("这一行没写单价（进货价）")

        val dupAt = seen[raw]
        if (dupAt != null) {
            throw AiWriteArgException(
                "「" + raw + "」在这一张单上出现了两次（上一次在第 " + dupAt + " 行）。" +
                    "同一个商品请合成一行，或者分成两张单 —— 同一张单上写两遍，库存会进两次。",
            )
        }
        seen[raw] = r.lineNo
        return Row(r.lineNo, raw, qty, price)
    }

    // ------------------------------------------------------------------ 认列
    private data class Cols(
        val name: Int,
        val qty: Int?,
        val price: Int?,
        /** 认出来但不会写进去的列（下标 → 原始表头词）。 */
        val ignored: List<Pair<Int, String>>,
    )

    /**
     * 按表头认列。**认不出商品名列就报错**，不猜：这是"整张卡不发"的第一条。
     * 表头匹配是"归一后包含"（"商品名称"能命中"商品名"），因为真实表头写法五花八门。
     */
    private fun mapColumns(header: List<String>): Cols {
        val norm = header.map { AiWriteArgs.norm(it) }
        fun find(words: List<String>): Int? = norm.indexOfFirst { h ->
            h.isNotEmpty() && words.any { w -> h == AiWriteArgs.norm(w) }
        }.takeIf { it >= 0 } ?: norm.indexOfFirst { h ->
            h.isNotEmpty() && words.any { w -> h.contains(AiWriteArgs.norm(w)) }
        }.takeIf { it >= 0 }

        val name = find(NAME_WORDS)
        if (name == null) {
            throw AiWriteArgException(
                "这张单子的第一行「" + header.joinToString(" | ") + "」里我认不出哪一列是**商品名**。" +
                    "请让用户把表头写成「商品名 / 数量 / 单价」这样的写法，或者直接告诉我哪一列是商品名。" +
                    "**不要自己猜** —— 猜错会把单价写成商品名。",
            )
        }
        val qty = find(QTY_WORDS)
            ?: throw AiWriteArgException(
                "这张单子的表头「" + header.joinToString(" | ") + "」里我认不出哪一列是**数量**。" +
                    "没有数量就不知道要进多少货，请让用户把数量列写清楚。",
            )
        val price = find(PRICE_WORDS)
            ?: throw AiWriteArgException(
                "这张单子的表头「" + header.joinToString(" | ") + "」里我认不出哪一列是**单价**（进货价）。" +
                    "没有单价就没法记成本，请让用户把单价列写清楚。",
            )
        val used = setOfNotNull(name, qty, price)
        val ignored = norm.mapIndexedNotNull { i, h ->
            if (i in used || h.isEmpty()) null
            else IGNORED_WORDS.firstOrNull { h.contains(AiWriteArgs.norm(it)) }?.let { i to header[i].trim() }
        }
        return Cols(name, qty, price, ignored)
    }

    // ------------------------------------------------------------------ 数值
    private fun parsePrice(raw: String): BigDecimal {
        val cleaned = raw.trim()
            .replace(",", "").replace("，", "")
            .removeSuffix("元").removeSuffix("块").removePrefix("¥").removePrefix("￥").trim()
        val v = cleaned.toBigDecimalOrNull()
            ?: throw AiWriteArgException("单价「" + raw + "」不是数字")
        if (v.signum() <= 0) {
            throw AiWriteArgException("单价是 " + v.toPlainString() + "：进货价必须大于 0（这一行多少钱进的？）")
        }
        if (v > MAX_PRICE) {
            throw AiWriteArgException(
                "单价是 " + v.toPlainString() + "，超过 " + MAX_PRICE.toPlainString() + " 的上限 ——" +
                    "这个数看着像多打了几个零，请让用户先核对",
            )
        }
        return v.setScale(2, RoundingMode.HALF_UP)
    }

    private fun parseCount(raw: String): Int {
        val cleaned = raw.trim().replace(",", "").replace("，", "")
            .removeSuffix("件").removeSuffix("个").removeSuffix("箱")
            .removeSuffix("袋").removeSuffix("桶").removeSuffix("包").trim()
        val v = cleaned.toIntOrNull()?.takeIf { it >= 1 }
            ?: throw AiWriteArgException("数量「" + raw + "」不是正整数")
        if (v > MAX_QUANTITY) {
            throw AiWriteArgException("数量是 " + v + "，超过 " + MAX_QUANTITY + " 的上限，请先核对")
        }
        return v
    }
}

/**
 * 采购单的一行（AI 侧的说法）。
 *
 * 为什么不让数据源直接收 DTO：**单测里的假数据源**（"AiWriteTest.FakeDs"）要能实现这个接口，
 * 而 DTO 是网络层的形状（序列化注解、字段默认值都会跟着渗进测试）。
 * ⛔ 行 id 刻意**不在这里**：本动作只建单，改行一律走"撤单重开"
 * （后端 _apply_items 是整份替换语义，把行 id 塞进撤回快照会让"撤回每一行旧值"变成最危险的形状）。
 */
data class AiPurchaseLine(
    val productId: Long,
    val quantity: Int,
    /** 这一行进货的单价（payload 里的 "unit_cost"，字符串两位小数）。 */
    val unitCost: String,
)

/**
 * 「按一张进货单建采购单」的处理器。
 *
 * 结构上与 [ApplyProductTableHandler] 一模一样（解析 → 逐行对着名册核对 → 一张卡 → 执行完如实汇报），
 * 因为面对的是同一类问题：**用户手里那张单子上的每一行都必须先读对，才能往下走**。
 */
class CreatePurchaseOrderHandler(
    private val ds: AiWriteDataSource,
    private val store: AiWritePreviewStore,
) : AiWriteHandler {

    override val actionId = AiWrites.PURCHASE_ORDERS_CREATE

    /** 执行完之后补的那句话（一次性：取走即清空）。见 [AiWriteHandler.commitNote]。 */
    private var pendingNote: String? = null

    override fun commitNote(): String? = pendingNote.also { pendingNote = null }

    override suspend fun prepare(params: JsonObject): AiWriteOutcome {
        val text = AiWriteArgs.required(
            params,
            "rows",
            "把那张进货单上的表格**原样**放进 rows（一行一条，含表头那一行：商品名 / 数量 / 单价）。" +
                "没有单子就别用这个动作。",
        )
        val parsed = AiPurchaseTable.parse(text)

        val supplierRaw = AiWriteArgs.required(params, "supplier", "这张进货单是谁开的（供应商/厂商的名字）")
        val roster = ds.suppliers()
        val supplier = roster.firstOrNull { AiWriteArgs.norm(it.label) == AiWriteArgs.norm(supplierRaw) }
            ?: return AiWriteOutcome.Rejected(
                "供应商/厂商名册里没有「" + supplierRaw + "」。请先确认名字（名册里没有的话，" +
                    "我可以用「新增供应商/厂商」把他建出来），再回来建这张单。",
                roster.take(5).map { it.label },
            )

        val docDate = AiWriteArgs.str(params, "doc_date")?.let { purchaseDate(it) } ?: LocalDate.now().toString()
        val remark = AiWriteArgs.str(params, "remark").orEmpty()

        // 逐行把单子上的商品名对到名册上：**对不上就整张卡不发**（宁可拒绝也不猜）。
        val byName = ds.products().associateBy { AiWriteArgs.norm(it.label) }
        val lines = ArrayList<Pair<AiName, AiPurchaseTable.Row>>(parsed.rows.size)
        val missing = ArrayList<String>(2)
        parsed.rows.forEach { r ->
            val hit = byName[AiWriteArgs.norm(r.name)]
            if (hit == null) missing += r.name else lines += hit to r
        }
        if (missing.isNotEmpty()) {
            return AiWriteOutcome.Rejected(
                "名册里没有这些商品：" + missing.joinToString("、") +
                    "。请先建商品（可以让我按表格建商品），再回来建这张单 —— " +
                    "进货必须挂在已有商品上，否则库存与成本价没有地方落。",
                missing.take(5),
            )
        }

        val total = parsed.total
        val details = ArrayList<String>(lines.size + 12)
        details += "供应商：" + supplier.label
        details += "单据日期：" + docDate
        details += "这一单：" + lines.size + " 行，合计 " + AiWriteArgs.moneyText(total) + " 元"
        parsed.notes.forEach { details += "⚠️ " + it }
        details += "———— 这一单要进的货 ————"
        lines.take(MAX_LISTED).forEach { (p, r) -> details += lineText(p.label, r) }
        if (lines.size > MAX_LISTED) details += "…… 还有 " + (lines.size - MAX_LISTED) + " 行，未逐条列出"
        details += "———— 保存之后（三件事一起落）————"
        details += "· 库存：" + lines.take(MAX_LISTED).joinToString("、") { (p, r) -> p.label + " +" + r.quantity } +
            "（后端同一个事务里入的）"
        details += "· 成本价：这几个商品的成本价按这一单重算"
        details += "· 供应商欠款：「" + supplier.label + "」的应付 +" + AiWriteArgs.moneyText(total) + " 元"
        if (remark.isNotEmpty()) details += "备注：" + remark

        val payload = buildJsonObject {
            put("supplier_id", supplier.id)
            put("supplier_label", supplier.label)
            put("doc_date", docDate)
            put("remark", remark)
            put("rows", buildJsonArray {
                lines.forEach { (p, r) ->
                    add(
                        buildJsonObject {
                            put("product_id", p.id)
                            put("product_label", p.label)
                            put("line_no", r.lineNo)
                            put("quantity", r.quantity)
                            put("unit_cost", AiWriteArgs.money(r.unitPrice))
                        },
                    )
                }
            })
        }
        return AiWriteOutcome.NeedConfirm(
            store.card(
                actionId,
                summary = "按这张进货单建采购单：" + supplier.label + "，" + lines.size + " 行，合计 " +
                    AiWriteArgs.moneyText(total) + " 元",
                detailLines = details,
                payload = payload,
            ),
        )
    }

    override suspend fun commit(payload: JsonObject, idempotencyKey: String) {
        val rowObjs = (payload["rows"] as? JsonArray).orEmpty().mapNotNull { it as? JsonObject }
        val lines = rowObjs.map {
            AiPurchaseLine(
                productId = it.reqLong("product_id"),
                quantity = it.reqInt("quantity"),
                unitCost = AiWriteArgs.str(it, "unit_cost").orEmpty(),
            )
        }
        if (lines.isEmpty()) {
            pendingNote = "这次没有要进的货（内部错误），什么都没写。"
            return
        }
        val supplierId = payload.reqLong("supplier_id")
        val docDate = AiWriteArgs.str(payload, "doc_date").orEmpty()
        val remark = AiWriteArgs.str(payload, "remark").orEmpty()
        pendingNote = try {
            val id = ds.createPurchaseOrder(supplierId = supplierId, docDate = docDate, remark = remark, lines = lines)
            "采购单 #" + id + " 建好了：" + lines.size + " 行进库，库存、成本价、供应商欠款三处都跟着落了。" +
                "这一单撤不回来（新建的单在写之前没有编号），要撤就跟我说一句「撤掉采购单 #" + id + "」。"
        } catch (e: kotlinx.coroutines.CancellationException) {
            throw e
        } catch (e: Exception) {
            "建采购单没成功（什么都没写）：" + (e.message ?: e.javaClass.simpleName)
        }
    }

    private companion object {
        /** 卡片上逐行列出几行；超过就只写"还有几行"（30 行的卡没人看得完，但合计一定要在）。 */
        const val MAX_LISTED = 12
    }
}

/**
 * 「改这张采购单的单头」的处理器（供应商 / 单据日期 / 备注三样）。
 *
 * ⛔ **改行不在这里**：后端采购服务的 _apply_items 是整份替换语义（没出现的行算撤行），
 * 要改数量或单价请「撤单重开」—— 那一条写进了变更单的 Known Limitations。
 */
class UpdatePurchaseOrderHandler(
    private val ds: AiWriteDataSource,
    private val store: AiWritePreviewStore,
) : AiWriteHandler {

    override val actionId = AiWrites.PURCHASE_ORDERS_UPDATE

    private var pendingNote: String? = null

    override fun commitNote(): String? = pendingNote.also { pendingNote = null }

    override suspend fun prepare(params: JsonObject): AiWriteOutcome {
        val rawOrder = AiWriteArgs.str(params, "order")
            ?: return AiWriteOutcome.Rejected("要改哪一张采购单？请给我单号（例如「采购单 #12」）。")
        val orderId = purchaseOrderNo(rawOrder)
            ?: return AiWriteOutcome.Rejected(
                "单号「" + rawOrder + "」我看不懂：请给我数字，例如「采购单 #12」。" +
                    "拿不准就先让我查一下「采购单」这一栏。",
            )
        val current = readOrder(ds, orderId) ?: return notFound(orderId)
        if (current.isDeleted) {
            return AiWriteOutcome.Rejected(
                "采购单 #" + orderId + " 现在是「已撤单」状态，单头也改不了。" +
                    "要改就先让我把它恢复回来（撤回入口里那条「恢复采购单」）。",
            )
        }

        val newSupplier = AiWriteArgs.str(params, "supplier")
        val roster = if (newSupplier == null) emptyList() else ds.suppliers()
        val supplier = newSupplier?.let { name ->
            roster.firstOrNull { AiWriteArgs.norm(it.label) == AiWriteArgs.norm(name) }
                ?: return AiWriteOutcome.Rejected(
                    "供应商/厂商名册里没有「" + name + "」，这一条改不了。",
                    roster.take(5).map { it.label },
                )
        }
        val supplierId = supplier?.id ?: current.supplierId
        val supplierLabel = supplier?.label ?: current.supplierName
        val docDate = AiWriteArgs.str(params, "doc_date")?.let { purchaseDate(it) } ?: current.docDate
        val remark = AiWriteArgs.str(params, "remark") ?: current.remark

        if (supplierId == current.supplierId && docDate == current.docDate && remark == current.remark) {
            return AiWriteOutcome.Rejected(
                "这三样跟现在一模一样（供应商 / 单据日期 / 备注），我没有要改的东西。你想改的是哪一样？",
            )
        }

        val details = ArrayList<String>(6)
        details += "采购单 #" + orderId + "（" + current.itemCount + " 行）"
        details += "———— 只改这三样 ————"
        if (supplierId != current.supplierId) details += "· 供应商：" + current.supplierName + " → " + supplierLabel
        if (docDate != current.docDate) details += "· 单据日期：" + current.docDate + " → " + docDate
        if (remark != current.remark) {
            details += "· 备注：" + (current.remark.ifEmpty { "（空）" }) + " → " + (remark.ifEmpty { "（空）" })
        }
        details += "这张单进了哪些货、每行进价多少，一律不动"
        details += "要改数量或单价，请先撤单再重开一张（后端换行是整份替换，改一行等于重写整张单）"

        val payload = buildJsonObject {
            put("order_id", orderId)
            put("supplier_id", supplierId)
            // ⛔ 供应商的**名字**不进 payload：撤回是"把 payload 里的键写回旧值"，
            //    而名字不在这个资源的 readKeys 里 —— 放进来只会在撤回卡上多一行读不懂的裸键
            //    （名字只进上面的卡片正文）。
            put("doc_date", docDate)
            put("remark", remark)
        }
        return AiWriteOutcome.NeedConfirm(
            store.card(
                actionId,
                summary = "改采购单 #" + orderId + " 的单头",
                detailLines = details,
                payload = payload,
            ),
        )
    }

    override suspend fun commit(payload: JsonObject, idempotencyKey: String) {
        val orderId = payload.reqLong("order_id")
        pendingNote = try {
            ds.updatePurchaseOrderHead(
                orderId = orderId,
                supplierId = payload.reqLong("supplier_id"),
                docDate = AiWriteArgs.str(payload, "doc_date").orEmpty(),
                remark = AiWriteArgs.str(payload, "remark").orEmpty(),
            )
            "采购单 #" + orderId + " 的单头改好了（供应商 / 单据日期 / 备注），这张单的货与钱没动。"
        } catch (e: kotlinx.coroutines.CancellationException) {
            throw e
        } catch (e: Exception) {
            "单头没改成（什么都没写）：" + (e.message ?: e.javaClass.simpleName)
        }
    }
}

/**
 * 「撤掉这张采购单」的处理器 = DELETE /purchase-orders/{id}：**冲库存 ＋ 撤应付 ＋ 重算成本价**。
 *
 * ⛔ 卡片上**不写单价与合计**：撤单是库存与欠款的事，而成本/进货价是成本开关后面的东西
 * —— 开关关着的人不该从这张卡上看到钱（用户口径 m13365 ③ 不破例）。
 */
class DeletePurchaseOrderHandler(
    private val ds: AiWriteDataSource,
    private val store: AiWritePreviewStore,
) : AiWriteHandler {

    override val actionId = AiWrites.PURCHASE_ORDERS_DELETE

    private var pendingNote: String? = null

    override fun commitNote(): String? = pendingNote.also { pendingNote = null }

    override suspend fun prepare(params: JsonObject): AiWriteOutcome {
        val rawOrder = AiWriteArgs.str(params, "order")
            ?: return AiWriteOutcome.Rejected("要撤哪一张采购单？请给我单号（例如「撤掉采购单 #12」）。")
        val orderId = purchaseOrderNo(rawOrder)
            ?: return AiWriteOutcome.Rejected(
                "单号「" + rawOrder + "」我看不懂：请给我数字，例如「撤掉采购单 #12」。" +
                    "拿不准就先让我查一下「采购单」这一栏。",
            )
        val current = readOrder(ds, orderId) ?: return notFound(orderId)
        if (current.isDeleted) {
            return AiWriteOutcome.Rejected("采购单 #" + orderId + " 已经是「已撤单」状态，不用再撤一次。")
        }

        val details = ArrayList<String>(8)
        details += "采购单 #" + orderId + " · 供应商「" + current.supplierName + "」 · " + current.docDate +
            " · " + current.itemCount + " 行"
        details += "———— 撤单之后（三件事一起回滚，后端同一个事务）————"
        details += "· 库存：这张单进过的货，按原数量冲回去"
        details += "· 成本价：这几个商品的成本价按剩下的进货记录重算"
        details += "· 供应商欠款：「" + current.supplierName + "」身上这张单带来的应付，一起撤回"
        details += "这一单每行多少钱、整单多少钱，卡片上不写：进货价只在成本开关打开时才进 AI 对话"
        details += "撤错了可以让我恢复它（恢复＝按原样再落一遍上面这三件事）"
        return AiWriteOutcome.NeedConfirm(
            store.card(
                actionId,
                summary = "撤掉采购单 #" + orderId,
                detailLines = details,
                payload = buildJsonObject { put("order_id", orderId) },
            ),
        )
    }

    override suspend fun commit(payload: JsonObject, idempotencyKey: String) {
        val orderId = payload.reqLong("order_id")
        pendingNote = try {
            ds.deletePurchaseOrder(orderId)
            "采购单 #" + orderId + " 撤了：进过的货冲回库存、这张单的应付撤回、成本价重算过。" +
                "撤错了跟我说一声，我把它恢复回来。"
        } catch (e: kotlinx.coroutines.CancellationException) {
            throw e
        } catch (e: Exception) {
            "撤单没成功（什么都没动）：" + (e.message ?: e.javaClass.simpleName)
        }
    }
}

/** [AiPurchaseTable] 里的一行在卡片上的写法（数量与单价都是**读到**的那个数）。 */
private fun lineText(label: String, r: AiPurchaseTable.Row): String =
    "· " + label + " × " + r.quantity + " × " + AiWriteArgs.moneyText(r.unitPrice) +
        " = " + AiWriteArgs.moneyText(r.amount)

/** 读一张采购单的现状；读不到返回 null（**不编造**）。 */
private suspend fun readOrder(ds: AiWriteDataSource, orderId: Int): PurchaseOrderDto? = try {
    ds.purchaseOrder(orderId.toLong())
} catch (e: kotlinx.coroutines.CancellationException) {
    throw e
} catch (e: Exception) {
    null
}

private fun notFound(orderId: Int): AiWriteOutcome.Rejected = AiWriteOutcome.Rejected(
    "读不到编号 " + orderId + " 的采购单（可能已经撤掉了，或者单号写错了）。" +
        "可以先让我查一下「采购单」这一栏，看它现在的单号。",
)

/** 单据日期只收 YYYY-MM-DD（后端 doc_date 是 date 类型；写错会变成 422 那种英文报错）。 */
/**
 * 从用户/模型给的字里取出单号："12"、"#12"、"采购单 12"、"第 12 号" 都认。
 *
 * ⚠️ 参数名叫 order（不是 order_id）：写动作的参数表里不许出现像编号的键名 ——
 * 那等于把"编造一个编号"的机会交给模型（AiWriteTest「任何动作的参数里都没有编号字段」钉着）。
 */
private fun purchaseOrderNo(raw: String): Int? =
    raw.filter { it.isDigit() }.toIntOrNull()?.takeIf { it > 0 }

private fun purchaseDate(raw: String): String {
    val s = raw.trim()
    if (!Regex("[0-9]{4}-[0-9]{2}-[0-9]{2}").matches(s)) {
        throw AiWriteArgException("单据日期「" + raw + "」我看不懂，请写成 2026-10-07 这样的格式。")
    }
    return s
}

/**
 * AI 写动作域「采购单」（CHG-0074）。四个动作 + 一个撤回资源条目，**调用**既有后端端点。
 *
 * ### 为什么角色只给派单员
 * 事实依据（不是我们自己定的）：后端采购单那四个写端点都要 Permission.LEDGER_EDIT，
 * 而 backend/app/core/rbac.py 里只有派单员同时有 PRODUCT_MANAGE 与 LEDGER_EDIT；
 * 货主一个都没有 —— 与「库存管理」页面上"货主连这一页都进不去"是同一件事。
 *
 * ### 为什么建单/撤单是手写处理器
 * 建单要先把**用户手里那张单子**读成确定的行（[AiPurchaseTable]），再对着名册逐行核对 ——
 * 声明式的字段类型里没有"一张表"，也没有"逐行对名册"这一步（与 products.apply_table 同一个解法）。
 * 撤单也是手写：卡片要写明"撤了之后三件事一起回滚"，而且**不能**出现钱。
 */
internal object AiWritePurchases {

    /** 这四个动作的角色（见对象头那段事实依据）：只给派单员，货主一个都没有。 */
    private val ROLES: Set<AiRole> = setOf(AiRole.DISPATCHER)

    val ACTIONS: List<AiWriteAction> = listOf(
        AiWriteAction(
            id = AiWrites.PURCHASE_ORDERS_CREATE,
            title = "按进货单建采购单",
            // HIGH：一次点确认会同时动三处钱的事实（库存、成本价、供应商欠款），而且撤不回来。
            risk = AiWriteRisk.HIGH,
            group = AiWrites.G_PURCHASE,
            roles = ROLES,
            blurb = "用户给了**进货单 / 送货单**（拍的照片、挂进来的文件、或者直接贴的表）、要按它建采购单时用它。" +
                "把那张单子上的表格**原样**放进 rows（含表头，不要改写、不要重排、不要自己加行、不要自己算金额），" +
                "再给一个供应商名字。App 会自己把表读出来、逐行对到商品名册上，然后把读到的每一行列在确认卡上给用户核对。" +
                "保存成功 = 库存增加、这几个商品的成本价按这一单重算、供应商欠款增加，三件事由后端同一个事务一起落。" +
                "⛔ 单子上有的商品名册里没有时**不要**自己建商品，如实告诉用户先建商品。",
            params = listOf(
                AiWriteParam(
                    "rows",
                    "进货单原文",
                    required = true,
                    kind = AiWriteParamKind.TEXT,
                    hint = "必填。把进货单上的那张表逐行**原样**放进来（含表头那一行，保留换行）：" +
                        "商品名 / 数量 / 单价。列之间用 Tab / 逗号 / 竖线 / 多个空格分开都行。" +
                        "⛔ 不要只挑几行、不要改数字、不要自己算金额（金额由系统算）。",
                ),
                AiWriteParam(
                    "supplier",
                    "供应商/厂商",
                    required = true,
                    kind = AiWriteParamKind.TEXT,
                    hint = "这张单是谁开的（名字，在「账本管理 → 供应商/厂商」页能看到全部档案）。" +
                        "名册里没有的话，先用「新增供应商/厂商」把他建出来。",
                ),
                AiWriteParam(
                    "doc_date",
                    "单据日期",
                    kind = AiWriteParamKind.DATE,
                    hint = "这张单上的日期（写成 2026-10-07）。不写就按今天算。",
                ),
                AiWriteParam(
                    "remark",
                    "备注",
                    hint = "要记在这张单上的一句话（可空，例如「张三送来的」「含两件赠品」）。",
                ),
            ),
        ),
        AiWriteAction(
            id = AiWrites.PURCHASE_ORDERS_UPDATE,
            title = "改采购单的单头",
            // MEDIUM：只改供应商/日期/备注，不动这张单的货与钱（要改行请撤单重开）。
            risk = AiWriteRisk.MEDIUM,
            group = AiWrites.G_PURCHASE,
            roles = ROLES,
            blurb = "改一张**已有**采购单的**单头三样**：供应商、单据日期、备注。" +
                "⛔ 改不了这张单进了哪些货、每行多少（后端换行是整份替换语义）—— 要改数量或单价，" +
                "请先「撤掉采购单」再重新建一张。三个都不给、或者给的值与现状完全一样时会被拒绝" +
                "（白弹一张什么都不改的卡比报错更糟）。",
            params = listOf(
                AiWriteParam(
                    "order",
                    "采购单编号",
                    required = true,
                    kind = AiWriteParamKind.NUMBER,
                    hint = "要改哪一张（单号，例如 12）。拿不准就先查一下「采购单」这一栏。",
                ),
                AiWriteParam(
                    "supplier",
                    "改成哪个供应商",
                    kind = AiWriteParamKind.TEXT,
                    hint = "换成谁开的单（名字）。不改就别传这个参数。",
                ),
                AiWriteParam(
                    "doc_date",
                    "单据日期",
                    kind = AiWriteParamKind.DATE,
                    hint = "改成哪一天（写成 2026-10-07）。不改就别传。",
                ),
                AiWriteParam(
                    "remark",
                    "备注",
                    hint = "改成什么（空串 = 清掉备注）。不改就别传。",
                ),
            ),
        ),
        AiWriteAction(
            id = AiWrites.PURCHASE_ORDERS_DELETE,
            title = "撤掉采购单",
            // HIGH：与建单对称 —— 冲库存、撤应付、重算成本价，一样撤不回来（撤回卡能放回来）。
            risk = AiWriteRisk.HIGH,
            group = AiWrites.G_PURCHASE,
            roles = ROLES,
            blurb = "撤掉一张采购单：这张单进过的货**冲回库存**、它带来的**供应商欠款一起撤回**、" +
                "相关商品的**成本价按剩下的进货记录重算**（后端既有语义）。" +
                "撤错了可以恢复（撤回入口里那条「恢复采购单」）。",
            params = listOf(
                AiWriteParam(
                    "order",
                    "采购单编号",
                    required = true,
                    kind = AiWriteParamKind.NUMBER,
                    hint = "要撤哪一张（单号，例如 12）。拿不准就先查一下「采购单」这一栏。",
                ),
            ),
        ),
        // 恢复走撤回路径（模型看不到它）：被撤掉的单在名册里已经查不到了，按名字解析说不通。
        restoreAction("采购单", AiWrites.PURCHASE_ORDERS_RESTORE, AiWrites.G_PURCHASE) { ds, id ->
            ds.restorePurchaseOrder(id)
        },
    )
}
