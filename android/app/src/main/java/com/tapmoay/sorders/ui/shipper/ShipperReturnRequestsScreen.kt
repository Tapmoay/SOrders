package com.tapmoay.sorders.ui.shipper

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
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
 * 货主端「我的退货申请」（2026-09-21）。
 *
 * ## 一段话看懂这一页
 * 货主在「我的订单」里对一张**已送达**的单点了「申请退货」，之后的事情在这里看：
 * 待派单员处理（还能撤回）/ 已办理（那一刻库存和账本才变）/ 已驳回（有原因）。
 *
 * ⛔ **状态中文名一律来自后端的 `statusLabel`**（见 [ReturnRequestStatusChip] 的注释：
 *    前端自己写一套映射，后端加一档就会在原样显示 `withdrawn` 这种机器码）。
 * ⛔ **这里没有任何金额**：申请阶段一分钱都没动，金额是派单员办理时由后端算的
 *    （后端 `ReturnRequestOut` 里根本没有金额字段，这是刻意的）。
 *
 * ## `focusRequestId`：从消息中心**直达某一条**（2026-09-21 用户要求）
 * 点「退货已办理 / 被驳回 / 已关闭」那条站内信进来时带上它（路由 `?focus=`）——
 * 那一条会被排到最前、打上标记、列表滚到它；找不到时列表照常显示 + 一行说明（不白屏）。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ShipperReturnRequestsScreen(
    container: AppContainer,
    onBack: () -> Unit,
    onOpenOrder: (Long) -> Unit = {},
    /** 路由上带的 `?focus=`（0 = 不是从消息中心来的）。 */
    focusRequestId: Long = 0L,
) {
    val vm: ShipperReturnRequestsViewModel =
        appViewModel { ShipperReturnRequestsViewModel(container, focusRequestId) }
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
                title = "我的退货申请",
                onBack = onBack,
            )
        },
    ) { padding ->
        Column(Modifier.fillMaxSize().padding(padding)) {
            SegmentedStatusTabs(
                // 待处理那一档带上张数（后端给的 pending_count）——
                // 货主最想知道的就是"有没有还没办的"，不该逼他点进去数
                labels = SHIPPER_RETURN_TABS.mapIndexed { i, t ->
                    if (i == 0 && vm.pendingCount > 0) t.label + " " + vm.pendingCount else t.label
                },
                colors = RETURN_TAB_COLORS,
                selected = vm.tab,
                onSelect = { vm.selectTab(it) },
            )
            // 定位**没找到**时的一行说明（列表照常显示全部）。
            // ⛔ 不写成错误页/白屏：那会让用户以为这一页坏了，而事实只是"这条申请不在这份列表里"。
            vm.focusNotice?.let { msg ->
                Text(
                    msg,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 6.dp),
                )
            }
            Box(Modifier.fillMaxSize()) {
                when {
                    vm.loading -> LoadingBox()
                    vm.error != null -> ErrorView(vm.error.orEmpty(), onRetry = { vm.load() })
                    vm.items.isEmpty() -> EmptyView(
                        if (vm.tab == 0) {
                            "没有待处理的退货申请。"
                        } else {
                            "还没有退货申请。在「我的订单」里，已送达的订单可以申请退货。"
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
                            ReturnRequestRow(
                                req = req,
                                onClick = { onOpenOrder(req.orderId) },
                                onWithdraw = { vm.askWithdraw(req) },
                                acting = vm.acting,
                                focused = req.id == vm.focusRequestId,
                            )
                        }
                    }
                }
            }
        }
    }

    // 撤回二次确认：文案必须写清"撤回不是删除"（用户口径）
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
 * 状态导航色：待处理=黄、全部=蓝 —— **直接取订单列表那一套**（[ORDER_TAB_COLORS] 的
 * 「全部」与「派单中」），不在这里另写一份 hex：两页的颜色必须是同一支色，
 * 各写一份的话改了一处另一处就悄悄分叉了。
 */
private val RETURN_TAB_COLORS = listOf(ORDER_TAB_COLORS[1], ORDER_TAB_COLORS[0])

/** 一行申请：订单号 + 要退的商品×件数 + 状态 + 申请时间（＋驳回原因 / 办理人 / 撤回）。 */
@Composable
private fun ReturnRequestRow(
    req: ReturnRequestDto,
    onClick: () -> Unit,
    onWithdraw: () -> Unit,
    acting: Boolean,
    /** true = 这一行就是"从消息中心点进来的那一条"（排在最前 + 打标记）。 */
    focused: Boolean = false,
) {
    SectionCard(modifier = Modifier.clickable(onClick = onClick)) {
        // 视觉标记：一枚小胶囊，写明"为什么它在最前面"——用户点完通知落进来时，
        // 一眼要能确认"就是这一条"，而不是自己在几十行里找。
        // ⚠️ 文案里不许出现 Markdown 星号（Text 不渲染 Markdown，会原样显示）。
        if (focused) {
            Surface(
                color = MaterialTheme.colorScheme.primary,
                shape = RoundedCornerShape(50),
            ) {
                Text(
                    "消息里点进来的这一条",
                    color = MaterialTheme.colorScheme.onPrimary,
                    style = MaterialTheme.typography.labelSmall,
                    modifier = Modifier.padding(horizontal = 10.dp, vertical = 4.dp),
                )
            }
            Spacer(Modifier.height(8.dp))
        }
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(
                "订单 #" + req.orderNo,
                style = MaterialTheme.typography.titleSmall,
                fontWeight = FontWeight.Bold,
                modifier = Modifier.weight(1f),
            )
            // 中文名**只用后端给的那一个**
            ReturnRequestStatusChip(status = req.status, label = req.statusLabel)
        }
        Spacer(Modifier.height(6.dp))
        Text(req.linesSummary, style = MaterialTheme.typography.bodyMedium)
        if (req.note.isNotBlank()) {
            Spacer(Modifier.height(2.dp))
            Text(
                "备注：" + req.note,
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
        // 被驳回：原因必须显示 —— 这是货主唯一能拿到的答复
        if (req.status == "rejected") {
            Spacer(Modifier.height(6.dp))
            Text(
                "驳回原因：" + req.rejectReason.ifBlank { "（派单员没有填原因）" },
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.error,
            )
        }
        // 已办理：谁办的、什么时候（钱和货是那一刻变的）
        if (req.status == "done") {
            Spacer(Modifier.height(6.dp))
            Text(
                buildString {
                    append("已由 ")
                    append(req.handledByName.ifBlank { "派单员" })
                    append(" 办理")
                    val at = formatDateTime(req.handledAt)
                    if (at.isNotBlank()) append(" · ").append(at)
                },
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        if (req.isPending) {
            Spacer(Modifier.height(2.dp))
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.End,
            ) {
                TextButton(onClick = onWithdraw, enabled = !acting) { Text("撤回申请") }
            }
        }
    }
}
