package com.tapmoay.sorders.core

import com.tapmoay.sorders.ui.messages.MessageRisk
import com.tapmoay.sorders.ui.messages.noticeRoute
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 「消息中心的消息在**软件外**也收得到」的全部判定（FEAT-0027）。
 *
 * 为什么这些必须由单测钉住：它们在真机上的失败**全是静默的** ——
 * 少弹一次（用户没看见库存不足）、弹两次（同一条消息两条链各来一次）、
 * 点通知去了错误的页（用户看到一张空列表或 403）、一次来 10 条刷屏；
 * 四种都不报错、日志里也看不出来，只有"用户那头没收到 / 收到了两条"这一种表现。
 */
class MessageNotifyTest {

    private fun j(v: Any): JsonElement = when (v) {
        is JsonElement -> v
        is Boolean -> JsonPrimitive(v)
        is Number -> JsonPrimitive(v)
        else -> JsonPrimitive(v.toString())
    }

    private fun payload(vararg pairs: Pair<String, Any>): Map<String, JsonElement> =
        pairs.associate { (k, v) -> k to j(v) }

    private fun message(
        id: Long = 1L,
        risk: MessageRisk = MessageRisk.INFO,
        title: String = "标题",
        body: String = "正文",
    ): PendingMessage = PendingMessage(
        id = id, risk = risk, title = title, body = body, route = null, type = "", payload = null,
    )

    // ---- ① severity → 风险档（解析只有一处：ui/messages/MessageGrading.riskOf）----

    @Test
    fun `后端的三个 severity 各自对应一档，认不出的一律当普通`() {
        assertEquals(MessageRisk.DANGER, MessageNotify.riskOfSeverity("danger"));
        assertEquals(MessageRisk.WARN, MessageNotify.riskOfSeverity("warn"));
        assertEquals(MessageRisk.WARN, MessageNotify.riskOfSeverity("warning"));
        assertEquals(MessageRisk.INFO, MessageNotify.riskOfSeverity("info"));
        // 缺字段（老消息）/ 空串 / 认不出 / 大写带空格 —— 都不许抛，也都不许当成危险
        assertEquals(MessageRisk.INFO, MessageNotify.riskOfSeverity(null));
        assertEquals(MessageRisk.INFO, MessageNotify.riskOfSeverity(""));
        assertEquals(MessageRisk.INFO, MessageNotify.riskOfSeverity("unknown"));
        assertEquals(MessageRisk.DANGER, MessageNotify.riskOfSeverity(" DANGER "));
    }

    // ---- ② 风险档 → 渠道（severity → 重要性 的唯一映射处）----

    @Test
    fun `三档各有自己的渠道，而且都不与司机新单那条混`() {
        val danger = MessageNotify.channelOf(MessageRisk.DANGER);
        val warn = MessageNotify.channelOf(MessageRisk.WARN);
        val info = MessageNotify.channelOf(MessageRisk.INFO);
        assertEquals(NotifyChannels.MESSAGES_ALERT, danger);
        assertEquals(NotifyChannels.MESSAGES_WARN, warn);
        assertEquals(NotifyChannels.MESSAGES_INFO, info);
        // 三条互不相同：写成同一个渠道 = 重要性分档名存实亡（而界面上看不出）
        assertEquals(3, setOf(danger, warn, info).size);
        // 一条都不许落到司机那条渠道（那条要语音、要横幅）
        assertNotEquals(NotifyChannels.ORDERS_ALERT, danger);
        assertNotEquals(NotifyChannels.ORDERS_ALERT, warn);
        assertNotEquals(NotifyChannels.ORDERS_ALERT, info);
        // 也不许回到那两条"只留定义、已不再发送"的旧渠道
        assertNotEquals(NotifyChannels.MESSAGES, warn);
        assertNotEquals(NotifyChannels.MESSAGES, info);
    }

    // ---- ③ 去重：同一条通知（按 id）只弹一次 ----

    @Test
    fun `同一条通知只弹一次：两条链都到达时第二条被挡住`() {
        val seen = mutableMapOf<Long, Long>();
        val now = 1_730_000_000_000L;
        assertTrue(MessageNotify.shouldPost(88L, true, true, false, seen));
        // 第一条弹过之后（socket 实时链）落盘
        MessageNotify.markSeen(seen, 88L, now);
        // 第二条（重连回补链）到的时候必须被挡住 —— 这就是"会弹两条"的那个 bug
        assertTrue(MessageNotify.isDuplicate(seen, 88L));
        assertFalse(MessageNotify.shouldPost(88L, true, true, false, seen));
        // 另一条消息不受影响
        assertTrue(MessageNotify.shouldPost(89L, true, true, false, seen));
    }

    @Test
    fun `没有 id 的负载不去重但照弹（宁可重复也不静默不提醒）`() {
        val seen = mapOf(0L to 1L);
        assertFalse(MessageNotify.isDuplicate(seen, 0L));
        assertTrue(MessageNotify.shouldPost(0L, true, true, false, seen));
    }

    // ---- ④⑤⑥ 三个"不弹"的理由 ----

    @Test
    fun `App 在前台时不弹（应用内本来就会刷新，不重复打扰）`() {
        assertFalse(MessageNotify.shouldPost(7L, true, true, foreground = true, seen = emptyMap()));
        assertTrue(MessageNotify.shouldPost(7L, true, true, foreground = false, seen = emptyMap()));
    }

    @Test
    fun `开关关掉时只不弹，不留下去重记录（消息本身一条不丢）`() {
        val seen = mutableMapOf<Long, Long>();
        assertFalse(MessageNotify.shouldPost(7L, true, enabled = false, foreground = false, seen = seen));
        // 关键：这一刻**没有**记下"这条弹过了" —— 用户重新打开开关后，这条消息
        //（如果还会再到达一次）仍然弹得出来，而不是被判成"已经弹过"。
        assertTrue(seen.isEmpty());
        assertTrue(MessageNotify.shouldPost(7L, true, enabled = true, foreground = false, seen = seen));
    }

    @Test
    fun `没有通知权限时不弹（发出去也会被系统丢掉）`() {
        assertFalse(MessageNotify.shouldPost(7L, allowed = false, enabled = true, foreground = false, seen = emptyMap()));
    }

    // ---- ⑦ 多条合并成一条摘要（别刷屏）----

    @Test
    fun `一条单发、多条合并成摘要，摘要按这批里最高那一档选渠道`() {
        assertEquals(MessageBatch.None, MessageNotify.plan(emptyList()));
        val one = message(id = 1L, risk = MessageRisk.WARN);
        assertEquals(MessageBatch.Single(one), MessageNotify.plan(listOf(one)));
        // 一次每日扫描同时发 3 条 → 一条摘要（而不是 3 格通知）
        val batch = listOf(
            message(id = 1L, risk = MessageRisk.INFO),
            message(id = 2L, risk = MessageRisk.INFO),
            message(id = 3L, risk = MessageRisk.DANGER),
        );
        assertEquals(MessageBatch.Summary(count = 3, risk = MessageRisk.DANGER), MessageNotify.plan(batch));
        // 一堆 info 里夹着一条 danger：按 info 发就等于把它埋进公告堆里
        assertEquals(MessageRisk.DANGER, MessageNotify.highest(listOf(MessageRisk.INFO, MessageRisk.DANGER)));
        assertEquals(MessageRisk.WARN, MessageNotify.highest(listOf(MessageRisk.INFO, MessageRisk.WARN)));
        assertEquals(MessageRisk.INFO, MessageNotify.highest(emptyList()));
        assertEquals("SOrders 有新消息", MessageNotify.SUMMARY_TITLE);
        assertTrue(MessageNotify.summaryBody(3).contains("3"));
    }

    // ---- ⑧ 落盘的"已弹过"记录 ----

    @Test
    fun `已弹过的记录能落盘、能读回，坏行只丢不抛`() {
        val now = 1_730_000_000_000L;
        val seen = mutableMapOf<Long, Long>();
        MessageNotify.markSeen(seen, 12L, now - 1_000L);
        MessageNotify.markSeen(seen, 13L, now);
        val raw = MessageNotify.encodeSeen(seen);
        assertEquals("12@1729999999000;13@1730000000000", raw);
        val back = MessageNotify.decodeSeen(raw, now);
        assertEquals(setOf(12L, 13L), back.keys.toSet());
        // 坏行（空段 / 没时间戳 / 没 id / 非数字）只丢不抛：少一条记录 = 多弹一次，
        // 因为一个坏字符让整份记录失效才是真的糟（那一批会整批重弹）
        val messy = MessageNotify.decodeSeen("abc;12@;@33;14@" + now + ";15@x", now);
        assertEquals(setOf(14L), messy.keys.toSet());
        // 空串（新装机器）读出来是空的，不抛
        assertTrue(MessageNotify.decodeSeen("", now).isEmpty());
        assertTrue(MessageNotify.decodeSeen(null, now).isEmpty());
    }

    @Test
    fun `超窗与超量的记录会被裁掉`() {
        val now = 1_730_000_000_000L;
        val seen = mutableMapOf<Long, Long>();
        MessageNotify.markSeen(seen, 1L, now - MessageNotify.SEEN_KEEP_MS - 1L);
        MessageNotify.markSeen(seen, 2L, now);
        assertEquals(setOf(2L), seen.keys.toSet());
        val many = mutableMapOf<Long, Long>();
        repeat(MessageNotify.SEEN_MAX + 10) { i -> MessageNotify.markSeen(many, (i + 1).toLong(), now - i) }
        assertEquals(MessageNotify.SEEN_MAX, many.size)
        // 读盘那条路也会裁（decodeSeen 内部就调它）；这里直接调一次，把这条口径也钉在单测里
        val manual = mutableMapOf(1L to now - MessageNotify.SEEN_KEEP_MS - 1L, 2L to now)
        MessageNotify.trimSeen(manual, now)
        assertEquals(setOf(2L), manual.keys.toSet());
        assertTrue(many.containsKey(1L));
    }

    // ---- ⑨ 深链：与 App 内点击**同一份路由** ----

    @Test
    fun `点通知的去向与消息中心里点这张卡逐条一致`() {
        val cases: List<Triple<String, String, Map<String, JsonElement>>> = listOf(
            Triple("dispatcher", "order.assigned", payload("order_id" to 12)),
            Triple("dispatcher", "order.delivered", payload("order_id" to 12)),
            Triple("shipper", "order.delivered", payload("order_id" to 12)),
            Triple("dispatcher", "stock.low", payload("product_id" to 7)),
            Triple("shipper", "price.changed", payload("product_id" to 7)),
            Triple("dispatcher", "receipt.received", payload()),
            Triple("shipper", "receipt.received", payload()),
            Triple("dispatcher", "payable.overdue", payload()),
            Triple("dispatcher", "vehicle.inspection_urgent", payload()),
            Triple("dispatcher", "system", payload("order_id" to 12)),
            Triple("dispatcher", "system", payload()),
            Triple("dispatcher", "order.return_request", payload("request_id" to 5)),
            Triple("shipper", "order.return_request.done", payload("request_id" to 5)),
        );
        cases.forEach { (role, type, pl) ->
            // 通知那条链算出来的，必须**逐个字符**等于消息中心那张卡片算出来的
            assertEquals(
                "type=" + type + " payload=" + pl,
                noticeRoute(role, type, pl),
                MessageNotify.routeOf(role, type, pl),
            );
        }
        // 几个具体去向也钉一下（防止两边一起被改坏、比对仍然"一致"）
        assertEquals("order/12/detail", MessageNotify.routeOf("dispatcher", "order.assigned", payload("order_id" to 12)));
        assertEquals("dispatcher/inventory?focus=7", MessageNotify.routeOf("dispatcher", "stock.low", payload("product_id" to 7)));
        assertEquals("shipper/prices", MessageNotify.routeOf("shipper", "price.changed", payload("product_id" to 7)));
        assertEquals("dispatcher/receipts", MessageNotify.routeOf("dispatcher", "receipt.received", payload()));
        assertEquals("dispatcher/return-requests?focus=5", MessageNotify.routeOf("dispatcher", "order.return_request", payload("request_id" to 5)));
        // 认不出来 / 角色对不上 / 缺键 ⇒ null = **不跳**（绝不瞎跳）
        assertNull(MessageNotify.routeOf("dispatcher", "vehicle.inspection_due", payload()));
        assertNull(MessageNotify.routeOf("dispatcher", "system", payload()));
        assertNull(MessageNotify.routeOf("shipper", "receipt.received", payload()));
        assertNull(MessageNotify.routeOf("dispatcher", "order.assigned", payload()));
    }

    @Test
    fun `socket 那份 payload 归一之后算出的去向，与 REST 那份一模一样`() {
        // socket 来的是 org.json 转出来的普通 Map（Long / String），REST 来的是 JsonElement
        val fromSocket = mapOf<String, Any>("order_id" to 12L, "order_no" to "A001");
        val normalized = MessageNotify.payloadOf(fromSocket);
        assertEquals(
            MessageNotify.routeOf("dispatcher", "order.assigned", payload("order_id" to 12)),
            MessageNotify.routeOf("dispatcher", "order.assigned", normalized),
        );
        // 数字必须仍是数字（转成字符串也读得出来，但"是不是数字"这件事被悄悄改了就不行）
        assertEquals(JsonPrimitive(12L), normalized?.get("order_id"));
        assertNull(MessageNotify.payloadOf(null));
    }

    @Test
    fun `深链所需的 payload 键会随通知一起带出去`() {
        val extras = MessageNotify.payloadExtras(payload("order_id" to 12, "product_id" to 7));
        assertEquals("12", extras[MessageNotify.PAYLOAD_EXTRA_PREFIX + "order_id"]);
        assertEquals("7", extras[MessageNotify.PAYLOAD_EXTRA_PREFIX + "product_id"]);
        assertTrue(MessageNotify.payloadExtras(null).isEmpty());
    }

    // ---- ⑩ 通知栏折叠行（截断只影响观感，不改消息本身）----

    @Test
    fun `折叠行只取第一行、超长截断加省略号`() {
        assertEquals("库存不足", MessageNotify.preview("库存不足" + "\n" + "第二行不该出现"));
        assertEquals("", MessageNotify.preview("   "));
        val long = "字".repeat(MessageNotify.BODY_PREVIEW_MAX + 20);
        val cut = MessageNotify.preview(long);
        assertEquals(MessageNotify.BODY_PREVIEW_MAX + 1, cut.length);
        assertTrue(cut.endsWith("…"));
        assertEquals("短正文原样", MessageNotify.preview("短正文原样"));
    }
}
