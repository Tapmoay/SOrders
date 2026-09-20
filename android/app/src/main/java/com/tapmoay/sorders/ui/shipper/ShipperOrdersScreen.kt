package com.tapmoay.sorders.ui.shipper

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Remove
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.core.OrderStatusModel
import com.tapmoay.sorders.ui.common.*

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ShipperOrdersScreen(
    container: AppContainer,
    onBack: () -> Unit,
    onOpenOrder: (Long) -> Unit,
    onCreateOrder: () -> Unit,
) {
    val vm: ShipperOrdersViewModel = appViewModel { ShipperOrdersViewModel(container) }
    val snackbar = remember { SnackbarHostState() }

    OneShotSnackbar(snackbar, vm.actionResult, onConsumed = { vm.actionResult = null })

    Scaffold(
        snackbarHost = { SnackbarHost(snackbar) },
        topBar = {
            TopAppBar(
                title = { Text("我的订单") },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
                    }
                },
                actions = {
                    Button(
                        onClick = onCreateOrder,
                        colors = ButtonDefaults.buttonColors(
                            containerColor = com.tapmoay.sorders.ui.theme.MgrGreen.let { androidx.compose.ui.graphics.Color(it) },
                            contentColor = androidx.compose.ui.graphics.Color.White,
                        ),
                        contentPadding = androidx.compose.foundation.layout.PaddingValues(horizontal = 14.dp),
                        modifier = Modifier.height(36.dp),
                    ) {
                        Icon(Icons.Default.Add, contentDescription = null, modifier = Modifier.size(18.dp))
                        Spacer(Modifier.width(4.dp))
                        Text("新增订单", style = MaterialTheme.typography.labelLarge)
                    }
                    Spacer(Modifier.width(8.dp))
                },
            )
        },
    ) { padding ->
        Column(Modifier.fillMaxSize().padding(padding)) {
            SegmentedStatusTabs(
                labels = SHIPPER_TABS.map { it.label },
                colors = ORDER_TAB_COLORS,
                selected = vm.selectedTab,
                onSelect = { vm.selectTab(it) },
            )
            Box(Modifier.fillMaxSize()) {
                when {
                    vm.loading -> LoadingBox()
                    vm.error != null -> ErrorView(vm.error.orEmpty(), onRetry = { vm.load() })
                    vm.orders.isEmpty() -> EmptyView("暂无订单", Modifier.align(Alignment.Center))
                    else -> LazyColumn(
                        Modifier.fillMaxSize(),
                        contentPadding = PaddingValues(16.dp),
                        verticalArrangement = Arrangement.spacedBy(10.dp),
                    ) {
                item {
                    if (vm.selectedTab == 3 || vm.selectedTab == 4) {
                        DateRangeFilter(onChange = vm::applyRange)
                    }
                    // 列表可能被服务端截断时说清楚（见 ShipperOrdersViewModel.maybeTruncated）
                    if (vm.maybeTruncated) {
                        Text(
                            "只显示了最近 ${vm.orders.size} 条 —— 可能还有更早的订单没列出来。" +
                                "要按时间找，请用上面的日期筛选。",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp),
                        )
                    }
                    Spacer(Modifier.height(6.dp))
                }
                        items(vm.orders, key = { it.id }) { order ->
                            OrderCard(
                                order = order,
                                onClick = { onOpenOrder(order.id) },
                                extra = {
                                    // 待派单/已派单（司机未接）可卡片直撤，不进详情。
                                    // 状态门取 `OrderStatusModel.CANCELLABLE`（后端 `cancel_pending` 同一对取值）。
                                    if (order.status in OrderStatusModel.CANCELLABLE) {
                                        TextButton(
                                            onClick = { vm.cancelTarget = order },
                                            enabled = !vm.acting,
                                            shape = androidx.compose.foundation.shape.RoundedCornerShape(10.dp),
                                            colors = ButtonDefaults.textButtonColors(
                                                contentColor = Color(0xFFD32F2F),
                                            ),
                                            contentPadding = PaddingValues(horizontal = 0.dp, vertical = 2.dp),
                                            modifier = Modifier
                                                .height(32.dp)
                                                .defaultMinSize(minWidth = 0.dp, minHeight = 0.dp),
                                        ) {
                                            Text(
                                                "撤销订单",
                                                style = MaterialTheme.typography.labelMedium,
                                                fontWeight = FontWeight.Bold,
                                            )
                                        }
                                    }
                                    // 退货申请（2026-09-21 用户口径）：货主**只能在订单上申请**，
                                    // 派单员办理完那一刻库存与账本才变。三个分支互斥：
                                    //  · 已有待处理申请 → 「退货申请中」**不可点** + 「撤回申请」
                                    //    （再点一次必然被后端拒："这张单已经有一张待处理的退货申请了"）；
                                    //  · 已送达 + 还有可退量 + 没有待处理申请 → 「申请退货」；
                                    //  · 其余（没送达 / 退完了 / 拉不到待处理申请）→ 一个都不画。
                                    val pending = vm.pendingFor(order)
                                    if (pending != null) {
                                        TextButton(
                                            onClick = {},
                                            enabled = false,
                                            shape = androidx.compose.foundation.shape.RoundedCornerShape(10.dp),
                                            contentPadding = PaddingValues(horizontal = 0.dp, vertical = 2.dp),
                                            modifier = Modifier
                                                .height(32.dp)
                                                .defaultMinSize(minWidth = 0.dp, minHeight = 0.dp),
                                        ) {
                                            Text(
                                                "退货申请中",
                                                style = MaterialTheme.typography.labelMedium,
                                                fontWeight = FontWeight.Bold,
                                            )
                                        }
                                        Spacer(Modifier.width(10.dp))
                                        TextButton(
                                            onClick = { vm.askWithdraw(pending) },
                                            enabled = !vm.acting,
                                            shape = androidx.compose.foundation.shape.RoundedCornerShape(10.dp),
                                            colors = ButtonDefaults.textButtonColors(
                                                contentColor = Color(RETURN_ACCENT),
                                            ),
                                            contentPadding = PaddingValues(horizontal = 0.dp, vertical = 2.dp),
                                            modifier = Modifier
                                                .height(32.dp)
                                                .defaultMinSize(minWidth = 0.dp, minHeight = 0.dp),
                                        ) {
                                            Text(
                                                "撤回申请",
                                                style = MaterialTheme.typography.labelMedium,
                                                fontWeight = FontWeight.Bold,
                                            )
                                        }
                                    } else if (vm.canApplyReturn(order)) {
                                        TextButton(
                                            onClick = { vm.openReturn(order) },
                                            enabled = !vm.acting,
                                            shape = androidx.compose.foundation.shape.RoundedCornerShape(10.dp),
                                            colors = ButtonDefaults.textButtonColors(
                                                contentColor = Color(RETURN_ACCENT),
                                            ),
                                            contentPadding = PaddingValues(horizontal = 0.dp, vertical = 2.dp),
                                            modifier = Modifier
                                                .height(32.dp)
                                                .defaultMinSize(minWidth = 0.dp, minHeight = 0.dp),
                                        ) {
                                            Text(
                                                "申请退货",
                                                style = MaterialTheme.typography.labelMedium,
                                                fontWeight = FontWeight.Bold,
                                            )
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

    // 二次确认（防误触）
    vm.cancelTarget?.let { target ->
        DangerConfirmDialog(
            title = "确认撤销订单？",
            message = "订单 #" + target.orderNo + " 撤销后将不再处理。司机若已接单无法撤销。",
            confirmText = "确认撤销",
            onConfirm = { vm.confirmCancel() },
            onDismiss = { vm.cancelTarget = null },
        )
    }

    // 申请退货弹层（与派单员「订单管理」里那个退货弹窗**同形**：逐行勾数量 + 备注选填）。
    // ⚠️ 这里**不显示金额**：申请阶段后端一分钱都不算，客户端自己乘一遍就是第二份金额算法
    //    （本仓库的规矩是"钱只算一处"）。金额在派单员办理的回执里由后端给。
    vm.returnTarget?.let { order ->
        if (vm.showReturnDialog) {
            AlertDialog(
                onDismissRequest = { vm.dismissReturnDialog() },
                title = { Text("申请退货 " + order.orderNo) },
                text = {
                    Column {
                        Text(
                            "这只是申请：提交后库存和账本都不会变，等派单员办理完才变。",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                        Spacer(Modifier.height(8.dp))
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            TextButton(onClick = { vm.returnAll() }) { Text("全部勾满") }
                            TextButton(onClick = { vm.returnNone() }) { Text("全清零") }
                        }
                        order.orderProducts.forEach { line ->
                            val max = vm.maxReturnable(line)
                            val qty = vm.returnQty[line.id] ?: 0
                            Row(
                                verticalAlignment = Alignment.CenterVertically,
                                modifier = Modifier.fillMaxWidth().padding(vertical = 2.dp),
                            ) {
                                Column(Modifier.weight(1f)) {
                                    Text(line.productNameSnapshot, style = MaterialTheme.typography.bodyMedium)
                                    Text(
                                        buildString {
                                            append("下单 ").append(line.quantity)
                                            if (line.damageQuantity > 0) append(" · 货损 ").append(line.damageQuantity)
                                            if (line.returnedQuantity > 0) append(" · 已退 ").append(line.returnedQuantity)
                                            append(" · 可退 ").append(max)
                                        },
                                        style = MaterialTheme.typography.bodySmall,
                                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                                    )
                                }
                                IconButton(
                                    onClick = { vm.setReturnQty(line.id, qty - 1) },
                                    enabled = qty > 0,
                                ) { Icon(Icons.Default.Remove, contentDescription = "减") }
                                Text(qty.toString(), style = MaterialTheme.typography.titleMedium)
                                IconButton(
                                    onClick = { vm.setReturnQty(line.id, qty + 1) },
                                    enabled = qty < max,
                                ) { Icon(Icons.Default.Add, contentDescription = "加") }
                            }
                        }
                        Spacer(Modifier.height(8.dp))
                        Text(
                            "一共申请退 " + vm.returnTotalQty() + " 件。派单员只能按这个数量退，不能改。",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                        Spacer(Modifier.height(8.dp))
                        OutlinedTextField(
                            vm.returnNote,
                            { vm.returnNote = it },
                            label = { Text("退货备注（选填，会留痕）") },
                            minLines = 2,
                            modifier = Modifier.fillMaxWidth(),
                        )
                        // 失败原因（后端的 detail 中文）**画在弹层里**：
                        // 画在页面上会被这层弹窗盖住，用户看到的就是"点了没反应"
                        FormErrorLine(vm.returnFormError)
                    }
                },
                confirmButton = {
                    TextButton(
                        onClick = { vm.confirmApplyReturn() },
                        enabled = !vm.returnSubmitting,
                    ) { Text(if (vm.returnSubmitting) "提交中…" else "提交申请") }
                },
                dismissButton = {
                    TextButton(onClick = { vm.dismissReturnDialog() }, enabled = !vm.returnSubmitting) { Text("取消") }
                },
            )
        }
    }

    // 撤回申请（二次确认）：文案必须写清"撤回不是删除"
    vm.withdrawTarget?.let { req ->
        AlertDialog(
            onDismissRequest = { vm.cancelWithdraw() },
            title = { Text("撤回这张退货申请？") },
            text = {
                Column {
                    Text(
                        "订单 #" + req.orderNo + "：" + req.linesSummary,
                        style = MaterialTheme.typography.bodyMedium,
                    )
                    Spacer(Modifier.height(8.dp))
                    Text(
                        "撤回不是删除：申请记录留着，派单员看得到你提过又撤了。" +
                            "撤回后可以重新申请（想改数量只能这么改）。",
                        style = MaterialTheme.typography.bodyMedium,
                    )
                    FormErrorLine(vm.withdrawFormError)
                }
            },
            confirmButton = {
                TextButton(onClick = { vm.confirmWithdraw() }, enabled = !vm.acting) { Text("确认撤回") }
            },
            dismissButton = { TextButton(onClick = { vm.cancelWithdraw() }) { Text("取消") } },
        )
    }
}

/**
 * 「退货申请」这条线的语义色（与工作台那一格、模块图标同色）。
 *
 * 一色一功能：退货这条线在两端都是这个棕橙 —— 与订单列表里「已退货」那一档的棕橙
 * （`ORDER_TAB_COLORS` 的 `#BF5B00`）是**同一族但不同深浅**的两个色：
 * 那一档是**结果**（这单退掉了），这个是**入口**（我要申请退）。
 */
private val RETURN_ACCENT = 0xFFB3492FL
