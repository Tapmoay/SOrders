package com.tapmoay.sorders.ui.shipper

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
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
import com.tapmoay.sorders.data.remote.dto.LedgerEntryDto
import com.tapmoay.sorders.data.remote.dto.OrderDto
import com.tapmoay.sorders.data.remote.dto.OrderProductDto
import androidx.compose.material3.ModalDrawerSheet
import androidx.compose.material3.ModalNavigationDrawer
import androidx.compose.material3.DrawerValue
import androidx.compose.material3.rememberDrawerState
import androidx.compose.runtime.rememberCoroutineScope
import kotlinx.coroutines.launch
import com.tapmoay.sorders.util.formatDateCN
import com.tapmoay.sorders.ui.common.*
import com.tapmoay.sorders.ui.dispatcher.centsToMoney
import com.tapmoay.sorders.ui.theme.MoneyOrange
import com.tapmoay.sorders.util.formatDateTime
import com.tapmoay.sorders.util.formatMoney
import com.tapmoay.sorders.ui.common.Hint

/**
 * 货主账本（**以订单为基础**，2026-09-20 用户第四轮口述）。
 *
 * ## 一段话看懂这一页
 * · 顶上**搜索框**：批发商搜**联系人（他的货主）**，普通货主搜**订单**；
 * · 右上角**一个时间药丸**（今天/昨天/前天/这周/近 7 天/上周/本月/上月/近一年/自定义）
 *   → 按**送达日**筛；点开是档位清单，**当前窗口永远看得见**；
 * · 一张**合计卡**：`我欠总分销商 ¥X`；
 * · **批发商货主**再多一段：`我的货主欠我多少` —— 先**联系人总计**、再**他名下的订单明细**，
 *   每单可以**核销**（不勾商品=整单；勾了=按商品核销），已经核销的可以**撤销**（软删，可恢复）；
 * · **普通货主**只有订单列表（点进详情）—— 他给自己下单，**没有核销**。
 *
 * ⛔ 两本账不许串：批发商那本核销只影响"我的货主欠我"，**永远不会让"我欠总分销商"变小**
 *   （后端 `shipper-ledger` 一个字节都不写 `orders.paid` / `cash_flows` / `ledgers`）。
 *
 * ## 两个视图、**一个**时间窗口（2026-09-20 22:5x 用户第三次点名后定稿）
 * 顶栏 `ReceiptLong` 图标切进「账目流水」（手动记账 / 货损红冲那些行的入口）时：
 * · 顶栏那颗**药丸不消失**（原来有一道 `if (!vm.showFlow)` 把它藏了）；
 * · 流水页面里**也没有**横滑的胶囊行（原来有一条 `DatePresetRow`，被用户点名否掉：
 *   「他还是那个滑动型的」）；
 * · 两个视图共用同一个 `rangeFrom/rangeTo`（换档 → `reloadWindow()` 两边一起重取）。
 *   口径依据：账本行的 `entry_date` 本来就等于**订单送达日**（`services/ledger_sync.py:27`），
 *   共用一个窗口不会让任何一边少算；反倒是"同一页两个视图各看一段时间"会让合计对不上。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ShipperLedgerScreen(
    container: AppContainer,
    onBack: () -> Unit,
    onOpenOrder: (Long) -> Unit = {},
) {
    val vm: ShipperLedgerViewModel = appViewModel { ShipperLedgerViewModel(container) }
    val snackbar = remember { SnackbarHostState() }
    // 两个弹层：档位清单（选哪一档）与自定义日期（选完区间）—— 都画在 Scaffold **外面**
    // （声明在它的 content 里就出了作用域）
    var showDatePresets by remember { mutableStateOf(false) }
    // 侧边抽屉：**只给批发商**（他才有"人"可挑；普通货主连手势都不开）
    val drawer = rememberDrawerState(DrawerValue.Closed)
    val scope = rememberCoroutineScope()

    OneShotSnackbar(snackbar, vm.actionResult, onConsumed = { vm.actionResult = null })

    ModalNavigationDrawer(
        drawerState = drawer,
        gesturesEnabled = vm.isMember && !vm.showFlow,
        drawerContent = {
            ModalDrawerSheet {
                CustomerDrawer(
                    vm = vm,
                    onPick = { key ->
                        vm.selectCustomer(key)
                        scope.launch { drawer.close() }
                    },
                )
            }
        },
    ) {
        Scaffold(
            snackbarHost = { SnackbarHost(snackbar) },
            topBar = {
                TopAppBar(
                    colors = TopAppBarDefaults.topAppBarColors(
                        containerColor = MaterialTheme.colorScheme.background,
                    ),
                    title = { Text(if (vm.showFlow) "账目流水" else "我的账本") },
                    navigationIcon = {
                        IconButton(onClick = { if (vm.showFlow) vm.toggleFlow() else onBack() }) {
                            Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
                        }
                    },
                    actions = {
                        // 旧「账目流水」保留成二级入口（手动记账 / 货损红冲那些行只在这里看得到）
                        IconButton(onClick = { vm.toggleFlow() }) {
                            Icon(
                                Icons.Default.ReceiptLong,
                                contentDescription = if (vm.showFlow) "看订单账" else "账目流水",
                            )
                        }
                        // 时间：**紧凑药丸**（当前窗口永远看得见），点开是档位清单。
                        // ⚠️ 不再铺那条 9 档胶囊行 —— 用户 2026-09-20：「时间都是这样子滑动的话
                        //    非常不方便」，并点名要派单员账本那种"右上角一个时间丸"。
                        // ⚠️ 2026-09-20 22:5x 用户第三次点名：**流水视图也要有它**。
                        //    原来这里有一道 `if (!vm.showFlow)` 的门，切进「账目流水」药丸就消失、
                        //    页面里又冒出那条横滑胶囊行 —— 用户看到的就是"账目流水还是滑动型的"。
                        //    现在整页只有**一个**窗口：两个视图共用它（与派单员账本同一个模型）。
                        DatePresetPill(label = vm.periodWord, onClick = { showDatePresets = true })
                    },
                )
            },
        ) { padding ->
            Box(Modifier.fillMaxSize().padding(padding)) {
                when {
                    // ⚠️ 「先盘点、再取数」那一帧：窗口还没定下来之前**整页 loading**
                    //    （用户 2026-09-21：「它会闪两下再跳到前天……闪两下已经不行了，不美观，
                    //     且占用性能」）。老写法在这里会先画一版「今天」的空态，用户看到的就是闪。
                    !vm.windowSettled -> LoadingBox()
                    vm.loading -> LoadingBox()
                    vm.error != null -> ErrorView(vm.error.orEmpty(), onRetry = { vm.load() })
                    vm.showFlow -> FlowView(vm, onOpenOrder)
                    else -> LedgerBody(vm, onOpenOrder, onOpenDrawer = {
                        vm.onDrawerQueryChange("")
                        scope.launch { drawer.open() }
                    })
                }
            }
        }
    }

    // 时间档位清单 + 自定义区间：两个弹层的状态机在 `DateFilterDialogs` 里（五个页面共用一份）
    DateFilterDialogs(
        showPresets = showDatePresets,
        onDismissPresets = { showDatePresets = false },
        preset = vm.preset,
        customFrom = vm.customFrom,
        customTo = vm.customTo,
        onPickPreset = { vm.applyPreset(it) },
        onApplyCustom = { f, t -> vm.applyCustomRange(f, t) },
    )

    // 核销弹层（整单 / 按商品）
    vm.settleTarget?.let { order -> SettleOrderDialog(vm, order) }
    // 这一单已经记了哪几笔（可从这里撤销）
    vm.settlementListTarget?.let { order -> OrderSettlementsDialog(vm, order) }
    // 撤销 / 恢复二次确认
    vm.revokeTarget?.let { s ->
        DangerConfirmDialog(
            title = "撤销这笔核销？",
            message = "订单 #" + (s.orderNo ?: "") + " 的 ¥" + formatMoney(s.amount) +
                " 会从「已收」里撤掉（记录留着，之后可以在「已撤销」里恢复）。" +
                "这只是你自己那一本账，公司那边的账一分都不动。",
            confirmText = "确认撤销",
            onConfirm = { vm.confirmRevoke() },
            onDismiss = { vm.cancelRevoke() },
        )
    }
    vm.restoreTarget?.let { s ->
        AlertDialog(
            onDismissRequest = { vm.cancelRestore() },
            title = { Text("恢复这笔核销？") },
            text = {
                Text(
                    "订单 #" + (s.orderNo ?: "") + " 的 ¥" + formatMoney(s.amount) +
                        " 会重新算成「已收」。"
                )
            },
            confirmButton = { TextButton(onClick = { vm.confirmRestore() }) { Text("确认恢复") } },
            dismissButton = { TextButton(onClick = { vm.cancelRestore() }) { Text("取消") } },
        )
    }
}

// ============================================================ 主体

@Composable
private fun LedgerBody(
    vm: ShipperLedgerViewModel,
    onOpenOrder: (Long) -> Unit,
    onOpenDrawer: () -> Unit,
) {
    Column(Modifier.fillMaxSize()) {
        // 批发商：**人员那一行**（与派单员账本同一形状）——点开是侧边抽屉，里面搜人、挑人。
        // 普通货主没有"人"可挑，所以这一行不画；他的搜索框留在页面上（搜的是订单）。
        if (vm.isMember) {
            CustomerTriggerRow(vm = vm, onOpen = onOpenDrawer)
        } else {
            Column(Modifier.padding(horizontal = 16.dp, vertical = 10.dp)) {
                SearchField(
                    value = vm.keyword,
                    onValueChange = { vm.onKeywordChange(it) },
                    placeholder = "搜订单：单号 / 收货人 / 地址",
                )
            }
        }

        LazyColumn(
            Modifier.fillMaxSize(),
            contentPadding = PaddingValues(start = 16.dp, end = 16.dp, bottom = 72.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            item { TotalsCard(vm) }

            if (vm.isMember) {
                val groups = vm.customers
                if (groups.isEmpty()) {
                    item { EmptyView("这一段没有订单", Modifier.fillMaxWidth()) }
                } else {
                    items(groups, key = { it.key }) { g -> CustomerCard(vm, g, onOpenOrder) }
                }
            } else {
                if (vm.orders.isEmpty()) {
                    item { EmptyView("这一段没有订单", Modifier.fillMaxWidth()) }
                } else {
                    item { OrdersOnlyCard(vm, onOpenOrder) }
                }
            }

            // 服务端只回了一页时**说出来**（判据是响应头，见 ShipperLedgerViewModel）
            if (vm.ordersTruncated) {
                item {
                    TruncationNote(
                        vm.ordersLimit,
                        "更早的请用右上角那段时间缩小范围；上面的合计只含已取到的这些单",
                    )
                }
            }

            if (vm.isMember && vm.revoked.isNotEmpty()) {
                item { RevokedCard(vm) }
            }
        }
    }
}

// ============================================================ 选人（人员那一行 + 侧边抽屉）

/**
 * 「人员」那一行：**这是谁 + 当前选中** —— 与派单员账本同一形状（用户点名要的那套形式）。
 *
 * 为什么把"选人"从页面上的搜索框挪进抽屉：
 * 用户 2026-09-20 指着派单员账本说「他那个可以选择货主，侧边来选择货主」——
 * 两页同一件事就该长同一个样子；而且抽屉里能**同时**看到每个人的欠款（搜索框只能筛，看不到数）。
 */
@Composable
private fun CustomerTriggerRow(vm: ShipperLedgerViewModel, onOpen: () -> Unit) {
    val picked = vm.selectedCustomer
    Row(
        Modifier.fillMaxWidth()
            .clickable { onOpen() }
            .padding(horizontal = 16.dp, vertical = 10.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(
            Icons.Default.People,
            contentDescription = null,
            tint = Color(CustomerAvatar),
            modifier = Modifier.size(18.dp),
        )
        Spacer(Modifier.width(8.dp))
        Column(Modifier.weight(1f)) {
            Text(
                if (picked == null) "货主" else picked.name,
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.Bold,
            )
            Text(
                if (picked == null) {
                    "全部（" + vm.allCustomers.size + " 人）"
                } else {
                    picked.phone.ifBlank { "欠我 ¥" + formatMoney(centsToMoney(picked.owedCents)) }
                },
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        Text("选择", style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.primary)
        Icon(
            Icons.Default.ChevronRight,
            contentDescription = null,
            tint = MaterialTheme.colorScheme.primary,
            modifier = Modifier.size(20.dp),
        )
    }
}

/**
 * 抽屉里的**货主名册**：搜索框 + 「全部」+ 每人一行（名字 / 手机号 / 欠我多少）。
 *
 * ⚠️ 这里的搜索**只筛名单**（不过滤账）：与派单员账本同一条规矩 ——
 *    在名册里搜一下，页面上的合计不该跟着变（那会让人以为钱少了）。
 */
@Composable
private fun CustomerDrawer(vm: ShipperLedgerViewModel, onPick: (String?) -> Unit) {
    Column(Modifier.fillMaxSize().padding(horizontal = 16.dp)) {
        Spacer(Modifier.height(16.dp))
        Text("选择货主", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
        Spacer(Modifier.height(10.dp))
        SearchField(
            value = vm.drawerQuery,
            onValueChange = { vm.onDrawerQueryChange(it) },
            placeholder = "搜姓名 / 手机号",
        )
        Spacer(Modifier.height(8.dp))
        LazyColumn(Modifier.fillMaxSize()) {
            item {
                DrawerCustomerRow(
                    title = "全部（" + vm.allCustomers.size + " 人）",
                    // ⚠️ 这里用**服务端的合计**（`summary.unreceived`），不是把这一页的行加起来：
                    //    列表带 limit，客户端求和会偏小（见 TotalsCard 的说明）。
                    subtitle = "欠我 ¥" + formatMoney(vm.summary?.unreceived ?: "0"),
                    selected = vm.selectedCustomerKey == null,
                    onClick = { onPick(null) },
                )
            }
            items(vm.drawerCustomers, key = { "d|" + it.key }) { c ->
                DrawerCustomerRow(
                    title = c.name,
                    subtitle = c.phone.ifBlank { c.orders.size.toString() + " 单" } +
                        " · 欠我 ¥" + formatMoney(centsToMoney(c.owedCents)),
                    selected = vm.selectedCustomerKey == c.key,
                    onClick = { onPick(c.key) },
                )
            }
            if (vm.drawerCustomers.isEmpty()) {
                item { EmptyView("没有匹配的货主", Modifier.fillMaxWidth()) }
            }
            item { Spacer(Modifier.height(24.dp)) }
        }
    }
}

@Composable
private fun DrawerCustomerRow(
    title: String,
    subtitle: String,
    selected: Boolean,
    onClick: () -> Unit,
) {
    Row(
        Modifier.fillMaxWidth().clickable { onClick() }.padding(vertical = 12.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(Modifier.weight(1f)) {
            Text(
                title,
                style = MaterialTheme.typography.bodyLarge,
                fontWeight = if (selected) FontWeight.Bold else FontWeight.Normal,
            )
            Text(
                subtitle,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        if (selected) {
            Icon(
                Icons.Default.Check,
                contentDescription = "当前选中",
                tint = MaterialTheme.colorScheme.primary,
            )
        }
    }
}


/**
 * 顶部那张卡 = **这一段他自己的收支统计**（2026-09-22 用户要求：「账本的那个统计，货主和批发商也做一下」）。
 *
 * ## 两个方向
 * · **支出 · 我该付的**：这一段我下的这些单 —— 货款 / 已付 / 还欠（欠的是**公司/总分销商**）；
 * · **收入 · 我该收的**：只有**批发商**才有 —— 货款 / 已收 / 待收（收的是**他的下游货主**）。
 *
 * ⛔ **两个方向的数一个字节都不互相写**（后端 `shipper-ledger` 从不写 `orders.paid`）——
 *    所以下面那本账怎么核销，"我该付的"都不会变。这一条在卡片上也要看得出来（两段之间画分隔线）。
 *
 * ⛔ **所有数字都取服务端**（`GET /shipper-ledger/summary`）。原来这里是客户端把这一页订单
 *    加起来 —— 列表一带 limit，单子多的那一段**合计就偏小**，而卡片上写着"这一段"。
 *    （"客户端求和"这件事本项目栽过一次：账本那页实测少算 62%，见 `CashFlowSummaryDto` 的注释。）
 *
 * ⚠️ **「我该付的」是货款，不含运费**：运费是公司与司机之间的账（`order_money` 的口径）。
 *    用户核对的是订单详情里那个"还欠"，两边必须是同一个数。
 */
@Composable
private fun TotalsCard(vm: ShipperLedgerViewModel) {
    val s = vm.summary
    SectionCard {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(
                vm.selectedCustomer?.let { "这一段 · " + it.name } ?: "这一段",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Spacer(Modifier.weight(1f))
            Text(
                // ⚠️ 这是**数据**（带值），留 `Text`；下面那段"你是给自己下单…"才是解释句、走 `Hint`
                //    —— 判据 `_check_hints.py` 明确要拦「关掉提示顺手把数据也关了」。
                if (s == null) {
                    ""
                } else {
                    "共 " + s.orders + " 单" +
                        if (s.clearedOrders > 0) " · 已结清 " + s.clearedOrders + " 单" else ""
                },
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.outline,
            )
        }

        Spacer(Modifier.height(6.dp))
        // ---- 支出：我该付的（两种货主都有）----
        Text(
            "支出 · 我该付的",
            style = MaterialTheme.typography.labelLarge,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Text(
            "¥" + formatMoney(s?.unpaid ?: "0"),
            style = MaterialTheme.typography.headlineSmall,
            fontWeight = FontWeight.Bold,
            color = Color(PayableRed),
        )
        Text(
            "货款 ¥" + formatMoney(s?.payable ?: "0") + " · 已付 ¥" + formatMoney(s?.paid ?: "0"),
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )

        if (s?.isMember == true) {
            HorizontalDivider(Modifier.padding(vertical = 10.dp))
            // ---- 收入：我该收的（只有批发商有）----
            Text(
                "收入 · 我该收的",
                style = MaterialTheme.typography.labelLarge,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Text(
                "¥" + formatMoney(s.unreceived),
                style = MaterialTheme.typography.headlineSmall,
                fontWeight = FontWeight.Bold,
                color = Color(ReceivableOrange),
            )
            Text(
                "货款 ¥" + formatMoney(s.receivable) + " · 已收 ¥" + formatMoney(s.received) +
                    if (s.settlements > 0) "（" + s.settlements + " 笔核销）" else "",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Spacer(Modifier.height(4.dp))
            Hint(
                "两段互不影响：下面那本账怎么核销，「我该付的」一分钱都不会变" +
                    "（核销只记在你自己这一本，公司那边的账不会跟着变）。",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.outline,
            )
        } else {
            Spacer(Modifier.height(4.dp))
            // ⚠️ 这一段是**纯解释**（不带任何值）→ 走 `Hint`；「已结清 N 单」那个数在右上角
            //    （那一条是 `Text`）。两句混在一次 `Hint` 里的话，关掉提示会把那个数一起关掉
            //    —— 判据 `_check_hints.py` 的 §2 专门拦这件事。
            Hint(
                // ⚠️ 措辞刻意避开"单/元/次/月"这类**单位字**：分类器把带单位的句子当**数据**
                //    （判据 `_hint_inventory.py::DIGIT_UNIT`），而数据是不许被提示开关藏掉的。
                //    这句话是纯解释（删掉它用户照样能把事做完）。
                "这里只有你欠公司的这一边：你自己卖货收回来的钱不经过本系统。",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.outline,
            )
        }
    }
}

/** 批发商：一个货主一张卡 —— **先总计，再他的订单明细**（用户要的排列）。 */
@Composable
private fun CustomerCard(
    vm: ShipperLedgerViewModel,
    g: LedgerCustomer,
    onOpenOrder: (Long) -> Unit,
) {
    SectionCard {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Box(
                Modifier.size(34.dp).background(Color(CustomerAvatar), CircleShape),
                contentAlignment = Alignment.Center,
            ) {
                Text(
                    g.name.take(1),
                    color = Color.White,
                    fontWeight = FontWeight.Bold,
                    style = MaterialTheme.typography.titleMedium,
                )
            }
            Spacer(Modifier.width(10.dp))
            Column(Modifier.weight(1f)) {
                Text(g.name, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
                if (g.phone.isNotBlank()) {
                    Text(
                        g.phone,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
            Column(horizontalAlignment = Alignment.End) {
                Text(
                    "欠我 ¥" + formatMoney(centsToMoney(g.owedCents)),
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.Bold,
                    color = if (g.owedCents > 0) Color(ReceivableOrange) else Color(0xFF8A8A8E),
                )
                Text(
                    g.orders.size.toString() + " 单 · 货款 ¥" + formatMoney(centsToMoney(g.goodsCents)),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
        Spacer(Modifier.height(8.dp))
        HorizontalDivider()
        Spacer(Modifier.height(4.dp))
        g.orders.forEachIndexed { i, o ->
            if (i > 0) HorizontalDivider(color = MaterialTheme.colorScheme.surfaceVariant)
            OrderRow(vm, o, onOpenOrder)
        }
    }
}

/** 普通货主：只有一张订单列表（点进详情）。 */
@Composable
private fun OrdersOnlyCard(vm: ShipperLedgerViewModel, onOpenOrder: (Long) -> Unit) {
    SectionCard {
        Text("我的订单", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
        Spacer(Modifier.height(6.dp))
        vm.orders.forEachIndexed { i, o ->
            if (i > 0) HorizontalDivider(color = MaterialTheme.colorScheme.surfaceVariant)
            OrderRow(vm, o, onOpenOrder)
        }
    }
}

/**
 * 一行订单。
 *
 * ## 用户 2026-09-20 第二次点名要改的就是这里
 * 「这个订单能不能好看一点啊，而且信息也不明确 —— **主要的是一个送达状态和这单多少钱**，
 *  这个是主要的。当然这个订单是可以点进去进行详情查看的，**所有订单都是一样可以点击**进详情。」
 *
 * 所以这一行按"扫一眼就够"重排（三行结构）：
 * ```
 *  [已送达] 09-18 02:15                        ¥192.60
 *  订单 #SO202609178074985653                   欠 ¥192.60   ›
 *  罗伟东 · 花生油×1 + 荷兰豆×10 等 3 样
 * ```
 * · **第一行左边**是送达状态徽章（`OrderStatusChip`：图标+颜色+文字三通道，老人/色弱也能读）
 *   加**送达时刻**；右边是**这单多少钱**（大字加粗）—— 他说的两个"主要的"就在同一行的两端；
 * · 第二行是单号 + 钱的第二档（核销状态 / 欠款）；
 * · 第三行是收货人与商品摘要（灰字一行，超了截断）；
 * · 整行可点（进订单详情），行尾那个 `›` 是"这里能点"的**可见证据** ——
 *   以前只有金额，用户不知道整行可点。
 *
 * ⚠️ 「核销」是**行内的按钮**，与整行点击分开：两种需求他都会遇到
 * （点订单看详情 / 点核销记一笔），合成一个手势就只能二选一。
 */
@Composable
private fun OrderRow(vm: ShipperLedgerViewModel, o: OrderDto, onOpenOrder: (Long) -> Unit) {
    val remaining = vm.remainingOf(o)
    val settled = vm.settledOfOrder(o.id)
    val can = vm.canSettle(o)

    Row(
        Modifier.fillMaxWidth().clickable { onOpenOrder(o.id) }.padding(vertical = 10.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(Modifier.weight(1f)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                OrderStatusChip(o.status)
                Spacer(Modifier.width(6.dp))
                Text(
                    deliveredWhen(o),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 1,
                )
            }
            Spacer(Modifier.height(4.dp))
            Text(
                "订单 #" + o.orderNo,
                style = MaterialTheme.typography.bodyMedium,
                fontWeight = FontWeight.Bold,
                maxLines = 1,
            )
            Text(
                goodsLine(o),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                maxLines = 1,
            )
        }
        Spacer(Modifier.width(8.dp))
        Column(horizontalAlignment = Alignment.End) {
            // 这一单多少钱 —— 与状态同一行的另一端，用户扫一眼就够
            Text(
                "¥" + formatMoney(centsToMoney(orderGoodsCents(o))),
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.Bold,
            )
            if (vm.isMember) {
                Text(
                    if (remaining > 0) "未核销 ¥" + formatMoney(centsToMoney(remaining)) else "已核销",
                    style = MaterialTheme.typography.bodySmall,
                    color = if (remaining > 0) Color(ReceivableOrange) else Color(0xFF8A8A8E),
                )
            } else {
                Text(
                    "欠 ¥" + formatMoney(o.arrearsAmount),
                    style = MaterialTheme.typography.bodySmall,
                    color = if ((o.arrearsAmount.toDoubleOrNull() ?: 0.0) > 0) Color(PayableRed) else Color(0xFF8A8A8E),
                )
            }
        }
        if (vm.isMember) {
            Spacer(Modifier.width(8.dp))
            Column(horizontalAlignment = Alignment.End) {
                if (can) {
                    Button(
                        onClick = { vm.openSettle(o) },
                        contentPadding = PaddingValues(horizontal = 12.dp, vertical = 0.dp),
                        modifier = Modifier.height(32.dp),
                    ) { Text("核销", style = MaterialTheme.typography.labelLarge) }
                }
                if (settled.isNotEmpty()) {
                    TextButton(
                        onClick = { vm.openSettlements(o) },
                        contentPadding = PaddingValues(horizontal = 6.dp, vertical = 0.dp),
                        modifier = Modifier.height(28.dp),
                    ) {
                        Text(
                            "已记 " + settled.size + " 笔",
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.primary,
                        )
                    }
                }
            }
        }
        // 「这里能点」的可见证据（用户 2026-09-20：他要知道**所有订单都能点进详情**）
        Icon(
            Icons.Default.ChevronRight,
            contentDescription = "查看订单详情",
            tint = MaterialTheme.colorScheme.outline,
            modifier = Modifier.size(20.dp),
        )
    }
}

/**
 * 送达时刻（第一行右边那个）。
 *
 * ⚠️ 没送达的单**不许写"已送达"**：那会让用户以为货已经到了。
 *    这一档显示的是"现在到哪一步了"（待派单/派单中/已接单）+ 下单日期。
 */
private fun deliveredWhen(o: OrderDto): String =
    if (!o.deliveredAt.isNullOrBlank()) {
        "送达 " + formatDateTime(o.deliveredAt)
    } else {
        statusWord(o.status) + " · 下单 " + formatDateCN(o.orderDate)
    }

/** 「罗伟东 · 花生油 1×24.10 + 荷兰豆 10×14.80 等 3 样」。 */
private fun goodsLine(o: OrderDto): String {
    val parts = mutableListOf<String>()
    val who = customerNameOf(o)
    if (who != UNSET_CUSTOMER && who.isNotBlank()) parts += who
    val goods = o.orderProducts.take(2).joinToString(" + ") { lineSummary(it) }
    if (goods.isNotBlank()) {
        parts += if (o.orderProducts.size > 2) goods + " 等 " + o.orderProducts.size + " 样" else goods
    }
    if (parts.isEmpty()) parts += "（没有商品明细）"
    return parts.joinToString(" · ")
}

private fun lineSummary(l: OrderProductDto): String =
    l.productNameSnapshot + " " + l.quantity + "×" + formatMoney(l.unitPrice)

private fun statusWord(status: String): String = when (status) {
    "PENDING_DISPATCH" -> "待派单"
    "DISPATCHED" -> "派单中"
    "ACCEPTED" -> "已接单"
    "DELIVERED" -> "已送达"
    "CANCELLED" -> "已撤销"
    "RETURNED" -> "已退货"
    else -> status
}

/** 已撤销的核销（软删的那些）：**手边的恢复入口**（不是只藏在 AI 撤回卡里）。 */
@Composable
private fun RevokedCard(vm: ShipperLedgerViewModel) {
    SectionCard {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Icon(Icons.Default.Undo, contentDescription = null, modifier = Modifier.size(16.dp))
            Spacer(Modifier.width(6.dp))
            Text("已撤销的核销", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
            Spacer(Modifier.weight(1f))
            Text(
                vm.revoked.size.toString() + " 笔",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.outline,
            )
        }
        Spacer(Modifier.height(6.dp))
        vm.revoked.forEach { s ->
            Row(Modifier.fillMaxWidth().padding(vertical = 6.dp), verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text(
                        "订单 #" + (s.orderNo ?: "-") + " · " + s.customerName.ifBlank { UNSET_CUSTOMER },
                        style = MaterialTheme.typography.bodyMedium,
                    )
                    Text(
                        "核销于 " + formatDateTime(s.settledAt) + " · ¥" + formatMoney(s.amount),
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                TextButton(onClick = { vm.askRestore(s) }, enabled = !vm.acting) { Text("恢复") }
            }
        }
    }
}

// ============================================================ 核销弹层

/**
 * 核销：**不勾任何商品 = 整单；勾了就是按商品核销**（用户：「可以对单个订单的某些商品
 * 进行部分商品核销，或者全部商品的核销」）。
 *
 * ⚠️ 金额由界面按"各行还可核销"算出来**只读显示**，不许手输：后端要求逐行对得上，
 *    手输必然对不上（那条路只有 400）。与派单员账本那张核销弹层是同一条规矩。
 */
@Composable
private fun SettleOrderDialog(vm: ShipperLedgerViewModel, order: OrderDto) {
    AlertDialog(
        onDismissRequest = { if (!vm.settleSubmitting) vm.closeSettle() },
        title = { Text("核销 订单 #" + order.orderNo) },
        text = {
            Column(Modifier.fillMaxWidth()) {
                Text(
                    customerNameOf(order) + "（" + customerPhoneOf(order).ifBlank { "没记电话" } + "）",
                    style = MaterialTheme.typography.bodyMedium,
                    fontWeight = FontWeight.Bold,
                )
                Spacer(Modifier.height(6.dp))
                Text(
                    "不勾商品 = 整单核销；只想收其中几样就勾上它们。",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Spacer(Modifier.height(4.dp))
                Row(verticalAlignment = Alignment.CenterVertically) {
                    TextButton(onClick = { vm.pickAllSettleLines() }) { Text("全部勾上") }
                    TextButton(onClick = { vm.clearSettleLines() }) { Text("清空（=整单）") }
                }
                HorizontalDivider()
                order.orderProducts.forEach { line ->
                    val left = vm.remainingOfLine(line.id)
                    val picked = line.id in vm.settlePicked
                    Row(
                        Modifier.fillMaxWidth()
                            .clickable(enabled = left > 0) { vm.toggleSettleLine(line.id) }
                            .padding(vertical = 6.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Checkbox(
                            checked = picked,
                            enabled = left > 0,
                            onCheckedChange = { vm.toggleSettleLine(line.id) },
                        )
                        Column(Modifier.weight(1f)) {
                            Text(line.productNameSnapshot, style = MaterialTheme.typography.bodyMedium)
                            Text(
                                line.quantity.toString() + (if (line.unit.isBlank()) "" else line.unit) +
                                    " × " + formatMoney(line.unitPrice) +
                                    if (line.returnedQuantity > 0) "（已退 " + line.returnedQuantity + "）" else "",
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        }
                        Text(
                            if (left > 0) "¥" + formatMoney(centsToMoney(left)) else "已收齐",
                            style = MaterialTheme.typography.bodyMedium,
                            color = if (left > 0) Color(ReceivableOrange) else Color(0xFF8A8A8E),
                        )
                    }
                }
                HorizontalDivider()
                Spacer(Modifier.height(8.dp))
                Text(
                    "收款方式",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Spacer(Modifier.height(4.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    ShipperLedgerViewModel.METHODS.forEach { (code, label) ->
                        FilterChip(
                            selected = vm.settleMethod == code,
                            onClick = { vm.settleMethod = code },
                            label = { Text(label, style = MaterialTheme.typography.labelMedium) },
                        )
                    }
                }
                Spacer(Modifier.height(8.dp))
                OutlinedTextField(
                    value = vm.settleNote,
                    onValueChange = { vm.settleNote = it },
                    label = { Text("备注（可选）") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
                Spacer(Modifier.height(10.dp))
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text("本次核销", style = MaterialTheme.typography.bodyMedium)
                    Spacer(Modifier.weight(1f))
                    Text(
                        "¥" + formatMoney(centsToMoney(vm.settleAmountCents())),
                        style = MaterialTheme.typography.titleMedium,
                        fontWeight = FontWeight.Bold,
                        color = Color(ReceivableOrange),
                    )
                }
                Hint(
                    "只记在你自己这一本账上 —— 公司那边的账不会变。",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.outline,
                )
                FormErrorLine(vm.settleError)
            }
        },
        confirmButton = {
            TextButton(onClick = { vm.submitSettle() }, enabled = !vm.settleSubmitting) {
                Text(if (vm.settleSubmitting) "处理中…" else "确认核销")
            }
        },
        dismissButton = {
            TextButton(onClick = { vm.closeSettle() }, enabled = !vm.settleSubmitting) { Text("取消") }
        },
    )
}

/** 这一单已经记了哪几笔核销 —— 从这里可以**撤销**其中任意一笔。 */
@Composable
private fun OrderSettlementsDialog(vm: ShipperLedgerViewModel, order: OrderDto) {
    val list = vm.settledOfOrder(order.id)
    AlertDialog(
        onDismissRequest = { vm.closeSettlements() },
        title = { Text("订单 #" + order.orderNo + " 的核销记录") },
        text = {
            Column(Modifier.fillMaxWidth()) {
                list.forEach { s ->
                    Row(Modifier.fillMaxWidth().padding(vertical = 6.dp), verticalAlignment = Alignment.CenterVertically) {
                        Column(Modifier.weight(1f)) {
                            Text("¥" + formatMoney(s.amount), fontWeight = FontWeight.Bold)
                            Text(
                                formatDateTime(s.settledAt) + " · " + methodLabel(s.method) +
                                    (if (s.note.isBlank()) "" else " · " + s.note),
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                            s.lines.take(3).forEach { ln ->
                                Text(
                                    ln.productName + " ¥" + formatMoney(ln.amount),
                                    style = MaterialTheme.typography.bodySmall,
                                    color = MaterialTheme.colorScheme.outline,
                                )
                            }
                        }
                        TextButton(onClick = { vm.askRevoke(s) }, enabled = !vm.acting) { Text("撤销") }
                    }
                    HorizontalDivider(color = MaterialTheme.colorScheme.surfaceVariant)
                }
                if (list.isEmpty()) Text("这一单还没有核销记录")
            }
        },
        confirmButton = { TextButton(onClick = { vm.closeSettlements() }) { Text("关闭") } },
    )
}

private fun methodLabel(code: String): String =
    ShipperLedgerViewModel.METHODS.firstOrNull { it.first == code }?.second ?: code

// ============================================================ 旧「账目流水」视图（保留）

/**
 * 账目流水（手动记账 / 货损红冲那些行的入口）。
 *
 * ⚠️ **它没有自己的时间控件**：窗口是顶栏那一个药丸（与订单账共用，见 VM 里那段注释）。
 *    原来这里铺着一条 `DatePresetRow`（9 档横滑胶囊）—— 用户 2026-09-20 22:5x 点名否掉：
 *    「你这个账目流水为什么也不做对应的那个右上角的时间图标？他还是那个滑动型的」。
 *    这一页上**任何一条横滑的日期胶囊都不该再出现**（全项目 grep `DatePresetRow` 应当只剩筛选条）。
 */
@Composable
private fun FlowView(vm: ShipperLedgerViewModel, onOpenOrder: (Long) -> Unit) {
    LazyColumn(
        Modifier.fillMaxSize(),
        contentPadding = PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        item {
            SectionCard {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text("账单趋势", style = MaterialTheme.typography.titleMedium, modifier = Modifier.weight(1f))
                    TextButton(onClick = { vm.chartType = if (vm.chartType == "line") "bar" else "line" }) {
                        Text(if (vm.chartType == "line") "条形图" else "折线图")
                    }
                }
                Spacer(Modifier.height(6.dp))
                val cs = vm.flowChartSeries
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
                Text(
                    "当前范围内合计",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Spacer(Modifier.height(2.dp))
                Text(
                    "¥" + formatMoney(vm.flowTotal().toString()),
                    style = MaterialTheme.typography.headlineSmall,
                    fontWeight = FontWeight.Bold,
                    color = Color(MoneyOrange),
                )
            }
        }
        if (vm.entries.isEmpty()) {
            item { EmptyView("该时段暂无账目", Modifier.fillMaxWidth()) }
        } else {
            if (vm.entriesTruncated) {
                item {
                    TruncationNote(
                        vm.entriesLimit,
                        "更早的请点右上角的日期档位缩小范围；上面的合计与趋势只含已取到的这些行",
                    )
                }
            }
            items(vm.entries, key = { it.id }) { e ->
                LedgerCard(
                    e = e,
                    expandedOrderId = vm.expandedOrderId,
                    expandedOrder = vm.expandedOrder,
                    orderLoading = vm.expandedOrderLoading,
                    onToggleOrder = { vm.toggleOrderDetail(it) },
                    onOpenOrder = onOpenOrder,
                )
            }
        }
        item { Spacer(Modifier.height(56.dp)) }
    }
}

@Composable
private fun LedgerCard(
    e: LedgerEntryDto,
    /** 就地展开的订单（用户要求「订单是可以展开进行查看的…包括货主的账本」）。 */
    expandedOrderId: Long?,
    expandedOrder: OrderDto?,
    orderLoading: Boolean,
    onToggleOrder: (Long) -> Unit,
    /** 仍然保留"跳到订单详情页"这条路（展开块右上角那个「打开订单」）。 */
    onOpenOrder: (Long) -> Unit,
) {
    val oid = e.orderId
    SectionCard {
        Row(
            // ⚠️ 点一下是**就地展开那一单**，不是跳走：跳走再回来，时间范围与滚动位置全没了
            Modifier.fillMaxWidth().clickable(enabled = oid != null) { oid?.let(onToggleOrder) },
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(Modifier.weight(1f)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    // 核心：名称（加粗突出 + 小图标语义色）
                    Icon(
                        if (e.source == "manual") Icons.Default.EditNote else Icons.Default.ReceiptLong,
                        contentDescription = null,
                        tint = Color(if (e.source == "manual") 0xFF8455E6 else 0xFF1E6FFF),
                        modifier = Modifier.size(14.dp),
                    )
                    Spacer(Modifier.width(5.dp))
                    Text(e.productName, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
                    Spacer(Modifier.width(8.dp))
                    val isManual = e.source == "manual"
                    Surface(
                        color = if (isManual) MaterialTheme.colorScheme.secondaryContainer else MaterialTheme.colorScheme.surfaceVariant,
                        shape = MaterialTheme.shapes.small,
                    ) {
                        Text(
                            if (isManual) "手动" else "订单",
                            style = MaterialTheme.typography.labelMedium,
                            modifier = Modifier.padding(horizontal = 6.dp, vertical = 1.dp),
                        )
                    }
                }
                Spacer(Modifier.height(3.dp))
                // 次要信息：一行灰字（日期·关联订单）
                Text(
                    (listOfNotNull(e.entryDate, e.orderNo?.let { "订单 #" + it }).joinToString(" · ")),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 1,
                )
                if (e.note.isNotBlank()) {
                    Text(e.note, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.outline, maxLines = 1)
                }
            }
            Spacer(Modifier.width(10.dp))
            // 金额：固定宽度右对齐 + 橙金加粗（真正的重点）
            Text(
                "¥" + formatMoney(e.total),
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.Bold,
                textAlign = TextAlign.End,
                color = Color(0xFFFF9500),
                modifier = Modifier.widthIn(min = 92.dp),
            )
        }
        if (oid != null && oid == expandedOrderId) {
            OrderPeek(
                loading = orderLoading,
                order = expandedOrder,
                onOpenFull = { onOpenOrder(oid) },
            )
        }
    }
}

// ============================================================ 配色（本页语义色）

/** 我欠别人的钱：红（欠出去是压力）。 */
private val PayableRed = 0xFFD32F2F

/** 别人欠我的钱：橙（与"账本"那一套橙色同源）。 */
private val ReceivableOrange = 0xFFFF9500

/** 货主头像底色：青（与"联系人/客户"一套，别和订单蓝、账本橙撞）。 */
private val CustomerAvatar = 0xFF00A2A8
