package com.tapmoay.sorders.ui.shipper

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotSame
import org.junit.Assert.assertSame
import org.junit.Test

/**
 * 下单清单**按"这个货主的价"重算**的纯逻辑（`repriceLines`）。
 *
 * 这一条是 2026-09-22 用户报的错价修出来的：海南香蕉默认价 20，给批发商谈好 10，
 * 用「预订单」下单还是 20 —— 因为在"专属价还在路上"的那一刻就把行价算定了，
 * 而**已经填好的行不会**因为专属价随后到达而重新算。
 *
 * ⚠️ 这里调的是**产品代码里那个函数本身**（`repriceLines`），不是测试里再抄一份规则。
 */
class RepriceLinesTest {

    private fun line(
        id: Long? = 1L,
        name: String = "海南香蕉",
        qty: Int = 2,
        price: String = "20",
        unit: String = "箱",
    ) = LineDraft(productId = id, name = name, quantity = qty, price = price, unit = unit)

    @Test
    fun `批发商的专属价会替换掉行上的默认价`() {
        val (out, changed) = repriceLines(listOf(line(price = "20"))) { "10" }
        assertEquals(1, changed)
        assertEquals("10", out[0].price)
        // 钱以外的字段一个都不许动（数量改了就是另一笔生意）
        assertEquals("海南香蕉", out[0].name)
        assertEquals(2, out[0].quantity)
        assertEquals("箱", out[0].unit)
    }

    @Test
    fun `价没变时一行都不算改动（幂等，不白动列表）`() {
        val src = listOf(line(price = "10"))
        val (out, changed) = repriceLines(src) { "10" }
        assertEquals(0, changed)
        // 同一个实例原样返回：调用方据此判断"要不要写回状态"，写回会白白触发一次重组
        assertSame(src[0], out[0])
    }

    @Test
    fun `商品已不在商品库时保留原样，不猜一个价`() {
        // priceOf 返回 null = 这件商品已经不在商品库（预设单里那件货后来被删/下架了）。
        // 这时**不许**拿默认价顶上 —— 我们连它的价都查不到，行价留空并由界面如实说出来
        // （提交时那一行会被挡下，用户只能删掉它或让派单员把商品恢复）。
        val src = listOf(line(price = ""))
        val (out, changed) = repriceLines(src) { null }
        assertEquals(0, changed)
        assertEquals("", out[0].price)
    }

    @Test
    fun `没有商品编号的行不碰（手输的自定义行没有价可算）`() {
        val src = listOf(line(id = null, price = ""))
        val (out, changed) = repriceLines(src) { error("不该问一个没有编号的行要价") }
        assertEquals(0, changed)
        assertEquals("", out[0].price)
    }

    @Test
    fun `多行里只改该改的那几行`() {
        val src = listOf(
            line(id = 1L, name = "海南香蕉", price = "20"),   // 有专属价 → 改
            line(id = 2L, name = "红富士苹果", price = "8"),   // 没有专属价 → 保持默认价
            line(id = 3L, name = "已下架商品", price = ""),    // 查不到 → 保持空
            line(id = 4L, name = "土豆", price = "3.5"),      // 有专属价 → 改
        )
        val prices = mapOf(1L to "10", 2L to "8", 4L to "3.2")
        val (out, changed) = repriceLines(src) { prices[it] }
        assertEquals(2, changed)
        assertEquals(listOf("10", "8", "", "3.2"), out.map { it.price })
    }

    @Test
    fun `返回的是新列表，不改调用方传进来的那一份`() {
        val src = listOf(line(price = "20"))
        val (out, _) = repriceLines(src) { "10" }
        assertNotSame(src, out)
        assertEquals("20", src[0].price)   // 原列表一个字节都没动
    }
}
