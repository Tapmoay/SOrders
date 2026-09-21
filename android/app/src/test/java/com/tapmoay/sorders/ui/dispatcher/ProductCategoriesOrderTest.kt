package com.tapmoay.sorders.ui.dispatcher

import com.tapmoay.sorders.data.remote.dto.ProductCategoryDto
import com.tapmoay.sorders.ui.common.moveItemTo
import org.junit.Assert.assertEquals
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 分类排序的两段纯逻辑：`moveItemTo`（四个名册页的数字排序 / 上下移 / 拖动共用）与
 * `dragSteps`（拖动位移 → 格数）。
 *
 * ## 为什么这两条必须单测
 * 它们是**"差一格"就直接改错用户数据**的地方：填 3 排到第 2 位、或拖动时挪多一格，
 * 界面上都只是"顺序不太对"，而下单页左侧的分组顺序就是店家给客户看的顺序。
 * 模拟器上点很容易看成"差不多对"，所以抽成纯函数在这里钉住。
 *
 * ⚠️ `moveItemTo` 原来住在 `ProductCategoriesViewModel.kt` 里（还带着一个商品专用的包装
 * `moveCategoryTo`）；2026-09-21 精简轮把它搬到 `ui/common/CategoryRoster.kt`（四个页面
 * 都用它，共用规则不该寄生在某一页），包装随之删除 —— 本文件现在直接测泛化版。
 */
class ProductCategoriesOrderTest {

    private fun cat(id: Long, name: String = "分类$id", count: Int = 0) =
        ProductCategoryDto(id = id, name = name, productCount = count)

    private fun ids(list: List<ProductCategoryDto>) = list.map { it.id }

    private val five = listOf(cat(1), cat(2), cat(3), cat(4), cat(5))

    @Test
    fun `填几就排到第几（1-based）`() {
        assertEquals(listOf(1L, 3L, 4L, 2L, 5L), ids(moveItemTo(five, { it.id }, id = 2, position = 4)))
        assertEquals(listOf(1L, 4L, 2L, 3L, 5L), ids(moveItemTo(five, { it.id }, id = 4, position = 2)))
        assertEquals(listOf(2L, 1L, 3L, 4L, 5L), ids(moveItemTo(five, { it.id }, id = 2, position = 1)))
        assertEquals(listOf(1L, 3L, 4L, 5L, 2L), ids(moveItemTo(five, { it.id }, id = 2, position = 5)))
    }

    @Test
    fun `填 0 或超过总数会被夹到两端（不报错、也不丢行）`() {
        assertEquals(listOf(3L, 1L, 2L, 4L, 5L), ids(moveItemTo(five, { it.id }, id = 3, position = 0)))
        assertEquals(listOf(3L, 1L, 2L, 4L, 5L), ids(moveItemTo(five, { it.id }, id = 3, position = -7)))
        assertEquals(listOf(1L, 2L, 4L, 5L, 3L), ids(moveItemTo(five, { it.id }, id = 3, position = 99)))
        // 夹完之后仍然是这 5 个，一个不多一个不少
        assertEquals(
            five.map { it.id }.toSet(),
            moveItemTo(five, { it.id }, id = 3, position = 99).map { it.id }.toSet(),
        )
    }

    @Test
    fun `挪到原位时原样返回同一个列表实例`() {
        // ViewModel 靠 `===` 判断"没变就别写状态"，这条契约不能破：
        // 破了的话，点一下"上移"而它已经在第一位，`dirty` 也会亮起来（用户看到「未保存」）
        assertSame(five, moveItemTo(five, { it.id }, id = 3, position = 3))
        // 已经夹到两端之后也一样（第 1 位填 0、最后一位填 99）
        assertSame(five, moveItemTo(five, { it.id }, id = 1, position = 0))
        assertSame(five, moveItemTo(five, { it.id }, id = 5, position = 99))
    }

    @Test
    fun `找不到的 id 与不足两行时不改任何东西`() {
        assertSame(five, moveItemTo(five, { it.id }, id = 999, position = 2))
        val one = listOf(cat(1))
        assertSame(one, moveItemTo(one, { it.id }, id = 1, position = 3))
        val empty = emptyList<ProductCategoryDto>()
        assertSame(empty, moveItemTo(empty, { it.id }, id = 1, position = 1))
    }

    /**
     * 「同一条」由 `idOf` 决定，与字段叫什么、是什么类型无关 —— 这正是它能被四个名册页
     * 共用一份的原因（商品/开销/运费/地点的 DTO 各有各的字段名）。
     */
    @Test
    fun `按哪个字段认同一条由 idOf 决定`() {
        data class Row(val code: Long, val title: String)
        val rows = listOf(Row(7, "甲"), Row(8, "乙"), Row(9, "丙"))
        assertEquals(listOf(8L, 9L, 7L), moveItemTo(rows, { it.code }, id = 7, position = 3).map { it.code })
    }

    @Test
    fun `拖动位移不足半行不动、超过半行挪一格`() {
        val row = 100f
        assertEquals(0, dragSteps(0f, row))
        assertEquals(0, dragSteps(49f, row))
        assertEquals(0, dragSteps(-49f, row))
        assertEquals(1, dragSteps(50f, row))   // 正好半行：翻过去（手指划一半就该换位）
        assertEquals(1, dragSteps(149f, row))
        assertEquals(2, dragSteps(150f, row))
        assertEquals(-1, dragSteps(-50f, row))
        assertEquals(-3, dragSteps(-260f, row))
    }

    @Test
    fun `上下对称：±半行都要翻位`() {
        // ⚠️ 这条第一版是**红的** —— 实现当时直接用了 `roundToInt()`，而 Java 的 round 是
        //    "向正无穷取整"：`(+0.5).roundToInt() == 1` 但 `(-0.5).roundToInt() == 0`。
        //    结果是"往上拖"比"往下拖"要多划一点，用户感觉是上边黏。
        val row = 100f
        for (frac in listOf(0.5f, 0.6f, 1.4f, 2.5f)) {
            assertEquals(
                "位移 ±${frac} 行应当对称",
                dragSteps(frac * row, row),
                -dragSteps(-frac * row, row),
            )
        }
        assertEquals(1, dragSteps(50f, 100f))
        assertEquals(-1, dragSteps(-50f, 100f))
    }

    @Test
    fun `量不出行高时不猜（除零保护）`() {
        assertEquals(0, dragSteps(200f, 0f))
        assertEquals(0, dragSteps(200f, -1f))
    }

    @Test
    fun `拖动是一格一格换位，所以中途松手也不会丢行`() {
        // 模拟"快速往下拖 3 格"：每次只挪 1 格，累计 3 次。
        // ⚠️ 期望值第一版写成了 [2,3,1,4,5] —— 那是**我数错了**（第 3 次已经把 id=1 挪到第 4 位）。
        //    这条测试的价值正在这里：拖动这种"连续小步"最容易在脑子里算错一格。
        var list: List<ProductCategoryDto> = five
        list = moveItemTo(list, { it.id }, id = 1, position = 2)   // [2,1,3,4,5]
        list = moveItemTo(list, { it.id }, id = 1, position = 3)   // [2,3,1,4,5]
        list = moveItemTo(list, { it.id }, id = 1, position = 4)   // [2,3,4,1,5]
        assertEquals(listOf(2L, 3L, 4L, 1L, 5L), ids(list))
        assertTrue(list.size == five.size)
    }
}
