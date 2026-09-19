package com.tapmoay.sorders.ai

import android.content.Context
import com.amap.api.services.geocoder.GeocodeQuery
import com.amap.api.services.geocoder.GeocodeResult
import com.amap.api.services.geocoder.GeocodeSearch
import com.amap.api.services.geocoder.RegeocodeResult
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull
import kotlin.coroutines.resume

/**
 * 把一段地址文字换成经纬度（高德地理编码）。
 *
 * ### 为什么 AI 这条路必须自己做这件事（v3.24 真机实测发现的缺口）
 * App 自己的页面里，坐标是**用户在地图上点出来的**——`AmapPicker` 选完点，
 * `address_lat/lng` 跟着表单一起提交。而 AI 没有人点地图，它只有一句话。
 * 结果是：AI 建的地址、AI 建的地点、AI 建的订单**全都没有坐标**。
 *
 * 后果不是"少存了一个字段"，而是**司机那一端的导航直接失灵**：
 * 订单详情页的「高德导航」拿到空坐标后走的是 [com.tapmoay.sorders.util.openAmapNavigation]
 * 的兜底分支——打开高德首页，**没有目的地**，司机得自己把地址再手打一遍。
 * 这恰好是"让用户零成本"要消灭的那一步，所以它必须在这里补上。
 *
 * ### 三条设计约束
 * 1. **只读**：它查高德，不碰 SOrders 后端。所以放在 `prepare` 里是安全的
 *    （`prepare` 的红线只禁"写后端"）。
 * 2. **一定超时**：高德 SDK 的回调不保证一定回来。没有超时的话，一次网络抽风
 *    会把整个确认卡卡住——用户看到的是"AI 不吭声了"。
 * 3. **串行 + 序号校验**：`GeocodeSearch` 是**一个实例一个监听器**。
 *    并发查两次时后设的监听器会覆盖前一个，于是**前一次的结果会喂给后一次的等待者**
 *    ——那是"地址 A 拿到地址 B 的坐标"这种最难查的错。用一把锁串行，再用序号挡掉
 *    超时后被丢弃的那次回调。
 */
internal object AiGeocode {

    /** 单次地理编码的超时（毫秒）。宁可没坐标，也不能让用户对着转圈的卡片等。 */
    const val TIMEOUT_MS = 5000L

    private val lock = Mutex()
    private var search: GeocodeSearch? = null

    /** 已发出的查询序号：回调回来时对不上就丢弃（见类注释第 3 条）。 */
    private var issued = 0

    /**
     * @param context null = 不定位（单测、或没有 Context 的场景）。**调用方必须容忍 null。**
     * @return 纬度 to 经度；null = 没解析出来（地址太模糊 / 没网 / 超时 / 没 Context）。
     */
    suspend fun lookup(context: Context?, address: String): Pair<Double, Double>? {
        val text = address.trim()
        if (context == null || text.isEmpty()) return null
        val app = context.applicationContext
        return withTimeoutOrNull(TIMEOUT_MS) {
            lock.withLock {
                runCatching { geocode(app, text) }.getOrNull()
            }
        }
    }

    private suspend fun geocode(context: Context, address: String): Pair<Double, Double>? {
        val seq = ++issued
        return withContext(Dispatchers.Main) {
            suspendCancellableCoroutine { cont ->
                val s = search ?: GeocodeSearch(context).also { search = it }
                s.setOnGeocodeSearchListener(
                    object : GeocodeSearch.OnGeocodeSearchListener {
                        override fun onRegeocodeSearched(result: RegeocodeResult?, rCode: Int) = Unit

                        override fun onGeocodeSearched(result: GeocodeResult?, rCode: Int) {
                            // 只认自己那一次查询的结果（超时被丢弃的那次不许污染下一次）
                            if (seq != issued) return
                            val point = if (rCode == 1000) {
                                result?.geocodeAddressList?.firstOrNull()?.latLonPoint
                            } else {
                                null
                            }
                            if (cont.isActive) {
                                cont.resume(point?.let { it.latitude to it.longitude })
                            }
                        }
                    },
                )
                // city 传空串 = 全国范围搜（与 App 里 AmapPicker 的关键字搜索同一套用法）
                s.getFromLocationNameAsyn(GeocodeQuery(address, ""))
            }
        }
    }
}
