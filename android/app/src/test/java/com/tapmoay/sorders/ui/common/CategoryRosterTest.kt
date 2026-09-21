package com.tapmoay.sorders.ui.common

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 四个分类名册（开销 / 运费 / 商品 / 地点）共用的三条规则。
 *
 * 为什么值得单独测：这三条原来在各自的 ViewModel 里各写一遍，而**已经走散过**——
 * 运费那一页的「撤销排序」当时是"只按 `savedOrder` 重建"的版本，会把保存之后新建的分类
 * 从列表里丢掉；开销/商品两页保留。同一个按钮、三页两种行为，谁都没报错。
 */
class CategoryRosterTest {

    private data class Row(val id: Long, val name: String)

    private fun rows(vararg ids: Long) = ids.map { Row(it, "分类$it") }

    @Test
    fun `只提交名册里的行_名册外的合成行不许带上`() {
        // 开销名册的列表里混着"名册外的分类（老数据）"这种 id == 0 的合成行：后端不认识它，
        // 带上就是整批拒绝（「顺序里有不存在的分类编号：[0]」）
        assertEquals(listOf(7L, 8L, 9L), submittableIds(rows(7, 0, 8, 9)) { it.id })
        // 负数（将来若有别的哨兵值）同样不许带上
        assertEquals(listOf(7L), submittableIds(rows(-1, 7)) { it.id })
        assertEquals(emptyList<Long>(), submittableIds(rows(0)) { it.id })
    }

    @Test
    fun `顺序改过没有_与上次保存的顺序逐位比`() {
        val saved = listOf(1L, 2L, 3L)
        assertFalse(orderChanged(rows(1, 2, 3), saved) { it.id })
        assertTrue(orderChanged(rows(2, 1, 3), saved) { it.id })
        // 新建的分类会让列表多一个编号 —— 那也算"改过"，要能点保存
        assertTrue(orderChanged(rows(1, 2, 3, 4), saved) { it.id })
        // 名册外的合成行（id=0）**不算**改动：它一直都在列表最后、后端也从不返回它，
        // 拿它一起比的话"未保存"标记会在保存成功之后仍然亮着（用户以为没保存上）
        assertFalse("id=0 的合成行不该把 dirty 点亮", orderChanged(rows(1, 2, 3, 0), listOf(1L, 2L, 3L)) { it.id })
    }

    @Test
    fun `撤销排序_回到上次保存的顺序`() {
        val saved = listOf(1L, 2L, 3L)
        val current = rows(3, 1, 2)
        assertEquals(listOf(1L, 2L, 3L), revertedOrder(current, saved) { it.id }.map { it.id })
    }

    @Test
    fun `撤销排序不许丢掉保存之后新建的分类`() {
        // savedOrder 是上次**保存**时的顺序，新建的分类不在里面；只按 savedOrder 重建，
        // 那一行会从列表里消失（后端还在，用户以为被删了）
        val saved = listOf(1L, 2L)
        val current = rows(2, 1, 99)   // 99 = 保存之后新建的
        assertEquals(listOf(1L, 2L, 99L), revertedOrder(current, saved) { it.id }.map { it.id })
    }

    @Test
    fun `保存顺序里已经不存在的行_直接跳过（不炸、也不补空位）`() {
        // 别人删掉了某个分类、而这份列表还没刷新时会出现
        val saved = listOf(1L, 2L, 3L)
        val current = rows(1, 3)
        assertEquals(listOf(1L, 3L), revertedOrder(current, saved) { it.id }.map { it.id })
    }
}
