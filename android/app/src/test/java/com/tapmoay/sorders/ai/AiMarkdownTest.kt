package com.tapmoay.sorders.ai

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * [AiMarkdown] 的单元测试。
 *
 * 表格解析是这里最值得测的部分：**列数不齐、分隔行、空单元格、被 ``` 包住、只有一行像表格**
 * ——每一种都真实出现过，而且出错的方式很安静（少一列 → 数字错位 → 用户看到的是一张错表，
 * 不是报错）。所以这里逐条钉住。
 */
class AiMarkdownTest {

    private fun tables(text: String) =
        AiMarkdown.parse(text).filterIsInstance<AiMarkdown.Block.Table>()

    private fun lines(text: String) =
        AiMarkdown.parse(text).filterIsInstance<AiMarkdown.Block.Line>()

    // ================================================================== 表格

    @Test
    fun parsesSimplePipeTableAndDropsSeparatorRow() {
        val t = tables(
            """
            | 司机 | 单量 | 准时率 |
            |---|---|---|
            | 王建国 | 22 | 31.8% |
            | 赵德海 | 22 | 36.4% |
            """.trimIndent(),
        ).single()

        assertEquals(listOf("司机", "单量", "准时率"), t.header)
        assertEquals(2, t.body.size)
        assertEquals(listOf("王建国", "22", "31.8%"), t.body[0])
        assertEquals(listOf("赵德海", "22", "36.4%"), t.body[1])
    }

    @Test
    fun parsesTableWithoutLeadingAndTrailingPipes() {
        val t = tables(
            """
            司机 | 单量
            --- | ---
            王建国 | 22
            """.trimIndent(),
        ).single()
        assertEquals(listOf("司机", "单量"), t.header)
        assertEquals(listOf("王建国", "22"), t.body.single())
    }

    @Test
    fun padsUnevenRowsSoColumnsNeverShift() {
        // 第 2 行少一列、第 3 行多一列 —— 补齐后每行列数一致，数字不会错位
        val t = tables(
            """
            | A | B | C |
            |---|---|---|
            | 1 | 2 |
            | 3 | 4 | 5 | 6 |
            """.trimIndent(),
        ).single()
        assertEquals(4, t.header.size)
        assertTrue("每行列数必须一致", t.body.all { it.size == t.header.size })
        assertEquals(listOf("1", "2", "", ""), t.body[0])
        assertEquals(listOf("3", "4", "5", "6"), t.body[1])
    }

    @Test
    fun parsesTableWrappedInCodeFence() {
        // 模型经常把表格包在 ``` 里；围栏只剥壳，不能因此丢掉整张表
        val t = tables(
            """
            下面是对比：
            ```
            | 项目 | 本月 | 上月 |
            |---|---|---|
            | 单量 | 73 | 125 |
            ```
            """.trimIndent(),
        ).single()
        assertEquals(listOf("项目", "本月", "上月"), t.header)
        assertEquals(listOf("单量", "73", "125"), t.body.single())
    }

    @Test
    fun singleTableLookingLineFallsBackToPlainText() {
        // 只有一行带竖线（比如"甲 | 乙"），不该被当成只有表头的表
        assertTrue(tables("甲 | 乙 | 丙").isEmpty())
        assertEquals(1, lines("甲 | 乙 | 丙").size)
    }

    @Test
    fun stripsBoldInsideTableCellsAndSeparatorVariants() {
        val t = tables(
            """
            | 名称 | 值 |
            |:---|---:|
            | **合计** | 12 |
            """.trimIndent(),
        ).single()
        assertEquals(listOf("名称", "值"), t.header)
        assertEquals("合计", t.body.single()[0])
    }

    @Test
    fun tableColumnWeightsFavourLongColumnsAndClampOutliers() {
        val w = AiMarkdown.columnWeights(
            listOf("司机", "单量"),
            listOf(listOf("王建国", "22"), listOf("这是一段特别特别长的备注说明文字", "3")),
        )
        assertEquals(2, w.size)
        assertTrue("长列权重应更大", w[1] < w[0])
        assertTrue("权重有上限，不能让一列吃掉整个宽度", w[0] <= 18f)
        assertTrue("权重有下限，窄列也要能看见", w[1] >= 3f)
    }

    @Test
    fun displayWidthCountsHanAsTwo() {
        assertEquals(4, AiMarkdown.displayWidth("司机"))
        assertEquals(2, AiMarkdown.displayWidth("22"))
        assertEquals(5, AiMarkdown.displayWidth("司机2"))
    }

    // ================================================================== 行内

    @Test
    fun parsesBoldSpans() {
        val spans = AiMarkdown.inline("按**单量**排，共 3 条")
        assertEquals(listOf("按", "单量", "排，共 3 条"), spans.map { it.text })
        assertEquals(listOf(false, true, false), spans.map { it.bold })
    }

    @Test
    fun unclosedBoldIsTreatedAsPlainText() {
        // 模型偶尔漏一个 ** —— 不能让后面整段都变粗
        val spans = AiMarkdown.inline("结论：**按单量 共 3 条")
        assertEquals(listOf(false), spans.map { it.bold }.distinct())
    }

    @Test
    fun stripsInlineBackticks() {
        assertEquals(listOf("用 库存报警 查"), AiMarkdown.inline("用 `库存报警` 查").map { it.text })
    }

    // ================================================================== 其它行

    @Test
    fun recognisesHeadingsBulletsAndNumberedItems() {
        val ls = lines(
            """
            ## 两点提醒
            - 第一条
            * 第二条
            1. 第三条
            2、第四条
            普通一段
            """.trimIndent(),
        )
        assertEquals(AiMarkdown.Block.Kind.HEADING, ls[0].kind)
        assertEquals("两点提醒", ls[0].spans.single().text)
        assertEquals(AiMarkdown.Block.Kind.BULLET, ls[1].kind)
        assertEquals(AiMarkdown.Block.Kind.BULLET, ls[2].kind)
        assertEquals(AiMarkdown.Block.Kind.NUMBERED, ls[3].kind)
        assertEquals("1.", ls[3].marker)
        assertEquals(AiMarkdown.Block.Kind.NUMBERED, ls[4].kind)
        assertEquals("2.", ls[4].marker)
        assertEquals(AiMarkdown.Block.Kind.TEXT, ls[5].kind)
    }

    @Test
    fun handlesBlankAndCrlfWithoutCrashing() {
        assertTrue(AiMarkdown.parse("").isEmpty())
        assertTrue(AiMarkdown.parse("   \n  ").isEmpty())
        assertEquals(2, lines("第一行\r\n\r\n第二行").size)
    }

    @Test
    fun decimalNumberAtLineStartIsNotTreatedAsListMarker() {
        // `3.5 元` 不能被当成「第 3 项，内容 = 5 元」——金额被吃掉一位是最不能忍的错
        val ls = lines("3.5 元每箱")
        assertEquals(AiMarkdown.Block.Kind.TEXT, ls.single().kind)
        assertEquals("3.5 元每箱", ls.single().spans.single().text)
    }

    @Test
    fun columnCharWidthsDriveRealTableLayout() {
        // 真表格的列宽靠它：内容最长的那个决定"这列至少要留多宽"，
        // 否则 `100.0%` 会被挤成三行（实测就是这个问题，用户原话"看不清"）
        val w = AiMarkdown.columnCharWidths(
            listOf("司机", "单量"),
            listOf(listOf("王建国", "22"), listOf("固定工资司机", "100.0%")),
        )
        assertEquals(listOf(12, 6), w)
        // 单列内容超长时封顶，避免一句整话把表撑爆
        assertEquals(
            listOf(24),
            AiMarkdown.columnCharWidths(listOf("这是一段特别特别长的备注说明文字" + "很长".repeat(20)), emptyList()),
        )
    }

    @Test
    fun toPlainTextKeepsTableReadable() {
        val plain = AiMarkdown.toPlainText(
            """
            | 司机 | 单量 |
            |---|---|
            | 王建国 | 22 |
            """.trimIndent(),
        )
        assertTrue("不该再出现 Markdown 分隔行", !plain.contains("---"))
        assertTrue(plain.contains("王建国"))
    }
}
