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
                title = { Text("待派单池") },
                windowInsets = if (embedded) WindowInsets(0, 0, 0, 0) else TopAppBarDefaults.windowInsets,
                navigationIcon = {
                    if (!embedded) {
                        IconButton(onClick = onBack) {
                            Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
                        }
                    }
                },
                actions = {
                    if (vm.orders.isNotEmpty()) {
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
            if (vm.selectionMode) {
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
        Box(Modifier.fillMaxSize().padding(padding)) {
            when {
                vm.loading -> LoadingBox()
                vm.error != null -> ErrorView(vm.error.orEmpty(), onRetry = { vm.load() })
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
}
