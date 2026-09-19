package com.tapmoay.sorders.core

import com.tapmoay.sorders.data.remote.dto.SocketEvent
import android.util.Log
import io.socket.client.IO
import io.socket.client.Socket
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.asSharedFlow

/**
 * 后端 Socket.IO 协议：
 * - 连接握手 auth: { token: JWT, lastNotificationId: 最近通知ID }
 * - 服务端事件：sync / notification / unread_count / realtime
 * - realtime payload: { type: order.assigned|order.revoked|order.dispatched|order.recalled|
 *   order.delivered|order.delivered_driver|order.cancelled|order.driver_ack|dispatcher.pending_pool, order_id, reason? }
 */
class SocketManager {

    private var socket: Socket? = null

    private val _events = MutableSharedFlow<SocketEvent>(extraBufferCapacity = 64)
    val events: SharedFlow<SocketEvent> = _events.asSharedFlow()

    private val _connected = MutableSharedFlow<Boolean>(extraBufferCapacity = 2)
    val connected: SharedFlow<Boolean> = _connected.asSharedFlow()

    /**
     * 服务端**明确拒绝**了这次会话（握手被拒 / 收到 `session_revoked`）。
     *
     * 与 [connected] = false 是两件事：那个只说"现在没连着"（网络抖动也会），
     * 这个说"再连也不会成功，令牌已经不算数了"。区别对待的理由见 [PushTrust.isServerRefusal]。
     */
    private val _sessionRefused = MutableSharedFlow<Unit>(extraBufferCapacity = 1)
    val sessionRefused: SharedFlow<Unit> = _sessionRefused.asSharedFlow()

    /** 一次会话只报一次：握手被拒后重连还会再抛几条，不该弹几个「登录已失效」 */
    @Volatile
    private var refusalNotified = false

    val isConnected: Boolean get() = socket?.connected() == true

    fun connect(baseUrl: String, token: String, lastNotificationId: Long = 0L) {
        if (socket?.connected() == true) return
        disconnect()
        refusalNotified = false
        try {
            val opts = IO.Options().apply {
                auth = mapOf(
                    "token" to token,
                    "lastNotificationId" to lastNotificationId.toString(),
                )
                reconnection = true
                reconnectionDelay = 1000
                reconnectionDelayMax = 10000
                randomizationFactor = 0.5
                timeout = 10000
                // 注意：不注入 transportOptions（engine.io 2.1.0 对空字段会 NPE，曾致登录闪退）
            }
            val s = IO.socket(baseUrl.trimEnd('/'), opts)
            listOf("sync", "notification", "unread_count", "realtime").forEach { ev ->
                s.on(ev) { args ->
                    if (args.isEmpty()) return@on
                    val raw = args[0]
                    @Suppress("UNCHECKED_CAST")
                    val data: Map<String, Any?> = when (raw) {
                        is Map<*, *> -> raw as Map<String, Any?>
                        is org.json.JSONObject -> toMapOfJson(raw)
                        else -> return@on
                    }
                    Log.i("SOrdersSock", "EVENT " + ev + " type=" + data["type"] + " keys=" + data.keys)
                    _events.tryEmit(SocketEvent(ev, data))
                }
            }
            s.on(Socket.EVENT_CONNECT) { Log.i("SOrdersSock", "CONNECTED to " + baseUrl); _connected.tryEmit(true) }
            s.on(Socket.EVENT_DISCONNECT) { Log.w("SOrdersSock", "DISCONNECTED"); _connected.tryEmit(false) }
            s.on(Socket.EVENT_CONNECT_ERROR) { args ->
                val err = args?.firstOrNull()
                Log.w("SOrdersSock", "CONNECT_ERROR " + err?.toString())
                _connected.tryEmit(false)
                // 服务端拒绝（令牌被吊销 / 账号停用 / 会话被撤销）→ 重试一辈子也不会好，
                // 必须让用户去重新登录；网络不通只是重连（判据与理由见 PushTrust.isServerRefusal）。
                // ⛔ 这里原来只打一行日志：司机"以为在连着、其实一条新单都收不到"（报告 C-3）。
                if (PushTrust.isServerRefusal(err)) notifyRefused("握手被拒绝")
            }
            // 后端在登出 / 改密码 / 停用之后**主动推**这个事件，然后断开连接
            // （服务端撤销会话的信号，不是普通断线）。令牌此时已经作废，
            // 所以不重连、直接走清会话那条链。
            s.on("session_revoked") {
                Log.w("SOrdersSock", "SESSION_REVOKED")
                notifyRefused("会话被服务端撤销")
            }
            socket = s
            s.connect()
        } catch (_: Exception) {
            // 地址非法等：静默失败，由 UI 层按需提示
        }
    }

    /**
     * socket.io-client 2.1.0 以 org.json.JSONObject 传递事件负载，转成 Map 供业务层使用。
     *
     * ⚠️ **必须深转**（嵌套对象/数组也要转）。踩过的坑：
     * 这里原来只转最外层，于是 `data["notification"]` 仍然是个 JSONObject，
     * 而业务层写的是 `as? Map<*, *>` —— 拿到 null，整条站内信被**静默丢掉**：
     * 站内信里的 type/title/content/order_id 全都读不到。
     * 表现是"司机收到了 realtime 事件、却没收到那条新派单消息"，
     * 而且不会有任何报错。凡是嵌套结构（notification / payload / notifications 数组）都靠这个函数。
     */
    private fun toMapOfJson(obj: org.json.JSONObject): Map<String, Any?> {
        val out = LinkedHashMap<String, Any?>()
        val it = obj.keys()
        while (it.hasNext()) {
            val k = it.next()
            out[k] = plain(obj.opt(k))
        }
        return out
    }

    /** 通知"这次会话已经没救了"（去重：一次会话只报一次） */
    private fun notifyRefused(why: String) {
        if (refusalNotified) return
        refusalNotified = true
        Log.w("SOrdersSock", "会话失效（$why）→ 清会话，不再重连")
        _sessionRefused.tryEmit(Unit)
    }

    /** 递归把 JSONObject/JSONArray 摊成 Map/List，其余原样返回 */
    private fun plain(v: Any?): Any? = when (v) {
        is org.json.JSONObject -> toMapOfJson(v)
        is org.json.JSONArray -> (0 until v.length()).map { plain(v.opt(it)) }
        else -> v
    }

    fun disconnect() {
        try {
            socket?.off()
            socket?.disconnect()
        } catch (_: Exception) {
        } finally {
            socket = null
        }
    }
}