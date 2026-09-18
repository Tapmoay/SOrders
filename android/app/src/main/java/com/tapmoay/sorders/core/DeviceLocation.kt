package com.tapmoay.sorders.core

import android.Manifest
import android.annotation.SuppressLint
import android.content.Context
import android.content.pm.PackageManager
import android.location.Location
import android.location.LocationManager
import android.os.Looper
import androidx.core.content.ContextCompat
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withTimeoutOrNull
import kotlin.coroutines.resume

/**
 * 一条候选坐标（**纯数据**）。
 *
 * 为什么不用 `android.location.Location` 直接传：本地 JVM 单测里它是空壳桩，
 * 一构造就抛 "not mocked"，判据（选哪一条）就没法单测了。
 */
data class LocationFix(val lat: Double, val lng: Double, val atMs: Long, val accuracyM: Float)

/**
 * **系统定位兜底**：只用来喂 [SunLocation]（"太阳几点落山"）。
 *
 * ### 为什么需要它
 * 自动夜间模式原本只有高德一条路，而高德这条路上任何一环出问题（Key 没绑当前签名、
 * 设备上没有高德服务、网络到不了高德服务器），坐标就永远是空的——表现是**一直**显示
 * "时区估算"，而用户以为自己开着定位。真机上就是这么栽的：
 * 日志里 `SERVICE_NOT_EXIST` + 清单缺 `APSService`，功能静默退化成估算。
 *
 * 日落只关心**经纬度**，系统 GPS/网络定位完全够用，所以这里做第二来源。
 *
 * ### ⚠️ 坐标系不同，所以只能喂日落
 * 高德给的是 GCJ-02，系统给的是 WGS-84，在国内差几百米。对"日落几点"没有影响
 * （几百米 ≈ 几秒），但**绝不能拿去填地址/水印**——那里的坐标要和后端、Web 端一致。
 * 所以本文件只调 `SunLocation.update`，**不往 `AmapLocationManager.locations` 里发点**
 * （那条流是给地图选点/拍照水印用的，它们要的是"带中文地址的 GCJ-02"）。
 */
object DeviceLocation {

    /** 超过这个年纪的缓存坐标不算数（手机可能几天没开过定位）。 */
    const val MAX_AGE_MS = 30 * 60 * 1000L

    /** 从若干候选里挑一条：先看新不新，再看好不好（准）。 */
    fun pickBest(
        fixes: List<LocationFix>,
        nowMs: Long,
        maxAgeMs: Long = MAX_AGE_MS,
    ): LocationFix? = fixes
        .filter { SunLocation.isPlausible(it.lat, it.lng) }
        // `atMs <= 0` = 不知道什么时候拿到的：能用，但排在所有"有时间"的后面
        .filter { it.atMs <= 0 || nowMs - it.atMs <= maxAgeMs }
        .sortedWith(compareByDescending<LocationFix> { it.atMs }.thenBy { it.accuracyM })
        .firstOrNull()

    fun fromLocation(loc: Location): LocationFix =
        LocationFix(loc.latitude, loc.longitude, loc.time, loc.accuracy)

    private fun hasPermission(context: Context): Boolean =
        ContextCompat.checkSelfPermission(context, Manifest.permission.ACCESS_FINE_LOCATION) ==
            PackageManager.PERMISSION_GRANTED ||
            ContextCompat.checkSelfPermission(context, Manifest.permission.ACCESS_COARSE_LOCATION) ==
            PackageManager.PERMISSION_GRANTED

    /**
     * 拿一次坐标并写进 [SunLocation]。拿不到返回 null（**不许**清掉上一次可用坐标）。
     *
     * 顺序：先吃缓存（绝大多数手机上是秒回的，还省一次 GPS 冷启动），没有再等一次回调。
     */
    @SuppressLint("MissingPermission")
    suspend fun requestSingle(context: Context, timeoutMs: Long = 6000L): LocationFix? {
        val ctx = context.applicationContext
        if (!hasPermission(ctx)) return null
        val lm = ctx.getSystemService(Context.LOCATION_SERVICE) as? LocationManager ?: return null

        val cached = try {
            lm.getProviders(true).mapNotNull { p ->
                try {
                    lm.getLastKnownLocation(p)
                } catch (_: Exception) {
                    null
                }
            }
        } catch (_: Exception) {
            emptyList()
        }
        val best = pickBest(cached.map(::fromLocation), System.currentTimeMillis())
            ?: awaitFirst(lm, timeoutMs)
            ?: return null

        return if (SunLocation.update(best.lat, best.lng)) best else null
    }

    @SuppressLint("MissingPermission")
    private suspend fun awaitFirst(lm: LocationManager, timeoutMs: Long): LocationFix? {
        val providers = try {
            lm.getProviders(true)
        } catch (_: Exception) {
            emptyList()
        }
        if (providers.isEmpty()) return null

        var listener: android.location.LocationListener? = null
        try {
            return withTimeoutOrNull(timeoutMs) {
                suspendCancellableCoroutine { cont ->
                    val l = object : android.location.LocationListener {
                        override fun onLocationChanged(location: Location) {
                            if (cont.isActive && SunLocation.isPlausible(location.latitude, location.longitude)) {
                                cont.resume(fromLocation(location))
                            }
                        }

                        // 老 API 上这两个是抽象方法，必须实现（新版本才有默认实现）
                        override fun onStatusChanged(provider: String?, status: Int, extras: android.os.Bundle?) = Unit
                        override fun onProviderEnabled(provider: String) = Unit
                        override fun onProviderDisabled(provider: String) = Unit
                    }
                    listener = l
                    try {
                        providers.forEach { p -> lm.requestLocationUpdates(p, 0L, 0f, l, Looper.getMainLooper()) }
                    } catch (_: Exception) {
                        cont.resume(null)
                    }
                }
            }
        } finally {
            // 无论拿到没拿到都要摘掉自己注册的那个监听，否则会一直占着 GPS（耗电）。
            // ⚠️ `removeUpdates` 只认**同一个实例**，所以这里必须是 `l` 本身。
            listener?.let { l ->
                try {
                    lm.removeUpdates(l)
                } catch (_: Exception) {
                }
            }
        }
    }
}
