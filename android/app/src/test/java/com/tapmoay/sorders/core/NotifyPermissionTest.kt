package com.tapmoay.sorders.core

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 「通知权限没开时该不该拦一次」——[NotifyPermission.shouldPrompt]。
 *
 * 台账 L-26 第⑤条（用户 2026-10-06，ref **m01132**）：「**如果权限不足的话，我们就给他开**」；
 * 首页那道硬提示（`ui/home/RoleHomeScreen.kt`）拦不拦，就只看这一个判断。
 *
 * 单测钉的是**两个方向都不许写错**：
 * - 写成恒真 → 每次进首页都弹（用户进一次烦一次，最后连真的该开的也一起被忽略）；
 * - 写成恒假 → 这个功能等于不存在（又回到"静默降级"，而漏通知的后果是账会乱）。
 */
class NotifyPermissionTest {

    @Test
    fun `权限开着就不拦（哪怕这一轮还没拦过）`() {
        assertFalse(NotifyPermission.shouldPrompt(enabled = true, promptedThisLaunch = false))
    }

    @Test
    fun `权限没开、这一轮还没拦过 —— 要拦`() {
        assertTrue(NotifyPermission.shouldPrompt(enabled = false, promptedThisLaunch = false))
    }

    @Test
    fun `同一轮启动里拦过一次就不再拦（进首页、切回来都不重复弹）`() {
        assertFalse(NotifyPermission.shouldPrompt(enabled = false, promptedThisLaunch = true))
    }

    @Test
    fun `四种组合逐条断言（防止这个判据被写成恒真或恒假）`() {
        val expected = mapOf(
            (true to false) to false,
            (true to true) to false,
            (false to false) to true,
            (false to true) to false,
        )
        listOf(false, true).forEach { enabled ->
            listOf(false, true).forEach { prompted ->
                assertTrue(
                    "enabled=$enabled / prompted=$prompted 与口径不一致",
                    NotifyPermission.shouldPrompt(enabled, prompted) == expected.getValue(enabled to prompted),
                )
            }
        }
    }

    @Test
    fun `markPrompted 之后这一次启动就算拦过了（落点只有这一个写入口）`() {
        NotifyPermission.markPrompted()
        assertTrue(NotifyPermission.promptedThisLaunch)
        assertFalse(
            NotifyPermission.shouldPrompt(enabled = false, promptedThisLaunch = NotifyPermission.promptedThisLaunch),
        )
    }
}
