package com.tapmoay.sorders.ai

import java.math.BigDecimal
import java.math.RoundingMode

/**
 * **贴一张表格批量调价**：把用户粘进来的那张表读成一行行「哪个商品、哪个批发商、涨降多少」。
 *
 * ### 为什么表格要由 **App 解析**，而不是让模型把它拆成参数
 * 模型完全可以把表格「翻译」成几组参数交上来。但只要它**必须重打一遍**，
 * 就多了一次出错的机会，而且这类错误（少一行、串列、把涨幅当成新价）**看不出来**——
 * 表格本身长得就像对的。
 * 让它**原样**把表格贴进 `rows`，再由这里的确定性解析器读，好处有三条：
 * 1. 解析器是纯函数、能单测（模型不是）；
 * 2. 卡片上写的是「我读到的 N 行」，用户看到的和自己贴的那张表能逐行对上；
 * 3. 读不出来的行**在第几行**报错（有行号），模型据此能问得很具体。
 *
 * ### 能读的形状（都是从真实贴法倒推的）
 * - 分隔符：**Tab**（从 Excel 复制）、`|`（Markdown 表格）、`,`/`，`、**两个以上空格**、
 *   以及中文顿号；Markdown 的分隔行（`|---|---|`）会被忽略；
 * - 表头：有就按表头映射列（「商品/产品/货名」、「批发商/商户/客户/货主」、「价格/新价/单价」、
 *   "幅度/涨跌/调整/比例「）；没有就**按内容认列**（拿真实商品名册和批发商名册去对）；
 * - 幅度：`-10%`、`10%`、`降10`、`涨5%`、`+3%`、`-10％`；
 * - 绝对价：`4.05`、`4.05元`、`¥4.05`、`新价4.05`（**只有表头/单位说清是价格时才当绝对价**，
 *   否则一个光秃秃的数字按**百分比**读——用户要的三种用法说的都是「涨/降百分之多少」，
 *   而且卡片会把 before→after 算出来，读错了一眼能看见）。
 *
 * ### 读不出来就**整张表都不发卡**
 * 一行读不出来（商品名对不上、数字看不清），不会「跳过这一行继续"——
 * 那样用户会拿到一张「少了一行」的卡，而他不会去数。宁可整张卡不发，把第几行、为什么说清楚。
 */
internal object AiPriceTable {

    /** 一次最多读多少行。
     *
     * 为什么要有上限：输入是**用户粘进来的一整张表**，一行一个请求（后端一次调用只套一套规则）。
     * 30 行是「能一眼看完 + 不会连打几十个请求」的折中；超了让用户分批，或者去页面上做。 */
    const val MAX_ROWS = 30

    /** 一个数值的上限（百分比绝对值 / 单价）。百分比另有 -100 ~ +1000 的区间约束。 */
    val MAX_PERCENT: BigDecimal = BigDecimal("1000")

    enum class Mode { ADJUST, FIXED }

    /**
     * 表里的一行（名字已经解析成编号）。
     *
     * @param shipper null = 这一行的批发商写的是「全部/所有」（或整张表就没有批发商列）
     */
    data class Row(
        val lineNo: Int,
        val product: AiName,
        val shipper: AiName?,
        val mode: Mode,
        val value: BigDecimal,
        /** 原文里那一格写了什么（报错和卡片上用它，比 BigDecimal 更能说明「我读的是这个」）。 */
        val rawValue: String,
    )

    // ------------------------------------------------------------------ 主入口

    /**
     * 把整张表读成若干行。
     *
     * @param forcedMode 用户/模型明确说了「这是新价表」或「这是涨跌幅表」时传进来；
     *   null = 按表头与格子内容自己判。
     * @throws AiWriteArgException 读不出来时（message 里带**行号**与那一行的原文）
     */
    fun parse(
        text: String,
        products: List<AiName>,
        members: List<AiName>,
        forcedMode: Mode? = null,
    ): List<Row> {
        if (products.isEmpty()) throw AiWriteArgException("系统里还没有商品，没法调价。")
        val lines = splitCells(text)
        val header = detectHeader(lines)
        val map = mapColumns(lines, header, products, members)
        val body = if (header != null) lines.drop(1) else lines
        if (body.isEmpty()) {
            throw AiWriteArgException(
                "这张表我一行内容都没读到。请让用户**把表格原样贴进来**（一行一条，列之间用" +
                    "空格/Tab/逗号/竖线分开都行），不要只给标题或说明。",
            )
        }
        if (body.size > MAX_ROWS) {
            throw AiWriteArgException(
                "这张表有 ${body.size} 行，超过一次 ${MAX_ROWS} 行的上限。" +
                    "请让用户**分批贴**（先做前 ${MAX_ROWS} 行），或者去「批发商管理 → 定价」页面上做。",
            )
        }

        val rows = ArrayList<Row>(body.size)
        for (r in body) {
            val cells = r.cells
            fun cell(i: Int?): String? = i?.let { cells.getOrNull(it) }?.trim()?.takeIf { it.isNotEmpty() }

            // ⚠️ 这一整段都包在 try 里：`AiWriteArgs.strict` 抛出来的话只有「系统里没有匹配…"，
            //    **不带行号**——而「第几行」恰恰是用户和模型唯一能定位的信息
            //    （单测抓到的：一条 20 行的表里，模型拿到「没有匹配水蜜桃」根本不知道是第几行，
            //    而它也不知道这一行原文长什么样）。所以这里统一补上行号与原文。
            try {
                val productRaw = cell(map.productCol)
                    ?: throw rowError(r, "这一行没读到商品名（只读到 ${cells.size} 格）")
                val product = AiWriteArgs.strict(productRaw, products, "商品")
                    ?: throw rowError(r, "商品「$productRaw」在商品库里对不上")

                val shipperRaw = cell(map.shipperCol)
                val shipper: AiName? = when {
                    shipperRaw == null -> null
                    isAllWord(shipperRaw) -> null
                    else -> AiWriteArgs.strict(shipperRaw, members, "批发商")
                }

                val valueRaw = cell(map.valueCol)
                    ?: throw rowError(
                        r,
                        "这一行没读到调整值（读到 ${cells.size} 格，我按第 ${map.valueCol + 1} 列取）",
                    )
                val (mode, value) = readValue(valueRaw, map.valueLooksLikePrice, forcedMode, r)
                validate(mode, value, r, valueRaw)

                rows += Row(
                    lineNo = r.lineNo,
                    product = product,
                    shipper = shipper,
                    mode = mode,
                    value = value,
                    rawValue = valueRaw,
                )
            } catch (e: AiWriteArgException) {
                // 已经带行号的（rowError 抛的）原样往上扔；其余（strict/readValue）补上行号。
                if (e.message?.contains("表格第 ${r.lineNo} 行") == true) throw e
                throw AiWriteArgException(
                    "表格第 ${r.lineNo} 行读不出来：${e.message}。那一行原文是「${cells.joinToString(" | ")}」。",
                    e.candidates,
                )
            }
        }
        if (rows.isEmpty()) throw AiWriteArgException("这张表里没有可执行的调价行。")
        return rows
    }

    // ------------------------------------------------------------------ 拆行/拆列

    // ⚠️ 拆行拆列的规则**已经搬到 [AiTable]**（"按表格建商品"要用同一份规则）：
    //    多一份就一定会有一份先被改、另一份留在原地，于是"同一张表，调价能读、建商品读不了"。
    //    下面两个薄包装只是让本文件其余代码保持原样。

    private fun splitCells(text: String): List<AiTable.Line> = AiTable.splitCells(text)

    private fun splitLine(line: String): List<String> = AiTable.splitLine(line)

    // ------------------------------------------------------------------ 表头

    private val PRODUCT_WORDS = listOf("商品", "产品", "货名", "品名", "货品", "名称")
    private val SHIPPER_WORDS = listOf("批发商", "商户", "客户", "货主", "门店", "商家", "买家", "单位")

    /** 表头里表示「这是绝对价格」的词（有它才敢把光秃秃的数字当新价读）。 */
    private val PRICE_WORDS = listOf("价格", "新价", "单价", "售价", "现价", "调后价", "价")

    /**
     * 表头里表示「这是涨跌幅」的词。
     *
     * ⚠️ 这里**故意不收 `%` / `％`**：含百分号的格子一定是**数据**，不可能是表头。
     * 第一版把它们当成表头词，于是「红富士苹果 / 城东水果批发 / **下调7.5%**」这种单行表
     * 被整行当成了表头（`下调7.5` 又不是数字，「没有数字」这条判据也就跟着失效），
     * 结果表里一行数据都不剩 → 报「每行只有 0 格」——**表本身完全没问题**（单测抓到的）。
     */
    private val PERCENT_WORDS = listOf("幅度", "涨跌", "调整", "比例", "百分比", "涨幅", "降幅")

    private fun detectHeader(lines: List<AiTable.Line>): List<String>? {
        val first = lines.firstOrNull() ?: return null
        val norm = first.cells.map { AiWriteArgs.norm(it) }
        val hit = norm.any { c -> (PRODUCT_WORDS + SHIPPER_WORDS + PRICE_WORDS + PERCENT_WORDS).any { it in c } }
        // ⚠️ 光有「表头词」还不够，两条额外的判据缺一不可：
        // ① 这一行**一个数字都不能有**（数据行几乎必然带数字，表头行通常不带）；
        // ② 至少有 2 格（只有 1 格的「表头」没有意义，那种输入应该走后面的报错路径）。
        val hasDigit = first.cells.any { c -> c.any { ch -> ch.isDigit() } }
        val looksLikeHeader = hit && !hasDigit && first.cells.size >= 2
        return if (looksLikeHeader) first.cells.map { it.trim() } else null
    }

    private data class ColumnMap(
        val productCol: Int,
        val shipperCol: Int?,
        val valueCol: Int,
        /** 数值列看起来像绝对价格（表头写「价格/单价」或格子带「元/¥"）→ 光数字当新价读。 */
        val valueLooksLikePrice: Boolean,
    )

    private fun mapColumns(
        lines: List<AiTable.Line>,
        header: List<String>?,
        products: List<AiName>,
        members: List<AiName>,
    ): ColumnMap {
        val body = if (header != null) lines.drop(1) else lines
        val width = (body.maxOfOrNull { it.cells.size } ?: 0).coerceAtMost(8)
        if (width < 2) {
            val sample = body.firstOrNull()?.let { it.cells.joinToString("｜") } ?: ""
            throw AiWriteArgException(
                "这张表每行只有 ${body.firstOrNull()?.cells?.size ?: 0} 格，读不出「商品 + 调整值」两列" +
                    "（第一行读到的是「$sample」）。" +
                    "请让用户把表格**按列分开**贴进来（列之间用空格/Tab/逗号/竖线）。",
            )
        }

        // ---- 有表头：按词映射 ----
        if (header != null) {
            val norm = header.map { AiWriteArgs.norm(it) }
            // ⚠️ `indexOfFirst` 找不到时返回 **-1**（不是 null）。第一版直接把它当 Int? 用，
            // 于是「表头里没有价格列」变成了 `priceCol = -1` → valueCol = -1 →
            // 每一行都取不到值，报的却是「这一行没读到调整值（读到 3 格）」：
            // 表没问题、行列也认对了，错误信息却把锅甩给数据行（单测抓到的）。
            fun find(words: List<String>): Int? =
                norm.indexOfFirst { c -> words.any { it in c } }.takeIf { it >= 0 }
            val p = find(PRODUCT_WORDS)
            val s = find(SHIPPER_WORDS)
            val priceCol = find(PRICE_WORDS)
            val pctCol = find(PERCENT_WORDS)
            val valueCol = priceCol ?: pctCol
            if (p != null && valueCol != null) {
                return ColumnMap(
                    productCol = p,
                    shipperCol = s,
                    valueCol = valueCol,
                    valueLooksLikePrice = priceCol != null && priceCol != pctCol,
                )
            }
            // 表头认不全（比如只写了「商品/商户/调整」）→ 落到内容推断，别硬猜
        }

        // ---- 没有表头（或表头认不全）：按内容认列 ----
        val productHits = IntArray(width)
        val memberHits = IntArray(width)
        val numericHits = IntArray(width)
        val pctHits = IntArray(width)
        for (r in body) {
            for (c in 0 until minOf(width, r.cells.size)) {
                val v = r.cells[c].trim()
                if (v.isEmpty()) continue
                if (looksNumeric(v)) {
                    numericHits[c]++
                    if (v.contains('%') || v.contains('％')) pctHits[c]++
                } else {
                    if (hitName(v, products)) productHits[c]++
                    if (hitName(v, members) || isAllWord(v)) memberHits[c]++
                }
            }
        }
        val productCol = productHits.indices.maxByOrNull { productHits[it] }?.takeIf { productHits[it] > 0 }
        // 批发商列：只有在**真的对上过批发商名**（或「全部」）时才算有这一列。
        val shipperCol = memberHits.indices.maxByOrNull { memberHits[it] }
            ?.takeIf { memberHits[it] > 0 && it != productCol }
        // 数值列优先取「看起来是数字」的那一列；一个数字都没有时（整列写成了「降一点」这种），
        // **退一步取剩下的第一列**——那样 readValue 能报出「第 N 行的值读不出来」，
        // 比「认不出哪一列是调整值」有用得多（那句会让用户以为是自己列排错了）。
        val remaining = (0 until width).filter { it != productCol && it != shipperCol }
        val valueCol = (remaining.maxByOrNull { numericHits[it] }?.takeIf { numericHits[it] > 0 }
            ?: remaining.firstOrNull())
        if (productCol == null || valueCol == null) {
            throw AiWriteArgException(
                "这张表我认不出「哪一列是商品、哪一列是调整值」。" +
                    "请让用户**加一行表头**（比如：商品 批发商 幅度），或者把商品名写全（要能在商品库里对上）。",
            )
        }
        // 没有 `%` 的纯数字列 + 格子带「元/¥" → 当成新价读
        val looksPrice = pctHits[valueCol] == 0 && body.any { r ->
            val v = r.cells.getOrNull(valueCol)?.trim().orEmpty()
            v.contains('元') || v.contains('¥') || v.contains('￥')
        }

        // ---- 剩下那些「既不是商品、也不是批发商、也不是数字」的列：**宁可拒绝** ----
        //
        // ⚠️ 这条是单测抓出来的：表格「红富士苹果 / 不存在的店 / -10%」里那一列其实是想指定
        //    一个批发商，只是名字写错了。旧逻辑认不出批发商列 → shipperCol=null →
        //    这一行被理解成**「全部批发商 -10%」**：用户只想改一家，系统改了所有家，
        //    而且卡片上看不出来（卡片只会老老实实列出全部批发商的新价）。
        //    范围错是本域最严重的错，所以这里不再「猜」，直接把这一列摆出来问用户。
        val used = setOfNotNull(productCol, shipperCol, valueCol)
        val suspicious = (0 until width).firstOrNull { c ->
            c !in used && body.any { r ->
                val v = r.cells.getOrNull(c)?.trim().orEmpty()
                v.isNotEmpty() && !looksNumeric(v) && !hitName(v, products) && !hitName(v, members)
            }
        }
        if (suspicious != null) {
            val sample = body.firstNotNullOfOrNull { r -> r.cells.getOrNull(suspicious)?.trim()?.takeIf { it.isNotEmpty() } }
            throw AiWriteArgException(
                "这张表里有一列我读不懂（第 ${suspicious + 1} 列，比如「$sample」）：" +
                    "它既不是商品名、也不是批发商名、也不是数字。" +
                    "如果那一列是**批发商**，请让用户把名字写全（要能在批发商名册里对上）；" +
                    "如果是备注之类的，请让他把那一列删掉。" +
                    "**不要把它当成「全部批发商」**——那会把只想改一家的价改成所有家。",
            )
        }
        return ColumnMap(productCol, shipperCol, valueCol, looksPrice)
    }

    // ------------------------------------------------------------------ 取值

    private fun readValue(
        raw: String,
        columnLooksLikePrice: Boolean,
        forced: Mode?,
        line: AiTable.Line,
    ): Pair<Mode, BigDecimal> {
        val cleaned = raw.trim()
            .removePrefix("新价").removePrefix("单价").removePrefix("价格").removePrefix("调至").removePrefix("调到")
            .replace("人民币", "").trim()
        // 这一格**自己说了**是价格（写「新价4.05」这种）——比"整列的推测"更可信，优先用它。
        val cellSaysPrice = raw.trim().let { t ->
            listOf("新价", "单价", "价格", "调至", "调到").any { t.startsWith(it) }
        } || raw.contains('元') || raw.contains('¥') || raw.contains('￥')

        val hasPercent = cleaned.contains('%') || cleaned.contains('％')
        val negative = cleaned.startsWith("降") || cleaned.startsWith("下调") || cleaned.startsWith("-")
        val positive = cleaned.startsWith("涨") || cleaned.startsWith("上调") || cleaned.startsWith("+")
        val mode = forced ?: when {
            hasPercent || negative || positive -> Mode.ADJUST
            // ⚠️ 顺序：格子自己的说明 > 整列的推测 > 默认按百分比。
            //   「新价3.80」如果落到最后那档，会被当成"涨 3.8%"，而用户明明写的是价格。
            cellSaysPrice || columnLooksLikePrice -> Mode.FIXED
            else -> Mode.ADJUST
        }

        val digits = cleaned
            .replace("%", "").replace("％", "")
            .removePrefix("涨").removePrefix("降").removePrefix("上调").removePrefix("下调")
            .removeSuffix("元").removePrefix("¥").removePrefix("￥")
            .removePrefix("+").removePrefix("-").trim()
        val v = digits.toBigDecimalOrNull()
            ?: throw rowError(line, "调整值「$raw」不是数字（百分比写 -10% / 10%，新价写 4.05）")

        val signed = when {
            mode == Mode.FIXED -> v
            negative -> v.negate()
            else -> v
        }
        // 涨价写成 `降-10` 这种双重否定会算反：在参数层就拦掉，让模型回去问清楚。
        if (mode == Mode.ADJUST && v.signum() < 0) {
            throw rowError(line, "调整值「$raw」里同时有「降」和负号，看不出是涨还是降")
        }
        return mode to signed.setScale(2, RoundingMode.HALF_UP)
    }

    private fun validate(mode: Mode, value: BigDecimal, line: AiTable.Line, raw: String) {
        if (mode == Mode.ADJUST) {
            if (value < BigDecimal(-100) || value > MAX_PERCENT) {
                throw rowError(
                    line,
                    "涨跌幅 $value% 超出允许范围（-100% ~ +${MAX_PERCENT.toPlainString()}%）",
                )
            }
            if (value.signum() == 0) {
                throw rowError(line, "涨跌幅是 0，这一行改了等于没改")
            }
        } else {
            if (value.signum() < 0) throw rowError(line, "新价不能是负数（$raw）")
            if (value > AiWriteArgs.MAX_AMOUNT) {
                throw rowError(line, "新价 $value 超过 ${AiWriteArgs.MAX_AMOUNT.toPlainString()} 的上限，像是多打了几个零")
            }
        }
    }

    // ------------------------------------------------------------------ 小工具

    private fun rowError(line: AiTable.Line, why: String) = AiWriteArgException(
        "表格第 ${line.lineNo} 行读不出来：$why。那一行原文是「${line.cells.joinToString(" | ")}」。" +
            "请让用户改这一行，或者把这一行删掉——**不要替他把这一行改成猜的**。",
    )

    private fun isAllWord(s: String): Boolean {
        val n = AiWriteArgs.norm(s)
        return n in setOf("全部", "所有", "全部批发商", "所有批发商", "全部商户", "所有商户", "all", "*", "-", "—", "全部客户")
    }

    private fun hitName(raw: String, pool: List<AiName>): Boolean {
        val q = AiWriteArgs.norm(raw)
        if (q.isEmpty()) return false
        return pool.any { AiWriteArgs.norm(it.label) == q }
    }

    private fun looksNumeric(s: String): Boolean {
        val t = s.trim()
            .replace("%", "").replace("％", "").replace("元", "")
            .removePrefix("¥").removePrefix("￥").removePrefix("+").removePrefix("-")
            .removePrefix("涨").removePrefix("降").removePrefix("新价").trim()
        return t.isNotEmpty() && t.toBigDecimalOrNull() != null
    }
}
