package com.tapmoay.sorders.core

import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 「手机在哪」这个坐标来源的单测。
 *
 * 为什么必须测：高德定位失败时**照常回调**，只是给 `lat=0.0, lng=0.0`（见 AmapLocationManager）。
 * 不校验就把它当成真实坐标去算日落，会得出一份完全错误的日落时间，而且**没有任何报错**——
 * 界面照常显示"按手机定位"，只是切换时刻离谱（0,0 在几内亚湾，日落时刻和国内差 8 小时）。
 */
class SunLocationTest {

    @After
    fun tearDown() {
        // 这是个全局对象，用例之间必须清干净（否则"有没有坐标"会串味）
        SunLocation.clear()
    }

    @Test
    fun `定位失败的哨兵值 0_0 不能被当成有效坐标`() {
        assertFalse(SunLocation.isPlausible(0.0, 0.0))
        // 误差范围内也算哨兵（±0.01° ≈ 1 公里）
        assertFalse(SunLocation.isPlausible(0.005, -0.004))
        assertFalse("失败值不该被收下", SunLocation.update(0.0, 0.0))
        assertNull(SunLocation.coords())
        assertFalse(SunLocation.hasFix())
    }

    @Test
    fun `空值_NAN_越界都不收`() {
        assertFalse(SunLocation.isPlausible(null, 120.0))
        assertFalse(SunLocation.isPlausible(30.0, null))
        assertFalse(SunLocation.isPlausible(Double.NaN, 120.0))
        assertFalse(SunLocation.isPlausible(30.0, Double.POSITIVE_INFINITY))
        assertFalse("纬度不会超过 90", SunLocation.isPlausible(91.0, 120.0))
        assertFalse("经度不会超过 180", SunLocation.isPlausible(30.0, 181.0))
    }

    @Test
    fun `国内正常坐标收下并能读回`() {
        assertTrue(SunLocation.update(39.9, 116.4))
        assertEquals(39.9 to 116.4, SunLocation.coords())
        assertTrue(SunLocation.hasFix())
        SunLocation.clear()
        assertNull(SunLocation.coords())
    }

    @Test
    fun `一次失败不该把上一次可用坐标清掉`() {
        // 定位是"偶发成功"的：失败一次就清空的话，用户会看到"刚才还准、现在不准了"，
        // 而且下一次成功之前会一直按估算走。
        assertTrue(SunLocation.update(43.8, 87.6))
        assertFalse(SunLocation.update(0.0, 0.0))
        assertEquals("上一次可用坐标要留着", 43.8 to 87.6, SunLocation.coords())
    }

    @Test
    fun `有坐标时日落按真实经纬度算（和时区估算不是一个结果）`() {
        val zoneOnly = SunClock.stateAt(now = 1_789_000_000_000L)
        val withFix = SunClock.stateAt(now = 1_789_000_000_000L, lat = 43.8, lng = 87.6)
        // 两种算法的结果必须**能被区分**：否则"按定位"这件事没有任何效果
        assertTrue(
            "估算与定位的切换时刻应该不同",
            zoneOnly.nextSwitchAt != withFix.nextSwitchAt || zoneOnly.dark != withFix.dark,
        )
    }
}
