package com.tapmoay.sorders.ui.common

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 订单列表**空着时那一句**的四种走法（2026-10-09，测试台账 TA-01）。
 *
 * 为什么要单测：这是一句"只在列表空着时出现"的话 —— 真机上要复现它得先造一个空列表，
 * 而判据（`_tools/qa/_check_order_list_ui.py`）只能看源码里有没有那几串字。
 * 只有把参数直接喂进来，才能钉住"**带状态筛选的空态必须点名是哪一档在挡**"这件事：
 * 缺省档「派单中」自带 `status=PENDING_DISPATCH`，用户搜一个已派单的单号时，
 * 屏幕上原来只有四个字"没有匹配的订单" —— 看起来就是"这单不见了"。
 */
class OrderEmptyHintTest {

    private fun hint(
        tabLabel: String = "派单中",
        statusFiltered: Boolean = true,
        windowWord: String? = null,
        searching: Boolean = false,
        noMatch: String = "没有匹配的订单",
    ) = orderEmptyHint(tabLabel, statusFiltered, windowWord, searching, noMatch)

    @Test
    fun `日期窗口那一档还是原来那一句（不许改短）`() {
        assertEquals(
            "「今天」没有已送达的订单 —— 点右上角可以换一段时间",
            hint(tabLabel = "已送达", windowWord = "今天"),
        )
    }

    @Test
    fun `日期窗口 + 搜过：两条出路都要给`() {
        val s = hint(tabLabel = "已送达", windowWord = "今天", searching = true)
        assertTrue(s, "点右上角可以换一段时间" in s)
        assertTrue(s, "点页签「全部」再搜" in s)
    }

    @Test
    fun `带状态筛选 + 搜过：点名是这一档在挡，并给出路（TA-01 的本体）`() {
        val s = hint(tabLabel = "派单中", searching = true)
        assertTrue(s, "这一页只看「派单中」" in s)
        assertTrue(s, "点页签「全部」可以搜别的状态" in s)
        assertTrue(s, "没有匹配的订单" !in s)
    }

    @Test
    fun `带状态筛选没搜过：说清这一档现在没单 + 出路`() {
        val s = hint(tabLabel = "已接单")
        assertTrue(s, "还没有单" in s)
        assertTrue(s, "点页签「全部」可以看到其他状态的单" in s)
    }

    @Test
    fun `换个档位标签，点名的那一档跟着换（不许写死字面量）`() {
        assertTrue("「已派单」还没有单" in hint(tabLabel = "已派单"))
        assertTrue("「已退货」还没有单" in hint(tabLabel = "已退货"))
    }

    @Test
    fun `「全部」那一档（不带 status）用调用方给的兜底句`() {
        assertEquals("没有匹配的订单", hint(statusFiltered = false))
        assertEquals("暂无订单", hint(statusFiltered = false, noMatch = "暂无订单"))
    }

    @Test
    fun `日期窗口优先于状态筛选（「已送达」两样都占时说的是时间）`() {
        val s = hint(tabLabel = "已送达", windowWord = "本月", searching = false)
        assertTrue(s, "「本月」没有已送达的订单" in s)
        assertTrue(s, "还没有单" !in s)
    }

    @Test
    fun `四档都给一句能照着做的话（都点了名，没有空话）`() {
        val all = listOf(
            hint(tabLabel = "已送达", windowWord = "今天"),
            hint(tabLabel = "已送达", windowWord = "今天", searching = true),
            hint(tabLabel = "派单中", searching = true),
            hint(tabLabel = "派单中"),
        )
        all.forEach { assertTrue(it, it.isNotBlank() && "点" in it) }
    }
}
