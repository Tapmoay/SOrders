package com.tapmoay.sorders.ui.common

import com.tapmoay.sorders.ui.dispatcher.isoDateOfMillis
import com.tapmoay.sorders.ui.dispatcher.isoDateToMillis
import java.time.Instant
import java.time.LocalDate
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 下单页「送达日期」（FEAT-0028）：默认值 / 能不能选 / 怎么显示 / 毫秒怎么换。
 *
 * 用户 2026-10-21 的口径：「**订单必须提前一天下达**，当天下的单不一定能准时送达」——
 * 所以这里最重要的三条用例是：**默认明天**、**昨天不可选**、**没有秒的 UTC 零点换算**。
 *
 * ⛔ 最后那一条不是洁癖：Material3 的 `DatePicker` 收发的毫秒是"那一天的 **UTC** 00:00"，
 * 按设备时区换算在东八区会整体差一天（打开停在前一天、确认又写回前一天），而界面上看不出来。
 */
class DeliveryDateTest {

    private val today = LocalDate.of(2026, 10, 21)

    @Test
    fun `推荐的那一天是明天（不是预选，只是标一个推荐）`() {
        // 用户 2026-10-22：「这个默认是空的是不填的，不是默认就填明天」
        // ⇒ 下单页初值空着（VM 那一行由判据盯），这里只是"推荐哪天"的那一个算法。
        assertEquals("2026-10-22", defaultDeliveryDate(today))
    }

    @Test
    fun `今天可选昨天不可选坏串不可选`() {
        assertTrue(deliveryDateAllowed("2026-10-21", today))
        assertTrue(deliveryDateAllowed("2026-10-22", today))
        assertFalse(deliveryDateAllowed("2026-10-20", today))
        assertFalse(deliveryDateAllowed("", today))
        assertFalse(deliveryDateAllowed(null, today))
        assertFalse(deliveryDateAllowed("2026-13-99", today))
    }

    @Test
    fun `离今天几天`() {
        assertEquals(1L, deliveryLeadDays("2026-10-22", today))
        assertEquals(0L, deliveryLeadDays("2026-10-21", today))
        assertEquals(-2L, deliveryLeadDays("2026-10-19", today))
        assertNull(deliveryLeadDays("not-a-date", today))
    }

    @Test
    fun `抽屉里只有今天到四天后`() {
        val choices = deliveryDateChoices(today)
        assertEquals(listOf("2026-10-21", "2026-10-22", "2026-10-23", "2026-10-24"), choices.map { it.first })
        assertEquals("今天（10-21）", choices[0].second)
        assertEquals("明天（10-22）", choices[1].second)
        assertEquals("后天（10-23）", choices[2].second)
        assertEquals("大后天（10-24）", choices[3].second)
    }

    @Test
    fun `那一行显示明天加日期`() {
        assertEquals("明天 · 10-22", deliveryDateLabel("2026-10-22", today))
        assertEquals("今天 · 10-21", deliveryDateLabel("2026-10-21", today))
        assertEquals("后天 · 10-23", deliveryDateLabel("2026-10-23", today))
        assertEquals("大后天 · 10-24", deliveryDateLabel("2026-10-24", today))
        // 再远的日子只说日期与周几（「4 天后」读起来像倒计时，而这一格要的是"哪天"）
        assertEquals("10-26 周一", deliveryDateLabel("2026-10-26", today))
        assertEquals("未选择", deliveryDateLabel(null, today))
    }

    @Test
    fun `毫秒是那一天的UTC零点`() {
        val millis = isoDateToMillis("2026-10-22")
        assertEquals(Instant.parse("2026-10-22T00:00:00Z").toEpochMilli(), millis)
        // 往返：选出来再读回去，必须是同一天（差一天的那个缺陷就死在这条上）
        assertEquals("2026-10-22", isoDateOfMillis(millis!!))
        assertNull(isoDateToMillis("坏日期"))
    }

    @Test
    fun `倒计时说的是还剩几天`() {
        assertEquals("还有 1 天", deliveryCountdown("2026-10-22", today))
        assertEquals("还有 3 天", deliveryCountdown("2026-10-24", today))
        assertEquals("今天送到", deliveryCountdown("2026-10-21", today))
        assertEquals("已过 2 天", deliveryCountdown("2026-10-19", today))
        assertNull(deliveryCountdown(null, today))
        assertNull(deliveryCountdown("坏日期", today))
    }

    @Test
    fun `卡片与详情那一行：日期加倒计时，终态只印日期`() {
        assertEquals("10-22 · 还有 1 天", deliveryDateText("2026-10-22", "PENDING_DISPATCH", today))
        assertEquals("10-22 · 还有 1 天", deliveryDateText("2026-10-22", "DISPATCHED", today))
        assertEquals("10-22 · 还有 1 天", deliveryDateText("2026-10-22", "ACCEPTED", today))
        // 终态：日子已经是历史，再说"还有 1 天"会读成"还没到"
        assertEquals("10-22", deliveryDateText("2026-10-22", "DELIVERED", today))
        assertEquals("10-22", deliveryDateText("2026-10-22", "CANCELLED", today))
        assertEquals("10-22", deliveryDateText("2026-10-22", "RETURNED", today))
        // 没选过 → 可空的那一版返回 null（调用方不该拿它直接画）
        assertNull(deliveryDateText(null, "PENDING_DISPATCH", today))
        assertNull(deliveryDateText("", "PENDING_DISPATCH", today))
    }

    @Test
    fun `没选过要明说未选择送达日期，不许整行消失`() {
        // 用户 2026-10-22：「如果他没选择的话，订单里就有一条信息说他没有选择送达日期」
        assertEquals("未选择送达日期", deliveryDateDisplay(null, "PENDING_DISPATCH", today))
        assertEquals("未选择送达日期", deliveryDateDisplay("", "DISPATCHED", today))
        assertEquals("未选择送达日期", deliveryDateDisplay("坏日期", "ACCEPTED", today))
        // 选了就照旧：日期 + 倒计时；终态只印日期
        assertEquals("10-22 · 还有 1 天", deliveryDateDisplay("2026-10-22", "DISPATCHED", today))
        assertEquals("10-22", deliveryDateDisplay("2026-10-22", "DELIVERED", today))
    }

    @Test
    fun `选择层只放今天以后`() {
        assertTrue(deliveryDateSelectable(isoDateToMillis(defaultDeliveryDate())!!))
        assertTrue(deliveryDateSelectable(isoDateToMillis(LocalDate.now().toString())!!))
        assertFalse(deliveryDateSelectable(isoDateToMillis(LocalDate.now().minusDays(1).toString())!!))
    }
}
