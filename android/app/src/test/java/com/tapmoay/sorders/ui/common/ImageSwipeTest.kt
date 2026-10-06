package com.tapmoay.sorders.ui.common

import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * 「看大图横滑翻页」的判据（CHG-0070 / 台账 L-37）。
 *
 * 手势那一层要真手指才验得了（真机取证见 `shots/chg0070_*_5554.png`），但"够不够翻、往哪翻、
 * 到头了没有"是纯算术 —— 阈值、首末张、单张、还没量到宽，全在这里钉死。
 * 1000px 宽 × 18% = 180px 这条线是这份用例的基准。
 */
class ImageSwipeTest {

    @Test
    fun `向左拖过阈值就是下一张`() {
        assertEquals(1, swipePageStep(accumX = -181f, boxWidth = 1000, atFirst = false, atLast = false))
    }

    @Test
    fun `向右拖过阈值就是上一张`() {
        assertEquals(-1, swipePageStep(accumX = 181f, boxWidth = 1000, atFirst = false, atLast = false))
    }

    @Test
    fun `位移不过阈值就不翻页（手抖或只是想挪一下）`() {
        assertEquals(0, swipePageStep(accumX = -179f, boxWidth = 1000, atFirst = false, atLast = false))
        assertEquals(0, swipePageStep(accumX = 179f, boxWidth = 1000, atFirst = false, atLast = false))
    }

    @Test
    fun `刚好等于阈值也算翻页`() {
        assertEquals(1, swipePageStep(accumX = -180f, boxWidth = 1000, atFirst = false, atLast = false))
    }

    @Test
    fun `第一张往右停在原地（不环绕）`() {
        assertEquals(0, swipePageStep(accumX = 400f, boxWidth = 1000, atFirst = true, atLast = false))
    }

    @Test
    fun `最后一张往左停在原地（不环绕）`() {
        assertEquals(0, swipePageStep(accumX = -400f, boxWidth = 1000, atFirst = false, atLast = true))
    }

    @Test
    fun `第一张往左还是能翻到下一张`() {
        assertEquals(1, swipePageStep(accumX = -400f, boxWidth = 1000, atFirst = true, atLast = false))
    }

    @Test
    fun `只有一张时两个方向都不翻（它同时是第一张也是最后一张）`() {
        assertEquals(0, swipePageStep(accumX = -400f, boxWidth = 1000, atFirst = true, atLast = true))
        assertEquals(0, swipePageStep(accumX = 400f, boxWidth = 1000, atFirst = true, atLast = true))
    }

    @Test
    fun `还没量到宽度时不翻（宁可不动，也不要翻到一张没人要的图）`() {
        assertEquals(0, swipePageStep(accumX = -900f, boxWidth = 0, atFirst = false, atLast = false))
    }

    @Test
    fun `没量到宽度时连 NaN 也不会翻`() {
        assertEquals(0, swipePageStep(accumX = Float.NaN, boxWidth = 1000, atFirst = false, atLast = false))
    }
}
