package com.tapmoay.sorders.ui.dispatcher

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.data.remote.dto.FreightSettlementGroupDto
import com.tapmoay.sorders.data.remote.dto.LedgerAccountOut
import com.tapmoay.sorders.data.remote.dto.LedgerEntryDto
import com.tapmoay.sorders.ui.common.*
import com.tapmoay.sorders.ui.theme.MemberGold
import com.tapmoay.sorders.ui.theme.MgrGreen
import com.tapmoay.sorders.ui.theme.MoneyOrange
import com.tapmoay.sorders.ui.theme.ProductPurple
import com.tapmoay.sorders.ui.theme.ShipperTeal
import com.tapmoay.sorders.util.formatMoney
import com.tapmoay.sorders.util.moneyToDouble

/**
 * 派单员账本管理：四类账（订单账/司机账/货主账/批发商账）。
 * ①时间范围导航 ②趋势图 ③汇总金额 ④明细（订单可点击查看；账户可展开流水）。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DispatcherLedgerScreen(
    container: AppContainer,
    onBack: () -> Unit,
    onOpenOrder: (Long) -> Unit = {},
    onOpenReceipts: () -> Unit = {},
    onOpenSettlements: () -> Unit = {},
    onOpenExpenses: () -> Unit = {},
    onOpenVehicles: () -> Unit = {},
) {
    val vm: DispatcherLedgerViewModel = appViewModel { DispatcherLedgerViewModel(container) }
    val snackbar = remember { SnackbarHostState() }

    OneShotSnackbar(snackbar, vm.actionResult, onConsumed = { vm.actionResult = null })

    // 失败**必须**看得见。
    // 以前这个页面的错误只在「tab != 0 且三个账户列表都空」时才渲染成整页 ErrorView：
    // 于是「+记一笔」被后端拒绝时（比如既没选货主也没填临时货主名），
    // **弹窗不关、界面毫无反馈**——用户以为点了没反应，再点一次还是没反应。
    // ⚠️ 这里消费的是**动作错误**（vm.error）。加载错误走 vm.loadError，
    //    它还要驱动下面那条整页 ErrorView（带重试），所以**不能**被提示条清掉 —— 见 VM 的注释。
    OneShotSnackbar(snackbar, vm.error, onConsumed = { vm.error = null })

    Scaffold(
        snackbarHost = { SnackbarHost(snackbar) },
        topBar = {
            TopAppBar(
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = MaterialTheme.colorScheme.background,
                ),
                title = { Text("账本管理", style = MaterialTheme.typography.titleLarge) },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
                    }
                },
            )
        },
    ) { padding ->
        Column(Modifier.fillMaxSize().padding(padding)) {
            LedgerTabBar(tab = vm.tab, onTab = { vm.selectTab(it) })
            AccountToolsEntry(
                onReceipts = onOpenReceipts,
                onSettlements = onOpenSettlements,
                onExpenses = onOpenExpenses,
                onVehicles = onOpenVehicles,
            )
            Box(Modifier.weight(1f)) {
                when {
                    vm.loading && vm.tab == 0 -> LoadingBox()
                    vm.accountsLoading && vm.tab != 0 -> LoadingBox()
                    vm.loadError != null && vm.tab != 0 && vm.driverAccounts.isEmpty() && vm.shipperAccounts.isEmpty() && vm.memberAccounts.isEmpty() ->
                        ErrorView(vm.loadError.orEmpty(), onRetry = { if (vm.tab == 0) vm.load() else vm.loadAccounts() })
                    else -> LazyColumn(
                        Modifier.fillMaxSize(),
                        contentPadding = PaddingValues(16.dp),
                        verticalArrangement = Arrangement.spacedBy(10.dp),
                    ) {
                        when (vm.tab) {
                            // ---- 司机账 ----
                            1 -> {
                                item { ReportTimeNav(mode = vm.chartMode, anchor = vm.chartAnchor, periodText = vm.periodText, onModeChange = { vm.applyMode(it) }, onAnchorChange = { vm.setAnchor(it) }) }
                                item {
                                    SectionCard {
                                        Text("当前范围司机运费合计", style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                                        Spacer(Modifier.height(2.dp))
                                        Text(
                                            "¥" + formatMoney(vm.driverAccounts.sumOf { it.total }.toString()),
                                            style = MaterialTheme.typography.headlineSmall,
                                            fontWeight = FontWeight.Bold,
                                            color = Color(MoneyOrange),
                                        )
                                    }
                                }
                                if (vm.driverAccounts.isEmpty()) {
                                    item { EmptyView("该时段暂无司机运费", Modifier.fillMaxWidth()) }
                                } else {
                                    items(vm.driverAccounts, key = { it.driverId }) { g ->
                                        DriverAccountCard(
                                            g = g,
                                            expanded = vm.expandedDriver == g.driverId,
                                            onToggle = { vm.toggleDriver(g.driverId) },
                                            onOpenOrder = onOpenOrder,
                                        )
                                    }
                                }
                            }

                            // ---- 货主账 ----
                            2 -> {
                                item { ReportTimeNav(mode = vm.chartMode, anchor = vm.chartAnchor, periodText = vm.periodText, onModeChange = { vm.applyMode(it) }, onAnchorChange = { vm.setAnchor(it) }) }
                                item {
                                    SectionCard {
                                        Text("当前范围货主账合计", style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                                        Spacer(Modifier.height(2.dp))
                                        Text(
                                            "¥" + formatMoney(vm.shipperAccounts.sumOf { moneyToDouble(it.total) }.toString()),
                                            style = MaterialTheme.typography.headlineSmall,
                                            fontWeight = FontWeight.Bold,
                                            color = Color(MoneyOrange),
                                        )
                                    }
                                }
                                if (vm.shipperAccounts.isEmpty()) {
                                    item { EmptyView("该时段暂无货主账目", Modifier.fillMaxWidth()) }
                                } else {
                                    items(vm.shipperAccounts, key = { it.id?.toString() + "|" + (it.tempName ?: "") }) { a ->
                                        val key = (if (a.id != null) "u|" + a.id else "t|" + a.tempName)
                                        AccountCard(
                                            a = a,
                                            key = key,
                                            expanded = vm.expandedAccount == key,
                                            entries = vm.accountEntries[key],
                                            onToggle = { vm.toggleAccount(key) },
                                            onOpenOrder = onOpenOrder,
                                            icon = Icons.Default.PeopleAlt,
                                            color = Color(ShipperTeal),
                                        )
                                    }
                                }
                            }

                            // ---- 批发商账 ----
                            3 -> {
                                item { ReportTimeNav(mode = vm.chartMode, anchor = vm.chartAnchor, periodText = vm.periodText, onModeChange = { vm.applyMode(it) }, onAnchorChange = { vm.setAnchor(it) }) }
                                item {
                                    SectionCard {
                                        Text("当前范围批发商账合计", style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                                        Spacer(Modifier.height(2.dp))
                                        Text(
                                            "¥" + formatMoney(vm.memberAccounts.sumOf { moneyToDouble(it.total) }.toString()),
                                            style = MaterialTheme.typography.headlineSmall,
                                            fontWeight = FontWeight.Bold,
                                            color = Color(MoneyOrange),
                                        )
                                    }
                                }
                                if (vm.memberAccounts.isEmpty()) {
                                    item { EmptyView("该时段暂无批发商账目", Modifier.fillMaxWidth()) }
                                } else {
                                    items(vm.memberAccounts, key = { it.id?.toString() + "|" + (it.tempName ?: "") }) { a ->
                                        val key = (if (a.id != null) "u|" + a.id else "t|" + a.tempName)
                                        AccountCard(
                                            a = a,
                                            key = key,
                                            expanded = vm.expandedAccount == key,
                                            entries = vm.accountEntries[key],
                                            onToggle = { vm.toggleAccount(key) },
                                            onOpenOrder = onOpenOrder,
                                            icon = Icons.Default.Badge,
                                            color = Color(MemberGold),
                                        )
                                    }
                                }
                            }

                            // ---- 订单账 ----
                            else -> {
                                item {
                                    ReportTimeNav(
                                        mode = vm.chartMode,
                                        anchor = vm.chartAnchor,
                                        periodText = vm.periodText,
                                        onModeChange = { vm.applyMode(it) },
                                        onAnchorChange = { vm.setAnchor(it) },
                                    )
                                }
                                item {
                                    SectionCard {
                                        Row(verticalAlignment = Alignment.CenterVertically) {
                                            Text("账单趋势", style = MaterialTheme.typography.titleMedium, modifier = Modifier.weight(1f))
                                            TextButton(onClick = { vm.chartType = if (vm.chartType == "line") "bar" else "line" }) {
                                                Text(if (vm.chartType == "line") "条形图" else "折线图")
                                            }
                                        }
                                        Spacer(Modifier.height(6.dp))
                                        val cs = vm.chartSeries
                                        if (cs.isEmpty()) {
                                            ChartEmpty("该时段暂无账单")
                                        } else {
                                            val vals = cs.map { it.second.toFloat() }
                                            val labels = cs.map { it.first.substring(5).replace("-", "/") }
                                            if (vm.chartType == "line") LineChart(vals, labels, Color(MoneyOrange))
                                            else BarChart(vals, labels, Color(MoneyOrange))
                                        }
                                    }
                                }
                                item {
                                    SectionCard {
                                        Row(verticalAlignment = Alignment.CenterVertically) {
                                            Column(Modifier.weight(1f)) {
                                                Text("当前范围内合计", style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                                                Spacer(Modifier.height(2.dp))
                                                Text(
                                                    "¥" + formatMoney(vm.total().toString()),
                                                    style = MaterialTheme.typography.headlineSmall,
                                                    fontWeight = FontWeight.Bold,
                                                    color = Color(MoneyOrange),
                                                )
                                            }
                                            Button(onClick = { vm.openCreate() }) {
                                                Icon(Icons.Default.Add, contentDescription = null, modifier = Modifier.size(18.dp))
                                                Spacer(Modifier.width(4.dp))
                                                Text("记账", style = MaterialTheme.typography.titleSmall)
                                            }
                                        }
                                    }
                                }
                                if (vm.entries.isEmpty()) {
                                    item { EmptyView("该时段暂无账目", Modifier.fillMaxWidth()) }
                                } else {
                                    items(vm.entries, key = { it.id }) { e ->
                                        LedgerRow(e, onDelete = { vm.deleteTarget = e }, onOpenOrder = onOpenOrder)
                                    }
                                }
                            }
                        }
                        item { Spacer(Modifier.height(56.dp)) }
                    }
                }
            }
        }
    }

    // 新增记账弹窗
    if (vm.showCreate) {
        AlertDialog(
            onDismissRequest = { if (!vm.acting) vm.showCreate = false },
            title = { Text("记一笔账") },
            text = {
                Column {
                    SoTextField(vm.draftShipperName, { vm.draftShipperName = it }, placeholder = "货主姓名（未注册可直接填）")
                    Spacer(Modifier.height(10.dp))
                    SoTextField(vm.draftProduct, { vm.draftProduct = it }, placeholder = "商品名称")
                    Spacer(Modifier.height(10.dp))
                    Row {
                        SoTextField(vm.draftQty, { vm.draftQty = it.filter { c -> c.isDigit() } }, placeholder = "数量", modifier = Modifier.weight(1f))
                        Spacer(Modifier.width(8.dp))
                        SoTextField(vm.draftPrice, { vm.draftPrice = it }, placeholder = "单价（元）", modifier = Modifier.weight(1f))
                    }
                    Spacer(Modifier.height(10.dp))
                    SoTextField(vm.draftDate, { vm.draftDate = it }, placeholder = "日期（如 2026-08-31）")
                    Spacer(Modifier.height(10.dp))
                    SoTextField(vm.draftNote, { vm.draftNote = it }, placeholder = "备注（选填）")
                }
            },
            confirmButton = {
                TextButton(onClick = { vm.create() }, enabled = !vm.acting) {
                    Text(if (vm.acting) "处理中…" else "保存")
                }
            },
            dismissButton = { TextButton(onClick = { vm.showCreate = false }, enabled = !vm.acting) { Text("取消") } },
        )
    }

    // 删除确认（危险操作二次确认）
    vm.deleteTarget?.let { target ->
        DangerConfirmDialog(
            title = "删除这笔账？",
            message = "删除后不可恢复：" + target.productName + " ×" + target.quantity + " ¥" + formatMoney(target.total),
            confirmText = "删除",
            onConfirm = { vm.confirmDelete() },
            onDismiss = { vm.deleteTarget = null },
        )
    }
}

/** 账本分类导航：订单账 / 司机账 / 货主账 / 批发商账 */
@Composable
private fun LedgerTabBar(tab: Int, onTab: (Int) -> Unit) {
    val tabs = listOf(
        Triple(0, "订单账", Icons.Default.AccountBalanceWallet to Color(MoneyOrange)),
        Triple(1, "司机账", Icons.Default.LocalShipping to Color(MgrGreen)),
        Triple(2, "货主账", Icons.Default.PeopleAlt to Color(ShipperTeal)),
        Triple(3, "批发商账", Icons.Default.Badge to Color(MemberGold)),
    )
    Row(
        Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        tabs.forEach { (idx, label, ic) ->
            val (icon, color) = ic
            val selected = tab == idx
            Surface(
                onClick = { onTab(idx) },
                shape = RoundedCornerShape(12.dp),
                color = if (selected) color.copy(alpha = 0.14f) else MaterialTheme.colorScheme.surface,
                border = BorderStroke(1.dp, if (selected) color.copy(alpha = 0.6f) else MaterialTheme.colorScheme.outlineVariant),
                modifier = Modifier.weight(1f).height(42.dp),
            ) {
                Row(
                    Modifier.fillMaxSize(),
                    horizontalArrangement = Arrangement.Center,
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Icon(icon, contentDescription = label, modifier = Modifier.size(16.dp), tint = if (selected) color else MaterialTheme.colorScheme.onSurfaceVariant)
                    Spacer(Modifier.width(4.dp))
                    Text(
                        label,
                        style = MaterialTheme.typography.labelMedium,
                        fontWeight = if (selected) FontWeight.Bold else FontWeight.Medium,
                        color = if (selected) color else MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
        }
    }
}

/** 司机账卡：可展开订单明细 */
@Composable
private fun DriverAccountCard(
    g: FreightSettlementGroupDto,
    expanded: Boolean,
    onToggle: () -> Unit,
    onOpenOrder: (Long) -> Unit,
) {
    SectionCard {
        Row(
            Modifier.fillMaxWidth().clickable(onClick = onToggle),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            TintedIcon(Icons.Default.LocalShipping, Color(MgrGreen), size = 16.dp, container = 32.dp)
            Spacer(Modifier.width(10.dp))
            Column(Modifier.weight(1f)) {
                Text(g.driverName.ifBlank { "司机" }, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
                Text(g.count.toString() + " 单已完成", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            Text(
                "¥" + formatMoney(g.total.toString()),
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.Bold,
                color = Color(MoneyOrange),
            )
            Spacer(Modifier.width(8.dp))
            Icon(
                if (expanded) Icons.Default.ExpandLess else Icons.Default.ExpandMore,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        if (expanded) {
            Spacer(Modifier.height(8.dp))
            HorizontalDivider()
            Spacer(Modifier.height(4.dp))
            g.orders.forEach { o ->
                Row(
                    Modifier.fillMaxWidth().clickable { onOpenOrder(o.orderId) }.padding(vertical = 8.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Icon(Icons.Default.LocalShipping, contentDescription = null, tint = Color(MgrGreen), modifier = Modifier.size(14.dp))
                    Spacer(Modifier.width(7.dp))
                    Column(Modifier.weight(1f)) {
                        Text(o.orderNo, style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.SemiBold)
                        Text(
                            listOfNotNull(o.deliveredAt?.take(16)?.replace("T", " "), o.deliveryDescription.ifBlank { null }, o.addressDetail.ifBlank { null }).joinToString(" · "),
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            maxLines = 2,
                        )
                    }
                    Spacer(Modifier.width(10.dp))
                    Text(
                        if (o.freightFee != null) "¥" + formatMoney(o.freightFee) else "待定价",
                        style = MaterialTheme.typography.bodyMedium,
                        fontWeight = FontWeight.Bold,
                        textAlign = TextAlign.End,
                        color = if (o.freightFee != null) Color(MoneyOrange) else Color(0xFF8A8A8E),
                        modifier = Modifier.widthIn(min = 92.dp),
                    )
                }
            }
        }
    }
}

/** 货主/批发商账卡：可展开流水明细 */
@Composable
private fun AccountCard(
    a: LedgerAccountOut,
    key: String,
    expanded: Boolean,
    entries: List<LedgerEntryDto>?,
    onToggle: () -> Unit,
    onOpenOrder: (Long) -> Unit,
    icon: androidx.compose.ui.graphics.vector.ImageVector,
    color: Color,
) {
    SectionCard {
        Row(
            Modifier.fillMaxWidth().clickable(onClick = onToggle),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            TintedIcon(icon, color, size = 16.dp, container = 32.dp)
            Spacer(Modifier.width(10.dp))
            Column(Modifier.weight(1f)) {
                Text(a.name.ifBlank { "货主" }, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
                Text(a.count.toString() + " 笔", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            Text(
                "¥" + formatMoney(a.total),
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.Bold,
                color = Color(MoneyOrange),
            )
            Spacer(Modifier.width(8.dp))
            Icon(
                if (expanded) Icons.Default.ExpandLess else Icons.Default.ExpandMore,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        if (expanded) {
            Spacer(Modifier.height(8.dp))
            HorizontalDivider()
            Spacer(Modifier.height(4.dp))
            if (entries == null) {
                Text("加载中…", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            } else if (entries.isEmpty()) {
                Text("该账户时段内暂无流水", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            } else {
                entries.forEach { e ->
                    Row(
                        Modifier.fillMaxWidth().clickable(enabled = e.orderId != null) { e.orderId?.let(onOpenOrder) }.padding(vertical = 6.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Icon(
                            if (e.source == "manual") Icons.Default.EditNote else Icons.Default.ReceiptLong,
                            contentDescription = null,
                            tint = if (e.source == "manual") Color(ProductPurple) else Color(0xFF1E6FFF),
                            modifier = Modifier.size(13.dp),
                        )
                        Spacer(Modifier.width(7.dp))
                        Column(Modifier.weight(1f)) {
                            Text(e.productName + " ×" + e.quantity, style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.Medium)
                            Text(
                                listOfNotNull(e.entryDate, e.orderNo?.let { "#" + it }, e.note.ifBlank { null }).joinToString(" · "),
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                                maxLines = 1,
                            )
                        }
                        Spacer(Modifier.width(10.dp))
                        Text(
                            "¥" + formatMoney(e.total),
                            style = MaterialTheme.typography.bodyMedium,
                            fontWeight = FontWeight.Bold,
                            textAlign = TextAlign.End,
                            color = Color(MoneyOrange),
                            modifier = Modifier.widthIn(min = 92.dp),
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun LedgerRow(e: LedgerEntryDto, onDelete: () -> Unit, onOpenOrder: (Long) -> Unit) {
    SectionCard {
        Row(
            Modifier.fillMaxWidth().clickable(enabled = e.orderId != null) { e.orderId?.let(onOpenOrder) },
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Icon(
                if (e.source == "manual") Icons.Default.EditNote else Icons.Default.ReceiptLong,
                contentDescription = null,
                tint = if (e.source == "manual") Color(ProductPurple) else Color(0xFF1E6FFF),
                modifier = Modifier.size(15.dp),
            )
            Spacer(Modifier.width(8.dp))
            Column(Modifier.weight(1f)) {
                Text(
                    (e.tempShipperName ?: "临时货主").ifBlank { "临时货主" },
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.Bold,
                )
                Spacer(Modifier.height(2.dp))
                Text(
                    listOfNotNull(e.productName + " ×" + e.quantity, e.entryDate, e.orderNo?.let { "#" + it }).joinToString(" · "),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 1,
                )
                if (e.note.isNotBlank()) {
                    Text(e.note, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.outline, maxLines = 1)
                }
            }
            Spacer(Modifier.width(10.dp))
            Text(
                "¥" + formatMoney(e.total),
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.Bold,
                textAlign = TextAlign.End,
                color = Color(MoneyOrange),
                modifier = Modifier.widthIn(min = 92.dp),
            )
            IconButton(onClick = onDelete) {
                Icon(Icons.Default.DeleteOutline, contentDescription = "删除", tint = MaterialTheme.colorScheme.error)
            }
        }
    }
}

/** 账本工具入口行：客户收款 / 司机结算 / 开销管理 / 车辆台账（四账页签之外的新增工具） */
@Composable
private fun AccountToolsEntry(
    onReceipts: () -> Unit,
    onSettlements: () -> Unit,
    onExpenses: () -> Unit,
    onVehicles: () -> Unit,
) {
    Row(
        Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 4.dp),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        ToolChip(Icons.Default.Payments, "客户收款", MoneyOrange, onReceipts)
        ToolChip(Icons.Default.Handshake, "司机结算", MgrGreen, onSettlements)
        ToolChip(Icons.Default.Receipt, "开销管理", 0xFF00A2C7, onExpenses)
        ToolChip(Icons.Default.LocalShipping, "车辆台账", 0xFF6950F5, onVehicles)
    }
}

@Composable
private fun androidx.compose.foundation.layout.RowScope.ToolChip(icon: androidx.compose.ui.graphics.vector.ImageVector, label: String, color: Long, onClick: () -> Unit) {
    Surface(
        onClick = onClick,
        shape = RoundedCornerShape(10.dp),
        color = MaterialTheme.colorScheme.surface,
        border = BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant),
        modifier = Modifier.weight(1f).height(52.dp),
    ) {
        Column(horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.Center) {
            Icon(icon, contentDescription = null, tint = androidx.compose.ui.graphics.Color(color), modifier = Modifier.size(20.dp))
            Spacer(Modifier.height(2.dp))
            Text(label, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}