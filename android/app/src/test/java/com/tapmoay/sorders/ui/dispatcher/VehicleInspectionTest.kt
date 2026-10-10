package com.tapmoay.sorders.ui.dispatcher

import com.tapmoay.sorders.ui.messages.MSG_TEXT_DANGER
import com.tapmoay.sorders.ui.messages.MSG_TEXT_WARN
import com.tapmoay.sorders.ui.messages.MessageRisk
import com.tapmoay.sorders.ui.messages.emphasisColor
import java.time.LocalDate
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNull
import org.junit.Test

/**
 * 车辆年检（FEAT-0022）：两个日期怎么变成「下次年检 + 还有几天 + 该上什么色」，
 * 以及**保存时哪一格该发、哪一格不该发**。
 *
 * 用户 2026-10-11 的口径：「到我给那个车子建档案的时候会填一下就是这车子的上牌日期，
 * 或者说是上一个年检日期啊方便我们去做一个提醒」。
 *
 * ⛔ 这一份测的是**客户端那一份兜底实现**（`VehicleInspection.kt`）。契约上"下次年检只有一处算"
 * 指的是**后端**：后端出参带了 `next_inspection_date` 时客户端必须直接用后端的
 * （见 `后端给了下次年检日期就用后端的，不许自己再算一遍` 这条用例）。
 */
class VehicleInspectionTest {

    private val today = LocalDate.of(2026, 10, 11)

    // ---- 下次年检：哪天 ----

    @Test
    fun `有上次年检日期就按它加一年`() {
        assertEquals(LocalDate.of(2025, 3, 1), nextInspectionDue("2020-03-01", "2024-03-01"))
    }

    @Test
    fun `没填上次年检就按上牌日期加一年`() {
        assertEquals(LocalDate.of(2021, 3, 1), nextInspectionDue("2020-03-01", null))
        assertEquals(LocalDate.of(2021, 3, 1), nextInspectionDue("2020-03-01", ""))
    }

    @Test
    fun `两格都空就不给提醒（不是拿今天当上牌日）`() {
        assertNull(nextInspectionDue(null, null))
        assertNull(nextInspectionDue("", "   "))
        assertNull(inspectionBadgeOf(null, null, null, today))
        assertNull(inspectionLine(inspectionBadgeOf(null, "", "", today)))
    }

    @Test
    fun `坏日期串当没填（不抛异常也不猜格式）`() {
        assertNull(parseIsoDate("2020/03/01"))
        assertNull(parseIsoDate("2024-02-30"))
        assertNull(parseIsoDate("下个月"))
        assertNull(nextInspectionDue("2020/03/01", "2024-13-01"))
        // 空格要能吃（后端/用户复制的串常带）
        assertEquals(LocalDate.of(2020, 3, 1), parseIsoDate(" 2020-03-01 "))
    }

    @Test
    fun `跨闰年是加一年不是加三百六十五天`() {
        // 2023-03-01 到 2024-03-01 中间夹着 2024-02-29，所以这一段是 366 天：
        // 按 365 天算会落到 2024-02-29 —— 提醒早了一天，而且没人看得出来。
        val base = LocalDate.of(2023, 3, 1)
        assertEquals(LocalDate.of(2024, 3, 1), nextInspectionDue(null, "2023-03-01"))
        assertNotEquals(base.plusDays(365), nextInspectionDue(null, "2023-03-01"))
        // 2/29 上牌：plusYears 收到 2/28（不是 3/1）—— 一年后那天本来就不存在
        assertEquals(LocalDate.of(2025, 2, 28), nextInspectionDue(null, "2024-02-29"))
    }

    // ---- 剩余天数分三档：>30 常规 / ≤30 警告 / 已过期 危险 ----

    @Test
    fun `剩余天数分档：三十天那条线两边各一档`() {
        assertEquals(MessageRisk.INFO, inspectionRisk(31))
        assertEquals(MessageRisk.WARN, inspectionRisk(30))
        assertEquals(MessageRisk.WARN, inspectionRisk(1))
        assertEquals(MessageRisk.WARN, inspectionRisk(0))
        assertEquals(MessageRisk.DANGER, inspectionRisk(-1))
        assertEquals(MessageRisk.DANGER, inspectionRisk(-400))
    }

    @Test
    fun `剩余天数按自然日算（今天到期是零，过期是负数）`() {
        assertEquals(30L, inspectionDaysLeft(LocalDate.of(2026, 11, 10), today))
        assertEquals(0L, inspectionDaysLeft(today, today))
        assertEquals(-3L, inspectionDaysLeft(LocalDate.of(2026, 10, 8), today))
    }

    @Test
    fun `还有几天的说法：没过期说还有、当天说今天到期、过期说已过期几天`() {
        assertEquals("还有 30 天", inspectionText(30))
        assertEquals("还有 1 天", inspectionText(1))
        assertEquals("今天到期", inspectionText(0))
        assertEquals("已过期 3 天", inspectionText(-3))
    }

    @Test
    fun `卡片那一行是整串（日期 + 还有几天）`() {
        val badge = inspectionBadgeOf(null, null, "2025-10-06", today)
        assertEquals(LocalDate.of(2026, 10, 6), badge?.due)
        assertEquals(-5L, badge?.daysLeft)
        assertEquals("下次年检：2026-10-06 · 已过期 5 天", inspectionLine(badge))
    }

    // ---- 后端优先 ----

    @Test
    fun `后端给了下次年检日期就用后端的，不许自己再算一遍`() {
        // 后端的口径与本地兜底**必须是同一条规则**；这里故意给一个"本地算不出来"的组合
        // （两格日期都空、后端却给了日期）：仍然要用后端的 —— 这样"后端加了新口径"时
        // 客户端不会拿一份老算法去覆盖它。
        val badge = inspectionBadgeOf("2030-01-01", null, null, today)
        assertEquals(LocalDate.of(2030, 1, 1), badge?.due)
        // 后端给的是坏串时退回本地兜底，而不是整行消失
        assertEquals(
            LocalDate.of(2025, 3, 1),
            inspectionBadgeOf("不是日期", "2020-03-01", "2024-03-01", today)?.due,
        )
    }

    @Test
    fun `颜色跟着档走，且用的是消息中心那张风险色表`() {
        assertEquals(MSG_TEXT_DANGER, emphasisColor(inspectionRisk(-1)))
        assertEquals(MSG_TEXT_WARN, emphasisColor(inspectionRisk(0)))
        assertEquals(MSG_TEXT_WARN, emphasisColor(inspectionRisk(30)))
        assertNull(emphasisColor(inspectionRisk(31)))
    }

    // ---- 日期选择器 ↔ ISO 串 ----

    @Test
    fun `日期选择器与 ISO 串来回换是同一天`() {
        val millis = isoDateToMillis("2020-03-01")
        assertEquals("2020-03-01", isoDateOfMillis(millis!!))
        assertNull(isoDateToMillis("2020/03/01"))
        assertNull(isoDateToMillis(""))
    }

    // ---- 保存时这一格发不发（PATCH 语义）----

    @Test
    fun `新建：填了才发，没填就整个键不出现`() {
        assertNull(newDateOrNull(""))
        assertNull(newDateOrNull("   "))
        assertEquals("2020-03-01", newDateOrNull(" 2020-03-01 "))
    }

    @Test
    fun `编辑：用户没动过的日期一个键都不发（老车本来就没填过）`() {
        // 打开弹层看一眼就保存 —— 这两格原样带出来、也原样"没改"，⛔ 不许发出去：
        // 发出去就是一封"把那两格清空"的指令，而用户什么都没做。
        assertNull(changedDateOrNull("2020-03-01", "2020-03-01"))
        assertNull(changedDateOrNull(null, ""))
        assertNull(changedDateOrNull("", "  "))
        assertNull(changedDateOrNull(null, "   "))
    }

    @Test
    fun `编辑：原来有值而用户清空了，那是真的改动（要发空串）`() {
        // 空串在后端 = 清空这一格（`VehicleUpdateRequest` 的注释）；⛔ 这里回 null 的话，
        // 用户点了「清除」再保存 = 白点。
        assertEquals("", changedDateOrNull("2020-03-01", ""))
        assertEquals("2024-03-01", changedDateOrNull(null, "2024-03-01"))
        assertEquals("2024-03-01", changedDateOrNull("2020-03-01", " 2024-03-01 "))
    }
}
