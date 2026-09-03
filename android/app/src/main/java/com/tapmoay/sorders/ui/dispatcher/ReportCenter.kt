package com.tapmoay.sorders.ui.dispatcher

import androidx.compose.foundation.background
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
import androidx.compose.ui.graphics.Shape
import androidx.compose.ui.unit.dp
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.sp
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.data.remote.dto.ExceptionOrderDto
import com.tapmoay.sorders.ui.common.*
import com.tapmoay.sorders.util.formatMoney
import java.time.LocalDate

/** 报表中心（排版参考：顶部页签 + 完整时段 + 淡紫表头分组 + 彩色竖线 + 指标卡） */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ReportCenterScreen(container: AppContainer, onBack: () -> Unit, initialTab: Int = 0) {
    val vm: ReportCenterViewModel = appViewModel { ReportCenterViewModel(container, initialTab) }
    val snackbar = remember { SnackbarHostState() }
    LaunchedEffect(vm.actionResult, vm.error) {
        vm.actionResult?.let { snackbar.showSnackbar(it); vm.actionResult = null } ?: vm.error?.let { snackbar.showSnackbar(it); vm.error = null }
    }
    var showPicker by remember { mutableStateOf(false) }

    Scaffold(
        snackbarHost = { SnackbarHost(snackbar) },
        topBar = {
            AppTopBar(
                title = "报表中心",
                onBack = onBack,
                actions = {
                    TextButton(onClick = { vm.load() }) {
                        Icon(Icons.Default.Refresh, null, Modifier.size(18.dp))
                        Spacer(Modifier.width(2.dp))
                        Text("刷新")
                    }
                },
            )
        },
    ) { pad ->
        Column(Modifier.fillMaxSize().padding(pad)) {
            Surface(
                color = MaterialTheme.colorScheme.surface,
                shape = MaterialTheme.shapes.small,
                modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp).clickable { showPicker = true },
            ) {
                Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(horizontal = 12.dp, vertical = 8.dp)) {
                    Icon(Icons.Default.DateRange, null, Modifier.size(16.dp), tint = Color(0xFF6950F5))
                    Spacer(Modifier.width(6.dp))
                    Text(vm.periodText, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurface)
                }
            }
            Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp), verticalAlignment = Alignment.CenterVertically) {
                listOf("day" to "按日", "week" to "按周", "month" to "按月").forEach { (k, label) ->
                    val sel = vm.mode == k
                    Surface(
                        color = if (sel) MaterialTheme.colorScheme.primary.copy(alpha = 0.14f) else MaterialTheme.colorScheme.surfaceVariant,
                        shape = MaterialTheme.shapes.small,
                        modifier = Modifier.padding(end = 8.dp).clickable { vm.mode = k; vm.load() },
                    ) {
                        Text(
                            label,
                            style = MaterialTheme.typography.labelMedium,
                            fontWeight = when { sel -> androidx.compose.ui.text.font.FontWeight.Bold; else -> androidx.compose.ui.text.font.FontWeight.Normal },
                            color = if (sel) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurfaceVariant,
                            modifier = Modifier.padding(horizontal = 14.dp, vertical = 7.dp),
                        )
                    }
                }
            }
            Spacer(Modifier.height(8.dp))
            SegmentedStatusTabs(
                labels = listOf("营业", "商品", "司机", "异常"),
                colors = listOf(
                    androidx.compose.ui.graphics.Color(0xFFFF9500), // 营业 · 橙
                    androidx.compose.ui.graphics.Color(0xFF8455E6), // 商品 · 紫
                    androidx.compose.ui.graphics.Color(0xFF00B578), // 司机 · 绿
                    androidx.compose.ui.graphics.Color(0xFFFF4D4F), // 异常 · 红
                ),
                selected = vm.tab,
                onSelect = { vm.tab = it; vm.load() },
            )
            when (vm.tab) {
                0 -> TurnoverTab(vm)
                1 -> ProductTab(vm)
                2 -> DriverTab(vm)
                else -> ExceptionTab(vm)
            }
        }
    }

    if (showPicker) {
        val pickerState = androidx.compose.material3.rememberDatePickerState(
            initialSelectedDateMillis = try {
                LocalDate.parse(vm.anchor).atStartOfDay(java.time.ZoneId.systemDefault()).toInstant().toEpochMilli()
            } catch (e: Exception) {
                System.currentTimeMillis()
            }
        )
        DatePickerDialog(
            onDismissRequest = { showPicker = false },
            confirmButton = {
                TextButton(onClick = {
                    pickerState.selectedDateMillis?.let {
                        vm.anchor = java.time.Instant.ofEpochMilli(it).atZone(java.time.ZoneId.systemDefault()).toLocalDate().toString()
                        vm.load()
                    }
                    showPicker = false
                }) { Text("确定") }
            },
            dismissButton = { TextButton(onClick = { showPicker = false }) { Text("取消") } },
        ) {
            DatePicker(state = pickerState)
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
            Text(title, style = MaterialTheme.typography.labelLarge, fontWeight = androidx.compose.ui.text.font.FontWeight.Bold, color = Color(0xFF495057))
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
        Text(value, style = MaterialTheme.typography.headlineSmall, fontWeight = androidx.compose.ui.text.font.FontWeight.Bold, color = color)
    }
}

@Composable
private fun StatRow(label: String, value: String, color: Color = MaterialTheme.colorScheme.onSurface) {
    Row(Modifier.fillMaxWidth().padding(vertical = 6.dp), verticalAlignment = Alignment.CenterVertically) {
        Text(label, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.weight(1f))
        Text(value, style = MaterialTheme.typography.titleSmall, fontWeight = androidx.compose.ui.text.font.FontWeight.Bold, color = color, textAlign = TextAlign.End)
    }
}

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
                StatBig("实际营业金额", "¥" + formatMoney(data.totalAmount), Color(0xFF1E6FFF))
            }
            item {
                SectionCard {
                    Text("营业指标", style = MaterialTheme.typography.titleMedium)
                    Spacer(Modifier.height(4.dp))
                    StatRow("订单数", data.totalOrders.toString() + " 单")
                    StatRow("单均价", "¥" + formatMoney(data.avgOrder))
                    StatRow("司机运费支出", "¥" + formatMoney(data.totalFreight), Color(0xFFFF9500))
                    StatRow("异常订单数", vm.pendingExceptionCount.toString() + " 单", Color(0xFFE53935))
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
                            Text("¥" + formatMoney(s.amount), style = MaterialTheme.typography.titleSmall, fontWeight = androidx.compose.ui.text.font.FontWeight.Bold, color = Color(0xFF1E6FFF), textAlign = TextAlign.End, modifier = Modifier.width(84.dp))
                        }
                        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
                    }
                }
            }
        }
    }
}

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
                    StatBig("商品总金额", "¥" + formatMoney(data.totalAmount), Color(0xFF8455E6), Modifier.weight(1f))
                    StatBig("出库总件数", data.totalQty.toString() + " 件", Color(0xFF00A8A8), Modifier.weight(1f))
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
                GroupHeader("商品明细")
                Spacer(Modifier.height(8.dp))
            }
            items(data.items, key = { it.productName }) { p ->
                SectionCard {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        AccentBar(Color(0xFF8455E6))
                        Spacer(Modifier.width(10.dp))
                        Column(Modifier.weight(1f)) {
                            Text(p.productName, style = MaterialTheme.typography.titleSmall, fontWeight = androidx.compose.ui.text.font.FontWeight.Bold)
                            Text(p.qty.toString() + " 件 · " + p.orderCount + " 单", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                        Text("¥" + formatMoney(p.amount), style = MaterialTheme.typography.titleMedium, fontWeight = androidx.compose.ui.text.font.FontWeight.Bold, color = Color(0xFFFF9500))
                    }
                }
            }
        }
    }
}

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
                SectionCard {
                    Text("完成单量 TOP（条形图）", style = MaterialTheme.typography.titleMedium)
                    Spacer(Modifier.height(8.dp))
                    BarChart(data.drivers.take(8).map { it.completedCount.toFloat() }, data.drivers.take(8).map { it.driverName }, Color(0xFF00B578))
                }
            }
            item {
                GroupHeader("司机绩效")
                Spacer(Modifier.height(8.dp))
            }
            items(data.drivers, key = { it.driverId }) { d ->
                SectionCard {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        AccentBar(Color(0xFF00B578))
                        Spacer(Modifier.width(10.dp))
                        Column(Modifier.weight(1f)) {
                            Text(d.driverName.ifBlank { "司机 " + d.driverId }, style = MaterialTheme.typography.titleSmall, fontWeight = androidx.compose.ui.text.font.FontWeight.Bold)
                            Text("准时率 " + ((d.onTimeRate ?: 0.0) * 100).toInt() + "% · 拍照率 " + (d.photoUploadRate * 100).toInt() + "%", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                        Text(d.completedCount.toString() + " 单", style = MaterialTheme.typography.titleMedium, fontWeight = androidx.compose.ui.text.font.FontWeight.Bold, color = Color(0xFF00B578))
                    }
                }
            }
        }
    }
}

@Composable
private fun ExceptionTab(vm: ReportCenterViewModel) {
    if (vm.loading && vm.exceptions.isEmpty()) {
        Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { CircularProgressIndicator() }
        return
    }
    val pending = vm.exceptions.filter { it.exceptionResolvedAt == null }
    val resolved = vm.exceptions.filter { it.exceptionResolvedAt != null }
    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        item {
            StatBig("待解决异常", pending.size.toString() + " 单", Color(0xFFE53935))
        }
        item {
            GroupHeader("待解决列表")
            Spacer(Modifier.height(8.dp))
        }
        items(pending, key = { "p" + it.id }) { e ->
            ExceptionCard(e, onResolve = { vm.openResolve(e) })
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
    }
}

@Composable
private fun ExceptionCard(e: ExceptionOrderDto, onResolve: (() -> Unit)?) {
    SectionCard {
        Row(verticalAlignment = Alignment.CenterVertically) {
            AccentBar(Color(0xFFE53935))
            Spacer(Modifier.width(10.dp))
            Column(Modifier.weight(1f)) {
                Text("#" + e.orderNo, style = MaterialTheme.typography.titleSmall, fontWeight = androidx.compose.ui.text.font.FontWeight.Bold)
                Text(e.exceptionReason, style = MaterialTheme.typography.bodyMedium, color = Color(0xFFE53935))
                Text(
                    (e.driverName?.let { "司机：" + it + "  " } ?: "") + (e.shipperName?.let { "货主：" + it } ?: "") + " · " + e.status,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                if (e.exceptionResolvedAt != null) Text("解决：" + e.exceptionResolution, style = MaterialTheme.typography.bodySmall, color = Color(0xFF00B578))
            }
            if (onResolve != null) TextButton(onClick = onResolve) { Text("解决") }
        }
    }
}