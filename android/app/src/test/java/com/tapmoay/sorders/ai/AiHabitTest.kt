package com.tapmoay.sorders.ai

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.LocalDate

/**
 * [AiHabits] 的单元测试。
 *
 * 这个功能会**改变模型的默认行为**，所以测试的重点不是"统计对不对"，而是两条纪律：
 * ① **样本不够就什么都不注入**（拿一两次偶发行为当"习惯"比不学更糟）；
 * ② 注入的文案里**必须带着"用户没说时才用 + 必须说明用了什么范围"这两条约束**——
 *    漏了它们，"学习习惯"就变成"擅自替用户决定"。
 */
class AiHabitTest {

    private fun tool(name: String, args: String = "{}") = ToolCallRecord(name, args)

    // ================================================================== 统计

    @Test
    fun observeAccumulatesToolsPeriodsAndQuestions() {
        var h = AiHabit()
        h = AiHabits.observe(
            h,
            listOf(
                tool(AiTools.DRIVER_PERFORMANCE, """{"date_from":"${today()}","date_to":"${today()}"}"""),
                tool(AiTools.DRIVER_PERFORMANCE),
            ),
            "这个月谁跑得最多？",
        )
        h = AiHabits.observe(h, listOf(tool(AiTools.INVENTORY_ALERTS)), "哪些货要补？")

        assertEquals(2, h.runs)
        assertEquals(2, h.toolCounts[AiTools.DRIVER_PERFORMANCE])
        assertEquals(1, h.toolCounts[AiTools.INVENTORY_ALERTS])
        assertEquals(1, h.periodCounts["今天"])
        assertEquals(listOf("哪些货要补？", "这个月谁跑得最多？"), h.recentQuestions)
    }

    @Test
    fun observeDedupsAndCapsQuestions() {
        var h = AiHabit()
        repeat(AiHabits.MAX_RECENT_QUESTIONS + 5) { i ->
            h = AiHabits.observe(h, emptyList(), "问题 $i")
        }
        assertEquals(AiHabits.MAX_RECENT_QUESTIONS, h.recentQuestions.size)
        assertTrue("最新的在最前面", h.recentQuestions.first() == "问题 24")

        // 重复问同一句不该占两条
        val again = AiHabits.observe(h, emptyList(), "问题 24")
        assertEquals(1, again.recentQuestions.count { it == "问题 24" })
    }

    @Test
    fun observeTruncatesVeryLongQuestions() {
        val h = AiHabits.observe(AiHabit(), emptyList(), "很".repeat(500))
        assertEquals(AiHabits.MAX_QUESTION_CHARS, h.recentQuestions.single().length)
    }

    // ================================================================== 时间范围识别

    @Test
    fun recognisesCommonPeriodsFromToolArguments() {
        val t = LocalDate.now()
        val thisFirst = t.withDayOfMonth(1)
        val lastEnd = thisFirst.minusDays(1)
        val lastFirst = lastEnd.withDayOfMonth(1)

        assertEquals("今天", AiHabits.periodOf("""{"date_from":"$t","date_to":"$t"}"""))
        assertEquals("本月", AiHabits.periodOf("""{"date_from":"$thisFirst","date_to":"$t"}"""))
        assertEquals("上月", AiHabits.periodOf("""{"date_from":"$lastFirst","date_to":"$lastEnd"}"""))
        assertEquals("近 7 天", AiHabits.periodOf("""{"date_from":"${t.minusDays(6)}","date_to":"$t"}"""))
    }

    @Test
    fun unknownOrMissingPeriodIsNotRecorded() {
        // 认不出就不记 —— 记错了会污染"他常用本月"这种结论
        assertNull(AiHabits.periodOf("""{"date_from":"2020-01-01","date_to":"2020-03-15"}"""))
        assertNull(AiHabits.periodOf("{}"))
        assertNull(AiHabits.periodOf("不是 JSON"))
    }

    // ================================================================== 注入提示词

    @Test
    fun noHintUntilEnoughSamples() {
        var h = AiHabit()
        repeat(AiHabits.MIN_SAMPLES - 1) { h = AiHabits.observe(h, listOf(tool(AiTools.SEARCH_SHIPPER)), "问") }
        assertNull("样本不够时什么都不注入", AiHabits.promptHint(h))
    }

    @Test
    fun hintCarriesTheTwoDisciplineRules() {
        var h = AiHabit()
        repeat(AiHabits.MIN_SAMPLES) {
            h = AiHabits.observe(
                h,
                listOf(tool(AiTools.DRIVER_PERFORMANCE, """{"date_from":"${thisMonthFirst()}","date_to":"${today()}"}""")),
                "谁跑得最多",
            )
        }
        val hint = AiHabits.promptHint(h) { AiTools.titleOf(it) }
        assertTrue(hint != null)
        val text = hint!!
        assertTrue("要带上样本量，让模型知道这个结论有多可信", text.contains("${AiHabits.MIN_SAMPLES} 次对话"))
        assertTrue("要说清常用查询", text.contains(AiTools.titleOf(AiTools.DRIVER_PERFORMANCE)))
        assertTrue("要认出惯用时间范围", text.contains("本月"))
        // 两条纪律：不越权 + 必须说明范围。缺任何一条，"学习"都会变成"擅自决定"
        assertTrue("必须写明只在用户没说清时当默认", text.contains("没说清楚"))
        assertTrue("必须要求模型说明它用了什么范围", text.contains("写明你按什么范围"))
    }

    @Test
    fun hintIsEmptyWhenNothingWasObserved() {
        assertNull(AiHabits.promptHint(AiHabit(runs = 99)))
    }

    // ================================================================== 编解码

    @Test
    fun encodeDecodeRoundTripAndToleratesGarbage() {
        var h = AiHabit()
        h = AiHabits.observe(h, listOf(tool(AiTools.INVENTORY_ALERTS)), "货要补吗")
        val back = AiHabits.decode(AiHabits.encode(h))
        assertEquals(h.runs, back.runs)
        assertEquals(h.toolCounts, back.toolCounts)
        assertEquals(h.recentQuestions, back.recentQuestions)

        // 坏数据一律退回空习惯，绝不抛（习惯丢了不影响任何功能）
        assertEquals(AiHabit(), AiHabits.decode("{不是 json"))
        assertEquals(AiHabit(), AiHabits.decode(""))
        assertEquals(AiHabit(), AiHabits.decode(null))
    }

    @Test
    fun decodeIgnoresUnknownFields() {
        val back = AiHabits.decode("""{"runs":5,"futureField":"x","toolCounts":{"a":1}}""")
        assertEquals(5, back.runs)
        assertEquals(mapOf("a" to 1), back.toolCounts)
    }

    private fun today(): String = LocalDate.now().toString()

    private fun thisMonthFirst(): String = LocalDate.now().withDayOfMonth(1).toString()

    @Test
    fun hintHasNoHintWhenSwitchIsOff() {
        // 关掉开关时 ViewModel 根本不会调 promptHint（见 AiChatViewModel.prepareSystemExtra），
        // 这里钉住"函数本身不依赖开关"这一点，避免以后有人在里面偷偷读设置造成两处判断不一致
        var h = AiHabit()
        repeat(AiHabits.MIN_SAMPLES) { h = AiHabits.observe(h, listOf(tool(AiTools.INVENTORY_ALERTS)), "q") }
        assertFalse(AiHabits.promptHint(h).isNullOrBlank())
    }
}
