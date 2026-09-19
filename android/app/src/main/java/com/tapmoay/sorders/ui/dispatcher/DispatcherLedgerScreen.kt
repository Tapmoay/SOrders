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
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.core.InputRules
import androidx.compose.ui.text.input.KeyboardType
import com.tapmoay.sorders.data.remote.dto.FreightSettlementGroupDto
import com.tapmoay.sorders.data.remote.dto.LedgerAccountOut
import com.tapmoay.sorders.data.remote.dto.LedgerEntryDto
import com.tapmoay.sorders.data.repo.PageMeta
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
                            // ---- 司机账（与货主账/批发商账**同一套**：搜索 + 多选 + 就地展开订单）----
                            1 -> {
                                val visible = vm.driversForTab()
                                item { ReportTimeNav(mode = vm.chartMode, anchor = vm.chartAnchor, periodText = vm.periodText, onModeChange = { vm.applyMode(it) }, onAnchorChange = { vm.setAnchor(it) }) }
                                item {
                                    DriverPicker(
                                        drivers = visible,
                                        selected = vm.selectedDrivers,
                                        query = vm.driverQuery,
                                        onQuery = { vm.driverQuery = it },
                                        onToggle = { vm.toggleDriverSelected(it) },
                                        onClear = { vm.clearDriverSelection() },
                                    )
                                }
                                item { DriverSelectedSummary(vm) }
                                when {
                                    vm.driverAccounts.isEmpty() ->
                                        item { EmptyView("该时段暂无司机运费", Modifier.fillMaxWidth()) }
                                    visible.isEmpty() ->
                                        item {
                                            EmptyView(
                                                "没有名字含「" + vm.driverQuery.trim() + "」的司机",
                                                Modifier.fillMaxWidth(),
                                            )
                                        }
                                    else -> items(visible, key = { it.driverId }) { g ->
                                        DriverAccountCard(
                                            g = g,
                                            expanded = vm.expandedDriver == g.driverId,
                                            onToggle = { vm.toggleDriver(g.driverId) },
                                            onOpenOrder = onOpenOrder,
                                            expandedOrderId = vm.expandedOrderId,
                                            expandedOrder = vm.expandedOrder,
                                            orderLoading = vm.expandedOrderLoading,
                                            onToggleOrder = { vm.toggleOrderDetail(it) },
                                        )
                                    }
                                }
                            }

                            // ---- 货主账 / 批发商账（**同一套版式，一份实现**）----
                            //
                            // 用户 2026-09-19：「批发商他只能看到合计的，但如果我想看**单个**的呢？
                            // 或者我想看 **2 个**人的呢？这要有个**自由选择**，而且页面也非常的反人性」。
                            // 两栏原来是两段几乎一样的代码（各写一遍 = 改一处漏一处），现在合成一支。
                            2, 3 -> {
                                val isMember = vm.tab == 3
                                val label = if (isMember) "批发商" else "货主"
                                val color = if (isMember) Color(MemberGold) else Color(ShipperTeal)
                                val visible = vm.accountsForTab()
                                item { ReportTimeNav(mode = vm.chartMode, anchor = vm.chartAnchor, periodText = vm.periodText, onModeChange = { vm.applyMode(it) }, onAnchorChange = { vm.setAnchor(it) }) }
                                item {
                                    AccountPicker(
                                        label = label,
                                        accounts = visible,
                                        keyOf = { vm.accountKey(it) },
                                        selected = vm.selectedAccounts,
                                        query = vm.accountQuery,
                                        onQuery = { vm.accountQuery = it },
                                        onToggle = { vm.toggleAccountSelected(it) },
                                        onClear = { vm.clearAccountSelection() },
                                        color = color,
                                    )
                                }
                                item { SelectedSummary(vm) }
                                when {
                                    (if (isMember) vm.memberAccounts else vm.shipperAccounts).isEmpty() ->
                                        item { EmptyView("该时段暂无" + label + "账目", Modifier.fillMaxWidth()) }
                                    visible.isEmpty() ->
                                        item {
                                            EmptyView(
                                                "没有名字含「" + vm.accountQuery.trim() + "」的" + label,
                                                Modifier.fillMaxWidth(),
                                            )
                                        }
                                    else -> items(visible, key = { vm.accountKey(it) }) { a ->
                                        val key = vm.accountKey(a)
                                        AccountCard(
                                            a = a,
                                            key = key,
                                            expanded = vm.expandedAccount == key,
                                            entries = vm.accountEntries[key],
                                            meta = vm.accountEntriesMeta[key],
                                            onToggle = { vm.toggleAccount(key) },
                                            expandedOrderId = vm.expandedOrderId,
                                            expandedOrder = vm.expandedOrder,
                                            orderLoading = vm.expandedOrderLoading,
                                            onToggleOrder = { vm.toggleOrderDetail(it) },
                                            onOpenOrder = onOpenOrder,
                                            icon = if (isMember) Icons.Default.Storefront else Icons.Default.PeopleAlt,
                                            color = color,
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
                                    // 服务端只回了一页时**说出来**（判据是响应头 `X-Truncated`，
                                    // 见 DispatcherLedgerViewModel）。⚠️ 上面那两张卡（趋势/合计）
                                    // 是拿这一页在客户端算的 —— 不说的话"当前范围内合计"会被
                                    // 当成整段总额，而它其实只含看得见的这些行。
                                    if (vm.entriesTruncated) {
                                        item {
                                            TruncationNote(
                                                vm.entriesLimit,
                                                "更早的请用上方时间导航缩小范围；上面的合计与趋势只含已取到的这些行",
                                            )
                                        }
                                    }
                                    items(vm.entries, key = { it.id }) { e ->
                                        LedgerRow(
                                            e = e,
                                            onDelete = { vm.deleteTarget = e },
                                            onOpenOrder = onOpenOrder,
                                            expandedOrderId = vm.expandedOrderId,
                                            expandedOrder = vm.expandedOrder,
                                            orderLoading = vm.expandedOrderLoading,
                                            onToggleOrder = { vm.toggleOrderDetail(it) },
                                        )
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
                        SoTextField(vm.draftQty, { vm.draftQty = InputRules.intInput(it, 6) }, placeholder = "数量", keyboardType = KeyboardType.Number, modifier = Modifier.weight(1f))
                        Spacer(Modifier.width(8.dp))
                        SoTextField(vm.draftPrice, { vm.draftPrice = InputRules.priceInput(it) }, placeholder = "单价（元）", keyboardType = KeyboardType.Decimal, modifier = Modifier.weight(1f))
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
    /** 就地展开那一单（与货主账/批发商账**同一套**：用户说「其他其他的都一样」）。 */
    expandedOrderId: Long? = null,
    expandedOrder: com.tapmoay.sorders.data.remote.dto.OrderDto? = null,
    orderLoading: Boolean = false,
    onToggleOrder: (Long) -> Unit = {},
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
                    // 与账本其余各处一致：点一下**就地展开那一单**，不是跳走
                    Modifier.fillMaxWidth().clickable { onToggleOrder(o.orderId) }.padding(vertical = 8.dp),
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
                if (o.orderId == expandedOrderId) {
                    OrderPeek(loading = orderLoading, order = expandedOrder, onOpenFull = { onOpenOrder(o.orderId) })
                }
            }
        }
    }
}

/**
 * 司机挑选器：与 [AccountPicker] **同一套交互**（搜索 + 多选 + 一键清空 + 那句"不选=全部"）。
 *
 * 为什么单独写一个而不是复用 [AccountPicker]：两者的数据类型不同
 * （`FreightSettlementGroupDto.driverId/driverName` vs `LedgerAccountOut.id/name`）。
 * 硬套的话要给 [AccountPicker] 加一层"取值适配器"，那层适配器比这 40 行更容易写错。
 * ⚠️ **但交互规则必须一致**（不选=全部、可点掉、清空、写明当前含义）——
 *    两处不一致才是真正的"反人性"。
 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun DriverPicker(
    drivers: List<FreightSettlementGroupDto>,
    selected: Set<Long>,
    query: String,
    onQuery: (String) -> Unit,
    onToggle: (Long) -> Unit,
    onClear: () -> Unit,
) {
    SectionCard {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("选司机", style = MaterialTheme.typography.titleMedium, modifier = Modifier.weight(1f))
            if (selected.isNotEmpty()) {
                TextButton(onClick = onClear) { Text("清空选择") }
            }
        }
        OutlinedTextField(
            value = query,
            onValueChange = onQuery,
            placeholder = { Text("搜索司机名字", style = MaterialTheme.typography.bodySmall) },
            leadingIcon = { Icon(Icons.Default.Search, contentDescription = null, modifier = Modifier.size(20.dp)) },
            singleLine = true,
            textStyle = MaterialTheme.typography.bodyMedium,
            modifier = Modifier.fillMaxWidth(),
        )
        Spacer(Modifier.height(8.dp))
        if (drivers.isEmpty()) {
            Text("没有匹配的司机", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        } else {
            FlowRow(
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                drivers.forEach { g ->
                    val on = g.driverId in selected
                    Surface(
                        color = if (on) Color(MgrGreen).copy(alpha = 0.18f) else MaterialTheme.colorScheme.surfaceVariant,
                        shape = MaterialTheme.shapes.small,
                        modifier = Modifier.clickable { onToggle(g.driverId) },
                    ) {
                        Row(
                            Modifier.padding(horizontal = 10.dp, vertical = 6.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            if (on) {
                                Icon(Icons.Default.Check, contentDescription = null, tint = Color(MgrGreen), modifier = Modifier.size(14.dp))
                                Spacer(Modifier.width(4.dp))
                            }
                            Text(
                                g.driverName,
                                style = MaterialTheme.typography.labelLarge,
                                fontWeight = if (on) FontWeight.Bold else FontWeight.Normal,
                                color = if (on) Color(MgrGreen) else MaterialTheme.colorScheme.onSurfaceVariant,
                                maxLines = 1,
                            )
                            Spacer(Modifier.width(6.dp))
                            Text(
                                "¥" + formatMoney(g.total.toString()),
                                style = MaterialTheme.typography.labelSmall,
                                color = if (on) Color(MgrGreen) else MaterialTheme.colorScheme.outline,
                            )
                        }
                    }
                }
            }
        }
        Spacer(Modifier.height(6.dp))
        Text(
            if (selected.isEmpty()) "一个都不选 = 全部（共 " + drivers.size + " 位）"
            else "已选 " + selected.size + " 位，下面只显示这几位；再点一下可以取消",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

/** 选中司机的合计（钱 + 单数 + 人数）。 */
@Composable
private fun DriverSelectedSummary(vm: DispatcherLedgerViewModel) {
    val (money, orders, n) = vm.driverSelectedSummary()
    SectionCard {
        Text(
            if (vm.selectedDrivers.isEmpty()) "当前范围全部司机运费合计" else "已选 " + n + " 位司机合计",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Spacer(Modifier.height(2.dp))
        Row(verticalAlignment = Alignment.Bottom) {
            Text(
                "¥" + formatMoney(money.toString()),
                style = MaterialTheme.typography.headlineSmall,
                fontWeight = FontWeight.Bold,
                color = Color(MoneyOrange),
            )
            Spacer(Modifier.width(10.dp))
            Text(
                orders.toString() + " 单",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(bottom = 3.dp),
            )
        }
    }
}

/**
 * 账户挑选器：**搜索 + 多选**（用户 2026-09-19 要的"自由选择"）。
 *
 * 原话：「批发商他只能看到合计的，但如果我想看**单个**的呢？或者我想看 **2 个**人的呢？
 * 这要有个**自由选择**，而且页面也非常的反人性」。
 *
 * 三条设计：
 * 1. **一个都不选 = 全部**（默认行为不变）—— 不逼用户先做一次选择才能看账；
 * 2. 选中态是**可点掉的**（再点一下取消），并且有一键「清空」—— 选错了不用一个个找回来；
 * 3. 下面那句「一个都不选 = 全部（共 N 个）」是**必需**的：多选控件最常见的困惑就是
 *    "我什么都没点，那现在显示的是全部还是什么都没有？"——不写清就是个猜谜。
 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun AccountPicker(
    label: String,
    accounts: List<LedgerAccountOut>,
    keyOf: (LedgerAccountOut) -> String,
    selected: Set<String>,
    query: String,
    onQuery: (String) -> Unit,
    onToggle: (String) -> Unit,
    onClear: () -> Unit,
    color: Color,
) {
    SectionCard {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("选$label", style = MaterialTheme.typography.titleMedium, modifier = Modifier.weight(1f))
            if (selected.isNotEmpty()) {
                TextButton(onClick = onClear) { Text("清空选择") }
            }
        }
        OutlinedTextField(
            value = query,
            onValueChange = onQuery,
            placeholder = { Text("搜索$label 名字", style = MaterialTheme.typography.bodySmall) },
            leadingIcon = { Icon(Icons.Default.Search, contentDescription = null, modifier = Modifier.size(20.dp)) },
            singleLine = true,
            textStyle = MaterialTheme.typography.bodyMedium,
            modifier = Modifier.fillMaxWidth(),
        )
        Spacer(Modifier.height(8.dp))
        if (accounts.isEmpty()) {
            Text(
                "没有匹配的$label",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        } else {
            // FlowRow：账户名长短不一，用 Row 会挤成一条、用 Column 会占掉半屏（设计规范 §5）
            FlowRow(
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                accounts.forEach { a ->
                    val k = keyOf(a)
                    val on = k in selected
                    Surface(
                        color = if (on) color.copy(alpha = 0.18f) else MaterialTheme.colorScheme.surfaceVariant,
                        shape = MaterialTheme.shapes.small,
                        modifier = Modifier.clickable { onToggle(k) },
                    ) {
                        Row(
                            Modifier.padding(horizontal = 10.dp, vertical = 6.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            if (on) {
                                Icon(Icons.Default.Check, contentDescription = null, tint = color, modifier = Modifier.size(14.dp))
                                Spacer(Modifier.width(4.dp))
                            }
                            Text(
                                a.name.ifBlank { label },
                                style = MaterialTheme.typography.labelLarge,
                                fontWeight = if (on) FontWeight.Bold else FontWeight.Normal,
                                color = if (on) color else MaterialTheme.colorScheme.onSurfaceVariant,
                                maxLines = 1,
                            )
                            Spacer(Modifier.width(6.dp))
                            Text(
                                "¥" + formatMoney(a.total),
                                style = MaterialTheme.typography.labelSmall,
                                color = if (on) color else MaterialTheme.colorScheme.outline,
                            )
                        }
                    }
                }
            }
        }
        Spacer(Modifier.height(6.dp))
        Text(
            if (selected.isEmpty()) "一个都不选 = 全部（共 " + accounts.size + " 个）"
            else "已选 " + selected.size + " 个，下面只显示这几个；再点一下可以取消",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

/**
 * 选中账户的**合计**。
 *
 * ⚠️ 为什么必须单独有这一行：原来每个账户各自一个数，要看"这几家一共多少钱"得自己心算相加 ——
 * 用户说的"反人性"就包括这一条。笔数取**服务端**的 `count`（全量），不是本地明细行数（那是分页的）。
 */
@Composable
private fun SelectedSummary(vm: DispatcherLedgerViewModel) {
    val (money, count) = vm.selectedSummary()
    SectionCard {
        Text(
            if (vm.selectedAccounts.isEmpty()) "当前范围全部账户合计" else "已选 " + vm.selectedAccounts.size + " 个账户合计",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Spacer(Modifier.height(2.dp))
        Row(verticalAlignment = Alignment.Bottom) {
            Text(
                "¥" + formatMoney(money.toString()),
                style = MaterialTheme.typography.headlineSmall,
                fontWeight = FontWeight.Bold,
                color = Color(MoneyOrange),
            )
            Spacer(Modifier.width(10.dp))
            Text(
                count.toString() + " 笔",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(bottom = 3.dp),
            )
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
    /** 这一账户的明细被服务端截断了没有 + 本次上限（判据是响应头，见 DispatcherLedgerViewModel）。 */
    meta: PageMeta?,
    onToggle: () -> Unit,
    /** 就地展开的订单（用户要求"订单是可以展开进行查看的"）：当前展开的是哪一条 + 它的内容。 */
    expandedOrderId: Long?,
    expandedOrder: com.tapmoay.sorders.data.remote.dto.OrderDto?,
    orderLoading: Boolean,
    onToggleOrder: (Long) -> Unit,
    /** 仍然保留"跳到订单详情页"这条路（就地展开不替代它）。 */
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
                // 明细被截断时**说出来**：卡上那行"N 笔"是**服务端**的全量笔数，
                // 而这里列出的可能只有一页 —— 不说的话"卡上 5000 笔、展开 1000 条"
                // 会被当成数据不一致（或干脆以为账丢了）。
                if (meta?.hasMore == true) {
                    TruncationNote(
                        meta.limit,
                        "该账户在此范围内的流水没列全（卡上的笔数是服务端全量），更早的请用上方时间导航缩小范围",
                        modifier = Modifier.padding(bottom = 4.dp),
                    )
                }
                entries.forEach { e ->
                    // ⚠️ 这一行点下去是**就地展开那一单**，不是跳走（用户 2026-09-19 的要求）。
                    //    跳走再回来，筛选/展开的账户/滚动位置全没了 —— 连着核几笔要来回跳十几趟。
                    val oid = e.orderId
                    Row(
                        Modifier
                            .fillMaxWidth()
                            .clickable(enabled = oid != null) { oid?.let(onToggleOrder) }
                            .padding(vertical = 6.dp),
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
                    // 展开了就把它那一单摊在流水行下面（"订单是可以展开进行查看的"）
                    if (oid != null && oid == expandedOrderId) {
                        OrderPeek(
                            loading = orderLoading,
                            order = expandedOrder,
                            onOpenFull = { onOpenOrder(oid) },
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun LedgerRow(
    e: LedgerEntryDto,
    onDelete: () -> Unit,
    onOpenOrder: (Long) -> Unit,
    /** 就地展开那一单（与货主账/批发商账**同一套**，用户说「其他其他的都一样」）。 */
    expandedOrderId: Long?,
    expandedOrder: com.tapmoay.sorders.data.remote.dto.OrderDto?,
    orderLoading: Boolean,
    onToggleOrder: (Long) -> Unit,
) {
    val oid = e.orderId
    SectionCard {
        Row(
            Modifier.fillMaxWidth().clickable(enabled = oid != null) { oid?.let(onToggleOrder) },
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
                    // ⚠️ 这里原来是 `e.tempShipperName ?: "临时货主"` —— 而**注册货主**的
                    //    `tempShipperName` 本来就是 null，于是满屏都是「临时货主」，
                    //    根本看不出这一笔是谁的（2026-09-19 后端补了 `shipper_name`）。
                    //    兜底顺序必须与后端一致：真名 → 临时货主称呼 → 「未命名」。
                    e.shipperName?.ifBlank { null }
                        ?: e.tempShipperName?.ifBlank { null }
                        ?: "未命名",
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
        if (oid != null && oid == expandedOrderId) {
            OrderPeek(loading = orderLoading, order = expandedOrder, onOpenFull = { onOpenOrder(oid) })
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