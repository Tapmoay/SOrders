package com.tapmoay.sorders.ai

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 「贴一张表格批量调价」的**表格解析器**测试（[AiPriceTable]，纯函数）。
 *
 * ### 为什么解析器要单独一个测试文件
 * 它是这条链路上**唯一由 App 做判断题**的地方：模型只负责把表格**原样**贴进来，
 * 后面全靠这里读懂。读错的后果是**价格被改错**，而且改错了不会报错——
 * 卡片上那串 before→after 是最后一道防线，如果解析器把列认错了，连那道防线也是错的。
 *
 * 所以这里把"真实会被贴出来的形状"尽量摆全：
 * Excel 的 Tab、Markdown 的竖线、CSV 的逗号、中文逗号、多个空格、带表头、不带表头。
 */
class AiPriceTableTest {

    private val products = listOf(
        AiName(41, "红富士苹果"),
        AiName(42, "皇冠梨"),
        AiName(43, "SOTEST雕牌洗衣粉"),
    )
    private val members = listOf(
        AiName(31, "城东水果批发"),
        AiName(32, "明辉食品行"),
    )

    private fun parse(text: String, mode: AiPriceTable.Mode? = null) =
        AiPriceTable.parse(text, products, members, mode)

    // ------------------------------------------------------------ 分隔符

    @Test
    fun `Tab 分隔（从 Excel 复制）`() {
        val rows = parse("红富士苹果\t城东水果批发\t-10%")
        assertEquals(1, rows.size)
        assertEquals(41L, rows[0].product.id)
        assertEquals(31L, rows[0].shipper?.id)
        assertEquals(AiPriceTable.Mode.ADJUST, rows[0].mode)
        assertEquals("-10.00", rows[0].value.toPlainString())
    }

    @Test
    fun `Markdown 表格（带分隔行）也能读`() {
        val rows = parse(
            """
            | 商品 | 批发商 | 幅度 |
            | --- | --- | --- |
            | 红富士苹果 | 城东水果批发 | -10% |
            | 皇冠梨 | 明辉食品行 | 5% |
            """.trimIndent(),
        )
        assertEquals(2, rows.size)
        assertEquals("红富士苹果", rows[0].product.label)
        assertEquals("明辉食品行", rows[1].shipper?.label)
        assertEquals("5.00", rows[1].value.toPlainString())
    }

    @Test
    fun `逗号与中文逗号都能读`() {
        assertEquals(1, parse("红富士苹果,城东水果批发,-10").size)
        assertEquals(1, parse("红富士苹果，城东水果批发，-10").size)
    }

    @Test
    fun `两个以上空格当分隔符`() {
        val rows = parse("红富士苹果   城东水果批发   -10%")
        assertEquals(1, rows.size)
        assertEquals(31L, rows[0].shipper?.id)
    }

    // ------------------------------------------------------------ 列的角色

    @Test
    fun `没有表头时按内容认列（商品列在后、批发商列在前）`() {
        val rows = parse("城东水果批发\t红富士苹果\t-10%")
        assertEquals("红富士苹果", rows[0].product.label)
        assertEquals("城东水果批发", rows[0].shipper?.label)
    }

    @Test
    fun `两列（商品 + 幅度）= 全部批发商`() {
        val rows = parse("红富士苹果\t-10%")
        assertEquals(1, rows.size)
        assertEquals(null, rows[0].shipper)
    }

    @Test
    fun `写「全部」的行走 null（= 全部批发商）`() {
        val rows = parse("红富士苹果\t全部\t-10%")
        assertEquals(null, rows[0].shipper)
        assertEquals(1, parse("红富士苹果\t所有批发商\t-3%").let { it }.size)
    }

    // ------------------------------------------------------------ 取值

    @Test
    fun `幅度的各种写法`() {
        fun v(s: String) = parse("红富士苹果\t城东水果批发\t$s")[0].value.toPlainString()
        assertEquals("-10.00", v("-10%"))
        assertEquals("-10.00", v("降10%"))
        assertEquals("-10.00", v("-10％"))       // 全角百分号
        assertEquals("10.00", v("涨10"))
        assertEquals("10.00", v("+10%"))
        assertEquals("-7.50", v("下调7.5%"))
    }

    @Test
    fun `表头写「新价」时，光数字按绝对价格读`() {
        val rows = parse(
            """
            商品	批发商	新价
            红富士苹果	城东水果批发	4.05
            """.trimIndent(),
        )
        assertEquals(AiPriceTable.Mode.FIXED, rows[0].mode)
        assertEquals("4.05", rows[0].value.toPlainString())
    }

    @Test
    fun `格子带「元」时也按绝对价格读`() {
        val rows = parse("红富士苹果\t城东水果批发\t4.05元")
        assertEquals(AiPriceTable.Mode.FIXED, rows[0].mode)
    }

    @Test
    fun `既没表头也没单位的裸数字按百分比读（用户要的三种用法都是百分比）`() {
        val rows = parse("红富士苹果\t城东水果批发\t10")
        assertEquals(AiPriceTable.Mode.ADJUST, rows[0].mode)
    }

    @Test
    fun `外面明确说了是绝对价（mode=fixed）就按新价读`() {
        val rows = parse("红富士苹果\t城东水果批发\t4.05", AiPriceTable.Mode.FIXED)
        assertEquals(AiPriceTable.Mode.FIXED, rows[0].mode)
        assertEquals("4.05", rows[0].value.toPlainString())
    }

    // ------------------------------------------------------------ 拒绝（读不出来就不发卡）

    @Test
    fun `商品名对不上时报出第几行和那一行原文`() {
        val e = runCatching { parse("红富士苹果\t城东水果批发\t-10%\n水蜜桃\t明辉食品行\t-5%") }.exceptionOrNull()
        assertTrue("应当抛 AiWriteArgException，实际 $e", e is AiWriteArgException)
        assertTrue(e!!.message!!.contains("第 2 行"))
        assertTrue(e.message!!.contains("水蜜桃"))
    }

    @Test
    fun `批发商对不上时也拒绝（不许悄悄改成全部）`() {
        val e = runCatching { parse("红富士苹果\t不存在的店\t-10%") }.exceptionOrNull()
        assertTrue(e is AiWriteArgException)
        assertTrue(e!!.message!!.contains("批发商"))
    }

    @Test
    fun `数字看不清时拒绝`() {
        val e = runCatching { parse("红富士苹果\t城东水果批发\t降一点") }.exceptionOrNull()
        assertTrue(e is AiWriteArgException)
        assertTrue(e!!.message!!.contains("不是数字"))
    }

    @Test
    fun `涨跌幅超过 -100% 拒绝（降超过 100% 是没有意义的）`() {
        val e = runCatching { parse("红富士苹果\t城东水果批发\t-150%") }.exceptionOrNull()
        assertTrue(e is AiWriteArgException)
        assertTrue(e!!.message!!.contains("超出允许范围"))
    }

    @Test
    fun `幅度是 0 拒绝（改了等于没改，多半是漏填）`() {
        val e = runCatching { parse("红富士苹果\t城东水果批发\t0%") }.exceptionOrNull()
        assertTrue(e is AiWriteArgException)
    }

    @Test
    fun `只有一格的行读不出来（要商品+调整值两列）`() {
        val e = runCatching { parse("红富士苹果") }.exceptionOrNull()
        assertTrue(e is AiWriteArgException)
    }

    @Test
    fun `空表格拒绝`() {
        val e = runCatching { parse("   \n\n  ") }.exceptionOrNull()
        assertTrue(e is AiWriteArgException)
    }

    @Test
    fun `超过上限的行数拒绝并让人分批`() {
        val lines = (1..(AiPriceTable.MAX_ROWS + 5)).joinToString("\n") { "红富士苹果\t城东水果批发\t-1%" }
        val e = runCatching { parse(lines) }.exceptionOrNull()
        assertTrue(e is AiWriteArgException)
        assertTrue(e!!.message!!.contains("分批"))
    }

    @Test
    fun `刚好等于上限可以过`() {
        val lines = (1..AiPriceTable.MAX_ROWS).joinToString("\n") { "红富士苹果\t城东水果批发\t-1%" }
        assertEquals(AiPriceTable.MAX_ROWS, parse(lines).size)
    }

    @Test
    fun `商品库里一个商品都没有时拒绝`() {
        val e = runCatching { AiPriceTable.parse("红富士苹果\t-10%", emptyList(), members) }.exceptionOrNull()
        assertTrue(e is AiWriteArgException)
    }
}
