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
    val api by lazy { ApiClient.create(tokenStore, onSessionExpired = { clearSession() }) }
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
     * 点通知进来时带的单号，由 AppRoot 消费后直达订单详情。
     * 放在容器里而不是直接导航：通知可能在 Activity 还没建好时到达（冷启动），
     * 直接 navigate 会丢。
     */
    val pendingOrderId = MutableStateFlow<Long?>(null)

    private val appScope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)

    /** 401 时清除本地会话；AppRoot 观察 sessionFlow 会自动跳回登录页 */
    fun clearSession() {
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