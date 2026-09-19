package com.tapmoay.sorders.ai

import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json

/**
 * 「这位派单员的使用习惯」——**本机统计，不出手机**。
 *
 * ### 它解决什么
 * 同一个人反复问同类问题（"这个月谁下单最多"），每次都要把时间范围、口径说全。
 * 把**他惯用的口径**记下来注入提示词，模型就能在他没说清时按他的习惯来，
 * 而不是每次反问一遍。
 *
 * ### 采集什么、不采集什么（写清楚，因为这是"学习用户行为"）
 * **采集**：调用过哪些工具（次数）、传过哪些时间区间（次数）、问过的问题原文（最近若干条）。
 * **不采集**：任何业务数据的**结果**（金额、客户名等不额外留存——它们本来就在对话历史里）；
 * 不做跨设备同步；不上传服务器。
 *
 * ### 注入提示词时的三条纪律（否则"学习"会变成"擅自替用户决定"）
 * 1. 只作为**默认值**注入，且明确写着"用户没说时才用"；
 * 2. 要求模型**在回答里说明它用了什么范围**（不能悄悄按习惯算）；
 * 3. 数据不足（[MIN_SAMPLES] 次以下）时**什么都不注入**——
 *    拿一两次偶发行为当"习惯"比不学更糟。
 */
@Serializable
data class AiHabit(
    /** 工具名 → 调用次数。 */
    val toolCounts: Map<String, Int> = emptyMap(),
    /** 时间区间「形状」→ 次数，例如 `本月` / `上月` / `近7天`。 */
    val periodCounts: Map<String, Int> = emptyMap(),
    /** 最近问过的问题（去重、倒序、限量），用于判断他关心什么。 */
    val recentQuestions: List<String> = emptyList(),
    /** 累计对话轮数（用于判断样本够不够）。 */
    val runs: Int = 0,
)

object AiHabits {

    /** 问题只留最近这么多条（内存/文件都不膨胀）。 */
    const val MAX_RECENT_QUESTIONS = 20

    /** 单条问题最多存这么多字。 */
    const val MAX_QUESTION_CHARS = 60

    /** 少于这么多次对话就不算"习惯"（见类注释纪律 3）。 */
    const val MIN_SAMPLES = 3

    /** 注入提示词时最多列几个工具。 */
    private const val MAX_TOOLS_IN_HINT = 3

    private val json = Json {
        ignoreUnknownKeys = true
        encodeDefaults = true
    }

    /** 序列化（存本地 prefs 用）。 */
    fun encode(habit: AiHabit): String = json.encodeToString(AiHabit.serializer(), habit)

    /** 反序列化。**坏数据一律退回空习惯**，绝不抛异常（习惯丢了不影响任何功能）。 */
    fun decode(text: String?): AiHabit {
        if (text.isNullOrBlank()) return AiHabit()
        return try {
            json.decodeFromString(AiHabit.serializer(), text)
        } catch (e: Exception) {
            AiHabit()
        }
    }

    /**
     * 累积一次对话的观察结果。
     *
     * @param toolCalls 本轮真实发生过的工具调用（由 agent 循环回报）
     * @param question  本轮用户问的话
     */
    fun observe(
        habit: AiHabit,
        toolCalls: List<ToolCallRecord>,
        question: String,
    ): AiHabit {
        val tools = habit.toolCounts.toMutableMap()
        val periods = habit.periodCounts.toMutableMap()
        toolCalls.forEach { c ->
            tools[c.name] = (tools[c.name] ?: 0) + 1
            periodOf(c.arguments)?.let { periods[it] = (periods[it] ?: 0) + 1 }
        }
        val q = question.trim().replace('\n', ' ').take(MAX_QUESTION_CHARS)
        val recent = (listOf(q).filter { it.isNotEmpty() } + habit.recentQuestions)
            .distinct()
            .take(MAX_RECENT_QUESTIONS)
        return habit.copy(
            toolCounts = tools,
            periodCounts = periods,
            recentQuestions = recent,
            runs = habit.runs + 1,
        )
    }

    /**
     * 从工具参数里认出"他常用哪个时间范围"。
     *
     * 做法是**看它实际传了什么**，而不是猜——认得出就记：`date_from == 当月 1 号` = 本月，
     * `date_from/date_to 都在上个月` = 上月，窗口 7 天 = 近 7 天。
     * 认不出（自定义区间）就**不记**，避免污染统计。
     */
    fun periodOf(argumentsJson: String): String? {
        val from = DATE_FROM.find(argumentsJson)?.groupValues?.get(1) ?: return null
        val to = DATE_TO.find(argumentsJson)?.groupValues?.get(1) ?: from
        val f = parseDate(from) ?: return null
        val t = parseDate(to) ?: return null
        val days = java.time.temporal.ChronoUnit.DAYS.between(f, t) + 1
        val today = java.time.LocalDate.now()
        val thisFirst = today.withDayOfMonth(1)
        val lastEnd = thisFirst.minusDays(1)
        return when {
            f == thisFirst && t == today -> "本月"
            f == lastEnd.withDayOfMonth(1) && t == lastEnd -> "上月"
            days == 7L && t == today -> "近 7 天"
            days == 1L && t == today -> "今天"
            days == 1L -> "某一天"
            else -> null
        }
    }

    private val DATE_FROM = Regex(""""date_from"\s*:\s*"([\d-]{10})"""")
    private val DATE_TO = Regex(""""date_to"\s*:\s*"([\d-]{10})"""")

    private fun parseDate(s: String): java.time.LocalDate? = try {
        java.time.LocalDate.parse(s)
    } catch (e: Exception) {
        null
    }

    /**
     * 生成要注入 system prompt 的几行；**数据不足时返回 null**（什么都不注入）。
     *
     * 措辞上刻意反复强调"用户没说时才用" + "必须说明用了什么范围"——
     * 这段文字会直接改变模型的默认行为，写含糊了它就会把习惯当成用户的要求。
     */
    fun promptHint(habit: AiHabit, toolTitle: (String) -> String = { it }): String? {
        if (habit.runs < MIN_SAMPLES) return null
        val topTools = habit.toolCounts.entries
            .sortedByDescending { it.value }
            .take(MAX_TOOLS_IN_HINT)
        val topPeriod = habit.periodCounts.entries.maxByOrNull { it.value }
        if (topTools.isEmpty() && topPeriod == null) return null

        return buildString {
            appendLine("【这位派单员的使用习惯】（本机统计，共 ${habit.runs} 次对话）")
            if (topTools.isNotEmpty()) {
                appendLine("他常用的查询：" + topTools.joinToString("、") { "${toolTitle(it.key)}(${it.value}次)" })
            }
            if (topPeriod != null && topPeriod.value >= MIN_SAMPLES) {
                appendLine("他问时间范围时，多数指的是「${topPeriod.key}」。")
            }
            appendLine("用法约束（必须遵守）：")
            appendLine("- 上面这些只在他**没说清楚**时作为默认值；他一旦说了范围/对象，一律以他说的为准。")
            appendLine("- 用了默认值时，**必须在回答里写明你按什么范围统计的**，不能悄悄按习惯算。")
        }
    }
}
