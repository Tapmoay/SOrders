package com.tapmoay.sorders.ai

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import java.math.BigDecimal
import java.math.RoundingMode

/**
 * **按一张表格批量建商品**——用户挂了一份 Excel/CSV（或直接贴了一张表），
 * 说"照这个把我这些货建进去"。
 *
 * ### 为什么表格必须由 **App** 解析，而不是让模型拆成参数
 * 和「按表格调价」是同一个理由（见 [AiPriceTable]）：只要模型**必须重打一遍**，
 * 就多一次出错的机会，而漏行、串列、把"库存"当"单价"**在卡片上看起来都是对的**。
 * 让模型把表格**原样**放进 `rows`，由这里的确定性解析器读，好处是三件事：
 * 1. 解析器是纯函数、能单测（模型不是）；
 * 2. 卡片上写的是"我读到的 N 行、分别是什么"，用户能和自己那份表逐行对上；
 * 3. 读不出来的行**带行号**报错，模型据此能问得很具体。
 *
 * ### 三条"宁可拒绝也不猜"
 * 1. **认不出哪一列是商品名** → 整张卡不发（靠表头认列；表头认不出就报错，
 *    绝不"按第一列猜"——猜错就是把单价写进商品名里，而用户要翻 30 行才发现）。
 * 2. **一行读不出来** → 整张卡不发（部分成功的批量最难核对：用户不会去数少了几行）。
 * 3. **表里有重名** → 拒绝（建两个同名商品，以后下单时谁都分不清该选哪个）。
 *
 * ### 为什么成本价**不在**这张表的列里
 * 成本是红线：它不许进模型上下文，也就不许由模型来设。所以这个动作**只认**
 * 名称/单位/默认单价/初始库存/报警阈值五列。**表里的成本列会被明确告知"没有写进去"**
 * ——静默丢掉一列比报错更糟：用户会以为成本已经录进去了（见 [ApplyProductTableHandler.prepare]）。
 */
internal object AiProductTable {

    /** 一次最多建几个。理由与调价表一致：输入是"用户的一大张表"，一行一个请求。
     *  30 行是"能一眼核对完 + 不会连打几十个请求"的折中。 */
    const val MAX_ROWS = 30

    /** 商品名长度上限（与 `products.create` 的 `name` 参数上限一致）。 */
    const val MAX_NAME = 64

    /** 单位长度上限。 */
    const val MAX_UNIT = 8

    /** 单价上限（超过一定是多打了零）。 */
    val MAX_PRICE: BigDecimal = BigDecimal("1000000")

    /** 表里的一行。 */
    data class Row(
        val lineNo: Int,
        val name: String,
        /** 没给单价 → null（后端按 0 建，卡片上会写明"单价 0.00"） */
        val price: BigDecimal?,
        val unit: String?,
        val stock: Int?,
        val alert: Int?,
    )

    /** 解析结果 + 那些"要说给用户听"的话（例如"表里有一列成本价，不会写进去"）。 */
    data class Parsed(val rows: List<Row>, val notes: List<String>)

    // ------------------------------------------------------------------ 列名

    private val NAME_WORDS = listOf("商品", "商品名", "品名", "名称", "产品", "产品名", "货名", "货品", "名字")
    private val PRICE_WORDS = listOf("单价", "价格", "默认单价", "售价", "价")
    private val UNIT_WORDS = listOf("单位", "规格", "计量单位")
    private val STOCK_WORDS = listOf("库存", "初始库存", "数量", "存量")
    private val ALERT_WORDS = listOf("报警", "预警", "报警阈值", "预警值", "库存报警", "低库存", "安全库存")
    /** 认出来但**不会写进去**的列：光是"认出来了"不够，还要在卡片上说清楚。 */
    private val IGNORED_WORDS = listOf("成本", "成本价", "进价", "进货价", "毛利", "利润", "备注", "图片", "编码", "条码")

    /**
     * 把一张表读成若干行。
     *
     * @throws AiWriteArgException 读不出来时（message 里带**行号**与那一行的原文）
     */
    fun parse(text: String): Parsed {
        val lines = AiTable.splitCells(text)
        if (lines.isEmpty()) {
            throw AiWriteArgException(
                "这张表我一行内容都没读到。请让用户**把表格原样贴进来**" +
                    "（一行一条，列之间用 Tab/逗号/竖线/多个空格分开都行）。",
            )
        }
        val header = lines.firstOrNull { it.cells.any { c -> c.isNotBlank() } }
            ?: throw AiWriteArgException("这张表是空的。")
        val cols = mapColumns(header.cells)

        val body = lines.dropWhile { it.lineNo <= header.lineNo }.filter { it.cells.any { c -> c.isNotBlank() } }
        if (body.isEmpty()) {
            throw AiWriteArgException(
                "我只读到一行表头「${header.cells.joinToString(" | ")}」，后面没有数据行。" +
                    "请让用户把表头和内容一起贴进来。",
            )
        }
        if (body.size > MAX_ROWS) {
            throw AiWriteArgException(
                "这张表有 ${body.size} 行数据，超过一次 $MAX_ROWS 行的上限。" +
                    "请让用户**分批来**（先做前 $MAX_ROWS 行），或者去「商品管理」页面上建。",
            )
        }

        val notes = ArrayList<String>(2)
        cols.ignored.forEach { (idx, label) ->
            val sample = body.firstNotNullOfOrNull { it.cells.getOrNull(idx)?.trim()?.takeIf { s -> s.isNotEmpty() } }
            notes += "表里的「${label}」列**没有写进去**（${sample?.let { "如「$it」" } ?: "整列都是空的"}）：" +
                "系统里的成本价只能在「商品管理」页面上填。"
        }

        val rows = ArrayList<Row>(body.size)
        val seen = HashMap<String, Int>()
        for (r in body) {
            try {
                rows += readRow(r, cols, seen)
            } catch (e: AiWriteArgException) {
                // ⚠️ **只有这一处**给错误补"第几行 + 那一行原文"。
                // 为什么必须补：模型和用户手里唯一能定位的信息就是这两样——
                // "单价不是数字"这句话本身没有指向性（30 行里哪一行？），
                // 而 [readRow] 里的每一处校验都不带行号，所以不会出现"两个行号"或"补了两次"。
                val rowText = r.cells.joinToString(" | ")
                throw AiWriteArgException(
                    "表格第 ${r.lineNo} 行读不出来：${e.message}。那一行原文是「$rowText」。",
                    e.candidates,
                )
            }
        }
        if (rows.isEmpty()) throw AiWriteArgException("这张表里没有可建的商品行。")
        return Parsed(rows, notes)
    }

    /**
     * 读一行。**抛出的信息里不带行号**——补行号是调用方的事（见上面那段 catch）。
     *
     * 这样分工的好处很具体：行号的格式只有一处，改文案时不会漏掉某一条校验。
     */
    private fun readRow(r: AiTable.Line, cols: Cols, seen: MutableMap<String, Int>): Row {
        fun cell(i: Int?): String? = i?.let { r.cells.getOrNull(it) }?.trim()?.takeIf { it.isNotEmpty() }

        val raw = cell(cols.name) ?: throw AiWriteArgException("没读到商品名")
        if (raw.length > MAX_NAME) {
            throw AiWriteArgException("商品名太长（${raw.length} 字，上限 $MAX_NAME）：$raw")
        }
        val unit = cell(cols.unit)?.let {
            if (it.length > MAX_UNIT) throw AiWriteArgException("单位太长（「$it」），最多 $MAX_UNIT 个字")
            it
        }
        val price = cell(cols.price)?.let { parseMoney(it, "单价") }
        val stock = cell(cols.stock)?.let { parseCount(it, "库存") }
        val alert = cell(cols.alert)?.let { parseCount(it, "报警阈值") }

        val dupAt = seen[raw]
        if (dupAt != null) {
            throw AiWriteArgException(
                "「$raw」出现了两次（上一次在第 $dupAt 行）。" +
                    "同名商品建两条，以后下单时谁都分不清该选哪个——请让用户合并成一行，或改成能区分的名字",
            )
        }
        seen[raw] = r.lineNo
        return Row(r.lineNo, raw, price, unit, stock, alert)
    }

    // ------------------------------------------------------------------ 认列

    private data class Cols(
        val name: Int,
        val price: Int?,
        val unit: Int?,
        val stock: Int?,
        val alert: Int?,
        /** 认出来但不会写进去的列（下标 → 原始表头词）。 */
        val ignored: List<Pair<Int, String>>,
    )

    /**
     * 按表头认列。
     *
     * **认不出商品名列就报错**，不猜：这是"整张卡不发"的第一条。
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
                "这张表的第一行「${header.joinToString(" | ")}」里我认不出哪一列是**商品名**。" +
                    "请让用户把表头写成「商品名 / 单价 / 单位 / 库存」这样的写法，" +
                    "或者告诉我哪一列是商品名。**不要自己猜**——猜错会把单价写成商品名。",
            )
        }
        val price = find(PRICE_WORDS)
        val unit = find(UNIT_WORDS)
        val stock = find(STOCK_WORDS)
        val alert = find(ALERT_WORDS)
        val used = setOfNotNull(name, price, unit, stock, alert)
        val ignored = norm.mapIndexedNotNull { i, h ->
            if (i in used || h.isEmpty()) null
            else IGNORED_WORDS.firstOrNull { h.contains(AiWriteArgs.norm(it)) }?.let { i to header[i].trim() }
        }
        // 报警列要避开"报警"和"库存"同时命中同一列的情况（"库存报警阈值"会同时命中两者）
        val alertSafe = alert?.takeIf { it != stock }
        return Cols(name, price, unit, stock, alertSafe, ignored)
    }

    // ------------------------------------------------------------------ 数值

    private fun parseMoney(raw: String, field: String): BigDecimal {
        val cleaned = raw.trim()
            .replace(",", "").replace("，", "")
            .removeSuffix("元").removeSuffix("块").removePrefix("¥").removePrefix("￥").trim()
        val v = cleaned.toBigDecimalOrNull()
            ?: throw AiWriteArgException("${field}「$raw」不是数字")
        if (v.signum() < 0) throw AiWriteArgException("${field}是负数（$raw）")
        if (v > MAX_PRICE) {
            throw AiWriteArgException(
                "${field}是 ${v.toPlainString()}，超过 ${MAX_PRICE.toPlainString()} 的上限——" +
                    "这个数看着像多打了几个零，请让用户先核对",
            )
        }
        return v.setScale(2, RoundingMode.HALF_UP)
    }

    private fun parseCount(raw: String, field: String): Int {
        val cleaned = raw.trim().replace(",", "").replace("，", "")
            .removeSuffix("件").removeSuffix("个").removeSuffix("箱").trim()
        val v = cleaned.toIntOrNull()?.takeIf { it >= 0 }
            ?: throw AiWriteArgException("${field}「$raw」不是 0 或正整数")
        if (v > AiWriteArgs.MAX_QUANTITY) {
            throw AiWriteArgException("${field}是 $v，超过 ${AiWriteArgs.MAX_QUANTITY} 的上限，请先核对")
        }
        return v
    }
}

/**
 * 「按表格建商品」的处理器。
 *
 * 结构上与 [ApplyPriceTableHandler] 一模一样（逐行执行、逐行 try/catch、执行完如实汇报），
 * 因为面对的**是同一类问题**：一次点确认 → 多个请求 → 必然存在"部分成功"。
 */
class ApplyProductTableHandler(
    private val ds: AiWriteDataSource,
    private val store: AiWritePreviewStore,
) : AiWriteHandler {

    override val actionId = AiWrites.PRODUCTS_APPLY_TABLE

    /** 执行完之后补的那句话（一次性：取走即清空）。见 [AiWriteHandler.commitNote]。 */
    private var pendingNote: String? = null

    override fun commitNote(): String? = pendingNote.also { pendingNote = null }

    override suspend fun prepare(params: JsonObject): AiWriteOutcome {
        val text = AiWriteArgs.required(
            params,
            "rows",
            "把那张表**原样**放进 rows（一行一条，含表头）。没有表格就别用这个动作。",
        )
        val parsed = AiProductTable.parse(text)

        // 系统里已经有的同名商品：这是**真实会发生**的事（用户把老表又传了一遍）。
        // 建重名的后果是"下单时两个一样的商品"，所以必须在卡片上点名，让用户自己决定。
        val existing = runCatching { ds.products().map { AiWriteArgs.norm(it.label) }.toSet() }
            .getOrDefault(emptySet())
        val clashes = parsed.rows.filter { AiWriteArgs.norm(it.name) in existing }

        val details = ArrayList<String>(AiProductTable.MAX_ROWS + 8)
        details += "表格：读到 ${parsed.rows.size} 行商品"
        parsed.notes.forEach { details += "⚠️ $it" }
        details += "———— 逐行新建 ————"
        parsed.rows.take(MAX_LISTED).forEach { r ->
            val bits = buildList {
                add("单价 ${r.price?.let { AiWriteArgs.money(it) } ?: "0.00"} 元")
                r.unit?.let { add("单位 $it") }
                r.stock?.let { add("初始库存 $it") }
                r.alert?.let { add("报警阈值 $it") }
            }
            details += "· 第 ${r.lineNo} 行 ${r.name}：${bits.joinToString("，")}"
        }
        if (parsed.rows.size > MAX_LISTED) {
            details += "…… 还有 ${parsed.rows.size - MAX_LISTED} 行，未逐条列出"
        }
        if (clashes.isNotEmpty()) {
            // ⚠️ 卡片是**纯文本渲染**（不走 Markdown），这里不能写 `**加粗**`——
            //    真机上会原样印出星号。这条红线由 _check_ai_guardrails.py 的"卡片文案没有星号"盯着。
            details += "⚠️ 系统里已经有同名的 ${clashes.size} 个商品：" +
                clashes.take(5).joinToString("、") { it.name } +
                "（会建成新的第二条。要改价/改资料请用「改商品」，不要在表格里再来一遍）"
        }
        // ⚠️ 成本这一列必须点破：静默丢掉它，用户会以为成本已经录进去了。
        details += "⚠️ 成本价不会写进去（只能在「商品管理」页面上填）"
        details += "⚠️ 这是一行一行发出去的：中间某行被后端拒绝时，其余行仍然会执行，我会把失败的那几行列出来"

        return AiWriteOutcome.NeedConfirm(
            store.offer(
                actionId = actionId,
                title = AiWrites.titleOf(actionId),
                risk = AiWrites.byId(actionId)!!.risk,
                summary = "按表格新建商品：${parsed.rows.size} 个",
                detailLines = details,
                payload = buildJsonObject {
                    put(
                        "rows",
                        JsonArray(
                            parsed.rows.map { r ->
                                buildJsonObject {
                                    put("name", r.name)
                                    put("line", r.lineNo.toString())
                                    put("price", AiWriteArgs.money(r.price ?: BigDecimal.ZERO))
                                    r.unit?.let { put("unit", it) }
                                    r.stock?.let { put("stock", it.toString()) }
                                    r.alert?.let { put("alert", it.toString()) }
                                }
                            },
                        ),
                    )
                },
            ),
        )
    }

    override suspend fun commit(payload: JsonObject, idempotencyKey: String) {
        val rows = (payload["rows"] as? JsonArray).orEmpty().mapNotNull { it as? JsonObject }
        if (rows.isEmpty()) {
            pendingNote = "这次没有要新建的商品行（内部错误），什么都没写。"
            return
        }
        val ok = ArrayList<String>()
        val failed = ArrayList<String>()
        rows.forEachIndexed { idx, r ->
            val line = (r["line"] as? JsonPrimitive)?.content?.toIntOrNull() ?: (idx + 1)
            val name = (r["name"] as? JsonPrimitive)?.content?.trim().orEmpty()
            if (name.isEmpty()) {
                failed += "第 $line 行（内部错误：商品名丢了）"
                return@forEachIndexed
            }
            try {
                ds.createProduct(
                    name = name,
                    defaultUnitPrice = (r["price"] as? JsonPrimitive)?.content ?: "0",
                    unit = (r["unit"] as? JsonPrimitive)?.content.orEmpty(),
                    stock = (r["stock"] as? JsonPrimitive)?.content?.toIntOrNull() ?: 0,
                    lowStockAlert = (r["alert"] as? JsonPrimitive)?.content?.toIntOrNull() ?: 0,
                )
                ok += name
            } catch (e: kotlinx.coroutines.CancellationException) {
                throw e
            } catch (e: Exception) {
                failed += "第 $line 行「$name」（${e.message ?: e.javaClass.simpleName}）"
            }
        }
        pendingNote = buildString {
            append("表格逐行结果：成功新建 ${ok.size} 个商品")
            if (failed.isEmpty()) {
                append("，全部建好")
            } else {
                append("、失败 ${failed.size} 行 —— ")
                append(failed.joinToString("；"))
                if (ok.isNotEmpty()) append("。（失败的那几个没建，成功的已经看得见了）")
            }
        }
    }

    private companion object {
        /** 卡片上逐条列出时最多列几条（与批量调价用同一个数："看一眼就够"的量）。 */
        const val MAX_LISTED = 12
    }
}

/** 「按表格建商品」的动作定义（行为在 [ApplyProductTableHandler]）。 */
internal object AiWriteProductTable {

    val ACTION: AiWriteAction = AiWriteAction(
        id = AiWrites.PRODUCTS_APPLY_TABLE,
        title = "按表格建商品",
        // MEDIUM：建的是新行，不影响已有商品和已有订单（价格快照在订单上），
        // 建错了随时能删。与「批量调价」的 HIGH 不同——那个是**改**已经生效的东西。
        risk = AiWriteRisk.MEDIUM,
        group = AiWrites.G_PRODUCT,
        blurb = "用户给了一张表（贴进来的、或者挂载的文件里读到的）、要按它**一次建多个商品**时用它。" +
            "把表格**原样**放进 rows（含表头），不要改写、不要重排、不要只挑几行——" +
            "系统会自己读那张表，并把「读到的每一行」列在确认卡上让用户逐行核对。",
        params = listOf(
            AiWriteParam(
                "rows", "表格原文", required = true, kind = AiWriteParamKind.TEXT,
                hint = "必填。把那张表**逐行原样**放进来（**含表头那一行**，保留换行）。" +
                    "列之间用 Tab / 逗号 / 竖线 / 多个空格分开都行。" +
                    "**不要**自己加解释、不要只挑几行、不要改写成 JSON、不要自己算金额",
            ),
        ),
    )
}
