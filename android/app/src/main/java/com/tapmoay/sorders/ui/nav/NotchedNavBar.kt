package com.tapmoay.sorders.ui.nav

import androidx.compose.ui.geometry.Rect
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Outline
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.Shape
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.LayoutDirection
import androidx.compose.ui.unit.dp
import kotlin.math.abs
import kotlin.math.atan2
import kotlin.math.sqrt

/**
 * 底部导航栏中间那个**凹口**（圆钮不是浮在栏上，而是坐在栏里"凹"下去的一块）。
 *
 * 用户拿星巴克 App 的截图提的要求：「这个导航栏要改一下，那个圆圈里面要凹一下，参考这个样式」。
 * 参照样式里，白色导航条的上沿在圆钮位置**向内凹进一个半圆**，圆钮正好嵌在凹口里——
 * 比"圆钮直接压在平直上沿上"更像一个整体，圆钮也不会看起来像贴上去的。
 *
 * ### 几何（这里全是"旋钮"，别凭感觉写）
 * 圆钮不是"整个浮在栏外面"，而是**上沿往上露 [AiNavButton.Protrude]，其余部分压在栏里**：
 * 圆心在栏上沿**下方** `半径 − Protrude` 处（58dp 的钮、露出 16dp → 圆心在沿下 13dp）。
 * 凹口就是以**这个圆心**为心、半径 = 钮半径 + 缝 的圆弧，从上沿切下去。
 *
 * ⚠️ 第一版把凹口的圆心放在"上沿之上 Protrude"，切出来只有 18dp 深的浅坑，
 *    而且几乎整块都被圆钮自己盖住 —— 真机截图量出来：栏上沿在缺口内外都是同一个 y，
 *    等于白做（用户要的"凹一下"看不见）。判定方法是量像素，不是看着像。
 *
 * ### 两侧的圆滑过渡（[Fillet]，2026-09-20 加）
 * 用户看真机截图提的第二个问题：「它那个圆圈图标它是被 2 个矩形像是框在一起的…
 * 就是它那个角是尖尖，把它做一个曲线过渡」。
 * 原因是几何本身：大圆是从上沿**斜着**切下去的（真机参数下切点处的切线约 70°），
 * 所以上沿与大圆之间留下两个尖角，看着像两个方块夹住圆钮。修法是加一段
 * **同时与上沿和大圆相切**的圆弧把这两个角换掉（圆角半径由相切条件定死 = 圆心深度，
 * 见 [NavBarNotch.geometry] 里的推导——取小了会剩下一小块"喙"）。
 */
object NavBarNotch {

    /**
     * 凹口与圆钮之间的可见缝隙。
     *
     * 5dp → 9dp（用户 2026-09-17 看真机截图反馈「这个太窄了，就是它紧贴着这个按钮，
     * 不要紧贴，稍微扩大一点」）。缝隙是这道造型里唯一"松不松"的旋钮：
     * 太小就成"被切了一刀"，太大圆钮又会显得没坐进去。
     */
    val Gap = 9.dp

    /** 导航栏上沿两个外角的圆角（参照图里那块白是有圆角的） */
    val CornerRadius = 18.dp

    // 过渡圆角的半径**没有常量**：它由两个相切条件解出来（= 圆心深度，真机 17dp）。
    // 写成常量就等于把"切点落在哪儿"变成一个可以改错的旋钮——先试过 6dp，真机上会
    // 剩下一小块"喙"加一条缝。推导与取舍写在 [geometry] 里。

    /**
     * 凹口几何。
     *
     * @param buttonDiameter    圆钮直径
     * @param buttonTopAboveEdge 圆钮**上沿**高出导航栏上沿多少（= 凸出高度）
     * @param gap               凹口与圆钮之间的缝
     * @param fillet            两侧圆滑过渡的圆角半径（px）。**默认 null = 用唯一正确的那个值**
     *                          （= 圆心深度，见下）；只有在做对照实验时才显式传
     *                          `0.0`（退回尖角，加过渡之前的样子）。
     */
    fun geometry(
        buttonDiameter: Number,
        buttonTopAboveEdge: Number,
        gap: Number,
        fillet: Number? = null,
    ): NotchGeometry {
        val r = buttonDiameter.toDouble() / 2 + gap.toDouble()
        val radius = buttonDiameter.toDouble() / 2
        // 圆心在栏上沿下方：上沿之上只有 protrude 那一段，剩下的是压在栏里的
        val centerY = radius - buttonTopAboveEdge.toDouble()
        val dy = abs(centerY)
        val halfWidth = if (r > dy) sqrt(r * r - dy * dy) else 0.0
        val depth = centerY + r

        // ---- 两侧的圆滑过渡 ----
        // 圆角圆（半径 f、圆心 F）必须**同时**与上沿和大圆相切，少切一个那边就还是尖角：
        //   与上沿（y=0）相切 ⇒ 圆心在沿下 f 处，切点 (xf, 0) 处切线水平；
        //   与大圆相切       ⇒ 两圆心距离 = r + f（外切，圆角在材料这一侧）。
        //   ⇒ xf² + (centerY − f)² = (r + f)²
        //   ⇒ xf² = (r² − centerY²) + 2f(r + centerY) = halfWidth² + 2f(r + centerY)
        //
        // ⚠️ 这条式子有个**必然的后果**：xf > halfWidth —— 过渡把上沿的开口撑宽了。
        //    "过渡了、但开口一点不变宽"在几何上不存在（除非 f = 0）。
        //    撑宽的那几 dp 正是原来尖角所在的位置，所以看着是"角被抹圆了"而不是"缺口变大了"。
        //
        // ⚠️⚠️ 两个相切条件还把**切点在大圆上的位置**和 f 锁成了一一对应
        //    （切点相对大圆最宽处的角 γ：sin γ = (centerY − f) / (r + f)）：
        //      f < centerY ⇒ γ > 0 ⇒ 切点在大圆**上半圈** ⇒ 大圆那一段边界仍留在材料里，
        //                            变成一小块薄"喙"外加一条缝（f=6dp 时喙宽 1.2dp）；
        //      f = centerY ⇒ γ = 0 ⇒ 切点正好在大圆**最宽处** ⇒ 那块料整块消失。
        //    所以默认取 f = centerY（真机 = 钮半径 − 凸出 = 17dp，圆心与大圆圆心等高），
        //    过渡就干净地等于"两个四分之一圆角 + 大圆的下半圈"，
        //    上沿开口半宽顺理成章 = 半径 + 缝 + 圆心深度（38 + 17 = 55dp）。
        val f = fillet?.toDouble() ?: centerY
        val filletDx = sqrt(halfWidth * halfWidth + 2 * f * (r + centerY))
        // 切点方向（圆角圆心 → 大圆圆心）；切点在这条连心线上、距圆角圆心 f
        val toCenterDeg = Math.toDegrees(atan2(centerY - f, filletDx))
        // 圆角弧：从顶点（270° = 正上方）顺时针扫到切点
        val filletSweep = 90.0 + toCenterDeg
        // 大圆弧的起点因此从"大圆与上沿的交点"换成**左切点**（180° + 切点角），
        // 终点是同侧的镜像 = 右切点（−切点角）
        val startAngle = -toCenterDeg
        return NotchGeometry(
            radius = r,
            halfWidth = halfWidth,
            depth = depth,
            centerY = centerY,
            startAngle = startAngle,
            filletRadius = f,
            filletDx = filletDx,
            filletSweepAngle = filletSweep,
        )
    }

    /** 用真实的圆钮尺寸算一次（[AiNavButton.Size] / [AiNavButton.Protrude]） */
    fun geometryForButton(density: Density): NotchGeometry = with(density) {
        geometry(
            buttonDiameter = AiNavButton.Size.toPx(),
            buttonTopAboveEdge = AiNavButton.Protrude.toPx(),
            gap = Gap.toPx(),
        )
    }
}

/**
 * 凹口几何（px）。
 *
 * [startAngle] = **右**切点相对大圆圆心的角度（负数，因为切点在圆心上方）；
 * [sweepAngle] = 从**左**切点逆时针扫回右切点经过的角（负值，中途一定经过 90°=最深点）。
 *
 * 2026-09-20 起这两个角描述的是**大圆与两侧圆角的切点**，不再是"大圆与上沿的交点"——
 * 后者现在是 [halfWidth]（尖角时代的位置，判据仍在用），上沿上的实际开口半宽是 [filletDx]。
 */
data class NotchGeometry(
    val radius: Double,
    val halfWidth: Double,
    val depth: Double,
    val centerY: Double,
    val startAngle: Double,
    /** 两侧圆滑过渡的圆角半径（0 = 不做过渡，退回用户说的"那个角是尖尖"） */
    val filletRadius: Double,
    /** 圆角与上沿的切点距中线多远 = 缺口在栏上沿上的实际半宽 */
    val filletDx: Double,
    /** 圆角弧的扫角（正值：从顶点顺时针扫到大圆上的切点） */
    val filletSweepAngle: Double,
) {
    /** 左切点角度（圆心坐标系，y 向下） */
    val leftAngle: Double get() = 180.0 - startAngle

    /** 从**左**切点出发、逆时针扫到右切点（负值） */
    val sweepAngle: Double get() = startAngle - leftAngle

    /** 右圆角弧的起点角度（相对**右圆角圆心**：与大圆的切点那边） */
    val rightFilletStartAngle: Double get() = 180.0 + startAngle
}

/**
 * 带凹口的导航栏形状：[NavBarNotch.CornerRadius] 圆角 + 顶部中间一个半圆缺口
 * （缺口两侧各一段与上沿、大圆双相切的圆角，见 [NavBarNotch.Fillet]）。
 *
 * 为什么做成 [Shape] 而不是自己画一张图：Compose 的 `background` / `shadow` 都吃 Shape，
 * 一套几何同时管住底色、阴影和裁剪，不会出现"底色凹了但阴影还是方的"这种穿帮。
 */
class NotchedBarShape(
    private val cornerRadius: Dp = NavBarNotch.CornerRadius,
    private val notch: (Density) -> NotchGeometry = { NavBarNotch.geometryForButton(it) },
) : Shape {

    override fun createOutline(size: Size, layoutDirection: LayoutDirection, density: Density): Outline {
        val g = notch(density)
        val corner = with(density) { cornerRadius.toPx() }.coerceAtMost(size.minDimension / 2f)
        val cx = size.width / 2f

        // 防御：缺口不能把导航栏咬穿，也不能宽过"两个外角圆角之间那段上沿"
        // （栏高被改小、圆钮被改大时才会发生；正常参数下 scale = 1f）。
        // ⚠️ 三个尺寸**必须同比例缩放**：半径、圆心深度、圆角半径各自夹取的话，
        //    圆角就不再与大圆相切——差一点点就是一条肉眼可见的缝或者一个尖角。
        val availHalf = size.width / 2f - corner
        val fitHeight = if (g.depth > 0) size.height / g.depth else 1.0
        val fitWidth = if (g.filletDx > 0) availHalf / g.filletDx else 1.0
        val scale = minOf(1.0, fitHeight, fitWidth).toFloat()

        val r = (g.radius * scale).toFloat()
        val cy = (g.centerY * scale).toFloat()
        val fx = (g.filletDx * scale).toFloat()
        val f = (g.filletRadius * scale).toFloat()
        // 大圆真的切到上沿了吗（圆心压在沿上/更下时 halfWidth = 0：钮本身就把那块盖住了）
        val cut = g.halfWidth > 0.0 && fx > 0f

        val path = Path().apply {
            moveTo(0f, size.height)
            lineTo(0f, corner)
            // 左上外角
            quadraticBezierTo(0f, 0f, corner, 0f)
            // 到凹口左圆角与上沿的切点（切点处切线水平 ⇒ 这里**没有角**）
            lineTo(cx - fx, 0f)
            if (cut) {
                // 左圆角弧：从顶点（270°=正上方）**顺时针**扫到大圆上的切点。
                // ⚠️ 不能反着扫（负扫角）：arcTo 会先补一条**直线**把两点连起来，
                //    那条线横在缺口上，看起来像被一块板盖住。
                arcTo(
                    rect = Rect(left = cx - fx - f, top = 0f, right = cx - fx + f, bottom = 2f * f),
                    startAngleDegrees = 270f,
                    sweepAngleDegrees = g.filletSweepAngle.toFloat(),
                    forceMoveTo = false,
                )
                // 大缺口弧：**从左切点出发、逆时针（负角）扫回右切点**，中途经过 90°（最深点）。
                arcTo(
                    rect = Rect(left = cx - r, top = cy - r, right = cx + r, bottom = cy + r),
                    startAngleDegrees = g.leftAngle.toFloat(),
                    sweepAngleDegrees = g.sweepAngle.toFloat(),
                    forceMoveTo = false,
                )
                // 右圆角弧：从大圆上的切点顺时针扫回顶点（270°），对称的另一半
                arcTo(
                    rect = Rect(left = cx + fx - f, top = 0f, right = cx + fx + f, bottom = 2f * f),
                    startAngleDegrees = g.rightFilletStartAngle.toFloat(),
                    sweepAngleDegrees = g.filletSweepAngle.toFloat(),
                    forceMoveTo = false,
                )
            }
            // 右圆角切点 → 右上外角
            lineTo(cx + fx, 0f)
            lineTo(size.width - corner, 0f)
            quadraticBezierTo(size.width, 0f, size.width, corner)
            lineTo(size.width, size.height)
            close()
        }
        return Outline.Generic(path)
    }
}
