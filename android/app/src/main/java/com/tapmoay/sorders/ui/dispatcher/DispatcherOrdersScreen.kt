package com.tapmoay.sorders.ui.dispatcher

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.core.InputRules
import com.tapmoay.sorders.core.OrderStatusModel
import com.tapmoay.sorders.ui.common.*
import com.tapmoay.sorders.util.formatMoney

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DispatcherOrdersScreen(
    container: AppContainer,
    onBack: () -> Unit,
    onOpenOrder: (Long) -> Unit,
) {
    val vm: DispatcherOrdersViewModel = appViewModel { DispatcherOrdersViewModel(container) }
    val snackbar = remember { SnackbarHostState() }

    OneShotSnackbar(snackbar, vm.actionResult, onConsumed = { vm.actionResult = null })

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
                actions = {
                    // 药丸（2026-09-22）：**每一档都画**，顶栏形态统一。
                    // · 可按日期筛的档（全部/已送达/已撤销/已退货）→ **可点**，点开是档位清单 + 自定义；
                    // · 「派单中」「已接单」（正在进行）→ **只显示**（写「不限时间」，没有 ▾、点不开）：
                    //   用户第三轮的原话「为了美观而统一…那个图标**无法选择**，他不会有列表，
                    //   就是只有显示」。
                    // ⚠️ 那两档**不按日期筛**，所以**不许写「今天」**（写日期档位名 = 屏幕上的一句
                    //   假话：本机实测派单中的单跨 09-16~09-21）。见 `ORDER_WINDOW_NO_LIMIT_WORD`。
                    // ⚠️ 它必须待在**顶栏**：默认档是带窗口的档时，今天没单列表本来就是空的 ——
                    //    把药丸藏进"列表非空"的分支里，用户就换不了档了（司机端 2026-09-20 栽过）。
                    vm.pillWord?.let { word ->
                        if (vm.pillPickable) {
                            DatePresetPill(label = word, onClick = { vm.showDatePresets = true })
                        } else {
                            DatePresetPill(label = word)
                        }
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
                labels = DISPATCH_TABS.map { it.label },
                colors = ORDER_TAB_COLORS,
                selected = vm.tab,
                onSelect = { vm.selectTab(it) },
            )
            Box(Modifier.fillMaxSize()) {
                when {
                    // ⚠️ 切进带日期窗口的档位那一瞬：窗口还在盘点（今天有没有单？没有就退到昨天…），
                    //    这时屏幕上还挂着**上一档**的单 —— 不挡住就是"先闪一批别的单"。
                    //    与账本页/司机端同一个门（2026-09-21 用户报的"闪两下"同族毛病）。
                    vm.datedTab && !vm.windowSettled -> LoadingBox()
                    vm.loading -> LoadingBox()
                    vm.error != null -> ErrorView(vm.error.orEmpty(), onRetry = { vm.load() })
                    vm.orders.isEmpty() -> EmptyView(
                        // 空态必须**指到右上角那个药丸**（司机端 2026-09-20 栽过同一个坑：
                        // 「已完成」筛空后没有出路）：默认档是「今天」，今天没单时这一页
                        // 本来就该是空的，不指路就会被当成"坏了"。
                        if (vm.datedTab && vm.periodWord != DatePresets.ALL) {
                            "「" + vm.periodWord + "」没有" + DISPATCH_TABS[vm.tab].label +
                                "的订单 —— 点右上角可以换一段时间"
                        } else {
                            "没有匹配的订单"
                        },
                        Modifier.align(Alignment.Center),
                    )
                    else -> LazyColumn(
                        Modifier.fillMaxSize(),
                        contentPadding = PaddingValues(16.dp),
                        verticalArrangement = Arrangement.spacedBy(10.dp),
                    ) {
                        items(vm.orders, key = { it.id }) { order ->
                            OrderCard(
                                order = order,
                                onClick = { onOpenOrder(order.id) },
                                showDriver = true,
                                showShipper = true,
                                // 卡片动作分区（2026-09-22 定的规范，见 `CardActionIcon`）：
                                // **左＝反向/警示，右＝编辑**。位置的含义写在 `OrderCard` 的两个槽上。
                                leading = {
                                    // 异常：**最左边**（用户：「异常的话，就放置在左边而且是最左边」）。
                                    // 形状改成"圈底图标"——原来那个 18dp 裸图标在信息很满的卡片上
                                    // 几乎看不见，手指也不好找（用户原话：「他要一个图标啊，稍微圈一下」）。
                                    CardActionIcon(
                                        icon = if (order.isException) Icons.Default.Report else Icons.Default.WarningAmber,
                                        contentDescription = "异常",
                                        tint = if (order.isException) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.tertiary,
                                        onClick = { vm.openException(order) },
                                    )
                                    // 撤回派单：**反向操作** → 左边（用户：「相反的操作，就在左边」）。
                                    // ⚠️ 状态门取 `OrderStatusModel.RECALLABLE`（后端 `recall_dispatch`
                                    //    允许 已派单 + 已接单）。原来只写 `== "ACCEPTED"`，
                                    //    于是**派错司机的第一时间撤不回来**：必须等司机先点接单，
                                    //    司机不接就永远撤不回来——而这正是最需要改派的时候。
                                    if (order.status in OrderStatusModel.RECALLABLE) {
                                        TextButton(onClick = { vm.openRecall(order) }) {
                                            Text("撤回", color = MaterialTheme.colorScheme.error)
                                        }
                                    }
                                    // 退货（2026-09-20）：只有「已送达」且**还有可退的量**才给这个按钮 ——
                                    // 点了必然被拒的按钮比没有按钮更糟（用户会以为系统坏了）。
                                    // 它也是**反向操作**（把卖出去的货收回来、账上红冲）→ 和撤回一起放左边。
                                    if (order.status in OrderStatusModel.RETURNABLE && vm.hasReturnable(order)) {
                                        TextButton(onClick = { vm.openReturn(order) }) { Text("退货") }
                                    }
                                },
                                extra = {
                                    // 编辑：**一律在右边**（用户：「编辑一定在右边，因为我们的惯用手是
                                    // 右手，我们好编辑」），且必须是"圈底的图标"而不是裸图标。
                                    CardActionIcon(
                                        icon = Icons.Default.Edit,
                                        contentDescription = "编辑",
                                        tint = MaterialTheme.colorScheme.primary,
                                        onClick = { vm.openEdit(order) },
                                    )
                                },
                            )
                        }
                        // 列表被服务端截断时说清楚（见 DispatcherOrdersViewModel.maybeTruncated）：
                        // 「全部订单」只显示最近 300 条时，不说就等于让派单员以为"这单不存在"。
                        // ⚠️ 挂在**最后一行**（用户 2026-09-22：「这个提示删掉啊，**他占位置了**」）：
                        //    它原来占着列表最上面、把第一张单推下去；挪到底部既不挡单，也没有把
                        //    "这一页不是全部"静默掉 —— **只挪位置，不删信息**。
                        //    措辞走共用那一份（`TruncationNote` / `truncationHint`），别在这页再写一遍。
                        if (vm.maybeTruncated) {
                            item(key = "truncated-note") {
                                TruncationNote(
                                    limit = ORDER_LIST_LIMIT,
                                    howToSeeMore = ORDER_TRUNCATION_HOW,
                                    modifier = Modifier.fillMaxWidth().padding(vertical = 8.dp),
                                )
                            }
                        }
                    }
                }
            }
        }
    }

    // 时间药丸的两个弹层（档位清单 + 自定义区间）。状态机**只有一份**，别在这一页再写一遍
    // `if (showPresets) … if (showCustom) …` —— 那条"选中自定义要先关清单、再开日期弹层"的规矩
    // 抄错一次，表现就是"点了自定义什么都没发生"（`DateFilterDialogs` 的注释里写着）。
    DateFilterDialogs(
        showPresets = vm.showDatePresets,
        onDismissPresets = { vm.showDatePresets = false },
        preset = vm.preset,
        customFrom = vm.customFrom,
        customTo = vm.customTo,
        onPickPreset = vm::applyPreset,
        onApplyCustom = vm::applyCustomRange,
    )

    // 编辑弹窗
    if (vm.showEditDialog) {
        AlertDialog(
            onDismissRequest = { vm.showEditDialog = false },
            title = { Text("编辑订单 " + (vm.editingOrder?.orderNo ?: "")) },
            text = {
                Column {
                    OutlinedTextField(vm.editAddress, { vm.editAddress = it }, label = { Text("收货地址") }, minLines = 2, modifier = Modifier.fillMaxWidth())
                    Spacer(Modifier.height(8.dp))
                    // 收货人 / 下单人：名称 + 电话（与下单页同一套用词）。
                    // 两个电话都只让数字进来（规则唯一实现在 core/InputRules.kt）。
                    // ⚠️ 老单里可能存着"嘿嘿"这种旧数据（生产库里真有），它会原样显示在框里；
                    //    用户一动手就被过滤掉，不动手直接保存会被后端用中文挡回（见 saveEdit）。
                    OutlinedTextField(
                        vm.editDongjiaName, { vm.editDongjiaName = it },
                        label = { Text("收货人名称") }, singleLine = true,
                        modifier = Modifier.fillMaxWidth(),
                    )
                    Spacer(Modifier.height(8.dp))
                    OutlinedTextField(
                        vm.editDongjia, { vm.editDongjia = InputRules.phoneInput(it) },
                        label = { Text("收货人电话") }, singleLine = true,
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Phone),
                        modifier = Modifier.fillMaxWidth(),
                    )
                    Spacer(Modifier.height(8.dp))
                    OutlinedTextField(
                        vm.editBossName, { vm.editBossName = it },
                        label = { Text("下单人名称") }, singleLine = true,
                        modifier = Modifier.fillMaxWidth(),
                    )
                    Spacer(Modifier.height(8.dp))
                    OutlinedTextField(
                        vm.editBoss, { vm.editBoss = InputRules.phoneInput(it) },
                        label = { Text("下单人电话") }, singleLine = true,
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Phone),
                        modifier = Modifier.fillMaxWidth(),
                    )
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

    // 退货弹窗（2026-09-20）：整单退 / 只退其中几个商品，**数量自己勾**
    vm.returnTarget?.let { order ->
        if (vm.showReturnDialog) {
            AlertDialog(
                onDismissRequest = { if (!vm.returnSubmitting) vm.showReturnDialog = false },
                title = { Text("退货 " + order.orderNo) },
                text = {
                    Column {
                        Hint(
                            "退回来的货会补回库存、账上按行红冲；这单如果已经收过钱，" +
                                "退掉的那部分会自动记一笔退给客户的现金。",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                        Spacer(Modifier.height(8.dp))
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            TextButton(onClick = { vm.returnAll() }) { Text("整单全退") }
                            TextButton(onClick = { vm.returnNone() }) { Text("全清零") }
                        }
                        OrderReturnLines(
                            lines = order.orderProducts,
                            returnQty = vm.returnQty,
                            maxReturnable = { vm.maxReturnable(it) },
                            onSetQty = { id, qty -> vm.setReturnQty(id, qty) },
                        )
                        Spacer(Modifier.height(8.dp))
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Text("退货金额", style = MaterialTheme.typography.bodyMedium)
                            Spacer(Modifier.weight(1f))
                            Text(
                                "¥" + formatMoney(vm.returnAmount()),
                                style = MaterialTheme.typography.titleMedium,
                                color = MaterialTheme.colorScheme.error,
                            )
                        }
                        Spacer(Modifier.height(8.dp))
                        OutlinedTextField(
                            vm.returnNote,
                            { vm.returnNote = it },
                            label = { Text("退货备注（选填，会留痕）") },
                            minLines = 2,
                            modifier = Modifier.fillMaxWidth(),
                        )
                    }
                },
                confirmButton = {
                    TextButton(
                        onClick = { vm.confirmReturn() },
                        enabled = !vm.returnSubmitting,
                        colors = ButtonDefaults.textButtonColors(contentColor = MaterialTheme.colorScheme.error),
                    ) { Text(if (vm.returnSubmitting) "处理中…" else "确认退货") }
                },
                dismissButton = {
                    TextButton(onClick = { vm.showReturnDialog = false }, enabled = !vm.returnSubmitting) { Text("取消") }
                },
            )
        }
    }
}
