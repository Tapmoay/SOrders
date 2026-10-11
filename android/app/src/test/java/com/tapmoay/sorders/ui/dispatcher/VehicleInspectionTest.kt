package com.tapmoay.sorders.ui.dispatcher

import com.tapmoay.sorders.ui.messages.MSG_TEXT_DANGER
import com.tapmoay.sorders.ui.messages.MSG_TEXT_WARN
import com.tapmoay.sorders.ui.messages.MessageRisk
import com.tapmoay.sorders.ui.messages.emphasisColor
import java.time.LocalDate
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 车辆年检（FEAT-0022）：两个日期怎么变成「下次年检 + 还有几天 + 该上什么色」，
 * 以及**保存时哪一格该发、哪一格不该发**。
 *
 * 用户 2026-10-11 的口径：「到我给那个车子建档案的时候会填一下就是这车子的上牌日期，
 * 或者说是上一个年检日期啊方便我们去做一个提醒」。
 *
 * CHG-0115（同一天）把提前量从"只剩 30 天才说"改成**提前 3 个月开口、提前 1 个月转红**：
 * 「这个车辆年检是**不能逾期**的……**一旦过了的话那车子是不能上路的**。……大概在**一个月，
 * 还是三个月前**就会有提醒的」。所以分档用例有**两条**线（90 / 30），不是一条。
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

    // ---- 剩余天数分四档（CHG-0115）：>90 常规 / 31~90 橙 / 0~30 红 / 已过期 红 ----

    @Test
    fun `剩余天数分档：九十天与三十天那两条线各自两边一档`() {
        assertEquals(MessageRisk.INFO, inspectionRisk(91))       // 还有三个月零一天：不打扰
        assertEquals(MessageRisk.WARN, inspectionRisk(90))       // 正好三个月：开口
        assertEquals(MessageRisk.WARN, inspectionRisk(31))       // 还有一个月零一天：还是橙
        assertEquals(MessageRisk.DANGER, inspectionRisk(30))     // 正好一个月：转红（必须去了）
        assertEquals(MessageRisk.DANGER, inspectionRisk(1))
        assertEquals(MessageRisk.DANGER, inspectionRisk(0))      // 到期日当天：红 +「今天到期」
        assertEquals(MessageRisk.DANGER, inspectionRisk(-1))     // 过期：红 +「已过期 N 天」
        assertEquals(MessageRisk.DANGER, inspectionRisk(-400))
    }

    @Test
    fun `两条提前量与后端那两个常量同值（90 天开口、30 天转红）`() {
        // 后端 inspection_due.INSPECTION_DUE_SOON_DAYS / INSPECTION_URGENT_DAYS 是权威；
        // 客户端这份兜底实现必须同值，否则界面上说的日子与收到的提醒不是同一档。
        assertEquals(90L, INSPECTION_DUE_SOON_DAYS)
        assertEquals(30L, INSPECTION_URGENT_DAYS)
    }

    @Test
    fun `三十天以内与已过期是同一个红，靠文案分开`() {
        // 用户口径是「不能逾期」⇒ 这两档都该是红的；区别只在 [inspectionText] 那句话。
        assertEquals(emphasisColor(inspectionRisk(30)), emphasisColor(inspectionRisk(-1)))
        assertEquals(MSG_TEXT_DANGER, emphasisColor(inspectionRisk(30)))
        assertEquals("还有 30 天", inspectionText(30))
        assertEquals("今天到期", inspectionText(0))
        assertEquals("已过期 1 天", inspectionText(-1))
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
        assertEquals(MSG_TEXT_DANGER, emphasisColor(inspectionRisk(0)))
        assertEquals(MSG_TEXT_DANGER, emphasisColor(inspectionRisk(30)))
        assertEquals(MSG_TEXT_WARN, emphasisColor(inspectionRisk(31)))
        assertEquals(MSG_TEXT_WARN, emphasisColor(inspectionRisk(90)))
        assertNull(emphasisColor(inspectionRisk(91)))
    }

    // ---- 日期选择器 ↔ ISO 串 ----

    @Test
    fun `日期选择器与 ISO 串来回换是同一天`() {
        val millis = isoDateToMillis("2020-03-01")
        assertEquals("2020-03-01", isoDateOfMillis(millis!!))
        assertNull(isoDateToMillis("2020/03/01"))
        assertNull(isoDateToMillis(""))
    }

    // ---- 未来日期不可选（后端不做范围校验）----

    @Test
    fun `选年检日期时不许选未来（今天能选，明天不行）`() {
        // 后端不做日期范围校验：填了未来日期不会报错，只会"算不出该提醒的那天"。
        assertTrue(inspectionDateAllowed("2026-10-11", today))
        assertTrue(inspectionDateAllowed("2020-03-01", today))
        assertFalse(inspectionDateAllowed("2026-10-12", today))
        assertFalse(inspectionDateAllowed("2027-01-01", today))
        assertFalse(inspectionDateAllowed("不是日期", today))
        assertFalse(inspectionDateAllowed(null, today))
    }

    @Test
    fun `选择器那条回调也按同一条规则（毫秒进来）`() {
        val nowIso = LocalDate.now().toString()
        val tomorrowIso = LocalDate.now().plusDays(1).toString()
        assertTrue(inspectionDateSelectable(isoDateToMillis(nowIso)!!))
        assertFalse(inspectionDateSelectable(isoDateToMillis(tomorrowIso)!!))
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
