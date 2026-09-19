package com.tapmoay.sorders.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/**
 * 系统定位兜底：挑坐标的判据（纯函数）。
 *
 * 为什么要测它：这一条路上任何一次"挑错坐标"都不会报错——手机在郑州、算的是北京的日落，
 * 用户只会看到"今天天黑得有点晚"，而且**下一次也不会好**（缓存坐标一直都在）。
 */
class DeviceLocationTest {

    private val now = 1_700_000_000_000L

    @Test
    fun `两条都新鲜时取新的一条`() {
        val old = LocationFix(30.0, 114.0, now - 60_000, 10f)
        val fresh = LocationFix(39.9, 116.4, now - 1_000, 50f)
        assertEquals(fresh, DeviceLocation.pickBest(listOf(old, fresh), now))
    }

    @Test
    fun `太旧的缓存不要（手机可能几天没开过定位）`() {
        val stale = LocationFix(39.9, 116.4, now - DeviceLocation.MAX_AGE_MS - 1, 5f)
        assertNull(DeviceLocation.pickBest(listOf(stale), now))
    }

    @Test
    fun `高德那种 (0,0) 失败哨兵要挡掉`() {
        val bogus = LocationFix(0.0, 0.0, now, 0f)
        assertNull(DeviceLocation.pickBest(listOf(bogus), now))
    }

    @Test
    fun `一样新的时候取更准的那条`() {
        val coarse = LocationFix(39.0, 116.0, now, 2000f)
        val fine = LocationFix(39.9, 116.4, now, 8f)
        assertEquals(fine, DeviceLocation.pickBest(listOf(coarse, fine), now))
    }

    @Test
    fun `没有候选就返回空_不许瞎猜`() {
        assertNull(DeviceLocation.pickBest(emptyList(), now))
    }

    @Test
    fun `时间未知的坐标能用_但排在有时间之后`() {
        val unknown = LocationFix(39.9, 116.4, 0, 1f)
        val known = LocationFix(30.0, 114.0, now - 120_000, 100f)
        assertEquals(known, DeviceLocation.pickBest(listOf(unknown, known), now))
        assertEquals(unknown, DeviceLocation.pickBest(listOf(unknown), now))
    }
}
