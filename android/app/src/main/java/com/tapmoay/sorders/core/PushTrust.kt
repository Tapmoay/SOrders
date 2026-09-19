package com.tapmoay.sorders.core

/**
 * 服务端推来的东西，本机**该信到什么程度**（纯函数，不碰 Android API，可单测）。
 *
 * 为什么要有这一层：Socket.IO 那条链路上，负载是"服务端说什么客户端信什么"——
 * 投给哪个房间（`emit_to_user` → `user_{id}`）与 `type` 叫什么全由后端决定，
 * 客户端从不核对（2026-09-19 报告 P1-4）。后果是**发错了人**的通知会在别人手机上响、
 * 进别人通知栏，而任何写入路径都能指定 `order.*` 命名空间去冒充派单。
 * 判定抽成纯函数，才有廉价的单测钉住它——这一层的 bug 和本仓库其它"静默失效"一样：
 * 不报错、界面上也看不出来，只有"这次没响 / 响错人了"。
 */
object PushTrust {

    /**
     * 单号最大能有多大。`orders.id` 是库里的 INT，合法单号必定 ≤ `Int.MAX_VALUE`；
     * 超过它的值不是"一个很大的单号"，而是**不成立的负载**。
     *
     * ⛔ 为什么必须在这里拦：下游 [NotifyCenter] 用 `orderId.toInt()` 当通知 id 与
     *    `PendingIntent` 的 requestCode，而 Long→Int 是**回绕**不是截断——
     *    相差 2^32 的两个单号会落到同一个通知 id（后一条把前一条**盖掉**）、
     *    同一个 requestCode（点旧通知打开的是新单）。负数/非数字同理。
     */
    const val MAX_ORDER_ID = Int.MAX_VALUE.toLong()

    /**
     * 这条负载是不是发给我的。
     *
     * 判据**只看一个方向**：带了 `recipient_id` 且不等于我 → 丢。
     * - 不带 `recipient_id` 一律放行：派单员的 `role_dispatchers` 广播
     *   （`{"type":"dispatcher.pending_pool"}`）与订单实时事件
     *   （`{"type":"order.assigned","order_id":…}`）**本来就没有收件人**——
     *   那是发给一个房间的，不是发给某个人的，按它拦会把派单员的新单提醒全杀掉。
     *   单条站内信（`notification` 里的对象、`sync` 回补的每一项）则一定有 `recipient_id`。
     * - 认不出当前用户（还没拿到会话）时也放行：拦下来的代价是司机漏单，
     *   而漏单在这套系统里是**没有任何人会发现**的那种失败。
     */
    fun acceptNotification(n: Map<*, *>?, myUserId: Long?): Boolean {
        if (n == null) return true
        val rid = (n["recipient_id"] as? Number)?.toLong() ?: return true
        return myUserId == null || rid == myUserId
    }

    /**
     * 这个 `type` 是不是本 App 认识的订单事件（**白名单**）。
     *
     * 用途只有一个：决定这条站内信的系统通知走哪条渠道（见 [RealtimeHub]）。
     * 不在白名单里的 `order.*` **不丢**，降级成普通消息通知——丢一条真消息的代价
     * 比多显示一条大得多；但也不许它冒充「派单与新单」：那条渠道是高优先级横幅 +
     * 点开直达某一单，是"伪造锁屏通知"最好用的道具。
     *
     * ⚠️ 清单来自后端真实在发的取值（`services/message_center.py`、`services/push_events.py`）；
     *    后端新增 `order.*` 事件时要同步这里，否则新事件只是降级成普通消息（不丢，但不再有订单渠道）。
     */
    val ORDER_TYPES: Set<String> = setOf(
        "order.assigned",
        "order.cancelled",
        "order.cancelled_dispatcher",
        "order.created",
        "order.delivered",
        "order.delivered_dispatcher",
        "order.delivered_driver",
        "order.dispatched",
        "order.driver_ack",
        "order.driver_ack_dispatcher",
        "order.freight.updated",
        "order.navigation.filled",
        "order.recalled",
        "order.revoked",
    )

    fun isOrderEvent(type: String): Boolean = type in ORDER_TYPES

    /** 单号可能躺在 `payload` 里，也可能在顶层——两处都认；越界/非数字一律 null（不是回绕） */
    fun orderIdOf(data: Map<*, *>?): Long? {
        val payload = data?.get("payload") as? Map<*, *>
        val v = payload?.get("order_id") ?: data?.get("order_id")
        val id = (v as? Number)?.toLong() ?: return null
        return if (id in 1..MAX_ORDER_ID) id else null
    }

    /**
     * 点通知进来的 intent 能不能信。
     *
     * ⛔ 为什么 extra 本身不算凭据：[MainActivity] 是 LAUNCHER + `exported="true"`
     *    （桌面要能拉起它，见清单里的注释），**任何 App** 都能发一个带
     *    `sorders_order_id=<任意单号>` 的 intent 进来——那会打断司机正在响的新单播报，
     *    而且日志里看不出是谁干的。所以只有"本机 [NotifyCenter] 建通知时附上的随机串"
     *    对得上才采信；对不上就整条忽略（不清会话、不崩、不提示——那是别人的 intent，不是我们的会话问题）。
     */
    fun trustedOrderId(orderId: Long, token: String?, mine: String?): Long? =
        if (orderId in 1..MAX_ORDER_ID && mine != null && token == mine) orderId else null

    /**
     * 握手是被**服务端拒绝**了，还是网络不通？
     *
     * 判据决定了要不要把用户踢回登录页，所以必须说得清"凭什么这么说"。依据是
     * socket.io-client 2.1.0 的真实行为（`Socket.onpacket`，反编译核对过）：
     * - 服务端拒绝时，服务器回的是一个 **CONNECT_ERROR 包**（python-socketio 的 `connect`
     *   处理器 `return False` 就发它），客户端把**包里的数据原样**抛给 `connect_error`——
     *   所以参数是 `{"message":"Connection rejected by server"}` 解出来的 Map/JSONObject
     *   或 String：**服务器跟我们说话了**。
     * - 网络不通/服务没起来时参数是 `IOException`/`EngineIOException` 这类异常对象
     *   （manager 的 `error` 事件转发过来的）：**根本没人回话**。
     * 于是判据 = 「参数不是异常对象」。刻意**不**写成 `is JSONObject` 白名单：多一种
     * 服务端表达方式就少拦一次，而漏判的方向是"继续重连"（可恢复），不是"把人踢下线"。
     *
     * ⛔ 反过来判（认不出就当被拒）会让信号差的司机被踢回登录页——那比多等几次重连糟得多。
     *    协议不匹配那种（v2 客户端连 v3 服务端）客户端合成的是 SocketIOException，
     *    也落在这里=按"连不上"处理，正确。
     */
    fun isServerRefusal(err: Any?): Boolean = err != null && err !is Throwable
}
