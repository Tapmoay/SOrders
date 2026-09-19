package com.tapmoay.sorders.ai

/**
 * 用户**挂载给 AI 的文件**（附件）——「把这个 Excel 传上去让它看看」这条路的数据模型。
 *
 * ### 它解决的是哪件事
 * 在这之前，AI 能看到的只有**系统库里的数据**（走 `read_data` 那 36 张表）。
 * 用户手里那张"我自己的商品表/账单表"它一个字都看不到，于是他只能一个字一个字打进来。
 * 附件就是把这扇门打开：**文件由服务端读成文本表格**（见后端 `files/parse-sheet`），
 * 这里负责把它变成模型看得懂的一段话，以及界面上那个能核对的小卡片。
 *
 * ### 三条不许违反的规矩
 * 1. **截断必须说出来**。读到第 200 行就停，那就要写「这张表一共 500 行，只附了前 200 行」。
 *    不说的话用户会以为模型看到了整张表，然后拿它的结论去做决定——而那个结论只覆盖了 40%。
 * 2. **不给模型"重打一遍"的机会**。附件内容以 **TSV 原文**交出去（不是让模型转写成 JSON）：
 *    要写数据时，模型把原文交给写操作，由 App 侧的确定性解析器去读（见 `AiWriteProductTable`）。
 *    模型"翻译"一次就多一次出错的机会，而且漏行/串列**看不出来**。
 * 3. **附件只进这一轮提问，不写进长期记忆**。用户的文件内容是他自己的数据，
 *    记忆是"跨对话自动注入"的东西，两者混起来等于把他表里的每一行都在以后每次对话里重放一遍。
 *
 * @param filename 文件名（带扩展名，界面上显示的就是它）
 * @param kind 后端判定的类型：`xlsx` / `text` / `tsv`
 * @param tables 读出来的工作表（Excel 可能有多张）
 * @param warnings 后端给的实话：编码是猜的、行被截断了、有工作表没读……
 */
data class AiAttachment(
    val filename: String,
    val kind: String,
    val tables: List<Table>,
    val warnings: List<String> = emptyList(),
    /**
     * 图片附件：`data:image/jpeg;base64,...`。
     *
     * 非 null 时 [tables] 一定是空的——图片**不走服务端解析**，它直接作为多模态内容
     * 发给模型（见 [LlmClient.ChatMessage.images]）。
     */
    val imageDataUrl: String? = null,
    /** 图片的规模说明（"长边 1280 · 约 180 KB"），卡片上给用户看。 */
    val imageMeta: String = "",
    /**
     * 图片来源（相册/拍照那条 `content://` 或 `file://` 的字符串）。
     *
     * 为什么值得存：附件面板里那一排"最近照片"要能**取消勾选**——取消时得知道
     * 当前挂着的哪个附件对应屏幕上哪张图。靠文件名或下标都对不上（同一张图可能重名、
     * 附件列表还会被后面的挂载插队）。存下来源是最直接的对账方式。
     *
     * **不参与任何发给模型的内容**（提示词块里没有它），所以不影响 token，也不进历史。
     */
    val sourceUri: String = "",
) {

    val isImage: Boolean get() = imageDataUrl != null

    /** 一张读出来的表。 */
    data class Table(
        val name: String,
        /** 每一格都是文本（数字/日期在后端已经格式化好，手机端不再做类型判断）。 */
        val rows: List<List<String>>,
        /** **截断前**的真实行数。 */
        val rowCount: Int,
        val colCount: Int,
        val truncated: Boolean,
    ) {
        /** 表头（第一行）。空表返回空列表。 */
        val header: List<String> get() = rows.firstOrNull().orEmpty()

        /** 数据行（去掉表头）。 */
        val body: List<List<String>> get() = if (rows.size > 1) rows.drop(1) else emptyList()
    }

    /** 这张附件一共带回来多少行（所有工作表相加）。 */
    val rowTotal: Int get() = tables.sumOf { it.rows.size }

    /**
     * 界面上那个 chip 主标题：「商品清单.xlsx」。
     * 文件名太长时截断——chip 是给人一眼扫的，不是给人读的。
     */
    fun title(): String = filename.ifBlank { "附件" }.let { if (it.length <= 24) it else it.take(23) + "…" }

    /**
     * chip 副标题：「商品清单 · 200 行 × 5 列」；多张表时写「3 张表 · 共 200 行」。
     * **截断在这里就要说出来**（"前 200 行 / 共 512 行"），因为这是用户唯一能看到的地方。
     */
    fun summary(): String {
        if (isImage) return listOf("图片", imageMeta).filter { it.isNotBlank() }.joinToString(" · ")
        if (tables.isEmpty()) return "没读到内容"
        if (tables.size == 1) {
            val t = tables[0]
            val head = t.name.take(12).ifBlank { "表 1" }
            return "$head · ${t.rowCount} 行 × ${t.colCount} 列" + if (t.truncated) "（只附了前 ${t.rows.size} 行）" else ""
        }
        val cut = tables.any { it.truncated }
        return "${tables.size} 张表 · 共 ${tables.sumOf { it.rowCount }} 行" + if (cut) "（有表被截断）" else ""
    }

    /** chip 上要不要显示一个"有话说"的角标（编码是猜的 / 有表没读）。 */
    val hasWarnings: Boolean get() = warnings.isNotEmpty()

    companion object {

        /** 一次最多挂几个文件。3 个足够表达"商品表 + 价格表"这种组合，再多只会把上下文撑爆。 */
        const val MAX_FILES = 3

        /**
         * 一个附件最多占多少字符（约 3~4k token）。
         *
         * 为什么要有：附件是被塞进**用户消息**里的，而用户消息是上下文的一部分。
         * 一张 200 行 × 10 列的表大约 12 万字符，直接发出去的话
         * 要么被压缩器砍掉一半（用户不知道），要么直接撞上窗口上限报错。
         * 12000 字符 ≈ 一个"看得清表头、看得清前几十行"的量。
         */
        const val MAX_PROMPT_CHARS = 12000

        /** 交给模型时，一张表**至少**要保留的行数（哪怕列很宽）。只看得到表头等于没看到。 */
        const val MIN_ROWS = 10

        /**
         * 附件的**硬天花板**（字符）。
         *
         * 和 [MAX_PROMPT_CHARS] 是两个概念，缺一不可：
         * - [MAX_PROMPT_CHARS] 是**预算**：正常情况下按它截断（一个"看得清表头、看得清前几十行"的量）；
         * - 这个是**灾难闸**：列特别宽时（后端允许单格 200 字符 × 40 列 = 一行 8000 字符），
         *   光守预算会让 [MIN_ROWS] 那 10 行根本放不进去，于是"一张宽表只能看到 3 行"——
         *   那还不如不传。所以宽表允许突破预算，但**不许无上限**。
         */
        const val HARD_MAX_CHARS = MAX_PROMPT_CHARS * 4

        /**
         * 把用户这次提问**连同附件**拼成真正发给模型的那段话。
         *
         * 没有附件时**原样返回**用户那句话——一个字都不加：
         * 多的每一个字都在教模型"这句话有什么弦外之音"。
         */
        fun augment(userText: String, items: List<AiAttachment>): String {
            if (items.isEmpty()) return userText
            val head = if (userText.isBlank()) {
                // 只传了文件、没写要求。**不替用户决定**要做什么，只让他先看懂再问——
                // 这是系统提示词里"缺信息就问"那条规则在附件这条路上的落点。
                "用户传了下面这个文件，没有写具体要求。请先用一两句话说明" +
                    "这是什么文件、有哪些列，然后问他要用它做什么。不要擅自改动任何数据。"
            } else {
                userText
            }
            val sb = StringBuilder(head)
            sb.append("\n\n")
            sb.append("【附件】以下是用户上传的文件内容（他自己带来的数据，不是系统库里的数据）")
            sb.append("：\n")
            items.forEachIndexed { i, a ->
                sb.append("\n")
                sb.append(block(i + 1, items.size, a))
            }
            if (items.any { it.isImage }) {
                // 图片是**真的发给模型看**的（多模态），不是转成文字。
                // 所以这里要教它一件事：看不清就说看不清——**不许猜**。
                // 猜出来的商品名/单号会一路带进确认卡和写操作，用户按着幻觉下单是最坏的结果。
                sb.append("\n图片是原图直接发给你的（不是转成文字），可以直接看。")
                sb.append("如果图里的字看不清、或者你需要的信息不在图里，**直说看不清并请用户重拍或补充**，")
                sb.append("不要凭印象猜内容（猜错的名字/单号会一路写进系统）。\n")
            }
            sb.append("\n写数据时把附件里的表格**原样**交给对应操作（不要自己重排、漏行或改数字）——")
            sb.append("系统会自己读那张表，读到的每一行都会列在确认卡上让用户核对。")
            return sb.toString()
        }

        /** 这一批附件里的图片 data URL（发给模型的多模态内容）。 */
        fun imagesOf(items: List<AiAttachment>): List<String> =
            items.mapNotNull { it.imageDataUrl }

        /** 单个附件那一段（含「截断了多少」这句实话）。 */
        fun block(index: Int, total: Int, a: AiAttachment): String {
            val sb = StringBuilder()
            sb.append("— 文件 $index/$total：${a.filename} —\n")
            if (a.isImage) {
                sb.append("（这是一张图片，已经作为图片发给你了${if (a.imageMeta.isNotBlank()) "；${a.imageMeta}" else ""}）\n")
                a.warnings.forEach { sb.append("⚠️ ").append(it).append("\n") }
                return sb.toString()
            }
            if (a.tables.isEmpty()) {
                sb.append("（这个文件里没有读到任何一行内容）\n")
            }
            a.tables.forEachIndexed { ti, t ->
                val label = if (a.tables.size > 1) "工作表「${t.name}」" else "内容"
                sb.append("$label：${t.rowCount} 行 × ${t.colCount} 列")
                if (t.truncated) sb.append("（**只附了前 ${t.rows.size} 行**，其余没有发给你）")
                sb.append("。列之间用 Tab 分隔，第一行通常是表头：\n")
                val (tsv, shown) = renderTsv(t)
                sb.append("```tsv\n").append(tsv).append("\n```\n")
                if (shown < t.rows.size) {
                    sb.append("（这一段按长度上限截断，实际只附了前 $shown 行）\n")
                }
                if (ti < a.tables.size - 1) sb.append("\n")
            }
            a.warnings.forEach { sb.append("⚠️ ").append(it).append("\n") }
            return sb.toString()
        }

        /**
         * 一张表 → TSV 文本。返回（文本, 真正放进去的行数）。
         *
         * 行数上限与**字符**上限是两个闸门，都要有：
         * 列少的表能放 200 行，列特别宽的表可能 20 行就到顶了。
         */
        private fun renderTsv(t: Table): Pair<String, Int> {
            val sb = StringBuilder()
            var shown = 0
            for (row in t.rows) {
                val line = row.joinToString("\t") { cell(it) }
                // 两道闸：① 到预算就停（但先保证 MIN_ROWS 行，否则只剩表头等于没看到）；
                //          ② 单行特别宽（列多）时也不许突破硬天花板。
                if (shown >= MIN_ROWS && sb.length + line.length + 1 > MAX_PROMPT_CHARS) break
                if (sb.length > HARD_MAX_CHARS) break
                sb.append(line).append("\n")
                shown++
            }
            if (sb.isNotEmpty()) sb.setLength(sb.length - 1) // 去掉最后一个换行
            return sb.toString() to shown
        }

        /**
         * 一格 → TSV 里的一格。
         *
         * 制表符/换行必须换成空格：格子里的一个 `\t` 会让**整行往后串一列**，
         * 而这种错位在模型眼里和"这张表本来就是这样"没有区别。
         * 空格子**留空**（TSV 里连续两个 Tab 就是"这一格是空的"，本来就没有歧义；
         * 补一个 `-` 之类的占位符反而会被当成真的内容）。
         */
        private fun cell(raw: String): String =
            raw.replace('\t', ' ').replace('\n', ' ').replace('\r', ' ').trim()
    }
}
