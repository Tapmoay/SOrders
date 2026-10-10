package com.tapmoay.sorders.ui.dispatcher

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 账号分类左栏的两级（2026-10-11 CHG-0112）：大类 → 子类的分组、缩进、「点大类筛出它下面
 * 所有子类」，以及两条边界（脏数据不许把行藏起来、平表名册照旧）。
 *
 * 全部打在纯函数上（`AccountCategoryTree.kt`，零 Compose import）—— 那几条判断是这一单最
 * 容易被后续改动弄坏的地方，而它们在真机上要「点开抽屉、数一列格子」才看得出来。
 */
class AccountCategoryTreeTest {

    private fun row(id: Long, name: String, parentId: Long? = null) =
        RosterRow(id = id, name = name, count = 0, sortOrder = id.toInt(), parentId = parentId)

    /** 名册顺序：货主(1) / 食堂(4) / 超市(5) / 批发商(2) / 派单员(3) ——
     *  两级树应当把它重排成「货主 → 食堂 → 超市 → 批发商 → 派单员」（子类紧跟它的大类）。 */
    private val roster = listOf(
        row(1, "货主"),
        row(4, "食堂", parentId = 1),
        row(5, "超市", parentId = 1),
        row(2, "批发商"),
        row(3, "派单员"),
    )

    @Test
    fun 大类后面紧跟它的子类且子类缩进一级() {
        val rail = categoryRailRows(roster)
        assertEquals(listOf("货主", "食堂", "超市", "批发商", "派单员"), rail.map { it.label })
        assertEquals(listOf(0, 1, 1, 0, 0), rail.map { it.depth })
        assertEquals("c|食堂", rail[1].key)
    }

    @Test
    fun 点大类筛出它下面所有子类_点子类只筛那一类() {
        assertEquals(setOf("货主", "食堂", "超市"), railNamesUnder(roster, "c|货主"))
        assertEquals(setOf("食堂"), railNamesUnder(roster, "c|食堂"))
        assertEquals(setOf("批发商"), railNamesUnder(roster, "c|批发商"))
    }

    @Test
    fun 筛选是按覆盖的名字来的_账号那一格仍然是叶子名() {
        // 这一条钉的是「点大类 = 把挂在子类上的账号也端出来」：账号上写的是「食堂」，
        // 而左栏点的是「货主」—— 不把它过滤掉才是这一单要的效果。
        val accounts = listOf("货主", "食堂", "超市", "批发商")
        fun shown(key: String) = accounts.filter { it in railNamesUnder(roster, key) }
        assertEquals(listOf("货主", "食堂", "超市"), shown("c|货主"))
        assertEquals(listOf("食堂"), shown("c|食堂"))
        assertEquals(listOf("批发商"), shown("c|批发商"))
    }

    @Test
    fun 全部那一格不筛() {
        assertTrue(railNamesUnder(roster, "").isEmpty())
        assertTrue(categoryRailRows(roster).none { it.key.isEmpty() })
    }

    @Test
    fun 父不在名册里的子类降级成大类_一行都不许消失() {
        // 父被删了（或 parent_id 指向一个已经不存在的行）：这一行照样要画出来 ——
        // 藏起来等于那一类的账号在左栏里点不到。
        val orphan = roster + row(9, "孤儿子类", parentId = 999)
        val rail = categoryRailRows(orphan)
        assertEquals(orphan.size, rail.size)
        val node = rail.first { it.label == "孤儿子类" }
        assertEquals(0, node.depth)
        assertEquals(setOf("孤儿子类"), node.covers)
    }

    @Test
    fun 第三层是脏数据_也降级成大类不许消失() {
        // 后端不让建「子类的子类」，但库里可能有（手工改库 / 老数据）。
        val deep = roster + row(7, "深一层", parentId = 4)
        val rail = categoryRailRows(deep)
        assertEquals(deep.size, rail.size)
        assertEquals(0, rail.first { it.label == "深一层" }.depth)
    }

    @Test
    fun 平表名册与两级之前一模一样() {
        // 车辆分类那份是平表（parentId 全是 null）：每格 depth=0、覆盖只有自己。
        val flat = listOf(row(1, "自有车队"), row(2, "外调车"))
        val rail = categoryRailRows(flat)
        assertEquals(listOf("自有车队", "外调车"), rail.map { it.label })
        assertTrue(rail.all { it.depth == 0 })
        assertEquals(setOf("外调车"), railNamesUnder(flat, "c|外调车"))
    }

    @Test
    fun 空名册不崩且什么都不画() {
        assertEquals(emptyList<RailRow>(), categoryRailRows(emptyList()))
        assertTrue(railNamesUnder(emptyList(), "c|货主").isNotEmpty())
    }
}
