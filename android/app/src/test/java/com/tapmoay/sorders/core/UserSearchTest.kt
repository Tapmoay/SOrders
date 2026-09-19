package com.tapmoay.sorders.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 按「人」搜索规则的钉子（用户 2026-09-19：名称 / 手机号 / 手机号后 4 位）。
 *
 * 为什么值得单独一份单测：这条规则有 3 个消费点（账本仪表盘、四个名册页、AI 的 `q`），
 * 而**它坏掉的样子是"搜得到 / 搜不到"** —— 界面上没有任何异常，用户只会觉得系统坏了。
 */
class UserSearchTest {

    // ---------------------------------------------------------------- 三种写法

    @Test
    fun `姓名、全号、后四位 都能命中同一个人`() {
        val name = "张三"
        val phone = "13800008001"

        assertTrue("姓名全写", UserSearch.matches("张三", name, phone))
        assertTrue("姓名片段", UserSearch.matches("张", name, phone))
        assertTrue("手机号全号", UserSearch.matches("13800008001", name, phone))
        assertTrue("手机号后 4 位", UserSearch.matches("8001", name, phone))
        assertTrue("手机号中间片段", UserSearch.matches("00008", name, phone))
    }

    @Test
    fun `不匹配的不能命中`() {
        // 反例必须钉住：没有它，"matches 恒返回 true" 也能让上面那条过
        assertFalse(UserSearch.matches("8002", "张三", "13800008001"))
        assertFalse(UserSearch.matches("李四", "张三", "13800008001"))
        assertFalse(UserSearch.matches("138000080012", "张三", "13800008001"))
    }

    // ---------------------------------------------------------------- 边界

    @Test
    fun `空查询 = 不筛（不是搜空串）`() {
        assertTrue(UserSearch.matches("", "张三", "13800008001"))
        assertTrue(UserSearch.matches("   ", "张三", "13800008001"))
        assertTrue("前导空格的查询词要按去掉空格后算", UserSearch.matches("  8001  ", "张三", "13800008001"))
    }

    @Test
    fun `姓名为空的人仍可按手机号搜到（老数据或临时货主）`() {
        assertTrue(UserSearch.matches("8001", null, "13800008001"))
        assertTrue(UserSearch.matches("8001", "", "13800008001"))
        // 两侧都空时，只有空查询能命中（否则一个空查询词会命中所有人）
        assertFalse(UserSearch.matches("8001", null, null))
    }

    @Test
    fun `大小写不分（与后端 func_lower 那份对齐）`() {
        assertTrue(UserSearch.matches("alice", "Alice Wang", "13800008001"))
        assertTrue(UserSearch.matches("ALICE", "Alice Wang", "13800008001"))
        assertTrue(UserSearch.matches("alice wang", "Alice Wang", "13800008001"))
    }

    @Test
    fun `软删账号的手机号带 _del 后缀时，去尾后的号也能搜到`() {
        // 名册页拿到的就是库里那个值（带后缀），用户只会输入能拨的那一段
        assertTrue(UserSearch.matches("8001", "张三", "13800008001_del160"))
        assertTrue(UserSearch.matches("13800008001", "张三", "13800008001_del160"))
    }

    // ---------------------------------------------------------------- 列表过滤

    @Test
    fun `filter 保持服务端给的原顺序、空词原样返回`() {
        val rows = listOf(
            Triple("张三", "13800008001", 1),
            Triple("李四", "13900008002", 2),
            Triple("张老板", "13700008003", 3),
        )

        // 顺序 = 服务端顺序（已按金额/编号排好），过滤不许打乱它
        val zhang = UserSearch.filter(rows, "张", { it.first }, { it.second })
        assertEquals(listOf(1, 3), zhang.map { it.third })

        val all = UserSearch.filter(rows, "", { it.first }, { it.second })
        assertEquals(3, all.size)

        val none = UserSearch.filter(rows, "8009", { it.first }, { it.second })
        assertTrue(none.isEmpty())
    }
}
