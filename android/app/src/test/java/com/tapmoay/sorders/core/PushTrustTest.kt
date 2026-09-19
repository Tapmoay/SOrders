package com.tapmoay.sorders.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 推送可信判据的单测（2026-09-19 报告 P1-4 / R2-NS-3 / C-3）。
 *
 * 这些断言的存在理由和「来单了」那组一样：这一层的错**没有表现**——
 * 放过了不该信的负载，是"响错人/响错内容"；拦掉了该信的负载，是"司机漏单"，
 * 两者都不报错、界面上也看不出来。所以两个方向都要钉住。
 */
class PushTrustTest {

    // ---- ① 这条站内信是不是发给我的（P1-4a） ----

    @Test
    fun `明确写着发给别人的通知一律丢`() {
        val n = mapOf("recipient_id" to 7L, "type" to "order.assigned", "title" to "新派单")
        assertFalse(PushTrust.acceptNotification(n, myUserId = 9L))
        assertTrue(PushTrust.acceptNotification(n, myUserId = 7L))
    }

    @Test
    fun `没有收件人的负载一律放行——派单员广播就是这样`() {
        // role_dispatchers 那条广播（{"type":"dispatcher.pending_pool"}）与订单实时事件
        // 本来就没有 recipient_id：它们是发给一个房间的，不是发给某个人的。
        // 按"没有收件人就丢"去拦，会把派单员的新单提醒整条杀掉。
        assertTrue(PushTrust.acceptNotification(mapOf("type" to "dispatcher.pending_pool"), 9L))
        assertTrue(PushTrust.acceptNotification(mapOf("type" to "order.assigned", "order_id" to 3L), 9L))
        assertTrue("根本不是站内信（没有 notification 对象）", PushTrust.acceptNotification(null, 9L))
    }

    @Test
    fun `认不出自己是谁时宁可放过也不错杀`() {
        // 会话还没读出来（userId 为 null）时把消息丢掉，代价是司机漏单且无人发现。
        assertTrue(PushTrust.acceptNotification(mapOf("recipient_id" to 7L), null))
    }

    @Test
    fun `收件人字段不认识时按放行处理`() {
        // 后端出参是 int（NotificationOut.recipient_id），类型不认识说明不是那份出参；
        // 宁可放过一条也不要误杀——误杀是"静默漏单"，比多显示一条严重得多。
        assertTrue(PushTrust.acceptNotification(mapOf("recipient_id" to "7"), 9L))
        assertTrue(PushTrust.acceptNotification(mapOf("recipient_id" to null), 9L))
    }

    // ---- ① type 白名单（P1-4b） ----

    @Test
    fun `后端真实在发的订单事件全都在白名单里`() {
        // 清单来自 backend/app/services/message_center.py 与 push_events.py 的实际取值。
        // 少一个的后果：那条站内信降级成普通消息（不丢，但不再走「派单与新单」渠道）。
        listOf(
            "order.assigned", "order.cancelled", "order.cancelled_dispatcher", "order.created",
            "order.delivered", "order.delivered_dispatcher", "order.delivered_driver",
            "order.dispatched", "order.driver_ack", "order.driver_ack_dispatcher",
            "order.freight.updated", "order.navigation.filled", "order.recalled", "order.revoked",
        ).forEach { assertTrue("$it 应当被认成订单事件", PushTrust.isOrderEvent(it)) }
    }

    @Test
    fun `编出来的 order 名字不算订单事件`() {
        // 这正是白名单要拦的：任何写入路径都能指定 type，而「派单与新单」渠道
        // 是高优先级横幅 + 点开直达某一单（伪造锁屏通知最好用的道具）。
        listOf(
            "order.win_a_prize",
            "order.assigned.fake",
            "order",
            "Order.assigned",
            "",
        ).forEach { assertFalse("$it 不该进订单渠道", PushTrust.isOrderEvent(it)) }
    }

    @Test
    fun `非订单事件本来就不走订单渠道`() {
        listOf("system", "reminder", "price.changed", "ledger.updated", "dispatcher.pending_pool")
            .forEach { assertFalse(it, PushTrust.isOrderEvent(it)) }
    }

    // ---- ① order_id 边界（P1-4c） ----

    @Test
    fun `超范围或非法的单号一律丢弃而不是回绕`() {
        // Long→Int 是回绕：相差 2^32 的两个单号会落到同一个通知 id 上（互相盖掉）、
        // 同一个 PendingIntent requestCode 上（点旧通知打开新单）。
        val bad = listOf<Any?>(
            PushTrust.MAX_ORDER_ID + 1,
            Long.MAX_VALUE,
            1L + (1L shl 32),
            0L,
            -1L,
            -4294967296L,
            "abc",
            "12",
            null,
        )
        bad.forEach { assertNull("$it 应当被丢弃", PushTrust.orderIdOf(mapOf("order_id" to it))) }
        assertEquals(1L, PushTrust.orderIdOf(mapOf("order_id" to 1)))
        assertEquals(PushTrust.MAX_ORDER_ID, PushTrust.orderIdOf(mapOf("order_id" to Int.MAX_VALUE)))
    }

    @Test
    fun `单号从 payload 里取，顶层兜底`() {
        // 两条链路形状不同：站内信的 order_id 在 payload 里，realtime 事件在顶层。
        assertEquals(31L, PushTrust.orderIdOf(mapOf("payload" to mapOf("order_id" to 31L))))
        assertEquals(32L, PushTrust.orderIdOf(mapOf("order_id" to 32L)))
        // 两处都有时以 payload 为准（站内信的对象里 payload 才是这条消息说的那一单）
        assertEquals(
            33L,
            PushTrust.orderIdOf(mapOf("payload" to mapOf("order_id" to 33L), "order_id" to 99L)),
        )
        assertNull(PushTrust.orderIdOf(null))
        assertNull(PushTrust.orderIdOf(mapOf("type" to "dispatcher.pending_pool")))
    }

    // ---- ② 点通知的凭据（R2-NS-3） ----

    @Test
    fun `没凭据或凭据不对的 intent 一律不采信`() {
        // 本 Activity 是 exported 的 LAUNCHER（桌面要能拉起它，不能改 false），
        // 所以任何 App 都能发一个带单号的 intent 进来打断司机正在响的新单。
        assertNull("完全没有凭据", PushTrust.trustedOrderId(404L, token = null, mine = "abc"))
        assertNull("凭据不对", PushTrust.trustedOrderId(404L, token = "guess", mine = "abc"))
        assertNull("本机还没有凭据（理论上不会发生）", PushTrust.trustedOrderId(404L, token = "abc", mine = null))
    }

    @Test
    fun `凭据对且单号合法才采信`() {
        assertEquals(404L, PushTrust.trustedOrderId(404L, token = "abc", mine = "abc"))
        // 凭据对也不许带越界单号：后面拿它当通知 id / requestCode（回绕）与 API 路径参数
        assertNull(PushTrust.trustedOrderId(0L, "abc", "abc"))
        assertNull(PushTrust.trustedOrderId(-5L, "abc", "abc"))
        assertNull(PushTrust.trustedOrderId(Long.MAX_VALUE, "abc", "abc"))
    }

    // ---- ③ 被服务端拒绝 vs 网络不通（C-3） ----

    @Test
    fun `服务端拒绝才算被拒`() {
        // 服务端 return False 时 python-socketio 回一个 CONNECT_ERROR 包，
        // socket.io-client 2.1.0 把**包里的数据原样**抛给 connect_error：
        // 所以参数是解出来的 Map/JSONObject，或字符串。
        assertTrue(
            PushTrust.isServerRefusal(mapOf("message" to "Connection rejected by server")),
        )
        assertTrue(PushTrust.isServerRefusal("Connection rejected by server"))
    }

    @Test
    fun `网络不通不许当成被拒——信号差不能把人踢回登录页`() {
        // 传输层失败时 connect_error 带的是异常对象（manager 的 error 事件转发过来的）。
        // 判成"被拒"就会清会话、把人踢下线，而真正的原因只是没信号。
        listOf<Any>(
            java.io.IOException("xhr poll error"),
            java.net.ConnectException("Connection refused"),
            java.net.SocketTimeoutException("timeout"),
        ).forEach { assertFalse("$it 不该算被拒", PushTrust.isServerRefusal(it)) }
    }

    @Test
    fun `判不出来时按连不上处理（继续重连，不踢人）`() {
        assertFalse(PushTrust.isServerRefusal(null))
        // 协议不匹配（v2 客户端连 v3 服务端）时客户端**合成**的是 SocketIOException，
        // 也是异常对象 → 按"连不上"处理，正确（那不是会话问题，重新登录也修不好）
        assertFalse(PushTrust.isServerRefusal(RuntimeException("boom")))
    }
}
