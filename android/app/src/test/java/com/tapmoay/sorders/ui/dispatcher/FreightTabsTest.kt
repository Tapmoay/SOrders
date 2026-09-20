package com.tapmoay.sorders.ui.dispatcher

import com.tapmoay.sorders.data.remote.dto.FreightTemplateDto
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 运费模板的**分类栏分组规则**（2026-09-21）。
 *
 * 为什么值得单独钉：一条价目可以挂**多个**分类（用户：「一个模板可以有多个分类」），
 * 所以它是"在哪几类下都出现"，不是"属于某一类" —— 这条规则被各页各写一遍的话，
 * 同一条价目在分类栏里会出现/消失得不一致，而**两边都不报错**。
 */
class FreightTabsTest {

    private fun tpl(id: Long, cats: List<String>) = FreightTemplateDto(id = id, name = "价目$id", categoryNames = cats)

    @Test
    fun `全部那一格永远都出现`() {
        assertTrue(underFreightTab(tpl(1, listOf("蔬菜")), FREIGHT_TAB_ALL))
        assertTrue(underFreightTab(tpl(2, emptyList()), FREIGHT_TAB_ALL))
    }

    @Test
    fun `挂了多个分类的价目在每一类下都出现`() {
        val t = tpl(1, listOf("蔬菜", "水果"))
        assertTrue(underFreightTab(t, "蔬菜"))
        assertTrue(underFreightTab(t, "水果"))
        assertFalse(underFreightTab(t, "冻品"))
    }

    @Test
    fun `没挂分类的只在未分类那一格（不是每一类都出现）`() {
        val t = tpl(1, emptyList())
        assertFalse(underFreightTab(t, "蔬菜"))
        assertTrue(underFreightTab(t, FREIGHT_TAB_NONE))
    }

    @Test
    fun `挂了分类的不会出现在未分类那一格`() {
        assertFalse(underFreightTab(tpl(1, listOf("蔬菜")), FREIGHT_TAB_NONE))
    }
}
