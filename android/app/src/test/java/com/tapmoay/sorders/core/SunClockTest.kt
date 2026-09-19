package com.tapmoay.sorders.core

import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 「随日落自动切换夜间模式」的判定单测。
 *
 * 为什么这些断言必须存在：算错的**表现是"半夜亮着 / 中午黑着"**，
 * 而且只在特定日期、特定地区出现——今天在上海试一下是对的，冬至的哈尔滨就错了。
 * 靠人工在真机上是测不全的，所以这一组测试的重点不是"跑通"，而是
 * **把季节、纬度、经度、昼夜边界四个方向各钉一遍**。
 *
 * 锚点值取自公开的天文数据（民用暮光 = 太阳高度角 −6°，北京时间）：
 * 北京 6/21 民用天亮 ≈ 04:13、天黑 ≈ 20:22；12/21 民用天亮 ≈ 07:03、天黑 ≈ 17:23。
 * 这里只按 **±30 分钟** 断言——公式本身是简化式（赤纬 ±0.5°、不查表），
 * 目标不是当天文台，而是"该亮的时候亮、该暗的时候暗"。
 */
class SunClockTest {

    private val cn: ZoneId = ZoneId.of("Asia/Shanghai")
    private val utc: ZoneId = ZoneId.of("UTC")

    private fun ms(y: Int, mo: Int, d: Int, h: Int, mi: Int, zone: ZoneId = cn): Long =
        LocalDate.of(y, mo, d).atTime(h, mi).atZone(zone).toInstant().toEpochMilli()

    private fun hm(minute: Int): String = "%02d:%02d".format(minute / 60, minute % 60)

    private fun day(y: Int, mo: Int, d: Int) = LocalDate.of(y, mo, d)

    // ---------------------------------------------------------------- 方向一：昼夜本身

    @Test
    fun `四个纬度两个至日：凌晨都算夜间、正午都算白天`() {
        // 三亚 / 上海 / 北京 / 哈尔滨 —— 纬度跨度 27°，覆盖中国全境
        val lats = mapOf("三亚" to 18.25, "上海" to 31.2, "北京" to 39.9, "哈尔滨" to 45.75)
        for ((name, lat) in lats) {
            for (d in listOf(day(2026, 6, 21), day(2026, 12, 21))) {
                val night = SunClock.stateAt(ms(d.year, d.monthValue, d.dayOfMonth, 2, 0), cn, lat)
                val noon = SunClock.stateAt(ms(d.year, d.monthValue, d.dayOfMonth, 12, 0), cn, lat)
                assertTrue("$name $d 凌晨 2 点应该是夜间", night.dark)
                assertFalse("$name $d 正午 12 点应该是白天", noon.dark)
            }
        }
    }

    @Test
    fun `夏至的黄昏比冬至晚 2 小时以上、天亮早 2 小时以上`() {
        // 这条是"不许写死 18 点开 6 点关"的正面证据：同一个纬度，两个季节差了两个多小时
        val summer = SunClock.crossings(day(2026, 6, 21), cn, 35.0)
        val winter = SunClock.crossings(day(2026, 12, 21), cn, 35.0)
        val duskGap = summer.duskMinute!! - winter.duskMinute!!
        val dawnGap = winter.dawnMinute!! - summer.dawnMinute!!
        assertTrue(
            "夏至(${hm(summer.duskMinute)}) 应比冬至(${hm(winter.duskMinute)}) 晚 2h 以上天黑",
            duskGap >= 120,
        )
        assertTrue(
            "夏至(${hm(summer.dawnMinute)}) 应比冬至(${hm(winter.dawnMinute)}) 早 2h 以上天亮",
            dawnGap >= 120,
        )
    }

    @Test
    fun `纬度越高，夏至的白天越长`() {
        val harbin = SunClock.crossings(day(2026, 6, 21), cn, 45.75)
        val sanya = SunClock.crossings(day(2026, 6, 21), cn, 18.25)
        val harbinDay = harbin.duskMinute!! - harbin.dawnMinute!!
        val sanyaDay = sanya.duskMinute!! - sanya.dawnMinute!!
        assertTrue(
            "哈尔滨夏至白天(${harbinDay}min) 应比三亚(${sanyaDay}min) 长 2h 以上",
            harbinDay - sanyaDay >= 120,
        )
    }

    @Test
    fun `同一个瞬间，换个时区结论就不同（证明用的是设备时区，不是写死的）`() {
        // 2026-09-17 11:00 UTC = 北京 19:00：北京已经天黑，UTC 那边还是上午
        val t = ms(2026, 9, 17, 11, 0, utc)
        assertTrue("北京 19:00 应该算夜间", SunClock.stateAt(t, cn, 35.0).dark)
        assertFalse("UTC 11:00 应该算白天", SunClock.stateAt(t, utc, 35.0).dark)
    }

    // ---------------------------------------------------------------- 方向二：边界（最容易错的地方）

    @Test
    fun `天亮天黑的前后一分钟，状态正好相反`() {
        val c = SunClock.crossings(day(2026, 9, 17), cn, 35.0)
        val dawnMs = ms(2026, 9, 17, c.dawnMinute!! / 60, c.dawnMinute % 60)
        val duskMs = ms(2026, 9, 17, c.duskMinute!! / 60, c.duskMinute % 60)

        assertTrue("天亮前一分钟还是夜间", SunClock.stateAt(dawnMs - 60_000L, cn, 35.0).dark)
        assertFalse("天亮那一刻就是白天", SunClock.stateAt(dawnMs, cn, 35.0).dark)
        assertFalse("天黑前一分钟还是白天", SunClock.stateAt(duskMs - 60_000L, cn, 35.0).dark)
        assertTrue("天黑那一刻就是夜间", SunClock.stateAt(duskMs, cn, 35.0).dark)
    }

    @Test
    fun `逐分钟扫一整天：暗 就等于 早于天亮 或 不早于天黑`() {
        // 这条是"三段语义"的自洽检查：任何一段边界写反、写漏，扫一遍立刻露出来
        val d = day(2026, 3, 5) // 随便挑一个非至日、非换季的日子
        val c = SunClock.crossings(d, cn, 35.0)
        val dawn = c.dawnMinute!!
        val dusk = c.duskMinute!!
        var darkMinutes = 0
        for (m in 0 until 24 * 60) {
            val dark = SunClock.stateAt(ms(2026, 3, 5, m / 60, m % 60), cn, 35.0).dark
            assertEquals(
                "第 $m 分钟（${hm(m)}）的状态和两次转折对不上",
                m < dawn || m >= dusk,
                dark,
            )
            if (dark) darkMinutes++
        }
        // 顺带钉住量级：三月上旬的夜间大约 12 小时（不可能出现"整天都是夜里"这种错）
        assertTrue("夜间时长不合理：${darkMinutes}min", darkMinutes in (10 * 60)..(14 * 60))
    }

    // ---------------------------------------------------------------- 方向三：下一次什么时候切

    @Test
    fun `下一次切换一定在未来，而且那一刻状态真的会翻过来`() {
        val times = listOf(0 to 30, 6 to 0, 12 to 0, 19 to 0, 23 to 30)
        for ((h, mi) in times) {
            val now = ms(2026, 9, 17, h, mi)
            val state = SunClock.stateAt(now, cn, 35.0)
            assertNotNull("${hm(h * 60 + mi)} 应该算得出下一次切换", state.nextSwitchAt)
            // JUnit 的断言不做智能转换，所以这里显式取一次非空
            val next = state.nextSwitchAt!!
            assertTrue("下一次切换必须在未来（${hm(h * 60 + mi)}）", next > now)
            assertTrue("下一次切换不该超过 24 小时", next - now <= 24 * 3600_000L)
            val flipped = SunClock.stateAt(next, cn, 35.0).dark
            val before = SunClock.stateAt(next - 60_000L, cn, 35.0).dark
            assertEquals("切换那一刻状态应该翻转（${hm(h * 60 + mi)} 那次）", !before, flipped)
        }
    }

    @Test
    fun `入夜之后，下一次切换是明天早上而不是今天早上`() {
        val next = SunClock.stateAt(ms(2026, 9, 17, 21, 0), cn, 35.0).nextSwitchAt!!
        val local = Instant.ofEpochMilli(next).atZone(cn)
        assertEquals("应当是第二天", day(2026, 9, 18), local.toLocalDate())
        assertTrue("应当是早上 5 点档，实际 ${local.hour} 点", local.hour == 5)
    }

    // ---------------------------------------------------------------- 方向四：公式对不对（真实世界的锚点）

    @Test
    fun `北京的夏至与冬至对齐真实天文值（±30 分钟）`() {
        val summer = SunClock.crossings(day(2026, 6, 21), cn, 39.9, lng = 116.4)
        val winter = SunClock.crossings(day(2026, 12, 21), cn, 39.9, lng = 116.4)
        val sDawn = summer.dawnMinute!!
        val sDusk = summer.duskMinute!!
        val wDawn = winter.dawnMinute!!
        val wDusk = winter.duskMinute!!
        // 夏至：民用天亮 ≈ 04:13 / 天黑 ≈ 20:22
        assertTrue("夏至天亮算成了 ${hm(sDawn)}", sDawn in (4 * 60 - 30)..(4 * 60 + 30))
        assertTrue("夏至天黑算成了 ${hm(sDusk)}", sDusk in (20 * 60)..(21 * 60))
        // 冬至：民用天亮 ≈ 07:03 / 天黑 ≈ 17:23
        assertTrue("冬至天亮算成了 ${hm(wDawn)}", wDawn in (7 * 60 - 30)..(7 * 60 + 30))
        assertTrue("冬至天黑算成了 ${hm(wDusk)}", wDusk in (17 * 60)..(18 * 60))
    }

    @Test
    fun `给真实经度时，经度每西移 15 度转折推迟正好一小时`() {
        // 4 分钟 / 度 —— 这条同时证明了"默认走时区中央经线"的那条路是可控的
        val d = day(2026, 9, 17)
        val east = SunClock.crossings(d, cn, 35.0, lng = 120.0)
        val west = SunClock.crossings(d, cn, 35.0, lng = 105.0)
        assertEquals(60L, (west.duskMinute!! - east.duskMinute!!).toLong())
        assertEquals(60L, (west.dawnMinute!! - east.dawnMinute!!).toLong())
    }

    @Test
    fun `极昼极夜没有切换时刻（不能返回一个假的钟点）`() {
        val polarDay = SunClock.crossings(day(2026, 6, 21), utc, 78.0)
        val polarNight = SunClock.crossings(day(2026, 12, 21), utc, 78.0)
        assertEquals(SunClock.Polar.ALWAYS_LIGHT, polarDay.polar)
        assertEquals(SunClock.Polar.ALWAYS_DARK, polarNight.polar)
        assertNull(polarDay.duskMinute)
        assertNull(polarNight.dawnMinute)

        val s1 = SunClock.stateAt(ms(2026, 6, 21, 3, 0, utc), utc, 78.0)
        val s2 = SunClock.stateAt(ms(2026, 12, 21, 12, 0, utc), utc, 78.0)
        assertFalse("极昼不该切夜间", s1.dark)
        assertNull("极昼没有下一次切换", s1.nextSwitchAt)
        assertTrue("极夜一直是夜间", s2.dark)
        assertNull("极夜没有下一次切换", s2.nextSwitchAt)
    }

    // ---------------------------------------------------------------- 界面那行字

    @Test
    fun `右侧那行字：关着说它做什么，开着说下一次几点切`() {
        val dark = SunClock.SunState(dark = true, nextSwitchAt = ms(2026, 9, 18, 5, 20))
        val light = SunClock.SunState(dark = false, nextSwitchAt = ms(2026, 9, 17, 18, 27))

        assertEquals("天黑切夜间，天亮切回白天", SunClock.summary(auto = false, state = dark, zone = cn, located = false))
        assertEquals(
            "现在夜间 · 05:20 自动转白天 · 按定位",
            SunClock.summary(auto = true, state = dark, zone = cn, located = true),
        )
        assertEquals(
            "现在白天 · 18:27 自动转夜间 · 按定位",
            SunClock.summary(auto = true, state = light, zone = cn, located = true),
        )
        // 极昼极夜没有下一次，也不能显示成 "null 自动转白天"
        val polar = SunClock.SunState(dark = true, nextSwitchAt = null)
        assertEquals("现在夜间 · 按定位", SunClock.summary(auto = true, state = polar, zone = cn, located = true))
    }

    @Test
    fun `没拿到定位时必须如实说「时区估算」并告诉用户开定位更准`() {
        // 两个精度差很多（新疆约 2 小时），说成一样等于骗人；而"没拿到位置"本身
        // 也该让用户知道怎么改——所以这句话里必须带"开定位"。
        val light = SunClock.SunState(dark = false, nextSwitchAt = ms(2026, 9, 17, 18, 27))
        val text = SunClock.summary(auto = true, state = light, zone = cn, located = false)
        assertTrue("要写明是估算：$text", text.contains("时区估算"))
        assertTrue("要告诉用户开定位更准：$text", text.contains("开定位"))
    }

    @Test
    fun `按定位算时用的是真实经纬度（新疆那种时区经线差 2 小时的要修掉）`() {
        // 乌鲁木齐：东经 87.6 用的是北京时间（东八区中央经线 120°E）。
        // 按真实经度算，天黑要比"按时区估算"晚整整 2 小时左右——这正是本轮要修的那件事。
        val day = day(2026, 9, 17)
        val byZone = SunClock.crossings(day, cn, 35.0)
        val byFix = SunClock.crossings(day, cn, 43.8, lng = 87.6)
        val gap = byFix.duskMinute!! - byZone.duskMinute!!
        assertTrue("真实经度应该让天黑晚 100 分钟以上，实际 $gap 分钟", gap >= 100)
    }
}
