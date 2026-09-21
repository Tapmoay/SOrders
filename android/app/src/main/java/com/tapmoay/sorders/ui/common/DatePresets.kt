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
    const val THIS_WEEK = "这周"
    const val LAST_7 = "近 7 天"
    const val LAST_WEEK = "上周"
    const val THIS_MONTH = "本月"
    const val LAST_MONTH = "上月"
    /**
     * 「近一年」= 今天往前 365 天（含今天）。
     *
     * 2026-09-20 用户点名要它（「这周、这个月、[近]一年啊，这些都可以，这预设好的，它都可以选择」）：
     * 账本是**三年**数据，只到「上月」的话"去年的账"只能靠自定义去点两次日期。
     * 口径与「近 7 天」同形（含今天，所以是 `minusDays(364)` 而不是 365）。
     */
    const val LAST_YEAR = "近一年"

    /** 「自定义」不由本表给区间（它要弹日期选择），所以**不在** [ROW] 里。 */
    const val CUSTOM = "自定义"

    /** 筛选条上按顺序显示的那几档（「自定义」由 UI 自己加在最后）。 */
    val ROW = listOf(
        ALL, TODAY, YESTERDAY, BEFORE_YESTERDAY, THIS_WEEK, LAST_7, LAST_WEEK,
        THIS_MONTH, LAST_MONTH, LAST_YEAR,
    )

    /**
     * **账本/开销这类"一打开就该有数"的页面**自动退档用的阶梯：
     * 今天 → 昨天 → 前天 → 近 7 天（都没有再落到 [ALL]）。
     *
     * 为什么把这四档放进来而不是各页各写一份：这已经是**第四个**页面要"今天没数就往前退"
     * （派单员账本、开销管理、货主账本，加上司机那两个），几份写死的清单必然走散 ——
     * 而走散的表现是"同一个默认行为在两个页面上不一样"，用户只会觉得系统不稳。
     *
     * ⚠️ 它**不是**"所有页面都该用这一条"：看**订单/账单**的页面用的是更长的一条
     * （[ORDER_PRESET_LADDER]：今天→昨天→前天→这周→上周→近 7 天→本月→上月）——
     * 因为**找一张单**比"看一本账"更可能不在今天，"这周/上周"对"这单派给谁了"是有意义的窗口。
     * 要用更长的那条就显式引用它，别悄悄改这一条（改了这一条，别的页面会跟着动）。
     */
    val AUTO_LADDER = listOf(TODAY, YESTERDAY, BEFORE_YESTERDAY, LAST_7)

    /**
     * **看订单 / 账单的页面**自动退档用的阶梯（比 [AUTO_LADDER] 长一截）：
     * 今天 → 昨天 → 前天 → 这周 → 上周 → 近 7 天 → 本月 → 上月（都没有时兜底 [ALL]）。
     *
     * 谁在用：司机任务（`DriverOrdersViewModel`）、司机账单（`DriverFreightViewModel`）、
     * 派单员「订单管理」、货主「我的订单」—— 都是"一条一条的记录"，而且都可能**今天没有**。
     *
     * 用户原话：2026-09-20（司机任务）「默认是看今天的，然后其次再往上推昨天、前天、这周，
     * 然后上周依次类推」；2026-09-22（两个订单列表）「他们是有那个**找订单的规则**，
     * 也就是**自动挡**，他需要做」。
     *
     * ⚠️ 家安在这里是有原因的（原来在 `ui/driver/DriverOrdersViewModel.kt` 里，只有司机那两页用）：
     *    阶梯一旦有第二个使用者，"谁抄了谁"就没人说得清 —— 这与 [AUTO_LADDER] 是同一条道理。
     */
    val ORDER_PRESET_LADDER = listOf(
        TODAY, YESTERDAY, BEFORE_YESTERDAY, THIS_WEEK, LAST_WEEK, LAST_7, THIS_MONTH, LAST_MONTH,
    )

    /**
     * **先把窗口定下来，再取那一次数** —— 所有"一打开就该有数"的页面共用这一条。
     *
     * ### 用户 2026-09-21 的原话（他报的是一个看得见的毛病）
     * > 「我在点击我的账本的时候，它会**闪两下**再跳到「前天」……我在点击账本之前，
     * >   它就已经**提前盘点好了**：今天有账就直接出今天，今天没账再换前天……
     * >   其他派单员那些账本界面基本上也是这个逻辑，**闪两下已经不行了**，不美观，且占用性能。」
     *
     * ### 为什么会闪（以及为什么"先按今天拉一次"是错的）
     * 老写法是「先按今天就位并**取一次数**（屏幕立刻有东西），真没单再异步退档」——
     * 于是最坏情况要画三帧：**今天（加载）→ 今天（空态）→ 前天（有数据）**。
     * 用户看到的就是"闪两下"，而且白发了一次注定被丢掉的请求。
     *
     * ### 现在的形状
     * 先只做**探测**（每档 `limit=1`，便宜），拿到那个"真有数"的档位、**只取一次数**。
     * 页面那边配一个 `windowSettled` 门：定下来之前整页是 loading，**一次都不画错窗口**。
     *
     * @param ladder 候选档位（默认 [AUTO_LADDER]；司机端传自己那条更长的）
     * @param hasData 这一档有没有数（**判据必须与页面自己的取数同源**，见各页注释）
     * @return 该用的档位：阶梯里第一个有数的；都没有 → [ALL]（不带日期条件，至少看得到全貌）
     */
    suspend fun pickWindow(
        ladder: List<String> = AUTO_LADDER,
        hasData: suspend (String) -> Boolean,
    ): String {
        for (label in ladder) {
            if (hasData(label)) return label
        }
        return ALL
    }

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
        // 「这周」= 本周一 ~ **今天**（与「本月」同一条理由：未来的日子没有账）。
        // ⚠️ 与「上周」是一对：那一档是**整周**（周一~周日），这一档只到今天 ——
        //    两档都按"周一为一周之首"，各写一份周首算法就会出现"这周比上周少一天"。
        THIS_WEEK -> today.minusDays((today.dayOfWeek.value - 1).toLong()).toString() to today.toString()
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
        // 「近一年」= 今天往前 365 天（含今天）—— 与「近 7 天」同一个写法（`minusDays(N-1)`），
        // 两种写法的差别是"到底 365 天还是 366 天"，用户看不出来，但**对账时会差一天**。
        LAST_YEAR -> today.minusDays(364).toString() to today.toString()
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
