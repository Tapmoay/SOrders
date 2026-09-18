package com.tapmoay.sorders.ui.nav

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import kotlin.math.sqrt

/**
 * 底部导航栏「凹口」几何的单测。
 *
 * 为什么值得单独测：这块形状**画错了也照样能跑**——第一版把凹口的圆心放在栏上沿之上，
 * 切出来只有 18dp 深的浅坑，而且几乎整块被圆钮自己盖住；真机截图量像素才发现
 * 「缺口内外上沿的 y 完全一样」，也就是用户要的"凹一下"根本没画出来。
 * 几何是纯数学，用测试钉住最便宜。
 */
class NotchedBarTest {

    // 真实参数：圆钮 58dp（半径 29dp）、上沿之上露出 16dp、缝 5dp
    // （这一组是**纯几何**的算术题，故意写死输入输出，验的是公式本身）
    private val g = NavBarNotch.geometry(buttonDiameter = 58.0, buttonTopAboveEdge = 16.0, gap = 5.0)

    // 真实参数的**设计约束**：输入取当前常量（改常量不该让公式测试变红，
    // 但"太浅/咬穿/紧贴"这些造型判据必须跟着常量走）。
    private val real = NavBarNotch.geometry(
        buttonDiameter = AiNavButton.Size.value.toDouble(),
        buttonTopAboveEdge = AiNavButton.Protrude.value.toDouble(),
        gap = NavBarNotch.Gap.value.toDouble(),
    )

    @Test
    fun `凹口圆心在栏内而不是栏外`() {
        // 圆钮是"上面露 16dp、其余压进栏里"，所以圆心必然在栏上沿**下方** 29−16＝13dp。
        // 放到栏外（13 → -16）就会切出一个又浅又藏在钮后面的坑，等于没画。
        assertEquals(13.0, g.centerY, 0.001)
        assertTrue("圆心必须在栏内（centerY > 0）", g.centerY > 0)
    }

    @Test
    fun `凹口半径 = 钮半径 + 缝（留出看得见的呼吸）`() {
        assertEquals(34.0, g.radius, 0.001)
        assertTrue("必须比钮大一点，否则贴着像被切了一刀", g.radius > 29.0)
    }

    @Test
    fun `凹口与上沿的交点算得对`() {
        // halfWidth = √(r² − centerY²) = √(34² − 13²) ≈ 31.4dp，即缺口横向跨约 63dp
        assertEquals(sqrt(34.0 * 34.0 - 13.0 * 13.0), g.halfWidth, 0.001)
        assertTrue("缺口要比圆钮略宽（58dp 的钮 → 缺口约 63dp）", g.halfWidth > 29.0)
    }

    @Test
    fun `最深点在栏里但要留得住图标和文字`() {
        // depth = centerY + r = 47dp；导航栏高 80dp → 咬掉约 59%（参照图大致就是这个比例）
        assertEquals(47.0, g.depth, 0.001)
        assertTrue("不能把整条栏咬穿", g.depth < 80.0)
        assertTrue("太浅了看不见（第一版 18dp 就是这个毛病）", g.depth > 30.0)
    }

    @Test
    fun `弧一定经过正下方（90 度）`() {
        // 缺口是"半圆"：弧从左右交点出发必须扫过 90°（正下方），否则要么没切到底、
        // 要么扫错方向把那块白又补回来。第二版踩的就是"从右交点顺时针"补出一条弦。
        assertEquals(-22.6, g.startAngle, 0.2)         // 右交点在圆心上方 → 负角
        assertEquals(202.6, g.leftAngle, 0.2)
        assertTrue("必须是逆时针（负扫角）", g.sweepAngle < 0)
        assertEquals(-225.2, g.sweepAngle, 0.4)
        // 从起点（左交点 202.6°）逆时针扫 225.2° → 终点 -22.6°＝右交点；
        // 途中经过 180°、90°（正下方）✓
        val end = g.leftAngle + g.sweepAngle
        assertEquals(g.startAngle, end, 0.001)
        assertTrue("扫过的角度里必须包含 90°", g.leftAngle + g.sweepAngle < 90.0 && g.leftAngle > 90.0)
    }

    @Test
    fun `圈钮完全浮在栏外时退化成半圆而不是画崩`() {
        // 极端参数（钮只露一半以上、圆心正好在沿上）也要有定义，不能出 NaN / 负宽度
        val onEdge = NavBarNotch.geometry(buttonDiameter = 58.0, buttonTopAboveEdge = 29.0, gap = 5.0)
        assertEquals(0.0, onEdge.centerY, 0.001)
        assertEquals(34.0, onEdge.halfWidth, 0.001)   // 半圆
        assertEquals(34.0, onEdge.depth, 0.001)
        assertEquals(0.0, onEdge.startAngle, 0.001)
    }

    @Test
    fun `钮几乎全压进栏里时不会算出虚数宽度`() {
        // centerY > r 的极端情况（钮很大、几乎不露头）：halfWidth 必须是 0 而不是负数/NaN
        val buried = NavBarNotch.geometry(buttonDiameter = 58.0, buttonTopAboveEdge = 0.0, gap = 0.0)
        assertEquals(29.0, buried.centerY, 0.001)
        assertEquals(0.0, buried.halfWidth, 0.001)
        assertTrue(buried.depth.isFinite())
    }

    // ---- 造型判据（跟着真实常量走：用户两轮反馈都是冲这几个数来的） ----

    @Test
    fun `凹口不紧贴圆钮（用户：太窄了，紧贴着按钮）`() {
        // 缝隙就是 r − 钮半径。用户看过真机截图后要求"稍微扩大一点"，
        // 所以这条下限是**用户定的**：低于 6dp 就变成"被切了一刀"。
        val gap = real.radius - AiNavButton.Size.value / 2
        assertTrue("缝隙只有 ${gap}dp，太窄（要 ≥6dp）", gap >= 6.0)
    }

    @Test
    fun `圆钮坐得比栏沿低一点（用户：把按钮稍微向下移一点）`() {
        // 圆心在栏内侧 — 这条第一版就错过一次（算到栏外，坑全被钮盖住）。
        // 现在还要保证它"坐进去"而不是"只搭了个边"：圆心至少进栏 15dp。
        assertTrue("圆心只在栏内 ${real.centerY}dp，看着还是飘在栏上", real.centerY >= 15.0)
    }

    @Test
    fun `凹口宽于圆钮（左右各留得出缝）`() {
        assertTrue(
            "凹口半宽 ${real.halfWidth}dp 没有超过钮半径 ${AiNavButton.Size.value / 2}dp",
            real.halfWidth > AiNavButton.Size.value / 2,
        )
    }

    @Test
    fun `凹口深而不咬穿（栏高 80dp 里留得住图标）`() {
        assertTrue("太浅看不见：${real.depth}dp", real.depth > 30.0)
        assertTrue("把栏咬穿了：${real.depth}dp", real.depth < 80.0)
    }
}
