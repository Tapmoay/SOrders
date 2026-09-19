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
import kotlin.math.acos
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

    /**
     * 凹口几何。
     *
     * @param buttonDiameter    圆钮直径
     * @param buttonTopAboveEdge 圆钮**上沿**高出导航栏上沿多少（= 凸出高度）
     * @param gap               凹口与圆钮之间的缝
     */
    fun geometry(buttonDiameter: Number, buttonTopAboveEdge: Number, gap: Number): NotchGeometry {
        val r = buttonDiameter.toDouble() / 2 + gap.toDouble()
        val radius = buttonDiameter.toDouble() / 2
        // 圆心在栏上沿下方：上沿之上只有 protrude 那一段，剩下的是压在栏里的
        val centerY = radius - buttonTopAboveEdge.toDouble()
        val dy = kotlin.math.abs(centerY)
        val halfWidth = if (r > dy) sqrt(r * r - dy * dy) else 0.0
        val depth = centerY + r
        // 弧角（Android：0°=三点方向，顺时针为正；y 向下，所以圆心上方是负角）
        val rightAngle = Math.toDegrees(kotlin.math.atan2(-centerY, halfWidth.coerceAtLeast(1e-6)))
        return NotchGeometry(
            radius = r,
            halfWidth = halfWidth,
            depth = depth,
            centerY = centerY,
            startAngle = rightAngle,
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
 * [startAngle] = **右**交点相对圆心的角度（负数，因为交点在圆心上方）；
 * [sweepAngle] = 从**左**交点逆时针扫回右交点经过的角（负值，中途一定经过 90°=最深点）。
 */
data class NotchGeometry(
    val radius: Double,
    val halfWidth: Double,
    val depth: Double,
    val centerY: Double,
    val startAngle: Double,
) {
    /** 左交点角度（圆心坐标系，y 向下） */
    val leftAngle: Double get() = 180.0 - startAngle

    /** 从**左**交点出发、逆时针扫到右交点（负值） */
    val sweepAngle: Double get() = startAngle - leftAngle
}

/**
 * 带凹口的导航栏形状：[NavBarNotch.CornerRadius] 圆角 + 顶部中间一个半圆缺口。
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
        // 防御：缺口不能把导航栏咬穿（栏高被改小、圆钮被改大时才会发生）。
        // 正常参数下 scale = 1f：58dp 的钮 + 5dp 缝 → 缺口深 47dp，栏高 80dp。
        val scale = if (g.depth > size.height) size.height / g.depth else 1.0
        val r = (g.radius * scale).toFloat()
        val cy = (g.centerY * scale).toFloat()
        val half = (g.halfWidth * scale).toFloat().coerceAtMost(size.width / 2f - corner)

        val path = Path().apply {
            moveTo(0f, size.height)
            lineTo(0f, corner)
            // 左上外角
            quadraticBezierTo(0f, 0f, corner, 0f)
            // 到凹口左缘
            lineTo(cx - half, 0f)
            if (half > 0f) {
                // 凹口弧：**从左边交点出发、逆时针（负角）扫回右边交点**，中途经过 90°（最深点）。
                // ⚠️ 不能从右边交点顺时针画：当前笔尖在左交点，而弧的起点在右交点时，
                //    arcTo 会先补一条**直线**把两点连起来——那条弦会横在缺口上，看起来像被一块板盖住。
                arcTo(
                    rect = Rect(left = cx - r, top = cy - r, right = cx + r, bottom = cy + r),
                    startAngleDegrees = g.leftAngle.toFloat(),
                    sweepAngleDegrees = g.sweepAngle.toFloat(),
                    forceMoveTo = false,
                )
            }
            lineTo(cx + half, 0f)
            // 右上外角
            lineTo(size.width - corner, 0f)
            quadraticBezierTo(size.width, 0f, size.width, corner)
            lineTo(size.width, size.height)
            close()
        }
        return Outline.Generic(path)
    }
}
