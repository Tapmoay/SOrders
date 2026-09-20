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
import com.tapmoay.sorders.core.InputRules
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
    var templatePick by remember { mutableStateOf(false) }

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
                        // ⚠️ 这两个页签是**车型**分组（标签就写着大车/挂车），所以按 `vehicle_type` 过滤。
                        //    原来用的判据是"按不按单计费"（`isPieceDriver`）——两者只因"挂车默认按单"
                        //    而恰好重合；挂了计费规则之后就会错位（大车司机跑到"挂车司机"组里）。
                        //    "要不要显示运费框"是另一件事，它只看 `isPieceDriver`（后端口径，见下方）。
                        var pickVehicle by remember { mutableStateOf(false) } // false=大车组, true=挂车组
                        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                            val selL = !pickVehicle
                            Surface(
                                color = if (selL) MaterialTheme.colorScheme.primary.copy(alpha = 0.14f) else MaterialTheme.colorScheme.surfaceVariant,
                                shape = MaterialTheme.shapes.small,
                                modifier = Modifier.weight(1f).clickable {
                                    pickVehicle = false
                                    vm.selectedDriverId = vm.drivers.firstOrNull { it.vehicleType != "trailer" }?.id
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
                                    vm.selectedDriverId = vm.drivers.firstOrNull { it.vehicleType == "trailer" }?.id
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
                                label = { Text(if (pickVehicle) "挂车司机" else "大车司机") },
                                trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(expanded = dExp) },
                                modifier = Modifier.fillMaxWidth().menuAnchor(),
                            )
                            ExposedDropdownMenu(expanded = dExp, onDismissRequest = { dExp = false }) {
                                vm.drivers.filter { (it.vehicleType == "trailer") == pickVehicle }.forEach { d ->
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
                                // 金额规则唯一实现在 core/InputRules.kt（原来这三个框都没有过滤）
                                onValueChange = { vm.assignFreight = InputRules.moneyInput(it) },
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
                    val ruleName = vm.selectedDriver?.driverRuleName?.takeIf { it.isNotBlank() }
                    if (!vm.selectionMode && ruleName != null) {
                        Text("这一单单独定（不填就按他的规则算）", style = MaterialTheme.typography.labelLarge)
                        Spacer(Modifier.height(4.dp))
                        Text(
                            "他现在的规则：$ruleName" +
                                vm.selectedDriver?.paySummary?.takeIf { it.isNotBlank() }?.let { " · $it" }.orEmpty(),
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                        Spacer(Modifier.height(6.dp))
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            OutlinedTextField(
                                value = vm.assignPieceAmount,
                                onValueChange = { vm.assignPieceAmount = InputRules.moneyInput(it) },
                                label = { Text("这一单的钱 ¥") },
                                singleLine = true,
                                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                                modifier = Modifier.weight(1f),
                            )
                            OutlinedTextField(
                                value = vm.assignCommissionRate,
                                onValueChange = { vm.assignCommissionRate = InputRules.moneyInput(it, maxDecimals = 2, maxWhole = 3) },
                                label = { Text("提成 %") },
                                singleLine = true,
                                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                                modifier = Modifier.weight(1f),
                            )
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
