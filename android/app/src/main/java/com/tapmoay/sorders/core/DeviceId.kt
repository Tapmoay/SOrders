package com.tapmoay.sorders.core

import android.content.Context
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import com.tapmoay.sorders.data.remote.api.DeviceApi
import com.tapmoay.sorders.data.remote.dto.DeviceRegisterRequest
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import java.util.UUID

/**
 * # App 实例标识（FEAT-0018 账号↔设备绑定与风控）
 *
 * ## 为什么是「App 实例 ID」，而不是 IMEI / MAC / 序列号
 * 后端要认的是**「同一部手机上的同一次 App 安装」**，拿它做两件事：
 * ① 一个账号最多绑 3 台设备（第 4 台要等最旧那台失效）；② 一台设备短时间不许绑多个账号
 * （防批量注册刷号）。用户 2026-10-11 的口径里，被防的是「刷号」，不是「同一个人换手机」。
 *
 * 那三样硬件标识**一个都不能用**：
 * · `Build.SERIAL` / `getSerial()`：Android 6（API 23）起对普通 App 直接抛安全异常；
 * · IMEI / 手机号等**不可重置**的标识：Android 10（API 29）起只有系统应用或运营商权限才拿得到
 *   （`READ_PRIVILEGED_PHONE_STATE`）—— 本 App 的清单里连 `READ_PHONE_STATE` 都没有，
 *   写上也是恒 null，白白背一条权限；
 * · MAC 地址：Android 6 之后 `WifiInfo` 一律回 `02:00:00:00:00:00`，读不到真实值。
 *
 * 更要紧的是**隐私**：IMEI / MAC 是**跨应用、跨卸载**都能一路追踪到同一个人的硬件标识，
 * 属于应用商店点名的敏感信息。为了一个风控指标把整台设备的使用者交出去，
 * 代价与收益完全不成比例 —— 所以这里用**本机随机生成、只对这一次安装有效**的 UUID。
 *
 * 代价是「重装 / 清数据 = 后端眼里的另一台设备」（会再占一个名额）。这不是缺陷，
 * 正是要的语义：那台设备上的凭证已经没了，新的安装本来就该重新认一次。
 *
 * ## 三个值的关系（⛔ 这里不存任何人的身份信息）
 * | 值 | 谁生成 | 存哪 | 干什么用 |
 * |---|---|---|---|
 * | `install_id` | **本机**（UUID v4） | DataStore `device` | 后端认设备的钥匙 |
 * | `token` | **后端**（`POST /devices/register` 回的 hmac） | 同上 | 证明「这个 install_id 是我自己注册的」，防伪造 |
 * | `X-Device-Id` | 现拼 | **不落盘** | `install_id + ":" + token`，所有请求统一带上（见 [ApiClient]） |
 *
 * ## 什么时候注册、失败了怎么办（⛔ 失败绝不许阻塞 App）
 * 冷启动由 [com.tapmoay.sorders.SOrdersApp] 打一次；**失败就不管了**
 * （离线 / 后端不可达 / 服务端还没发版），往后任何一发请求发现头是空的，
 * [ApiClient] 会通过 `onDeviceIdMissing` 再拉一次（后台、静默、60 秒内只试一次）。
 * 「注册不上就用不了 App」是绝对不能出现的形态：这台设备还没注册时，用户照样要能登录、
 * 能看订单 —— 只是后端那边暂时把这次请求当成没带设备信息。
 */

/** 设备标识里**与 Android 无关**的那一半（纯函数，单测直接打在这上面）。 */
object DeviceIdentity {

    /** 请求头名。契约由父会话与后端定死，⛔ 两边都不许改。 */
    const val HEADER = "X-Device-Id"

    /** 后端对 `install_id` 的长度要求（8~64 位，见 FEAT-0018 契约）。 */
    const val ID_MIN = 8
    const val ID_MAX = 64

    /** 生成一个新的 App 实例 ID：UUID v4（36 位，落在 [ID_MIN]~[ID_MAX] 中间）。 */
    fun newInstallId(): String = UUID.randomUUID().toString()

    /** 这个 `install_id` 后端收不收（越界 = 生成/落盘坏了，⛔ 别发给后端让它猜）。 */
    fun isValidInstallId(raw: String?): Boolean = raw != null && raw.length in ID_MIN..ID_MAX

    /**
     * 发出去的 `X-Device-Id` 取值。
     *
     * ⛔ **两个都齐了才发；半截值不发**：只有 `install_id` 没有 `token` 时后端认不出这台设备，
     *    而"带了一个认不出的头"比"没带头"更难查 —— 出问题时分不清是"这台还没注册"
     *    还是"注册成功但头拼错了"。
     */
    fun headerValue(installId: String?, token: String?): String? =
        if (isValidInstallId(installId) && !token.isNullOrBlank()) "$installId:$token" else null
}

/** 落盘的那两个值（[DeviceIdStore.read] 的返回）。 */
data class DevicePrefs(val installId: String? = null, val token: String? = null)

/**
 * 设备标识的落盘口子。
 *
 * 抽成接口只有一个理由：**这段逻辑必须能被 JVM 单测打到**（"同一台设备两次启动拿到同一个
 * install_id、清数据之后换一个、离线时注册失败但 App 照常可用"）。真机实现是 DataStore
 * （见 [PrefsDeviceIdStore]），单测换成内存实现，一行都不碰 Android。
 */
interface DeviceIdStore {
    suspend fun read(): DevicePrefs
    suspend fun write(installId: String, token: String?)
}

private val Context.deviceDataStore by preferencesDataStore(name = "device")

/**
 * 真机实现：`preferencesDataStore(name = "device")` —— App 私有目录
 * `/data/data/com.tapmoay.sorders/files/datastore/device.preferences_pb`。
 *
 * 与登录会话（[TokenStore] 的 `session`）同一个机制，但**分成两个文件**：
 * 退出登录会 `clear()` 掉 session，而设备身份**不该跟着账号一起没**
 * （同一台手机换个人登录，它还是这台设备）。
 */
class PrefsDeviceIdStore(private val context: Context) : DeviceIdStore {

    private object Keys {
        val INSTALL_ID = stringPreferencesKey("install_id")
        val TOKEN = stringPreferencesKey("device_token")
    }

    override suspend fun read(): DevicePrefs {
        val p = context.deviceDataStore.data.first()
        return DevicePrefs(p[Keys.INSTALL_ID], p[Keys.TOKEN])
    }

    override suspend fun write(installId: String, token: String?) {
        context.deviceDataStore.edit { p ->
            p[Keys.INSTALL_ID] = installId
            if (token != null) p[Keys.TOKEN] = token
        }
    }
}

/**
 * 设备身份的持有者（为什么这么设计见文件头）。
 *
 * 两个值在内存里各留一份：OkHttp 的拦截器要**跨线程同步**读 [headerValue]，
 * 而 DataStore 只有挂起函数（与 [TokenStore.cachedToken] 同一个套路）。
 *
 * [now] 可注入只为一件事 —— 单测要验「失败后 60 秒内不再打第二发」。
 */
class DeviceId(
    private val store: DeviceIdStore,
    private val now: () -> Long = { System.currentTimeMillis() },
) {

    @Volatile
    private var cachedInstallId: String? = null

    @Volatile
    private var cachedToken: String? = null

    /** 单飞：同一时刻只允许一次注册请求（冷启动那一发与拦截器补的那一发会撞上）。 */
    @Volatile
    private var registering: Boolean = false

    /** 上一次注册**尝试**的时刻（毫秒）——后端不可达时不能每一发请求都去撞一次。 */
    @Volatile
    private var lastAttemptAt: Long = 0L

    /** 供 OkHttp 拦截器同步读取；还没注册成功就是 null（那时不发这个头）。 */
    fun headerValue(): String? = DeviceIdentity.headerValue(cachedInstallId, cachedToken)

    /** 启动时把落盘的值读进内存（拦截器是同步的，读不了挂起函数）。 */
    fun warmCache() {
        if (headerValue() != null) return
        try {
            val p = runBlocking { store.read() }
            if (cachedInstallId == null) cachedInstallId = p.installId
            if (cachedToken == null) cachedToken = p.token
        } catch (_: Exception) {
            // 读不出来就当作"这台设备还没注册"：⛔ 一个设备头**没有任何理由**把 App 拦在启动页
        }
    }

    /**
     * 保证 `install_id` 存在（没有就生成并落盘）——**只做本机的事，不联网**。
     *
     * 「同一台设备两次启动拿到同一个值」靠的是 DataStore；`pm clear` / 卸载会连它一起清掉，
     * 下一次启动就生成一个新的（＝后端眼里的另一台设备，见文件头）。
     */
    suspend fun ensureInstallId(): String {
        cachedInstallId?.let { if (DeviceIdentity.isValidInstallId(it)) return it }
        val stored = try {
            store.read().installId
        } catch (e: CancellationException) {
            throw e
        } catch (_: Exception) {
            null
        }
        if (DeviceIdentity.isValidInstallId(stored)) {
            cachedInstallId = stored
            return stored!!
        }
        val fresh = DeviceIdentity.newInstallId()
        cachedInstallId = fresh
        try {
            store.write(fresh, cachedToken)
        } catch (e: CancellationException) {
            throw e
        } catch (_: Exception) {
            // 落盘失败：这一次先用内存里的值（App 照常能用），下次启动会再生成一个
        }
        return fresh
    }

    /**
     * 调 `POST /devices/register` 换 `token`（幂等：已经有 token 就直接 true）。
     *
     * @return 现在**是不是**已经拿得到 `X-Device-Id`（不是"这一次请求成功了"）。
     *   失败一律 `false` + 静默：调用方（[com.tapmoay.sorders.core.AppContainer]）只当没发生。
     */
    suspend fun ensureRegistered(api: DeviceApi): Boolean {
        if (!cachedToken.isNullOrBlank()) return true
        if (registering) return false
        val t = now()
        if (t - lastAttemptAt < RETRY_COOLDOWN_MS) return false
        lastAttemptAt = t
        registering = true
        try {
            val installId = ensureInstallId()
            val resp = api.register(DeviceRegisterRequest(installId = installId))
            val token = resp.token.takeIf { it.isNotBlank() } ?: return false
            // 后端回的 `device_id` 就是它记下的那个 install_id。万一它与本地不同（理论上不该），
            // 以**后端记下的那个**为准：头里送错值只会让往后每一发请求都被判成"没绑定"。
            val id = resp.deviceId.takeIf { DeviceIdentity.isValidInstallId(it) } ?: installId
            cachedInstallId = id
            cachedToken = token
            // 落盘失败不影响"这一次已经能用"：下次启动会重新注册一次（后端那边多一条绑定记录）
            try {
                store.write(id, token)
            } catch (e: CancellationException) {
                throw e
            } catch (_: Exception) {
            }
            return true
        } catch (e: CancellationException) {
            // ⛔ 协程取消**原样抛**：当成"注册失败"会让调用方在已经被取消的上下文里继续干活
            //    （司机端语音播报踩过同一个坑：CancellationException 被 catch(Exception) 吃掉，
            //     结果"打断"退化成"再喊一嗓子"）
            throw e
        } catch (_: Exception) {
            // 离线 / 后端不可达 / 服务端还没发版 —— 全按"这次没注册上"处理，静默返回
            return false
        } finally {
            registering = false
        }
    }

    companion object {
        /**
         * 两次注册**尝试**的最小间隔（毫秒）。
         *
         * 为什么需要它：补注册挂在拦截器上（任何一发请求发现头是空的就会来一次），
         * 后端长时间不可达时，没有节流就等于"用户每点一下，就多一发注定失败的注册请求"。
         */
        const val RETRY_COOLDOWN_MS = 60_000L
    }
}
