package com.tapmoay.sorders.ui.driver

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.core.OrderStatusModel
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
                // ⚠️ 屏幕上这批单**不是这一栏的**（2026-10-06，BUG-0014）：`ordersTab` 才是"画的是哪一栏"。
                //    只挡 `tab == 1 && !windowSettled` 那一档是不够的 —— 那一档只在**第一次**进「已完成」
                //    时关闸；切回来 / 切过去都会漏出上一栏的单，而且卡片还按上一栏的样子画。
                //    ⛔ 这一档必须排在 `error` **之后**：取数失败时 ordersTab 会一直停在旧值，
                //    排在前面就把 ErrorView 顶掉了（用户将永远看不到失败，只看到转圈）。
                vm.ordersTab != vm.tab -> LoadingBox()
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
                                OrderCard(
                                    order = order,
                                    // ⚠️ 卡片**本体**仍然是进详情页（点卡片＝看这一单的全部：商品行、
                                    //    照片、内部备注…）。下面那颗按钮只是把"接单"这一个动作
                                    //    从详情页搬到列表上，**不替代**详情页。
                                    onClick = { onOpenOrder(order.id) },
                                    driverMode = true,
                                    highlight = vm.ordersTab == 0,
                                    // 卡片最底下那一整行（2026-10-08，CHG-0081）：司机**在列表上直接接单**，
                                    // 不必先进详情页。用户原话：「直接在订单卡片里面的最底下是有一个按钮，
                                    // 他可以直接在那里点击确认…他就不需要直接的点进去…进行确认就可以了」。
                                    //
                                    // 三个判据各有出处，别合并：
                                    //  · 状态门 [OrderStatusModel.ACKABLE]＝详情页那颗按钮的同一把尺
                                    //    （后端 `services/order_flow.accept_order` 只认 DISPATCHED → ACCEPTED）；
                                    //  · 「进行中」那一栏才画（`vm.ordersTab == 0`）：已完成档里全是送达/退货的单，
                                    //    按定义接不了（用 `ordersTab` 而不是 `tab` —— 见 `ordersTab` 的 KDoc：
                                    //    切栏那一瞬间 `tab` 已经变了、屏幕上的数据还没变）；
                                    //  · **到这里为止**。⛔ 不要再加 `!order.isNewForDriver`（CHG-0081 初版加过，
                                    //    2026-10-08 真机取证当场打脸）：那个字段的语义正是"已派单且这个司机还没接过"
                                    //    （`services/order_response.py` 按 `driver_acknowledged_at is None` 算），
                                    //    而 ACKABLE 就是 `DISPATCHED` —— 两个条件互斥，加上它等于
                                    //    「凡是真需要接的新单都不画按钮」，按钮只剩"已经接过又被退回来"的病态单可见，
                                    //    整个需求白做。真机上那两张带「新任务」标的单就是这么没有按钮的。
                                    //    重复接单由 `ACKABLE` 与后端 CAS 一起挡（见 `DriverOrdersViewModel.ack`）。
                                    bottomAction = {
                                        if (vm.ordersTab == 0 && order.status in OrderStatusModel.ACKABLE) {
                                            // 语义绿 = 「已送达/成功」那一支（`0xFF00B578`），与详情页那颗
                                            // 逐像素同色同高（56dp）——同一个动作在两个页面上不该长得不一样。
                                            // 高 56dp 是刻意的例外：`06_DESIGN_SYSTEM.md §4.2` 那排 40dp 是
                                            // **并列**的次要动作，而这是"这一张单现在要做的那一件事"，是主行动。
                                            val busy = vm.ackingOrderId == order.id
                                            // 同一时刻只接一张：只要有请求在飞，**别的**卡片那颗也置灰
                                            // （`ackingOrderId` 是单值；两个请求同时在飞时界面说不清谁成了谁没成）。
                                            val locked = vm.ackingOrderId != null
                                            Button(
                                                onClick = { vm.ack(order) },
                                                enabled = !locked,
                                                modifier = Modifier.fillMaxWidth().padding(top = 10.dp).height(56.dp),
                                                colors = ButtonDefaults.buttonColors(
                                                    containerColor = Color(0xFF00B578),
                                                    contentColor = Color.White,
                                                ),
                                            ) {
                                                if (busy) {
                                                    // 转圈：点下去到服务器回话之间必须看得见"在处理"，
                                                    // 否则司机连点，第二次必然被后端 CAS 判成 400。
                                                    CircularProgressIndicator(
                                                        modifier = Modifier.size(20.dp),
                                                        color = Color.White,
                                                        strokeWidth = 2.dp,
                                                    )
                                                } else {
                                                    Icon(
                                                        Icons.Default.CheckCircle,
                                                        contentDescription = null,
                                                        modifier = Modifier.size(20.dp),
                                                    )
                                                }
                                                Spacer(Modifier.width(8.dp))
                                                Text("确认接单", style = MaterialTheme.typography.titleSmall)
                                            }
                                            // 失败的那句话说在**这张卡上**（设计规范 §4.8「错误的落点」）：
                                            // 页面级 `error` 会被渲染门拿去顶掉整个列表，那他就连这张单都看不见了。
                                            // ⚠️ 必须按单号过滤（`ackErrorOrderId`）：`ackError` 是个单值，
                                            //    不判的话一张单失败会让**所有**卡片底下同时冒同一句红字。
                                            FormErrorLine(
                                                if (vm.ackErrorOrderId == order.id) vm.ackError else null,
                                                Modifier.padding(top = 6.dp),
                                            )
                                        }
                                    },
                                )
                            }
                        }
                    }
                }
            }
        }
    }

    // 档位清单 + 自定义区间：两个弹层的状态机在 `DateFilterDialogs` 里（五个页面共用一份）
    DateFilterDialogs(
        showPresets = showDatePresets,
        onDismissPresets = { showDatePresets = false },
        preset = vm.preset,
        customFrom = vm.customFrom,
        customTo = vm.customTo,
        onPickPreset = { vm.applyPreset(it) },
        onApplyCustom = { f, t -> vm.applyCustomRange(f, t) },
    )
}
