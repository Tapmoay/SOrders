package com.tapmoay.sorders.ai

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import androidx.core.content.ContextCompat
import com.tapmoay.sorders.core.AmapLocationManager
import com.tapmoay.sorders.core.AmapLocationPoint
import com.tapmoay.sorders.core.SunLocation
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineStart
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull

/**
 * **手机当前在哪** —— 这是 AI 唯一一条"读本机"的路（其余读的都是后端表）。
 *
 * ### 为什么必须有它（2026-09-21 用户原话）
 * 「ai 它要具备读取手机的地点的能力，因为 ai 它是要具备所有功能…包括用户不是我们要去手动选地点吗？
 * 它也可以去选地点，**这个权限给它开啊**」。在此之前：AI 只能把用户**说出来的地址文字**拿去高德换坐标
 * （[AiGeocode]），它**从来不读手机自己的定位** —— 所以"我在哪 / 用我现在的位置建条地址"它必然答不出来。
 *
 * ### 三条硬规矩
 * 1. **坐标只在本文件与写链路之间流转**：模型看得到的输出里**只有地址文字**（见 [AiLocalReads]）。
 *    模型要写"用户所在的地方"时只写四个字 [HERE]，真实地址与精确坐标由 App 在这里换上。
 * 2. **只要高德 GCJ-02**：导航坐标必须是高德坐标系。[com.tapmoay.sorders.core.DeviceLocation]
 *    的系统定位是 WGS84（在国内差几百米），所以它**只**喂 [SunLocation]（算日落），
 *    ⛔ 不许拿来当导航坐标、也不许拿它当逆地理的输入。高德那条失败就**如实说拿不到**，
 *    不悄悄退到系统定位（那会写出一个偏几百米的地址，而界面上看不出来）。
 * 3. **按需取一次**：不订阅、不后台持续定位、不缓存；日志里一个坐标都不打。
 */
data class AiPlace(
    /** 高德逆地理出来的完整地址文字（含省市区，如「广东省惠州市惠城区麦地路 11 号」）。 */
    val address: String,
    /** GCJ-02 纬度（与后端、Web 端、地图选点同一坐标系）。 */
    val lat: Double,
    /** GCJ-02 经度。 */
    val lng: Double,
)

/**
 * 定位提供者：真机是高德（[AmapCurrentLocationProvider]），单测传替身、或 null = 没有这个能力。
 *
 * 做成接口的理由与 [AiGeocode] 接受 `context: Context?` 同源：**单测里没有 Android 运行时**，
 * 而"拿不到定位时怎么办"恰恰是最需要被测到的那一半（用户会遇到的正是没授权/没信号）。
 */
interface AiLocationProvider {

    /**
     * 定位权限给了吗。**先去问权限，不去等一个注定不来的回调** ——
     * 没授权时高德一个回调都不会有，界面上表现成"AI 卡住了"。
     */
    fun permitted(): Boolean

    /**
     * 取一次定位。null = 这次没拿到（超时 / 没信号 / 服务没开 / 只回了不可信的 `(0,0)`）。
     * 坐标**必须是 GCJ-02**（见类注释第 2 条）。
     */
    suspend fun current(): AiPlace?
}

object AiLocation {

    /**
     * 地址类参数里允许模型写的**固定哨兵**（四个字，别改成同义词：模型照抄的正是这个字面量）。
     *
     * 为什么是句柄而不是"让模型填坐标"：本仓第一条硬规矩就是**模型全程碰不到经纬度**。
     * 而"用我当前位置"这件事又必须精确到和手动选点一样（司机照着它导航），所以分工是：
     * 模型只写这四个字 → App 取一次定位 → 真实地址文字 + 精确坐标一起写进 payload。
     */
    const val HERE = "当前位置"

    /**
     * 取一次定位的超时。
     *
     * 宁可回一句"这次没拿到"，也不让用户对着转圈的卡片等 —— 与 [AiGeocode.TIMEOUT_MS] 同一条理由。
     */
    const val TIMEOUT_MS = 8000L

    /** 模型在这个地址参数上写的是不是「当前位置」。 */
    fun isHere(text: String?): Boolean = text?.trim() == HERE

    /**
     * 地址类输入的**唯一解析入口**：是句柄就取一次手机定位，否则交给 [geocode]（高德地理编码）。
     *
     * ### 为什么把这条分叉收到一处（而不是让每个处理器自己判）
     * 地址类动作有三个入口（声明式 `geocodeFrom` 那一族、下单、改单）。各写一遍"认不认句柄"，
     * 必然有一个漏掉 —— 漏掉的那个会把**字面量「当前位置」**写进地址库：不报错，
     * 而司机导航到一个叫"当前位置"的地方。而且"句柄**绝不许**落到地理编码那条路上"
     * 这件事，只有收成一处才测得出来（见 `AiLocalReadsTest`：那条测试断言地理编码一次都没被调）。
     *
     * @param provider 本机定位提供者（null = 这个环境没有定位能力 → 句柄当场被拒）
     * @param geocode 普通地址的解析方式（生产是 [AiGeocode]，单测是替身）
     * @throws AiWriteArgException 句柄拿不到定位时（**不弹卡**，见 [requireHere]）
     */
    suspend fun resolveAddress(
        text: String,
        provider: AiLocationProvider?,
        geocode: suspend (String) -> Pair<Double, Double>?,
    ): AiPlace? =
        if (isHere(text)) requireHere(provider)
        else geocode(text)?.let { AiPlace(address = text, lat = it.first, lng = it.second) }

    /**
     * 把「当前位置」解析成真实地址 + 精确坐标。
     *
     * @throws AiWriteArgException 拿不到定位时**抛一句能照着改的中文**：调用方（写链路）
     *   会把它转成一次拒绝 —— **不弹卡**。白弹一张卡比报错更糟：用户点了确认，
     *   要么地址里印着「当前位置」四个字，要么坐标是上一个地方。
     */
    suspend fun requireHere(provider: AiLocationProvider?): AiPlace {
        if (provider == null) throw AiWriteArgException(NO_PROVIDER)
        if (!provider.permitted()) throw AiWriteArgException(NO_PERMISSION)
        return provider.current() ?: throw AiWriteArgException(NO_FIX)
    }

    /** 这台设备/这次构建里根本没有定位能力（单测、或没接 Context）。 */
    internal const val NO_PROVIDER =
        "这台设备上读不到「当前位置」（App 没有接定位能力）。" +
            "请让用户直接把地址说完整（带上城市和区/路名），或者回 App 用地图选点。" +
            "⛔ 不要自己编一个地址，也不要再试一次这个写法。"

    /** 没授权 —— 必须**告诉用户去哪儿开**，否则他只会反复问同一句话。 */
    internal const val NO_PERMISSION =
        "读不到「当前位置」：这个 App 还没有定位权限。" +
            "请让用户去手机的「设置 → 应用 → SOrders → 权限 → 位置信息」里打开（选「使用应用时允许」），" +
            "然后再说一次；也可以让他直接把地址说完整。"

    /** 授权了但这次没定位到。 */
    internal const val NO_FIX =
        "这次没拿到定位（可能手机没开定位服务、或在室内/地下收不到信号）。" +
            "请让用户到空旷处再说一次，或者直接把地址说完整（带上城市和区/路名）。"

    /**
     * 真机实现：走**高德**单次定位（GCJ-02 + 逆地理地址），失败回 null。
     *
     * ### 为什么不用 [com.tapmoay.sorders.core.DeviceLocation] 兜底
     * 它是系统定位（WGS84）。日落计算差几百米无所谓，**导航坐标差几百米就是把司机带错路口**；
     * 而且"退回系统定位"这件事在界面上完全看不出来。所以这里是**一路到底**：高德拿不到就说拿不到。
     *
     * ### 为什么不复用界面上那个 [AmapLocationManager] 实例
     * 那是拍照水印 / 地图选点在用的（`AppContainer.locationManager`）。共用的话，
     * 别处发起的一次定位会把它的结果喂给正在等的那一次（同一条 SharedFlow）——
     * 表现是"AI 拿到了水印那一次的坐标"，而且不报错。多一个客户端（按需才建）换这一个确定性，值。
     */
    class AmapCurrentLocationProvider(private val context: Context) : AiLocationProvider {

        private val appContext = context.applicationContext

        /** 串行：同一时刻只允许一次定位在飞（与 [AiGeocode] 的锁同一条理由）。 */
        private val lock = Mutex()

        /**
         * 高德客户端**按需建**（`lazy`）：用户不碰"当前位置"就一个 SDK 客户端都不起
         * —— 免得多一个常驻的定位组件。建成之后一直复用（反复重建冷启动要 1~2 秒）。
         */
        private val manager by lazy { AmapLocationManager(appContext) }

        override fun permitted(): Boolean =
            ContextCompat.checkSelfPermission(appContext, Manifest.permission.ACCESS_FINE_LOCATION) ==
                PackageManager.PERMISSION_GRANTED ||
                ContextCompat.checkSelfPermission(appContext, Manifest.permission.ACCESS_COARSE_LOCATION) ==
                PackageManager.PERMISSION_GRANTED

        override suspend fun current(): AiPlace? = lock.withLock {
            // 高德 SDK 的客户端在**主线程**建/发最稳（界面侧一直是这么用的）。
            withContext(Dispatchers.Main.immediate) {
                withTimeoutOrNull(TIMEOUT_MS) {
                    val m = manager
                    val got = CompletableDeferred<AmapLocationPoint?>()
                    // ⚠️ `UNDISPATCHED`：**先把订阅登记好，再发起定位**。
                    //    普通 `launch` 要等当前协程挂起才跑，而那之间发出的值会被直接丢掉
                    //    （SharedFlow 无 replay）→ 症状是"每一次都超时"，且不报错。
                    val sub = launch(start = CoroutineStart.UNDISPATCHED) {
                        got.complete(m.locations.first())
                    }
                    try {
                        // false = 连"发起"都没成功（权限被撤/SDK 起不来），不会有任何回调 → 直接回 null
                        if (!m.requestSingle()) return@withTimeoutOrNull null
                        got.await().toPlace()
                    } finally {
                        sub.cancel()
                    }
                }
            }
        }

        /**
         * ⛔ 失败值挡两道，**两道都必须过**：
         * 1. `(0,0)` —— 高德失败时**照常回调**，只是给 `(0,0)`（见 `AmapLocationManager`）。
         *    判据复用全仓唯一那一份 [SunLocation.isPlausible]，不在这里另写一套。
         * 2. 地址文字为空 —— 地址类动作要的是**文字**（写进 `detail_address` 给司机看），
         *    只有坐标等于没拿到；此时回 null 让上层如实说"没定位到"，而不是写一个空地址。
         *
         * ⚠️ 失败**不清任何"上一次的坐标"**：本提供者刻意**不持有**上一次可用坐标 ——
         * "用当前位置"是用户**现在**站在哪儿，拿一个十分钟前的点去写收货地址，
         * 就是把司机导航到用户**曾经**在的地方（本仓对"错坐标"的一贯口径：
         * 补导航那个动作宁可拒绝，也不把对的坐标改成错的）。要改这条，得先拍板接受这个后果。
         */
        private fun AmapLocationPoint?.toPlace(): AiPlace? {
            val p = this ?: return null
            if (!SunLocation.isPlausible(p.lat, p.lng)) return null
            val text = p.address.trim()
            if (text.isEmpty()) return null
            return AiPlace(address = text, lat = p.lat, lng = p.lng)
        }
    }
}
