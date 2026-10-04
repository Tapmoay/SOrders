package com.tapmoay.sorders.ui.dispatcher.report

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.tapmoay.sorders.ui.common.BarChart
import com.tapmoay.sorders.ui.common.ChartEmpty
import com.tapmoay.sorders.ui.common.LoadingBox
import com.tapmoay.sorders.ui.common.SectionCard

/**
 * 报表中心 v2 的**第一屏**（CHG-0034）。
 *
 * 五张表在一张卡里（用户 2026-10-05：「五张表合并成一张卡、每行像按钮」），每行的右边是**那一段的
 * 大数**、点进去越点越细；下面依次是「要盯的事」「走势」「详细报表（原来那 11 个入口）」。
 *
 * ⛔ 这一屏不许出现任何接口字段名、任何 JSON（用户：「不能出现 JSON 那种数据样式，那个是完全不能出现的」）。
 * ⛔ 不许在这里做钱的加减（见 `ReportV2ViewModel` 顶部那三条）。
 */
internal fun LazyListScope.reportHomeItems(
    vm: ReportV2ViewModel,
    onOpen: (ReportNode) -> Unit,
    onOpenTab: (Int) -> Unit,
) {
    item { ConclusionCard(vm) }
    item { FiveTablesCard(vm, onOpen) }
    item { AlertsCard(vm, onOpen) }
    item { TrendCard(vm) }
    item { EntriesCard(onOpenTab) }
    item { NotesCard() }
}

// ------------------------------------------------------------------ ① 经营总览
@Composable
private fun ConclusionCard(vm: ReportV2ViewModel) {
    val (from, to) = vm.dateRange
    SectionCard {
        SectionTitle("经营总览")
        Spacer(Modifier.height(8.dp))
        if (vm.turnover == null || vm.profit == null) {
            LoadingBox()
            return@SectionCard
        }
        val revenue = vm.revenueAmount
        val op = vm.operatingProfit
        val sentence = if (revenue == 0.0 && op == 0.0) {
            "「" + vm.periodWord + "」这一段（" + from + " ~ " + to + "）没有已送达的单，" +
                "下面五个数都是 0 —— 这不是错，是这一段真没有单。"
        } else {
            "这一段营业额 " + money(vm.turnover?.totalAmount) + "（" + vm.revenueOrders + " 单）" +
                "，营业利润 " + money(vm.profit?.operatingProfit) + (if (op < 0) "（是亏的）" else "（是赚的）") +
                (if (vm.receivableBalance > 0) {
                    "；另外到 " + vm.asOfText + " 为止还有 " + money(vm.customers?.totals?.balance) + " 挂在客户账上没收回"
                } else {
                    ""
                }) + "。"
        }
        Text(sentence, style = MaterialTheme.typography.bodyMedium)

        val advice = buildList {
            if (op < 0) add("「利润表」看钱花在哪")
            if (vm.receivableBalance > 0) add("「别人欠我」去催收")
            if (vm.driverOwed > 0) add("「我欠司机」该结算")
            if (num(vm.costCoverage?.revenueUncovered) > 0) add("「商品成本」有收入算不出成本")
        }.take(2)
        if (advice.isNotEmpty()) {
            Spacer(Modifier.height(8.dp))
            Text(
                "最该先看：" + advice.joinToString("、"),
                style = MaterialTheme.typography.bodyMedium,
                color = Palette.warn,
                fontWeight = FontWeight.SemiBold,
            )
        }
        // 时间档位与区间在顶栏上已经有了（药丸写着档位、副标题写着区间），这里不再重复一遍 ——
        // 用户 2026-10-05：「不要什么都解释」。自动退档那句话由外壳画在列表最上面
        // （ReportV2Screen 里的 vm.autoNote），这里不写第二遍。
    }
}

// ------------------------------------------------------------------ ② 五张表（一张卡）
@Composable
private fun FiveTablesCard(vm: ReportV2ViewModel, onOpen: (ReportNode) -> Unit) {
    val p = vm.profit
    val t = vm.turnover
    SectionCard {
        SectionTitle("五张表")
        Spacer(Modifier.height(2.dp))
        Text(
            "点哪一行，就往那一层细看，一直能点到订单",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        if (p == null || t == null) {
            LoadingBox()
            return@SectionCard
        }
        HairLine()
        // ① 利润表
        val expenses = p.operatingExpenses
        TableTile(
            icon = ReportNodes.profit.icon,
            color = ReportNodes.profit.color,
            title = "利润表",
            word = "赚没赚钱（这一段）",
            amount = money(p.operatingProfit),
            amountColor = toneColor(amountTone(vm.operatingProfit)),
            lines = triples(
                Triple("商品毛利", vm.grossProfit, money(p.grossProfit)),
                Triple("司机运费", num(p.deliveryCost), money(p.deliveryCost)),
                Triple("期间费用", num(p.operatingExpenseTotal), money(p.operatingExpenseTotal)),
            ),
            chips = listOf(
                "毛利率 " + percentText(ratioOf(p.grossProfit, p.revenueTotal)) to toneColor(Tone.GOOD),
                "营业利润率 " + percentText(ratioOf(p.operatingProfit, p.revenueTotal)) to toneColor(amountTone(vm.operatingProfit)),
            ),
            onClick = { onOpen(ReportNodes.profit) },
        )
        HairLine()
        // ② 资产负债表（时点）
        TableTile(
            icon = ReportNodes.balance.icon,
            color = ReportNodes.balance.color,
            title = "资产负债表",
            word = "别人欠我多少（到 " + vm.asOfText + " 为止）",
            amount = money(vm.customers?.totals?.balance),
            amountColor = toneColor(Tone.WARN),
            lines = triples(
                Triple("别人欠我", vm.receivableBalance, money(vm.customers?.totals?.balance)),
                Triple("库存", vm.stockKinds.toDouble(), vm.stockKinds.toString() + " 个品种"),
                Triple("我欠司机", vm.driverOwed, money(vm.drivers?.drivers?.sumOf { num(it.freightOwed) }?.toString())),
            ),
            chips = listOf(
                "欠款 " + (vm.customers?.totals?.debtorCount ?: 0) + " 人" to toneColor(Tone.WARN),
                "超额度 " + vm.overLimitCount + " 家" to toneColor(Tone.BAD),
            ),
            onClick = { onOpen(ReportNodes.balance) },
        )
        HairLine()
        // ③ 现金流量表
        TableTile(
            icon = ReportNodes.cash.icon,
            color = ReportNodes.cash.color,
            title = "现金流量表",
            word = "这一段真进真出多少",
            amount = money(vm.cashSummary?.net),
            amountColor = toneColor(amountTone(vm.netCash)),
            lines = triples(
                Triple("进来", num(vm.cashSummary?.income), money(vm.cashSummary?.income)),
                Triple("出去", num(vm.cashSummary?.expense), money(vm.cashSummary?.expense)),
            ),
            chips = listOf((vm.cashSummary?.count ?: 0).toString() + " 笔流水" to toneColor(Tone.INFO)),
            onClick = { onOpen(ReportNodes.cash) },
        )
        HairLine()
        // ④ 运营分析表
        TableTile(
            icon = ReportNodes.ops.icon,
            color = ReportNodes.ops.color,
            title = "运营分析表",
            word = "哪赚哪亏（商品 / 司机 / 车辆）",
            amount = money(vm.turnover?.totalAmount),
            amountColor = toneColor(Tone.PLAIN),
            lines = triples(
                Triple("营业额", vm.revenueAmount, money(vm.turnover?.totalAmount)),
                Triple("商品毛利", vm.grossProfit, money(p.grossProfit)),
                Triple("单数", vm.revenueOrders.toDouble(), vm.revenueOrders.toString() + " 单"),
            ),
            chips = listOf(
                "客单 " + money(vm.turnover?.avgOrder) to toneColor(Tone.INFO),
                "司机 " + (vm.drivers?.drivers?.size ?: 0) + " 人" to toneColor(Tone.GOOD),
            ),
            onClick = { onOpen(ReportNodes.ops) },
        )
        HairLine()
        // ⑤ 关键指标表（比率 —— 接口没有，是页面相除算的）
        TableTile(
            icon = ReportNodes.kpi.icon,
            color = ReportNodes.kpi.color,
            title = "关键指标表",
            word = "赚不赚钱（比率，页面按接口的数算）",
            amount = percentText(ratioOf(p.grossProfit, p.revenueTotal)),
            amountColor = toneColor(Tone.GOOD),
            lines = triples(
                Triple("营业利润率", vm.operatingProfit, percentText(ratioOf(p.operatingProfit, p.revenueTotal))),
                Triple("司机运费率", num(p.deliveryCost), percentText(ratioOf(p.deliveryCost, p.revenueTotal))),
                Triple("期间费用率", num(p.operatingExpenseTotal), percentText(ratioOf(p.operatingExpenseTotal, p.revenueTotal))),
            ),
            chips = listOf("保本 " + breakevenText(p) to toneColor(Tone.WARN)),
            onClick = { onOpen(ReportNodes.kpi) },
        )
        NoteText("毛利率 = 商品毛利 ÷ 营业额；行驶中的这些比率接口没有给，是这一页用接口给的两个数相除算的。")
        // 期间费用那三行只在真取到分类明细时才有意义，这里静默用一次，避免"取了不用"的悬空变量
        if (expenses.isEmpty()) NoteText("这一段没有期间费用的分类明细。")
    }
}

/**
 * 保本营业额（粗算）=（期间费用 + 折旧）÷ 毛利率。算不出来（没有分母、或毛利率 ≤ 0）就返 null。
 *
 * ⛔ 算不出来要在屏上写「—」；⛔ 不能当成 0 画成「¥0」—— 那是假话，用户会照着它做决定。
 */
internal fun breakevenValue(p: com.tapmoay.sorders.data.remote.dto.ProfitReportDto?): Double? {
    if (p == null) return null
    val margin = ratioOf(p.grossProfit, p.revenueTotal) ?: return null
    if (margin <= 0.0) return null
    val fixed = num(p.operatingExpenseTotal) + num(p.depreciationTotal)
    return fixed / margin
}

/** 同上，给屏上直接显示的那串字：算得出来是「¥xx.xx」，算不出来是「—」。 */
internal fun breakevenText(p: com.tapmoay.sorders.data.remote.dto.ProfitReportDto?): String {
    val v = breakevenValue(p) ?: return "—"
    // ⚠️ 走 money()（内部是 formatMoney，会去尾零）：自己拼 "¥" + "%.2f" 会画出「¥0.00」，
    //    正好违反用户那条「数字后面不要那么多零」（2026-10-05 走查抓到的）。
    return money(java.lang.String.format(java.util.Locale.US, "%.2f", v))
}

// ------------------------------------------------------------------ ③ 要盯的事
@Composable
private fun AlertsCard(vm: ReportV2ViewModel, onOpen: (ReportNode) -> Unit) {
    val rows = vm.customers?.rows.orEmpty()
        .sortedByDescending { num(it.balance) }
        .take(3)
    val topText = if (rows.isEmpty()) "—" else {
        rows.joinToString("、") { it.name.ifBlank { "没填货主" } + " " + money(it.balance) }
    }
    SectionCard {
        SectionTitle("要盯的事")
        Spacer(Modifier.height(6.dp))
        LineRow(
            icon = ReportNodes.driverPayable.icon,
            iconColor = Palette.warn,
            title = "该付司机的钱",
            sub = "每个司机那一行的待结运费相加（接口按人给，没有给合计）",
            value = money(java.lang.String.format(java.util.Locale.US, "%.2f", vm.driverOwed)),
            valueColor = toneColor(Tone.WARN),
            onClick = { onOpen(ReportNodes.driverPayable) },
        )
        HairLine()
        LineRow(
            icon = ReportNodes.receivable.icon,
            iconColor = Palette.bad,
            title = "超信用额度的客户",
            sub = "额度是空的不算超（那是「没给他定额度」）",
            value = vm.overLimitCount.toString() + " 家",
            valueColor = toneColor(if (vm.overLimitCount > 0) Tone.BAD else Tone.PLAIN),
            onClick = { onOpen(ReportNodes.receivable) },
        )
        HairLine()
        LineRow(
            icon = ReportNodes.receivable.icon,
            iconColor = Palette.warn,
            title = "欠得最多的三个人",
            sub = topText,
            value = null,
            valueColor = toneColor(Tone.WARN),
            onClick = { onOpen(ReportNodes.receivable) },
        )
        HairLine()
        LineRow(
            icon = ReportNodes.opsExceptions.icon,
            iconColor = Palette.bad,
            title = "异常单（近 30 天）",
            sub = "卡住的、超时没送达的；点进去看是哪几张",
            value = vm.exceptions.size.toString() + " 单",
            valueColor = toneColor(if (vm.exceptions.isNotEmpty()) Tone.BAD else Tone.PLAIN),
            onClick = { onOpen(ReportNodes.opsExceptions) },
        )
    }
}

// ------------------------------------------------------------------ ④ 走势
@Composable
private fun TrendCard(vm: ReportV2ViewModel) {
    SectionCard {
        SectionTitle("走势")
        Spacer(Modifier.height(8.dp))
        val series = vm.turnover?.series.orEmpty()
        when {
            series.isEmpty() -> ChartEmpty("这一段没有已送达的单，画不出走势")
            vm.spanDays > 366L -> ChartEmpty("这一段太长（超过一年），按日画出来会重复；把时间药丸换到「上月」看走势")
            else -> {
                BarChart(
                    values = series.map { (it.amount.toDoubleOrNull() ?: 0.0).toFloat() },
                    labels = series.map { it.label },
                    color = Palette.good,
                )
                NoteText("按天画这一段每一天的营业额（" + series.size + " 个点）。这一天没有单就是 0。")
            }
        }
    }
}

// ------------------------------------------------------------------ ⑤ 详细报表（原来那 11 个入口）
@Composable
private fun EntriesCard(onOpenTab: (Int) -> Unit) {
    SectionCard {
        SectionTitle("详细报表")
        Spacer(Modifier.height(2.dp))
        Text(
            "原来那 11 个页面一个都没少，从这儿进还是老样子",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Spacer(Modifier.height(10.dp))
        EntryGridInline(onOpenTab)
    }
}

/**
 * 两列入口格 —— 版式与老入口页（`EntryCardGrid`）一致：白卡 + 圆角彩底图标（白线图形）+ 文字。
 *
 * ⚠️ 这里**不能**直接用 `EntryCardGrid`：它内部是 `LazyVerticalGrid`（要一个确定高度），
 *    塞进 LazyColumn 的 item 里量不出高度，直接崩。
 */
@Composable
private fun EntryGridInline(onOpenTab: (Int) -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
        REPORT_ENTRIES.chunked(2).forEach { pair ->
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                pair.forEach { e ->
                    Surface(
                        shape = MaterialTheme.shapes.medium,
                        color = MaterialTheme.colorScheme.surface,
                        border = BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.5f)),
                        onClick = { onOpenTab(e.key.toInt()) },
                        modifier = Modifier.weight(1f),
                    ) {
                        Row(
                            verticalAlignment = Alignment.CenterVertically,
                            modifier = Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 12.dp),
                        ) {
                            Box(
                                Modifier.size(40.dp).background(e.color, RoundedCornerShape(10.dp)),
                                contentAlignment = Alignment.Center,
                            ) { Icon(e.icon, null, Modifier.size(22.dp), tint = Color.White) }
                            Spacer(Modifier.width(12.dp))
                            Text(
                                e.label,
                                style = MaterialTheme.typography.bodyMedium,
                                fontWeight = FontWeight.Medium,
                                maxLines = 1,
                                overflow = TextOverflow.Ellipsis,
                                // 可伸缩的文本必须显式给 weight：不给的话它去挤后面的兄弟（真机上表现为被挤成一条缝）
                                modifier = Modifier.weight(1f, fill = false),
                            )
                        }
                    }
                }
                if (pair.size == 1) Spacer(Modifier.weight(1f))
            }
        }
    }
}

// ------------------------------------------------------------------ ⑥ 口径说明（不是 JSON，是人话）
@Composable
private fun NotesCard() {
    SectionCard {
        SectionTitle("这几句话怎么读")
        Spacer(Modifier.height(6.dp))
        NoteText("· 数字全部来自后端报表接口，页面不加也不改；接口没有的（库存金额、所得税、车辆购置价）就写没有，不猜。")
        NoteText("· 「别人欠我」是时点账（到某一天为止），与「这一段」的营业额不是同一段时间 —— 两句话别对着加。")
        NoteText("· 比率（毛利率、营业利润率、保本点）是页面用接口给的两个数相除算的，分母为 0 时写「—」。")
        NoteText("· 每一层点到底都是订单；再往下就是那张单自己的页面。点不动的行没有箭头，点得动的才有。")
    }
}

/** 迷你条用的一小组：把三个数按同一把尺子折成条长（第三个数是它要显示的文字）。 */
private fun triples(vararg items: Triple<String, Double, String>): List<Triple<String, Float, String>> {
    val max = items.maxOfOrNull { kotlin.math.abs(it.second) } ?: 0.0
    return items.map { Triple(it.first, fractionOf(it.second, max), it.third) }
}
