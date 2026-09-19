package com.tapmoay.sorders.ai

/**
 * 极简 Markdown 解析：**只做模型实际会输出的那几种**，够用就好。
 *
 * ### 为什么需要它
 * 实测模型很爱输出 Markdown 表格（`| 司机 | 单量 |` 加一行 `|---|---|`）。原来直接当纯文本贴出来，
 * 用户看到的就是一堆竖线和横线——**看不清，也不好看**。加粗同理：`**按单量**` 会把星号原样显示。
 *
 * ### 为什么是自己写一个小解析器，而不是引第三方库
 * 1. 需要的语法只有四种：**表格 / 加粗 / 列表 / 标题**。一个完整 Markdown 库会带来一大片用不到的
 *    解析分支和渲染器，还要额外处理它自己的链接/图片/HTML 转义行为。
 * 2. **它必须是纯 Kotlin**（无 Compose、无 Android），这样表格解析这种最容易写错的逻辑
 *    能在 JVM 单测里穷举——表格是"列数不齐、分隔行、空单元格、被 ``` 包住"这些边角最容易崩的地方。
 *
 * ### 已知的取舍（写清楚，免得以后当成 bug）
 * - **代码围栏 ```` ``` ```` 只被剥掉，不做代码高亮**：这个助手回答的是经营数据，不会输出代码，
 *   而它**会**把表格包在围栏里。剥掉围栏让表格能被正确识别，比支持高亮重要得多。
 * - 只认识 `**粗体**`，不认识斜体/链接/引用块——模型在这个场景里不用它们。
 * - 表格不追求对齐（Markdown 的 `:---:` 对齐标记一律忽略）：手机屏幕窄，对齐不如"能换行"重要。
 */
object AiMarkdown {

    /** 行内片段：目前只需要区分「是不是粗体」。 */
    data class Span(val text: String, val bold: Boolean = false)

    /** 一个解析出来的块。 */
    sealed interface Block {
        enum class Kind { TEXT, HEADING, BULLET, NUMBERED }

        /** 一段普通文本（段落 / 标题 / 列表项）。[marker] 是列表项前面的符号（`•` 或 `1.`）。 */
        data class Line(val spans: List<Span>, val kind: Kind, val marker: String? = null) : Block

        /** 一张表。[header] 与 [body] 的每一行长度都已被补齐成相同列数。 */
        data class Table(val header: List<String>, val body: List<List<String>>) : Block
    }

    /**
     * 是否是「看起来像表格」的一行。
     *
     * 两个竖线以上直接认；**只有一个竖线时要求两侧都很短**——因为
     * `司机 | 单量` 这种省略首尾竖线的写法也要认，而"一整句话里夹了一个竖线"不能认。
     */
    private fun looksLikeTableRow(line: String): Boolean {
        val t = line.trim()
        if (t.isEmpty()) return false
        val pipes = t.count { it == '|' }
        if (pipes >= 2) return true
        if (pipes == 1) return t.split('|').all { it.trim().length in 1..30 }
        return false
    }

    /**
     * Markdown 的分隔行：`|---|---|`、`:--:`、`--- | ---`。
     *
     * 判据是「**含减号**且只由 `- : | 空格 =` 组成」——不能只按字符集判，
     * 否则 `| 2026-09-01 | 5 |` 这种正常数据行（也含减号）会被误当成分隔行删掉。
     */
    private fun isSeparatorRow(line: String): Boolean {
        val t = line.trim()
        if (!t.contains('-')) return false
        return t.all { it == '-' || it == ':' || it == '|' || it == ' ' || it == '=' }
    }

    /** 拆一格：去掉两端空白，并把单元格内部的 `**` 也去掉（表头加粗由渲染层统一做）。 */
    private fun splitCells(line: String): List<String> {
        var t = line.trim()
        if (t.startsWith("|")) t = t.substring(1)
        if (t.endsWith("|")) t = t.dropLast(1)
        return t.split('|').map { it.trim().replace("**", "") }
    }

    /**
     * 解析成块列表。任何输入都不会抛异常（解析失败就退化成纯文本，绝不因为一处格式问题让整条回答消失）。
     */
    fun parse(text: String): List<Block> {
        if (text.isBlank()) return emptyList()
        val lines = text.replace("\r\n", "\n").replace('\r', '\n').split('\n')

        val out = ArrayList<Block>()
        var i = 0
        while (i < lines.size) {
            val raw = lines[i]

            // 代码围栏：只剥壳，里面的内容照常解析（表格常被包在围栏里）
            if (raw.trim().startsWith("```")) {
                i++
                continue
            }

            // 空行：分段，直接丢
            if (raw.isBlank()) {
                i++
                continue
            }

            // 表格：连续的表格行合成一个块
            if (looksLikeTableRow(raw)) {
                val group = ArrayList<String>()
                while (i < lines.size && looksLikeTableRow(lines[i])) {
                    if (!isSeparatorRow(lines[i])) group += lines[i]
                    i++
                }
                val rows = group.map { splitCells(it) }.filter { it.isNotEmpty() }
                if (rows.size >= 2) {
                    val cols = rows.maxOf { it.size }
                    fun pad(r: List<String>) = List(cols) { idx -> r.getOrElse(idx) { "" } }
                    out += Block.Table(header = pad(rows.first()), body = rows.drop(1).map { pad(it) })
                    continue
                }
                // 只有一行"像表格"——那就是普通文本，别硬当表
                group.forEach { out += textLine(it) }
                continue
            }

            out += textLine(raw)
            i++
        }
        return out
    }

    /** 非表格行：识别标题 / 无序列表 / 有序列表，剩下的当普通段落。 */
    private fun textLine(line: String): Block.Line {
        val t = line.trimEnd()
        val trimmed = t.trimStart()
        HEADING.matchEntire(trimmed)?.let {
            return Block.Line(inline(it.groupValues[1]), Block.Kind.HEADING)
        }
        BULLET.matchEntire(trimmed)?.let {
            return Block.Line(inline(it.groupValues[2]), Block.Kind.BULLET, marker = "•")
        }
        NUMBERED_SPACED.matchEntire(trimmed)?.let {
            return Block.Line(inline(it.groupValues[2]), Block.Kind.NUMBERED, marker = it.groupValues[1] + ".")
        }
        NUMBERED_CN.matchEntire(trimmed)?.let {
            return Block.Line(inline(it.groupValues[2]), Block.Kind.NUMBERED, marker = it.groupValues[1] + ".")
        }
        return Block.Line(inline(t), Block.Kind.TEXT)
    }

    private val HEADING = Regex("""^#{1,6}\s+(.*)$""")
    private val BULLET = Regex("""^([-*•])\s+(.*)$""")

    /**
     * 有序列表：`1. xxx` / `2) xxx` **要求序号后面有空格**。
     *
     * 为什么必须要求空格：不要求的话 `3.5 元` 会被当成「第 3 项，内容 = 5 元」——
     * 金额被吃掉一位，这是最不能忍的一类错。
     */
    private val NUMBERED_SPACED = Regex("""^(\d{1,2})[.．)）]\s+(.*)$""")

    /** 中文顿号写法（`2、第三条`）**可以没有空格**——它就是中文里的枚举符号，不会和数字混。 */
    private val NUMBERED_CN = Regex("""^(\d{1,2})[、,]\s*(.*)$""")

    /**
     * 行内解析：抽出 `**粗体**`，并把 `` ` `` 去掉（不显示反引号，也不做等宽字体）。
     * 未闭合的 `**` 按普通文字处理（模型偶尔会漏一个，不能让后面整段都变粗）。
     */
    fun inline(text: String): List<Span> {
        if (text.isEmpty()) return emptyList()
        val out = ArrayList<Span>()
        var idx = 0
        while (idx < text.length) {
            val start = text.indexOf("**", idx)
            if (start < 0) {
                out += Span(text.substring(idx).replace("`", ""))
                break
            }
            val end = text.indexOf("**", start + 2)
            if (end < 0) {
                // 只有开头没有结尾 → 当普通文字
                out += Span(text.substring(idx).replace("`", ""))
                break
            }
            if (start > idx) out += Span(text.substring(idx, start).replace("`", ""))
            val boldText = text.substring(start + 2, end).replace("`", "")
            if (boldText.isNotEmpty()) out += Span(boldText, bold = true)
            idx = end + 2
        }
        return out.filter { it.text.isNotEmpty() }
    }

    /**
     * 每列最长内容的显示宽度（**不夹到窄区间**，只封顶），用来算"这一列至少要留多宽"。
     *
     * 与 [columnWeights] 的区别很重要：
     * - [columnWeights] 是**比例**，用于纯文本对齐；
     * - 这个是**绝对宽度**，用于真表格排版。真表格必须按它给每列一个**最小宽度**，
     *   否则列被压到几个字符宽时，`100.0%` 会断成 `100.` / `0` / `%` 三行、
     *   `固定工资` 会断成四个竖排的字——**这正是用户说的"看不清"**。
     *
     * @param maxChars 封顶，避免某一列里塞了一整句话就把整张表撑爆（配合提示词里的"最多 4 列"）。
     */
    fun columnCharWidths(
        header: List<String>,
        body: List<List<String>>,
        maxChars: Int = 24,
    ): List<Int> {
        val cols = maxOf(header.size, body.maxOfOrNull { it.size } ?: 0)
        if (cols <= 0) return emptyList()
        return (0 until cols).map { c ->
            (listOf(header.getOrElse(c) { "" }) + body.map { it.getOrElse(c) { "" } })
                .maxOf { displayWidth(it) }
                .coerceIn(2, maxChars)
        }
    }

    /**
     * 表格列宽权重：按各列**最长内容**分配，这样"姓名"列宽、"单量"列窄，不会出现数字列占半屏。
     *
     * 中日韩字符按 2 个宽度算（一个汉字约等于两个数字的宽度）；权重下限 3、上限 18，
     * 避免某列内容特别长（比如一整句话）把别的列挤没。
     */
    fun columnWeights(header: List<String>, body: List<List<String>>): List<Float> =
        columnCharWidths(header, body, maxChars = 18).map { it.coerceIn(3, 18).toFloat() }

    // ---------------------------------------------------------------- 表格排版（Excel 观感）

    /**
     * 哪几列该**右对齐**（表格渲染用）。
     *
     * 判据是**这一列里大多数格子都是数字**（≥60%），不是"表头里有'金额'"——
     * 表头写法千变万化（金额/单价/运费/应付/数量/件数…），按词表认一定会漏；
     * 而"这一列装的是不是数字"是**看内容就知道**的。
     *
     * 一列里混着数字和文字时（如"3 件/待定价"），按少数服从多数：
     * 右对齐一列文字会很难看，而左对齐一列数字只是没那么整齐。
     */
    fun numericColumns(table: Block.Table): List<Boolean> {
        if (table.body.isEmpty()) return List(table.header.size) { false }
        return (0 until table.header.size).map { ci ->
            val cells = table.body.map { it.getOrNull(ci).orEmpty().trim() }.filter { it.isNotEmpty() }
            if (cells.isEmpty()) return@map false
            cells.count { Numberish.matches(it) } >= (cells.size * 6 + 9) / 10
        }
    }

    /**
     * 这一行是不是**结论行**（"合计/总计/小计"）。
     *
     * 渲染时给它加粗 + 更明显的底纹：模型给的明细表常在最后一行放合计，
     * 而它长得和明细一样时，用户会把结论当成第 N 条数据读过去。
     */
    fun isTotalRow(row: List<String>): Boolean =
        row.firstOrNull()?.trim()?.let { c -> c.isNotEmpty() && TotalWords.any { c.contains(it) } } == true

    /** 数值格：可选正负号/括号、货币符号、千分位、小数、百分号、常见单位。 */
    private val Numberish = Regex(
        "^[-+()]?[¥￥$]?\\d[\\d,，]*(?:\\.\\d+)?\\s*(?:%|％)?" +
            "(?:元|块|件|箱|个|斤|公斤|吨|袋|桶|包|瓶|公里|千米|km|米|分钟|小时|天|单|次|人|笔)?$",
    )

    private val TotalWords = listOf("合计", "总计", "小计", "总共", "一共", "总数", "汇总")

    /** 显示宽度：汉字/全角按 2 计，其它按 1 计。 */
    fun displayWidth(s: String): Int {
        // 刻意用显式循环而不是 `sumOf { if … 2 else 1 }`：后者会因为 sumOf 的
        // Int/Long/Double 重载而报「Overload resolution ambiguity」（编译器无法从字面量定类型）。
        var w = 0
        for (ch in s) {
            val c = ch.code
            w += if (c >= 0x1100 && isWide(c)) 2 else 1
        }
        return w
    }

    /** 粗略的全角判定（覆盖中日韩、全角标点、全角字母数字）。 */
    private fun isWide(code: Int): Boolean = when (code) {
        in 0x1100..0x115F, in 0x2E80..0xA4CF, in 0xAC00..0xD7A3,
        in 0xF900..0xFAFF, in 0xFE30..0xFE6F, in 0xFF00..0xFF60, in 0xFFE0..0xFFE6,
        -> true
        else -> false
    }

    /**
     * 纯文本化：把 Markdown 标记去掉，用于**复制到剪贴板**之外的场景（如摘要）。
     * 表格转成「单元格之间用空格分隔」的几行，保证粘贴出去仍然可读。
     */
    fun toPlainText(text: String): String = parse(text).joinToString("\n") { b ->
        when (b) {
            is Block.Table -> {
                val rows = listOf(b.header) + b.body
                val widths = columnWeights(b.header, b.body).map { it.toInt() }
                rows.joinToString("\n") { r ->
                    r.mapIndexed { i, cell -> pad(cell, widths.getOrElse(i) { 6 }) }.joinToString("  ")
                }
            }
            is Block.Line -> (b.marker?.plus(" ") ?: "") + b.spans.joinToString("") { it.text }
        }
    }

    private fun pad(s: String, width: Int): String {
        val w = displayWidth(s)
        return if (w >= width) s else s + " ".repeat(width - w)
    }
}
