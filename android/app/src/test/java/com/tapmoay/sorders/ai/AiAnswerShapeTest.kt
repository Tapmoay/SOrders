package com.tapmoay.sorders.ai

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 呈现兜底：助手答复里连续的「标签：值」散行补成两列小表（[AiAnswerShape]）。
 *
 * ### 用户原话（2026-10-09，ref m35395）
 * 「AI 的回答最好都要用表格的样式…上面有文字下面有信息混在一起就很难分辨出来，
 * 他具体想表达的核心内容是什么。」
 *
 * ### 守的是什么
 * 1. **该成表的成表** —— 截图那条（三个字段）必须变成一张无表头两列表；两行就该成表。
 * 2. **不该成表的别乱动** —— 单独一行、值是一整句话、值太长、标题、编号步骤、模型自己
 *    写好的 Markdown 表，一律原样。兜底的错法不是"漏"，是**把叙述拆成标签**（用户会照着错的标签核对数字），
 *    所以每条规则都要有反例。
 */
class AiAnswerShapeTest {

    private fun shape(text: String): List<AiMarkdown.Block> = AiAnswerShape.apply(AiMarkdown.parse(text))

    @Test
    fun `截图那条：三个字段的散行补成一张无表头两列表`() {
        val text = listOf(
            "确认卡发给你了，点一下「确认」就写好：",
            "- 收货人：张三",
            "- 电话：13900002222",
            "- 终点地址：幸福路 18 号",
            "「城东水果批发」我没往这张卡里放——它是这条线路的起点，还是写进备注？",
        ).joinToString("\n")
        val blocks = shape(text)
        assertEquals("首句 / 表 / 追问 —— 正好三块：\n$blocks", 3, blocks.size)
        assertTrue("首句还是普通一行：\n$blocks", blocks[0] is AiMarkdown.Block.Line)
        val table = blocks[1] as AiMarkdown.Block.Table
        assertTrue("无表头 —— 第一列就是标签，不该硬编一个表头：\n$table", table.header.isEmpty())
        assertEquals(
            listOf(
                listOf("收货人", "张三"),
                listOf("电话", "13900002222"),
                listOf("终点地址", "幸福路 18 号"),
            ),
            table.body,
        )
        assertTrue("追问要留在表格外面（单独一行）：\n$blocks", blocks[2] is AiMarkdown.Block.Line)
    }

    @Test
    fun `两行就成表（下限是 2，用户口径：只要有同类信息就该排开）`() {
        assertEquals(2, AiAnswerShape.MIN_ROWS)
        val blocks = shape("订单号：SO202610080000000001\n状态：已送达")
        assertEquals(1, blocks.size)
        assertEquals(
            listOf(listOf("订单号", "SO202610080000000001"), listOf("状态", "已送达")),
            (blocks[0] as AiMarkdown.Block.Table).body,
        )
    }

    @Test
    fun `单独一行不成表（一行就是一行，多画一层框反而重）`() {
        val blocks = shape("订单号：SO202610080000000001")
        assertEquals(1, blocks.size)
        assertTrue("单行必须原样留着：\n$blocks", blocks[0] is AiMarkdown.Block.Line)
    }

    @Test
    fun `值是一整句话就不成表（那是叙述，不是标签：值）`() {
        val text = listOf(
            "备注：这一单要先跟司机确认能不能在早上八点之前到，不能的话就改到下午。",
            "原因：客户临时改了时间",
        ).joinToString("\n")
        val blocks = shape(text)
        assertEquals("两行都不该进表：\n$blocks", 2, blocks.size)
        assertTrue(blocks.all { it is AiMarkdown.Block.Line })
    }

    @Test
    fun `值太长不成表（超过 24 显示宽度，汉字算 2）`() {
        assertEquals(24, AiAnswerShape.MAX_VALUE_WIDTH)
        val text = listOf(
            "商品名称：阿克苏冰糖心苹果特级果 10 斤装礼盒",
            "单价：58.00 元",
        ).joinToString("\n")
        val blocks = shape(text)
        assertEquals("长值那行留在正文里，剩下单独一行也不成表：\n$blocks", 2, blocks.size)
        assertTrue(blocks.all { it is AiMarkdown.Block.Line })
    }

    @Test
    fun `标题与编号步骤不被吸进表（它们已经排过了）`() {
        val text = listOf(
            "## 本次对账",
            "1. 打开账本页",
            "2. 核对金额",
            "收货人：张三",
            "电话：13900002222",
        ).joinToString("\n")
        val blocks = shape(text)
        assertEquals(4, blocks.size)
        assertEquals(AiMarkdown.Block.Kind.HEADING, (blocks[0] as AiMarkdown.Block.Line).kind)
        assertEquals(AiMarkdown.Block.Kind.NUMBERED, (blocks[1] as AiMarkdown.Block.Line).kind)
        assertEquals(AiMarkdown.Block.Kind.NUMBERED, (blocks[2] as AiMarkdown.Block.Line).kind)
        assertEquals(
            listOf(listOf("收货人", "张三"), listOf("电话", "13900002222")),
            (blocks[3] as AiMarkdown.Block.Table).body,
        )
    }

    @Test
    fun `模型自己写好的 Markdown 表原样不动`() {
        val text = listOf(
            "| 商品 | 金额 |",
            "| --- | --- |",
            "| 苹果 | 12.00 |",
            "| 梨 | 8.00 |",
        ).joinToString("\n")
        val parsed = AiMarkdown.parse(text)
        assertTrue("前提：这段本来就能解析成表：\n$parsed", parsed.any { it is AiMarkdown.Block.Table })
        assertEquals("兜底不该再动它：\n$parsed", parsed, AiAnswerShape.apply(parsed))
    }

    @Test
    fun `中间隔一句叙述就分成两张表（只吸连续的那一段）`() {
        val text = listOf(
            "收货人：张三",
            "电话：13900002222",
            "以上是收货信息。",
            "商品：苹果",
            "数量：3 箱",
        ).joinToString("\n")
        val blocks = shape(text)
        assertEquals(3, blocks.size)
        assertEquals(2, (blocks[0] as AiMarkdown.Block.Table).body.size)
        assertTrue(blocks[1] is AiMarkdown.Block.Line)
        assertEquals(2, (blocks[2] as AiMarkdown.Block.Table).body.size)
    }

    @Test
    fun `加粗的标签照样成表（按纯文本拼接，不是拿原始 Markdown 去切）`() {
        val blocks = shape("- **收货人**：张三\n- **电话**：13900002222")
        assertEquals(1, blocks.size)
        assertEquals(
            listOf(listOf("收货人", "张三"), listOf("电话", "13900002222")),
            (blocks[0] as AiMarkdown.Block.Table).body,
        )
    }

    @Test
    fun `没有冒号的行原样留着`() {
        val blocks = shape("这单已送达\n路上注意安全")
        assertEquals(2, blocks.size)
        assertTrue(blocks.all { it is AiMarkdown.Block.Line })
    }
}
