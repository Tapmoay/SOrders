package com.tapmoay.sorders.ui.theme

import kotlin.math.abs
import kotlin.math.cbrt
import kotlin.math.pow
import kotlin.math.sqrt

/**
 * 一套配色"看着像不像一套"的两个量（CHG-0102）。
 *
 * 用户 2026-10-10 的说法（ref `m04527`，逐字）：
 * 「我们现在一看好看的话，它所有的呃比如说我们一般评价一个画它比较偏低，
 *   饱和但是整体的色调又统一且看的舒适是这样子的这样，它又是怎么做到的呢？」
 *
 * 答案不是"饱和度统一"，是这两条：
 * 1. **明度 L\* 挤在一条窄带里** —— 这是"色调统一"的真正来源。
 *    CHG-0101 那套的 L\* 极差是 **25.6**，用户看着"太灰"；CHG-0091 那套是 **51.8**，
 *    看着"太亮、刺眼"。两头都不是"统一"。
 * 2. **每一格的彩度都不能掉到"没人当它是颜色"那一档** —— CHG-0101 那套里
 *    「账户管理」的 C\* 只有 **8.1**（那个色相在那个明度下能给到 72，只用了 11%），
 *    而同屏的「消息中心」有 **58.4** —— 同屏差 7 倍，看着就是"有的灰有的艳"。
 *
 * ⛔ 这两个函数只做算式，不读 `Modules` 也不读 `Color`：判据要能在**任何一组颜色**上跑，
 *    这样"换色的人"跑一次就知道自己把哪一格推出去了。
 */

/** CIE L\*（0~100）：这个颜色"有多亮"。 */
internal fun labLightness(argb: Long): Double = lab(argb).first

/** CIE C\*（0~~130）：这个颜色"离灰轴有多远"。 */
internal fun labChroma(argb: Long): Double = lab(argb).second

/** 一组颜色里最亮与最暗差多少 L\*。越小越"像一套"。 */
internal fun lightnessSpread(colors: List<Long>): Double {
    if (colors.isEmpty()) return 0.0
    val ls = colors.map { labLightness(it) }
    return ls.max() - ls.min()
}

/** 一组颜色里最没颜色的那一格差多少 C\*。 */
internal fun weakestChroma(colors: List<Long>): Double {
    if (colors.isEmpty()) return 0.0
    return colors.minOf { labChroma(it) }
}

/** 那个"最没颜色"的一格是谁（报错信息里点名用）。 */
internal fun weakestChromaLabel(pairs: List<Pair<String, Long>>): String {
    if (pairs.isEmpty()) return ""
    val w = pairs.minBy { labChroma(it.second) }
    return "%s C*=%.1f".format(w.first, labChroma(w.second))
}

private fun lab(argb: Long): Pair<Double, Double> {
    fun lin(v: Long): Double {
        val t = (v and 0xFF) / 255.0
        return if (t > 0.04045) ((t + 0.055) / 1.055).pow(2.4) else t / 12.92
    }

    val r = lin(argb shr 16)
    val g = lin(argb shr 8)
    val b = lin(argb)
    val x = (0.4124564 * r + 0.3575761 * g + 0.1804375 * b) / 0.95047
    val y = 0.2126729 * r + 0.7151522 * g + 0.0721750 * b
    val z = (0.0193339 * r + 0.1191920 * g + 0.9503041 * b) / 1.08883

    fun f(t: Double) = if (t > 0.008856) cbrt(t) else (7.787 * t + 16.0 / 116.0)
    val fx = f(x)
    val fy = f(y)
    val fz = f(z)
    val l = 116.0 * fy - 16.0
    val a = 500.0 * (fx - fy)
    val bb = 200.0 * (fy - fz)
    return l to sqrt(a * a + bb * bb)
}

/** 两个 ARGB 的 RGB 欧氏距离（口径与 `ModulesEntryTest.colorGap` 逐字相同）。 */
internal fun argbGap(a: Long, b: Long): Double {
    fun ch(c: Long, sh: Int) = ((c shr sh) and 0xFF).toDouble()
    val dr = ch(a, 16) - ch(b, 16)
    val dg = ch(a, 8) - ch(b, 8)
    val db = ch(a, 0) - ch(b, 0)
    return sqrt(dr * dr + dg * dg + db * db)
}

/** 一组颜色两两之间最近的那一对差多少（同屏撞色就靠它）。 */
internal fun closestPair(pairs: List<Pair<String, Long>>): Triple<String, String, Double>? {
    var best: Triple<String, String, Double>? = null
    for (i in pairs.indices) {
        for (j in i + 1 until pairs.size) {
            val d = argbGap(pairs[i].second, pairs[j].second)
            if (best == null || d < best!!.third) best = Triple(pairs[i].first, pairs[j].first, d)
        }
    }
    return best
}

/** 这个颜色离灰轴的相对距离够不够（0~1，1 = 那个色相在那个明度下能给到的最艳）。 */
internal fun relativeChroma(argb: Long, maxChroma: Double): Double {
    if (maxChroma <= 0.0) return 0.0
    return labChroma(argb) / maxChroma
}

/** 两个颜色在色相上差多少度（0~180）。 */
internal fun hueDistance(argbA: Long, argbB: Long): Double {
    val d = abs(hueOf(argbA) - hueOf(argbB)) % 360.0
    return if (d > 180.0) 360.0 - d else d
}

private fun hueOf(argb: Long): Double {
    fun lin(v: Long): Double {
        val t = (v and 0xFF) / 255.0
        return if (t > 0.04045) ((t + 0.055) / 1.055).pow(2.4) else t / 12.92
    }

    val r = lin(argb shr 16)
    val g = lin(argb shr 8)
    val b = lin(argb)
    val x = (0.4124564 * r + 0.3575761 * g + 0.1804375 * b) / 0.95047
    val y = 0.2126729 * r + 0.7151522 * g + 0.0721750 * b
    val z = (0.0193339 * r + 0.1191920 * g + 0.9503041 * b) / 1.08883

    fun f(t: Double) = if (t > 0.008856) cbrt(t) else (7.787 * t + 16.0 / 116.0)
    val a = 500.0 * (f(x) - f(y))
    val bb = 200.0 * (f(y) - f(z))
    return (Math.toDegrees(kotlin.math.atan2(bb, a)) + 360.0) % 360.0
}
