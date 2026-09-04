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
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.data.remote.dto.ExceptionOrderDto
import com.tapmoay.sorders.data.remote.dto.OperationLogDto
import com.tapmoay.sorders.ui.common.*
import com.tapmoay.sorders.util.formatMoney

/** 报表页（从入口页进入）：顶部时间导航 + 主题内容 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ReportCenterScreen(container: AppContainer, onBack: () -> Unit, initialTab: Int = 0) {
    val vm: ReportCenterViewModel = appViewModel { ReportCenterViewModel(container, initialTab) }
    val snackbar = remember { SnackbarHostState() }
    LaunchedEffect(vm.actionResult, vm.error) {
        vm.actionResult?.let { snackbar.showSnackbar(it); vm.actionResult = null } ?: vm.error?.let { snackbar.showSnackbar(it); vm.error = null }
    }

    val title = when (vm.tab) { 0 -> "营业纵览"; 1 -> "商品经营"; 2 -> "司机绩效"; else -> "异常与审计" }

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
                },
            )
        },
    ) { pad ->
        Column(Modifier.fillMaxSize().padding(pad)) {
            if (vm.tab != 3) {
                ReportTimeNav(
                    mode = vm.mode,
                    anchor = vm.anchor,
                    periodText = vm.periodText,
                    onModeChange = { vm.mode = it; vm.load() },
                    onAnchorChange = { vm.anchor = it; vm.load() },
                )
            } else {
                // 异常与审计：固定近 30 天
                Text(
                    "近 30 天运营异常与敏感操作记录",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp),
                )
            }
            when (vm.tab) {
                0 -> TurnoverTab(vm)
                1 -> ProductTab(vm)
                2 -> DriverTab(vm)
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
                    Text(
                        "毛利口径：仅按有成本快照的订单计算（" + data.costCoveredLines + "/" + data.totalLines + " 行计入），未计入的订单未参与毛利计算。",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    StatRow("货损金额", money(data.damageAmount), Color(0xFFE53935))
                    if (data.damageQty > 0) StatRow("货损件数", data.damageQty.toString() + " 件", Color(0xFFE53935))
                }
            }
            item {
                SectionCard {
                    Text("资金状态", style = MaterialTheme.typography.titleMedium)
                    Spacer(Modifier.height(4.dp))
                    StatRow("现金已收", money(data.collected), Color(0xFF00B578))
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
                    Text(
                        "毛利口径：仅按有成本快照的订单计算（" + data.costCoveredLines + "/" + data.totalLines + " 行计入），未计入的订单未参与毛利计算。",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
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
                GroupHeader("商品明细")
                Spacer(Modifier.height(8.dp))
            }
            items(data.items, key = { it.productName }) { p ->
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
                GroupHeader("司机绩效")
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
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                StatBig("待解决异常", pending.size.toString() + " 单", Color(0xFFE53935), Modifier.weight(1f))
                StatBig("已解决", resolved.size.toString() + " 单", Color(0xFF00B578), Modifier.weight(1f))
            }
        }
        item {
            val total = vm.exceptions.size
            val rate = if (total > 0) (resolved.size * 100 / total) else 0
            SectionCard {
                Text("解决率", style = MaterialTheme.typography.titleMedium)
                Spacer(Modifier.height(4.dp))
                StatRow("近 30 天异常总数", total.toString() + " 单")
                StatRow("解决率", rate.toString() + " %", Color(0xFF00B578))
            }
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
        item {
            GroupHeader("敏感操作审计（近 60 条）")
            Spacer(Modifier.height(8.dp))
        }
        items(vm.operationLogs, key = { "log" + it.id }) { log ->
            AuditLogCard(log)
        }
        if (vm.operationLogs.isEmpty()) {
            item { ChartEmpty("暂无操作日志") }
        }
    }
}

@Composable
private fun AuditLogCard(log: OperationLogDto) {
    SectionCard {
        Row(verticalAlignment = Alignment.CenterVertically) {
            AccentBar(Color(0xFF6950F5))
            Spacer(Modifier.width(10.dp))
            Column(Modifier.weight(1f)) {
                Text(actionLabel(log.action), style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Bold)
                log.changeContent?.takeIf { it.isNotBlank() }?.let {
                    Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 2)
                }
                Text(log.createdAt.take(19).replace("T", " "), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            log.orderId?.let { Text("单 #" + it, style = MaterialTheme.typography.bodySmall, color = Color(0xFF6950F5)) }
        }
    }
}

private fun actionLabel(action: String): String = when (action) {
    "order.split" -> "拆分子订单"
    "order.update_freight" -> "修改运费"
    "order.cancel" -> "撤销订单"
    "order.delete" -> "删除订单"
    "order.update" -> "修改订单"
    "order.exception" -> "标记异常"
    "price_rule" -> "修改批发价"
    else -> action
}

@Composable
private fun ExceptionCard(e: ExceptionOrderDto, onResolve: (() -> Unit)?) {
    SectionCard {
        Row(verticalAlignment = Alignment.CenterVertically) {
            AccentBar(Color(0xFFE53935))
            Spacer(Modifier.width(10.dp))
            Column(Modifier.weight(1f)) {
                Text("#" + e.orderNo, style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Bold)
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
