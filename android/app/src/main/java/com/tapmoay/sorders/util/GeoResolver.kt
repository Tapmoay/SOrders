package com.tapmoay.sorders.util

import android.content.Context
import com.amap.api.services.core.LatLonPoint
import com.amap.api.services.geocoder.GeocodeSearch
import com.amap.api.services.geocoder.RegeocodeQuery
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlin.coroutines.resume

/**
 * 逆地理编码（高德）：把经纬度解析为具体地点名（如 xx村 / 昌江大道 xx路 / xx店）。
 * 供拍照水印、地图选点确认等使用；失败返回 null，调用方回退订单地址。
 */
object GeoResolver {

    private var geocodeSearch: GeocodeSearch? = null

    private fun getSearch(context: Context): GeocodeSearch? {
        geocodeSearch?.let { return it }
        return try {
            GeocodeSearch(context.applicationContext).also { geocodeSearch = it }
        } catch (_: Exception) {
            null
        }
    }

    /** 同步单发（拍照水印场景：后台线程调用，不阻塞 UI） */
    fun resolveSync(context: Context, lat: Double, lng: Double): String? {
        return try {
            val search = getSearch(context) ?: return null
            // getFromLocation 直接返回 RegeocodeAddress（同步版）
            val addr = search.getFromLocation(
                RegeocodeQuery(LatLonPoint(lat, lng), 200f, GeocodeSearch.AMAP)
            )
            if (addr != null) {
                addr.formatAddress ?: addr.pois?.firstOrNull()?.title
            } else null
        } catch (_: Exception) {
            null
        }
    }

    /** 挂起版（Compose/协程场景：地图选点确认后补全地址名） */
    suspend fun resolve(context: Context, lat: Double, lng: Double): String? =
        suspendCancellableCoroutine { cont ->
            try {
                val search = getSearch(context) ?: run {
                    if (cont.isActive) cont.resume(null)
                    return@suspendCancellableCoroutine
                }
                search.setOnGeocodeSearchListener(object : GeocodeSearch.OnGeocodeSearchListener {
                    override fun onRegeocodeSearched(result: com.amap.api.services.geocoder.RegeocodeResult?, rCode: Int) {
                        val addr = if (rCode == 1000 && result?.getRegeocodeAddress() != null) {
                            val a = result.getRegeocodeAddress()
                            a.formatAddress ?: a.pois?.firstOrNull()?.title
                        } else null
                        if (cont.isActive) cont.resume(addr)
                    }

                    override fun onGeocodeSearched(result: com.amap.api.services.geocoder.GeocodeResult?, rCode: Int) {}
                })
                search.getFromLocationAsyn(RegeocodeQuery(LatLonPoint(lat, lng), 200f, GeocodeSearch.AMAP))
            } catch (e: Exception) {
                if (cont.isActive) cont.resume(null)
            }
        }
}