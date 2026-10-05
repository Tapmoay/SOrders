package com.tapmoay.sorders.ui.dispatcher

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.core.InputRules
import com.tapmoay.sorders.core.UserSearch
import com.tapmoay.sorders.ui.common.*
import com.tapmoay.sorders.util.trimMoneyZeros
import kotlinx.coroutines.launch

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DispatcherPoolScreen(
    container: AppContainer,
    onBack: () -> Unit,
    onOpenOrder: (Long) -> Unit,
    /** true = 作为底部导航内容内嵌（隐藏返回矢头/双重 inset） */
    embedded: Boolean = false,
) {
    val vm: DispatcherPoolViewModel = appViewModel { DispatcherPoolViewModel(container) }
    val snackbar = remember { SnackbarHostState() }

    OneShotSnackbar(snackbar, vm.actionResult, onConsumed = { vm.actionResult = null })

    // 一次性提示（全选被上限截断等）。没有它，"全选只选了 100 单"这件事用户看不到。
    OneShotSnackbar(snackbar, vm.notice, onConsumed = { vm.notice = null })

    Scaffold(
        snackbarHost = { SnackbarHost(snackbar) },
        topBar = {
            TopAppBar(
                // 标题跟着分页走：切到「已完成派单」还写「待派单池」，用户会以为切错了
                title = { Text(if (vm.tab == DispatcherPoolViewModel.TAB_COMPLETED) "已完成派单" else "待派单池") },
                windowInsets = if (embedded) WindowInsets(0, 0, 0, 0) else TopAppBarDefaults.windowInsets,
                navigationIcon = {
                    if (!embedded) {
                        IconButton(onClick = onBack) {
                            Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
                        }
                    }
                },
                actions = {
                    // 批量派单只属于「待派单池」那一档（已完成档的卡片动作是「退回池子」）
                    if (vm.tab == DispatcherPoolViewModel.TAB_POOL && vm.orders.isNotEmpty()) {
                        TextButton(
                            onClick = {
                                if (vm.selectionMode) vm.clearSelection() else vm.selectionMode = true
                            },
                        ) {
                            Text(if (vm.selectionMode) "取消选择" else "批量派单")
                        }
                    }
                },
            )
        },
        bottomBar = {
            if (vm.tab == DispatcherPoolViewModel.TAB_POOL && vm.selectionMode) {
                Surface(shadowElevation = 8.dp) {
                    Row(
                        Modifier.fillMaxWidth().padding(16.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Text(
                            "已选 " + vm.selectedIds.size + " 单",
                            style = MaterialTheme.typography.titleSmall,
                            modifier = Modifier.weight(1f),
                        )
                        TextButton(onClick = { vm.selectAll() }) {
                            // "已经选满"的判据要跟着上限走：池里 300 单、上限 100 单时，
                            // 选满 100 单就该显示「取消全选」（否则按钮看起来点了没反应）
                            val cap = minOf(vm.orders.size, DispatcherPoolViewModel.MAX_BATCH_ASSIGN)
                            Text(
                                if (vm.selectedIds.size >= cap && cap > 0) "取消全选"
                                else "全选" + if (vm.orders.size > DispatcherPoolViewModel.MAX_BATCH_ASSIGN)
                                    "（最多 ${DispatcherPoolViewModel.MAX_BATCH_ASSIGN}）" else "",
                            )
                        }
                        Button(
                            onClick = { vm.openAssign(null) },
                            enabled = vm.selectedIds.isNotEmpty(),
                        ) { Text("批量派单") }
                    }
                }
            }
        },
    ) { padding ->
        Column(Modifier.fillMaxSize().padding(padding)) {
            // 分页（用户 2026-10-05：「在派单词再加一个分页为已完成派单」）。
            // ⛔ 用通用 SegmentedPicker，**不新建 OrderTab 档位表**：那是货主/派单员订单列表的档位，
            //    `_tools/qa/_check_order_list_ui.py` 对它每一格都有要求（缺省档、格数、每个状态一个落点），
            //    而这里只是同一页上的两个数据源切换。
            SegmentedPicker(
                labels = listOf("待派单池", "已完成派单"),
                selected = vm.tab,
                onSelect = { vm.selectTab(it) },
                modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 10.dp),
            )
            // 「已完成派单」顶栏那颗选司机（CHG-0040）。用户 2026-10-05：「司机一旦多起来、
            // 订单一旦多起来就是很容易找不到」⇒「上面改一个可以选择司机的方式」。
            // 只在已完成那一档出现：待派档还没派给谁，没有可筛的人。
            if (vm.tab == DispatcherPoolViewModel.TAB_COMPLETED) {
                PersonTriggerRow(
                    icon = Icons.Default.Person,
                    color = MaterialTheme.colorScheme.tertiary,
                    label = "司机",
                    value = vm.driverFilterLabel,
                    onOpen = { vm.openDriverPicker() },
                )
            }
            Box(Modifier.fillMaxSize()) {
                when {
                    vm.loading -> LoadingBox()
                    vm.error != null -> ErrorView(vm.error.orEmpty(), onRetry = { vm.load() })
                    // 已完成档的空态与池子不同：池子清空是好事，这里空是「还没派过单」
                    vm.tab == DispatcherPoolViewModel.TAB_COMPLETED && vm.dispatched.isEmpty() ->
                        EmptyView("还没有派给司机的单", Modifier.align(Alignment.Center))
                    vm.tab == DispatcherPoolViewModel.TAB_COMPLETED -> DispatchedList(vm, onOpenOrder)
                    vm.orders.isEmpty() -> EmptyView("待派单池已清空", Modifier.align(Alignment.Center))
                    else -> LazyColumn(
                        Modifier.fillMaxSize(),
                        contentPadding = PaddingValues(16.dp),
                        verticalArrangement = Arrangement.spacedBy(10.dp),
                    ) {
                        // 列表被后端截断时必须说出来：`GET /orders?status=PENDING_DISPATCH`
                        // 对派单员**服务端强制 300 条**（积压多时那个接口会返回十几 MB）。
                        // 不写这一句，用户会以为"待派就这么多"，而实际积压可能是几千单。
                        if (vm.listTruncated) {
                            item(key = "truncated-hint") {
                                Surface(
                                    shape = MaterialTheme.shapes.small,
                                    color = MaterialTheme.colorScheme.secondaryContainer,
                                ) {
                                    Text(
                                        "只显示最近 ${vm.orders.size} 单（待派共 ${vm.totalPending} 单）。" +
                                            "先派掉一批，后面会自动补上来。",
                                        style = MaterialTheme.typography.bodySmall,
                                        color = MaterialTheme.colorScheme.onSecondaryContainer,
                                        modifier = Modifier.fillMaxWidth().padding(10.dp),
                                    )
                                }
                            }
                        }
                        items(vm.orders, key = { it.id }) { order ->
                            Column {
                                if (vm.selectionMode) {
                                    Row(
                                        Modifier.fillMaxWidth(),
                                        verticalAlignment = Alignment.CenterVertically,
                                    ) {
                                        Checkbox(
                                            checked = order.id in vm.selectedIds,
                                            onCheckedChange = { vm.toggleSelect(order.id) },
                                        )
                                        Spacer(Modifier.width(8.dp))
                                        Text(
                                            "#" + order.orderNo,
                                            style = MaterialTheme.typography.titleSmall,
                                            modifier = Modifier.weight(1f),
                                        )
                                    }
                                }
                                OrderCard(
                                    order = order,
                                    onClick = { if (vm.selectionMode) vm.toggleSelect(order.id) else onOpenOrder(order.id) },
                                    showShipper = true,
                                    // 卡片动作分区（2026-09-22 定的规范：**左＝反向/警示，右＝主操作/编辑**）。
                                    leading = {
                                        if (!vm.selectionMode) {
                                            // 撤销 = **反向操作** → 左边、而且是**最左边**
                                            //（用户 2026-09-22「派单在右边，撤销在左边，而且是最左边」——
                                            //  与"编辑一定在右边、相反的操作就在左边"是同一条规范）。
                                            TextButton(onClick = { vm.openCancel(order.id) }) {
                                                Text("撤销", color = MaterialTheme.colorScheme.error)
                                            }
                                        }
                                    },
                                    extra = {
                                        if (!vm.selectionMode) {
                                            // 派单 = 这一页的**主操作** → 右边（惯用手是右手，够得着）
                                            TextButton(onClick = { vm.openAssign(order.id) }) {
                                                Text("派单")
                                            }
                                        }
                                    },
                                )
                            }
                        }
                    }
                }
            }
        }
    }

    // 派单弹窗（单选/批量共用）—— 与订单详情页共用同一份实现
    // （ui/dispatcher/AssignDriverDialog.kt：P8 按三种车型分档 + 标签跟选中的人走；⛔ 别在这里再写一份简化的）
    AssignDriverDialog(vm)

    // 选司机筛选抽屉（只在「已完成派单」那一档用得上）：形态与派单那颗一样 ——
    // 左栏车型分档 + 右栏名单，用户说的是「同样也是左边侧边栏」。
    if (vm.showDriverPicker) PoolDriverFilterDrawer(vm)

    // 改单抽屉 + 货物明细 + 加货选品（CHG-0040）：改完只通知司机，货主端一个字都不出。
    if (vm.editingOrder != null) PoolEditSheet(vm)
    if (vm.editingLine != null) PoolLineSheet(vm)
    if (vm.showLinePicker) {
        ProductPickerSheet(
            products = vm.products,
            loading = vm.loadingProducts,
            priceFor = { vm.priceFor(it) },
            categoryOrder = vm.categoryOrder,
            onConfirm = { picked -> vm.addPickedLines(picked) },
            onDismiss = { vm.showLinePicker = false },
        )
    }

    // 撤销确认
    if (vm.showCancelDialog) {
        AlertDialog(
            onDismissRequest = { vm.showCancelDialog = false },
            title = { Text("撤销订单") },
            text = {
                Column {
                    Text("确认撤销该订单？撤销后货主将在「已撤销」中看到该订单。")
                    // 失败原因画在**弹层里**（页面级 error 被弹层盖住，2026-09-23 真机抓到）
                    FormErrorLine(vm.dialogError)
                }
            },
            confirmButton = {
                TextButton(
                    onClick = { vm.confirmCancel() },
                    enabled = !vm.acting,
                    colors = ButtonDefaults.textButtonColors(contentColor = MaterialTheme.colorScheme.error),
                ) { Text("确认撤销") }
            },
            dismissButton = { TextButton(onClick = { vm.showCancelDialog = false }) { Text("再想想") } },
        )
    }

    // 退回派单池（静默动作：货主端看不到、也没有任何提醒 —— 用户 2026-10-05 明确要求）
    if (vm.showReleaseDialog) {
        AlertDialog(
            onDismissRequest = { vm.showReleaseDialog = false },
            title = { Text("退回派单池") },
            text = {
                Column {
                    Text("这一单会回到待派单池，司机那边立刻看不到它了。")
                    Spacer(Modifier.height(8.dp))
                    Text(
                        "货主端不会有任何变化：他看到的还是「已派单 / 已接单」，也不会有任何提醒。",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    Spacer(Modifier.height(12.dp))
                    OutlinedTextField(
                        value = vm.releaseReason,
                        onValueChange = { vm.releaseReason = it },
                        label = { Text("退回原因（可选，只有派单员看得到）") },
                        modifier = Modifier.fillMaxWidth(),
                    )
                    FormErrorLine(vm.dialogError)
                }
            },
            confirmButton = {
                TextButton(
                    onClick = { vm.confirmRelease() },
                    colors = ButtonDefaults.textButtonColors(contentColor = MaterialTheme.colorScheme.error),
                ) { Text("确认退回") }
            },
            dismissButton = { TextButton(onClick = { vm.showReleaseDialog = false }) { Text("再想想") } },
        )
    }
}

// ---- 「已完成派单」分页（CHG-0039）----
// 用户 2026-10-05：「司机一个卡片是一个司机，然后司机里面有很多小卡片，小卡片就是订单；
// 然后派单员可以点进去，对这些订单进行修改」—— 所以按司机分组：组头是人，下面挂他的单。

@Composable
private fun DispatchedList(vm: DispatcherPoolViewModel, onOpenOrder: (Long) -> Unit) {
    LazyColumn(
        Modifier.fillMaxSize(),
        contentPadding = PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        // 筛出来的空 ≠ 一单都没有：这两种空必须说不一样的话（否则「这位司机手上没单」会被
        // 读成「这些天白干了」）。没筛人时的空态由调用处那一支负责，这里只管筛空。
        if (vm.visibleGroups.isEmpty() && vm.driverFilterId != null) {
            item(key = "no-order-for-driver") {
                EmptyView("这位司机现在没有在途的单", Modifier.fillMaxWidth().padding(top = 40.dp))
            }
        }
        vm.visibleGroups.forEach { group ->
            item(key = "driver-" + (group.driverId ?: 0L)) { DriverGroupHeader(group) }
            items(group.orders, key = { "order-" + it.id }) { order ->
                OrderCard(
                    order = order,
                    onClick = { onOpenOrder(order.id) },
                    modifier = Modifier.padding(start = 14.dp),
                    showShipper = true,
                    // 退回池子 = 反向动作 → 左边（OrderCard 的规矩：左＝反向/警示，右＝编辑类）
                    leading = {
                        TextButton(onClick = { vm.openRelease(order.id) }) {
                            Text("退回池子", color = MaterialTheme.colorScheme.error)
                        }
                    },
                    // 编辑 = 编辑类动作 → 右边（用户 2026-09-22：「编辑一定在右边，惯用手是右手」）
                    extra = {
                        TextButton(onClick = { vm.openEdit(order) }) { Text("编辑") }
                    },
                )
            }
        }
        if (vm.dispatchedHitCap) {
            item(key = "dispatched-truncated-note") {
                TruncationNote(
                    limit = ORDER_LIST_LIMIT,
                    // ⛔ 这一档的截断只有一个来源：后端对 DISPATCHED / ACCEPTED 各自强制 300 条。
                    //    文案不许指向日期筛选那种页面上并不存在的东西（判据要求点名真实存在的入口，
                    //    或说「可能不全」）。「选司机」是筛不是翻页：筛完照样只有这 300 条。
                    howToSeeMore = "先退掉一两单（或等司机送达），后面的会自动补上来；这一档可能不全，别据此下结论",
                    modifier = Modifier.fillMaxWidth().padding(vertical = 8.dp),
                )
            }
        }
    }
}

@Composable
private fun DriverGroupHeader(group: DriverOrderGroup) {
    SectionCard(Modifier.fillMaxWidth()) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            TintedIcon(Icons.Default.Person, MaterialTheme.colorScheme.tertiary, size = 16.dp, container = 32.dp)
            Spacer(Modifier.width(10.dp))
            Column(Modifier.weight(1f)) {
                Text(
                    group.driverName,
                    // 定死自己的宽度：长名字否则会去挤右边的兄弟（判据 _check_adaptive_layout.py §5）
                    modifier = Modifier.fillMaxWidth(),
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.Bold,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
                val phone = group.driverPhone?.takeIf { it.isNotBlank() }
                Text(
                    (if (phone != null) phone + " · " else "") + group.orders.size + " 单",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
    }
}

// ---- 选司机（「已完成派单」顶栏那颗触发行拉出来的左侧抽屉，CHG-0040）----
//
// 形态与派单那颗完全一样（左栏车型分档 + 右栏名单）：用户说的是「同样也是左边侧边栏」。
// ⚠️ 抽屉底色不许在调用点传：全 App 的抽屉底由 ui/theme/Color.kt 的 SheetSurface 一处说了算。

@Composable
private fun PoolDriverFilterDrawer(vm: DispatcherPoolViewModel) {
    val scope = rememberCoroutineScope()
    val drawer = rememberDrawerState(DrawerValue.Open)
    // 抽屉被滑回去/点外面关掉时，状态也得跟着收 —— 不收的话下次点触发行会「打不开」
    // （showDriverPicker 还是 true，界面却不显示了：这正是本项目最讨厌的静默失效）。
    LaunchedEffect(drawer.currentValue) {
        if (drawer.currentValue == DrawerValue.Closed && vm.showDriverPicker) vm.showDriverPicker = false
    }
    // 档位是车型分组（判据就是 vehicle_type）：三种车各一档，没设过车型的账号单独一档。
    // ⛔ 没人的档不画（照 AssignDriverDialog 的老规矩）—— 画出来就是「点开抽屉第一眼看到
    // 『这一档还没有司机』」，而触发行刚刚才说过名册里有 25 位（2026-10-05 实机撞上的正是这个：
    // 默认落在空的「未设置车型」档 ⇒ 名册明明有 25 个人，抽屉里一个都不显示）。
    val kindOrder = listOf("small", "large", "trailer")
    val shownKinds = kindOrder.filter { k -> vm.drivers.any { (it.vehicleType ?: "") == k } } +
        if (vm.drivers.any { (it.vehicleType ?: "") !in kindOrder }) listOf("") else emptyList()
    // 打开时停在「现在筛的那位司机」所在的档：否则选了小车司机再打开抽屉，名单里找不到他。
    // 没筛人（或那位司机不在任何一档）时落在第一个真的有人 的档 —— ⛔ 空档当默认等于打开就是空名单。
    var pick by remember {
        val cur = vm.drivers.firstOrNull { it.id == vm.driverFilterId }?.vehicleType ?: ""
        mutableStateOf(if (shownKinds.contains(cur)) cur else shownKinds.firstOrNull() ?: "")
    }
    ModalNavigationDrawer(
        drawerState = drawer,
        gesturesEnabled = false,
        drawerContent = {
            ModalDrawerSheet {
                Row(Modifier.fillMaxSize()) {
                    MasterRail(
                        items = shownKinds.map {
                            RailItem(key = it, label = driverKindLabel(it.ifBlank { null }))
                        },
                        selectedKey = pick,
                        onSelect = { pick = it },
                        modifier = Modifier.width(104.dp).fillMaxHeight(),
                    )
                    Box(Modifier.weight(1f)) {
                        PersonDrawer(
                            title = "选择司机",
                            options = vm.drivers
                                .filter { (it.vehicleType ?: "") == pick }
                                .filter { d -> UserSearch.matches(vm.driverQuery, d.fullName, d.phone) }
                                .map { d ->
                                    PersonOption(
                                        key = d.id.toString(),
                                        title = d.fullName.ifBlank { d.username },
                                        subtitle = d.phone,
                                    )
                                },
                            selectedKey = vm.driverFilterId?.toString(),
                            query = vm.driverQuery,
                            onQueryChange = { vm.driverQuery = it },
                            onPick = { key ->
                                vm.pickDriver(key?.toLongOrNull())
                                scope.launch { drawer.close() }
                            },
                            emptyText = if (vm.driverQuery.isBlank()) {
                                "这一档还没有司机"
                            } else {
                                UserSearch.noMatchText(vm.driverQuery) + "司机"
                            },
                            allLabel = "全部司机",
                            allSubtitle = "不筛选，按司机分组显示所有单",
                        )
                    }
                }
            }
        },
    ) {
        // 抽屉是盖在内容上的一层：这里留空（透明），底下的列表与顶栏照旧看得见，
        // 关掉抽屉之后不需要任何还原动作。
        Box(Modifier.fillMaxSize())
    }
}

// ---- 改单（收货信息 + 货物明细，CHG-0040）----
//
// 用户 2026-10-05：「在这个阶段可以对订单进行更改，不管是货主、商品，全部都可以更改」
// 「如果更改的话，对应的司机是会收到消息的，说这个信息已经更改了」。
// ⛔ 货主归属不在这一层改（那是改账，不是改单）。

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun PoolEditSheet(vm: DispatcherPoolViewModel) {
    val order = vm.editingOrder ?: return
    ModalBottomSheet(
        onDismissRequest = { vm.closeEdit() },
        sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true),
    ) {
        Column(
            Modifier.fillMaxHeight().verticalScroll(rememberScrollState()).padding(horizontal = 16.dp),
        ) {
            Text("编辑订单", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
            Text(
                "#" + order.orderNo,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Spacer(Modifier.height(6.dp))
            // 与「退回池子」同一个口径：动作只对司机可见，货主端一个字都不出（用户明确要求）。
            Hint(
                "改完只通知司机，货主端不会有任何提醒。",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Spacer(Modifier.height(12.dp))
            // 房规（「分组一律白卡 + 共用行」）：输入一律走 `ui/common/FormRows.kt` 那套共用行，
            // ⛔ 卡里不许出现描边输入框（`_check_form_panel_style.py` 的全库总数只许减不许增）。
            FormTextAreaRow(
                "收货地址",
                vm.editAddress,
                { vm.editAddress = it },
                placeholder = "如 惠城区龙丰街道办前路130号",
            )
            FormInputRow(
                "收货人",
                vm.editDongjiaName,
                { vm.editDongjiaName = it },
                placeholder = "如 江水生",
            )
            FormInputRow(
                // 标签里必须带「电话」两个字 —— 输入规则判据按标签认这一格是什么（_check_input_rules.py）
                "收货人电话",
                vm.editDongjiaPhone,
                // 电话只让数字进来（规则唯一实现在 core/InputRules.kt，别在界面里另写一遍）
                { vm.editDongjiaPhone = InputRules.phoneInput(it) },
                keyboardType = KeyboardType.Phone,
                placeholder = "如 13575323478",
            )
            FormInputRow(
                "下单人",
                vm.editBossName,
                { vm.editBossName = it },
                placeholder = "如 家家福川菜馆",
            )
            FormInputRow(
                "下单人电话",
                vm.editBossPhone,
                { vm.editBossPhone = InputRules.phoneInput(it) },
                keyboardType = KeyboardType.Phone,
                placeholder = "如 13561342256",
            )
            FormTextAreaRow(
                "备注",
                vm.editRemark,
                { vm.editRemark = it },
                placeholder = "选填 · 给司机看的一句话",
            )
            FormErrorLine(vm.editError)
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End) {
                TextButton(onClick = { vm.closeEdit() }) { Text("取消") }
                TextButton(onClick = { vm.saveEdit() }) {
                    // 防连点：一次网络往返期间再点一次会改两遍，司机也会收到两条。
                    Text(if (vm.editBusy) "保存中…" else "保存收货信息")
                }
            }

            HorizontalDivider(Modifier.padding(vertical = 8.dp))
            Text("货物明细", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
            Spacer(Modifier.height(6.dp))
            when {
                // 空列表 + 正在拉 ≠ 这一单没有货：两种必须说不一样的话。
                vm.editLinesLoading -> Text(
                    "正在读这一单的货…",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                vm.editLines.isEmpty() -> Text(
                    "这一单还没有货物",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                else -> vm.editLines.forEach { line ->
                    Row(
                        Modifier.fillMaxWidth().padding(vertical = 6.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Column(Modifier.weight(1f)) {
                            Text(
                                line.productNameSnapshot,
                                // 定死自己的宽度：长货名否则会去挤右边那颗「改」
                                modifier = Modifier.fillMaxWidth(),
                                maxLines = 1,
                                overflow = TextOverflow.Ellipsis,
                            )
                            Text(
                                // 金额显示一律过漏斗（`_check_money_display.py` 的红线：`¥` 后面那个数
                                // 直接把后端 `60.0000` 印出来就是它要抓的形态）。这里用 `trimMoneyZeros`
                                // 而不是 `formatMoney`：与下面那个价框的预填同一个口径，`12.3456` 不会被印成 `12.35`。
                                "×" + line.quantity + line.unit + " · ¥" + trimMoneyZeros(line.unitPrice),
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        }
                        TextButton(onClick = { vm.openLineEdit(line) }) { Text("改") }
                    }
                }
            }
            TextButton(onClick = { vm.showLinePicker = true }) { Text("加一件货") }
            Spacer(Modifier.height(24.dp))
        }
    }
}

// ---- 改一件货（数量 + 单价 + 删掉，CHG-0040）----

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun PoolLineSheet(vm: DispatcherPoolViewModel) {
    val line = vm.editingLine ?: return
    ModalBottomSheet(
        onDismissRequest = { vm.closeLineEdit() },
        sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true),
    ) {
        Column(
            Modifier.fillMaxHeight().verticalScroll(rememberScrollState()).padding(horizontal = 16.dp),
        ) {
            Text("改这一件货", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
            Text(
                line.productNameSnapshot,
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Spacer(Modifier.height(12.dp))
            FormInputRow(
                "数量",
                vm.lineQty,
                { vm.lineQty = it },
                keyboardType = KeyboardType.Number,
                placeholder = "如 4",
            )
            FormInputRow(
                "单价（元）",
                vm.linePrice,
                // 金额过滤的唯一实现在 core/InputRules.kt：单价列 Numeric(14,4) ⇒ 走 priceInput（四位）
                { vm.linePrice = InputRules.priceInput(it) },
                keyboardType = KeyboardType.Decimal,
                placeholder = "如 52.1",
            )
            FormErrorLine(vm.editError)
            Row(
                Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                // 删 = 警示动作 → 左边（与卡片上「退回池子」同一个规矩）
                TextButton(onClick = { vm.deleteLine() }) {
                    Text("删掉这件货", color = MaterialTheme.colorScheme.error)
                }
                Row {
                    TextButton(onClick = { vm.closeLineEdit() }) { Text("取消") }
                    TextButton(onClick = { vm.saveLine() }) {
                        Text(if (vm.editBusy) "保存中…" else "保存")
                    }
                }
            }
            Spacer(Modifier.height(24.dp))
        }
    }
}
