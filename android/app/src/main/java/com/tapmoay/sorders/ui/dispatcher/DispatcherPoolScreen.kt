package com.tapmoay.sorders.ui.dispatcher

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.ui.common.*

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

    // 撤销确认
    if (vm.showCancelDialog) {
        AlertDialog(
            onDismissRequest = { vm.showCancelDialog = false },
            title = { Text("撤销订单") },
            text = { Text("确认撤销该订单？撤销后货主将在「已撤销」中看到该订单。") },
            confirmButton = {
                TextButton(
                    onClick = { vm.confirmCancel() },
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
        vm.dispatchedGroups.forEach { group ->
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
                )
            }
        }
        if (vm.dispatchedHitCap) {
            item(key = "dispatched-truncated-note") {
                TruncationNote(
                    limit = ORDER_LIST_LIMIT,
                    // 这一档没有任何筛选/搜索入口，只能靠「退回池子」把后面的挤上来 ——
                    // 所以文案不许指向日期筛选（判据要求点名页面上真实存在的东西，或说「可能不全」）
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
