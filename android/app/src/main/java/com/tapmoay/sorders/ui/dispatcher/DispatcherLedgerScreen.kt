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
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.core.InputRules
import com.tapmoay.sorders.core.UserSearch
import androidx.compose.ui.text.input.KeyboardType
import com.tapmoay.sorders.data.remote.dto.FreightSettlementOrderDto
import com.tapmoay.sorders.data.remote.dto.LedgerEntryDto
import com.tapmoay.sorders.data.remote.dto.OrderDto
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
                            // ---- 司机账 / 货主账 / 批发商账：**一套仪表盘，一份实现** ----
                            //
                            // 用户 2026-09-19：「**所有的账本你可以一个仪表盘的思维进行去构建**」
                            // （这句推翻了他上一轮要的"搜索 + 多选"，理由见 ViewModel 顶部那段）。
                            // 三类账原来各有一张卡 + 一个挑选器（改一处漏一处），现在合成一支：
                            // 仪表盘（账户数/笔数/金额，跟着搜索走）+ 一个搜索框 + 可展开的账户行。
                            1, 2, 3 -> {
                                val isMember = vm.tab == 3
                                val isDriver = vm.tab == 1
                                val label = when (vm.tab) {
                                    1 -> "司机"
                                    3 -> "批发商"
                                    else -> "货主"
                                }
                                val color = when (vm.tab) {
                                    1 -> Color(MgrGreen)
                                    3 -> Color(MemberGold)
                                    else -> Color(ShipperTeal)
                                }
                                val icon = when (vm.tab) {
                                    1 -> Icons.Default.LocalShipping
                                    3 -> Icons.Default.Storefront
                                    else -> Icons.Default.PeopleAlt
                                }
                                val all = vm.accountRows()
                                val visible = vm.visibleAccountRows()
                                item { ReportTimeNav(mode = vm.chartMode, anchor = vm.chartAnchor, periodText = vm.periodText, onModeChange = { vm.applyMode(it) }, onAnchorChange = { vm.setAnchor(it) }) }
                                item { LedgerDashboardCard(vm, label = label, color = color) }
                                when {
                                    all.isEmpty() ->
                                        item { EmptyView("该时段暂无" + label + "账目", Modifier.fillMaxWidth()) }
                                    visible.isEmpty() ->
                                        item {
                                            EmptyView(
                                                UserSearch.noMatchText(vm.query) + label + "账户",
                                                Modifier.fillMaxWidth(),
                                            )
                                        }
                                    else -> items(visible, key = { it.key }) { r ->
                                        LedgerAccountRowCard(
                                            row = r,
                                            blankLabel = label,
                                            expanded = vm.expandedKey == r.key,
                                            onToggle = { vm.toggleRow(r.key) },
                                            icon = icon,
                                            color = color,
                                        ) {
                                            // 展开块：司机账的明细**已经在列表响应里**（group.orders），
                                            // 货主/批发商的流水是另取的 —— 两件事，两种内容，各自渲染。
                                            if (isDriver) {
                                                DriverOrderLines(
                                                    orders = vm.driverOrdersOf(r.key),
                                                    expandedOrderId = vm.expandedOrderId,
                                                    expandedOrder = vm.expandedOrder,
                                                    orderLoading = vm.expandedOrderLoading,
                                                    onToggleOrder = { vm.toggleOrderDetail(it) },
                                                    onOpenOrder = onOpenOrder,
                                                )
                                            } else {
                                                AccountEntryLines(
                                                    entries = vm.accountEntries[r.key],
                                                    meta = vm.accountEntriesMeta[r.key],
                                                    loading = vm.accountEntriesLoading,
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
                                                // 与另外三类账**同一个 KPI 版式**（仪表盘思维：钱单独一行）
                                                KpiBlock(
                                                    label = "订单账合计（当前时间范围）",
                                                    total = vm.total(),
                                                    stats = "共 " + vm.entries.size + " 笔流水" +
                                                        if (vm.entriesTruncated) "（只含已取到的）" else "",
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

// ============================================================ 账本仪表盘
//
// 用户 2026-09-19 第二次拍板：「**所有的账本你可以一个仪表盘的思维进行去构建**」——
// 这句推翻了上一版的「搜索 + 多选 chip 墙」。两个理由记在这里，免得下一轮又有人把它加回来：
//   ① chip 墙上写的"名字 + 金额"与下面列表里的**是同一份信息**，重复放在两处，
//      就一定会出现"两边对不上"的困惑；
//   ② 账户一多，"在一堆 chip 里找到要点的那几个"比看账本身更花时间 —— 这正是他说的「麻烦」。
//
// 现在：一屏看完所有账户各自的数（下面第一张卡就是仪表盘），一个搜索框把范围收窄，
// **收窄之后的合计写在仪表盘上**（"这两家一共多少"这么看，不用勾选），点账户行就地展开流水。

/**
 * 仪表盘上那三个数（**钱单独一行**，账户数/笔数是在解释它，用弱化的小字跟在下面）。
 *
 * 「一个数字一行」是本项目的既有约定（商品卡上售价与库存分行）；这里钱的数字最大最粗、
 * 独占一行，另外两个数合成一句 —— 而不是把三个数并排堆成一行小字（那既不突出钱，
 * 也看不出哪个数是解释哪个的）。
 */
@Composable
private fun KpiBlock(label: String, total: Double, stats: String, hint: String? = null) {
    Text(label, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
    Spacer(Modifier.height(2.dp))
    Text(
        "¥" + formatMoney(total.toString()),
        style = MaterialTheme.typography.headlineSmall,
        fontWeight = FontWeight.Bold,
        color = Color(MoneyOrange),
    )
    Spacer(Modifier.height(2.dp))
    Text(stats, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
    if (hint != null) {
        Text(hint, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.outline)
    }
}

/**
 * 账户仪表盘：合计（跟着搜索走）+ 搜索框。
 *
 * ⚠️ 搜索是**本地**过滤：`/ledger/accounts` 与 `/freight-settlement` 都是一次回全量
 *    （没有分页、也没有 500 上限），再走服务端只是每次打字多打一次后端。
 *    名册页（`/users` 一页最多 500 条）就**必须**走服务端 `?q=`，见 `UsersManageViewModel`。
 */
@Composable
private fun LedgerDashboardCard(
    vm: DispatcherLedgerViewModel,
    label: String,
    color: Color,
) {
    val d = vm.dashboard()
    val all = vm.accountRows()
    val searching = vm.query.isNotBlank()
    SectionCard {
        KpiBlock(
            label = if (searching) "按「" + vm.query.trim() + "」筛出的合计" else label + "账合计（当前时间范围）",
            total = d.total,
            stats = d.accounts.toString() + " 个账户 · 共 " + d.count + " 笔",
            // 过滤时把"全部是多少"一起说出来：不说的话用户会拿筛出的那个数当总额去对账
            hint = if (searching) {
                "全部 " + all.size + " 个" + label + "账户合计 ¥" +
                    formatMoney(all.sumOf { it.total }.toString()) + "（清空搜索可看全部）"
            } else null,
        )
        Spacer(Modifier.height(12.dp))
        SearchField(value = vm.query, onValueChange = { vm.query = it })
    }
}

/**
 * 一个账户一行 —— 司机账 / 货主账 / 批发商账**同一个版式、同一份实现**。
 *
 * 名字下面那行是**手机号 + 笔数**：
 * · 手机号是**同名不同人**唯一的分辨依据（两个「张老板」以前是两行一模一样的卡，
 *   只能靠金额猜谁是谁），也是用户 2026-09-19 要的搜索键之一；
 * · 没号的（临时货主）要说清"为什么没有"，不能留一行空白让人以为是加载失败。
 *
 * [expand] 是展开块的内容插槽：司机账展开的是**响应里已经带着的**订单明细，
 * 货主/批发商账展开的是**另取的**流水 —— 两件事，两种内容，共用这一个外壳。
 */
@Composable
private fun LedgerAccountRowCard(
    row: LedgerAccountRow,
    blankLabel: String,
    expanded: Boolean,
    onToggle: () -> Unit,
    icon: ImageVector,
    color: Color,
    expand: @Composable () -> Unit,
) {
    SectionCard {
        Row(
            Modifier.fillMaxWidth().clickable(onClick = onToggle),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            TintedIcon(icon, color, size = 16.dp, container = 32.dp)
            Spacer(Modifier.width(10.dp))
            Column(Modifier.weight(1f)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        row.title.ifBlank { "未命名" + blankLabel },
                        style = MaterialTheme.typography.titleMedium,
                        fontWeight = FontWeight.Bold,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                    if (row.inactive) {
                        Spacer(Modifier.width(6.dp))
                        Surface(color = MaterialTheme.colorScheme.surfaceVariant, shape = MaterialTheme.shapes.small) {
                            Text(
                                "已停用",
                                style = MaterialTheme.typography.labelSmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                                modifier = Modifier.padding(horizontal = 6.dp, vertical = 1.dp),
                            )
                        }
                    }
                }
                Text(
                    listOf(
                        row.phone?.ifBlank { null } ?: "未注册账号",
                        row.count.toString() + " " + row.countUnit,
                    ).joinToString(" · "),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 1,
                )
            }
            Spacer(Modifier.width(10.dp))
            Text(
                "¥" + formatMoney(row.total.toString()),
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
            expand()
        }
    }
}

/**
 * 司机账展开：他在这段时间里完成的单。
 *
 * ⚠️ 明细**已经跟在结算响应里**（`group.orders`），所以这里不请求、也没有"加载中"这一态 ——
 *    而货主账那边要另取一次（见 [AccountEntryLines]），两种情形不能共用一句状态文案。
 */
@Composable
private fun DriverOrderLines(
    orders: List<FreightSettlementOrderDto>,
    expandedOrderId: Long?,
    expandedOrder: OrderDto?,
    orderLoading: Boolean,
    onToggleOrder: (Long) -> Unit,
    onOpenOrder: (Long) -> Unit,
) {
    if (orders.isEmpty()) {
        Text(
            "这一段时间里没有他的单",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        return
    }
    orders.forEach { o ->
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

/**
 * 货主/批发商账展开：这个账户在这一段里的流水（**另取**，取过就缓存）。
 *
 * 一行点下去是**就地展开那一单**（用户 2026-09-19：「订单是可以展开进行查看的」）——
 * 原来是跳到订单详情页，回来之后筛选/展开/滚动位置全没了，连着核几笔要来回跳十几趟。
 * 「打开订单」那条路仍然留着（展开块右上角），看照片/导航/司机备注还得进详情页。
 */
@Composable
private fun AccountEntryLines(
    entries: List<LedgerEntryDto>?,
    /** 这一账户的明细被服务端截断了没有 + 本次上限（判据是响应头，见 DispatcherLedgerViewModel）。 */
    meta: PageMeta?,
    loading: Boolean,
    onOpenOrder: (Long) -> Unit,
    expandedOrderId: Long?,
    expandedOrder: OrderDto?,
    orderLoading: Boolean,
    onToggleOrder: (Long) -> Unit,
) {
    if (entries == null) {
        Text(
            if (loading) "加载中…" else "还没取到流水，收起再展开试试",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        return
    }
    if (entries.isEmpty()) {
        Text(
            "该账户时段内暂无流水",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        return
    }
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
