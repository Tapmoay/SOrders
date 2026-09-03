package com.tapmoay.sorders.ui.shipper

import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsPressedAsState
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Close
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.tapmoay.sorders.core.AppContainer
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
                    Spacer(Modifier.height(6.dp))
                }
                        items(vm.orders, key = { it.id }) { order ->
                            OrderCard(
                                order = order,
                                onClick = { onOpenOrder(order.id) },
                                extra = {
                                    // 待派单/已派单（司机未接）可卡片直撤，不进详情
                                    if (order.status == "PENDING_DISPATCH" || order.status == "DISPATCHED") {
                                        TextButton(
                                            onClick = { vm.cancelTarget = order },
                                            enabled = !vm.acting,
                                            shape = androidx.compose.foundation.shape.RoundedCornerShape(10.dp),
                                            colors = ButtonDefaults.textButtonColors(
                                                contentColor = androidx.compose.ui.graphics.Color(0xFFD32F2F),
                                            ),
                                            contentPadding = PaddingValues(horizontal = 0.dp, vertical = 2.dp),
                                            modifier = Modifier
                                                .height(32.dp)
                                                .defaultMinSize(minWidth = 0.dp, minHeight = 0.dp),
                                        ) {
                                            Text(
                                                "撤销订单",
                                                style = MaterialTheme.typography.labelMedium,
                                                fontWeight = androidx.compose.ui.text.font.FontWeight.Bold,
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
}
