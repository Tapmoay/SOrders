package com.tapmoay.sorders.ui.shipper

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.WarningAmber
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
import com.tapmoay.sorders.ui.theme.MgrGreen

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
                    // 药丸（2026-09-22）：**每一档都画**，顶栏形态统一。
                    // · 可按日期筛的档（全部/已送达/已撤销/已退货）→ **可点**；
                    // · 「已接单」「派单中」（正在进行）→ **只显示**「不限时间」（没有 ▾、点不开）：
                    //   用户原话「为了美观而统一…那个图标**无法选择**，他不会有列表，就是只有显示」，
                    //   以及更早的「**货主的那个时间也移到那上面去**」。
                    // ⚠️ 那两档**不按日期筛**，所以**不许写「今天」**（本机实测已接单 8 单跨
                    //   09-11~09-20，今天一单都没有）。
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
        bottomBar = {
            // 「新增订单」原在顶栏右上角，用户 2026-09-22 要求「新建订单就先**放在下面**吧，
            // 放在**底下**」。用**整条底栏**而不是一个悬浮圆钮：这一页只有这一个主动作、整条更好按，
            // 而且不会盖住列表最后一张卡（悬浮钮会压在卡片上）。
            Surface(tonalElevation = 3.dp, shadowElevation = 8.dp) {
                Button(
                    onClick = onCreateOrder,
                    colors = ButtonDefaults.buttonColors(containerColor = Color(MgrGreen), contentColor = Color.White),
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 16.dp, vertical = 10.dp)
                        .height(48.dp),
                ) {
                    Icon(Icons.Default.Add, contentDescription = null, modifier = Modifier.size(20.dp))
                    Spacer(Modifier.width(6.dp))
                    Text("新增订单", style = MaterialTheme.typography.titleSmall)
                }
            }
        },
    ) { padding ->
        Column(Modifier.fillMaxSize().padding(padding)) {
            SegmentedStatusTabs(
                labels = SHIPPER_TABS.map { it.label },
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
                        // 空态必须**说清是哪个筛子把结果挡住了**（同派单员页，见 `ui/common/OrderEmptyHint.kt`）：
                        // 默认档是「已接单」（带 status 条件），这一页**没有搜索框**，
                        // 所以 `searching` 固定 false，兜底句是「暂无订单」。
                        vm.emptyHint(searching = false, noMatch = "暂无订单"),
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
                                // 卡片动作分区（2026-09-22 定的规范，见 `CardActionIcon`）：
                                // 这一页的动作**全是反向/破坏类**（撤销订单、申请退货、撤回申请），
                                // 所以**一个都不放右边** —— 右边那个位置留给"编辑"
                                // （用户原话：「编辑一定在右边…相反的操作，就在左边」）。
                                leading = {
                                    // 「账上认不出人」的单（收货人与下单人都没填名字，L-28 / CHG-0057）：
                                    // 一颗红标，点它进详情补联系信息。
                                    // ⛔ 只能放这一侧：右边那个位置留给"编辑"，而且这一页不许出现右侧那个
                                    //    动作分区（判据 _tools/qa/_check_order_list_ui.py 按字面盯着这一页的形态 ——
                                    //    连注释里写出那个字面形状都会让它假红，2026-10-06 踩过一次）。
                                    if (order.contactRisk) {
                                        CardActionIcon(
                                            icon = Icons.Default.WarningAmber,
                                            contentDescription = "补联系信息",
                                            label = "补联系信息",
                                            tint = MaterialTheme.colorScheme.error,
                                            onClick = { onOpenOrder(order.id) },
                                        )
                                    }
                                    // 待派单/已派单（司机未接）可卡片直撤，不进详情。
                                    // 状态门取 `OrderStatusModel.CANCELLABLE`（后端 `cancel_pending` 同一对取值）。
                                    if (order.status in OrderStatusModel.CANCELLABLE) {
                                        TextButton(
                                            onClick = { vm.openCancel(order) },
                                            enabled = !vm.acting,
                                            shape = androidx.compose.foundation.shape.RoundedCornerShape(10.dp),
                                            colors = ButtonDefaults.textButtonColors(
                                                contentColor = Color(0xFFF50010),
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
                        // 列表被服务端截断时说清楚（见 ShipperOrdersViewModel.maybeTruncated）。
                        // ⚠️ 挂在**最后一行**（用户 2026-09-22：「这个提示删掉啊，**他占位置了**」）：
                        //    原来它占着列表最上面、把第一张单推下去；挪到底部既不挡单，也没有把
                        //    "这一页不是全部"静默掉 —— **只挪位置，不删信息**。
                        //    措辞走共用那一份（`TruncationNote`），别在这一页再写一遍。
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

    // 时间药丸的两个弹层（档位清单 + 自定义区间）—— 状态机只有一份（`DateFilterDialogs`），
    // 别在这一页再写一遍 `if (showPresets) … if (showCustom) …`。
    DateFilterDialogs(
        showPresets = vm.showDatePresets,
        onDismissPresets = { vm.showDatePresets = false },
        preset = vm.preset,
        customFrom = vm.customFrom,
        customTo = vm.customTo,
        onPickPreset = vm::applyPreset,
        onApplyCustom = vm::applyCustomRange,
    )

    // 二次确认（防误触）
    vm.cancelTarget?.let { target ->
        DangerConfirmDialog(
            title = "确认撤销订单？",
            message = "订单 #" + target.orderNo + " 撤销后将不再处理。司机若已接单无法撤销。",
            confirmText = "确认撤销",
            error = vm.cancelError,
            enabled = !vm.acting,
            onConfirm = { vm.confirmCancel() },
            onDismiss = { vm.dismissCancel() },
        )
    }

    // 申请退货弹层（与派单员「订单管理」里那个退货弹窗**同形**：逐行勾数量 + 备注选填）。
    // ⚠️ 这里**不显示金额**：申请阶段后端一分钱都不算，客户端自己乘一遍就是第二份金额算法
    //    （本仓库的规矩是"钱只算一处"）。金额在派单员办理的回执里由后端给。
    vm.returnTarget?.let { order ->
        if (vm.showReturnDialog) {
            CardAlertDialog(
                tone = DialogTone.WARN,
                onDismissRequest = { vm.dismissReturnDialog() },
                // 单号另起一行、小一号（走查 P4：标题那 24sp 一行塞不下 20 个字符，会被从数字中间劈开）。
                title = { DialogTitle("申请退货", order.orderNo) },
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
                        OrderReturnLines(
                            lines = order.orderProducts,
                            returnQty = vm.returnQty,
                            maxReturnable = { vm.maxReturnable(it) },
                            onSetQty = { id, qty -> vm.setReturnQty(id, qty) },
                        )
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
        CardAlertDialog(
            tone = DialogTone.DANGER,
            onDismissRequest = { vm.cancelWithdraw() },
            title = { Text("撤回这张退货申请？") },
            text = {
                Column {
                    Text(
                        "订单 #" + req.orderNo + "：" + req.linesSummary,
                        style = MaterialTheme.typography.bodyMedium,
                    )
                    Spacer(Modifier.height(8.dp))
                    Hint(
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
private val RETURN_ACCENT = 0xFFE0785EL
