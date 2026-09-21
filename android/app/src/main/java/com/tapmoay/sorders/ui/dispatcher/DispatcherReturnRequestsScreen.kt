package com.tapmoay.sorders.ui.dispatcher

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.data.remote.dto.ReturnRequestDto
import com.tapmoay.sorders.ui.common.*
import com.tapmoay.sorders.util.formatDateTime

/**
 * 派单端「退货申请」待办页（2026-09-21）。
 *
 * ## 一段话看懂这一页
 * 货主（含批发商）在订单上点了「申请退货」之后，申请单落到这里 —— 用户口径是
 * 「**批发商只是一个申请，派单员才是实际性的操作**。派单员进行完了之后，整个才进行库存
 * 才会发生一个改变和变动」。
 * 所以：
 *  · **办理退货** = 照这张申请**实际退货**，库存和账本**在这一刻才变**
 *    （退回来的货补回库存、账本按这几行红冲、这单收过钱会自动退款）；
 *  · 数量**锁死** —— 这一页没有改数量的地方，只能按申请单上的数量退；要改先驳回让货主重提；
 *  · **驳回**必须写理由（那是货主唯一能拿到的答复）。
 *
 * ⛔ 状态中文名一律用后端的 `statusLabel`（见 [ReturnRequestStatusChip]）。
 *
 * ## `focusRequestId`：从消息中心**直达某一条**（2026-09-21 用户要求）
 * 点「退货申请待处理」那条站内信进来时带上它（路由 `?focus=`）——那一条会被排到最前、
 * 打上标记、列表滚到它；列表里没有它时照常显示全部 + 一行说明（不白屏、不假装定位到了）。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DispatcherReturnRequestsScreen(
    container: AppContainer,
    onBack: () -> Unit,
    onOpenOrder: (Long) -> Unit = {},
    /** 路由上带的 `?focus=`（0 = 不是从消息中心来的）。 */
    focusRequestId: Long = 0L,
) {
    val vm: DispatcherReturnRequestsViewModel =
        appViewModel { DispatcherReturnRequestsViewModel(container, focusRequestId) }
    val snackbar = remember { SnackbarHostState() }
    val listState = rememberLazyListState()

    // 进来就把"要定位的那一条"应用上。正常情况下 VM 已经是按这个值建的（这里什么都不做），
    // 只有 VM 被复用时才真的重新定位一次 —— 见 `applyFocus` 的注释。
    LaunchedEffect(focusRequestId) { vm.applyFocus(focusRequestId) }

    // 定位成功时把列表滚到最前。那一条已经被**排到第一位**，所以"滚到它"就是滚到 0 ——
    // 不做下标计算：列表随时可能被换档/刷新重排，算出来的下标会失效（滚到别人身上）。
    LaunchedEffect(vm.focusRequestId, vm.items.firstOrNull()?.id) {
        if (vm.focusRequestId > 0L && vm.items.isNotEmpty()) listState.animateScrollToItem(0)
    }

    OneShotSnackbar(snackbar, vm.actionResult, onConsumed = { vm.actionResult = null })

    Scaffold(
        snackbarHost = { SnackbarHost(snackbar) },
        topBar = {
            AppTopBar(
                title = "退货申请",
                onBack = onBack,
            )
        },
    ) { padding ->
        Column(Modifier.fillMaxSize().padding(padding)) {
            SegmentedStatusTabs(
                labels = returnTabLabels(DISPATCH_RETURN_TABS, vm.pendingCount),
                colors = RETURN_TODO_TAB_COLORS,
                selected = vm.tab,
                onSelect = { vm.selectTab(it) },
            )
            // 定位**没找到**时的一行说明（列表照常显示全部）。
            // ⛔ 不写成错误页/白屏：那会让派单员以为这一页坏了，而事实只是"这条申请不在这份列表里"。
            // 这一段与货主端**同一处实现**（`common/ReturnRequestsUi.kt`）。
            ReturnRequestsFocusNotice(vm.focusNotice)
            Box(Modifier.fillMaxSize()) {
                when {
                    vm.loading -> LoadingBox()
                    vm.error != null -> ErrorView(vm.error.orEmpty(), onRetry = { vm.load() })
                    vm.items.isEmpty() -> EmptyView(
                        if (vm.tab == 1) {
                            "没有待处理的退货申请。"
                        } else {
                            "还没有退货申请。货主在「我的订单」里对已送达的订单可以提出申请。"
                        },
                        Modifier.align(Alignment.Center),
                    )
                    else -> LazyColumn(
                        Modifier.fillMaxSize(),
                        state = listState,
                        contentPadding = PaddingValues(16.dp),
                        verticalArrangement = Arrangement.spacedBy(10.dp),
                    ) {
                        items(vm.items, key = { it.id }) { req ->
                            ReturnTodoRow(
                                req = req,
                                acting = vm.acting,
                                onClick = { onOpenOrder(req.orderId) },
                                onFulfill = { vm.askFulfill(req) },
                                onReject = { vm.askReject(req) },
                                focused = req.id == vm.focusRequestId,
                            )
                        }
                    }
                }
            }
        }
    }

    // ---- 办理退货：二次确认（文案是本页最重要的东西）----
    vm.fulfillTarget?.let { req ->
        AlertDialog(
            onDismissRequest = { if (!vm.acting) vm.cancelFulfill() },
            title = { Text("办理退货 " + req.orderNo) },
            text = {
                Column {
                    Text(
                        "申请人：" + req.shipperName.ifBlank { "—" } + "　要退：" + req.linesSummary,
                        style = MaterialTheme.typography.bodyMedium,
                    )
                    if (req.note.isNotBlank()) {
                        Spacer(Modifier.height(4.dp))
                        Text(
                            "申请备注：" + req.note,
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                    Spacer(Modifier.height(10.dp))
                    Text(
                        "按这张申请实际退货：库存和账本在这一刻才变" +
                            "（退回来的货补回库存、账本按这几行红冲、这单收过钱会自动退款）。",
                        style = MaterialTheme.typography.bodyMedium,
                    )
                    Spacer(Modifier.height(8.dp))
                    Text(
                        "数量锁死：只能按申请单上的数量退，不能改；要改请先驳回让货主重新申请。",
                        style = MaterialTheme.typography.bodyMedium,
                        fontWeight = FontWeight.Bold,
                    )
                    // 失败原因画在弹层里（页面上会被这层弹窗盖住 = "点了没反应"）
                    FormErrorLine(vm.fulfillFormError)
                }
            },
            confirmButton = {
                TextButton(
                    onClick = { vm.confirmFulfill() },
                    enabled = !vm.acting,
                    colors = ButtonDefaults.textButtonColors(contentColor = MaterialTheme.colorScheme.error),
                ) { Text(if (vm.acting) "办理中…" else "确认退货") }
            },
            dismissButton = {
                TextButton(onClick = { vm.cancelFulfill() }, enabled = !vm.acting) { Text("取消") }
            },
        )
    }

    // ---- 驳回：理由必填（空理由连提交按钮都点不动）----
    vm.rejectTarget?.let { req ->
        AlertDialog(
            onDismissRequest = { if (!vm.acting) vm.cancelReject() },
            title = { Text("驳回退货申请 " + req.orderNo) },
            text = {
                Column {
                    Text(
                        "申请人：" + req.shipperName.ifBlank { "—" } + "　要退：" + req.linesSummary,
                        style = MaterialTheme.typography.bodyMedium,
                    )
                    Spacer(Modifier.height(8.dp))
                    Text(
                        "驳回不做任何改变：不动库存、不动账本、不改订单。理由会原样发给货主" +
                            "（他就靠这句话知道哪里不对、要怎么改）。",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    Spacer(Modifier.height(8.dp))
                    OutlinedTextField(
                        vm.rejectReason,
                        { vm.rejectReason = it },
                        label = { Text("驳回理由（必填）") },
                        minLines = 2,
                        modifier = Modifier.fillMaxWidth(),
                    )
                    FormErrorLine(vm.rejectFormError)
                }
            },
            confirmButton = {
                TextButton(
                    onClick = { vm.confirmReject() },
                    enabled = vm.canReject,
                    colors = ButtonDefaults.textButtonColors(contentColor = MaterialTheme.colorScheme.error),
                ) { Text(if (vm.acting) "提交中…" else "确认驳回") }
            },
            dismissButton = {
                TextButton(onClick = { vm.cancelReject() }, enabled = !vm.acting) { Text("取消") }
            },
        )
    }
}

/**
 * 状态导航色：全部=蓝、待处理=黄 —— **直接取订单列表那一套**（[ORDER_TAB_COLORS] 的
 * 「全部」与「派单中」），不在这里另写一份 hex（与货主端那一页同源）。
 */
private val RETURN_TODO_TAB_COLORS = listOf(ORDER_TAB_COLORS[0], ORDER_TAB_COLORS[1])

/** 一行待办：订单号 + 申请人 + 要退的商品×件数 + 申请备注 + 申请时间（待处理行带两个按钮）。 */
@Composable
private fun ReturnTodoRow(
    req: ReturnRequestDto,
    acting: Boolean,
    onClick: () -> Unit,
    onFulfill: () -> Unit,
    onReject: () -> Unit,
    /** true = 这一行就是"从消息中心点进来的那一条"（排在最前 + 打标记）。 */
    focused: Boolean = false,
) {
    SectionCard(modifier = Modifier.clickable(onClick = onClick)) {
        // 行首（定位徽章 + 订单号 + 状态徽章）与货主端**同一处实现**：
        // 那个徽章是用户"点通知进来后确认就是这一条"的唯一依据，两端必须同形。
        ReturnRequestsHeading(req = req, focused = focused)
        Spacer(Modifier.height(6.dp))
        Text(
            "申请人：" + req.shipperName.ifBlank { "—" },
            style = MaterialTheme.typography.bodyMedium,
        )
        Spacer(Modifier.height(2.dp))
        Text(req.linesSummary, style = MaterialTheme.typography.bodyMedium)
        if (req.note.isNotBlank()) {
            Spacer(Modifier.height(2.dp))
            Text(
                "申请备注：" + req.note,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        Spacer(Modifier.height(4.dp))
        Text(
            "申请时间 " + formatDateTime(req.createdAt),
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        // 已驳回的也把理由显示出来：货主来问"为什么驳"时，派单员在同一屏就能看到答案
        if (req.status == "rejected" && req.rejectReason.isNotBlank()) {
            Spacer(Modifier.height(4.dp))
            Text(
                "驳回理由：" + req.rejectReason,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.error,
            )
        }
        // 两个按钮**只在待处理行**出现：已办理/已驳回/已撤回的申请再点必然被后端拒
        if (req.isPending) {
            Spacer(Modifier.height(2.dp))
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.End,
            ) {
                TextButton(onClick = onReject, enabled = !acting) {
                    Text("驳回", color = MaterialTheme.colorScheme.error)
                }
                Spacer(Modifier.width(4.dp))
                TextButton(onClick = onFulfill, enabled = !acting) { Text("办理退货") }
            }
        }
    }
}
