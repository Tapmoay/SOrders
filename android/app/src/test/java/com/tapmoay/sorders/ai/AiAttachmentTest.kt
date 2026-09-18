package com.tapmoay.sorders.ai

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 附件（挂载文件）的**提示词拼装**测试（[AiAttachment]，纯函数）。
 *
 * ### 这里保的是两件"用户看不见但会被坑"的事
 * 1. **截断必须说出来**：一张 500 行的表只发前 200 行时，模型和用户都必须知道，
 *    否则用户会拿一个只覆盖 40% 数据的结论去做决定。
 * 2. **格子里的制表符/换行必须换成空格**：一个 `\t` 会让整行往后串一列，
 *    而错位之后模型照样能"一本正经地"分析，看不出来。
 */
class AiAttachmentTest {

    private fun att(vararg rows: List<String>, truncated: Boolean = false, rowCount: Int = rows.size, warnings: List<String> = emptyList()) =
        AiAttachment(
            filename = "商品清单.xlsx",
            kind = "xlsx",
            tables = listOf(
                AiAttachment.Table(
                    name = "Sheet1",
                    rows = rows.toList(),
                    rowCount = rowCount,
                    colCount = rows.firstOrNull()?.size ?: 0,
                    truncated = truncated,
                ),
            ),
            warnings = warnings,
        )

    @Test
    fun `没有附件时一个字都不加`() {
        assertEquals("看看这个", AiAttachment.augment("看看这个", emptyList()))
    }

    @Test
    fun `有附件时带上文件名、规模与 TSV 原文`() {
        val text = AiAttachment.augment("照这个建商品", listOf(att(listOf("商品名", "单价"), listOf("苹果", "45.5"))))
        assertTrue(text, text.contains("照这个建商品"))
        assertTrue(text, text.contains("商品清单.xlsx"))
        assertTrue(text, text.contains("商品名\t单价"))
        assertTrue(text, text.contains("苹果\t45.5"))
        assertTrue(text, text.contains("2 行 × 2 列"))
    }

    @Test
    fun `截断了就必须写出来（附了多少行、总共多少行）`() {
        val a = att(listOf("商品名"), listOf("苹果"), rowCount = 500, truncated = true)
        val text = AiAttachment.block(1, 1, a)
        assertTrue(text, text.contains("500 行"))
        assertTrue(text, text.contains("只附了前 2 行"))
    }

    @Test
    fun `格子里的制表符与换行换成空格（否则整行串列）`() {
        val a = att(listOf("商品名", "备注"), listOf("苹果", "带\t制表符\n带换行"))
        val text = AiAttachment.augment("x", listOf(a))
        assertTrue(text, text.contains("带 制表符 带换行"))
        // 原文里的制表符只能出现在列分隔处：这一行必须正好是 2 列
        val line = text.lines().first { it.startsWith("苹果") }
        assertEquals(2, line.split("\t").size)
    }

    @Test
    fun `只传文件不打字时，不替用户决定要做什么`() {
        val text = AiAttachment.augment("", listOf(att(listOf("商品名"), listOf("苹果"))))
        assertTrue(text, text.contains("没有写具体要求"))
        assertTrue(text, text.contains("不要擅自改动任何数据"))
    }

    @Test
    fun `后端的实话原样带出去`() {
        val a = att(listOf("商品名"), listOf("苹果"), warnings = listOf("这个文件不是 UTF-8 编码，已按中文 GBK/GB18030 读取。"))
        val text = AiAttachment.block(1, 1, a)
        assertTrue(text, text.contains("GBK"))
    }

    @Test
    fun `chip 摘要写清截断，长文件名截短`() {
        val a = AiAttachment(
            filename = "这是一个特别特别特别特别长的商品清单文件名.xlsx",
            kind = "xlsx",
            tables = listOf(AiAttachment.Table("Sheet1", listOf(listOf("a")), rowCount = 512, colCount = 5, truncated = true)),
        )
        assertTrue(a.summary(), a.summary().contains("512 行"))
        assertTrue(a.summary(), a.summary().contains("只附了前 1 行"))
        assertTrue(a.title().length <= 24)
    }

    @Test
    fun `空表也有话说（不返回 null、不抛）`() {
        val a = AiAttachment("空.xlsx", "xlsx", emptyList())
        assertEquals("没读到内容", a.summary())
        assertTrue(AiAttachment.block(1, 1, a).contains("没有读到任何一行"))
        assertFalse(a.hasWarnings)
    }

    @Test
    fun `多张表时规模相加，任一被截断就标出来`() {
        val a = AiAttachment(
            filename = "多表.xlsx",
            kind = "xlsx",
            tables = listOf(
                AiAttachment.Table("A", listOf(listOf("x")), rowCount = 10, colCount = 1, truncated = false),
                AiAttachment.Table("B", listOf(listOf("y")), rowCount = 20, colCount = 1, truncated = true),
            ),
        )
        assertEquals(2, a.rowTotal)
        assertTrue(a.summary(), a.summary().contains("2 张表"))
        assertTrue(a.summary(), a.summary().contains("截断"))
    }

    @Test
    fun `超长表格按预算截断，且至少保留 10 行`() {
        // 20 列 × 200 字符 = 每行约 4000 字符 → 10 行就到 4 万，远超 12000 的预算
        val wide = (1..20).map { "很长的列名$it".padEnd(20, 'x') }
        val rows = listOf(wide) + (1..40).map { r -> wide.map { "$r-$it".padEnd(200, 'y') } }
        val a = AiAttachment("宽表.xlsx", "xlsx", listOf(AiAttachment.Table("S", rows, rowCount = rows.size, colCount = 20, truncated = false)))
        val text = AiAttachment.block(1, 1, a)
        // 至少 10 行（含表头那条是行数统计的一部分）
        val tsvLines = text.substringAfter("```tsv\n").substringBefore("\n```").lines()
        assertTrue("至少保留 10 行，实际 ${tsvLines.size}", tsvLines.size >= AiAttachment.MIN_ROWS)
        // 而且不能突破硬天花板（宽表允许超预算，但不许无上限）
        assertTrue("附件正文不该超过硬天花板，实际 ${text.length}", text.length <= AiAttachment.HARD_MAX_CHARS + 200)
    }
}
