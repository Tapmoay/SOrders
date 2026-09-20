package com.tapmoay.sorders.ui.common

import com.tapmoay.sorders.ui.theme.ChartPalette
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import kotlin.math.sqrt

/**
 * 扇形图的**纯计算**（角度、占比）与图表配色的可分辨性。
 *
 * 为什么这两件事一起测：它们都只有一条判据 —— "图能不能被读懂"。
 * 角度算错会在环上留缝/重叠（看不出是 bug，只觉得"这图画得怪"）；
 * 配色太近则两块分不开，只能靠图例反查，图就白画了。
 */
class PieChartMathTest {

    @Test
    fun `角度加起来正好是一个整圆`() {
        val a = pieAngles(listOf(1f, 2f, 3f, 4f))
        assertEquals(4, a.size)
        assertEquals(0f, a.first().first, 1e-4f)
        assertEquals(360f, a.sumOf { it.second.toDouble() }.toFloat(), 1e-3f)
        // 相邻块首尾相接（不重叠也不留缝）
        a.zipWithNext().forEach { (p, n) -> assertEquals(p.first + p.second, n.first, 1e-4f) }
    }

    @Test
    fun `只有一块时就是整圆`() {
        assertEquals(listOf(0f to 360f), pieAngles(listOf(7f)))
    }

    @Test
    fun `全零或空不给角度（调用方画空态，而不是画一个圆假装有钱）`() {
        assertTrue(pieAngles(emptyList()).isEmpty())
        assertTrue(pieAngles(listOf(0f, 0f)).isEmpty())
    }

    @Test
    fun `负数与非法值当 0 处理（角度不能是负的）`() {
        val a = pieAngles(listOf(-5f, 10f, Float.NaN))
        assertEquals(3, a.size)
        assertEquals(0f, a[0].second, 1e-4f)
        assertEquals(360f, a[1].second, 1e-3f)
        assertEquals(0f, a[2].second, 1e-4f)
    }

    @Test
    fun `占比文字：小于 1% 的块也要看得见`() {
        // 明明看得见的小扇形写着 0% 会被读成"数据错了"，所以这一档给一位小数
        assertEquals("0.4%", percentText(0.4f, 100f))
        assertEquals("35%", percentText(35f, 100f))
        assertEquals("99.5%", percentText(99.5f, 100f))
        assertEquals("0%", percentText(1f, 0f))
    }

    @Test
    fun `图表配色的两两距离都够远（相邻两块必须一眼分得开）`() {
        assertTrue("配色表至少要有 6 色（扇形最多 6 块）", ChartPalette.size >= 6)
        ChartPalette.forEachIndexed { i, a ->
            ChartPalette.drop(i + 1).forEach { b ->
                val d = distance(a, b)
                assertTrue("两种配色太接近（距离 $d < 60）：${hex(a)} vs ${hex(b)}", d >= 60.0)
            }
        }
    }

    private fun hex(c: Long) = "#" + c.toString(16).uppercase().takeLast(6)

    private fun distance(a: Long, b: Long): Double {
        val ar = (a shr 16) and 0xFF
        val ag = (a shr 8) and 0xFF
        val ab = a and 0xFF
        val br = (b shr 16) and 0xFF
        val bg = (b shr 8) and 0xFF
        val bb = b and 0xFF
        return sqrt(((ar - br) * (ar - br) + (ag - bg) * (ag - bg) + (ab - bb) * (ab - bb)).toDouble())
    }
}
