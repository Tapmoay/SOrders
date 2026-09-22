package com.tapmoay.sorders.ui.dispatcher

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.launch
import com.tapmoay.sorders.ai.AiOrderRef
import com.tapmoay.sorders.data.remote.dto.ProductReportDto
import com.tapmoay.sorders.data.remote.dto.ProductReportItemDto
import com.tapmoay.sorders.data.remote.dto.TurnoverReportDto
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.data.remote.dto.ExceptionOrderDto
import com.tapmoay.sorders.data.remote.dto.OperationLogDto
import com.tapmoay.sorders.ui.common.*
import com.tapmoay.sorders.util.formatMoney
import com.tapmoay.sorders.util.saveExportFile
import java.time.LocalDate
import com.tapmoay.sorders.ui.common.Hint

/** 报表页（从入口页进入）：顶部时间导航 + 主题内容 + 导出 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ReportCenterScreen(container: AppContainer, onBack: () -> Unit, initialTab: Int = 0) {
    val vm: ReportCenterViewModel = appViewModel { ReportCenterViewModel(container, initialTab) }
    val snackbar = remember { SnackbarHostState() }
    val context = LocalContext.current
    val scope = androidx.compose.runtime.rememberCoroutineScope()
    OneShotSnackbar(snackbar, vm.actionResult, onConsumed = { vm.actionResult = null })
    OneShotSnackbar(snackbar, vm.error, onConsumed = { vm.error = null })

    val title = when (vm.tab) { 0 -> "营业纵览"; 1 -> "商品经营"; 2 -> "司机绩效"; 3 -> "客户经营"; 4 -> "资金收支"; else -> "异常与审计" }
    // 时间药丸那两个弹层的开关：**只记这一个**（自定义区间那个开关由 `DateFilterDialogs` 自己持有）
    var showPresets by remember { mutableStateOf(false) }

    Scaffold(
        snackbarHost = { SnackbarHost(snackbar) },
        topBar = {
            AppTopBar(
                title = title,
                onBack = onBack,
                actions = {
                    // 时间：**顶栏右上角一颗药丸**（与账本/订单/司机账本同一套）。
                    // ⚠️ 2026-09-22 换掉了页内那条 `ReportTimeNav`：它顶上"完整时段"那一块是个
                    //    **可点的 Surface**（实测 761×126 px，正压在顶栏下面），点它就弹系统日历 ——
                    //    用户报的「点击商品经营的时候有时候会弹出一个日历」就是它。
                    //    现在页面里**没有任何时间控件**：只有这颗药丸 + 我们的档位清单/区间弹层。
                    //    窗口没定下来之前**连药丸都不画**（先画一版"今天"再跳 = 用户点名的「闪两下」）。
                    if (vm.tab != 5 && vm.windowSettled) {
                        DatePresetPill(label = vm.periodLabel, onClick = { showPresets = true })
                    }
                    TextButton(onClick = { vm.load() }) {
                        Icon(Icons.Default.Refresh, null, Modifier.size(18.dp))
                        Spacer(Modifier.width(2.dp))
                        Text("刷新")
                    }
                    TextButton(
                        onClick = {
                            vm.exportCurrent { bytes ->
                                if (bytes != null) {
                                    val (f, t) = vm.dateRange
                                    val fn = title + "-" + f + "_" + t + ".xlsx"
                                    val path = saveExportFile(context, bytes, fn)
                                    scope.launch { snackbar.showSnackbar(if (path != null) "已导出：" + path else "导出失败：无法保存文件") }
                                }
                            }
                        },
                        enabled = !vm.exporting,
                    ) {
                        Icon(Icons.Default.FileDownload, null, Modifier.size(18.dp))
                        Spacer(Modifier.width(2.dp))
                        Text(if (vm.exporting) "导出中" else "导出")
                    }
                },
            )
        },
    ) { pad ->
        Column(Modifier.fillMaxSize().padding(pad)) {
            if (vm.tab == 5) {
                // 这一页**没有时间控件**（固定近 30 天）——说明必须写这一页自己的事。
                // 原来这里印的是「资金流水（按日/周/月切换上方时间）」：那是**资金收支**那一页的说法，
                // 印在「异常与审计」上既不对（这一页不是资金流水）、也把人往一个不存在的地方指。
                Text(
                    "这个页面固定看近 30 天：上面是待处理异常，下面是最近的操作日志",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp),
                )
                ExceptionTab(vm)
            } else if (!vm.windowSettled) {
                LoadingBox(Modifier.weight(1f))
            } else {
                when (vm.tab) {
                    0 -> TurnoverTab(vm)
                    1 -> ProductTab(vm)
                    2 -> DriverTab(vm)
                    3 -> CustomerTab(vm)
                    else -> FinanceTab(vm)
                }
            }
        }
    }

    // 时间那一颗药丸的弹层：档位清单 + 自定义区间（**与账本/订单/司机账本同一份实现**，
    // 五个页面共用 `DateFilterDialogs` —— 里面那条"先关清单、再开区间弹层"的顺序也共用）。
    // 窗口没定下来之前药丸都没画，这里自然也不会开。
    DateFilterDialogs(
        showPresets = showPresets,
        onDismissPresets = { showPresets = false },
        preset = vm.preset,
        customFrom = vm.customFrom,
        customTo = vm.customTo,
        onPickPreset = { vm.applyPreset(it) },
        onApplyCustom = { f, t -> vm.applyCustomRange(f, t) },
    )

    vm.resolveTarget?.let { t ->
        AlertDialog(
            onDismissRequest = { vm.resolveTarget = null },
            title = { Text("解决异常") },
            text = {
                Column {
                    Text("#" + t.orderNo + " · " + t.exceptionReason, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    Spacer(Modifier.height(8.dp))
                    OutlinedTextField(
                        value = vm.resolveNote,
                        onValueChange = { vm.resolveNote = it },
                        label = { Text("解决说明（如：已电话联系司机重新派单）") },
                        minLines = 2,
                        modifier = Modifier.fillMaxWidth(),
                    )
                }
            },
            confirmButton = { TextButton(onClick = { vm.confirmResolve() }, enabled = !vm.resolving) { Text("标记解决") } },
            dismissButton = { TextButton(onClick = { vm.resolveTarget = null }) { Text("取消") } },
        )
    }
}

@Composable
private fun GroupHeader(title: String) {
    Surface(color = Color(0xFFF3F0FF), shape = MaterialTheme.shapes.small, modifier = Modifier.fillMaxWidth()) {
        Row(Modifier.padding(horizontal = 12.dp, vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
            Box(
                Modifier.width(4.dp).height(14.dp)
                    .background(Color(0xFF6950F5), MaterialTheme.shapes.extraSmall)
            )
            Spacer(Modifier.width(8.dp))
            Text(title, style = MaterialTheme.typography.labelLarge, fontWeight = FontWeight.Bold, color = Color(0xFF495057))
        }
    }
}

@Composable
private fun AccentBar(color: Color) {
    Box(Modifier.width(4.dp).height(16.dp).background(color, MaterialTheme.shapes.extraSmall))
}

@Composable
private fun StatBig(label: String, value: String, color: Color, extra: Modifier = Modifier) {
    SectionCard(modifier = extra) {
        Text(label, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Spacer(Modifier.height(4.dp))
        Text(value, style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold, color = color)
    }
}

@Composable
private fun StatRow(label: String, value: String, color: Color = MaterialTheme.colorScheme.onSurface) {
    Row(Modifier.fillMaxWidth().padding(vertical = 6.dp), verticalAlignment = Alignment.CenterVertically) {
        Text(label, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.weight(1f))
        Text(value, style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Bold, color = color, textAlign = TextAlign.End)
    }
}

private fun money(s: String?): String = "¥" + formatMoney(s ?: "0")

/**
 * 商品毛利 = **有成本快照的那批行的收入** − 成本（2026-09-19 审计 R13-R1）。
 *
 * ⚠️ 这里原来是 `totalAmount − costTotal`（全部行的金额 − 只有成本行的成本），
 * 和第三轮修掉的后端口径**不是同一个数**：没成本快照的行会以"0 成本、100% 毛利"全额进账。
 * 实测同一个月：界面按旧公式算出 **72,177.75**，而正确值（导出与后端接口）是 **10,789.00**——
 * 差 6.7 倍。所以这份公式必须和后端 `cost_covered_amount - cost_total` 一模一样。
 */
internal fun grossProfit(data: TurnoverReportDto): Double =
    (data.costCoveredAmount?.toDoubleOrNull() ?: 0.0) - (data.costTotal?.toDoubleOrNull() ?: 0.0)

/**
 * 商品经营页的毛利 = **有成本快照那批商品的金额** − 成本合计。
 *
 * ⚠️ 和营业纵览是同一个道理（R13-R1）：原来这里也用 `totalAmount − costTotal`，
 * 把"没有成本快照的商品"当成 0 成本全额算进毛利。
 *
 * ⚠️ 2026-09-19 审计第十七轮再修一次：**收入的来源必须与后端同一处**。
 *    上一版是客户端自己 `items.filter { cost > 0 }.sumOf { amount }` —— 它和后端
 *    **导出**那一行（当时也是自己 sum 一遍）恰好一致，于是两处一起错：
 *    本机实测商品页/导出 11,071.00，而营业纵览（正确口径）10,789.00。
 *    现在直接用后端给的 `costCoveredAmount`（只有一处算它），客户端不再自己筛。
 *    老后端（没有这个字段）才回落到本地筛选——那是过渡，不是长期口径。
 */
internal fun productGrossProfit(data: ProductReportDto): Double {
    val fromServer = data.costCoveredAmount?.toDoubleOrNull()
    val income = fromServer ?: data.items
        .filter { (it.cost.toDoubleOrNull() ?: 0.0) > 0.0 }
        .sumOf { it.amount.toDoubleOrNull() ?: 0.0 }
    val cost = data.costTotal.toDoubleOrNull() ?: 0.0
    return income - cost
}

/**
 * 单个商品的毛利：**参与毛利的金额 − 该商品成本**（没有成本快照的商品返回 null = 显示"—"）。
 *
 * ⛔ 原来这一列用的是 `amount − cost`（全额收入减成本）——那是被废止的老公式：
 *    本机实测逐行毛利列合计 72,177.75，正是营业纵览修复前那个错数；唯一混合组
 *    ttt 印 327.50（正确 45.50，差 7.2 倍）。
 */
internal fun productItemProfit(it: ProductReportItemDto): Double? {
    val covered = it.coveredAmount?.toDoubleOrNull()
    if (covered != null) {
        return if ((it.coveredLines ?: 0) > 0) covered - (it.cost.toDoubleOrNull() ?: 0.0) else null
    }
    // 老后端没有 coveredAmount：按老口径判断"这一行参不参与毛利"，但收入侧仍然只算有成本的
    val cost = it.cost.toDoubleOrNull() ?: 0.0
    return if (cost > 0.0) (it.amount.toDoubleOrNull() ?: 0.0) - cost else null
}

/**
 * 毛利说明（口径 + 覆盖率）—— **两个页面共用这一份文字**。
 *
 * ⚠️ 成本口径 2026-09-19 换过一次（用户要求：「这么算的话，毛利率会偏低」）：
 *    旧口径 = 订单行的 `cost_price_snapshot`（下单那一刻的最新进货价）—— 进货价一涨，
 *    从旧库存出的货就被按新的高价算成本；新口径 = **入库流水的加权平均进货价**。
 *    所以这句话必须**同时报出两个数**：多少行真的用了入库均价、多少行退回了下单时的成本价。
 *    只报覆盖率的话，用户会以为整份毛利都已经是平均口径 —— 而那正是最容易骗人的写法。
 *
 * `avg + snap == 0` 有两种情况：老后端不下发这两个字段，或者这段窗口一行成本都没有。
 * 这时**不许编**一个区分说法，退回不带区分的写法（宁可少说，不能说错）。
 */
private fun coverageText(cov: Int, total: Int, avgLines: Int, snapLines: Int): String {
    val head = if (avgLines + snapLines > 0) {
        "毛利口径：成本按「入库流水的加权平均进货价」算（${avgLines} 行）；" +
            "另有 ${snapLines} 行该商品没记过进货价，按下单时的成本价算。"
    } else {
        "毛利口径：成本按商品的成本价算（还没有入库进货价可加权）。"
    }
    return head + "共 ${cov}/${total} 行算得出成本（收入与成本取同一批行）；" +
        "其余行没有成本，「不进毛利」（营业额里仍然有它们）。"
}

@Composable
private fun CoverNote(cov: Int, total: Int, avgLines: Int, snapLines: Int) {
    Text(
        coverageText(cov, total, avgLines, snapLines),
        style = MaterialTheme.typography.bodySmall,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
    )
}

// ===================== ① 营业纵览 =====================

@Composable
private fun TurnoverTab(vm: ReportCenterViewModel) {
    val data = vm.turnover
    if (vm.loading && data == null) {
        Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { CircularProgressIndicator() }
        return
    }
    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        if (data != null) {
            item {
                StatBig("实际营业金额", money(data.totalAmount), Color(0xFF1E6FFF))
            }
            item {
                SectionCard {
                    Text("营业指标", style = MaterialTheme.typography.titleMedium)
                    Spacer(Modifier.height(4.dp))
                    StatRow("订单数", data.totalOrders.toString() + " 单")
                    StatRow("单均价", money(data.avgOrder))
                    StatRow("司机运费支出", money(data.totalFreight), Color(0xFFFF9500))
                    // 口径必须写在标签里：这是**近 30 天待处理**的异常数（随本页一起取，见 ViewModel），
                    // 而上面几行是本期（当天/周/月）的营业额口径 —— 两个窗口不同，不说清就会被当成一个。
                    StatRow("待处理异常（近 30 天）", vm.pendingExceptionCount.toString() + " 单", Color(0xFFE53935))
                    if (data.cancelledOrders > 0) StatRow("已撤销订单数", data.cancelledOrders.toString() + " 单", Color(0xFF8A8A8E))
                }
            }
            item {
                SectionCard {
                    Text("盈利概览", style = MaterialTheme.typography.titleMedium)
                    Spacer(Modifier.height(4.dp))
                    val profit = grossProfit(data)
                    StatRow("商品毛利", "¥" + formatMoney(profit.toString()), Color(0xFF00B578))
                    CoverNote(data.costCoveredLines, data.totalLines, data.costAvgLines, data.costSnapshotLines)
                    StatRow("货损金额", money(data.damageAmount), Color(0xFFE53935))
                    if (data.damageQty > 0) StatRow("货损件数", data.damageQty.toString() + " 件", Color(0xFFE53935))
                }
            }
            item {
                SectionCard {
                    Text("资金状态", style = MaterialTheme.typography.titleMedium)
                    Spacer(Modifier.height(4.dp))
                    StatRow("已收", money(data.collected), Color(0xFF00B578))
                    StatRow("挂账未收", money(data.arrearsTotal), Color(0xFFFF6B2C))
                    val all = (data.collected.toDoubleOrNull() ?: 0.0) + (data.arrearsTotal.toDoubleOrNull() ?: 0.0)
                    val rate = if (all > 0) ((data.collected.toDoubleOrNull() ?: 0.0) / all * 100).toInt() else 0
                    StatRow("收款率", rate.toString() + " %", Color(0xFF1E6FFF))
                }
            }
            item {
                SectionCard {
                    Text("客户账汇总", style = MaterialTheme.typography.titleMedium)
                    Spacer(Modifier.height(6.dp))
                    Text("货主账", style = MaterialTheme.typography.labelLarge, color = Color(0xFF00A2C7))
                    if (vm.shipperAccounts.isEmpty()) Text("暂无流水", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    vm.shipperAccounts.take(3).forEach { a ->
                        StatRow(a.name, a.count.toString() + " 笔 · ¥" + formatMoney(a.total), Color(0xFF00A2C7))
                    }
                    Spacer(Modifier.height(6.dp))
                    Text("批发商账", style = MaterialTheme.typography.labelLarge, color = Color(0xFFF5A623))
                    if (vm.memberAccounts.isEmpty()) Text("暂无流水", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    vm.memberAccounts.take(3).forEach { a ->
                        StatRow(a.name, a.count.toString() + " 笔 · ¥" + formatMoney(a.total), Color(0xFFF5A623))
                    }
                    if (data.arrearsUnits.isNotEmpty()) {
                        Spacer(Modifier.height(6.dp))
                        Text("挂账未收 TOP5", style = MaterialTheme.typography.labelLarge, color = Color(0xFFFF6B2C))
                        data.arrearsUnits.forEach { u ->
                            StatRow(u.name, money(u.amount), Color(0xFFFF6B2C))
                        }
                    }
                }
            }
            item {
                SectionCard {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text("统计图", style = MaterialTheme.typography.titleMedium, modifier = Modifier.weight(1f))
                        TextButton(onClick = { vm.chartType = if (vm.chartType == "line") "bar" else "line" }) {
                            Text(if (vm.chartType == "line") "条形图" else "折线图", fontSize = 12.sp)
                        }
                    }
                    Spacer(Modifier.height(6.dp))
                    val vals = data.series.map { it.amount.toDoubleOrNull()?.toFloat() ?: 0f }
                    val labels = data.series.map { it.label }
                    when {
                        vals.any { it > 0f } && vm.chartType == "line" -> LineChart(vals, labels, Color(0xFF1E6FFF))
                        vals.any { it > 0f } -> BarChart(vals, labels, Color(0xFF00B578))
                        else -> ChartEmpty("该时段暂无送达数据")
                    }
                }
            }
            item {
                GroupHeader("每日明细")
                Spacer(Modifier.height(8.dp))
            }
            item {
                SectionCard {
                    data.series.forEach { s ->
                        Row(Modifier.padding(vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                            AccentBar(Color(0xFF6950F5))
                            Spacer(Modifier.width(10.dp))
                            Text(s.label, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.weight(1f), color = MaterialTheme.colorScheme.onSurface)
                            Text(s.orders.toString() + " 单", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, textAlign = TextAlign.End, modifier = Modifier.width(48.dp))
                            Spacer(Modifier.width(12.dp))
                            Text(money(s.amount), style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Bold, color = Color(0xFF1E6FFF), textAlign = TextAlign.End, modifier = Modifier.width(84.dp))
                        }
                        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
                    }
                }
            }
        }
    }
}

// ===================== ② 商品经营（信息分层：搜索+排序+TOP收起） =====================

@Composable
private fun ProductTab(vm: ReportCenterViewModel) {
    val data = vm.products
    if (vm.loading && data == null) {
        Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { CircularProgressIndicator() }
        return
    }
    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        if (data != null) {
            item {
                Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    StatBig("商品总金额", money(data.totalAmount), Color(0xFF8455E6), Modifier.weight(1f))
                    StatBig("出库总件数", data.totalQty.toString() + " 件", Color(0xFF00A8A8), Modifier.weight(1f))
                }
            }
            item {
                SectionCard {
                    Text("盈利与损耗", style = MaterialTheme.typography.titleMedium)
                    Spacer(Modifier.height(4.dp))
                    val profit = productGrossProfit(data)
                    StatRow("商品毛利", "¥" + formatMoney(profit.toString()), Color(0xFF00B578))
                    CoverNote(data.costCoveredLines, data.totalLines, data.costAvgLines, data.costSnapshotLines)
                    StatRow("货损金额", money(data.damageAmount), Color(0xFFE53935))
                }
            }
            item {
                SectionCard {
                    Text("销量 TOP（条形图）", style = MaterialTheme.typography.titleMedium)
                    Spacer(Modifier.height(8.dp))
                    val top = data.items.take(8)
                    if (top.isEmpty()) ChartEmpty("暂无数据")
                    else BarChart(top.map { it.amount.toDoubleOrNull()?.toFloat() ?: 0f }, top.map { it.productName }, Color(0xFF8455E6))
                }
            }
            item {
                GroupHeader("商品明细（" + data.items.size + " 种）")
                Spacer(Modifier.height(8.dp))
            }
            item {
                SectionCard {
                    OutlinedTextField(
                        value = vm.productSearch,
                        onValueChange = { vm.productSearch = it },
                        placeholder = { Text("搜索商品名称", style = MaterialTheme.typography.bodySmall) },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth(),
                        textStyle = MaterialTheme.typography.bodyMedium,
                    )
                    Spacer(Modifier.height(6.dp))
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        listOf("amount" to "按金额", "qty" to "按件数", "profit" to "按毛利", "damage" to "按货损").forEach { (k, label) ->
                            val sel = vm.productSort == k
                            Surface(
                                color = if (sel) MaterialTheme.colorScheme.primary.copy(alpha = 0.14f) else MaterialTheme.colorScheme.surfaceVariant,
                                shape = MaterialTheme.shapes.small,
                                modifier = Modifier.clickable { vm.productSort = k },
                            ) {
                                Text(
                                    label,
                                    style = MaterialTheme.typography.labelMedium,
                                    fontWeight = if (sel) FontWeight.Bold else FontWeight.Normal,
                                    color = if (sel) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurfaceVariant,
                                    modifier = Modifier.padding(horizontal = 10.dp, vertical = 5.dp),
                                )
                            }
                        }
                    }
                }
            }
            val filtered = vm.filteredProducts
            val shown = if (vm.productShowAll) filtered else filtered.take(15)
            items(shown, key = { vm.productSort + "|" + it.productName }) { p ->
                SectionCard {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        AccentBar(Color(0xFF8455E6))
                        Spacer(Modifier.width(10.dp))
                        Column(Modifier.weight(1f)) {
                            Text(p.productName, style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Bold)
                            Text(p.qty.toString() + " 件 · " + p.orderCount + " 单" + (if (p.damageQty > 0) " · 货损 " + p.damageQty + " 件" else ""), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                            // ⛔ 逐行毛利必须走 `productItemProfit`（参与毛利的金额 − 成本）：
                            //    这里原来是 `amount − cost`，把没有成本快照的商品按 100% 毛利印出来
                            //    （本机实测逐行合计 72,177.75，正是营业纵览修复前那个错数）。
                            val profit = productItemProfit(p)
                            Text(
                                (if (profit == null) "毛利 —（这一行没有成本快照，不进毛利）"
                                 else "毛利 ¥" + formatMoney(profit.toString())) +
                                    (if (p.damageQty > 0) " · 货损 ¥" + formatMoney(p.damageAmount) else ""),
                                style = MaterialTheme.typography.bodySmall,
                                color = if (profit == null) MaterialTheme.colorScheme.onSurfaceVariant else Color(0xFF00B578),
                            )
                        }
                        Text(money(p.amount), style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold, color = Color(0xFFFF9500))
                    }
                }
            }
            if (filtered.size > 15 && !vm.productShowAll) {
                item {
                    SectionCard {
                        TextButton(onClick = { vm.productShowAll = true }, modifier = Modifier.fillMaxWidth()) {
                            Text("查看全部 " + filtered.size + " 个商品（当前显示 TOP15）", fontSize = 13.sp)
                        }
                    }
                }
            }
            if (filtered.isEmpty()) item { ChartEmpty("无匹配商品") }
        }
    }
}

// ===================== ③ 司机绩效 =====================

@Composable
private fun DriverTab(vm: ReportCenterViewModel) {
    val data = vm.drivers
    if (vm.loading && data == null) {
        Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { CircularProgressIndicator() }
        return
    }
    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        if (data == null || data.drivers.isEmpty()) {
            item { ChartEmpty("该时段暂无司机绩效数据") }
        } else {
            item {
                val totalOrders = data.drivers.sumOf { it.completedCount }
                val ot = data.drivers.mapNotNull { it.onTimeRate }
                val avgOt = if (ot.isNotEmpty()) (ot.sum() / ot.size * 100).toInt() else 0
                val pr = data.drivers.mapNotNull { it.photoUploadRate }
                val avgPr = if (pr.isNotEmpty()) (pr.sum() / pr.size * 100).toInt() else 0
                val owed = data.drivers.mapNotNull { it.freightOwed?.toDoubleOrNull() }.sum()
                SectionCard {
                    Text("绩效总览", style = MaterialTheme.typography.titleMedium)
                    Spacer(Modifier.height(4.dp))
                    StatRow("完成单量", totalOrders.toString() + " 单")
                    StatRow("平均准时率", avgOt.toString() + " %", Color(0xFF00B578))
                    StatRow("平均拍照率", avgPr.toString() + " %", Color(0xFF00A2C7))
                    StatRow("计件司机待结运费", "¥" + formatMoney(owed.toString()), Color(0xFFFF6B2C))
                    Text("待结运费 = 计件（PIECE）司机应结运费 − 已结算金额；工资制司机不计。", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
            item {
                SectionCard {
                    Text("完成单量 TOP（条形图）", style = MaterialTheme.typography.titleMedium)
                    Spacer(Modifier.height(8.dp))
                    BarChart(data.drivers.take(8).map { it.completedCount.toFloat() }, data.drivers.take(8).map { it.driverName }, Color(0xFF00B578))
                }
            }
            item {
                GroupHeader("司机绩效（" + data.drivers.size + " 人）")
                Spacer(Modifier.height(8.dp))
            }
            items(data.drivers, key = { it.driverId }) { d ->
                SectionCard {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        AccentBar(Color(0xFF00B578))
                        Spacer(Modifier.width(10.dp))
                        Column(Modifier.weight(1f)) {
                            Text(d.driverName.ifBlank { "司机 " + d.driverId }, style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Bold)
                            Text("准时率 " + ((d.onTimeRate ?: 0.0) * 100).toInt() + "% · 拍照率 " + (d.photoUploadRate * 100).toInt() + "%" + (d.avgDeliverySeconds?.let { s -> " · 平均 " + ((s / 60).toInt()).toString() + " 分钟" } ?: ""), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                            val modeText = when ((d.billingMode ?: "").uppercase()) {
                                "SALARY" -> "工资制"
                                "PIECE" -> (d.freightOwed?.let { "待结运费 ¥" + formatMoney(it) } ?: "计件")
                                else -> ""
                            }
                            if (modeText.isNotBlank()) Text(modeText, style = MaterialTheme.typography.bodySmall, color = if ((d.billingMode ?: "").uppercase() == "SALARY") Color(0xFF8A8A8E) else Color(0xFFFF6B2C))
                        }
                        Text(d.completedCount.toString() + " 单", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold, color = Color(0xFF00B578))
                    }
                }
            }
        }
    }
}

// ===================== ④ 客户经营 =====================

@Composable
private fun CustomerTab(vm: ReportCenterViewModel) {
    if (vm.loading && vm.shipperAccounts.isEmpty() && vm.memberAccounts.isEmpty()) {
        Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { CircularProgressIndicator() }
        return
    }
    val shippers = vm.shipperAccounts
    val members = vm.memberAccounts
    // ⛔ **批发商不能算两遍**（2026-09-19 审计）：后端的 `kind=shipper` 与 `kind=member` 两个列表
    //    都按"账本流水归属"分组，而批发商（is_member）**同时出现在两个列表里** —— 直接相加会让
    //    订货总额虚高（本机实测 ¥185,121 vs 真值 ¥128,063，虚高 44.6%）、客户数也从 38 变 41。
    //    同一页签的 Excel 导出反而是对的（后端分三桶），于是"页面一个数、导出一个数"。
    //    这里按用户 id 去重：批发商优先算在 members 桶里。
    val memberIds = members.mapNotNull { it.id }.toSet()
    val plainShippers = shippers.filter { it.id == null || it.id !in memberIds }
    val all = plainShippers + members
    val totalCount = all.sumOf { it.count }
    val totalAmount = all.sumOf { it.total.toDoubleOrNull() ?: 0.0 }
    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        item {
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                StatBig("订货总额", money(totalAmount.toString()), Color(0xFF00A2C7), Modifier.weight(1f))
                StatBig("客户数", all.size.toString() + " 家", Color(0xFF00B578), Modifier.weight(1f))
            }
        }
        item {
            SectionCard {
                Text("经营概览", style = MaterialTheme.typography.titleMedium)
                Spacer(Modifier.height(4.dp))
                StatRow("订货笔数", totalCount.toString() + " 笔")
                StatRow("客单价", if (all.isNotEmpty()) money((totalAmount / all.size).toString()) else "¥0.00", Color(0xFF1E6FFF))
                StatRow("临时货主", shippers.count { it.tempName != null }.toString() + " 家", Color(0xFF8A8A8E))
            }
        }
        item {
            SectionCard {
                Text("客户账分组", style = MaterialTheme.typography.titleMedium)
                Spacer(Modifier.height(6.dp))
                Text("货主账", style = MaterialTheme.typography.labelLarge, color = Color(0xFF00A2C7))
                if (shippers.isEmpty()) Text("暂无流水", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                shippers.take(5).forEach { a ->
                    StatRow(a.name, a.count.toString() + " 笔 · ¥" + formatMoney(a.total), Color(0xFF00A2C7))
                }
                Spacer(Modifier.height(6.dp))
                Text("批发商账", style = MaterialTheme.typography.labelLarge, color = Color(0xFFF5A623))
                if (members.isEmpty()) Text("暂无流水", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                members.take(5).forEach { a ->
                    StatRow(a.name, a.count.toString() + " 笔 · ¥" + formatMoney(a.total), Color(0xFFF5A623))
                }
            }
        }
        if (vm.customerArrears.isNotEmpty()) {
            item {
                SectionCard {
                    Text("挂账未收", style = MaterialTheme.typography.titleMedium, color = Color(0xFFFF6B2C))
                    Spacer(Modifier.height(6.dp))
                    vm.customerArrears.take(8).forEach { u ->
                        StatRow(u.name, money(u.amount), Color(0xFFFF6B2C))
                    }
                }
            }
        }
        item {
            GroupHeader("客户明细")
            Spacer(Modifier.height(8.dp))
        }
        if (shippers.isNotEmpty()) {
            item {
                Text("货主 · 临时货主", style = MaterialTheme.typography.labelLarge, color = Color(0xFF00A2C7))
                Spacer(Modifier.height(6.dp))
            }
            items(shippers, key = { "s" + (it.id ?: it.tempName) }) { a ->
                SectionCard {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        AccentBar(Color(0xFF00A2C7))
                        Spacer(Modifier.width(10.dp))
                        Column(Modifier.weight(1f)) {
                            Text(a.name, style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Bold)
                            if (a.tempName != null) Text("临时货主", style = MaterialTheme.typography.bodySmall, color = Color(0xFF8A8A8E))
                        }
                        Text(a.count.toString() + " 笔 · ¥" + formatMoney(a.total), style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Bold, color = Color(0xFF00A2C7))
                    }
                }
            }
        }
        if (members.isNotEmpty()) {
            item {
                Text("批发商", style = MaterialTheme.typography.labelLarge, color = Color(0xFFF5A623))
                Spacer(Modifier.height(6.dp))
            }
            items(members, key = { "m" + it.id }) { a ->
                SectionCard {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        AccentBar(Color(0xFFF5A623))
                        Spacer(Modifier.width(10.dp))
                        Column(Modifier.weight(1f)) {
                            Text(a.name, style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Bold)
                        }
                        Text(a.count.toString() + " 笔 · ¥" + formatMoney(a.total), style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Bold, color = Color(0xFFF5A623))
                    }
                }
            }
        }
    }
}

// ===================== ⑤ 资金收支 =====================

@Composable
private fun FinanceTab(vm: ReportCenterViewModel) {
    if (vm.loading && vm.cashFlows.isEmpty()) {
        Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { CircularProgressIndicator() }
        return
    }
    val flows = vm.cashFlows
    // ⚠️ 方向比大小写（后端存的是小写 in/out），业务类型/开销分类的取值见 ReportFinance：
    //    这三处以前各错一种，而且是同一类"不会报错"的错——见 ReportFinance 的类注释。
    // ⚠️ 金额取**服务端汇总**（见 ViewModel 里的注释）：客户端对"这一页流水"求和会少算。
    //    汇总拿不到时（老后端/请求失败）才退回对当前页求和，并在标题上写明"仅本页"。
    val summary = vm.cashFlowSummary
    val income = summary?.income?.toDoubleOrNull()
        ?: flows.filter { ReportFinance.isIncome(it.direction) }.sumOf { it.amount.toDoubleOrNull() ?: 0.0 }
    val expense = summary?.expense?.toDoubleOrNull()
        ?: flows.filter { !ReportFinance.isIncome(it.direction) }.sumOf { it.amount.toDoubleOrNull() ?: 0.0 }
    val expByCat = vm.expenses.groupBy { ReportFinance.expenseCategoryLabel(it.category) }.mapValues { it.value.sumOf { e -> e.amount.toDoubleOrNull() ?: 0.0 } }
    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        item {
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                StatBig("资金流入", money(income.toString()), Color(0xFF00B578), Modifier.weight(1f))
                StatBig("资金流出", money(expense.toString()), Color(0xFFFF6B2C), Modifier.weight(1f))
            }
        }
        item {
            SectionCard {
                Text("净额", style = MaterialTheme.typography.titleMedium)
                Spacer(Modifier.height(4.dp))
                StatRow("净流入", money((income - expense).toString()), if (income - expense >= 0) Color(0xFF00B578) else Color(0xFFE53935))
            }
        }
        if (expByCat.isNotEmpty()) {
            item {
                SectionCard {
                    Text("开销分类汇总", style = MaterialTheme.typography.titleMedium)
                    Spacer(Modifier.height(4.dp))
                    expByCat.entries.sortedByDescending { it.value }.forEach { (cat, amt) ->
                        StatRow(cat, money(amt.toString()), Color(0xFFFF9500))
                    }
                }
            }
        }
        item {
            GroupHeader(
                "资金流水（本窗口共 " + (summary?.count ?: flows.size) + " 条" +
                    (if (flows.size > 100) "，下面只列最近 100 条" else "") + "）",
            )
            Spacer(Modifier.height(8.dp))
            // 服务端只回了一页时**说出来**（判据是响应头 `X-Truncated`）：不说的话用户会把
            // "看得见的这几行"当成整个窗口的明细。出路是上方那个时间导航（它切的是服务端窗口），
            // 所以这句话直接点名它 —— 不做"加载更多"（这些端点的 limit 是服务端上限，不是页码）。
            if (vm.cashFlowsTruncated) {
                TruncationNote(vm.cashFlowsLimit, "这一窗口更早的请用上方时间导航切到更早的日期")
                Spacer(Modifier.height(4.dp))
            }
        }
        if (flows.isEmpty()) item { ChartEmpty("该时段暂无资金流水") }
        items(flows.take(100), key = { it.id.toString() }) { f ->
            val isIn = ReportFinance.isIncome(f.direction)
            SectionCard {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    AccentBar(if (isIn) Color(0xFF00B578) else Color(0xFFFF6B2C))
                    Spacer(Modifier.width(10.dp))
                    Column(Modifier.weight(1f)) {
                        Text(f.partyName?.takeIf { it.isNotBlank() } ?: (if (isIn) "收入" else "支出"), style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Bold)
                        Text(f.flowDate + " · " + ReportFinance.bizLabel(f.bizType), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                    Text(
                        (if (isIn) "+" else "-") + money(f.amount),
                        style = MaterialTheme.typography.titleMedium,
                        fontWeight = FontWeight.Bold,
                        color = if (isIn) Color(0xFF00B578) else Color(0xFFFF6B2C),
                    )
                }
            }
        }
    }
}

// 资金方向 / 业务类型 / 开销分类的映射统一在 ReportFinance（纯函数 + 单测）：
// 它们曾经各自"悄悄错一种"，而错法在界面上都看不出来。

// ===================== ⑥ 异常与审计 =====================

@Composable
private fun ExceptionTab(vm: ReportCenterViewModel) {
    if (vm.loading && vm.exceptions.isEmpty()) {
        Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { CircularProgressIndicator() }
        return
    }
    // 待解决按**危险层级分组、组内按拖得久的在前**（见 ReportPriority.kt 的口径说明）。
    // 用户原话：「上百条翻不到，就该按危险层级/紧急层级做分类和优先级排序」——
    // 分组标题就是"先看哪一组"，组内排序就是"组里先看哪一条"。
    //
    // ⚠️ 但真机上先看到的不是"排序不够好"，而是**列表里一半是要留档的东西**：
    //    后端这个列表是规则自动生成的，275 条里 110 条是「逾期送达」（已经送到客户手里了）、
    //    9 条是「已撤销」。所以先按"还要不要人做点什么"拆开，再谈组内排序。
    val pending = pendingExceptions(vm.exceptions)
    val past = pastExceptions(vm.exceptions)
    val resolved = vm.exceptions.filter { it.exceptionResolvedAt != null }
    var auditFilter by remember { mutableStateOf<AuditKind?>(null) }
    val audits = sortedAudits(vm.operationLogs.take(60), auditFilter)
    val counts = auditCounts(vm.operationLogs.take(60))
    // 两块各自都有几十上百条，**谁排在前面谁挡住另一块**：
    // v3.26 把审计挪到异常前面（当时异常几百条翻不到），结果审计 60 条之后，
    // 「要处理的」又被挡在下面。真正的解法不是再挪一次位置，而是**一次只显示一块**。
    var pane by remember { mutableStateOf(0) } // 0=要处理 1=审计 2=已过去
    // 段控件放在 LazyColumn **外面**：放里面就得靠负 padding 去抵消列表的左右留白，
    // 而 Compose 的 padding 不允许负数——真机上直接崩（logcat：
    // `IllegalArgumentException: Padding must be non-negative` @ ReportCenter 的这一行）。
    Column(Modifier.fillMaxSize()) {
        SegmentedStatusTabs(
            labels = listOf("要处理 " + pending.size, "审计 " + vm.operationLogs.take(60).size, "已过去 " + past.size),
            colors = listOf(Color(0xFFE53935), Color(0xFF6950F5), Color(0xFF8A8A8E)),
            selected = pane,
            onSelect = { pane = it },
        )
        LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        if (pane == 0) {
            item {
                Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    StatBig("要处理", pending.size.toString() + " 单", Color(0xFFE53935), Modifier.weight(1f))
                    StatBig("其中钱货风险", pending.count { exceptionRisk(it) == RiskLevel.MONEY }.toString() + " 单", Color(0xFFFF8A65), Modifier.weight(1f))
                }
            }
            item {
                val total = vm.exceptions.size
                val rate = if (total > 0) (resolved.size * 100 / total) else 0
                SectionCard {
                    Text("异常总账（近 30 天）", style = MaterialTheme.typography.titleMedium)
                    Spacer(Modifier.height(4.dp))
                    StatRow("总共 " + total.toString() + " 单", "要处理 " + pending.size + " + 已过去 " + past.size + " + 已解决 " + resolved.size)
                    StatRow("解决率", rate.toString() + " %", Color(0xFF00B578))
                    val oldest = pending.maxOfOrNull { stuckDays(it) } ?: 0
                    if (oldest >= 3) StatRow("最久已拖", oldest.toString() + " 天", Color(0xFFFF8A65))
                }
            }
            // 分组渲染：同一危险层级的连在一起，层级标题写清"为什么这组要先看"
            var lastLevel: RiskLevel? = null
            pending.forEach { e ->
                val lv = exceptionRisk(e)
                if (lv != lastLevel) {
                    lastLevel = lv
                    item(key = "lv" + lv.name) {
                        LevelHeader(lv, pending.count { exceptionRisk(it) == lv })
                    }
                }
                item(key = "p" + e.id) {
                    ExceptionCard(e, onResolve = { vm.openResolve(e) })
                }
            }
            if (pending.isEmpty()) {
                item { ChartEmpty("没有要处理的异常") }
            }
        }
        if (pane == 1) {
            item {
                GroupHeader("敏感操作审计（近 60 条）")
                Spacer(Modifier.height(8.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    AuditChip("全部", counts.values.sum(), auditFilter == null) { auditFilter = null }
                    AuditChip("改钱", counts[AuditKind.MONEY] ?: 0, auditFilter == AuditKind.MONEY) { auditFilter = AuditKind.MONEY }
                    AuditChip("删数据", counts[AuditKind.DELETE] ?: 0, auditFilter == AuditKind.DELETE) { auditFilter = AuditKind.DELETE }
                    AuditChip("账号权限", counts[AuditKind.AUTH] ?: 0, auditFilter == AuditKind.AUTH) { auditFilter = AuditKind.AUTH }
                    AuditChip("改状态", counts[AuditKind.STATE] ?: 0, auditFilter == AuditKind.STATE) { auditFilter = AuditKind.STATE }
                }
                Spacer(Modifier.height(4.dp))
                Hint(
                    "排序：改钱/删数据/账号权限 → 改状态 → 其它，同级按时间倒序",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                // 只回了 60 条时**必须说出来**：这个页签是"我那次改动到底有没有被记录"的
                // 唯一入口，不说的话用户会把"没看到"读成"没记录"。页签里没有时间筛选
                // （异常与审计固定近 30 天），能取更多的入口是右上角「导出」——所以指向它。
                if (vm.operationLogsTruncated) {
                    Spacer(Modifier.height(6.dp))
                    TruncationNote(
                        vm.operationLogsLimit,
                        "更早的没被列出来（不代表没记录），需要更多请点右上角「导出」",
                    )
                }
                Spacer(Modifier.height(8.dp))
            }
            items(audits, key = { "log" + it.id }) { log ->
                AuditLogCard(log)
            }
            if (audits.isEmpty()) {
                item { ChartEmpty(if (vm.operationLogs.isEmpty()) "暂无操作日志" else "这一类里没有操作记录") }
            }
        }
        // 「已过去」单独一屏：它数量最大、但**不用处理**，只是对账/复盘时来看。
        // 和待处理混在一起正是"274 单翻不到"的根子。
        if (pane == 2) {
            item {
                GroupHeader("已过去（不用处理，只是留档）· " + past.size + " 单")
                Spacer(Modifier.height(4.dp))
                Text(
                    "含已送达但迟到过的单（货已经到客户手里）和已撤销/撤回的单（终态）。" +
                        "它们进这一屏是为了对账时查得到，不需要谁去点「解决」。",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Spacer(Modifier.height(8.dp))
            }
            items(past, key = { "past" + it.id }) { e ->
                ExceptionCard(e, onResolve = null)
            }
            if (resolved.isNotEmpty()) {
                item {
                    GroupHeader("已解决（" + resolved.size + "）")
                    Spacer(Modifier.height(8.dp))
                }
                items(resolved, key = { "r" + it.id }) { e ->
                    ExceptionCard(e, onResolve = null)
                }
            }
            if (past.isEmpty() && resolved.isEmpty()) {
                item { ChartEmpty("没有已经过去的异常") }
            }
        }
        }
    }
}

@Composable
private fun AuditChip(label: String, count: Int, selected: Boolean, onClick: () -> Unit) {
    val bg = if (selected) Color(0xFF6950F5) else MaterialTheme.colorScheme.surfaceVariant
    val fg = if (selected) Color.White else MaterialTheme.colorScheme.onSurfaceVariant
    Surface(color = bg, shape = RoundedCornerShape(50), modifier = Modifier.clickable { onClick() }) {
        Text(
            if (count > 0) "$label $count" else label,
            style = MaterialTheme.typography.bodySmall,
            color = fg,
            modifier = Modifier.padding(horizontal = 12.dp, vertical = 6.dp),
        )
    }
}

/** 异常分组的组标题：一眼看出这组为什么排在前面。 */
@Composable
private fun LevelHeader(lv: RiskLevel, count: Int) {
    val color = when (lv) {
        RiskLevel.MONEY -> Color(0xFFE53935)
        RiskLevel.STUCK -> Color(0xFFFF8A65)
        RiskLevel.OTHER -> Color(0xFF8A8A8E)
        RiskLevel.PAST -> Color(0xFF8A8A8E)
        RiskLevel.DONE -> Color(0xFF00B578)
    }
    val why = when (lv) {
        RiskLevel.MONEY -> "已经在赔钱/可能丢货，先处理这些"
        RiskLevel.STUCK -> "单卡住了（超时未送/未派/地址联系不上），还没赔钱"
        RiskLevel.OTHER -> "其它异常"
        RiskLevel.PAST -> "不用处理"
        RiskLevel.DONE -> "已解决"
    }
    Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(top = 4.dp)) {
        Box(Modifier.size(8.dp).background(color, RoundedCornerShape(50)))
        Spacer(Modifier.width(8.dp))
        Text(lv.label + "（" + count + "）", style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Bold, color = color)
        Spacer(Modifier.width(8.dp))
        Text(why, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

@Composable
private fun AuditLogCard(log: OperationLogDto) {
    // 每条自己带级别：分组标题回答"先看哪一类"，这里回答"这一条算哪一档"。
    // 分类筛选会打乱原来的位置，所以判断不能只靠"它在第几组"。
    val kind = auditKind(log.action, log.changeContent)
    val lv = auditRisk(kind)
    SectionCard {
        Row(verticalAlignment = Alignment.CenterVertically) {
            AccentBar(levelColor(lv))
            Spacer(Modifier.width(10.dp))
            Column(Modifier.weight(1f)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(actionLabel(log.action), style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Bold)
                    Spacer(Modifier.width(6.dp))
                    KindBadge(kind.label, levelColor(lv))
                }
                log.changeContent?.takeIf { it.isNotBlank() }?.let {
                    // **改了什么**放第二行（用户最先要看的）：后端存的是 JSON，已翻成人话。
                    Text(auditChangeText(it), style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurface, maxLines = 3)
                }
                // **谁、什么时候**：审计的第一个问题就是"谁改的"，原来只印了时间。
                Text(
                    auditWhoWhen(log.operatorName, log.createdAt),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            // 涉及哪一单：写**单号**（不是内部编号 `#404`）
            log.orderNo?.takeIf { it.isNotBlank() }?.let {
                Text(it, style = MaterialTheme.typography.bodySmall, color = Color(0xFF6950F5))
            }
        }
    }
}

/**
 * 「谁 · 什么时候」——审计页第一眼要看的两个字段。
 *
 * 时间做**友好化**：今天 / 昨天 / 更早（更早才写「月-日」）。审计关心"什么时候发生的"，
 * 而 `2026-09-16 10:21:50` 这种全量时间戳在列表里既占地方又要用户自己换算。
 * 解析不出来就只写操作人——不编一个时间。
 */
internal fun auditWhoWhen(operator: String?, createdAt: String): String {
    val who = operator?.takeIf { it.isNotBlank() } ?: "操作人未知"
    val t = parseDateTime(createdAt) ?: return who
    val today = LocalDate.now()
    val d = t.toLocalDate()
    val day = when {
        d == today -> "今天"
        d == today.minusDays(1) -> "昨天"
        else -> "%02d-%02d".format(d.monthValue, d.dayOfMonth)
    }
    return "$who · $day %02d:%02d".format(t.hour, t.minute)
}

@Composable
private fun KindBadge(text: String, color: Color) {
    Surface(color = color.copy(alpha = 0.12f), shape = RoundedCornerShape(50)) {
        Text(
            text,
            style = MaterialTheme.typography.labelSmall,
            color = color,
            modifier = Modifier.padding(horizontal = 8.dp, vertical = 2.dp),
        )
    }
}

private fun levelColor(lv: RiskLevel): Color = when (lv) {
    RiskLevel.MONEY -> Color(0xFFE53935)
    RiskLevel.STUCK -> Color(0xFFFF8A65)
    RiskLevel.OTHER -> Color(0xFF8A8A8E)
    RiskLevel.PAST -> Color(0xFF8A8A8E)
    RiskLevel.DONE -> Color(0xFF00B578)
}

/**
 * 操作日志的 `action` → 中文。
 *
 * ⚠️ 这张表原来是**按猜的格式写的**（`order.split`、`price_rule` 这种小写点分形式），
 * 而后端存的是**枚举名**（`ORDER_SPLIT`、`PRICE_RULE_UPSERT`）——两边从来没对上过，
 * 于是审计页一直显示 `ORDER_DELETE` 这种原始码。这里按后端的真实取值重写，
 * 并补上本轮新增的调价留痕（`price_rules.py` 现在会把每次改价写进操作日志）。
 */
private fun actionLabel(action: String): String = when (action) {
    "ORDER_CREATE" -> "新建订单"
    "ORDER_UPDATE" -> "修改订单"
    "ORDER_DISPATCH" -> "派单"
    "ORDER_RECALL" -> "撤回派单"
    "ORDER_COMPLETE" -> "送达完成"
    "ORDER_CANCEL" -> "撤销订单"
    "ORDER_DELETE" -> "移入回收站"
    "ORDER_RESTORE" -> "从回收站恢复"
    "ORDER_EXCEPTION" -> "标记/解除异常"
    "ORDER_FREIGHT" -> "修改运费"
    "ORDER_SPLIT" -> "拆分子订单"
    "ORDER_RETURN" -> "订单退货"
    // 退货申请（2026-09-21）：**申请与执行是两个动作、两个人**，审计页上必须分得开 ——
    // 看到「订单退货」是"货真的退了"，看到「申请退货」只是"他提了一嘴"。
    "ORDER_RETURN_REQUEST" -> "申请退货"
    "ORDER_RETURN_REQUEST_REJECT" -> "驳回退货申请"
    "ORDER_RETURN_REQUEST_WITHDRAW" -> "撤回退货申请"
    // 派单员直接退了货 → 那张申请被自动关闭（2026-09-21 用户拍板的那条规则）。
    // 与「订单退货」分开：审计页上要能回答"这张申请为什么没被办理就结束了"。
    "ORDER_RETURN_REQUEST_CLOSE" -> "退货申请自动关闭"
    // 预订单 / 订单模板（2026-09-22）：预设单会变成真订单 ——「这条预设是谁建的/改的/删的」
    // 必须查得到，所以三个动作码各有各的中文名（⛔ 审计页上不许出现原始码）。
    "ORDER_TEMPLATE_UPSERT" -> "建/改预设单"
    "ORDER_TEMPLATE_DELETE" -> "删预设单"
    "ORDER_TEMPLATE_RESTORE" -> "恢复预设单"
    // 供应商 / 厂商 + 应付款（2026-09-22）：这一组同时决定"欠他多少"和"钱什么时候出去的"，
    // 所以九个动作码各有各的中文名（⛔ 审计页上不许出现原始码）。
    // 拆开而不是合成三个：审计页要能一眼分出「改了档案」/「改了欠款金额」/「把钱付出去了」。
    "SUPPLIER_UPSERT" -> "建/改供应商"
    "SUPPLIER_DELETE" -> "删供应商"
    "SUPPLIER_RESTORE" -> "恢复供应商"
    "SUPPLIER_PAYABLE_UPSERT" -> "建/改应付款"
    "SUPPLIER_PAYABLE_DELETE" -> "删应付款"
    "SUPPLIER_PAYABLE_RESTORE" -> "恢复应付款"
    "SUPPLIER_PAYMENT_CREATE" -> "付供应商款"
    "SUPPLIER_PAYMENT_CANCEL" -> "撤销付款"
    "SUPPLIER_PAYMENT_RESTORE" -> "恢复付款"
    "NOTIFICATION_MODERATE" -> "处理他人消息"
    "ORDER_LINE_ADD" -> "加一行商品"
    "ORDER_LINE_UPDATE" -> "改一行商品"
    "ORDER_LINE_DELETE" -> "删一行商品"
    "ORDER_PAY" -> "标记已收款"
    "ORDER_CHARGE" -> "转入挂账单位"
    "LEDGER_CREATE" -> "记一笔账"
    "LEDGER_UPDATE" -> "改账本流水"
    "LEDGER_DELETE" -> "删账本流水"
    // 2026-09-19 审计补的"动钱必留痕"动作码（这几条写操作以前一条日志都不写）
    "RECEIPT_CREATE" -> "客户收款"
    "SETTLEMENT_CREATE" -> "建司机结算单"
    "SETTLEMENT_STATUS" -> "结算单确认/付款/作废"
    "EXPENSE_CREATE" -> "记一笔开销"
    "DRIVER_BILL_GENERATE" -> "生成司机应付明细"
    "CUSTOMER_MERGE" -> "合并客户"
    "PRODUCT_CREATE" -> "新建商品"
    "PRODUCT_UPDATE" -> "修改商品"
    "PRODUCT_DELETE" -> "删除商品"
    "PRODUCT_RESTORE" -> "恢复商品"
    "PRICE_RULE_UPSERT" -> "修改批发价"
    "USER_CREATE" -> "新建账号"
    "USER_UPDATE" -> "修改账号"
    // ⚠️ 下面四条是**第二遍真机**补上的：它们在库里出现过，而这张表漏了 →
    //    审计页上直接显示 `USER_RESTORE`／`PRODUCT_DELETE` 这种原始码，用户看不懂。
    //    现在有一条红线**从后端源码里扫出所有动作名**，逐个要求这里必须有中文（见 §44.8）。
    "USER_DELETE" -> "删除账号"
    "USER_RESTORE" -> "恢复账号"
    "INVENTORY_ADJUST" -> "调整库存"
    // AI 撤回：用户点了「撤回」，把一次 AI 写操作回滚掉——单独一行，一眼能看出"这次是撤销"
    "AI_UNDO" -> "撤回 AI 的改动"
    // 司机计费规则（v3.36）：拆成两条是为了让审计页能分开回答两个问题——
    // 「这份规则被改成什么样了」和「谁的计费规则被换了」。
    "DRIVER_RULE_UPSERT" -> "改司机计费规则"
    "DRIVER_RULE_ATTACH" -> "换司机的计费规则"
    // 司机到场补导航信息（v3.42）：这个坐标会被写进**全库共享**的地点库，
    // 所以要能一眼看出"是谁在哪一单上标的"（混进"修改订单"里就分不出来了）。
    "ORDER_NAVIGATION_FILL" -> "补订单导航信息"
    // 商品分类名册（v3.43）：改的是"下单页左侧那一列叫什么、按什么顺序"。
    // 拆三个码，是因为要回答三个不同的问题——改了哪个分类 / 删了哪个 / 顺序怎么排的。
    "PRODUCT_CATEGORY_UPSERT" -> "改商品分类"
    "PRODUCT_CATEGORY_DELETE" -> "删商品分类"
    "PRODUCT_CATEGORY_REORDER" -> "调整分类顺序"
    // 地点分类（2026-09-19）：与商品分类**分开命名** —— 审计里"改了商品分类"和
    // "改了自己的地点分类"是两件事，都叫「改分类」就分不出是哪一件了。
    "PLACE_CATEGORY_UPSERT" -> "改地点分类"
    "PLACE_CATEGORY_DELETE" -> "删地点分类"
    "PLACE_CATEGORY_REORDER" -> "调地点分类顺序"
    // 开销分类（2026-09-20）：与上面两套**分开命名**，原因同地点分类 ——
    // 审计里"改了开销分类"和"改了商品/地点分类"是三件事，都叫「改分类」就分不出来了。
    "EXPENSE_CATEGORY_UPSERT" -> "改开销分类"
    "EXPENSE_CATEGORY_DELETE" -> "删开销分类"
    "EXPENSE_CATEGORY_REORDER" -> "调开销分类顺序"
    // 商品可见白名单（v3.43）：本质是授权，必须一眼看出"谁给谁开了哪些商品"。
    "PRODUCT_VISIBILITY_SET" -> "改商品可见范围"
    // 常用共享地点自动进「我的地点」（v3.43）：系统替他改了他自己的库，
    // 他下次看到多出一条地点，得能查出是这一步加的。
    "PLACE_AUTO_ADDED" -> "常用地点自动入库"
    // 共享地点库的管理（2026-09-19）：这张表全库共用，改/撤/删影响的是**所有人**的选点
    "PLACE_UPDATE" -> "改共享地点"
    "PLACE_PUBLISH" -> "设为共享地点"
    "PLACE_DEMOTE" -> "撤销共享地点"
    "PLACE_DELETE" -> "删共享地点"
    "PLACE_RESTORE" -> "恢复共享地点"
    // 车辆台账（v3.44）：车牌/车型会出现在记账与油耗选车的地方。
    // 拆两个码，回答两个不同的问题——「这辆车被改成什么样了」和「谁把车从张三名下拿走了」。
    "VEHICLE_UPSERT" -> "新增/修改车辆"
    "VEHICLE_DRIVER_SET" -> "车辆换/解绑司机"
    // 挂账单位与运费模板（2026-09-19 审计 R14-1）：这两块原来**一条日志都不写**，
    // 所以审计页上也从来不会出现它们；现在补上了写入点，中文名也得跟上
    // （`_check_action_labels.py` 会拦：漏了的话卡片上直接显示原始码）。
    "ARREARS_UNIT_UPSERT" -> "新增/修改挂账单位"
    "ARREARS_UNIT_DELETE" -> "删除挂账单位"
    "ARREARS_UNIT_RESTORE" -> "恢复挂账单位"
    "FREIGHT_TEMPLATE_UPSERT" -> "新增/修改运费模板"
    "FREIGHT_TEMPLATE_DELETE" -> "删除运费模板"
    "FREIGHT_TEMPLATE_RESTORE" -> "恢复运费模板"
    // 运费分类名册（2026-09-21）：运费模板与计费规则共用的一套分类
    "FREIGHT_CATEGORY_UPSERT" -> "改运费分类"
    "FREIGHT_CATEGORY_DELETE" -> "删运费分类"
    "FREIGHT_CATEGORY_REORDER" -> "调运费分类顺序"
    // 预订单分类名册（2026-09-22）：预订单页左栏那一列（改名会级联改掉挂着的预设单）
    "ORDER_TEMPLATE_CATEGORY_UPSERT" -> "改预订单分类"
    "ORDER_TEMPLATE_CATEGORY_DELETE" -> "删预订单分类"
    "ORDER_TEMPLATE_CATEGORY_REORDER" -> "调预订单分类顺序"
    // 派单员手动定价：这一单没匹配到价目 → 他手填了运费（可顺带沉淀成价目）
    "ORDER_FREIGHT_PRICE" -> "手动定价运费"
    // 批发商自己那一本账（2026-09-20）：他给下游货主核销 / 撤销 / 恢复。
    // 这三个动作**不写** cash_flows、不动 orders.paid（见 `models/shipper_settlement.py`），
    // 所以审计页是唯一能回查"这笔核销谁在什么时候记的、撤的"的地方。
    "SHIPPER_SETTLE_CREATE" -> "批发商核销（向他的货主收钱）"
    "SHIPPER_SETTLE_REVOKE" -> "撤销批发商核销"
    "SHIPPER_SETTLE_RESTORE" -> "恢复批发商核销"
    else -> action
}

@Composable
private fun ExceptionCard(e: ExceptionOrderDto, onResolve: (() -> Unit)?) {
    val lv = exceptionRisk(e)
    val days = stuckDays(e)
    SectionCard {
        Row(verticalAlignment = Alignment.CenterVertically) {
            AccentBar(levelColor(lv))
            Spacer(Modifier.width(10.dp))
            Column(Modifier.weight(1f)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text("#" + e.orderNo, style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Bold)
                    // 「拖了几天」是紧急层级的**可见依据**：用户能自己核对排序对不对。
                    // 「已过去」的不显示——单子已经了结，没有"拖"可言。
                    if (lv != RiskLevel.DONE && lv != RiskLevel.PAST && days > 0) {
                        Spacer(Modifier.width(6.dp))
                        KindBadge("已拖 " + days + " 天", if (days >= 3) Color(0xFFE53935) else Color(0xFFFF8A65))
                    }
                }
                // **哪里异常**放第二行（用户最先要看的）——它就是后端给的 exception_reason。
                Text(e.exceptionReason, style = MaterialTheme.typography.bodyMedium, color = Color(0xFFE53935))
                // **谁的异常**：货主/司机各一段，**缺哪个就不显示哪个**，不用 `?: ""` 拼出
                // 「司机：  货主：老张」这种空壳（用户原话：「没必要的数据不需要存在」）。
                val who = listOfNotNull(
                    e.shipperName?.takeIf { it.isNotBlank() }?.let { "货主：$it" },
                    e.driverName?.takeIf { it.isNotBlank() }?.let { "司机：$it" },
                )
                if (who.isNotEmpty()) {
                    Text(who.joinToString("  "), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                // ⚠️ 状态要写**中文**：原来直接把后端枚举名（`PENDING_DISPATCH`）印在卡上，
                //    这就是用户说的"代码返回什么就照样渲染上去"。见 [AiWrites.statusLabel]。
                val st = AiOrderRef.statusLabel(e.status)
                if (st.isNotBlank()) {
                    Text("状态：$st", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                if (e.exceptionResolvedAt != null) Text("解决：" + e.exceptionResolution, style = MaterialTheme.typography.bodySmall, color = Color(0xFF00B578))
            }
            if (onResolve != null) TextButton(onClick = onResolve) { Text("解决") }
        }
    }
}