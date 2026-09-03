package com.tapmoay.sorders.ui.dispatcher

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.foundation.clickable
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
import com.tapmoay.sorders.data.remote.dto.UserDto
import com.tapmoay.sorders.ui.common.*
import com.tapmoay.sorders.ui.nav.Routes

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
    var templatePick by remember { mutableStateOf(false) }

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
                            Text(if (vm.selectedIds.size == vm.orders.size && vm.orders.isNotEmpty()) "取消全选" else "全选")
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
                                extra = {
                                    if (!vm.selectionMode) {
                                        TextButton(onClick = { vm.openAssign(order.id) }) {
                                            Text("派单")
                                        }
                                        TextButton(onClick = { vm.openCancel(order.id) }) {
                                            Text("撤销", color = MaterialTheme.colorScheme.error)
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

    // 派单弹窗（单选/批量共用）
    if (vm.showAssignDialog) {
        AlertDialog(
            onDismissRequest = { vm.showAssignDialog = false },
            title = { Text(if (vm.selectionMode) "批量派单（" + vm.selectedIds.size + " 单）" else "派单") },
            text = {
                Column {
                    Text("选择司机", style = MaterialTheme.typography.labelLarge)
                    Spacer(Modifier.height(8.dp))
                    if (vm.drivers.isEmpty()) {
                        Text(
                            "暂无可用司机账号，请先在「司机管理」中添加",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.error,
                        )
                    } else {
                        var pickVehicle by remember { mutableStateOf(false) } // false=大车司机组, true=挂车司机组
                        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                            val selL = !pickVehicle
                            Surface(
                                color = if (selL) MaterialTheme.colorScheme.primary.copy(alpha = 0.14f) else MaterialTheme.colorScheme.surfaceVariant,
                                shape = MaterialTheme.shapes.small,
                                modifier = Modifier.weight(1f).clickable {
                                    pickVehicle = false
                                    vm.selectedDriverId = vm.drivers.firstOrNull { !vm.isPieceDriver(it) }?.id
                                },
                            ) {
                                Column(
                                    Modifier.fillMaxWidth().padding(vertical = 8.dp),
                                    horizontalAlignment = Alignment.CenterHorizontally,
                                ) {
                                    Icon(
                                        Icons.Default.LocalShipping, contentDescription = null,
                                        tint = if (selL) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurfaceVariant,
                                    )
                                    Spacer(Modifier.height(2.dp))
                                    Text(
                                        "大车司机",
                                        style = MaterialTheme.typography.labelMedium,
                                        fontWeight = if (selL) androidx.compose.ui.text.font.FontWeight.Bold else androidx.compose.ui.text.font.FontWeight.Normal,
                                        color = if (selL) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurfaceVariant,
                                    )
                                }
                            }
                            val selT = pickVehicle
                            Surface(
                                color = if (selT) MaterialTheme.colorScheme.primary.copy(alpha = 0.14f) else MaterialTheme.colorScheme.surfaceVariant,
                                shape = MaterialTheme.shapes.small,
                                modifier = Modifier.weight(1f).clickable {
                                    pickVehicle = true
                                    vm.selectedDriverId = vm.drivers.firstOrNull { vm.isPieceDriver(it) }?.id
                                },
                            ) {
                                Column(
                                    Modifier.fillMaxWidth().padding(vertical = 8.dp),
                                    horizontalAlignment = Alignment.CenterHorizontally,
                                ) {
                                    Icon(
                                        Icons.Default.AirportShuttle, contentDescription = null,
                                        tint = if (selT) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurfaceVariant,
                                    )
                                    Spacer(Modifier.height(2.dp))
                                    Text(
                                        "挂车司机",
                                        style = MaterialTheme.typography.labelMedium,
                                        fontWeight = if (selT) androidx.compose.ui.text.font.FontWeight.Bold else androidx.compose.ui.text.font.FontWeight.Normal,
                                        color = if (selT) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurfaceVariant,
                                    )
                                }
                            }
                        }
                        Spacer(Modifier.height(8.dp))
                        var dExp by remember { mutableStateOf(false) }
                        ExposedDropdownMenuBox(expanded = dExp, onExpandedChange = { dExp = it }) {
                            OutlinedTextField(
                                value = if (vm.selectedDriver != null) (vm.selectedDriver?.fullName?.ifBlank { vm.selectedDriver?.username ?: "" } ?: "") + " " + (vm.selectedDriver?.phone ?: "") else "请选择司机",
                                onValueChange = {},
                                readOnly = true,
                                label = { Text(if (pickVehicle) "挂车司机（按单计费）" else "大车司机（固定工资）") },
                                trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(expanded = dExp) },
                                modifier = Modifier.fillMaxWidth().menuAnchor(),
                            )
                            ExposedDropdownMenu(expanded = dExp, onDismissRequest = { dExp = false }) {
                                vm.drivers.filter { vm.isPieceDriver(it) == pickVehicle }.forEach { d ->
                                    DropdownMenuItem(
                                        text = { Text((d.fullName.ifBlank { d.username }) + " " + d.phone) },
                                        onClick = {
                                            vm.selectedDriverId = d.id
                                            dExp = false
                                        },
                                    )
                                }
                            }
                        }
                    }
                    Spacer(Modifier.height(12.dp))
                    if (!vm.selectionMode && vm.isPieceDriver(vm.selectedDriver)) {
                        Text("运费（该司机按单计费）", style = MaterialTheme.typography.labelLarge)
                        Spacer(Modifier.height(6.dp))
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            OutlinedTextField(
                                value = vm.assignFreight,
                                onValueChange = { vm.assignFreight = it },
                                label = { Text("一车运费 ¥（可后补）") },
                                singleLine = true,
                                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                                modifier = Modifier.weight(1f),
                            )
                            Spacer(Modifier.width(8.dp))
                            TextButton(onClick = { templatePick = true }) { Text("模板") }
                        }
                        Spacer(Modifier.height(8.dp))
                    }
                    Spacer(Modifier.height(4.dp))
                    Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.fillMaxWidth()) {
                        Checkbox(
                            checked = vm.assignCollectCash,
                            onCheckedChange = { vm.assignCollectCash = it },
                        )
                        Spacer(Modifier.width(8.dp))
                        Column {
                            Text("收取现金", style = MaterialTheme.typography.bodyMedium, fontWeight = androidx.compose.ui.text.font.FontWeight.Bold)
                            Text(
                                "勾选后司机送达时可选择「收现金」或「挂账」；不勾选则送达自动挂账",
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        }
                    }
                    Spacer(Modifier.height(4.dp))
                    OutlinedTextField(
                        value = vm.assignNote,
                        onValueChange = { vm.assignNote = it },
                        label = { Text("内部备注（可选，与司机可见）") },
                        minLines = 2,
                        modifier = Modifier.fillMaxWidth(),
                    )
                }
            },
            confirmButton = {
                TextButton(onClick = { vm.confirmAssign() }, enabled = !vm.acting) {
                    Text(if (vm.acting) "派单中…" else "确认派单")
                }
            },
            dismissButton = { TextButton(onClick = { vm.showAssignDialog = false }) { Text("取消") } },
        )
    }

    // 运费模板选择
    if (templatePick) {
        AlertDialog(
            onDismissRequest = { templatePick = false },
            title = { Text("选择运费模板") },
            text = {
                Column(Modifier.heightIn(max = 320.dp)) {
                    if (vm.templates.isEmpty()) {
                        Text(
                            "暂无模板，请先在「订单模板」中维护",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    } else {
                        vm.templates.forEach { t ->
                            Row(
                                Modifier.fillMaxWidth().clickable {
                                    vm.applyTemplate(t)
                                    templatePick = false
                                }.padding(vertical = 6.dp),
                                verticalAlignment = Alignment.CenterVertically,
                            ) {
                                Column(Modifier.weight(1f)) {
                                    Text(t.name, style = MaterialTheme.typography.bodyMedium, fontWeight = androidx.compose.ui.text.font.FontWeight.Bold)
                                    Text(
                                        t.fromPlace + " → " + t.toPlace +
                                            (t.vehicleType?.let { v -> when (v) {
                                                "small" -> " · 小车"; "large" -> " · 大车"; "trailer" -> " · 挂车"; else -> "" } } ?: ""),
                                        style = MaterialTheme.typography.bodySmall,
                                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                                    )
                                }
                                Text(
                                    "¥" + t.fee,
                                    style = MaterialTheme.typography.titleSmall,
                                    fontWeight = androidx.compose.ui.text.font.FontWeight.Bold,
                                    color = androidx.compose.ui.graphics.Color(0xFFFF9500),
                                )
                            }
                            HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
                        }
                    }
                }
            },
            confirmButton = { TextButton(onClick = { templatePick = false }) { Text("关闭") } },
        )
    }

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
