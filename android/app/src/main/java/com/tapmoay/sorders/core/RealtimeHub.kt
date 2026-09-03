package com.tapmoay.sorders.core

import com.tapmoay.sorders.BuildConfig
import com.tapmoay.sorders.data.remote.dto.SocketEvent
import com.tapmoay.sorders.ui.nav.Role
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.*
import kotlinx.coroutines.launch

/**
 * Socket.IO 事件中枢：
 * - 维护未读数与最近通知 ID（重连时回传后端补拉）
 * - 关键订单事件触发列表刷新信号（refreshOrders）
 * - 司机端对新单/撤回进行语音播报（speech_important 消息同样播报）
 */
class RealtimeHub(private val container: AppContainer) {

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)

    private val _unreadCount = MutableStateFlow(0L)
    val unreadCount: StateFlow<Long> = _unreadCount.asStateFlow()

    private val _lastNotificationId = MutableStateFlow(0L)
    val lastNotificationId: StateFlow<Long> = _lastNotificationId.asStateFlow()

    private val _refreshOrders = MutableSharedFlow<Unit>(extraBufferCapacity = 8)
    val refreshOrders: SharedFlow<Unit> = _refreshOrders.asSharedFlow()

    private val _newMessages = MutableSharedFlow<Unit>(extraBufferCapacity = 8)
    val newMessages: SharedFlow<Unit> = _newMessages.asSharedFlow()

    private val _refreshLedger = MutableSharedFlow<Unit>(extraBufferCapacity = 8)
    val refreshLedger: SharedFlow<Unit> = _refreshLedger.asSharedFlow()

    private var role: Role = Role.SHIPPER

    init {
        // 跟踪当前角色（语音播报仅司机）
        scope.launch {
            container.tokenStore.sessionFlow.collect { s ->
                if (s != null) {
                    role = Role.fromKey(s.role)
                    // 登录 / App 重启会话恢复：确保 Socket 长连接（幂等，已连接则跳过）
                    container.socketManager.connect(
                        BuildConfig.API_BASE_URL,
                        s.token,
                        lastNotificationId.value,
                    )
                } else {
                    container.socketManager.disconnect()
                    _unreadCount.value = 0
                }
            }
        }
        // 处理 Socket 事件
        scope.launch {
            container.socketManager.events.collect { handle(it) }
        }
    }

    private fun handle(e: SocketEvent) {
        when (e.name) {
            "unread_count" -> {
                _unreadCount.value = (e.data["count"] as? Number)?.toLong() ?: 0L
            }
            "sync" -> {
                val list = e.data["notifications"]
                if (list is List<*>) {
                    (list.lastOrNull() as? Map<*, *>)?.let { last ->
                        (last["id"] as? Number)?.let { id ->
                            if (id.toLong() > _lastNotificationId.value) _lastNotificationId.value = id.toLong()
                        }
                    }
                }
                _unreadCount.value = (e.data["unread_count"] as? Number)?.toLong() ?: 0L
            }
            "notification" -> {
                _unreadCount.value += 1
                val n = e.data["notification"] as? Map<*, *>
                val id = (n?.get("id") as? Number)?.toLong() ?: 0L
                if (id > _lastNotificationId.value) _lastNotificationId.value = id
                _newMessages.tryEmit(Unit)
                // 通知即状态变化（新订单/派单/接单/送达/撤销等），列表自动刷新
                val ntype = (n?.get("type") as? String) ?: ""
                if (ntype.startsWith("order.")) {
                    _refreshOrders.tryEmit(Unit)
                    // 提示音：有消息及时察觉（司机另有语音播报）
                    container.beep()
                }
                val speechImportant = (n?.get("speech_important") as? Boolean) == true
                val title = (n?.get("title") as? String) ?: ""
                if (role == Role.DRIVER && speechImportant && title.isNotBlank()) {
                    container.tts.speak(title)
                }
            }
            "realtime" -> when (e.type) {
                "order.assigned" -> {
                    _refreshOrders.tryEmit(Unit)
                    if (role == Role.DRIVER) container.tts.speak("您有新的送货任务，请及时查看")
                }
                "order.revoked" -> {
                    _refreshOrders.tryEmit(Unit)
                    if (role == Role.DRIVER) container.tts.speak("有任务被撤回，请查看最新列表")
                }
                "order.delivered", "order.delivered_driver", "order.delivered_dispatcher",
                "order.cancelled", "order.cancelled_dispatcher", "order.dispatched", "order.recalled",
                "order.driver_ack", "order.driver_ack_dispatcher", "order.created", "order.freight.updated" -> _refreshOrders.tryEmit(Unit)
                "dispatcher.pending_pool" -> _refreshOrders.tryEmit(Unit)
                "ledger.updated" -> _refreshLedger.tryEmit(Unit)
            }
        }
    }

    /** 登录/重连成功后同步未读数（REST 兜底） */
    suspend fun syncUnreadFromApi() {
        runCatching {
            val c = container.repo.unreadCount()
            _unreadCount.value = c.count
        }
    }
}