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

    /** 收到新通知提示音（订单/消息），及时察觉 */
    fun beep() = beepManager.beep()
    val locationManager by lazy { AmapLocationManager(appContext) }

    /** 会话失效计数（供 UI Toast 提示） */
    val sessionExpiredTick = MutableStateFlow(0)

    private val appScope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)

    /** 401 时清除本地会话；AppRoot 观察 sessionFlow 会自动跳回登录页 */
    fun clearSession() {
        sessionExpiredTick.value += 1
        appScope.launch { tokenStore.clear() }
    }
}