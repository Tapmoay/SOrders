package com.tapmoay.sorders.ai

/**
 * 一张批量确认卡上要画的那张**长表格**（CHG-0119）。
 *
 * ### 为什么要有它（用户 2026-10-11 的原话）
 * 「他那个确认卡呀，他不要一个（角色）一个（角色）的弹啊……如果是叫他批量干活的话，
 *   那个确认卡也是只弹一个，只是那个表格卡是多个、长表格显示多个人，这样就省事。」
 * 之前 40 条批发商专属价被**一张张弹**，用户在 14:21 连着看到 4 条
 * 「没写成：这张确认卡已经失效了（有效期 5 分钟…）」——卡还没点就作废，活儿白干。
 *
 * ### 它是什么
 * 「这一批要干什么」的**全是数据**：表头 + 每行 + 一句「这表没画全」的说明。
 * 界面（`ui/ai/AiChatScreen.kt` 的 `BatchCardTable`）只负责画这几行；
 * 「怎么从 N 张单条卡里抽列」只有 [AiCardBatchTable.sheet] 一处实现。
 *
 * ⛔ 它**不参与写库**：表格是从暂存区里那 N 条 payload 的明细**渲染**出来的，
 *    真正写下去的仍然是 `_batch` 数组里的 payload（见 [BatchWriteHandler]）。
 *    ⇒ 表格里少一行、少一列，都**不会**让写下去的条数变少。
 *
 * @param headers 表头，第 1 列固定 [AiCardBatchTable.INDEX_HEADER]、第 2 列 [AiCardBatchTable.SUBJECT_HEADER]、
 *   第 3 列 [AiCardBatchTable.CHANGE_HEADER]（用户要看的就是「谁 · 改前 → 改后」）。
 * @param rows 与 [headers] 等长的行；格子里没有值时是 [AiCardBatchTable.MISSING]，**不是空串**
 *   （空串在表格里看起来像"这一格没渲染出来"，破折号才读得出"这一项本来就没有"）。
 * @param note 表后面那一句实话：行数超了、列数超了分别说清 —— 空串表示"这一批全画下了"。
 */
data class AiCardBatchTableSheet(
    val headers: List<String>,
    val rows: List<List<String>>,
    val note: String,
)

/**
 * 把 N 张单条确认卡压成一张【序号 / 对象 / 改前 → 改后 / 其余字段…】的表格（CHG-0119）。
 *
 * ### 数据从哪来（没有新数据源）
 * [BatchWriteHandler] 手里的 `rows` 本来就是**逐条 prepare 出来的** [AiPendingWrite]：
 * 每条都有 `summary`（谁 + 干什么）与 `bodyLines`（处理器写的「标签：值」行）。
 * 表格只是把它们**转置**：标签取并集当表头，每条卡按标签取值当一行 —— 一行一个人/一条价。
 *
 * ### ⛔ 不许在这里自己切冒号
 * 「标签：值」的判定全仓只有一份（[AiCardTable.asPair]，用户 2026-09-20 要求卡片信息一律走表格）。
 * 这里再写一份 `indexOf('：')` 就会出现两套判定，改一处漏一处。
 *
 * ### 超限只说清、不拦人
 * 行数超过 [MAX_ROWS]、列数超过 [MAX_COLS] 时**照旧执行全部**（用户 2026-09-21 拍板
 * 「批量是没有上限的」），只是把「表里只列了前 N 条」写进 [AiCardBatchTableSheet.note]。
 */
internal object AiCardBatchTable {

    /** 第 1 列：序号。用户逐行核对的锚点（"第 3 条不对"）。 */
    const val INDEX_HEADER = "序号"

    /** 第 2 列：目标对象。取每条卡自己的 `summary`（处理器写的那句"谁 + 干什么"）。 */
    const val SUBJECT_HEADER = "对象"

    /** 第 3 列：改前 → 改后。**用户唯一真正要看的那一列**（这次到底把什么改成了什么）。 */
    const val CHANGE_HEADER = "改前 → 改后"

    /** 格子里没有值时的占位符（见 [AiCardBatchTableSheet.rows] 的 KDoc）。 */
    const val MISSING = "—"

    /** 表最多几列：再多手机上就得横向滚，标题栏也会被挤成两个字。 */
    const val MAX_COLS = 7

    /** 表最多几行：与既有批量口径同一个数（`AiPriceTable.MAX_ROWS`，写入侧逐行执行上限）。 */
    const val MAX_ROWS = 30

    /** 「改前 → 改后」这个箭头是各处理器写明细时的既有约定（如「原来：10.00 元 → 现在：12.00 元」）。 */
    private const val ARROW = "→"

    /**
     * 造一张表。
     *
     * @param items 逐条 prepare 出来的单条卡（顺序就是执行顺序）。
     */
    fun sheet(items: List<AiPendingWrite>): AiCardBatchTableSheet {
        // 每一格的「标签 → 值」：判定复用确认卡那一份（AiCardTable.asPair），这里不切冒号。
        val pairs = items.map { item -> item.bodyLines.mapNotNull { AiCardTable.asPair(it) } }
        // 表头 = 固定的前 3 列 + 各条卡里出现过的标签（按**首次出现的顺序**，不是字母序：
        // 处理器写明细的顺序就是用户该读的顺序）。
        val labels = ArrayList<String>(MAX_COLS)
        pairs.forEach { row -> row.forEach { p -> if (p.label !in labels) labels += p.label } }
        val extra = labels.take((MAX_COLS - 3).coerceAtLeast(0))
        val headers = listOf(INDEX_HEADER, SUBJECT_HEADER, CHANGE_HEADER) + extra
        val shown = items.take(MAX_ROWS)
        val rows = shown.mapIndexed { i, item ->
            listOf("${i + 1}", item.summary, changeOf(item, pairs[i])) +
                extra.map { label -> pairs[i].firstOrNull { it.label == label }?.value ?: MISSING }
        }
        return AiCardBatchTableSheet(
            headers = headers,
            rows = rows,
            note = noteOf(items.size, shownCols = extra.size, allCols = labels.size),
        )
    }

    /**
     * 这一条的「改前 → 改后」。
     *
     * 优先取**值里带箭头**的那一行（各处理器的既有写法，如「原来」→「10.00 元 → 现在：12.00 元」）；
     * 没有箭头就退到第一条「标签：值」的值；连一条明细都没有时退到 `summary`
     * （它本来就写着"谁 + 干什么"，对"新建一条"这类没有改前值的动作它就是全部信息）。
     */
    private fun changeOf(item: AiPendingWrite, row: List<AiCardTable.Row.Pair>): String {
        row.firstOrNull { it.value.contains(ARROW) }?.let { return it.value }
        row.firstOrNull()?.let { return it.value }
        return item.summary
    }

    /** 表后面那句实话：**行没列全、列没列全都要说**（静默截断 = 用户以为表就是全部）。 */
    private fun noteOf(total: Int, shownCols: Int, allCols: Int): String = buildString {
        if (total > MAX_ROWS) {
            append("共 ${total} 条，表里只列了前 ${MAX_ROWS} 条（点确认仍然是这 ${total} 条全部执行）。")
        }
        if (allCols > shownCols) {
            if (isNotEmpty()) append('\n')
            append("另有 ${allCols - shownCols} 个字段没列出来（表最多 ${MAX_COLS} 列），每一条的明细都在正文里。")
        }
    }
}
