package com.tapmoay.sorders.ui.dispatcher.report

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.Menu
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.DrawerValue
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalDrawerSheet
import androidx.compose.material3.ModalNavigationDrawer
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.rememberDrawerState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.ui.common.AppTopBar
import com.tapmoay.sorders.ui.common.CategoryDrawerWidth
import com.tapmoay.sorders.ui.common.DateFilterDialogs
import com.tapmoay.sorders.ui.common.DatePresetPill
import com.tapmoay.sorders.ui.common.DatePresets
import com.tapmoay.sorders.ui.common.ErrorView
import com.tapmoay.sorders.ui.common.LoadingBox
import com.tapmoay.sorders.ui.common.appViewModel
import kotlinx.coroutines.launch

/**
 * 报表中心（v2）—— CHG-0034 的新首页 + 下钻树，**唯一的外壳**。
 *
 * 形状（用户 2026-10-05 定的）：
 * · 一进来是一张「五张表」的卡：利润表 / 资产负债表 / 现金流量表 / 运营分析表 / 关键指标表，
 *   每行像按钮 —— 点进去一层层变细，最底下是**一张订单**；
 * · 右上角一颗时间药丸（日历图标 + 当前区间 + ▾），八档 + 自选起止；
 * · 左上角汉堡打开**左侧抽屉**：老 11 个入口一个都没少（用户：「原先的也做一个保存」）；
 * · 屏上不出现接口字段名、不出现 JSON —— 要核对原文的走老页面（抽屉里那 11 项）。
 *
 * ⚠️ 窗口先定下来再取数（[ReportV2ViewModel.windowSettled]）：定下来之前整页是 loading，
 *    **一次都不画错窗口**（用户 2026-09-21 报过"闪两下"）。
 * ⚠️ 老实现（ReportCenter.kt / ReportCenterViewModel.kt 那 11 个页签）一个字都没动：
 *    抽屉里点老入口就是切到那条老路由（[onOpenTab] → Routes.REPORT_*）。
 */
@Composable
fun ReportV2Screen(
    container: AppContainer,
    onBack: () -> Unit,
    onOpenTab: (Int) -> Unit,
    onOpenOrder: (Long) -> Unit,
) {
    val vm: ReportV2ViewModel = appViewModel { ReportV2ViewModel(container) }
    val drawer = rememberDrawerState(DrawerValue.Closed)
    val scope = rememberCoroutineScope()
    var showPresets by remember { mutableStateOf(false) }

    // 系统返回：还在下钻里就先回上一级（不然一下退出整个报表中心）
    BackHandler(enabled = vm.stack.size > 1) { vm.backOne() }

    ModalNavigationDrawer(
        drawerState = drawer,
        drawerContent = {
            ModalDrawerSheet(modifier = Modifier.width(CategoryDrawerWidth)) {
                ReportV2Drawer(
                    vm = vm,
                    onPickHome = {
                        scope.launch { drawer.close() }
                        vm.backToHome()
                    },
                    onPickTab = { tab ->
                        scope.launch { drawer.close() }
                        onOpenTab(tab)
                    },
                )
            }
        },
    ) {
        Scaffold(
            topBar = {
                AppTopBar(
                    title = vm.current.title,
                    subtitle = periodLine(vm),
                    onBack = { if (!vm.backOne()) onBack() },
                    actions = {
                        // 左侧抽屉的入口（用户要的「原先的也做一个保存」全在里面：11 个老入口一个没少）。
                        // 本仓库其它带抽屉的页面都是在页内放一个按钮把它打开（见 AddressScreen / AccountManageScreen），
                        // 这里页内没有搜索框那类落点，所以入口放在顶栏这一排的最前面。
                        IconButton(onClick = { scope.launch { drawer.open() } }) {
                            Icon(Icons.Default.Menu, contentDescription = "打开抽屉：原来的页面")
                        }
                        DatePresetPill(label = vm.periodWord, onClick = { showPresets = true })
                        IconButton(onClick = { vm.retry() }) {
                            Icon(Icons.Default.Refresh, contentDescription = "重新取数")
                        }
                    },
                )
            },
        ) { pad ->
            Box(Modifier.fillMaxSize().padding(pad)) {
                when {
                    // 窗口没定下来 → 一次都不画（宁可整页转圈，也不画错窗口）
                    !vm.windowSettled -> LoadingBox()

                    // 一块都没取到 → 整页报错 + 重试；只要有一块到了就照常画（缺的那块自己写"没取到"）
                    vm.error != null && vm.turnover == null && vm.profit == null ->
                        ErrorView(vm.error ?: "取数失败", onRetry = { vm.retry() })

                    else -> LazyColumn(
                        modifier = Modifier.fillMaxSize(),
                        // 左右各留 12dp（用户 2026-10-05：「图标不要完全贴到左边，留点空隙」）
                        contentPadding = PaddingValues(start = 12.dp, end = 12.dp, top = 4.dp, bottom = 28.dp),
                    ) {
                        // ⛔ 这里原来挂着「档位是自动挑的」那句长解释 —— 用户 2026-10-05：
                        //    「那些没必要解释的没必要解释……全部删掉」。档位与区间药丸自己写着。
                        item { CrumbBar(vm) }
                        if (vm.current.id == ReportNodes.home.id) {
                            reportHomeItems(
                                vm = vm,
                                onOpen = { vm.open(it) },
                                onOpenTab = onOpenTab,
                            )
                        } else {
                            reportNodeItems(
                                vm = vm,
                                node = vm.current,
                                onOpen = { vm.open(it) },
                                onOpenTab = onOpenTab,
                                onOpenOrder = onOpenOrder,
                            )
                        }
                    }
                }
            }
        }
    }

    // 时间药丸 → 八档清单（「自定义」照样能选，选完接着弹日期区间）
    DateFilterDialogs(
        showPresets = showPresets,
        onDismissPresets = { showPresets = false },
        preset = vm.preset,
        customFrom = vm.customFrom,
        customTo = vm.customTo,
        onPickPreset = vm::applyPreset,
        onApplyCustom = vm::applyCustomRange,
        row = DatePresets.REPORT_ROW,
    )
}

/** 标题底下那一行：看的是哪一段（时点账另说，见各节点页自己的说明）。 */
private fun periodLine(vm: ReportV2ViewModel): String {
    val (from, to) = vm.dateRange
    val span = if (from == to) from else from + " ~ " + to
    return vm.periodWord + " · " + span
}

/**
 * 面包屑：只在钻进去以后出现。
 *
 * ⚠️ 只让「报表中心」可点（回首页）——中间层级是**看**的，不是点的：
 *    ViewModel 只有「回上一级 / 回首页」两个动作，给中间层画成可点却只能退一级，
 *    用户会以为点错了（要么做到位，要么不做）。
 */
@Composable
private fun CrumbBar(vm: ReportV2ViewModel) {
    if (vm.stack.size <= 1) return
    Row(
        modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 2.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        Text(
            "报表中心",
            style = MaterialTheme.typography.labelLarge,
            color = Palette.violet,
            modifier = Modifier.clickable { vm.backToHome() },
        )
        vm.stack.drop(1).forEach { n ->
            Text(
                "›",
                style = MaterialTheme.typography.labelLarge,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Text(
                n.title,
                style = MaterialTheme.typography.labelLarge,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
                // 面包屑可以很长（下钻三层），必须自己让位：⛔ 不许把右边的层挤没
                modifier = Modifier.weight(1f, fill = false),
                color = if (n.id == vm.current.id) {
                    MaterialTheme.colorScheme.onSurface
                } else {
                    MaterialTheme.colorScheme.onSurfaceVariant
                },
            )
        }
    }
}

/**
 * 左侧抽屉：**原来的入口一个都没少**（用户：「原先的也做一个保存」）。
 *
 * 第一行是新的报表首页；下面 11 行是老入口，点进去走老路由（老页面零改动）。
 */
@Composable
private fun ReportV2Drawer(
    vm: ReportV2ViewModel,
    onPickHome: () -> Unit,
    onPickTab: (Int) -> Unit,
) {
    Column(
        Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            // 左右 16dp：抽屉里每一行的图标与标题对齐在同一条线上（原来行是 0 内边距，图标贴死左边）
            .padding(horizontal = 16.dp, vertical = 18.dp),
    ) {
        Text("报表中心", style = MaterialTheme.typography.titleLarge)
        Spacer(Modifier.height(10.dp))

        LineRow(
            icon = Icons.Default.Home,
            iconColor = Palette.violet,
            title = "报表首页",
            sub = null,
            value = null,
            valueColor = Color.Unspecified,
            onClick = onPickHome,
            chevron = true,
        )
        HairLine()
        Text(
            "原来的页面",
            style = MaterialTheme.typography.labelLarge,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.padding(top = 12.dp, bottom = 4.dp),
        )
        REPORT_ENTRIES.forEach { e ->
            LineRow(
                icon = e.icon,
                iconColor = e.color,
                title = e.label,
                sub = REPORT_ENTRY_SUBS[e.key].orEmpty(),
                value = null,
                valueColor = Color.Unspecified,
                onClick = { onPickTab(e.key.toIntOrNull() ?: 0) },
                chevron = true,
            )
        }
    }
}
