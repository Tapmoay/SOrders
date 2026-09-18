package com.tapmoay.sorders.ai

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test

/**
 * 「按表格建商品」的**表格解析器**测试（[AiProductTable]，纯函数）。
 *
 * ### 为什么这个解析器必须逐条钉住
 * 它是这条链路上**唯一做判断题**的地方：模型只把表格原样搬过来，后面全靠这里读懂。
 * 读错的后果不是报错，而是**建出一批错的商品**（把单价当商品名、把成本当售价、少建几行），
 * 而用户在确认卡上看到的是"30 行"——他不会去数。
 *
 * 所以这里把"真实会被贴出来的形状"和"三条宁可拒绝也不猜"都钉成用例。
 */
class AiProductTableTest {

    private fun parse(text: String) = AiProductTable.parse(text)

    @Test
    fun `Tab 分隔（从 Excel 复制）+ 表头认列`() {
        val r = parse(
            "商品名\t单位\t单价\t库存\n" +
                "红富士苹果\t箱\t45.5\t120\n" +
                "海南香蕉\t件\t3\t0",
        )
        assertEquals(2, r.rows.size)
        assertEquals("红富士苹果", r.rows[0].name)
        assertEquals("45.50", r.rows[0].price!!.toPlainString())
        assertEquals("箱", r.rows[0].unit)
        assertEquals(120, r.rows[0].stock)
        // 没给报警阈值的行 → null（不是 0：0 表示"不报警"，那是用户的决定，不该由我们默认）
        assertNull(r.rows[0].alert)
        assertEquals("3.00", r.rows[1].price!!.toPlainString())
    }

    @Test
    fun `Markdown 表格（带分隔行）也能读`() {
        val r = parse(
            """
            | 品名 | 单价 | 单位 |
            | --- | --- | --- |
            | 皇冠梨 | 6.8 | 斤 |
            | 农夫山泉 | 22 | 件 |
            """.trimIndent(),
        )
        assertEquals(2, r.rows.size)
        assertEquals("皇冠梨", r.rows[0].name)
        assertEquals("6.80", r.rows[0].price!!.toPlainString())
        assertEquals("件", r.rows[1].unit)
    }

    @Test
    fun `表头是常见别名也能认（商品名称 售价 计量单位）`() {
        val r = parse("商品名称,售价,计量单位\n雕牌洗衣粉,12.5,袋")
        assertEquals("雕牌洗衣粉", r.rows[0].name)
        assertEquals("12.50", r.rows[0].price!!.toPlainString())
        assertEquals("袋", r.rows[0].unit)
    }

    @Test
    fun `只有商品名一列也能建（单价按 0）`() {
        val r = parse("商品名\n红富士苹果\n皇冠梨")
        assertEquals(2, r.rows.size)
        assertNull(r.rows[0].price)
    }

    // ------------------------------------------------------------ 三条"宁可拒绝也不猜"

    @Test
    fun `认不出商品名列 → 拒绝，不许猜第一列`() {
        try {
            parse("甲\t乙\t丙\n1\t2\t3")
            fail("应当拒绝")
        } catch (e: AiWriteArgException) {
            assertTrue(e.message!!, e.message!!.contains("商品名"))
        }
    }

    @Test
    fun `一行读不出来 → 带行号拒绝`() {
        try {
            parse("商品名\t单价\n红富士苹果\t45.5\n皇冠梨\t不是数字")
            fail("应当拒绝")
        } catch (e: AiWriteArgException) {
            val m = e.message!!
            assertTrue(m, m.contains("第 3 行"))
            assertTrue(m, m.contains("皇冠梨"))
        }
    }

    @Test
    fun `表里重名 → 拒绝并列出行号`() {
        try {
            parse("商品名\t单价\n红富士苹果\t45.5\n红富士苹果\t50")
            fail("应当拒绝")
        } catch (e: AiWriteArgException) {
            val m = e.message!!
            assertTrue(m, m.contains("红富士苹果"))
            assertTrue(m, m.contains("第 2 行"))
            assertTrue(m, m.contains("第 3 行"))
        }
    }

    @Test
    fun `超过 30 行 → 拒绝并说清上限`() {
        val body = (1..31).joinToString("\n") { "商品$it\t${it}.00" }
        try {
            parse("商品名\t单价\n$body")
            fail("应当拒绝")
        } catch (e: AiWriteArgException) {
            assertTrue(e.message!!, e.message!!.contains("30"))
        }
    }

    // ------------------------------------------------------------ 数值与边界

    @Test
    fun `单价带单位或货币符号也能读`() {
        val r = parse("商品名\t单价\n甲\t￥12.50 元\n乙\t1,200.00")
        assertEquals("12.50", r.rows[0].price!!.toPlainString())
        assertEquals("1200.00", r.rows[1].price!!.toPlainString())
    }

    @Test
    fun `单价是负数 → 拒绝`() {
        try {
            parse("商品名\t单价\n甲\t-5")
            fail("应当拒绝")
        } catch (e: AiWriteArgException) {
            assertTrue(e.message!!, e.message!!.contains("负数"))
        }
    }

    @Test
    fun `单价超过一百万 → 当成多打了零，拒绝`() {
        try {
            parse("商品名\t单价\n甲\t1000001")
            fail("应当拒绝")
        } catch (e: AiWriteArgException) {
            assertTrue(e.message!!, e.message!!.contains("上限"))
        }
    }

    @Test
    fun `库存带 件 也能读，负数拒绝`() {
        val r = parse("商品名\t库存\n甲\t120 件")
        assertEquals(120, r.rows[0].stock)
        try {
            parse("商品名\t库存\n甲\t-1")
            fail("应当拒绝")
        } catch (e: AiWriteArgException) {
            assertTrue(e.message!!, e.message!!.contains("库存"))
        }
    }

    @Test
    fun `商品名过长 → 拒绝（上限与 products create 的 name 一致）`() {
        val long = "果".repeat(AiProductTable.MAX_NAME + 1)
        try {
            parse("商品名\n$long")
            fail("应当拒绝")
        } catch (e: AiWriteArgException) {
            assertTrue(e.message!!, e.message!!.contains("太长"))
        }
    }

    // ------------------------------------------------------------ 不会写进去的列

    @Test
    fun `成本列不写进去，但必须在 notes 里说清楚`() {
        val r = parse("商品名\t单价\t成本价\n红富士苹果\t45.5\t30")
        assertEquals("45.50", r.rows[0].price!!.toPlainString())
        assertTrue(r.notes.toString(), r.notes.any { it.contains("成本") && it.contains("没有写进去") })
    }

    @Test
    fun `空行和全空表格都有明确说法`() {
        try {
            parse("   \n\n")
            fail("应当拒绝")
        } catch (e: AiWriteArgException) {
            assertTrue(e.message!!, e.message!!.contains("一行内容都没读到"))
        }
        try {
            parse("商品名\t单价")
            fail("应当拒绝")
        } catch (e: AiWriteArgException) {
            assertTrue(e.message!!, e.message!!.contains("表头"))
        }
    }

    @Test
    fun `行号是用户看到的原文行号（空行也算一行）`() {
        val r = parse("商品名\n\n红富士苹果\n\n皇冠梨")
        assertEquals(2, r.rows.size)
        // 空行占掉了第 2、4 行 → 两条数据分别是第 3、5 行
        assertEquals(3, r.rows[0].lineNo)
        assertEquals(5, r.rows[1].lineNo)
    }
}
