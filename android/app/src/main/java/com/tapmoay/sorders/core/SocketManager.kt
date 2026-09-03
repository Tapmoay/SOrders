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

    val isConnected: Boolean get() = socket?.connected() == true

    fun connect(baseUrl: String, token: String, lastNotificationId: Long = 0L) {
        if (socket?.connected() == true) return
        disconnect()
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
            s.on(Socket.EVENT_CONNECT_ERROR) { Log.w("SOrdersSock", "CONNECT_ERROR " + it?.toString()); _connected.tryEmit(false) }
            socket = s
            s.connect()
        } catch (_: Exception) {
            // 地址非法等：静默失败，由 UI 层按需提示
        }
    }

    /** socket.io-client 2.1.0 以 org.json.JSONObject 传递事件负载，转成 Map 供业务层使用 */
    private fun toMapOfJson(obj: org.json.JSONObject): Map<String, Any?> {
        val out = LinkedHashMap<String, Any?>()
        val it = obj.keys()
        while (it.hasNext()) {
            val k = it.next()
            out[k] = obj.opt(k) as Any?
        }
        return out
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