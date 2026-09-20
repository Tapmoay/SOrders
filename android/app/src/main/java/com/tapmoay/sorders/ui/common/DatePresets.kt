package com.tapmoay.sorders.ui.common

import java.time.LocalDate

/**
 * 日期预设 —— **唯一一份实现**（订单/账本/库存流水的筛选条、派单员账本的日期行都走这里）。
 *
 * 为什么必须只有一份：「本月」如果在账本页算「1 日~月末」、在筛选条算「1 日~今天」，
 * 两处都"看起来对"，可一到对账，差的那几天没人说得清是谁的错。
 * 本仓库栽过同类问题（同一个"今天"在报表与结算页按不同时区算），所以这里把**档位与它的
 * 区间**放在同一个纯函数里：想改口径只能改这一处，两处同时变。
 *
 * 约定（写清楚，免得下一轮有人按自己的理解改）：
 * · 「本月」= 本月 1 日 ~ **今天**（未来的日子没有账，不把未来算进"这个月"）；
 * · 「上月」= 上月 1 日 ~ 上月最后一天；
 * · 「上周」= 上周一 ~ 上周日（**不是**"最近 7 天"——那是另一档，`近 7 天` 含今天）；
 * · 「全部」= **不带日期条件**（返回 null，调用方自己知道"这一档没有区间"）。
 *
 * ⚠️ 报表中心那套「按日/周/月」的时间导航**不是**这里的东西：它是"翻到哪一天/哪一周"，
 *    与"选一个常用窗口"是两件事，那一份在 `ui/common/ReportTimeNav.kt`。
 */
object DatePresets {

    const val ALL = "全部"
    const val TODAY = "今天"
    const val YESTERDAY = "昨天"
    const val BEFORE_YESTERDAY = "前天"
    const val LAST_7 = "近 7 天"
    const val LAST_WEEK = "上周"
    const val THIS_MONTH = "本月"
    const val LAST_MONTH = "上月"

    /** 「自定义」不由本表给区间（它要弹日期选择），所以**不在** [ROW] 里。 */
    const val CUSTOM = "自定义"

    /** 筛选条上按顺序显示的那几档（「自定义」由 UI 自己加在最后）。 */
    val ROW = listOf(ALL, TODAY, YESTERDAY, BEFORE_YESTERDAY, LAST_7, LAST_WEEK, THIS_MONTH, LAST_MONTH)

    /**
     * 这一档对应的日期区间（`YYYY-MM-DD`，两端都含）；返回 **null = 这一档不带限制**（全部）。
     *
     * @param today 由调用方传进来（而不是内部取 `now()`）：这样它是**纯函数**，
     *              月末、跨年、周一这些边界才测得了。
     */
    fun rangeOf(label: String, today: LocalDate): Pair<String, String>? = when (label) {
        ALL -> null
        TODAY -> today.toString() to today.toString()
        YESTERDAY -> today.minusDays(1).let { it.toString() to it.toString() }
        BEFORE_YESTERDAY -> today.minusDays(2).let { it.toString() to it.toString() }
        LAST_7 -> today.minusDays(6).toString() to today.toString()
        LAST_WEEK -> {
            // 本周一往前退一周 = 上周一；+6 天 = 上周日（周一为一周之首，与报表口径一致）
            val monday = today.minusDays((today.dayOfWeek.value - 1).toLong()).minusWeeks(1)
            monday.toString() to monday.plusDays(6).toString()
        }
        THIS_MONTH -> today.withDayOfMonth(1).toString() to today.toString()
        LAST_MONTH -> {
            val first = today.withDayOfMonth(1).minusMonths(1)
            first.toString() to first.withDayOfMonth(first.lengthOfMonth()).toString()
        }
        // 认不出的档（含「自定义」：它的区间由调用方给）→ **不加日期限制**。
        // 宁可查全量，也不要凭空造一个区间出来（造出来的区间会静默少算钱）。
        else -> null
    }

    /**
     * 「自定义」那一格的标签：两头都选好了就把那段日期写出来（`09-01~09-20`），
     * 而不是只写"自定义"三个字 —— 只写那三个字，用户就分不清"我选的到底是哪一段"。
     */
    fun customLabel(from: String?, to: String?): String =
        if (from != null && to != null) from.take(10).substring(5) + "~" + to.take(10).substring(5) else CUSTOM
}
