package com.tapmoay.sorders.ai

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.math.BigDecimal

/**
 * 「这件货对**这个货主**是多少钱」的测试（[AiPriceBasis]，纯函数）。
 *
 * ### 为什么这一份必须有单测
 * 它是 AI 那条路上**唯一**决定报价的地方，而后端**不重算价**
 * （`order_products.py` 直接收 `body.unit_price`）—— 也就是说这里算错，
 * 库里就真的按错的价记，谁都不会报错。用户 2026-09-22 复查新功能时问的
 * 正是这件事（「AI 在核心业务工作上有出现错误吗」），而那天的答案里就有这个 bug：
 * 批发商谈好 10 元、AI 建出来的单按 20 元（走的是商品库默认价）。
 *
 * 所以下面每一条都是"钱算错与否"的分界，不是走个形式：
 * 专属价优先 / 认不出人时不串号 / 没有价时**返回 null 而不是 0**（0 = 白送）。
 */
class AiPriceBasisTest {

    private val apple = 41L
    private val pear = 42L
    private val cityEast = 31L      // 城东水果批发（批发商）
    private val minghui = 32L       // 明辉食品行（批发商）

    /** 城东：苹果谈成 10 元；明辉：苹果谈成 9 元（**同一件货、两个价**，专门用来查串号）。 */
    private fun basis() = AiPriceBasis(
        special = mapOf(
            (cityEast to apple) to BigDecimal("10.00"),
            (minghui to apple) to BigDecimal("9.00"),
        ),
        defaults = mapOf(
            apple to BigDecimal("20.00"),
            pear to BigDecimal("7.50"),
        ),
    )

    // ---------------------------------------------------------------- 生效价

    @Test
    fun `有专属价就用专属价 —— 不是商品库那个默认价`() {
        val p = basis().of(cityEast, apple)!!
        assertEquals(BigDecimal("10.00"), p.value)
        assertTrue("必须标成「专属价」，卡片上要写出来", p.fromSpecial)
        assertEquals("这个货主的专属价", p.basisCn)
    }

    @Test
    fun `同一件货、两个货主各是各的价（不串号）`() {
        val b = basis()
        assertEquals(BigDecimal("10.00"), b.of(cityEast, apple)!!.value)
        assertEquals(BigDecimal("9.00"), b.of(minghui, apple)!!.value)
    }

    @Test
    fun `没有专属价才回退商品库的默认价`() {
        val p = basis().of(cityEast, pear)!!
        assertEquals(BigDecimal("7.50"), p.value)
        assertTrue("要标成「默认价」——用户才知道这是没谈过的价", !p.fromSpecial)
        assertEquals("商品库的默认价", p.basisCn)
    }

    @Test
    fun `认不出货主（临时货主）时只走默认价，绝不拿别人的专属价顶上`() {
        val p = basis().of(null, apple)!!
        assertEquals(BigDecimal("20.00"), p.value)
        assertTrue(!p.fromSpecial)
    }

    @Test
    fun `两边都没有这个价 → 返回 null（＝不知道价），绝不返回 0`() {
        assertNull(basis().of(cityEast, 999L))
        assertNull(basis().of(null, 999L))
    }

    // ---------------------------------------------------------------- 后端给的字符串

    @Test
    fun `读不出来的价当作「没有这个价」，不是 0`() {
        // 0 会被当成"这件货不要钱" —— 那个后果比"不知道价"严重得多
        assertNull(AiPriceBasis.moneyOf(""))
        assertNull(AiPriceBasis.moneyOf("   "))
        assertNull(AiPriceBasis.moneyOf("—"))
        assertNull(AiPriceBasis.moneyOf("abc"))
    }

    @Test
    fun `后端给的四位小数归到两位（这才是能进请求体的形状）`() {
        assertEquals(BigDecimal("10.00"), AiPriceBasis.moneyOf("10.0000"))
        assertEquals(BigDecimal("7.50"), AiPriceBasis.moneyOf("7.50"))
    }

    // ---------------------------------------------------------------- 卡片口径

    @Test
    fun `卡片上那个价是显示口径（去尾零），不是后端那种四位小数`() {
        // ⛔ 值（进 payload 的两位小数）不在这里：它由 `of()` 出来的 `value` 直接给
        //    （`AiWriteArgs.money` 是那一份唯一实现，不在这条路上再抄一遍）。
        assertEquals("56.7", AiPriceBasis.Price(BigDecimal("56.70"), fromSpecial = false).display)
        assertEquals("87", AiPriceBasis.Price(BigDecimal("87.00"), fromSpecial = true).display)
        assertEquals("56.77", AiPriceBasis.Price(BigDecimal("56.77"), fromSpecial = false).display)
    }

    // ---------------------------------------------------------------- 与系统价不一致

    @Test
    fun `价一致时什么都不说（形状不同也算一致：10 与 10_00）`() {
        val b = basis()
        assertNull(b.mismatchNote(BigDecimal("10.00"), b.of(cityEast, apple)))
        assertNull(b.mismatchNote(BigDecimal("10"), b.of(cityEast, apple)))
    }

    @Test
    fun `价不一致时两个数都摆出来，并让模型回去核对`() {
        val b = basis()
        val note = b.mismatchNote(BigDecimal("20.00"), b.of(cityEast, apple))!!
        assertTrue("要写出**系统价**：$note", note.contains("10"))
        assertTrue("要写出**卡片上按多少算**：$note", note.contains("20"))
        assertTrue("要说清这个价是哪一种：$note", note.contains("专属价"))
        assertTrue("要让它去问用户，而不是默默建单：$note", note.contains("先跟用户核对"))
    }

    /**
     * ⚠️ 这句话**有长度预算**，超了就会被切掉半行（2026-09-22 真机截图抓到的）。
     *
     * 卡片明细区是 `heightIn(max = 200.dp)` + 内部滚动（`AiChatScreen` 里那个 `CardInfoTable`
     * 调用点），而建单卡本来就有 5 行（货主/日期/商品明细/货/合计）。第一版这句话 3 行、
     * 整块顶到 ~210dp，于是**最后一行被裁掉一半**（用户只会觉得"卡片坏了"，而内容其实只是需要滚一下）。
     */
    @Test
    fun `这句话不许长到被明细区裁掉（两行以内）`() {
        val note = basis().mismatchNote(BigDecimal("20.00"), basis().of(cityEast, apple))!!
        assertTrue("实际 ${note.length} 字：$note", note.length <= 52)
    }

    @Test
    fun `系统价未知时不乱提示（不知道就不说话）`() {
        assertNull(basis().mismatchNote(BigDecimal("20.00"), null))
    }
}
