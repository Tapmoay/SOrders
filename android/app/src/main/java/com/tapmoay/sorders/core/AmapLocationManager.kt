package com.tapmoay.sorders.core

import android.annotation.SuppressLint
import android.content.Context
import com.amap.api.location.AMapLocation
import com.amap.api.location.AMapLocationClient
import com.amap.api.location.AMapLocationClientOption
import com.amap.api.location.AMapLocationListener
import com.tapmoay.sorders.BuildConfig
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
 *
 * ⚠️ 这里**只**负责"带地址的高德坐标"。[SunLocation]（日落算几点）还有第二条来源
 * ——[DeviceLocation] 的系统定位，因为日落只需要经纬度，不该被高德 Key/服务卡死。
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
                isMockEnable = BuildConfig.DEBUG
            }
            c.setLocationOption(opt)
            c.setLocationListener(object : AMapLocationListener {
                override fun onLocationChanged(loc: AMapLocation?) {
                    // 注意：不移除 client（保持常驻复用），仅停止本次定位——反复重建高德客户端冷启动约 1-2 秒
                    if (loc != null && loc.errorCode == 0) {
                        val pt = AmapLocationPoint(
                            lat = loc.latitude,
                            lng = loc.longitude,
                            address = loc.address ?: "",
                            accuracy = loc.accuracy,
                        )
                        lastPoint = pt
                        SunLocation.update(pt.lat, pt.lng)
                        _locations.tryEmit(pt)
                    } else {
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

    /**
     * 发起一次单次定位。
     *
     * @return true = 已经发出去（结果走 [locations]）；false = **连发起都没成功**
     *   （权限缺失或 SDK 起不来）。调用方拿到 false 时应当走 [DeviceLocation] 兜底——
     *   否则"高德没起来"这种失败**一个回调都不会有**，界面会一直停在"时区估算"，
     *   而没有任何地方知道该退到系统定位。
     */
    @SuppressLint("MissingPermission")
    fun requestSingle(): Boolean {
        return try {
            val c = buildClient() ?: return false
            c.startLocation()
            true
        } catch (_: Exception) {
            false
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
