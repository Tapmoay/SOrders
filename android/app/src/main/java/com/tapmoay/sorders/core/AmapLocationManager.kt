package com.tapmoay.sorders.core

import android.annotation.SuppressLint
import android.content.Context
import com.amap.api.location.AMapLocation
import com.amap.api.location.AMapLocationClient
import com.amap.api.location.AMapLocationClientOption
import com.amap.api.location.AMapLocationListener
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.asSharedFlow

data class AmapLocationPoint(
    val lat: Double,
    val lng: Double,
    val address: String,
    val accuracy: Float,
)

/**
 * 高德定位（GCJ-02，与后端/Web 端坐标体系一致）：
 * - 单次定位 requestSingle()：拍照水印 / 地图选点「使用当前位置」
 * - 返回 lastPoint 含逆地理地址（地点名，如「北京市海淀区中关村…」）
 * 调用前需确保定位权限已授予（UI 层处理）。
 */
class AmapLocationManager(private val context: Context) {

    private val appContext = context.applicationContext

    private var client: AMapLocationClient? = null

    private val _locations = MutableSharedFlow<AmapLocationPoint>(extraBufferCapacity = 4)
    val locations: SharedFlow<AmapLocationPoint> = _locations.asSharedFlow()

    /** 最近一次定位（拍照水印使用；未定位成功为 null） */
    @Volatile
    var lastPoint: AmapLocationPoint? = null

    private fun buildClient(): AMapLocationClient? {
        if (client != null) return client
        return try {
            val c = AMapLocationClient(appContext)
            val opt = AMapLocationClientOption().apply {
                locationMode = AMapLocationClientOption.AMapLocationMode.Hight_Accuracy
                isOnceLocation = true
                isOnceLocationLatest = true
                isNeedAddress = true
                isMockEnable = false
            }
            c.setLocationOption(opt)
            c.setLocationListener(object : AMapLocationListener {
                override fun onLocationChanged(loc: AMapLocation?) {
                    client = null
                    if (loc != null && loc.errorCode == 0) {
                        val pt = AmapLocationPoint(
                            lat = loc.latitude,
                            lng = loc.longitude,
                            address = loc.address ?: "",
                            accuracy = loc.accuracy,
                        )
                        lastPoint = pt
                        _locations.tryEmit(pt)
                    } else {
                        // 定位失败：回调空结果由 UI 层提示
                        _locations.tryEmit(
                            AmapLocationPoint(
                                lat = 0.0,
                                lng = 0.0,
                                address = "",
                                accuracy = 0f,
                            )
                        )
                    }
                    c.stopLocation()
                }
            })
            client = c
            c
        } catch (_: Exception) {
            null
        }
    }

    @SuppressLint("MissingPermission")
    fun requestSingle() {
        try {
            buildClient()?.startLocation()
        } catch (_: Exception) {
            // 权限缺失或 SDK 异常：静默，UI 层给出提示
        }
    }

    fun stop() {
        try {
            client?.stopLocation()
            client?.onDestroy()
        } catch (_: Exception) {
        } finally {
            client = null
        }
    }
}
