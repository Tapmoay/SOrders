package com.tapmoay.sorders.core

import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import android.util.Log
import com.tapmoay.sorders.SOrdersApp
import com.tapmoay.sorders.ui.nav.Role
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

/**
 * 后台接收派单的常驻服务（只给"关掉 App 也要收到单"这件事用）。
 *
 * ### 为什么必须有它
 * 实时消息走的是 Socket.IO **长连接**，而长连接是进程级的：
 * App 退回后台后，安卓随时可以杀进程、Doze 会掐网络——表现就是
 * 「司机手机一声不响」，而这恰恰是最不能出错的一件事。
 * 不依赖厂商推送通道（本项目没有也不会用 FCM：国内机型没有 Google 服务，
 * 各家推送要分别接 SDK）能长期活着的办法只有前台服务。
 *
 * ### 它自己不干活
 * 业务判定全在 [RealtimeHub]（进程级，Application 里就有了），这个服务只做三件事：
 * 1. **把进程按住**，并且显式触发一次 [RealtimeHub]（App 是被服务拉起来的时，
 *    界面从没创建过它——不触发就"服务活着但没人连 Socket"）；
 * 2. 挂一条常驻通知：让用户知道它在后台收单，点进去能关掉（不做隐形后台）；
 * 3. 会话没了（退出登录）就自己退场，不留一个空转的常驻通知。
 */
class AlertService : Service() {

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)

    private val container: AppContainer
        get() = (application as SOrdersApp).container

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        _running.value = true
        goForeground()
        // ⚠️ 这一行不是装饰：RealtimeHub 是 lazy 的，界面没起过就没有实例，
        //    也就没有人去连 Socket（"服务在跑但收不到消息"就是这么来的）。
        container.realtimeHub
        scope.launch { keepConnected() }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        goForeground()
        return START_STICKY
    }

    override fun onDestroy() {
        _running.value = false
        scope.cancel()
        super.onDestroy()
    }

    /** 保证长连接在，并在退出登录时退场 */
    private suspend fun keepConnected() {
        val session = container.tokenStore.current()
        if (session == null) {
            stopSelf()
            return
        }
        container.socketManager.connect(
            ApiEndpoint.baseUrl,
            session.token,
            container.realtimeHub.lastNotificationId.value,
        )
        container.tokenStore.sessionFlow.collect { s ->
            if (s == null) {
                stopSelf()
            } else {
                // 换账号/换 token 后重连（connect 是幂等的，已连则跳过）
                container.socketManager.connect(
                    ApiEndpoint.baseUrl,
                    s.token,
                    container.realtimeHub.lastNotificationId.value,
                )
            }
        }
    }

    private fun goForeground() {
        val allowed = container.notifyCenter.canPost()
        val text = if (allowed) {
            "有新派单会立刻提醒你"
        } else {
            // 说清楚"现在收不到"，而不是让用户以为一切正常
            "通知权限没开，现在只会在 App 里显示"
        }
        val n = container.notifyCenter.serviceNotification(text)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            // API 34 起必须用清单里声明过的类型。用 specialUse 而不是 dataSync：
            // Android 15 对 dataSync 有"每 24 小时累计 6 小时"的硬上限，
            // 司机的手机是要整天挂着的，被系统掐掉就等于又收不到单了。
            val type = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
                ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE
            } else {
                ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC
            }
            startForeground(SERVICE_NOTIFICATION_ID, n, type)
        } else {
            startForeground(SERVICE_NOTIFICATION_ID, n)
        }
        Log.i(NewOrderPlayer.TAG, "后台接收服务已就绪（通知可用=$allowed）")
    }

    companion object {

        private val _running = MutableStateFlow(false)

        /** 供设置页显示"现在是否后台在收"（用户看不到状态就会反复开关试） */
        val running: StateFlow<Boolean> = _running.asStateFlow()

        /**
         * 启动常驻接收。
         *
         * ⚠️ Android 12+ 限制**后台启动前台服务**：只能在 App 可见时调用
         * （登录后、进主界面时）。开机与升级后由 [BootReceiver] 走系统豁免通道。
         * 调用失败不抛异常：收不到后台消息是"少一层保障"，不该让 App 崩。
         */
        fun start(context: Context) {
            try {
                val i = Intent(context, AlertService::class.java)
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                    context.startForegroundService(i)
                } else {
                    context.startService(i)
                }
            } catch (_: Exception) {
                // 后台启动被系统拒（IllegalStateException）：静默降级为"只在前台收"
            }
        }

        fun stop(context: Context) {
            try {
                context.stopService(Intent(context, AlertService::class.java))
            } catch (_: Exception) {
            }
        }

        /**
         * 按当前设置与角色对齐服务状态。**只能在 App 可见时调用**（见 [start]）。
         *
         * 抽成一个函数是因为有两个调用点：进主界面时、用户在「消息提醒」里拨开关时。
         * 两处各写一遍的话，迟早会出现"设置页显示开着、其实服务没起"这种没人能发现的错位。
         */
        fun sync(context: Context, role: Role?) {
            val container = (context.applicationContext as? SOrdersApp)?.container ?: return
            val shouldRun = container.tokenStore.cachedToken() != null &&
                    container.alertPrefs.backgroundEnabled(role)
            if (!shouldRun) {
                stop(context)
                return
            }
            // ⚠️ **即使已经在跑也要再 start 一次**（start 是幂等的，只会再走一遍 onStartCommand）。
            // 真机踩到的坑：进主界面时权限对话框还没点「允许」，那一刻 startForeground 的通知
            // 被系统丢掉了；用户随后点了允许，但**没有任何人重新发一次**——
            // 结果是"服务在后台收着单，通知栏里却什么都没有"，用户完全无从判断。
            start(context)
        }
    }
}
