package com.tapmoay.sorders.core

import android.content.Context
import com.tapmoay.sorders.data.repo.AppRepository
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.launch

/** 应用级服务容器（手动依赖注入，避免引入重型 DI 框架） */
class AppContainer(val context: Context) {

    val appContext: Context = context.applicationContext

    val tokenStore by lazy { TokenStore(appContext) }

    /**
     * 设备身份（FEAT-0018 账号↔设备绑定与风控）：App 自己生成的 `install_id` + 后端发的设备 token。
     *
     * ⛔ 不是 IMEI / MAC / 序列号（读不到、也是隐私红线）；为什么用"App 实例 ID"、
     *    以及注册不上时怎么办，都写在 [DeviceId] 的文件头。
     */
    val deviceId by lazy { DeviceId(PrefsDeviceIdStore(appContext)) }

    // 401 的**原因**从拦截器一路带到界面（BUG-0006）：被顶号 / 被停用 / 改密码 / 令牌过期
    // 四种处置完全不同，原来只有一句写死的「登录已失效，请重新登录」。
    val api by lazy {
        ApiClient.create(
            tokenStore,
            deviceId,
            // 任何一发请求发现设备头是空的（这台还没注册上）就来这里补一次：后台、静默、有节流
            onDeviceIdMissing = { ensureDeviceRegistered() },
            onSessionExpired = { reason -> clearSession(reason) },
        )
    }
    val repo by lazy { AppRepository(api) }
    val socketManager by lazy { SocketManager() }
    val realtimeHub by lazy { RealtimeHub(this) }
    val tts by lazy { TtsManager(appContext) }
    val beepManager by lazy { BeepManager() }

    /** 提醒设置（语音开关/重复次数/后台接收），同步可读——Socket 回调与服务里都要用 */
    val alertPrefs by lazy { AlertPrefs(appContext) }

    /** 「这条界面提示已经出现过几次」——解释性的话最多出现 3 次，同步可读（合成时要判画不画） */
    val hintPrefs by lazy { HintPrefs(appContext) }

    /** 系统通知出口（本 App 以前一条系统通知都不发，见 NotifyCenter 注释） */
    val notifyCenter by lazy { NotifyCenter(appContext, alertPrefs) }

    /** 司机端「来单了」语音播报 */
    val newOrderPlayer by lazy { NewOrderPlayer(appContext, tts, alertPrefs) }

    /** 收到新通知提示音（订单/消息），及时察觉 */
    fun beep() = beepManager.beep()
    val locationManager by lazy { AmapLocationManager(appContext) }

    /** 会话失效计数（供 UI Toast 提示） */
    val sessionExpiredTick = MutableStateFlow(0)

    /**
     * 最近一次会话失效的**原因**（服务端说的原话；拿不到就是 null）。
     *
     * ⚠️ 2026-10-03（E2E 走查 BUG-0006）：原来只有 [sessionExpiredTick]，提示语写死在界面上
     * （「登录已失效，请重新登录」）—— 被顶号 / 被停用 / 改了密码 / 令牌过期四种原因
     * 在用户眼里是同一句话，而处置办法完全不同（重登 / 找派单员 / 别再乱试）。
     * 服务端 401 的正文里已经写明原因，这里只负责把它**原样带到界面**，⛔ 不在这里改口径。
     */
    val sessionExpiredReason = MutableStateFlow<String?>(null)

    /**
     * 点通知进来时带的单号，由 AppRoot 消费后直达订单详情。
     * 放在容器里而不是直接导航：通知可能在 Activity 还没建好时到达（冷启动），
     * 直接 navigate 会丢。
     */
    val pendingOrderId = MutableStateFlow<Long?>(null)

    private val appScope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)

    /**
     * 让这台设备拿到 [DeviceId] 里的 token（幂等：已经有 token 时直接返回；离线失败下次再说）。
     *
     * 调用点只有两个：① [com.tapmoay.sorders.SOrdersApp.onCreate]（冷启动打一发）
     * ② 拦截器发现设备头是空的时（见 [ApiClient.create] 的 `onDeviceIdMissing`）。
     *
     * ⛔ 这是**尽力而为**的一件事：注册不上不许影响任何业务 —— 用户照样要能登录、能看单，
     *    后端那边只是暂时把请求当成没带设备信息。所以这里连异常都不往外抛。
     */
    fun ensureDeviceRegistered() {
        // ⚠️ 换到 IO：`api` 是懒加载的，它首次构造时会同步探一次后端地址
        //    （见 ApiEndpoint.baseUrl 的 /health 探测），放主线程上就是启动时卡一下
        appScope.launch(Dispatchers.IO) {
            try {
                deviceId.ensureRegistered(api.deviceApi)
            } catch (e: kotlinx.coroutines.CancellationException) {
                throw e
            } catch (_: Exception) {
                // ⛔ 注册不上不许影响任何一件事（也刻意不打日志：这本来就是允许静默失败的一步）
            }
        }
    }

    /** 401 时清除本地会话；AppRoot 观察 sessionFlow 会自动跳回登录页 */
    fun clearSession(reason: String? = null) {
        sessionExpiredReason.value = reason
        sessionExpiredTick.value += 1
        // 退出登录 = 这台手机不该再为上一个账号响铃、也不该继续挂着常驻通知
        newOrderPlayer.stop()
        AlertService.stop(appContext)
        appScope.launch {
            tokenStore.clear()
            // TTS 引擎在这里销毁（而不是在 Activity.onDestroy）：退出界面后
            // 后台服务还活着要能说话，一关界面就销毁会让"后台收到的单没声音"
            tts.shutdown()
        }
    }
}