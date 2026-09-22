package com.tapmoay.sorders.ui.home

import com.tapmoay.sorders.ui.nav.Modules
import com.tapmoay.sorders.ui.nav.Role
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 工作台头部那条文案（`workbenchHeaderText`）与它**只出现在哪两端**。
 *
 * ## 由来（用户 2026-09-22，对着他给的 POS 截图两轮口述）
 * > 「这次做的样式它是**比较长，且扁**的，就是**能用一行的概括就概括**……**货主的标签 + 工作台**，
 * > 也就是说「**工作台 · 订单与账本**」在**左边**，然后**货主的标签放在右边**」；
 * > 「有 1.1 有一个**单是不需要做的，那就是司机**……也就是说，**只要做派单员和货主**」。
 *
 * 这一组断言守三件事：**三个角色的左文案**（一个字都不许走样）、
 * **与右边胶囊不重复**（不许再写成「货主端 · 订单与账本」）、
 * 以及**司机端确实没有工作台这一屏**（用户第 1.1 条的原话就是"司机那端没有这个形态"）。
 */
class WorkbenchHeaderTest {

    @Test
    fun `三种角色的左文案（一行，与右边胶囊不重复）`() {
        assertEquals("工作台 · 订单与账本", workbenchHeaderText(Role.SHIPPER))
        assertEquals("工作台 · 全量管理", workbenchHeaderText(Role.DISPATCHER))
        assertEquals("工作台 · 任务与送达", workbenchHeaderText(Role.DRIVER))
    }

    @Test
    fun `文案里不许再出现「货主端」「司机端」「派单端」——那一端已经由右边的胶囊说了`() {
        Role.entries.forEach { r ->
            val text = workbenchHeaderText(r)
            assertFalse("$r 的文案里还留着角色端别：$text", text.contains("端"))
        }
    }

    @Test
    fun `文案都是一行、都以「工作台」开头（左半边的意思不能丢）`() {
        Role.entries.forEach { r ->
            val text = workbenchHeaderText(r)
            assertTrue("$r：$text 没有以「工作台」开头", text.startsWith("工作台"))
            assertFalse("$r：$text 里不许有换行（它是一行概括）", text.contains("\n"))
            assertTrue("$r：$text 太短了，右边的胶囊才是两三个字", text.length > 6)
        }
    }

    @Test
    fun `司机端没有工作台这一屏（用户点名司机不做）`() {
        val driverTabs = Modules.bottomTabs(Role.DRIVER)
        assertFalse(
            "司机端不该有工作台 Tab —— 有了就会用到这个头部，而用户明确说司机这端不做",
            driverTabs.any { it.content == "workbench" },
        )
    }

    @Test
    fun `要改的两端（货主与派单员）确实都有工作台这一屏`() {
        assertTrue(Modules.bottomTabs(Role.SHIPPER).any { it.content == "workbench" })
        assertTrue(Modules.bottomTabs(Role.DISPATCHER).any { it.content == "workbench" })
    }
}
