package com.tapmoay.sorders.ui.nav

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import kotlin.math.atan2
import kotlin.math.cos
import kotlin.math.sin
import kotlin.math.sqrt

/**
 * 底部导航栏「凹口」几何的单测。
 *
 * 为什么值得单独测：这块形状**画错了也照样能跑**——第一版把凹口的圆心放在栏上沿之上，
 * 切出来只有 18dp 深的浅坑，而且几乎整块被圆钮自己盖住；真机截图量像素才发现
 * 「缺口内外上沿的 y 完全一样」，也就是用户要的"凹一下"根本没画出来。
 * 几何是纯数学，用测试钉住最便宜。
 *
 * 2026-09-20 加了第二件事：两侧「圆滑过渡」（用户：「它那个角是尖尖，把它做一个曲线过渡」）。
 * 判据是**相切关系**——圆角要同时与上沿、大圆相切，少切一个那边就还是尖角；
 * 而"相切"恰好是肉眼最容易看错、代码最容易写偏的那种东西，所以这里逐条算。
 */
class NotchedBarTest {

    // 真实参数：圆钮 58dp（半径 29dp）、上沿之上露出 16dp、缝 5dp
    // （这一组是**纯几何**的算术题，故意写死输入输出，验的是公式本身）
    // 过渡圆角**不传**：它的唯一正确取值是"圆心深度"，由相切条件解出来（见下面那条不变量）。
    private val g = NavBarNotch.geometry(
        buttonDiameter = 58.0,
        buttonTopAboveEdge = 16.0,
        gap = 5.0,
    )

    // 过渡半径 = 0：必须**逐位退回**加过渡之前那套几何（尖角时代）。
    // 这是"过渡真的是一段弧、而不是把别的数改了"的对照物。
    private val sharp = NavBarNotch.geometry(
        buttonDiameter = 58.0,
        buttonTopAboveEdge = 16.0,
        gap = 5.0,
        fillet = 0.0,
    )

    // 试过但**没用**的那一档：6dp 的过渡。留着它是为了让"为什么不取小的"有个可执行的答案
    // （真机上它会在两侧各留下一小块薄"喙"，见下面对应的那条测试）。
    private val tooSmall = NavBarNotch.geometry(
        buttonDiameter = 58.0,
        buttonTopAboveEdge = 16.0,
        gap = 5.0,
        fillet = 6.0,
    )

    // 真实参数的**设计约束**：输入取当前常量（改常量不该让公式测试变红，
    // 但"太浅/咬穿/紧贴/开口过宽"这些造型判据必须跟着常量走）。
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
        // 过渡不改圆心：它只动上沿那两个角
        assertEquals(g.centerY, sharp.centerY, 0.001)
    }

    @Test
    fun `凹口半径 = 钮半径 + 缝（留出看得见的呼吸）`() {
        assertEquals(34.0, g.radius, 0.001)
        assertTrue("必须比钮大一点，否则贴着像被切了一刀", g.radius > 29.0)
        assertEquals(g.radius, sharp.radius, 0.001)
    }

    @Test
    fun `凹口与上沿的交点算得对`() {
        // halfWidth = √(r² − centerY²) = √(34² − 13²) ≈ 31.4dp，即缺口横向跨约 63dp
        assertEquals(sqrt(34.0 * 34.0 - 13.0 * 13.0), g.halfWidth, 0.001)
        assertTrue("缺口要比圆钮略宽（58dp 的钮 → 缺口约 63dp）", g.halfWidth > 29.0)
        // 过渡不动这个数：它仍然是"大圆与上沿的交点"（尖角时代的位置），
        // 判据「缺口比圆钮宽」用的就是它，所以不能在加过渡时被改掉。
        assertEquals(sharp.halfWidth, g.halfWidth, 0.001)
    }

    @Test
    fun `最深点在栏里但要留得住图标和文字`() {
        // depth = centerY + r = 47dp；导航栏高 80dp → 咬掉约 59%（参照图大致就是这个比例）
        assertEquals(47.0, g.depth, 0.001)
        assertTrue("不能把整条栏咬穿", g.depth < 80.0)
        assertTrue("太浅了看不见（第一版 18dp 就是这个毛病）", g.depth > 30.0)
        // 过渡是"抹角"，不是"加深"：最深点必须原地不动，否则等于又改了一次造型
        assertEquals(sharp.depth, g.depth, 0.001)
    }

    @Test
    fun `弧一定经过正下方（90 度）`() {
        // 缺口是"半圆"：弧从左右交点出发必须扫过 90°（正下方），否则要么没切到底、
        // 要么扫错方向把那块白又补回来。第二版踩的就是"从右交点顺时针"补出一条弦。
        // 这一条用**无过渡**的参数：它验的是大圆本身的扫法（与过渡无关）。
        assertEquals(-22.6, sharp.startAngle, 0.2)         // 右交点在圆心上方 → 负角
        assertEquals(202.6, sharp.leftAngle, 0.2)
        assertTrue("必须是逆时针（负扫角）", sharp.sweepAngle < 0)
        assertEquals(-225.2, sharp.sweepAngle, 0.4)
        // 从起点（左交点 202.6°）逆时针扫 225.2° → 终点 -22.6°＝右交点；
        // 途中经过 180°、90°（正下方）✓
        val end = sharp.leftAngle + sharp.sweepAngle
        assertEquals(sharp.startAngle, end, 0.001)
        assertTrue("扫过的角度里必须包含 90°", sharp.leftAngle + sharp.sweepAngle < 90.0 && sharp.leftAngle > 90.0)
    }

    @Test
    fun `加了圆滑过渡后弧仍然经过正下方（90 度）`() {
        // 过渡把大圆的起点从"与上沿的交点"挪到"与圆角的切点"，扫角因此变小（少扫了两段圆角），
        // 但**最深点必须还是 90°**：起点和终点关于竖直轴对称，中点就落在 90°。
        assertEquals(90.0, (g.leftAngle + g.startAngle) / 2.0, 0.001)
        assertTrue("必须是逆时针（负扫角）", g.sweepAngle < 0)
        assertTrue("扫过的角度里必须包含 90°", g.leftAngle > 90.0 && g.leftAngle + g.sweepAngle < 90.0)
        assertEquals(g.startAngle, g.leftAngle + g.sweepAngle, 0.001)
        // 过渡抹掉的是两段小弧，所以扫角一定比无过渡时小
        assertTrue("过渡后扫角反而变大了（说明起点没挪到切点）", g.sweepAngle > sharp.sweepAngle)
    }

    @Test
    fun `过渡圆角半径 = 圆心深度（切点落在大圆最宽处，旧的方角整块消失）`() {
        // 这条是"过渡取值"的唯一不变量，四个等价的说法各验一遍：
        // 半径 = 圆心深度 ⇒ 圆角圆心与大圆圆心等高 ⇒ 切点在大圆最宽处 ⇒ 开口半宽 = 半径 + 缝 + 圆心深度。
        // ⚠️ 取小了会怎样：见下一条测试（会留下"喙"）。
        assertEquals("圆角半径必须等于圆心深度", g.centerY, g.filletRadius, 1e-9)
        assertEquals("开口半宽必须 = 大圆半径 + 圆角半径", g.radius + g.filletRadius, g.filletDx, 1e-9)
        assertEquals("切点必须落在大圆最宽处（切点角 0）", 0.0, g.startAngle, 1e-9)
        assertEquals("圆角弧是四分之一圆", 90.0, g.filletSweepAngle, 1e-9)
        assertEquals("大圆弧是半圈", -180.0, g.sweepAngle, 1e-9)
        assertEquals("左切点 = 正左方", 180.0, g.leftAngle, 1e-9)
        // 纯几何那组：半径 34 + 圆心深度 13 = 开口半宽 47dp
        assertEquals(47.0, g.filletDx, 1e-9)
    }

    @Test
    fun `过渡取小了会在大圆上半圈留下一小块喙（所以不取 6dp）`() {
        // 切点角 γ 由 sin γ = (圆心深度 − f) / (半径 + f) 决定：
        //   f = 圆心深度 → γ = 0（切点在最宽处，旧方角整块被抹掉）；
        //   f 越小     → γ 越大（切点往大圆上半圈跑），大圆那一小段边界留在材料里，
        //                就是一块薄"喙"加一条缝——真机上 0.5dp 看不出来，但像素量尺量得出来。
        assertTrue("6dp 的过渡怎么反而把切点压到最宽处以下了", tooSmall.startAngle < 0.0)
        // 切点的横向位置 = r·cos γ < r ⇒ 大圆最宽处那一小截（r − r·cos γ）还在材料里
        val lipWidth = tooSmall.radius - tooSmall.radius * cos(Math.toRadians(tooSmall.startAngle))
        assertTrue("6dp 时喙宽 ${lipWidth}dp 应当 > 0.5dp（这就是被否掉的理由）", lipWidth > 0.5)
        // 取对了就不该有喙：切点正好在最宽处
        assertEquals(0.0, g.radius - g.radius * cos(Math.toRadians(g.startAngle)), 1e-9)
    }

    @Test
    fun `圆滑过渡与上沿和大圆同时相切`() {
        // 圆角圆心 F = (filletDx, filletRadius)：与上沿相切 ⇒ 圆心在沿下 f 处；
        // 与大圆（圆心 C = (0, centerY)、半径 radius）外切 ⇒ |CF| = radius + f。
        // 少切任何一个，那边就还是一个尖角（用户看到的就是"两个矩形夹住圆钮"）。
        val dc = sqrt(g.filletDx * g.filletDx + (g.centerY - g.filletRadius) * (g.centerY - g.filletRadius))
        assertEquals(g.radius + g.filletRadius, dc, 1e-6)

        // 切点 T 必须**同时**落在两个圆上，而且在连心线上（相切的定义）
        val t = Math.toRadians(g.leftAngle)
        val tx = g.radius * cos(t)
        val ty = g.centerY + g.radius * sin(t)
        assertEquals(g.radius, sqrt(tx * tx + (ty - g.centerY) * (ty - g.centerY)), 1e-6)   // 在大圆上
        assertEquals(g.filletRadius, sqrt((tx + g.filletDx) * (tx + g.filletDx) + (ty - g.filletRadius) * (ty - g.filletRadius)), 1e-6)
        // 切点在栏上沿**之下**（曲线在栏内完成），但又不到缺口底部
        assertTrue("切点跑到上沿上面去了（ty=$ty）", ty > 0.0)
        assertTrue("切点比缺口底还深（ty=$ty）", ty < g.depth)
    }

    @Test
    fun `过渡把上沿的开口撑宽（不撑宽就说明还是尖角）`() {
        // 几何上躲不掉：圆角要同时与上沿、大圆相切 ⇒ xf² = halfWidth² + 2f(r + centerY) > halfWidth²。
        // 撑宽的那几 dp 正是原来尖角所在的位置——所以看着是"角被抹圆了"，不是"缺口变大了"。
        assertTrue("过渡后开口没有变宽：${g.filletDx} vs ${g.halfWidth}", g.filletDx > g.halfWidth)
        // 反过来的对照：f = 0 时开口必须**等于**交点位置（也就是尖角原样）
        assertEquals(sharp.halfWidth, sharp.filletDx, 1e-9)
        assertEquals(
            sqrt(34.0 * 34.0 - 13.0 * 13.0 + 2 * g.filletRadius * (34.0 + 13.0)),
            g.filletDx,
            0.001,
        )
    }

    @Test
    fun `圆角弧的扫角是顺时针的（反了会补一条弦把缺口盖住）`() {
        // 圆角弧从顶点（270°）顺时针扫到切点：扫角必然落在 (0°, 180°)
        assertTrue("扫角必须为正（顺时针）：${g.filletSweepAngle}", g.filletSweepAngle > 0.0)
        assertTrue("扫角超过半圈了：${g.filletSweepAngle}", g.filletSweepAngle < 180.0)
        // 两侧对称 ⇒ 扫角相同，只是起点不同（差 180°）
        assertEquals(180.0, g.rightFilletStartAngle - g.startAngle, 1e-9)
    }

    @Test
    fun `圈钮完全浮在栏外时退化成半圆而不是画崩`() {
        // 极端参数（钮只露一半以上、圆心正好在沿上）也要有定义，不能出 NaN / 负宽度
        val onEdge = NavBarNotch.geometry(
            buttonDiameter = 58.0,
            buttonTopAboveEdge = 29.0,
            gap = 5.0,
            fillet = 0.0,
        )
        assertEquals(0.0, onEdge.centerY, 0.001)
        assertEquals(34.0, onEdge.halfWidth, 0.001)   // 半圆
        assertEquals(34.0, onEdge.depth, 0.001)
        assertEquals(0.0, onEdge.startAngle, 0.001)
        // 带过渡时同样的退化参数也不能出现 NaN / 负半径
        val onEdgeFillet = NavBarNotch.geometry(
            buttonDiameter = 58.0,
            buttonTopAboveEdge = 29.0,
            gap = 5.0,
            fillet = 6.0,
        )
        assertTrue("退化成 NaN/负数了", onEdgeFillet.filletDx.isFinite() && onEdgeFillet.filletDx > 0.0)
        assertTrue(onEdgeFillet.filletSweepAngle > 0.0 && onEdgeFillet.filletSweepAngle < 180.0)
    }

    @Test
    fun `钮几乎全压进栏里时不会算出虚数宽度`() {
        // centerY > r 的极端情况（钮很大、几乎不露头）：halfWidth 必须是 0 而不是负数/NaN
        val buried = NavBarNotch.geometry(
            buttonDiameter = 58.0,
            buttonTopAboveEdge = 0.0,
            gap = 0.0,
            fillet = 0.0,
        )
        assertEquals(29.0, buried.centerY, 0.001)
        assertEquals(0.0, buried.halfWidth, 0.001)
        assertTrue(buried.depth.isFinite())
        // 带过渡时：halfWidth = 0（大圆没切到上沿）→ 形状层会跳过整个缺口，只画平直上沿。
        // 几何本身仍要有定义（不许 NaN），否则夹取与缩放都会跟着变成 NaN。
        val buriedFillet = NavBarNotch.geometry(
            buttonDiameter = 58.0,
            buttonTopAboveEdge = 0.0,
            gap = 0.0,
            fillet = 6.0,
        )
        assertEquals(0.0, buriedFillet.halfWidth, 0.001)
        assertTrue(
            "NaN/负数：filletDx=${buriedFillet.filletDx} sweep=${buriedFillet.filletSweepAngle}",
            buriedFillet.filletDx.isFinite() && buriedFillet.filletSweepAngle.isFinite(),
        )
    }

    // ---- 造型判据（跟着真实常量走：用户几轮反馈都是冲这几个数来的） ----

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

    @Test
    fun `圆滑过渡够看得出来、又没大到啃掉旁边的 Tab`() {
        // 下限：过渡半径 = 圆心深度（真机 17dp）。它同时是"看得出来"和"没留下喙"的下限——
        // 再小切点就落到大圆上半圈去了（见「喙」那条测试）。
        assertTrue("过渡半径 ${real.filletRadius}dp 太小（要 ≥8dp）", real.filletRadius >= 8.0)
        // 上限：5 个槽各 72dp（360dp 宽的屏），左右两个 Tab 的图标内沿在 ±60dp。
        // 上沿开口半宽超过它，缺口就缺到图标脸上了。
        assertTrue(
            "过渡把上沿开口撑到 ${real.filletDx}dp（>58dp 会啃到左右两个 Tab 的图标）",
            real.filletDx < 58.0,
        )
        // 真实参数下确实相切（发上去的就是这一组）
        val dc = sqrt(real.filletDx * real.filletDx + (real.centerY - real.filletRadius) * (real.centerY - real.filletRadius))
        assertEquals(real.radius + real.filletRadius, dc, 1e-6)
    }

    @Test
    fun `过渡的切点落在栏内（曲线在栏上沿之下完成）`() {
        // 切点高度 = f + f·sin(切点角)：必须 >0（在沿下）且 < 最深点。
        // 切点角取 0（= 大圆最宽处）时切点高度正好等于圆角半径 = 圆心深度。
        val ty = real.filletRadius + real.filletRadius * sin(Math.toRadians(-real.startAngle))
        assertTrue("切点跑到栏上沿之上（$ty dp）", ty > 0.0)
        assertTrue("切点比缺口底还深（$ty dp）", ty < real.depth)
        assertEquals("切点应当正好在大圆最宽处（与大圆圆心等高）", real.centerY, ty, 1e-9)
        // 切点角只能是 0（最宽处）到 90°（正下方）之间；0 表示旧的方角整块被抹掉
        assertTrue("切点角越界：${-real.startAngle}", -real.startAngle >= 0.0 && -real.startAngle < 90.0)
    }

    @Test
    fun `右圆角弧的起点角 = 180 度 + 大弧终点角（两侧对称）`() {
        // 形状层直接用这个角画第二条圆角弧；它推错了就会出现"右边一个尖角"
        // （arcTo 找不到起点时会补一条弦，比尖角更难看）
        assertEquals(180.0 + g.startAngle, g.rightFilletStartAngle, 1e-9)
        assertTrue(
            "右圆角起点角必须落在下半圈方向（90°, 270°）：${g.rightFilletStartAngle}",
            g.rightFilletStartAngle > 90.0 && g.rightFilletStartAngle < 270.0,
        )
    }

    @Test
    fun `切点角就是圆角圆心到大圆圆心的方向`() {
        // 相切的判定用得上：方向角 = atan2(centerY − f, filletDx)
        assertEquals(
            Math.toDegrees(atan2(real.centerY - real.filletRadius, real.filletDx)),
            -real.startAngle,
            1e-9,
        )
    }
}
