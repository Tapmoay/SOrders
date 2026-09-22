package com.tapmoay.sorders.ui.common

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 单位选择页的两段纯逻辑（`unitChoices` / `filterUnits`）。
 *
 * ## 为什么第一条必须单测（它是"会静默改掉商品单位"的那一道保险）
 * 词表 = 原来的 16 个预设 + **商品库里已经在用的那些**，而库里 `products.unit` 是自由串
 * （老数据里可能有"提""筐"这种预设里没有的单位）。
 * 如果 `unitChoices` 漏了"当前单位"，用户编辑一个单位是"提"的商品时：
 * 点开选择页 → **找不到"提"** → 随手点一个别的 → 保存 → **单位被改了，而界面上看不出任何异常**。
 * 这种错模拟器上要"故意去试"才能发现，所以钉在纯函数上。
 */
class UnitsTest {

    @Test
    fun `当前单位一定在列表里 —— 哪怕是预设和库里都没有的冷门词`() {
        val list = unitChoices(current = "提", inUse = listOf("件", "箱"))
        assertTrue("当前单位必须能被选中，否则一次误点就静默改了它", list.contains("提"))
        assertEquals("补进来的当前单位排最前面（要一眼看得见）", "提", list.first())
    }

    @Test
    fun `库里已经在用的排在最前面（预设在后），且去重保序`() {
        val list = unitChoices(current = "箱", inUse = listOf("提", "筐", "提", "  "))
        assertEquals(listOf("提", "筐"), list.take(2))
        assertEquals("预设接在后面", UNIT_PRESETS.first(), list[2])
        // 预设里也有「箱」，只留一份（在库里那一段里）
        assertEquals(1, list.count { it == "箱" })
    }

    @Test
    fun `不去改动预设的完整性（16 个都在）`() {
        val list = unitChoices(current = "件", inUse = emptyList())
        assertEquals(UNIT_PRESETS.size, list.size)
        UNIT_PRESETS.forEach { assertTrue("预设 $it 不能丢", list.contains(it)) }
    }

    @Test
    fun `当前值为空时不制造空档位`() {
        assertEquals(UNIT_PRESETS, unitChoices(current = null, inUse = emptyList()))
        assertEquals(UNIT_PRESETS, unitChoices(current = "   ", inUse = emptyList()))
    }

    @Test
    fun `unitOrDefault：空与纯空格都兜成「件」（与后端缺省一致）`() {
        assertEquals("件", unitOrDefault(null))
        assertEquals("件", unitOrDefault(""))
        assertEquals("件", unitOrDefault("   "))
        assertEquals("袋", unitOrDefault(" 袋 "))
    }

    @Test
    fun `搜索是子串、忽略大小写；关键词为空就返回全部`() {
        val units = listOf("件", "公斤", "箱", "kg")
        assertEquals(units, filterUnits(units, ""))
        assertEquals(units, filterUnits(units, "   "))
        assertEquals(listOf("公斤"), filterUnits(units, "斤"))
        assertEquals(listOf("kg"), filterUnits(units, "KG"))
    }

    @Test
    fun `搜不到就是空表（页面据此画「没有匹配」，而不是「没有单位可选」）`() {
        assertTrue(filterUnits(listOf("件", "箱"), "提").isEmpty())
        assertFalse(UNIT_PRESETS.contains("提"))
    }
}
