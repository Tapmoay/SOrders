package com.tapmoay.sorders.ui.dispatcher

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.foundation.lazy.items
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
import com.tapmoay.sorders.core.UserSearch
import com.tapmoay.sorders.data.remote.dto.FreightSettlementOrderDto
import com.tapmoay.sorders.data.remote.dto.LedgerEntryDto
import com.tapmoay.sorders.data.remote.dto.OrderDto
import com.tapmoay.sorders.ui.common.*
import com.tapmoay.sorders.ui.theme.MgrGreen
import com.tapmoay.sorders.ui.theme.MoneyOrange
import com.tapmoay.sorders.ui.theme.ProductPurple
import com.tapmoay.sorders.util.formatMoney
import kotlinx.coroutines.launch

/**
 * 派单员账本：**一类账一页**（订单账 / 司机账 / 货主账 / 批发商账，由入口页那一格定）。
 *
 * ## 页面形状（2026-09-20 第五轮定稿，用户口述逐条对着做）
 *
 * 顶上那一条是「这一类账的名字 + 时间」，正文第一行是「人员」，下面才是数据：
 *
 * > 那个折线图条形图还有扇形图，我们**直接去掉**就行了……到时候**在报表中心看**就可以了。
 * > 那个时间也太复杂了，换一种崭新形式，**但是时间和选择人物不要一样的展现形式**；
 * > 选择人物我们用那种**侧边栏抽屉**，可以在那里寻找人物，点击人物就可以了。
 *
 * | 谁 | 用什么形态 | 为什么 |
 * |---|---|---|
 * | **时间** | 顶栏一个紧凑的**药丸**（写着当前窗口，点开是档位清单） | 9 个胶囊横着铺两行太占地方；药丸常驻顶栏，**当前窗口永远看得见**（口径词是这一页最容易搞错的东西） |
 * | **人员** | 页面上**一行入口** → 打开**侧边抽屉**（抽屉里带搜索） | 人一多，"一排 chip 里找"比看账还花时间；抽屉里能搜、能滚，选中即关 |
 * | **图** | **一张都没有** | 用户点名去掉；图归报表中心（那里有现成的营业额/商品/司机三套） |
 *
 * ## 这一页被否掉过的东西（别再装回来）
 *
 * · 页内那条 **4 页签导航**（`LedgerTabBar`）——「最上面的 4 个去掉，那是**老的导航栏**」；
 * · **司机账里的「司机结算单」入口**——「那个结算，这个也直接去掉」（功能还在，走工作台那一格）；
 * · **日期胶囊那一行**（`DatePresetRow`）——「太复杂了，这样的不好，换一种崭新形式」；
 * · **人员 chip 那一行**——「假如司机多的话，那我要选该怎么去选呢？」；
 * · **三种图**（折线/条形/扇形）——「直接去掉就行了…在报表中心看就可以了」。
 * · ⛔ 这一页**只管看账**：客户收款 / 开销管理在入口页里，不在这里。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DispatcherLedgerScreen(
    container: AppContainer,
    onBack: () -> Unit,
    onOpenOrder: (Long) -> Unit = {},
    initialTab: Int = 0,
    /** 「记账」按钮 → 去「记一笔账」那一页（用户 2026-09-20 第七轮改成单独一页）。 */
    onCreateEntry: () -> Unit = {},
) {
    val vm: DispatcherLedgerViewModel = appViewModel { DispatcherLedgerViewModel(container, initialTab) }
    val snackbar = remember { SnackbarHostState() }
    // 两个弹层：自定义日期（选完区间）与档位清单（选哪一档）——都是**函数体这一层**的状态
    // （弹层画在 Scaffold 外面，声明在它的 content 里就出了作用域）
    var showCustomRange by remember { mutableStateOf(false) }
    var showDatePresets by remember { mutableStateOf(false) }
    // 侧边抽屉：选人用（订单账没有"人"，所以那一边连手势都关掉）
    val drawer = rememberDrawerState(DrawerValue.Closed)
    val scope = rememberCoroutineScope()

    OneShotSnackbar(snackbar, vm.actionResult, onConsumed = { vm.actionResult = null })

    // 从「记一笔账」那一页回来时重取一次（第一次进这一页不重复拉，`init` 刚拉过）。
    // ⚠️ 少了这一句：刚记的那笔不在列表里 → 用户以为没存上 → 再记一遍。
    LaunchedEffect(Unit) { vm.onEnter() }

    // 失败**必须**看得见。
    // 以前这个页面的错误只在「三个账户列表都空」时才渲染成整页 ErrorView：
    // 于是「+记一笔」被后端拒绝时（比如既没选货主也没填临时货主名），
    // **弹窗不关、界面毫无反馈**——用户以为点了没反应，再点一次还是没反应。
    // ⚠️ 这里消费的是**动作错误**（vm.error）。加载错误走 vm.loadError，
    //    它还要驱动下面那条整页 ErrorView（带重试），所以**不能**被提示条清掉 —— 见 VM 的注释。
    OneShotSnackbar(snackbar, vm.error, onConsumed = { vm.error = null })

    ModalNavigationDrawer(
        drawerState = drawer,
        gesturesEnabled = vm.tab != 0,
        drawerContent = {
            ModalDrawerSheet {
                PersonDrawer(
                    vm = vm,
                    onPick = { key ->
                        vm.selectPersonKey(key)
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
                    title = {
                        // 标题写的是**这一类账**：页内没有导航了，它是唯一说明"我在看哪一本账"的地方
                        Text(vm.kindTitle(), style = MaterialTheme.typography.titleLarge)
                    },
                    navigationIcon = {
                        IconButton(onClick = onBack) {
                            Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
                        }
                    },
                    actions = {
                        // 时间：紧凑药丸（当前窗口 + 下拉箭头），点开是档位清单。
                        DatePresetPill(
                            label = vm.periodWord,
                            onClick = { showDatePresets = true },
                        )
                    },
                )
            },
        ) { padding ->
            Column(Modifier.fillMaxSize().padding(padding)) {
                // 人员那一行：**只在"人的账"里出现**（订单账那一堆流水里没有"人"可挑）
                if (vm.tab != 0) {
                    PersonTriggerRow(
                        vm = vm,
                        onOpen = { vm.query = ""; scope.launch { drawer.open() } },
                    )
                }
                Box(Modifier.weight(1f).fillMaxHeight()) {
                    when {
                        // ⚠️ 「先盘点、再取数」那一帧：窗口还没定下来之前**整页 loading**
                        //    （2026-09-21 用户：「它会闪两下再跳到前天……闪两下已经不行了，
                        //     不美观，且占用性能」）。老写法在这里会先画一版「今天」的账/空态。
                        !vm.windowSettled -> LoadingBox()
                        vm.loading && vm.tab == 0 -> LoadingBox()
                        vm.accountsLoading && vm.tab != 0 -> LoadingBox()
                        vm.loadError != null && vm.tab != 0 && vm.driverAccounts.isEmpty() && vm.shipperAccounts.isEmpty() && vm.memberAccounts.isEmpty() ->
                            ErrorView(vm.loadError.orEmpty(), onRetry = { if (vm.tab == 0) vm.load() else vm.loadAccounts() })
                        else -> LazyColumn(
                            Modifier.fillMaxSize(),
                            contentPadding = PaddingValues(start = 16.dp, end = 16.dp, top = 4.dp, bottom = 16.dp),
                            verticalArrangement = Arrangement.spacedBy(10.dp),
                        ) {
                            when {
                                // ---- 订单账：一页流水（唯一还能手动记账的地方）----
                                vm.tab == 0 -> ledgerEntryItems(vm, onOpenOrder, onCreateEntry)
                                // ---- 某个人：他这一段的账（按订单）----
                                vm.personKey != null -> {
                                    // 名字是**现成的**（就在账户行/抽屉里），所以先画"这是谁"，
                                    // 钱等拉回来再说 —— 反过来先画一堆 0 再跳成真数，用户会以为账错了。
                                    item { PersonHeaderCard(vm) }
                                    if (vm.personLoading) item { LoadingBox() }
                                    else ledgerPersonItems(vm, onOpenOrder)
                                }
                                // ---- 全部人：合计 + 每人一行（点一行 = 进他的账）----
                                else -> {
                                    val label = vm.kindLabel()
                                    val all = vm.accountRows()
                                    item { LedgerDashboardCard(vm, label = label, color = vm.kindColor()) }
                                    if (all.isEmpty()) {
                                        item { EmptyView("该时段暂无" + label + "账目", Modifier.fillMaxWidth()) }
                                    } else {
                                        items(all, key = { it.key }) { r ->
                                            LedgerAccountRow(
                                                row = r,
                                                blankLabel = label,
                                                icon = vm.kindIcon(),
                                                color = vm.kindColor(),
                                                onOpen = { vm.openPerson(r) },
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
    }

    // 时间档位清单（点顶栏那个药丸打开）
    if (showDatePresets) {
        DatePresetDialog(
            selected = vm.preset,
            customFrom = vm.customFrom,
            customTo = vm.customTo,
            onPick = { label ->
                showDatePresets = false
                // 「自定义」不由档位表给区间（它要选两头的日期）→ 直接开日期弹层
                if (label == DatePresets.CUSTOM) showCustomRange = true else vm.applyPreset(label)
            },
            onDismiss = { showDatePresets = false },
        )
    }

    // 自定义日期（只选一头点「应用」＝什么都不做）
    if (showCustomRange) {
        DateRangeDialog(
            initialFrom = vm.customFrom,
            initialTo = vm.customTo,
            onDismiss = { showCustomRange = false },
            onApply = { f, t ->
                showCustomRange = false
                vm.applyCustomRange(f, t)
            },
        )
    }

    // ⛔ 「记一笔账」的弹窗**不在这里了**（用户 2026-09-20 第七轮）：记账要**从商品库选商品**，
    //    而选品那一份 UI 是全屏底部弹层 —— 套在 `AlertDialog` 里就是两层 modal 窗口叠着。
    //    现在它是单独一页（`Routes.LEDGER_CREATE` / `LedgerCreateScreen.kt`），
    //    回来那一下由 `vm.onEnter()` 重取（见下面那个 LaunchedEffect）。

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

    // 就地核销（整单 / 按商品）—— 用户 2026-09-20：「点击订单点击核销…可以全部核销，
    // 也可以按商品进行核销」。
    if (vm.settleTarget != null) SettleOrderDialog(vm, onDismiss = { vm.closeSettle() })
    // 批量核销（点合计 → 核销全部，只有"进到某个人"时才给）
    if (vm.settleAllOpen) SettleAllDialog(vm, onDismiss = { vm.closeSettleAll() })
}

/**
 * 人员那一行：**页面上唯一一个"选人"的入口**（点开右侧抽屉）。
 *
 * 为什么不做成一排 chip（那是被否掉的那一版）：「假如司机多的话，那我要选该怎么去选呢？」
 * —— 一屏铺不下、还得左右滑；抽屉里能搜（姓名 / 手机号 / 后 4 位）能滚，选完自动关上。
 * ⚠️ 这一行**不写金额**：金额在下面的账户行上（同一份信息写两处，就一定会"两边对不上"）。
 */
@Composable
private fun PersonTriggerRow(vm: DispatcherLedgerViewModel, onOpen: () -> Unit) {
    Surface(
        onClick = onOpen,
        color = MaterialTheme.colorScheme.surface,
        shape = MaterialTheme.shapes.medium,
        modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 6.dp),
    ) {
        Row(
            Modifier.fillMaxWidth().padding(horizontal = 14.dp, vertical = 12.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            TintedIcon(vm.kindIcon(), vm.kindColor(), size = 16.dp, container = 32.dp)
            Spacer(Modifier.width(10.dp))
            Column(Modifier.weight(1f)) {
                Text(
                    "人员",
                    style = MaterialTheme.typography.labelMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Text(
                    if (vm.personKey == null) "全部（" + vm.accountRows().size + " 人）" else vm.personTitle(),
                    style = MaterialTheme.typography.titleSmall,
                    fontWeight = FontWeight.Bold,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
            Spacer(Modifier.width(8.dp))
            Text("选择", style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.primary)
            Icon(
                Icons.Default.ChevronRight,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.primary,
            )
        }
    }
}

/**
 * 侧边抽屉的内容：**搜索框 + 名单**（第一行永远是「全部」）。
 *
 * 「全部」放在最上面而不是藏起来：默认状态就是它，用户看完某个人要回到"所有人在这一段的账"
 * 时得有个明确的地方点。
 */
@Composable
private fun PersonDrawer(vm: DispatcherLedgerViewModel, onPick: (String?) -> Unit) {
    val rows = vm.drawerPersons()
    Column(Modifier.fillMaxSize().padding(horizontal = 16.dp)) {
        Spacer(Modifier.height(20.dp))
        Text(
            "选择" + vm.kindLabel(),
            style = MaterialTheme.typography.titleMedium,
            fontWeight = FontWeight.Bold,
        )
        Spacer(Modifier.height(10.dp))
        SearchField(value = vm.query, onValueChange = { vm.query = it })
        Spacer(Modifier.height(8.dp))
        LazyColumn(Modifier.weight(1f)) {
            item(key = "all") {
                DrawerPersonRow(
                    title = "全部（" + vm.accountRows().size + " 人）",
                    subtitle = "看所有人在" + vm.periodWord + "的账",
                    selected = vm.personKey == null,
                    onClick = { onPick(null) },
                )
            }
            if (rows.isEmpty()) {
                item {
                    Text(
                        UserSearch.noMatchText(vm.query) + vm.kindLabel(),
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.padding(vertical = 16.dp),
                    )
                }
            } else {
                items(rows, key = { it.key }) { r ->
                    DrawerPersonRow(
                        title = r.title.ifBlank { r.phone ?: "未命名" + vm.kindLabel() },
                        // 手机号是**同名不同人**唯一的分辨依据（两个「张老板」在真机上就是两行一样的名字）
                        subtitle = listOfNotNull(r.phone?.ifBlank { null }, "停用".takeIf { r.inactive }).joinToString(" · "),
                        selected = vm.personKey == r.key,
                        onClick = { onPick(r.key) },
                    )
                }
            }
        }
        Spacer(Modifier.height(12.dp))
    }
}

/** 抽屉里的一行（选中那行打勾 + 加粗）。 */
@Composable
private fun DrawerPersonRow(title: String, subtitle: String, selected: Boolean, onClick: () -> Unit) {
    Row(
        Modifier.fillMaxWidth().clickable(onClick = onClick).padding(vertical = 12.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(Modifier.weight(1f)) {
            Text(
                title,
                style = MaterialTheme.typography.bodyLarge,
                fontWeight = if (selected) FontWeight.Bold else FontWeight.Normal,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            if (subtitle.isNotBlank()) {
                Text(
                    subtitle,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 1,
                )
            }
        }
        if (selected) {
            Icon(Icons.Default.Check, contentDescription = "当前选中", tint = MaterialTheme.colorScheme.primary)
        }
    }
}

/**
 * 账户一行 —— 司机账 / 货主账 / 批发商账**同一个版式、同一份实现**。
 *
 * 名字下面那行是**手机号 + 笔数/单数**：
 * · 手机号是**同名不同人**唯一的分辨依据（两个「张老板」以前是两行一模一样的卡，
 *   只能靠金额猜谁是谁），也是用户 2026-09-19 要的搜索键之一；
 * · 没号的（临时货主）要说清"为什么没有"，不能留一行空白让人以为是加载失败。
 *
 * ⛔ 这里**没有展开块**：点一下就是进他的账（第二层，按订单）。
 */
@Composable
private fun LedgerAccountRow(
    row: LedgerAccountRow,
    blankLabel: String,
    icon: ImageVector,
    color: Color,
    onOpen: () -> Unit,
) {
    SectionCard {
        Row(
            Modifier.fillMaxWidth().clickable(onClick = onOpen),
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
            Spacer(Modifier.width(4.dp))
            Icon(
                Icons.Default.ChevronRight,
                contentDescription = "进他的账",
                tint = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

/** 订单账那一档的明细（「记账」按钮去单独一页：`Routes.LEDGER_CREATE`）。 */
private fun LazyListScope.ledgerEntryItems(
    vm: DispatcherLedgerViewModel,
    onOpenOrder: (Long) -> Unit,
    onCreateEntry: () -> Unit,
) {
    item {
        SectionCard {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    // 与其余几类账**同一个 KPI 版式**（仪表盘思维：钱单独一行）
                    KpiBlock(
                        label = "订单账合计（" + vm.periodWord + "）",
                        total = vm.total(),
                        stats = "共 " + vm.entries.size + " 笔流水" +
                            if (vm.entriesTruncated) "（只含已取到的）" else "",
                    )
                }
                Button(onClick = onCreateEntry) {
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
        // 服务端只回了一页时**说出来**（判据是响应头 `X-Truncated`，见 DispatcherLedgerViewModel）。
        // ⚠️ 上面那张卡（合计）是拿这一页在客户端算的 —— 不说的话"当前范围内合计"会被当成
        //    整段总额，而它其实只含看得见的这些行。
        if (vm.entriesTruncated) {
            item {
                TruncationNote(
                    vm.entriesLimit,
                    "更早的请点右上角的日期档位缩小范围；上面的合计只含已取到的这些行",
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

// ============================================================ 账本仪表盘
//
// 用户 2026-09-19 第二次拍板：「**所有的账本你可以一个仪表盘的思维进行去构建**」——
// 这句推翻了上一版的「搜索 + 多选 chip 墙」。两个理由记在这里，免得下一轮又有人把它加回来：
//   ① chip 墙上写的"名字 + 金额"与下面列表里的**是同一份信息**，重复放在两处，
//      就一定会出现"两边对不上"的困惑；
//   ② 账户一多，"在一堆 chip 里找到要点的那几个"比看账本身更花时间 —— 这正是他说的「麻烦」。
//
// 现在：一屏看完所有账户各自的数（下面第一张卡就是仪表盘），选人走侧边抽屉，
// 点账户行进他的账。
//
// ⛔ 2026-09-20 第五轮**又删掉了三张图**（折线/条形/扇形）：用户说「直接去掉就行了……
//    到时候在报表中心看就可以了」。所以这一页现在只有**数**，没有图 —— 图在
//    `ui/common/Charts.kt`（报表中心/货主账本/司机端在用），账本页一张都不画。

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
 * 账户仪表盘：这一类账在**当前时间窗口**里的合计。
 *
 * ⚠️ 它取的是**全部账户**的合计（`dashboard()` 里没有搜索）：搜索在抽屉里，
 *    而抽屉是"选人"用的 —— 边打字边改这里的合计，关掉抽屉就会剩一个对不上的总数。
 * ⚠️ 这里**故意不给**「核销全部」按钮：用户 2026-09-20 明说"全部（所有人）时那个合计
 *    不能批量核销，只能下到每个司机/货主才能批量核销" —— 收款单绑的是**一个人的**
 *    客户档案，在"全部人"这一层收钱就等于把钱记到某个随机的人头上。
 */
@Composable
private fun LedgerDashboardCard(
    vm: DispatcherLedgerViewModel,
    label: String,
    color: Color,
) {
    val d = vm.dashboard()
    SectionCard {
        KpiBlock(
            // 口径词跟着窗口走（§4.9）：档位是「全部」时写"当前时间范围"会让人以为有个具体窗口
            label = label + "账合计（" + vm.periodWord + "）",
            total = d.total,
            stats = d.accounts.toString() + " 个账户 · 共 " + d.count + " 笔",
            hint = "点某一行进他的账（核销在那一页里）；批量核销要先选中某个人，再点他的合计",
        )
        // ⚠️ 选人的入口**不在这里**：它是页面上单独那一行（设计规范 §4.15）。
    }
}

/**
 * 司机账展开：他在这段时间里完成的单。
 *
 * ⚠️ 明细**已经跟在结算响应里**（`group.orders`），所以这里不请求、也没有"加载中"这一态。
 * ⚠️ 金额显示的是**司机应得**（`pay_total`，与组头合计同源）；货主运费另用小字标注 ——
 *    两个数常常不等，拿运费当"他该拿多少"会让这一列加起来对不上上面的合计。
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
            Column(horizontalAlignment = Alignment.End) {
                Text(
                    "¥" + formatMoney(o.payTotal),
                    style = MaterialTheme.typography.bodyMedium,
                    fontWeight = FontWeight.Bold,
                    textAlign = TextAlign.End,
                    color = Color(MoneyOrange),
                    modifier = Modifier.widthIn(min = 92.dp),
                )
                Text(
                    if (o.freightFee != null) "运费 ¥" + formatMoney(o.freightFee) else "运费 待定价",
                    style = MaterialTheme.typography.labelSmall,
                    color = if (o.freightFee != null) MaterialTheme.colorScheme.onSurfaceVariant else Color(0xFFFF6B2C),
                )
            }
        }
        if (o.orderId == expandedOrderId) {
            OrderPeek(loading = orderLoading, order = expandedOrder, onOpenFull = { onOpenOrder(o.orderId) })
        }
    }
}

/** 司机第二层那一块：他这一段跑的单（不再请求，明细在列表响应里）。 */
@Composable
internal fun DriverPersonOrders(vm: DispatcherLedgerViewModel, onOpenOrder: (Long) -> Unit) {
    SectionCard {
        Text("他跑的单（" + vm.periodWord + "）", style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Bold)
        Spacer(Modifier.height(6.dp))
        DriverOrderLines(
            orders = vm.driverOrdersOf(vm.personKey.orEmpty()),
            expandedOrderId = vm.expandedOrderId,
            expandedOrder = vm.expandedOrder,
            orderLoading = vm.expandedOrderLoading,
            onToggleOrder = { vm.toggleOrderDetail(it) },
            onOpenOrder = onOpenOrder,
        )
    }
}

@Composable
private fun LedgerRow(
    e: LedgerEntryDto,
    onDelete: () -> Unit,
    onOpenOrder: (Long) -> Unit,
    /** 就地展开那一单（与货主账/批发商账**同一套**，用户说「其他其他的都一样」）。 */
    expandedOrderId: Long?,
    expandedOrder: OrderDto?,
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
