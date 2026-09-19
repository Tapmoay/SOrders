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
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.data.remote.dto.ExceptionOrderDto
import com.tapmoay.sorders.data.remote.dto.OperationLogDto
import com.tapmoay.sorders.ui.common.*
import com.tapmoay.sorders.util.formatMoney
import com.tapmoay.sorders.util.saveExportFile
import java.time.LocalDate

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

    Scaffold(
        snackbarHost = { SnackbarHost(snackbar) },
        topBar = {
            AppTopBar(
                title = title,
                onBack = onBack,
                actions = {
                    TextButton(onClick = { vm.load() }) {
                        Icon(Icons.Default.Refresh, null, Modifier.size(18.dp))
                        Spacer(Modifier.width(2.dp))
                        Text("刷新")
                    }
                    TextButton(
                        onClick = {
                            vm.exportCurrent { bytes ->
                                if (bytes != null) {
                                    val fn = title + "-" + vm.anchor + ".xlsx"
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
            if (vm.tab != 5) {
                ReportTimeNav(
                    mode = vm.mode,
                    anchor = vm.anchor,
                    periodText = vm.periodText,
                    onModeChange = { vm.mode = it; vm.load() },
                    onAnchorChange = { vm.anchor = it; vm.load() },
                )
            } else {
                Text(
                    "资金流水（按日/周/月切换上方时间）",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp),
                )
            }
            when (vm.tab) {
                0 -> TurnoverTab(vm)
                1 -> ProductTab(vm)
                2 -> DriverTab(vm)
                3 -> CustomerTab(vm)
                4 -> FinanceTab(vm)
                else -> ExceptionTab(vm)
            }
        }
    }

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

private fun coverageText(cov: Int, total: Int): String =
    "毛利口径：仅按有成本快照的订单计算（" + cov + "/" + total + " 行计入），未计入的订单未参与毛利计算。"

@Composable
private fun CoverNote(cov: Int, total: Int) {
    Text(coverageText(cov, total), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
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
                    StatRow("异常订单数", vm.pendingExceptionCount.toString() + " 单", Color(0xFFE53935))
                    if (data.cancelledOrders > 0) StatRow("已撤销订单数", data.cancelledOrders.toString() + " 单", Color(0xFF8A8A8E))
                }
            }
            item {
                SectionCard {
                    Text("盈利概览", style = MaterialTheme.typography.titleMedium)
                    Spacer(Modifier.height(4.dp))
                    val profit = (data.totalAmount.toDoubleOrNull() ?: 0.0) - (data.costTotal.toDoubleOrNull() ?: 0.0)
                    StatRow("商品毛利", "¥" + formatMoney(profit.toString()), Color(0xFF00B578))
                    CoverNote(data.costCoveredLines, data.totalLines)
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
                    val profit = (data.totalAmount.toDoubleOrNull() ?: 0.0) - (data.costTotal.toDoubleOrNull() ?: 0.0)
                    StatRow("商品毛利", "¥" + formatMoney(profit.toString()), Color(0xFF00B578))
                    CoverNote(data.costCoveredLines, data.totalLines)
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
                            val profit = (p.amount.toDoubleOrNull() ?: 0.0) - (p.cost.toDoubleOrNull() ?: 0.0)
                            Text("毛利 ¥" + formatMoney(profit.toString()) + (if (p.damageQty > 0) " · 货损 ¥" + formatMoney(p.damageAmount) else ""), style = MaterialTheme.typography.bodySmall, color = Color(0xFF00B578))
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
    val all = shippers + members
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
    val income = flows.filter { ReportFinance.isIncome(it.direction) }.sumOf { it.amount.toDoubleOrNull() ?: 0.0 }
    val expense = flows.filter { !ReportFinance.isIncome(it.direction) }.sumOf { it.amount.toDoubleOrNull() ?: 0.0 }
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
            GroupHeader("资金流水（" + flows.size + " 条）")
            Spacer(Modifier.height(8.dp))
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
                Text(
                    "排序：改钱/删数据/账号权限 → 改状态 → 其它，同级按时间倒序",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
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
    "ORDER_LINE_ADD" -> "加一行商品"
    "ORDER_LINE_UPDATE" -> "改一行商品"
    "ORDER_LINE_DELETE" -> "删一行商品"
    "ORDER_PAY" -> "标记已收款"
    "ORDER_CHARGE" -> "转入挂账单位"
    "LEDGER_CREATE" -> "记一笔账"
    "LEDGER_UPDATE" -> "改账本流水"
    "LEDGER_DELETE" -> "删账本流水"
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
    // 商品可见白名单（v3.43）：本质是授权，必须一眼看出"谁给谁开了哪些商品"。
    "PRODUCT_VISIBILITY_SET" -> "改商品可见范围"
    // 常用共享地点自动进「我的地点」（v3.43）：系统替他改了他自己的库，
    // 他下次看到多出一条地点，得能查出是这一步加的。
    "PLACE_AUTO_ADDED" -> "常用地点自动入库"
    // 车辆台账（v3.44）：车牌/车型会出现在记账与油耗选车的地方。
    // 拆两个码，回答两个不同的问题——「这辆车被改成什么样了」和「谁把车从张三名下拿走了」。
    "VEHICLE_UPSERT" -> "新增/修改车辆"
    "VEHICLE_DRIVER_SET" -> "车辆换/解绑司机"
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