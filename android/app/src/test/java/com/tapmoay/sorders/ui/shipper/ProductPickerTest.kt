package com.tapmoay.sorders.ui.shipper

import com.tapmoay.sorders.data.remote.dto.ProductDto
import com.tapmoay.sorders.ui.common.PickedLine
import com.tapmoay.sorders.ui.common.categoryTabs
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Test

/**
 * 外卖式选品页的**纯逻辑**：分类分组 + 一次挑多件怎么并入清单。
 *
 * ⚠️ 这里调的都是**产品代码里那个函数本身**（`categoryTabs` / `mergePickedIntoLines`），
 * 不是测试里再抄一份规则 —— 抄一份的后果是"测试全绿、产品坏了"，
 * 本仓库栽过这个跟头（见 `_tools/ai/_reverse_verify_all.py` 的由来）。
 */
class ProductPickerTest {

    private fun p(id: Long, name: String, category: String = "", unit: String = "件") =
        ProductDto(id = id, name = name, category = category, unit = unit)

    private fun picked(id: Long, qty: Int = 1, unit: String = "件") =
        PickedLine(productId = id, name = "商品$id", qty = qty, unit = unit, price = "10")

    // ---------------- 分类分组 ----------------

    @Test
    fun `全部商品都没分类时只剩全部一个分类`() {
        val tabs = categoryTabs(listOf(p(1, "A"), p(2, "B"), p(3, "C")))
        // 关键：不能出现「未分类」这一格 —— 全是未分类时它没有信息量，
        // 而且会让用户以为"必须先分类才能下单"
        assertEquals(listOf("全部"), tabs)
    }

    @Test
    fun `分类按商品数倒序`() {
        val tabs = categoryTabs(
            listOf(
                p(1, "A", "粮油"),
                p(2, "B", "饮料"),
                p(3, "C", "饮料"),
                p(4, "D", "饮料"),
                p(5, "E", "日化"),
                p(6, "F", "日化"),
            ),
        )
        assertEquals(listOf("全部", "饮料", "日化", "粮油"), tabs)
    }

    @Test
    fun `未分类永远排最后`() {
        val tabs = categoryTabs(
            listOf(
                p(1, "A"),            // 未分类
                p(2, "B"),            // 未分类
                p(3, "C"),            // 未分类
                p(4, "D", "饮料"),
            ),
        )
        // 未分类有 3 件、饮料只有 1 件，但「未分类」是兜底档，不许抢在正经分类前面
        assertEquals(listOf("全部", "饮料", "未分类"), tabs)
    }

    @Test
    fun `纯空格的分类算未分类`() {
        val tabs = categoryTabs(listOf(p(1, "A", "   "), p(2, "B", "饮料")))
        assertEquals(listOf("全部", "饮料", "未分类"), tabs)
    }

    @Test
    fun `分类前后空格不会分成两格`() {
        val tabs = categoryTabs(listOf(p(1, "A", "饮料"), p(2, "B", " 饮料 ")))
        assertEquals(listOf("全部", "饮料"), tabs)
    }

    @Test
    fun `分类清单里一定有全部`() {
        assertEquals(listOf("全部"), categoryTabs(emptyList()))
    }

    // ---------------- 名册顺序（v3.43：顺序由派单员定，不再按商品数推）----------------

    @Test
    fun `有名册时按名册顺序排，不按商品数`() {
        val products = listOf(
            p(1, "A", "粮油"), p(2, "B", "饮料"), p(3, "C", "饮料"), p(4, "D", "饮料"),
        )
        // 名册把"粮油"排在"饮料"前面（商品数 1 < 3）—— 顺序必须听名册的
        val tabs = categoryTabs(products, listOf("粮油", "饮料"))
        assertEquals(listOf("全部", "粮油", "饮料"), tabs)
    }

    @Test
    fun `名册里没有商品的分类不出现（空页签是噪音）`() {
        val products = listOf(p(1, "A", "饮料"))
        val tabs = categoryTabs(products, listOf("粮油", "饮料", "日化"))
        assertEquals(listOf("全部", "饮料"), tabs)
    }

    @Test
    fun `名册外的分类排在名册后面（不许因为不在名册里就藏起来）`() {
        val products = listOf(p(1, "A", "野分类"), p(2, "B", "饮料"), p(3, "C", "野分类"))
        val tabs = categoryTabs(products, listOf("饮料"))
        // 关键：**野分类必须在**，只是排在名册之后
        assertEquals(listOf("全部", "饮料", "野分类"), tabs)
    }

    @Test
    fun `名册里的重复项与空白项不会多出格子`() {
        val products = listOf(p(1, "A", "饮料"))
        val tabs = categoryTabs(products, listOf("饮料", " 饮料 ", "", "   "))
        assertEquals(listOf("全部", "饮料"), tabs)
    }

    @Test
    fun `名册为空时退回按商品数倒序`() {
        val products = listOf(p(1, "A", "粮油"), p(2, "B", "饮料"), p(3, "C", "饮料"))
        assertEquals(listOf("全部", "饮料", "粮油"), categoryTabs(products, emptyList()))
    }

    // ---------------- 一次挑多件 ----------------

    @Test
    fun `同一件商品重复挑是累加数量而不是多一行`() {
        val merged = mergePickedIntoLines(emptyList(), listOf(picked(1, 2)))!!
        val again = mergePickedIntoLines(merged, listOf(picked(1, 3)))!!
        assertEquals(1, again.size)
        assertEquals(5, again[0].quantity)
    }

    @Test
    fun `不同商品各占一行且顺序保持`() {
        val merged = mergePickedIntoLines(emptyList(), listOf(picked(7), picked(3), picked(5)))!!
        assertEquals(listOf(7L, 3L, 5L), merged.map { it.productId })
    }

    @Test
    fun `加满 10 行后再挑新商品就整批拒绝`() {
        val ten = (1L..10L).map { LineDraft(productId = it, name = "商品$it") }
        // 不做部分成功：11、12 两件一件都不许悄悄进去
        assertNull(mergePickedIntoLines(ten, listOf(picked(11), picked(12))))
    }

    @Test
    fun `同一件商品即使清单已满也只累加不占新行`() {
        val ten = (1L..10L).map { LineDraft(productId = it, name = "商品$it") }
        val merged = mergePickedIntoLines(ten, listOf(picked(1, 2)))
        assertNotNull("已在清单里的商品只加数量，不该被 10 行上限挡掉", merged)
        assertEquals(10, merged!!.size)
        assertEquals(3, merged[0].quantity)
    }

    @Test
    fun `正好加到 10 行允许`() {
        val nine = (1L..9L).map { LineDraft(productId = it, name = "商品$it") }
        assertEquals(10, mergePickedIntoLines(nine, listOf(picked(10)))!!.size)
    }

    @Test
    fun `数量与单位一起落到行上`() {
        val merged = mergePickedIntoLines(emptyList(), listOf(picked(1, 3, "箱")))!!
        assertEquals(3, merged[0].quantity)
        assertEquals("箱", merged[0].unit)
    }

    @Test
    fun `手输的自定义行不会被同名商品顶掉`() {
        // productId 为 null = 手输的自定义商品行；选品页挑的正规商品不该和它合并
        val custom = listOf(LineDraft(productId = null, name = "临时货", quantity = 1, price = "5"))
        val merged = mergePickedIntoLines(custom, listOf(picked(1, 2)))!!
        assertEquals(2, merged.size)
    }
}
