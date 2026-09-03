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
import com.tapmoay.sorders.data.remote.dto.InventoryMovementDto
import com.tapmoay.sorders.data.remote.dto.InventorySummaryItemDto
import com.tapmoay.sorders.ui.common.*
import com.tapmoay.sorders.util.formatDateTime

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun InventoryScreen(
    container: AppContainer,
    onBack: () -> Unit,
) {
    val vm: InventoryViewModel = appViewModel { InventoryViewModel(container) }
    val snackbar = remember { SnackbarHostState() }
    var showMovements by remember { mutableStateOf(false) }

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
                title = { Text("库存管理") },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
                    }
                },
                actions = {
                    IconButton(onClick = { vm.refresh() }) {
                        Icon(Icons.Default.Refresh, contentDescription = "刷新")
                    }
                    TextButton(onClick = { showMovements = true }) { Text("流水") }
                },
            )
        },
    ) { padding ->
        Box(Modifier.fillMaxSize().padding(padding)) {
            when {
                vm.loading -> LoadingBox()
                vm.error != null -> ErrorView(vm.error.orEmpty(), onRetry = { vm.load() })
                vm.summary.isEmpty() -> EmptyView("暂无商品，请先在商品管理中创建", Modifier.align(Alignment.Center))
                else -> LazyColumn(
                    Modifier.fillMaxSize(),
                    contentPadding = PaddingValues(16.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    item {
                        Text(
                            "实时库存（低库存在前）",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                    items(vm.summary, key = { it.productId }) { s ->
                        StockCard(
                            s = s,
                            onInbound = {
                                vm.products.firstOrNull { it.id == s.productId }?.let { p ->
                                    vm.openMovement(p, inbound = true)
                                }
                            },
                            onOutbound = {
                                vm.products.firstOrNull { it.id == s.productId }?.let { p ->
                                    vm.openMovement(p, inbound = false)
                                }
                            },
                        )
                    }
                }
            }
        }
    }

    // 出入库弹窗
    if (vm.showMovementDialog) {
        AlertDialog(
            onDismissRequest = { vm.showMovementDialog = false },
            title = { Text(if (vm.movementInbound) "入库" else "出库") },
            text = {
                Column {
                    Text(
                        "商品：" + (vm.movementProduct?.name ?: "") +
                            "（当前库存 " + (vm.movementProduct?.stock ?: 0) + "）",
                        style = MaterialTheme.typography.bodyMedium,
                    )
                    Spacer(Modifier.height(10.dp))
                    SoTextField(
                        vm.movementQty,
                        { vm.movementQty = it.filter { c -> c.isDigit() } },
                        placeholder = "数量",
                        modifier = Modifier.fillMaxWidth(),
                    )
                    Spacer(Modifier.height(8.dp))
                    SoTextField(
                        vm.movementNote,
                        { vm.movementNote = it },
                        placeholder = "备注（如供应商/用途）",
                        modifier = Modifier.fillMaxWidth(),
                    )
                    if (!vm.movementInbound) {
                        Spacer(Modifier.height(6.dp))
                        Text(
                            "出库数量不能超过当前库存 " + (vm.movementProduct?.stock ?: 0),
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.error,
                        )
                    }
                }
            },
            confirmButton = {
                TextButton(onClick = { vm.confirmMovement() }, enabled = !vm.acting) {
                    Text(if (vm.acting) "处理中…" else "确认" + (if (vm.movementInbound) "入库" else "出库"))
                }
            },
            dismissButton = { TextButton(onClick = { vm.showMovementDialog = false }) { Text("取消") } },
        )
    }

    // 流水弹层
    if (showMovements) {
        ModalBottomSheet(onDismissRequest = { showMovements = false }) {
            Column(Modifier.padding(horizontal = 20.dp).padding(bottom = 32.dp)) {
                Text("出入库流水", style = MaterialTheme.typography.titleLarge)
                Spacer(Modifier.height(10.dp))
                DateRangeFilter(onChange = vm::applyMovFilter)
                Spacer(Modifier.height(8.dp))
                if (vm.movements.isEmpty()) {
                    Text(
                        "暂无流水记录",
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.padding(vertical = 24.dp),
                    )
                } else {
                    LazyColumn(Modifier.heightIn(max = 420.dp)) {
                        items(vm.movements, key = { it.id }) { m ->
                            MovementRow(m)
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun StockCard(
    s: InventorySummaryItemDto,
    onInbound: () -> Unit,
    onOutbound: () -> Unit,
) {
    val low = s.lowStockAlert > 0 && s.stock <= s.lowStockAlert
    SectionCard {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text(s.productName, style = MaterialTheme.typography.titleSmall)
                Spacer(Modifier.height(4.dp))
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        "库存 " + s.stock + " " + s.unit,
                        style = MaterialTheme.typography.bodyMedium,
                        color = if (low) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.primary,
                    )
                    if (low) {
                        Spacer(Modifier.width(8.dp))
                        Surface(color = MaterialTheme.colorScheme.errorContainer, shape = MaterialTheme.shapes.small) {
                            Text(
                                "低库存",
                                style = MaterialTheme.typography.labelMedium,
                                color = MaterialTheme.colorScheme.onErrorContainer,
                                modifier = Modifier.padding(horizontal = 6.dp, vertical = 1.dp),
                            )
                        }
                    }
                }
            }
            FilledTonalButton(onClick = onInbound, contentPadding = PaddingValues(horizontal = 12.dp)) {
                Text("入库")
            }
            Spacer(Modifier.width(8.dp))
            OutlinedButton(
                onClick = onOutbound,
                enabled = s.stock > 0,
                contentPadding = PaddingValues(horizontal = 12.dp),
            ) { Text("出库") }
        }
    }
}

@Composable
private fun MovementRow(m: InventoryMovementDto) {
    val inbound = m.change > 0
    Row(
        Modifier.fillMaxWidth().padding(vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Surface(
            color = if (inbound) MaterialTheme.colorScheme.primaryContainer else MaterialTheme.colorScheme.errorContainer,
            shape = MaterialTheme.shapes.small,
        ) {
            Text(
                (if (inbound) "+" else "") + m.change,
                style = MaterialTheme.typography.titleSmall,
                color = if (inbound) MaterialTheme.colorScheme.onPrimaryContainer else MaterialTheme.colorScheme.onErrorContainer,
                modifier = Modifier.padding(horizontal = 8.dp, vertical = 3.dp),
            )
        }
        Spacer(Modifier.width(10.dp))
        Column(Modifier.weight(1f)) {
            Text(
                if (m.note.isBlank()) (if (inbound) "入库" else "出库") else m.note,
                style = MaterialTheme.typography.bodyMedium,
                maxLines = 1,
            )
            Text(
                formatDateTime(m.createdAt),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.outline,
            )
        }
    }
}
