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
import com.tapmoay.sorders.ui.nav.Routes

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DispatcherOrdersScreen(
    container: AppContainer,
    onBack: () -> Unit,
    onOpenOrder: (Long) -> Unit,
) {
    val vm: DispatcherOrdersViewModel = appViewModel { DispatcherOrdersViewModel(container) }
    val snackbar = remember { SnackbarHostState() }

    LaunchedEffect(vm.actionResult) {
        vm.actionResult?.let {
            snackbar.showSnackbar(it)
            vm.actionResult = null
        }
    }

    Scaffold(
        snackbarHost = { SnackbarHost(snackbar) },
        topBar = {
            TopAppBar(
                title = { Text("全部订单") },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
                    }
                },
            )
        },
    ) { padding ->
        Column(Modifier.fillMaxSize().padding(padding)) {
            // 搜索框
            Row(
                Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                OutlinedTextField(
                    value = vm.search,
                    onValueChange = { vm.search = it },
                    placeholder = { Text("搜索单号/货主/司机/地址") },
                    singleLine = true,
                    leadingIcon = { Icon(Icons.Default.Search, contentDescription = null) },
                    modifier = Modifier.weight(1f),
                )
                Spacer(Modifier.width(8.dp))
                FilledTonalButton(onClick = { vm.searchNow() }) { Text("搜索") }
            }
            SegmentedStatusTabs(
                labels = DISPATCH_TABS.map { it.second },
                colors = ORDER_TAB_COLORS,
                selected = vm.tab,
                onSelect = { vm.selectTab(it) },
            )
            Box(Modifier.fillMaxSize()) {
                when {
                    vm.loading -> LoadingBox()
                    vm.error != null -> ErrorView(vm.error.orEmpty(), onRetry = { vm.load() })
                    vm.orders.isEmpty() -> EmptyView("没有匹配的订单", Modifier.align(Alignment.Center))
                    else -> LazyColumn(
                        Modifier.fillMaxSize(),
                        contentPadding = PaddingValues(16.dp),
                        verticalArrangement = Arrangement.spacedBy(10.dp),
                    ) {
                item {
                    if (vm.tab == 3 || vm.tab == 4) {
                        DateRangeFilter(onChange = vm::applyRange)
                    }
                    Spacer(Modifier.height(6.dp))
                }
                        items(vm.orders, key = { it.id }) { order ->
                            OrderCard(
                                order = order,
                                onClick = { onOpenOrder(order.id) },
                                showDriver = true,
                                showShipper = true,
                                extra = {
                                    IconButton(onClick = { vm.openEdit(order) }) {
                                        Icon(Icons.Default.Edit, contentDescription = "编辑", modifier = Modifier.size(18.dp))
                                    }
                                    IconButton(onClick = { vm.openException(order) }) {
                                        Icon(
                                            if (order.isException) Icons.Default.Report else Icons.Default.WarningAmber,
                                            contentDescription = "异常",
                                            tint = if (order.isException) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.tertiary,
                                            modifier = Modifier.size(18.dp),
                                        )
                                    }
                                    if (order.status == "ACCEPTED") {
                                        TextButton(onClick = { vm.openRecall(order) }) {
                                            Text("撤回", color = MaterialTheme.colorScheme.error)
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

    // 编辑弹窗
    if (vm.showEditDialog) {
        AlertDialog(
            onDismissRequest = { vm.showEditDialog = false },
            title = { Text("编辑订单 " + (vm.editingOrder?.orderNo ?: "")) },
            text = {
                Column {
                    OutlinedTextField(vm.editAddress, { vm.editAddress = it }, label = { Text("收货地址") }, minLines = 2, modifier = Modifier.fillMaxWidth())
                    Spacer(Modifier.height(8.dp))
                    OutlinedTextField(vm.editDongjia, { vm.editDongjia = it }, label = { Text("东家电话") }, singleLine = true, modifier = Modifier.fillMaxWidth())
                    Spacer(Modifier.height(8.dp))
                    OutlinedTextField(vm.editBoss, { vm.editBoss = it }, label = { Text("老板电话") }, singleLine = true, modifier = Modifier.fillMaxWidth())
                    Spacer(Modifier.height(8.dp))
                    OutlinedTextField(vm.editRemark, { vm.editRemark = it }, label = { Text("备注") }, minLines = 2, modifier = Modifier.fillMaxWidth())
                    Spacer(Modifier.height(8.dp))
                    OutlinedTextField(vm.editInternal, { vm.editInternal = it }, label = { Text("内部备注（司机/派单可见）") }, minLines = 2, modifier = Modifier.fillMaxWidth())
                }
            },
            confirmButton = { TextButton(onClick = { vm.saveEdit() }, enabled = !vm.acting) { Text("保存") } },
            dismissButton = { TextButton(onClick = { vm.showEditDialog = false }) { Text("取消") } },
        )
    }

    // 撤回派单弹窗
    if (vm.showRecallDialog) {
        AlertDialog(
            onDismissRequest = { vm.showRecallDialog = false },
            title = { Text("撤回派单") },
            text = {
                Column {
                    Text("撤回后订单回到「派单中」，司机端将收到撤回通知。")
                    Spacer(Modifier.height(10.dp))
                    OutlinedTextField(
                        vm.recallReason,
                        { vm.recallReason = it },
                        label = { Text("撤回原因（必填，将留痕）") },
                        minLines = 2,
                        modifier = Modifier.fillMaxWidth(),
                    )
                }
            },
            confirmButton = {
                TextButton(
                    onClick = { vm.confirmRecall() },
                    enabled = !vm.acting,
                    colors = ButtonDefaults.textButtonColors(contentColor = MaterialTheme.colorScheme.error),
                ) { Text("确认撤回") }
            },
            dismissButton = { TextButton(onClick = { vm.showRecallDialog = false }) { Text("取消") } },
        )
    }

    // 异常登记弹窗
    if (vm.showExceptionDialog) {
        AlertDialog(
            onDismissRequest = { vm.showExceptionDialog = false },
            title = { Text("异常登记") },
            text = {
                Column {
                    OutlinedTextField(vm.exceptionReason, { vm.exceptionReason = it }, label = { Text("异常原因") }, minLines = 2, modifier = Modifier.fillMaxWidth())
                    Spacer(Modifier.height(8.dp))
                    OutlinedTextField(vm.exceptionResolution, { vm.exceptionResolution = it }, label = { Text("处理方案") }, minLines = 2, modifier = Modifier.fillMaxWidth())
                    Spacer(Modifier.height(8.dp))
                    OutlinedTextField(
                        vm.expectedBefore,
                        { vm.expectedBefore = it },
                        label = { Text("预计送达时间（如 2026-08-01 18:00）") },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth(),
                    )
                }
            },
            confirmButton = { TextButton(onClick = { vm.confirmException() }, enabled = !vm.acting) { Text("登记") } },
            dismissButton = { TextButton(onClick = { vm.showExceptionDialog = false }) { Text("取消") } },
        )
    }
}
