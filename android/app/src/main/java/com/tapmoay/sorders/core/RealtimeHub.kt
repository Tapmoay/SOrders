package com.tapmoay.sorders.core

import com.tapmoay.sorders.data.remote.dto.SocketEvent
import com.tapmoay.sorders.ui.common.UnitConv
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
 * - 司机端对新单/撤回、**派单员端对"有待派单的新订单"**进行语音播报
 *   （判定在 core/NewOrderAlert.kt，按 角色 × 事件类型）。⚠️ **站内信的 `speech_important` 不会被播报**
 *   （2026-09-19 审计 R14-11 把这里原来那句"（speech_important 消息同样播报）"删掉了：
 *   全仓库 Android 侧没有任何一处读这个字段，只有旧网页端读；写着它就会让人以为已经有这功能）
 */
class RealtimeHub(private val container: AppContainer) {

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)

    private val _unreadCount = MutableStateFlow(0L)
    val unreadCount: StateFlow<Long> = _unreadCount.asStateFlow()

    /**
     * 已收到的最大站内信 id。**初始值从本机读**（R14-13）：
     * 原来固定从 0 起，进程重启就归零 → 后端按最旧 200 条回补 → 断线期间的消息永远补不到。
     */
    private val _lastNotificationId = MutableStateFlow(
        runCatching { container.alertPrefs.lastNotificationId }.getOrDefault(0L)
    )
    val lastNotificationId: StateFlow<Long> = _lastNotificationId.asStateFlow()

    private val _refreshOrders = MutableSharedFlow<Unit>(extraBufferCapacity = 8)
    val refreshOrders: SharedFlow<Unit> = _refreshOrders.asSharedFlow()

    private val _newMessages = MutableSharedFlow<Unit>(extraBufferCapacity = 8)
    val newMessages: SharedFlow<Unit> = _newMessages.asSharedFlow()

    private val _refreshLedger = MutableSharedFlow<Unit>(extraBufferCapacity = 8)
    val refreshLedger: SharedFlow<Unit> = _refreshLedger.asSharedFlow()

    private var role: Role = Role.SHIPPER

    /**
     * 当前登录用户 id——核对"这条站内信是不是发给我的"要用（见 [PushTrust.acceptNotification]）。
     * 必须在 `connect()` **之前**赋值：握手成功后服务端立刻下发 `sync`，
     * 那一批回补消息要与实时消息走同一套判据。
     */
    private var userId: Long? = null

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
                    userId = s.userId
                    // 登录 / App 重启会话恢复：确保 Socket 长连接（幂等，已连接则跳过）
                    container.socketManager.connect(
                        ApiEndpoint.baseUrl,
                        s.token,
                        lastNotificationId.value,
                    )
                    // 单位换算（一车 = 8 方，2026-09-24）：**登录/恢复会话时拉一次**。
                    // 为什么放在这里：订单卡片、订单明细、账本小卡、下单页四处都要它，
                    // 而它们都没有"载入完成"这个共同点 —— 谁先打开就先显示"10 车 ≈ 80 方"，
                    // 晚打开的那一页不该显示成另一个样子。失败**静默**（换算只是多显示一个数，
                    // 它不该让任何列表变成错误页），下一次登录还会再试。
                    // ⛔ **按角色**决定要不要拉：这张表只有货主与派单员能读（后端 `require_roles`）。
                    //    以前不看角色地拉一次，司机每次登录/恢复会话都在后端留下一条 403 —— 而且是静默的，
                    //    界面上什么都看不到（走查报告 §5.3）。传的是**会话里的角色 key** `s.role`，
                    //    不是 App 的 `Role`：后者把 wholesaler 折成 SHIPPER，批发商会继续 403。
                    scope.launch { runCatching { UnitConv.ensure(container.repo, s.role) } }
                } else {
                    userId = null
                    container.socketManager.disconnect()
                    _unreadCount.value = 0
                    // 退出登录：把换算表也清掉（它是全库共用的一份，但**不该跨账号留着** ——
                    // 换个人登录时沿用上一个人的缓存，就会在别人的单上继续显示换算）
                    UnitConv.clear()
                    // 退出登录 / 未登录：**把回补游标清掉**（R14-13 的落盘带来的必然要求）。
                    // 游标是「本机这个人已经收到哪儿」的进度；换一个账号登录时若沿用上一个人的
                    // 游标，新账号那些 id 更小的未读消息会被后端全部过滤掉（比"补最旧的 200 条"更糟：
                    // 一条都补不到）。所以会话消失时归零，登录后从"全部"开始补。
                    _lastNotificationId.value = 0L
                    runCatching { container.alertPrefs.lastNotificationId = 0L }
                }
            }
        }
        // 处理 Socket 事件
        scope.launch {
            container.socketManager.events.collect { handle(it) }
        }
        // 握手被服务端拒绝 / 会话被撤销（`session_revoked`）：重试一辈子也不会好，
        // 所以走**已有的**清会话通道（`AppContainer.clearSession` → `sessionExpiredTick`
        // + `tokenStore.clear()`），用户看到「登录已失效，请重新登录」，
        // 而不是"以为还连着、其实一条新单都收不到"（2026-09-19 报告 C-3）。
        // ⛔ 网络不通**不**走这条链（判据见 [PushTrust.isServerRefusal]）：信号差不能把人踢下线。
        scope.launch {
            container.socketManager.sessionRefused.collect { reason ->
                // 服务端在 `session_revoked` 里写了原因（被顶号 / 登出 / 改密码 / 停用），
                // 一路带到界面上显示（BUG-0006）。
                if (container.tokenStore.cachedToken() != null) container.clearSession(reason)
            }
        }
    }

    private fun handle(e: SocketEvent) {
        when (e.name) {
            "unread_count" -> {
                _unreadCount.value = (e.data["count"] as? Number)?.toLong() ?: 0L
            }
            "sync" -> {
                // 断线回补（R14-13，2026-09-19 审计）。这里原来**只把游标往前推、列表整个丢掉**：
                // 而回补窗口本身也退化成"补最旧的 200 条"（后端已改），于是断线期间的消息
                // 既不会变成系统通知、也不会播报 —— 司机错过新单的三层提醒在重连这条路径上是空的。
                // 现在：① 逐条补发系统通知（白名单里的订单事件走订单通知，其余走消息通知）；
                //      ② 游标**落盘**（`AlertPrefs.lastNotificationId`），进程重启不再归零；
                //      ③ **补响**（2026-10-06 CHG-0055，台账 L-26）——回补的这一条也可能是
                //         "他还没听见的那一单"，判定见 [NewOrderAlert.ringbackOf]。
                val list = e.data["notifications"]
                // ③ 的候选：整批看完再决定补哪一条（"只补最新一条"这条口径要看到全批）
                val rungCandidates = mutableListOf<RingItem>()
                if (list is List<*>) {
                    list.forEach { item ->
                        val m = item as? Map<*, *> ?: return@forEach
                        // 回补的每一条也是站内信：同样只采信发给我的（判据一处实现，见 PushTrust）
                        if (!PushTrust.acceptNotification(m, userId)) return@forEach
                        val id = (m["id"] as? Number)?.toLong() ?: 0L
                        val ntype = (m["type"] as? String) ?: ""
                        val title = (m["title"] as? String) ?: ""
                        val content = (m["content"] as? String) ?: ""
                        if (title.isNotBlank()) {
                            if (PushTrust.isOrderEvent(ntype)) {
                                container.notifyCenter.postOrder(PushTrust.orderIdOf(m), title, content)
                            } else {
                                container.notifyCenter.postMessage(title, content, id)
                            }
                        }
                        // ③ 候选：回补里的这一条（含撤回/送达这类"不该响"的，由纯判定去挑）
                        rungCandidates += RingItem(ntype, PushTrust.orderIdOf(m), title)
                        if (ntype.startsWith("order.")) _refreshOrders.tryEmit(Unit)
                        bumpCursor(id)
                    }
                }
                // 断线 / 还没登录那段时间被派的单，在重连这一刻补响一声（判定见 [NewOrderAlert.ringbackOf]）
                ringback(rungCandidates)
                _unreadCount.value = (e.data["unread_count"] as? Number)?.toLong() ?: 0L
            }
            "notification" -> {
                // ⛔ 先判"这条是不是发给我的"（2026-09-19 报告 P1-4）：房间投递由后端决定，
                //    客户端不核对的话，任何一条发错人的通知都会在**别人**手机上响、进别人通知栏。
                //    判据只认 `recipient_id` 且只看一个方向（缺字段一律放行，理由见 PushTrust），
                //    所以派单员那种"没有收件人"的广播不受影响。
                val n = e.data["notification"] as? Map<*, *>
                if (!PushTrust.acceptNotification(n, userId)) return
                _unreadCount.value += 1
                val id = (n?.get("id") as? Number)?.toLong() ?: 0L
                bumpCursor(id)
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
                    // 走哪条渠道由**白名单**决定（P1-4）：认识的订单事件才进「派单与新单」
                    // （高优先级横幅 + 点开直达某一单），编出来的 order.* 降级成普通消息——
                    // 不丢，但不许它冒充派单（原来只判 `startsWith("order.")`）。
                    if (PushTrust.isOrderEvent(ntype)) {
                        container.notifyCenter.postOrder(orderId, title, content)
                    } else {
                        container.notifyCenter.postMessage(title, content, id)
                    }
                }
                // 列表刷新仍按 `order.` 前缀（不用白名单）：后端将来加一个 order.* 事件时，
                // 这里若也收紧就会"列表不刷新"而没人发现——那是本项目最讨厌的静默失效。
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
                if (NewOrderAlert.shouldStop(e.type)) {
                    container.newOrderPlayer.stop()
                    // 撤回/取消/接单之后，这一单的「新单」去重键必须作废（R14-14）：
                    // 否则撤回后 60 秒内重派给同一个司机，第二声会被去重吞掉、完全不响。
                    NewOrderAlert.forgetOnStop(announced, e.type, orderIdOf(e.data))
                }
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
                    // CHG-0040：派单员改了收货信息或货物明细（后端 order_products 三个写端点都会发
                    // orders.edited → 站内信 + 这条实时信号）—— 司机这边重拉一次就好。
                    // ⛔ 这个取值以前在这里**没有任何分支**：后端发了没人认，改单对司机完全无感。
                    "order.updated" -> _refreshOrders.tryEmit(Unit)
                    "dispatcher.pending_pool" -> _refreshOrders.tryEmit(Unit)
                    "ledger.updated" -> _refreshLedger.tryEmit(Unit)
                }
            }
        }
    }

    /**
     * 语音播报。**按 (角色 × 事件类型) 判**（[NewOrderAlert.speaks]）：
     * 司机听「有新派单」，派单员听「有新订单待派单」，货主一句都不听
     * （「来单了」对货主本来就是**错的信息**——他不是要跑车也不是要派单的那个人）。
     */
    private fun announce(type: String, orderId: Long?, title: String) {
        if (type.isBlank()) return
        // 站内信与 realtime 两条链路都会走到这里：撤回/取消这一类"该闭嘴了"的信号
        // 顺手把该单的新单去重键作废（R14-14），否则撤回后重派没人响。
        NewOrderAlert.forgetOnStop(announced, type, orderId)
        // 同一条作废口径也要落到盘上：内存那份随进程消失，而盘上那条"已响过"若留着，
        // 撤回之后重新派给同一个司机就会被它吞掉（R14-14 的原形）。
        forgetRungOnStop(type, orderId)
        val ev = NewOrderAlert.eventOf(type, orderId, title) ?: return
        if (!NewOrderAlert.speaks(role, ev.kind)) return
        val now = System.currentTimeMillis()
        if (NewOrderAlert.isDuplicate(announced, ev.dedupeKey, now)) return
        announced[ev.dedupeKey] = now
        // 落盘（2026-10-06 CHG-0055）：回补补响时靠它回答"这一声之前响过没有"，
        // ⛔ 少了这一行，每次冷启动重连都会把断线期间那批单**再响一遍**。
        markRung(ev.dedupeKey, now)
        container.newOrderPlayer.play(
            ev.kind,
            NewOrderAlert.planFor(ev.kind, container.alertPrefs.repeatTimes),
        )
    }


    /**
     * 回补补响（2026-10-06 CHG-0055，台账 L-26）。用户原话：「假如司机登录了账号，这时候有个订单
     * 派给他了，他就直接开始响铃……**那个铃声要响的，不是不响**」「断网期间：响过了就没必要，
     * 没响的话就要响」。
     *
     * ⛔ 缺口形状：`sync` 那条分支原来**只有系统通知、一声不响** —— 司机登录前 / 断网期间被派的单
     *    在通知栏里躺着，而人在车上不会翻通知栏：这条路径上"三层提醒"只有一层。
     * 判定在 [NewOrderAlert.ringbackOf]（纯函数、有单测）：只补还在等他的那一声、一次只补最新的一条。
     */
    private fun ringback(candidates: List<RingItem>) {
        if (candidates.isEmpty()) return
        val now = System.currentTimeMillis()
        val rung = NewOrderAlert.rungDecode(container.alertPrefs.rungKeys, now)
        val pick = NewOrderAlert.ringbackOf(candidates, role, rung) ?: return
        // 与实时那条路走**同一个入口**：播放、内存去重、落盘都在 announce 里。
        // 这里再判一遍"该不该响"就会有两处口径，而它们迟早会漂。
        announce(pick.type, pick.orderId, pick.title)
    }

    /** 把一条"响过了"记到盘上（失败静默：记不上最多多响一声，不能让它挡住播报）。 */
    private fun markRung(key: String, now: Long) {
        val seen = NewOrderAlert.rungDecode(container.alertPrefs.rungKeys, now)
        NewOrderAlert.markRung(seen, key, now)
        runCatching { container.alertPrefs.rungKeys = NewOrderAlert.rungEncode(seen) }
    }

    /**「这单结束了」时把盘上那条"已响过"也作废（与内存那份同一口径，见 [announce]）。 */
    private fun forgetRungOnStop(type: String, orderId: Long?) {
        if (orderId == null || !NewOrderAlert.shouldStop(type)) return
        val now = System.currentTimeMillis()
        val seen = NewOrderAlert.rungDecode(container.alertPrefs.rungKeys, now)
        val before = seen.size
        NewOrderAlert.forgetOnStop(seen, type, orderId)
        if (seen.size == before) return  // 盘上本来就没有这两个键：不必写一次
        runCatching { container.alertPrefs.rungKeys = NewOrderAlert.rungEncode(seen) }
    }

    /**
     * 推进"已收到的最大站内信 id"，并**落盘**（R14-13）。
     *
     * 只放内存的后果：进程被杀 → 重启后游标归零 → 后端回补的是最旧的 200 条 →
     * 断线期间的新单消息永远补不到。落盘之后重连带的是真实进度，回补窗口才有意义。
     */
    private fun bumpCursor(id: Long) {
        if (id <= _lastNotificationId.value) return
        _lastNotificationId.value = id
        runCatching { container.alertPrefs.lastNotificationId = id }
    }

    /**
     * 单号可能躺在站内信的 payload 里，也可能在 realtime 事件的顶层——两处都认。
     * 解析与边界（越界/负数/非数字 → null，不回绕）只有一处实现，见 [PushTrust.orderIdOf]。
     */
    private fun orderIdOf(data: Map<*, *>?): Long? = PushTrust.orderIdOf(data)

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