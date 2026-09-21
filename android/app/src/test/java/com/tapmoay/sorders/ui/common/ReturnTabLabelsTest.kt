package com.tapmoay.sorders.ui.common

import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * 退货申请两端共用的**档位标签**：待处理那一档带上张数。
 *
 * 为什么值得单独测：这段原来是两页各写一遍的 `mapIndexed { i, t -> if (i == 1 …) }` /
 * `if (i == 0 …)` —— 两页的档位顺序**相反**，所以那句"魔法下标"只能在各自那一页是对的；
 * 谁把另一页那行抄过来，张数就挂到**另一档**上（用户看到「全部 3」，点进去却不是那三张），
 * 而且不会报任何错。现在判据是档位的 **key**，这个文件钉的就是它。
 */
class ReturnTabLabelsTest {

    private val dispatcherTabs = listOf(ReturnTab("all", "全部"), ReturnTab("pending", "待处理"))
    private val shipperTabs = listOf(ReturnTab("pending", "待处理"), ReturnTab("all", "全部"))

    @Test
    fun `张数挂在「待处理」那一档上_与档位顺序无关`() {
        assertEquals(listOf("全部", "待处理 3"), returnTabLabels(dispatcherTabs, 3))
        assertEquals(listOf("待处理 3", "全部"), returnTabLabels(shipperTabs, 3))
    }

    @Test
    fun `没有待处理时不加那个 0`() {
        // 「待处理 0」是噪音：用户还得点进去确认一次"真的没有"
        assertEquals(listOf("全部", "待处理"), returnTabLabels(dispatcherTabs, 0))
        assertEquals(listOf("待处理", "全部"), returnTabLabels(shipperTabs, 0))
    }

    @Test
    fun `名册里没有 pending 这一档时原样返回（不硬塞张数）`() {
        val other = listOf(ReturnTab("all", "全部"), ReturnTab("done", "已办理"))
        assertEquals(listOf("全部", "已办理"), returnTabLabels(other, 7))
    }

    @Test
    fun `其它档位永远不带数字`() {
        val tabs = listOf(ReturnTab("all", "全部"), ReturnTab("pending", "待处理"), ReturnTab("done", "已办理"))
        assertEquals(listOf("全部", "待处理 12", "已办理"), returnTabLabels(tabs, 12))
    }
}
