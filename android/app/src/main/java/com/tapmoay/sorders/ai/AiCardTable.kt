package com.tapmoay.sorders.ai

/**
 * **确认卡「信息区」的结构**：把各家处理器产出的 `detailLines` 解析成「标签 / 值」行。
 *
 * ## 为什么要有这一步（用户 2026-09-20）
 * 用户截了一张确认卡，把信息区框出来说：
 * > 所有卡片只要是那里显示的信息，尽量都使用表格的形式…核心目标是**将信息正确且明显地展示出来**。
 * > 如果只是文字的信息的话太看不清了。
 *
 * 那一块原来是**一列纯文字**（`AiChatScreen` 里 `p.detailLines.forEach { Text(it) }`），
 * 而卡片文案本来就是**成对**的（「订单号：SO…」「地点：旧仓库 → 新仓库」），
 * 全靠一串同样的灰字排下来 —— 值在哪、标签是哪个，只能一行行读。
 *
 * ## 为什么不改那 50 个处理器、改成"处理器给结构化数据"
 * `detailLines` 是 ~50 个处理器（含声明式 CRUD）的公共出参，形状统一是「标签：值」。
 * 让每个处理器改成一个新类型＝**动 50 个文件**，而其中任何一处漏改都会让那张卡**少一行**
 * ——用户看不出来少了什么（这正是本项目最怕的那种 bug）。
 * 在这里解析一次，**所有卡片一起变表格**，而处理器那边一个字都不用动。
 *
 * ## 判据（三条，宁可判成整行，也不要猜错标签）
 * 1. `———— xxx ————` → [Row.Section]（分段标题，跨整行）
 * 2. `标签：值`（第一个全角/半角冒号切）→ [Row.Pair]，**标签要像标签**：
 *    非空、不超过 [MAX_LABEL] 个字、不含空格/「·」/emoji 前缀 ——
 *    否则判成 [Row.Full]（例：「⚠️ 写进去就撤不回来」「· 第 3 行 老王：…」）。
 * 3. 其余 → [Row.Full]（跨整行的说明/警告/列表项），**一字不改地照原样显示**。
 *
 * ⚠️ 值里**允许**再出现冒号（「备注：9:30 送到」→ 标签「备注」、值「9:30 送到」）：
 *    只按**第一个**冒号切。切错了会让用户读到"标签是半句话"，比不切更糟。
 */
internal object AiCardTable {

    /** 标签最多几个字（超过就不像标签了，当整行）。 */
    const val MAX_LABEL = 10

    sealed interface Row {
        /** 分段标题（原来写作 `———— xxx ————`）。 */
        data class Section(val text: String) : Row

        /** 标签 + 值 —— 表格里最普通的一行。 */
        data class Pair(val label: String, val value: String) : Row

        /** 跨整行的一句话（警告 / 列表项 / 说明）。 */
        data class Full(val text: String) : Row
    }

    /** `———— 用这个点的坐标 ————` / `---- xx ----` / `==== xx ====`（处理器里三种都出现过）。 */
    private val SECTION = Regex("^[-—=~]{2,}\\s*(.+?)\\s*[-—=~]{2,}$")

    /**
     * 解析一坨 [lines]。空行被丢掉（它们只用来在纯文本里分段，表格里由行高负责）。
     *
     * 纯函数：不碰 UI、不碰 IO —— 单测直接喂字符串列表（`AiCardTableTest`）。
     */
    fun rows(lines: List<String>): List<Row> {
        val out = ArrayList<Row>(lines.size)
        for (raw in lines) {
            val line = raw.trim()
            if (line.isEmpty()) continue
            val sec = SECTION.matchEntire(line)
            if (sec != null) {
                val title = sec.groupValues[1].trim()
                if (title.isNotEmpty()) out += Row.Section(title)
                continue
            }
            out += asPair(line) ?: Row.Full(line)
        }
        return out
    }

    /** 这一行能不能当「标签：值」；不能就返回 null（调用方按整行处理）。 */
    private fun asPair(line: String): Row.Pair? {
        // 第一个冒号（全角优先：中文文案里几乎全是全角）
        val idx = line.indexOfFirst { it == '：' || it == ':' }
        if (idx <= 0 || idx >= line.length - 1) return null
        val label = line.substring(0, idx).trim()
        val value = line.substring(idx + 1).trim()
        if (value.isEmpty()) return null
        if (label.isEmpty() || label.length > MAX_LABEL) return null
        // 标签里不该有空格 / 「·」/ 箭头 —— 有的话它其实是一句话，不是标签
        if (label.any { it.isWhitespace() || it == '·' || it == '→' }) return null
        return Row.Pair(label, value)
    }
}
