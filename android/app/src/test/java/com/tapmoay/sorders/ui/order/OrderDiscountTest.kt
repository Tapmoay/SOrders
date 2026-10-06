package com.tapmoay.sorders.ui.order

import com.tapmoay.sorders.data.remote.dto.OrderDto
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 订单打折的界面口径（CHG-0071 / 台账 L-34）。
 *
 * 这里钉的都是"算错了也编译得过、只是用户看到另一个数"的东西：值框放行了一个
 * 服务端一定拒的数（用户点保存才知道错）、钱显示成另一个数、折扣的来龙去脉漏了人。
 * **折扣算法本身**（摊到行、幂等替换、退货按折后实付退）钉在
 * `backend/tests/test_order_discount.py` —— 客户端一个乘法都不做。
 */
class OrderDiscountTest {

    private fun order(
        kind: String? = null,
        value: String? = null,
        amount: String? = null,
        reason: String? = null,
        byName: String? = null,
        lines: List<JsonObject>? = null,
        status: String = "PENDING_DISPATCH",
    ) = OrderDto(
        id = 1,
        orderNo = "SO-DISCOUNT-TEST",
        status = status,
        discountKind = kind,
        discountValue = value,
        discountAmount = amount,
        discountReason = reason,
        discountByName = byName,
        discountLines = lines,
    )

    @Test
    fun `百分比：空、非数、0、负数、100 及以上都不放行`() {
        assertEquals("先填一个数", discountValueError(DISCOUNT_KIND_PERCENT, ""))
        assertEquals("先填一个数", discountValueError(DISCOUNT_KIND_PERCENT, "   "))
        assertTrue(discountValueError(DISCOUNT_KIND_PERCENT, "十") != null)
        assertTrue(discountValueError(DISCOUNT_KIND_PERCENT, "0") != null)
        assertTrue(discountValueError(DISCOUNT_KIND_PERCENT, "-5") != null)
        assertTrue(discountValueError(DISCOUNT_KIND_PERCENT, "100") != null)
        assertTrue(discountValueError(DISCOUNT_KIND_PERCENT, "150") != null)
    }

    @Test
    fun `百分比：10 与 10_5 放行，超过四位小数不放行`() {
        assertNull(discountValueError(DISCOUNT_KIND_PERCENT, "10"))
        assertNull(discountValueError(DISCOUNT_KIND_PERCENT, "10.5"))
        assertNull(discountValueError(DISCOUNT_KIND_PERCENT, "0.01"))
        assertNull(discountValueError(DISCOUNT_KIND_PERCENT, "99.9999"))
        assertTrue(discountValueError(DISCOUNT_KIND_PERCENT, "10.12345") != null)
    }

    @Test
    fun `抹零：只要大于 0 就放行（上限是这一单有多少钱，服务端才知道）`() {
        assertTrue(discountValueError(DISCOUNT_KIND_AMOUNT, "0") != null)
        assertTrue(discountValueError(DISCOUNT_KIND_AMOUNT, "") != null)
        assertNull(discountValueError(DISCOUNT_KIND_AMOUNT, "0.01"))
        assertNull(discountValueError(DISCOUNT_KIND_AMOUNT, "20"))
        assertNull(discountValueError(DISCOUNT_KIND_AMOUNT, "20.00"))
        assertTrue(discountValueError(DISCOUNT_KIND_AMOUNT, "1.23456789") != null)
    }

    @Test
    fun `发出去的值原样：不许去尾零、不许补两位（一格式化精度就变了）`() {
        assertEquals("10.50", discountValueToSend(" 10.50 "))
        assertEquals("0.1000", discountValueToSend("0.1000"))
        assertEquals("20", discountValueToSend("20"))
    }

    @Test
    fun `两种方式各有自己的说法：减 10% 与 抹零 20`() {
        assertEquals("减 10%", discountSummary(DISCOUNT_KIND_PERCENT, "10"))
        assertEquals("减 10.5%", discountSummary(DISCOUNT_KIND_PERCENT, "10.5000"))
        assertEquals("抹零 ¥20", discountSummary(DISCOUNT_KIND_AMOUNT, "20.00"))
        assertEquals("抹零 ¥0", discountSummary(DISCOUNT_KIND_AMOUNT, null))
        assertEquals("减百分比", discountKindLabel(DISCOUNT_KIND_PERCENT))
        assertEquals("抹零", discountKindLabel(DISCOUNT_KIND_AMOUNT))
    }

    @Test
    fun `已优惠只在真减了钱时才出现（0 与负数都不算）`() {
        assertNull(discountHeadline(order()))
        assertNull(discountHeadline(order(kind = "percent", value = "10", amount = null)))
        assertNull(discountHeadline(order(kind = "percent", value = "10", amount = "0")))
        assertNull(discountHeadline(order(kind = "percent", value = "10", amount = "0.00")))
        assertNull(discountHeadline(order(kind = "percent", value = "10", amount = "-1")))
        assertEquals("已优惠 ¥12.5", discountHeadline(order(kind = "percent", value = "10", amount = "12.50")))
    }

    @Test
    fun `来龙去脉：打了几折、谁打的、为什么（没人或没理由就少印那一截）`() {
        assertNull(discountTrace(order()))
        assertEquals(
            "减 10% · 张三 · 理由：老客户",
            discountTrace(order(kind = "percent", value = "10", byName = "张三", reason = "老客户")),
        )
        assertEquals(
            "减 10% · 张三",
            discountTrace(order(kind = "percent", value = "10", byName = "张三", reason = "  ")),
        )
        assertEquals(
            "抹零 ¥20 · 理由：抹个零",
            discountTrace(order(kind = "amount", value = "20", reason = "抹个零")),
        )
    }

    @Test
    fun `已经参与折扣的行能从快照里读出来（改折扣时把勾预先打上）`() {
        val lines = listOf(
            JsonObject(mapOf("line_id" to JsonPrimitive(3), "name" to JsonPrimitive("脐橙"))),
            JsonObject(mapOf("line_id" to JsonPrimitive(7))),
        )
        assertEquals(setOf(3L, 7L), discountLineIds(order(kind = "percent", value = "10", lines = lines)))
        assertEquals(emptySet<Long>(), discountLineIds(order()))
        assertEquals(
            emptySet<Long>(),
            discountLineIds(order(kind = "percent", value = "10", lines = listOf(JsonObject(mapOf("name" to JsonPrimitive("坏数据")))))),
        )
    }

    @Test
    fun `只有还能改钱的那三档能打折（与后端 LINE_EDITABLE_STATUSES 同一组值）`() {
        assertTrue(canDiscount("PENDING_DISPATCH"))
        assertTrue(canDiscount("DISPATCHED"))
        assertTrue(canDiscount("ACCEPTED"))
        assertTrue(canDiscount("accepted"))
        assertFalse(canDiscount("DELIVERED"))
        assertFalse(canDiscount("CANCELLED"))
        assertFalse(canDiscount("RETURNED"))
        assertFalse(canDiscount(""))
        assertEquals(setOf("PENDING_DISPATCH", "DISPATCHED", "ACCEPTED"), DISCOUNT_STATUSES)
    }
}
