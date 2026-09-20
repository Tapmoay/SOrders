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
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.ui.common.*

/**
 * 司机任务页。
 * - 独立页模式（默认）：有返回键 + 内部 TabRow（进行中/已完成）
 * - 嵌入式模式（embedded=true，作为底部导航内容）：隐藏返回/TabRow，
 *   由底部导航的两个 Tab 控制 tab，标题随 tabIndex 变化
 *
 * 顶栏（2026-09-20 用户点名）：「**先是左边是刷新键，然后右边就是这个时间排版**」——
 * 原来那行 9 个日期胶囊**太长、要横向滑动、右边还会被切掉**，换成右上角一个紧凑药丸
 * （当前窗口 + 下拉箭头），点开是**全部预设 + 自定义**。药丸只在「已完成」出现
 * （「进行中」没有日期窗口可挑）。
 *
 * ⚠️ 别把药丸藏进"列表非空"的分支里：这一页默认档位就是「今天」，今天没单时列表本来就是空的，
 *    藏起来用户就再也换不了档（2026-09-20 前一版正是这么把人困住的）。
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
    var showDatePresets by remember { mutableStateOf(false) }
    var showCustomRange by remember { mutableStateOf(false) }

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
                if (embedded) {
                    // 左：刷新。嵌入式下没有返回键，这个位置正好给刷新用。
                    IconButton(onClick = { vm.refresh() }) {
                        Icon(Icons.Default.Refresh, contentDescription = "刷新")
                    }
                } else {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
                    }
                }
            },
            actions = {
                // 右：时间药丸（只有「已完成」有日期窗口可挑）
                if (vm.tab == 1) {
                    DatePresetPill(label = vm.periodWord, onClick = { showDatePresets = true })
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
                // ⚠️ 切进「已完成」的那一瞬：屏幕上还挂着**上一栏（进行中）的单**，
                //    等盘点 + 取数跑完才换成已完成的 —— 不挡住的话就是"先闪一批进行中的单"。
                //    （2026-09-21 用户报的"闪两下"同族毛病；账本那几页也是同一道门。）
                vm.tab == 1 && !vm.windowSettled -> LoadingBox()
                vm.loading -> LoadingBox()
                vm.error != null -> ErrorView(vm.error.orEmpty(), onRetry = { vm.load() })
                else -> LazyColumn(
                    Modifier.fillMaxSize(),
                    contentPadding = PaddingValues(16.dp),
                    verticalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                    if (vm.orders.isEmpty()) {
                        item {
                            // 空态文案必须**指到右上角那个药丸**：默认档位是「今天」，
                            // 今天没单时这一页本来就该是空的，不指路就会被当成"坏了"。
                            EmptyView(
                                if (vm.tab == 0) {
                                    "暂无进行中任务，等派单员派单后这里会实时出现"
                                } else {
                                    "「" + vm.periodWord + "」没有已完成的订单 —— 点右上角可以换一段时间"
                                },
                                Modifier.fillMaxWidth().padding(top = 48.dp),
                            )
                        }
                    } else {
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

    // 档位清单（点顶栏那个药丸打开）：全部预设 + 自定义，当前那一档打勾
    if (showDatePresets) {
        DatePresetDialog(
            selected = vm.preset,
            customFrom = vm.customFrom,
            customTo = vm.customTo,
            onPick = { label ->
                showDatePresets = false
                // 「自定义」不由档位表给区间（它要选两头的日期）→ 直接开日期弹层
                if (label == DatePresets.CUSTOM) showCustomRange = true else vm.applyPreset(label)
            },
            onDismiss = { showDatePresets = false },
        )
    }
    // 自定义区间（日期弹层回来的）
    if (showCustomRange) {
        DateRangeDialog(
            initialFrom = vm.customFrom,
            initialTo = vm.customTo,
            onDismiss = { showCustomRange = false },
            onApply = { f, t -> vm.applyCustomRange(f, t) },
        )
    }
}
