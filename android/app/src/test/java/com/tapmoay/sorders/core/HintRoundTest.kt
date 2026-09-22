package com.tapmoay.sorders.core

import com.tapmoay.sorders.core.HintRound.State
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 「提示」总开关那三条用户决定的单测（`HintRound` 是纯函数，见它的 KDoc）。
 *
 * 为什么必须有：这三条是**按顺序发生**才有意义的契约 ——
 * "第一次登录打开 → 下一次冷启动关上 → 手动拨过之后永不自动改"。
 * 顺序错一个（比如冷启动把它关了、而用户明明手动打开过），
 * 表现是"**开关自己会变**"，而真机上极难复现（要点登录、杀进程、再开、再拨）。
 * 这里把顺序直接摆出来跑。
 *
 * ⛔ 其中最后两条是**反悔条款**：用户手动拨过之后，任何自动逻辑都不许再动它。
 * 那是最容易被"顺手加一条自动判断"改坏的地方。
 */
class HintRoundTest {

    private val fresh = HintRound.FRESH

    // ---- 默认值与第一次登录 ----

    @Test
    fun `全新安装默认是关的（第一次登录之前不显示任何说明）`() {
        assertFalse(fresh.visible)
        assertFalse(fresh.roundShown)
        assertFalse(fresh.autoOffPending)
    }

    @Test
    fun `第一次登录把开关打开，并记下待自动关`() {
        val s = HintRound.onLogin(fresh)
        assertTrue("第一次登录必须打开（新用户要先看全）", s.visible)
        assertTrue(s.roundShown)
        assertTrue("要记得下一轮冷启动把它关上", s.autoOffPending)
    }

    @Test
    fun `同一台设备的第二次登录不再改开关`() {
        val after = HintRound.onAppStart(HintRound.onLogin(fresh)) // 第一轮：开 → 冷启动：关
        assertFalse(after.visible)
        val again = HintRound.onLogin(after)
        assertFalse("第二次登录不该又把它打开（那是每账号一次，不是每台一次）", again.visible)
        assertEquals(after, again)
    }

    // ---- 冷启动 ----

    @Test
    fun `首次登录那一轮之后的冷启动会自动关上`() {
        val s = HintRound.onAppStart(HintRound.onLogin(fresh))
        assertFalse("用户要的就是「之后就默认关闭」", s.visible)
        assertFalse(s.autoOffPending)
    }

    @Test
    fun `再冷启动几次都保持关着（不会自己来回跳）`() {
        var s = HintRound.onAppStart(HintRound.onLogin(fresh))
        repeat(3) { s = HintRound.onAppStart(s) }
        assertFalse(s.visible)
    }

    @Test
    fun `没登录过就冷启动，什么都不做`() {
        assertEquals(fresh, HintRound.onAppStart(fresh))
    }

    // ---- 反悔条款：用户手动拨过之后，自动逻辑不许再动它 ----

    @Test
    fun `用户手动打开之后，冷启动不许把它关掉`() {
        // 首次登录那一轮 → 用户自己拨开 → 冷启动
        val s = HintRound.onAppStart(HintRound.setByUser(HintRound.onLogin(fresh), on = true))
        assertTrue("手动打开过就是他的选择，不许被自动关掉", s.visible)
    }

    @Test
    fun `用户手动关掉之后，再登录不许又打开`() {
        val s = HintRound.onLogin(HintRound.setByUser(HintRound.onLogin(fresh), on = false))
        assertFalse("他明确关掉过，再登进来不该又打开", s.visible)
    }

    @Test
    fun `手动拨过就清掉待自动关`() {
        val s = HintRound.setByUser(HintRound.onLogin(fresh), on = true)
        assertFalse(s.autoOffPending)
    }

    // ---- 老安装 ----

    @Test
    fun `老安装不补一轮：即使旧值是关的，也不再自动打开`() {
        val s = HintRound.fromLegacy(legacyAlwaysOn = false)
        assertFalse(s.visible)
        assertTrue("老用户早就见过那些话，升级不该又给他打开一遍", s.roundShown)
        assertEquals(s, HintRound.onLogin(s))
    }

    @Test
    fun `老安装里旧开关是开的，就继续开着`() {
        val s = HintRound.fromLegacy(legacyAlwaysOn = true)
        assertTrue(s.visible)
        assertEquals(s, HintRound.onLogin(s))
    }

    // ---- 幂等 ----

    @Test
    fun `同一个值连拨两次不改变状态`() {
        val once = HintRound.setByUser(fresh, on = true)
        assertEquals(once, HintRound.setByUser(once, on = true))
        val off = HintRound.setByUser(once, on = false)
        assertEquals(off, HintRound.setByUser(off, on = false))
    }

    @Test
    fun `状态是值对象（比较靠内容，不靠引用）`() {
        assertEquals(State(true, true, false), State(true, true, false))
        // 两条路各自的确切结果（差别就在 autoOffPending）：
        assertEquals("手动拨开：不留待自动关", State(true, true, false),
            HintRound.setByUser(fresh, on = true))
        assertEquals("首次登录：要留待自动关", State(true, true, true),
            HintRound.onLogin(fresh))
    }
}
