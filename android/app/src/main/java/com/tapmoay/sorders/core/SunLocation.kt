package com.tapmoay.sorders.core

import kotlin.math.abs

/** 最近一次可信的手机坐标；拿不到就退回时区估算。 */
object SunLocation {

    @Volatile
    private var point: Pair<Double, Double>? = null

    fun coords(): Pair<Double, Double>? = point

    fun hasFix(): Boolean = point != null

    fun update(lat: Double?, lng: Double?): Boolean {
        if (!isPlausible(lat, lng)) return false
        point = lat!! to lng!!
        return true
    }

    fun clear() {
        point = null
    }

    /** 定位失败时高德回的是 (0,0) 而不是 null，这种值必须挡掉。 */
    fun isPlausible(lat: Double?, lng: Double?): Boolean {
        if (lat == null || lng == null) return false
        if (lat.isNaN() || lng.isNaN() || lat.isInfinite() || lng.isInfinite()) return false
        if (lat < -90.0 || lat > 90.0) return false
        if (lng < -180.0 || lng > 180.0) return false
        if (abs(lat) < 0.01 && abs(lng) < 0.01) return false
        return true
    }
}
