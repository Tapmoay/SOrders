package com.tapmoay.sorders.ui.messages

import com.tapmoay.sorders.ui.nav.Role
import com.tapmoay.sorders.ui.nav.Routes
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonArray
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 消息卡片的**分级纯函数**（FEAT-0019，2026-10-11）。
 *
 * 用户的原话是：「按消息类型做颜色区别，而且只有未读才有这个样式，已读所有消息一个样」、
 * 「你的文字不能全部用颜色给他去搞出来……我们的真正的重心是这几个字：第一库存不足、以及现在
 * 还剩多少库存的那个个数……**全是重点就是没有重点**」。
 *
 * 这里钉的不是界面长得像不像，而是**界面拿去画的那几个判断**：哪一族是哪个色、severity 只决定
 * 被点名词的颜色、只有被点名的片段才上色、点进去该去哪一页、**payload 里缺键时返回 null（不跳）**。
 *
 * ⛔ 边界：这些是纯函数测试 —— 竖条 6px、未读才画、已读全灰这些"画法"由
 * `_tools/qa/_check_message_card_grading.py` 钉源码，不在这里重复。
 */
class MessageGradingTest {

    private fun payload(vararg pairs: Pair<String, Any>): Map<String, JsonElement> =
        pairs.associate { (k, v) ->
            k to when (v) {
                is Int -> JsonPrimitive(v)
                is Long -> JsonPrimitive(v)
                is List<*> -> buildJsonArray { v.forEach { add(JsonPrimitive(it.toString())) } }
                else -> JsonPrimitive(v.toString())
            }
        }

    // ---- 1) 类型 → 颜色（都是工作台那一格的色）----

    @Test
    fun `库存不足与库存偏低是同一个族同一个色`() {
        assertEquals(MessageFamily.STOCK, familyOf("stock.shortage"))
        assertEquals(MessageFamily.STOCK, familyOf("stock.low"))
        assertEquals(MessageFamily.STOCK, familyOf("stock.near_low"))
        assertEquals(0xFF008EABL, familyOf("stock.shortage").color)
        assertEquals(0xFF008EABL, familyOf("stock.near_low").color)
    }

    @Test
    fun `后端 FEAT-0019 定名的九类新消息都认得出`() {
        assertEquals(MessageFamily.STOCK, familyOf("stock.low"))
        assertEquals(MessageFamily.STOCK, familyOf("stock.near_low"))
        assertEquals(MessageFamily.ARREARS, familyOf("arrears.over_limit"))
        assertEquals(MessageFamily.PAYABLE, familyOf("payable.due_soon"))
        assertEquals(MessageFamily.PAYABLE, familyOf("payable.overdue"))
        assertEquals(MessageFamily.INVOICE, familyOf("invoice.issued"))
        assertEquals(MessageFamily.VEHICLE, familyOf("vehicle.inspection_due"))
        assertEquals(MessageFamily.ACCOUNT, familyOf("account.new_device_login"))
        assertEquals(0xFFAC7217L, familyOf("account.new_device_login").color)
        assertEquals(MessageFamily.ACCOUNT, familyOf("account.device_unfrozen"))
    }

    @Test
    fun `订单一族按结果分三种色`() {
        assertEquals(MessageFamily.ORDER, familyOf("order.assigned"))
        assertEquals(0xFF1E6FFFL, familyOf("order.return_request").color)
        assertEquals(MessageFamily.ORDER_DONE, familyOf("order.delivered"))
        assertEquals(0xFF00AC6EL, familyOf("order.delivered_driver").color)
        assertEquals(MessageFamily.ORDER_VOID, familyOf("order.revoked"))
        assertEquals(MessageFamily.ORDER_VOID, familyOf("order.deleted"))
        assertEquals(0xFF917A16L, familyOf("order.cancelled").color)
    }

    @Test
    fun `钱的三个族与其它格子各是各的色`() {
        assertEquals(0xFF9C88E0L, familyOf("receipt.received").color)
        assertEquals(0xFF9C88E0L, familyOf("arrears.over_limit").color)
        assertEquals(0xFFE05288L, familyOf("payable.overdue").color)
        assertEquals(0xFFE08034L, familyOf("invoice.issued").color)
        assertEquals(0xFFB65DC4L, familyOf("price_change").color)
        assertEquals(0xFF00AAAEL, familyOf("vehicle.inspection_due").color)
        assertEquals(0xFFAC7217L, familyOf("account.new_device").color)
    }

    @Test
    fun `认不出来的类型落到消息中心那一格`() {
        assertEquals(MessageFamily.SYSTEM, familyOf("system"))
        assertEquals(0xFFE07B80L, familyOf("who.knows.what").color)
        assertEquals(MessageFamily.SYSTEM, familyOf("  SYSTEM  "))
    }

    @Test
    fun `小标签优先用 payload 里点名的文案`() {
        assertEquals("库存预警", messageLabel("stock.shortage", null))
        assertEquals("临期预警", messageLabel("stock.shortage", payload("label" to "临期预警")))
        assertEquals("库存预警", messageLabel("stock.shortage", payload("label" to "   ")))
    }

    // ---- 2) severity → 风险档（只决定被点名词用什么色）----

    @Test
    fun `severity 三档与缺字段`() {
        assertEquals(MessageRisk.DANGER, riskOf("danger"))
        assertEquals(MessageRisk.WARN, riskOf("warn"))
        assertEquals(MessageRisk.WARN, riskOf("warning"))
        assertEquals(MessageRisk.INFO, riskOf("info"))
        assertEquals(MessageRisk.INFO, riskOf(null))
        assertEquals(MessageRisk.INFO, riskOf("whatever"))
    }

    @Test
    fun `只有危险与警告上风险色 info 不上色`() {
        assertEquals(0xFFD93025L, emphasisColor(MessageRisk.DANGER))
        assertEquals(0xFFE07B00L, emphasisColor(MessageRisk.WARN))
        assertNull(emphasisColor(MessageRisk.INFO))
    }
    // ---- 3) payload.emphasis → 该上色的片段（⛔ 只有被点名的片段，其余正常深色）----

    @Test
    fun `点名词从 JSON 数组里取并按顺序去重`() {
        val p = payload("emphasis" to listOf("库存不足", "8", "库存不足", " "))
        assertEquals(listOf("库存不足", "8"), emphasisWords(p))
        assertEquals(emptyList<String>(), emphasisWords(null))
        // 没有这个键（老消息）= 一个字都不上色，而不是"整条都算重点"
        assertEquals(emptyList<String>(), emphasisWords(payload("order_id" to 7)))
    }

    @Test
    fun `点名词也认手写的逗号串`() {
        assertEquals(listOf("库存不足", "8"), emphasisWords(payload("emphasis" to "库存不足, 8")))
        assertEquals(listOf("库存不足"), emphasisWords(payload("emphasis" to "库存不足")))
    }

    @Test
    fun `只有被点名的片段上色其余原样`() {
        val spans = splitByEmphasis("当前库存 8 筐，低于报警阈值 20 筐", listOf("8"))
        assertEquals(listOf("当前库存 ", "8", " 筐，低于报警阈值 20 筐"), spans.map { it.text })
        assertEquals(listOf(false, true, false), spans.map { it.emphasized })
    }

    @Test
    fun `词在正文里找不到就一个字都不上色`() {
        val spans = splitByEmphasis("司机 李伟明 已接单", listOf("库存不足", "8"))
        assertEquals(listOf("司机 李伟明 已接单"), spans.map { it.text })
        assertTrue(spans.none { it.emphasized })
    }

    @Test
    fun `重叠时先匹配长的`() {
        val spans = splitByEmphasis("红富士苹果库存不足", listOf("不足", "库存不足"))
        assertEquals(listOf("红富士苹果", "库存不足"), spans.map { it.text })
        assertEquals(listOf(false, true), spans.map { it.emphasized })
    }

    @Test
    fun `有 severity 但没有 emphasis 就整条正常色`() {
        // 后端口径：没有重点词的消息 payload 可能**整个是 null**（不是空对象）。
        assertTrue(emphasisWords(null).isEmpty())
        assertTrue(emphasisWords(payload("product_id" to 8)).isEmpty())
        val spans = splitByEmphasis("SO202610100551555025 已被接单", emphasisWords(payload("product_id" to 8)))
        assertEquals(1, spans.size)
        assertFalse(spans[0].emphasized)
    }

    @Test
    fun `没有点名词时整段原样`() {
        val spans = splitByEmphasis("当前库存 8 筐", emptyList())
        assertEquals(1, spans.size)
        assertFalse(spans[0].emphasized)
        assertTrue(splitByEmphasis("", listOf("8")).isEmpty())
    }

    // ---- 4) payload → 该去哪一页（⛔ 缺键 = null = 不跳）----

    @Test
    fun `库存预警带商品号就去库存管理页并定位那个商品`() {
        assertEquals(
            Routes.INVENTORY + "?focus=8",
            noticeRoute(Role.DISPATCHER.key, "stock.shortage", payload("product_id" to 8)),
        )
    }

    @Test
    fun `库存预警缺商品号就不跳`() {
        assertNull(noticeRoute(Role.DISPATCHER.key, "stock.shortage", null))
        assertNull(noticeRoute(Role.DISPATCHER.key, "stock.shortage", payload("product_name" to "红富士苹果")))
        assertNull(noticeRoute(Role.DISPATCHER.key, "stock.shortage", payload("product_id" to 0)))
        assertNull(noticeRoute(Role.DISPATCHER.key, "stock.shortage", payload("product_id" to "abc")))
    }

    @Test
    fun `订单类去订单详情缺单号就不跳`() {
        assertEquals(
            "order/123/detail",
            noticeRoute(Role.SHIPPER.key, "order.assigned", payload("order_id" to 123, "order_no" to "SO1")),
        )
        assertNull(noticeRoute(Role.SHIPPER.key, "order.assigned", payload("order_no" to "SO1")))
    }

    @Test
    fun `退货申请仍由 NoticeRouting 一处算`() {
        // 派单员收到退货申请 → 派单端的退货申请页并定位那一条
        assertEquals(
            Routes.dispatcherReturnRequests(31),
            noticeRoute(Role.DISPATCHER.key, "order.return_request", payload("request_id" to 31)),
        )
        // 缺申请单号（或角色对不上）⇒ NoticeRouting 认不出来，它 docstring 里写明「退回老行为：
        // 有单号就开订单详情」⇒ 这里落进订单一族那一支。⛔ 但这条兜底只在 MessageGrading 一处，
        // 消息页不许自己再写一份。
        assertEquals(
            Routes.orderDetail(5),
            noticeRoute(Role.DISPATCHER.key, "order.return_request", payload("order_id" to 5)),
        )
        // 连订单号都没有 ⇒ 不跳
        assertNull(noticeRoute(Role.DISPATCHER.key, "order.return_request", payload("order_no" to "SO1")))
    }

    @Test
    fun `收款应付发票价格各去自己那一页`() {
        assertEquals(Routes.DISPATCH_RECEIPTS, noticeRoute(Role.DISPATCHER.key, "receipt.received", null))
        assertEquals(Routes.DISPATCH_SUPPLIERS, noticeRoute(Role.DISPATCHER.key, "payable.overdue", null))
        assertEquals(Routes.INVOICES, noticeRoute(Role.DISPATCHER.key, "invoice.issued", null))
        assertEquals(Routes.SHIPPER_PRICES, noticeRoute(Role.SHIPPER.key, "price_change", null))
    }

    @Test
    fun `车辆年检与系统公告不跳`() {
        assertNull(noticeRoute(Role.DISPATCHER.key, "vehicle.inspection_due", null))
        assertNull(noticeRoute(Role.DISPATCHER.key, "announcement", null))
    }

    @Test
    fun `认不出的类型只认老的订单号兜底`() {
        assertNull(noticeRoute(Role.DISPATCHER.key, "ledger_export", payload("download_url" to "http://x")))
        assertEquals("order/9/detail", noticeRoute(Role.DISPATCHER.key, "ledger_export", payload("order_id" to 9)))
    }

    @Test
    fun `角色缓存为空时不当货主`() {
        // 空串若经 Role.fromKey 会回落成 SHIPPER → 价格 / 收款类会被错送到货主那一页
        assertNull(noticeRoute("", "price_change", null))
        assertNull(noticeRoute("", "receipt.received", null))
        assertEquals(Routes.SHIPPER_PRICES, noticeRoute(Role.SHIPPER.key, "price_change", null))
    }

    @Test
    fun `链接文案按样本一类一句`() {
        assertEquals("查看库存", noticeActionLabel("stock.shortage"))
        assertEquals("查看订单", noticeActionLabel("order.assigned"))
        assertEquals("查看账本", noticeActionLabel("order.delivered"))
        assertEquals("查看详情", noticeActionLabel("order.deleted"))
        assertEquals("查看收款", noticeActionLabel("receipt.received"))
        assertEquals("查看欠款", noticeActionLabel("arrears.over_limit"))
        assertEquals("去付款", noticeActionLabel("payable.due_soon"))
        assertEquals("查看发票", noticeActionLabel("invoice.issued"))
        assertEquals("查看价格", noticeActionLabel("price_change"))
        assertEquals("查看设备", noticeActionLabel("account.new_device"))
        assertNull(noticeActionLabel("vehicle.inspection_due"))
        assertNull(noticeActionLabel("announcement"))
    }
}
