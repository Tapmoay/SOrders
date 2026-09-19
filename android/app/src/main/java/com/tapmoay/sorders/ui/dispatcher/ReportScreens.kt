package com.tapmoay.sorders.ui.dispatcher

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.data.remote.dto.ExceptionOrderDto
import com.tapmoay.sorders.ui.common.*
import com.tapmoay.sorders.util.formatMoney
import java.time.LocalDate

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun ReportModeBar(vm: ReportViewModel, title: String) {
    var showPicker by remember { mutableStateOf(false) }
    Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 6.dp), verticalAlignment = Alignment.CenterVertically) {
        listOf("day" to "按日", "week" to "按周", "month" to "按月").forEach { (k, label) ->
            val sel = vm.mode == k
            Surface(
                color = if (sel) MaterialTheme.colorScheme.primary.copy(alpha = 0.14f) else MaterialTheme.colorScheme.surface,
                shape = MaterialTheme.shapes.small,
                modifier = Modifier.padding(end = 8.dp).clickable {
                    vm.mode = k
                    vm.load()
                },
            ) {
                Text(
                    label,
                    style = MaterialTheme.typography.labelLarge,
                    color = if (sel) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(horizontal = 14.dp, vertical = 7.dp),
                )
            }
        }
        Spacer(Modifier.weight(1f))
        Surface(
            color = MaterialTheme.colorScheme.surface,
            shape = MaterialTheme.shapes.small,
            modifier = Modifier.clickable { showPicker = true },
        ) {
            Text(
                vm.anchor,
                style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(horizontal = 10.dp, vertical = 7.dp),
            )
        }
    }
    if (showPicker) {
        val dpState = androidx.compose.material3.rememberDatePickerState(
            initialSelectedDateMillis = try {
                java.time.LocalDate.parse(vm.anchor).atStartOfDay(java.time.ZoneId.systemDefault()).toInstant().toEpochMilli()
            } catch (e: Exception) {
                System.currentTimeMillis()
            }
        )
        DatePickerDialog(
            onDismissRequest = { showPicker = false },
            confirmButton = {
                TextButton(onClick = {
                    val ms = dpState.selectedDateMillis
                    if (ms != null) {
                        vm.anchor = java.time.Instant.ofEpochMilli(ms).atZone(java.time.ZoneId.systemDefault()).toLocalDate().toString()
                        vm.load()
                    }
                    showPicker = false
                }) { Text("确定") }
            },
            dismissButton = { TextButton(onClick = { showPicker = false }) { Text("取消") } },
        ) {
            DatePicker(state = dpState)
        }
    }
}

@Composable
private fun StatCard(label: String, value: String, color: Color = MaterialTheme.colorScheme.primary, sub: String? = null) {
    SectionCard {
        Text(label, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Spacer(Modifier.height(4.dp))
        Text(value, style = MaterialTheme.typography.headlineSmall, fontWeight = androidx.compose.ui.text.font.FontWeight.Bold, color = color)
        if (sub != null) {
            Text(sub, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}

// ============ 营业额报表 ============
@Composable
fun ReportTurnoverScreen(container: AppContainer, onBack: () -> Unit) {
    val vm: TurnoverReportViewModel = appViewModel { TurnoverReportViewModel(container) }
    Scaffold(topBar = { AppTopBar(title = "营业额报表", onBack = onBack) }) { pad ->
        Column(Modifier.fillMaxSize().padding(pad)) {
            ReportModeBar(vm, "营业额")
            val data = vm.data
            if (data == null) {
                Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { CircularProgressIndicator() }
                return@Column
            }
            LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                item {
                    Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                        StatCard("营业金额（" + data.periodLabel + "）", "¥" + formatMoney(data.totalAmount), Color(0xFF1E6FFF), "订单 " + data.totalOrders + " 单")
                        StatCard("司机运费支出", "¥" + formatMoney(data.totalFreight), Color(0xFFFF9500), "均价 ¥" + formatMoney(data.avgOrder))
                    }
                }
                item {
                    SectionCard {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Text("统计图", style = MaterialTheme.typography.titleMedium, modifier = Modifier.weight(1f))
                            TextButton(onClick = { vm.chartType = if (vm.chartType == "line") "bar" else "line" }) {
                                Text(if (vm.chartType == "line") "切换条形图" else "切换折线图")
                            }
                        }
                        Spacer(Modifier.height(8.dp))
                        val vals = data.series.map { it.amount.toDoubleOrNull()?.toFloat() ?: 0f }
                        val labels = data.series.map { it.label }
                        if (vals.any { it > 0f }) {
                            if (vm.chartType == "line") LineChart(vals, labels, Color(0xFF1E6FFF))
                            else BarChart(vals, labels, Color(0xFF00B578))
                        } else {
                            ChartEmpty("该时段暂无送达数据")
                        }
                    }
                }
                item {
                    SectionCard {
                        Text("每日明细", style = MaterialTheme.typography.titleMedium)
                        Spacer(Modifier.height(6.dp))
                        data.series.forEach { s ->
                            Row(Modifier.fillMaxWidth().padding(vertical = 6.dp), verticalAlignment = Alignment.CenterVertically) {
                                Text(s.label, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.weight(1f), color = MaterialTheme.colorScheme.onSurfaceVariant)
                                Text(s.orders.toString() + " 单", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                                Spacer(Modifier.width(12.dp))
                                Text("¥" + formatMoney(s.amount), style = MaterialTheme.typography.titleSmall, fontWeight = androidx.compose.ui.text.font.FontWeight.Bold, color = Color(0xFF1E6FFF))
                            }
                            HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
                        }
                    }
                }
            }
        }
    }
}

// ============ 商品明细报表 ============
@Composable
fun ReportProductScreen(container: AppContainer, onBack: () -> Unit) {
    val vm: ProductReportViewModel = appViewModel { ProductReportViewModel(container) }
    Scaffold(topBar = { AppTopBar(title = "商品明细报表", onBack = onBack) }) { pad ->
        Column(Modifier.fillMaxSize().padding(pad)) {
            ReportModeBar(vm, "商品")
            val data = vm.data
            if (data == null) {
                Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { CircularProgressIndicator() }
                return@Column
            }
            LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                item {
                    Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                        StatCard("商品总金额", "¥" + formatMoney(data.totalAmount), Color(0xFF8455E6))
                        StatCard("出库总件数", data.totalQty.toString() + " 件", Color(0xFF00A8A8))
                    }
                }
                item {
                    SectionCard {
                        Text("销量 TOP 商品（条形图）", style = MaterialTheme.typography.titleMedium)
                        Spacer(Modifier.height(8.dp))
                        val top = data.items.take(8)
                        if (top.isEmpty()) ChartEmpty("暂无数据")
                        else BarChart(top.map { it.amount.toDoubleOrNull()?.toFloat() ?: 0f }, top.map { it.productName }, Color(0xFF8455E6))
                    }
                }
                items(data.items, key = { it.productName }) { p ->
                    SectionCard {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Column(Modifier.weight(1f)) {
                                Text(p.productName, style = MaterialTheme.typography.titleSmall, fontWeight = androidx.compose.ui.text.font.FontWeight.Bold)
                                Spacer(Modifier.height(2.dp))
                                Text(p.qty.toString() + " 件 · " + p.orderCount + " 单", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                            }
                            Text("¥" + formatMoney(p.amount), style = MaterialTheme.typography.titleMedium, fontWeight = androidx.compose.ui.text.font.FontWeight.Bold, color = Color(0xFFFF9500))
                        }
                    }
                }
            }
        }
    }
}

// ============ 司机绩效报表 ============
@Composable
fun ReportDriverScreen(container: AppContainer, onBack: () -> Unit) {
    val vm: DriverReportViewModel = appViewModel { DriverReportViewModel(container) }
    Scaffold(topBar = { AppTopBar(title = "司机绩效报表", onBack = onBack) }) { pad ->
        Column(Modifier.fillMaxSize().padding(pad)) {
            ReportModeBar(vm, "司机")
            val data = vm.data
            if (data == null) {
                Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { CircularProgressIndicator() }
                return@Column
            }
            LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                if (data.drivers.isEmpty()) {
                    item { ChartEmpty("该时段暂无司机绩效数据") }
                } else {
                    item {
                        SectionCard {
                            Text("完成单量 TOP", style = MaterialTheme.typography.titleMedium)
                            Spacer(Modifier.height(8.dp))
                            BarChart(data.drivers.take(8).map { it.completedCount.toFloat() }, data.drivers.take(8).map { it.driverName }, Color(0xFF00B578))
                        }
                    }
                    items(data.drivers, key = { it.driverId }) { d ->
                        SectionCard {
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                Column(Modifier.weight(1f)) {
                                    Text(d.driverName.ifBlank { "司机 " + d.driverId }, style = MaterialTheme.typography.titleSmall, fontWeight = androidx.compose.ui.text.font.FontWeight.Bold)
                                    Spacer(Modifier.height(2.dp))
                                    Text(
                                        "准时率 " + ((d.onTimeRate ?: 0.0) * 100).toInt() + "% · 拍照率 " + (d.photoUploadRate * 100).toInt() + "%",
                                        style = MaterialTheme.typography.bodySmall,
                                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                                    )
                                }
                                Text(d.completedCount.toString() + " 单", style = MaterialTheme.typography.titleMedium, fontWeight = androidx.compose.ui.text.font.FontWeight.Bold, color = Color(0xFF00B578))
                            }
                        }
                    }
                }
            }
        }
    }
}

// ============ 异常订单报表 ============
@Composable
fun ReportExceptionScreen(container: AppContainer, onBack: () -> Unit) {
    val vm: ExceptionReportViewModel = appViewModel { ExceptionReportViewModel(container) }
    val snackbar = remember { SnackbarHostState() }
    OneShotSnackbar(snackbar, vm.actionResult, onConsumed = { vm.actionResult = null })
    OneShotSnackbar(snackbar, vm.error, onConsumed = { vm.error = null })
    Scaffold(snackbarHost = { SnackbarHost(snackbar) }, topBar = { AppTopBar(title = "异常订单报表", onBack = onBack) }) { pad ->
        Column(Modifier.fillMaxSize().padding(pad)) {
            Text(
                "整单环节任何问题（撤销/撤回/超时未派/超时未送/逾期送达）都会标记异常；小问题派单员可在此解决。",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp),
            )
            val pending = vm.items.filter { it.exceptionResolvedAt == null }
            val resolved = vm.items.filter { it.exceptionResolvedAt != null }
            LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                item {
                    SectionCard {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Text("待解决异常", style = MaterialTheme.typography.titleMedium, modifier = Modifier.weight(1f))
                            Text(pending.size.toString() + " 单", style = MaterialTheme.typography.titleSmall, fontWeight = androidx.compose.ui.text.font.FontWeight.Bold, color = Color(0xFFE53935))
                        }
                    }
                }
                items(pending, key = { "p" + it.id }) { e ->
                    ExceptionCard(e, onResolve = { vm.openResolve(e) })
                }
                if (resolved.isNotEmpty()) {
                    item {
                        SectionCard {
                            Text("已解决（" + resolved.size + "）", style = MaterialTheme.typography.titleMedium)
                        }
                    }
                    items(resolved, key = { "r" + it.id }) { e ->
                        ExceptionCard(e, onResolve = null)
                    }
                }
            }
        }
    }
    vm.resolveTarget?.let { t ->
        AlertDialog(
            onDismissRequest = { vm.resolveTarget = null },
            title = { Text("解决异常") },
            text = {
                Column {
                    Text("" + t.orderNo + " · " + t.exceptionReason, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    Spacer(Modifier.height(8.dp))
                    OutlinedTextField(
                        value = vm.resolveNote,
                        onValueChange = { vm.resolveNote = it },
                        label = { Text("解决说明（如：已电话联系司机重新派单）") },
                        singleLine = false,
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
private fun ExceptionCard(e: ExceptionOrderDto, onResolve: (() -> Unit)?) {
    SectionCard {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text("#" + e.orderNo, style = MaterialTheme.typography.titleSmall, fontWeight = androidx.compose.ui.text.font.FontWeight.Bold)
                Spacer(Modifier.height(2.dp))
                Text(e.exceptionReason, style = MaterialTheme.typography.bodyMedium, color = Color(0xFFE53935))
                Spacer(Modifier.height(2.dp))
                Text(
                    (e.driverName?.let { "司机：" + it + "  " } ?: "") + (e.shipperName?.let { "货主：" + it } ?: "") + " · " + e.status,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                if (e.exceptionResolvedAt != null) {
                    Text("解决说明：" + e.exceptionResolution, style = MaterialTheme.typography.bodySmall, color = Color(0xFF00B578))
                }
            }
            if (onResolve != null) {
                TextButton(onClick = onResolve) { Text("解决") }
            }
        }
    }
}
