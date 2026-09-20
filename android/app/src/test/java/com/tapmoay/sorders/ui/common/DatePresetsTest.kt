package com.tapmoay.sorders.ui.common

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.DayOfWeek
import java.time.LocalDate

/**
 * 日期档位的单测。
 *
 * 为什么值得钉：「本月」到底是"1 日~月末"还是"1 日~今天"、"上周"是"上周一~上周日"还是
 * "最近 7 天"—— 这些**两种都说得通**，所以只能靠测试把口径固定下来。
 * 更要紧的是**只有一份实现**：筛选条与账本页共用它，谁改了这里两处一起变。
 *
 * 基准日取 2026-09-16（**星期三**，且离月末还有半个月）：周一/月末这两个边界都在这一组里。
 */
class DatePresetsTest {

    private val wed = LocalDate.of(2026, 9, 16)

    @Test
    fun `基准日确实是星期三（下面几条断言都靠它）`() {
        assertEquals(DayOfWeek.WEDNESDAY, wed.dayOfWeek)
    }

    @Test
    fun `今天昨天前天都是单日窗口`() {
        assertEquals("2026-09-16" to "2026-09-16", DatePresets.rangeOf(DatePresets.TODAY, wed))
        assertEquals("2026-09-15" to "2026-09-15", DatePresets.rangeOf(DatePresets.YESTERDAY, wed))
        assertEquals("2026-09-14" to "2026-09-14", DatePresets.rangeOf(DatePresets.BEFORE_YESTERDAY, wed))
    }

    @Test
    fun `近 7 天含今天（6 天前到今天）`() {
        assertEquals("2026-09-10" to "2026-09-16", DatePresets.rangeOf(DatePresets.LAST_7, wed))
    }

    @Test
    fun `上周是上周一到上周日（不是最近 7 天）`() {
        // 2026-09-16 是星期三 → 本周一 = 09-14 → 上周一 = 09-07，上周日 = 09-13
        assertEquals("2026-09-07" to "2026-09-13", DatePresets.rangeOf(DatePresets.LAST_WEEK, wed))
    }

    @Test
    fun `这周是本周一到今天（2026-09-20 用户点名要的档）`() {
        // 用户原话：「第 2 层是时间上的统计，比如说，昨天、今天、前天、**这周**、这个月」
        assertEquals("2026-09-14" to "2026-09-16", DatePresets.rangeOf(DatePresets.THIS_WEEK, wed))
        // 周一那天 = 单日窗口（与「本月」在月初那天同形）
        assertEquals(
            "2026-09-14" to "2026-09-14",
            DatePresets.rangeOf(DatePresets.THIS_WEEK, LocalDate.of(2026, 9, 14)),
        )
        // 周日那天 = 整周（周一~周日），不是"只到今天"以外的别的东西
        assertEquals(
            "2026-09-14" to "2026-09-20",
            DatePresets.rangeOf(DatePresets.THIS_WEEK, LocalDate.of(2026, 9, 20)),
        )
    }

    @Test
    fun `上周在周一那天取到的仍然是上一周`() {
        val monday = LocalDate.of(2026, 9, 14)
        assertEquals("2026-09-07" to "2026-09-13", DatePresets.rangeOf(DatePresets.LAST_WEEK, monday))
    }

    @Test
    fun `本月是本月初到今天（不把未来算进来）`() {
        assertEquals("2026-09-01" to "2026-09-16", DatePresets.rangeOf(DatePresets.THIS_MONTH, wed))
        // 月初那天 = 单日窗口
        assertEquals("2026-09-01" to "2026-09-01", DatePresets.rangeOf(DatePresets.THIS_MONTH, LocalDate.of(2026, 9, 1)))
    }

    @Test
    fun `上月是整月（含 31 天与跨年）`() {
        assertEquals("2026-08-01" to "2026-08-31", DatePresets.rangeOf(DatePresets.LAST_MONTH, wed))
        // 跨年：1 月的上个月是去年 12 月
        assertEquals("2025-12-01" to "2025-12-31", DatePresets.rangeOf(DatePresets.LAST_MONTH, LocalDate.of(2026, 1, 5)))
        // 三月一日的上个月是 2 月，闰年 29 天
        assertEquals("2024-02-01" to "2024-02-29", DatePresets.rangeOf(DatePresets.LAST_MONTH, LocalDate.of(2024, 3, 1)))
    }

    @Test
    fun `全部与认不出的档都不带日期条件`() {
        assertNull("「全部」必须返回 null（调用方拿它当'不加条件'）", DatePresets.rangeOf(DatePresets.ALL, wed))
        assertNull("自定义的区间由调用方给，这里不许自己编一个", DatePresets.rangeOf(DatePresets.CUSTOM, wed))
        assertNull("认不出的档宁可查全量，也不要凭空造区间", DatePresets.rangeOf("上个季度", wed))
    }

    @Test
    fun `筛选条上每一档都算得出区间（除了全部）`() {
        DatePresets.ROW.forEach { label ->
            if (label == DatePresets.ALL) {
                assertNull(label, DatePresets.rangeOf(label, wed))
            } else {
                val r = DatePresets.rangeOf(label, wed)
                assertTrue("$label 没有区间（筛选条上会是一个点了没反应的胶囊）", r != null)
                assertTrue("$label 的区间是反的", (r!!.first <= r.second))
            }
        }
        assertTrue("「自定义」不该出现在档位表里（它要弹日期选择）", DatePresets.CUSTOM !in DatePresets.ROW)
    }

    @Test
    fun `自定义那一格的标签写的是日期而不是三个字`() {
        assertEquals("09-01~09-20", DatePresets.customLabel("2026-09-01", "2026-09-20"))
        assertEquals(DatePresets.CUSTOM, DatePresets.customLabel(null, null))
        assertEquals(DatePresets.CUSTOM, DatePresets.customLabel("2026-09-01", null))
    }
}
