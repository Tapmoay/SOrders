package com.tapmoay.sorders.core

import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import kotlin.math.abs
import kotlin.math.acos
import kotlin.math.cos
import kotlin.math.roundToInt
import kotlin.math.sin

object SunClock {

    /** 民用暮光：太阳在地平线下 6°。 */
    const val CIVIL_ZENITH = 96.0

    /** 拿不到定位时的纬度（中国中心）。 */
    const val DEFAULT_LAT = 35.0

    enum class Polar { NONE, ALWAYS_LIGHT, ALWAYS_DARK }

    data class Crossings(val dawnMinute: Int?, val duskMinute: Int?, val polar: Polar)

    data class SunState(val dark: Boolean, val nextSwitchAt: Long?)

    private val HHMM: DateTimeFormatter = DateTimeFormatter.ofPattern("HH:mm")

    fun stateAt(
        now: Long = System.currentTimeMillis(),
        zone: ZoneId = ZoneId.systemDefault(),
        lat: Double = DEFAULT_LAT,
        lng: Double? = null,
    ): SunState {
        val zdt = Instant.ofEpochMilli(now).atZone(zone)
        val today = crossings(zdt.toLocalDate(), zone, lat, lng)
        when (today.polar) {
            Polar.ALWAYS_DARK -> return SunState(dark = true, nextSwitchAt = null)
            Polar.ALWAYS_LIGHT -> return SunState(dark = false, nextSwitchAt = null)
            Polar.NONE -> Unit
        }
        val dawn = today.dawnMinute ?: return SunState(dark = false, nextSwitchAt = null)
        val dusk = today.duskMinute ?: return SunState(dark = true, nextSwitchAt = null)
        val minute = zdt.hour * 60 + zdt.minute
        return when {
            minute < dawn -> SunState(dark = true, nextSwitchAt = at(zdt.toLocalDate(), dawn, zone))
            minute < dusk -> SunState(dark = false, nextSwitchAt = at(zdt.toLocalDate(), dusk, zone))
            else -> {
                val tomorrow = zdt.toLocalDate().plusDays(1)
                val next = crossings(tomorrow, zone, lat, lng).dawnMinute
                SunState(dark = true, nextSwitchAt = next?.let { at(tomorrow, it, zone) })
            }
        }
    }

    /** 按手机当前位置算；没有可信坐标就退回时区估算。 */
    fun stateHere(
        now: Long = System.currentTimeMillis(),
        zone: ZoneId = ZoneId.systemDefault(),
    ): SunState {
        val p = SunLocation.coords() ?: return stateAt(now, zone)
        return stateAt(now, zone, p.first, p.second)
    }

    fun crossings(
        date: LocalDate,
        zone: ZoneId,
        lat: Double = DEFAULT_LAT,
        lng: Double? = null,
    ): Crossings {
        val n = date.dayOfYear
        val decl = 23.45 * sin(Math.toRadians(360.0 / 365.0 * (284 + n)))
        val b = Math.toRadians(360.0 / 364.0 * (n - 81))
        val eot = 9.87 * sin(2 * b) - 7.53 * cos(b) - 1.5 * sin(b)

        val noonElev = 90.0 - abs(lat - decl)
        val midnightElev = abs(lat + decl) - 90.0
        if (midnightElev > -6.0) return Crossings(null, null, Polar.ALWAYS_LIGHT)
        if (noonElev < -6.0) return Crossings(null, null, Polar.ALWAYS_DARK)

        val cosH = (
            (cos(Math.toRadians(CIVIL_ZENITH)) - sin(Math.toRadians(lat)) * sin(Math.toRadians(decl))) /
                (cos(Math.toRadians(lat)) * cos(Math.toRadians(decl)))
            ).coerceIn(-1.0, 1.0)
        val halfDay = Math.toDegrees(acos(cosH)) / 15.0

        val stdLng = zone.rules.getOffset(date.atStartOfDay(zone).toInstant()).totalSeconds / 240.0
        val lngFix = 4.0 * (stdLng - (lng ?: stdLng))
        val dawnMinute = (12.0 - halfDay) * 60 - eot + lngFix
        val duskMinute = (12.0 + halfDay) * 60 - eot + lngFix
        return Crossings(minuteOfDay(dawnMinute), minuteOfDay(duskMinute), Polar.NONE)
    }

    fun summary(
        auto: Boolean,
        state: SunState,
        zone: ZoneId = ZoneId.systemDefault(),
        located: Boolean,
    ): String {
        if (!auto) return "天黑切夜间，天亮切回白天"
        val hm = state.nextSwitchAt?.let {
            Instant.ofEpochMilli(it).atZone(zone).toLocalTime().format(HHMM)
        }
        val basis = if (located) "按定位" else "时区估算，开定位更准"
        return when {
            hm == null -> (if (state.dark) "现在夜间" else "现在白天") + " · $basis"
            state.dark -> "现在夜间 · $hm 自动转白天 · $basis"
            else -> "现在白天 · $hm 自动转夜间 · $basis"
        }
    }

    private fun minuteOfDay(minutes: Double): Int = Math.floorMod(minutes.roundToInt(), 24 * 60)

    private fun at(date: LocalDate, minuteOfDay: Int, zone: ZoneId): Long =
        date.atStartOfDay(zone).plusMinutes(minuteOfDay.toLong()).toInstant().toEpochMilli()
}
