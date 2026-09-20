package com.tapmoay.sorders.ui.dispatcher

import com.tapmoay.sorders.core.ledgerSourceLabel
import com.tapmoay.sorders.data.remote.dto.FreightSettlementGroupDto
import com.tapmoay.sorders.data.remote.dto.LedgerEntryDto
import com.tapmoay.sorders.util.moneyToDouble
import java.time.LocalDate

/**
 * 账本页那三张图的**取数规则** —— 纯函数，有单测。
 *
 * 为什么单独放一份：图表上的数**必须**与屏幕上那几个合计同源。图自己另算一遍
 * （比如"金额 = 只算正数""日期读不出来的跳过"这些细节各写一遍），就会变成
 * 「上面写 ¥3,200、扇形加起来 ¥2,800」——两个数都不报错，用户只能怀疑人生。
 * 所以这里只做**分组与排序**：输入就是页面已经在用的那几批数据。
 *
 * 三条口径写死在这里，改之前先想清楚：
 * 1. **日期读不出来的行不计入按天序列**（不当成今天：把不知哪天的钱算进今天，是凭空造数）；
 * 2. **按天序列会把区间里没有流水的那天补成 0**（折线图缺天会"跳着画"，趋势看着就变平了）；
 * 3. 扇形最多 [MAX_SLICES] 块，其余合并成「其他」，**但绝不丢**（丢掉的话占比加起来不到 100%）。
 */

/** 扇形最多画几块：再多就是一圈细线，谁也读不出来。 */
const val MAX_SLICES = 6

/** 合并后的那一块的名字（图例上要能一眼看出"这不是某一项，是其余合计"）。 */
const val OTHER_SLICE = "其他"

// 三种图的类型码与显示名 —— 页面上的切换条与这里**同一份**（各写一份会出现"点条形出来折线"）。
const val CHART_LINE = "line"
const val CHART_BAR = "bar"
const val CHART_PIE = "pie"
val CHART_TYPES_ALL = listOf(CHART_LINE, CHART_BAR, CHART_PIE)

/** 图表类型的显示名。 */
fun chartTypeLabel(type: String): String = when (type) {
    CHART_LINE -> "折线"
    CHART_BAR -> "条形"
    else -> "扇形"
}

/**
 * 这一档账**有哪几种图可选**（纯函数，有单测）。
 *
 * ⚠️ 货主账（2）/ 批发商账（3）**没有折线**：`/ledger/accounts` 只回账户汇总、没有按天的数。
 *    拿明细接口（`/ledger/entries`，一页最多 1000 条）去凑一条曲线，会在明细被截断时
 *    画出一条**比上面合计小**的线 —— 同一屏两个数，比"少一种图"糟得多。
 */
fun chartTypesFor(tab: Int): List<String> =
    if (tab == 0 || tab == 1) CHART_TYPES_ALL else listOf(CHART_BAR, CHART_PIE)

/**
 * 图上的日期标签：`2026-09-20` → `09/20`。
 *
 * **折线与条形共用这一份**：两边各截一次的话，同一段时间在两张图上的标签会不一致
 * （一边 `09/20`、一边 `2026-09-20`），切换图表时看着像换了数据。
 */
fun dayLabel(date: String): String {
    val d = date.take(10)
    return if (d.length == 10) d.substring(5).replace("-", "/") else d
}

/** 条形图上"账户名"这类标签最多留几个字（再长会把旁边的标签挤出屏）。 */
fun shortLabel(name: String): String = if (name.length <= 6) name else name.take(6) + "…"

/**
 * 按天汇总。`rows` 是 (日期文本, 金额) 对，日期只取前 10 位（`YYYY-MM-DD`）。
 *
 * [from]/[to] 给全了就**按日历补零**（含首含尾）；不给（「全部」那一档）就只列有流水的那几天。
 */
fun dailySeries(
    rows: List<Pair<String, Double>>,
    from: String? = null,
    to: String? = null,
): List<Pair<String, Double>> {
    val buckets = LinkedHashMap<String, Double>()
    rows.forEach { (rawDate, amount) ->
        val day = rawDate.take(10)
        if (day.length == 10) buckets[day] = (buckets[day] ?: 0.0) + amount
    }
    if (from == null || to == null) {
        return buckets.entries.sortedBy { it.key }.map { it.key to it.value }
    }
    val start = runCatching { LocalDate.parse(from) }.getOrNull()
    val end = runCatching { LocalDate.parse(to) }.getOrNull()
    // 区间本身读不出来时退回"只列有流水的那几天"，**不要**凭空画一条空线
    if (start == null || end == null) return buckets.entries.sortedBy { it.key }.map { it.key to it.value }
    val out = ArrayList<Pair<String, Double>>()
    var d: LocalDate = start   // 上面已经判过 null（写成 var d = start 的话类型仍是 LocalDate?）
    while (!d.isAfter(end)) {
        out += d.toString() to (buckets[d.toString()] ?: 0.0)
        d = d.plusDays(1)
    }
    return out
}

/**
 * 扇形/排行的切片：金额倒序取前 [max] 项，其余合并成 [OTHER_SLICE]。
 *
 * 合并的那一块**排在最后**（不按金额插回去）：它是"剩余合计"，混在中间会让人以为
 * 它是某个具体的账户。
 */
fun topSlices(items: List<Pair<String, Double>>, max: Int = MAX_SLICES): List<Pair<String, Double>> {
    val named = items.filter { it.second > 0.0 }.sortedByDescending { it.second }
    if (named.size <= max) return named
    val head = named.take(max - 1)
    val rest = named.drop(max - 1).sumOf { it.second }
    return head + (OTHER_SLICE to rest)
}

// ---------------------------------------------------------------- 订单账

/** 订单账：按天（`entry_date`）。 */
fun orderDailySeries(entries: List<LedgerEntryDto>, from: String? = null, to: String? = null): List<Pair<String, Double>> =
    dailySeries(entries.map { it.entryDate to moneyToDouble(it.total) }, from, to)

/** 订单账：按**来源**（订单入账 / 手工记账 / 货损红冲）——「这笔钱是怎么来的」。 */
fun orderSourceTotals(entries: List<LedgerEntryDto>): List<Pair<String, Double>> {
    val buckets = LinkedHashMap<String, Double>()
    entries.forEach { e ->
        val label = ledgerSourceLabel(e.source)
        buckets[label] = (buckets[label] ?: 0.0) + moneyToDouble(e.total)
    }
    return buckets.entries.sortedByDescending { it.value }.map { it.key to it.value }
}

// ---------------------------------------------------------------- 司机账

/**
 * 司机账：按天（送达时间 `delivered_at`）× **司机应得** `pay_total`。
 *
 * ⚠️ 口径与组头的 `total` 完全一致（后端 `driver_pay.pay_for_order` 逐单累加）——
 *    这里要是拿 `freight_fee`（货主运费）求和，图上就会比上面那个合计多出一截，
 *    而两张数都在同一屏（2026-09-19 审计踩过：账单 675 / 司机端 1500）。
 */
fun driverDailySeries(groups: List<FreightSettlementGroupDto>, from: String? = null, to: String? = null): List<Pair<String, Double>> =
    dailySeries(
        groups.flatMap { g -> g.orders.map { (it.deliveredAt ?: "") to moneyToDouble(it.payTotal) } },
        from,
        to,
    )

/** 司机账：按司机（谁应得多少）——扇形与排行共用。 */
fun driverTotals(groups: List<FreightSettlementGroupDto>): List<Pair<String, Double>> =
    groups.map { (it.driverName.ifBlank { "司机 " + it.driverId }) to it.total }

// ---------------------------------------------------------------- 货主账 / 批发商账

/**
 * 货主账 / 批发商账：按账户。
 *
 * ⚠️ 这两个接口（`/ledger/accounts`）**只回账户汇总、没有按天的数**，所以这两类账只给
 *    「排行/构成」两种图，不给折线 —— 拿明细接口去凑一条按天曲线，会在明细被截断时
 *    画出一条比上面合计小的线（同一屏两个数），那比"少一种图"糟得多。
 */
fun accountTotals(rows: List<LedgerAccountRow>): List<Pair<String, Double>> =
    rows.map { (it.title.ifBlank { "未命名" }) to it.total }
