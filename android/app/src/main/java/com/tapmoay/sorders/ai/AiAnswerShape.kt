package com.tapmoay.sorders.ai

/**
 * **呈现兜底**：助手答复里连续的「标签：值」散行，自动补成一张两列小表（表头为空）。
 *
 * ### 为什么提示词之外还要有代码兜底
 * 提示词（[AiAnswerSkills]）管的是「模型想不想排」，兜底管的是「模型没排时用户看到什么」。
 * 用户 2026-10-09 那张截图（ref m35394）就是没排的那种：
 *
 *     • 收货人：张三
 *     • 电话：13900002222
 *     • 终点地址：幸福路 18 号
 *
 * 三行同样的灰字排下来，值在哪、标签是哪个只能一行行读 —— 他说的就是这一眼：
 * 「上面有文字下面有信息混在一起就很难分辨出来」。而「标签：值」是**确定性形状**，代码认得出；
 * 认得出就该画成表（确认卡信息区从 2026-09-20 起就是这么做的）。
 *
 * ### 判定只有一份
 * 「这行算不算标签：值」的规则复用 [AiCardTable.asPair]（标签 ≤10 字、按第一个冒号切、
 * 标签里不许有空格 / 中点 / 箭头）。⛔ 不要在这里再写一份 —— 两份判定迟早走散，
 * 同一句话在确认卡里是表格、在回答里却是散行。
 *
 * ### 只做三件事
 * 1. **连续 ≥ [MIN_ROWS] 行**都是「标签：值」才成表；单独一行不成表（一行就是一行，多画一层框反而重）。
 * 2. 只吸 [AiMarkdown.Block.Kind.TEXT] 与 [AiMarkdown.Block.Kind.BULLET]：标题、编号步骤、
 *    模型自己写好的 Markdown 表格一律不动（那些他已经排过了）。
 * 3. 值必须短（显示宽度不超过 [MAX_VALUE_WIDTH]、不带句读）：值是一整句话时它该留在正文里，
 *    塞进单元格只会把表格撑成一团（[AiAnswerStyle] 第 9 条同一口径：单元格里只放短语）。
 *
 * ### 为什么在**上色之前**跑
 * [AiAnswerTone] 的既有裁定是「表格不参与上色」（表格画在中性白卡上）。兜底若在上色之后做，
 * 那些刚染上色的行会带着染色名额进表格、颜色随后被丢掉 —— 名额白花，后面的行反而没颜色。
 * 所以顺序是 parse → [apply] → tone。
 *
 * ### 为什么只对助手气泡生效
 * 调用点（`AiRichText`）只在 toned 为真时跑它：用户自己写的话原样显示，⛔ 不替他排版。
 */
internal object AiAnswerShape {

    /** 至少几行才成表：一行「标签：值」就是一行，画成表反而多一层框。 */
    const val MIN_ROWS: Int = 2

    /** 值最长多少（显示宽度，汉字算 2）：再长就是一句话，该留在正文里。 */
    const val MAX_VALUE_WIDTH: Int = 24

    /** 值里带这些标点就是在叙述，不是在给一个值。 */
    private val CLAUSE_MARKS = listOf('。', '！', '？', '；', '，')

    /**
     * 兜底：把连续的「标签：值」散行合成 [AiMarkdown.Block.Table]（header 为空 = 无表头两列表）。
     *
     * 纯函数：不碰 UI、不碰 IO —— 单测直接喂 [AiMarkdown.parse] 的结果（`AiAnswerShapeTest`）。
     */
    fun apply(blocks: List<AiMarkdown.Block>): List<AiMarkdown.Block> {
        val out = ArrayList<AiMarkdown.Block>(blocks.size)
        var i = 0
        while (i < blocks.size) {
            if (pairAt(blocks[i]) == null) {
                out += blocks[i]
                i++
                continue
            }
            val rows = ArrayList<List<String>>()
            var j = i
            while (j < blocks.size) {
                val p = pairAt(blocks[j]) ?: break
                rows += listOf(p.label, p.value)
                j++
            }
            if (rows.size >= MIN_ROWS) {
                out += AiMarkdown.Block.Table(header = emptyList(), body = rows)
                i = j
            } else {
                out += blocks[i]
                i++
            }
        }
        return out
    }

    /** 这一块能不能当表里的一行；不能就返回 null（调用方按原样处理）。 */
    private fun pairAt(block: AiMarkdown.Block): AiCardTable.Row.Pair? {
        val line = block as? AiMarkdown.Block.Line ?: return null
        if (line.kind != AiMarkdown.Block.Kind.TEXT && line.kind != AiMarkdown.Block.Kind.BULLET) return null
        val text = line.spans.joinToString("") { it.text }.trim()
        val pair = AiCardTable.asPair(text) ?: return null
        if (!looksLikeValue(pair.value)) return null
        return pair
    }

    /** 值像不像「一个值」：短语、不带句读（一整句话该留在正文里）。 */
    private fun looksLikeValue(value: String): Boolean {
        if (value.any { it in CLAUSE_MARKS }) return false
        if (value.endsWith('：') || value.endsWith(':')) return false
        return AiMarkdown.displayWidth(value) <= MAX_VALUE_WIDTH
    }
}
