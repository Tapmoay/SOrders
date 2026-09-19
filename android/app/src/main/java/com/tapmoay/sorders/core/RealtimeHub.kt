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

    /**
     * 最近播报过的事件（去重键 → 时间戳）。
     *
     * 为什么需要：同一次派单后端会从**两条链路**各推一次——
     * `notification`（站内信，带 speech_important）+ `realtime`（状态事件），
     * 不去重的话司机听到的是「来单了来单了」连着放两组。
     */
    private val announced = mutableMapOf<String, Long>()

    init {
        // 跟踪当前角色（语音播报仅司机）
        scope.launch {
            container.tokenStore.sessionFlow.collect { s ->
                if (s != null) {
                    role = Role.fromKey(s.role)
                    // 登录 / App 重启会话恢复：确保 Socket 长连接（幂等，已连接则跳过）
                    container.socketManager.connect(
                        ApiEndpoint.baseUrl,
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
                val title = (n?.get("title") as? String) ?: ""
                val content = (n?.get("content") as? String) ?: ""
                val orderId = orderIdOf(n)
                // ① 系统通知：让消息像别的 App 一样进通知栏/锁屏。
                //    在这之前 App **一条系统通知都没发过**（只在自己界面里显示），
                //    锁屏的手机上什么都看不到——这是"不像别的软件"的根因。
                if (title.isNotBlank()) {
                    if (ntype.startsWith("order.")) {
                        container.notifyCenter.postOrder(orderId, title, content)
                    } else {
                        container.notifyCenter.postMessage(title, content)
                    }
                }
                if (ntype.startsWith("order.")) {
                    _refreshOrders.tryEmit(Unit)
                    // 提示音：有消息及时察觉（司机另有语音播报）
                    container.beep()
                }
                // ② 司机语音：新单重复播报、撤回只说一遍（判定逻辑见 NewOrderAlert）
                announce(ntype, orderId, title)
            }
            "realtime" -> {
                // 司机的动作 / 撤回 / 完成 → 立刻闭嘴（接单后还在喊"来单了"会让司机怀疑接没接上）
                if (NewOrderAlert.shouldStop(e.type)) container.newOrderPlayer.stop()
                when (e.type) {
                    "order.assigned" -> {
                        _refreshOrders.tryEmit(Unit)
                        announce(e.type, orderIdOf(e.data), "")
                    }
                    "order.revoked" -> {
                        _refreshOrders.tryEmit(Unit)
                        announce(e.type, orderIdOf(e.data), "")
                    }
                    "order.delivered", "order.delivered_driver", "order.delivered_dispatcher",
                    "order.cancelled", "order.cancelled_dispatcher", "order.dispatched", "order.recalled",
                    "order.driver_ack", "order.driver_ack_dispatcher", "order.created", "order.freight.updated" ->
                        _refreshOrders.tryEmit(Unit)
                    "dispatcher.pending_pool" -> _refreshOrders.tryEmit(Unit)
                    "ledger.updated" -> _refreshLedger.tryEmit(Unit)
                }
            }
        }
    }

    /**
     * 司机语音播报。**只有司机会响**（判定在 [NewOrderAlert.isSpoken]）：
     * 派单员/货主大部分时间在电脑前，手机上再放语音是打扰，
     * 而且「来单了」对他们本来就是**错的信息**——那不是他们的活。
     */
    private fun announce(type: String, orderId: Long?, title: String) {
        if (type.isBlank()) return
        val ev = NewOrderAlert.eventOf(type, orderId, title) ?: return
        if (!NewOrderAlert.isSpoken(role)) return
        val now = System.currentTimeMillis()
        if (NewOrderAlert.isDuplicate(announced, ev.dedupeKey, now)) return
        announced[ev.dedupeKey] = now
        container.newOrderPlayer.play(
            ev.kind,
            NewOrderAlert.planFor(ev.kind, container.alertPrefs.repeatTimes),
        )
    }

    /** 单号可能躺在站内信的 payload 里，也可能在 realtime 事件的顶层——两处都认 */
    private fun orderIdOf(data: Map<*, *>?): Long? {
        val payload = data?.get("payload") as? Map<*, *>
        val v = payload?.get("order_id") ?: data?.get("order_id")
        return (v as? Number)?.toLong()
    }

    /** 登录/重连成功后同步未读数（REST 兜底） */    suspend fun syncUnreadFromApi() {
        runCatching {
            val c = container.repo.unreadCount()
            _unreadCount.value = c.count
        }
    }

    /** 本地操作（如软删除订单）成功后通知订单列表刷新 */
    fun notifyOrdersChanged() {
        _refreshOrders.tryEmit(Unit)
    }
}