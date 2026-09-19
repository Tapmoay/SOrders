package com.tapmoay.sorders.ai

/**
 * **表格文本的通用读法**：把用户贴进来/文件里读出来的一段文本，切成「一行若干格」。
 *
 * ### 为什么单独抽出来
 * 这段拆行拆列的规则原本长在 [AiPriceTable] 里（按表格调价）。到「按表格建商品」
 * （[AiProductTable]）时它要被用第二次——而这份规则恰恰是**最不该有两份**的那种：
 * 多一份就一定会有一份先被改、另一份留在原地，于是"同样一张表，调价能读、建商品读不了"，
 * 而两边的报错都说得头头是道。
 *
 * ### 能读的形状（都是从真实贴法倒推的，不是猜的）
 * - Tab（从 Excel 复制出来的就是它）、`|`（Markdown 表格）、`,` / `，`、
 *   中文顿号 `、`、**两个以上空格**，最后一档才是单个空格；
 * - 空行、Markdown 的分隔行（`|---|---|`）直接丢掉；
 * - 不删列、不去重、不纠正——**读到的就是原文**，判断留给各自的解析器。
 */
internal object AiTable {

    /** 一行：行号（= 用户看到的原文行号，报错和卡片上都要用它）+ 各格内容。 */
    data class Line(val lineNo: Int, val cells: List<String>)

    /** 拆成「每行若干格」。空行与 Markdown 分隔行丢掉。 */
    fun splitCells(text: String): List<Line> {
        val out = ArrayList<Line>()
        text.replace("\r\n", "\n").replace("\r", "\n").split("\n").forEachIndexed { i, raw ->
            val line = raw.replace('\u00a0', ' ').trimEnd()
            if (line.isBlank()) return@forEachIndexed
            // Markdown 表格的分隔行：|---|---| 或 |:--|--:|
            if (line.replace("|", "").replace(":", "").replace("-", "").replace(" ", "").isEmpty()) {
                return@forEachIndexed
            }
            out += Line(i + 1, splitLine(line))
        }
        return out
    }

    /** 拆一行里的各格。顺序 = 优先级：Tab 最先（Excel 粘贴的权威形态）。 */
    fun splitLine(line: String): List<String> {
        val s = line.trim().trim('|')
        return when {
            s.contains('\t') -> s.split('\t')
            s.contains('|') -> s.split('|')
            s.contains(',') || s.contains('，') -> s.split(',', '，')
            Regex("\\s{2,}").containsMatchIn(s) -> s.split(Regex("\\s{2,}"))
            s.contains('、') -> s.split('、')
            // 最后一档：单个空格（商品名里带空格的情况很少，且此时通常有表头）
            else -> s.split(' ')
        }.map { it.trim() }
    }

    /**
     * 这一行像不像表头。
     *
     * 两条判据缺一不可（单测抓出来的）：
     * ① 命中至少一个 [words] 里的词；
     * ② 这一行**一个数字都没有**——数据行几乎必然带数字，表头行通常不带。
     *    少了 ②，「红富士苹果 城东水果批发 下调7.5%」这种单行表会被整行当成表头。
     */
    fun looksLikeHeader(line: Line, words: List<String>): Boolean {
        val norm = line.cells.map { AiWriteArgs.norm(it) }
        val hit = norm.any { c -> c.isNotEmpty() && words.any { w -> c.contains(AiWriteArgs.norm(w)) } }
        val hasDigit = line.cells.any { c -> c.any { ch -> ch.isDigit() } }
        return hit && !hasDigit
    }
}
