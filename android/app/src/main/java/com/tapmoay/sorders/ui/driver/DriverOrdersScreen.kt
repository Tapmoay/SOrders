package com.tapmoay.sorders.ui.driver

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.ui.common.*

/**
 * 司机任务页。
 * - 独立页模式（默认）：有返回键 + 内部 TabRow（进行中/已完成）
 * - 嵌入式模式（embedded=true，作为底部导航内容）：隐藏返回/TabRow，
 *   由底部导航的两个 Tab 控制 tab，标题随 tabIndex 变化；右上角放消息铃铛（未读角标）
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DriverOrdersScreen(
    container: AppContainer,
    onBack: () -> Unit,
    onOpenOrder: (Long) -> Unit,
    tabIndex: Int = -1,
    embedded: Boolean = false,
) {
    val vm: DriverOrdersViewModel = appViewModel { DriverOrdersViewModel(container) }

    // 嵌入式：底部导航负责 tab 切换，同步 VM 选中态
    LaunchedEffect(tabIndex) {
        if (tabIndex >= 0) vm.selectTab(tabIndex)
    }

    Column(Modifier.fillMaxSize()) {
        TopAppBar(
            title = {
                Text(
                    when {
                        tabIndex == 1 -> "已完成"
                        tabIndex == 0 -> "进行中"
                        else -> "我的任务"
                    }
                )
            },
            windowInsets = if (embedded) WindowInsets(0, 0, 0, 0) else TopAppBarDefaults.windowInsets,
            navigationIcon = {
                if (!embedded) {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
                    }
                }
            },
            actions = {
                IconButton(onClick = { vm.refresh() }) {
                    Icon(Icons.Default.Refresh, contentDescription = "刷新")
                }
            },
        )
        if (!embedded) {
            SegmentedStatusTabs(
                labels = listOf("进行中", "已完成"),
                colors = listOf(
                    androidx.compose.ui.graphics.Color(0xFFFFB300),
                    androidx.compose.ui.graphics.Color(0xFF00B578),
                ),
                selected = vm.tab,
                onSelect = { vm.selectTab(it) },
            )
        }
        Box(Modifier.fillMaxSize()) {
            when {
                vm.loading -> LoadingBox()
                vm.error != null -> ErrorView(vm.error.orEmpty(), onRetry = { vm.load() })
                vm.orders.isEmpty() -> EmptyView(
                    if (vm.tab == 0) "暂无进行中任务，等派单员派单后这里会实时出现" else "暂无已完成任务",
                    Modifier.align(Alignment.Center),
                )
                else -> LazyColumn(
                    Modifier.fillMaxSize(),
                    contentPadding = PaddingValues(16.dp),
                    verticalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                item {
                    if (vm.tab == 1) {
                        DateRangeFilter(onChange = vm::applyRange)
                    }
                    Spacer(Modifier.height(6.dp))
                }
                    items(vm.orders, key = { it.id }) { order ->
                        Column {
                            if (order.isNewForDriver) {
                                Surface(
                                    color = MaterialTheme.colorScheme.errorContainer,
                                    shape = MaterialTheme.shapes.small,
                                ) {
                                    Text(
                                        "新任务",
                                        style = MaterialTheme.typography.labelMedium,
                                        color = MaterialTheme.colorScheme.onErrorContainer,
                                        modifier = Modifier.padding(horizontal = 8.dp, vertical = 2.dp),
                                    )
                                }
                                Spacer(Modifier.height(6.dp))
                            }
                            OrderCard(order = order, onClick = { onOpenOrder(order.id) }, driverMode = true, highlight = vm.tab == 0)
                        }
                    }
                }
            }
        }
    }
}
