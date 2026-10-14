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
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.data.remote.dto.ReturnRequestDto
import com.tapmoay.sorders.ui.common.*
import com.tapmoay.sorders.ui.theme.ShipperTeal
import com.tapmoay.sorders.ui.theme.ThemeGreen
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
 *  · **改明细**（2026-10-15 CHG-0130）= **只改申请单上的商品×件数**，不动库存、不动账本、
 *    不影响退款；改完只发一条通知给货主和批发商。三方都能改（货主/批发商在自己那一页改），
 *    前提都是这张还待处理。数量**不再是锁死的** —— 用户后来改了口径：
 *    「退货是可以改的…不需要重新让货主撤销然后再重新申请一下」；
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
                                onAmend = { vm.askAmend(req) },
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
        CardAlertDialog(
            tone = DialogTone.DANGER,
            onDismissRequest = { if (!vm.acting) vm.cancelFulfill() },
            // 标题里的单号另起一行、小一号（走查 P4：标题那 24sp 一行塞不下 20 个字符）。
            title = { DialogTitle("办理退货", req.orderNo) },
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
                    // 不可逆的后果（2026-10-04 CHG-0031）：按下"确认退货"之前唯一的防线。
                    Text(
                        "按这张申请实际退货：库存和账本在这一刻才变" +
                            "（退回来的货补回库存、账本按这几行红冲、这单收过钱会自动退款）。",
                        style = MaterialTheme.typography.bodyMedium,
                    )
                    Spacer(Modifier.height(8.dp))
                    // ⚠️ 这句在 2026-10-15 CHG-0130 之前是"数量锁死：只能按申请单上的数量退，
                    //    不能改；要改请先驳回让货主重新申请"——用户后来改了口径（"退货是可以改的"）。
                    //    现在数量能在办理之前随时改，所以这里只剩一件要紧事：
                    //    **按下确认，钱和货就动了**（明细以申请单上最新的那一份为准）。
                    // 这一句是**教法**（怎么改、谁来改），不是数据/状态 ⇒ 挂总开关：
                    // 关掉提示的人不需要这段说明；真的按下去会发生什么由上一段 Text 兜着。
                    Hint(
                        "按申请单上最新的明细退（要改数量先点「改明细」，三方都能改）。" +
                            "按下去库存、账本、退款就一起动了，撤不回来。",
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
        CardAlertDialog(
            tone = DialogTone.WARN,
            onDismissRequest = { if (!vm.acting) vm.cancelReject() },
            // 同上。
            title = { DialogTitle("驳回退货申请", req.orderNo) },
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

    // ---- 改明细：只改申请单上的商品×件数（钱和货都不动）----
    // 弹层与货主端**同一个实现**（common/ReturnRequestsUi.kt::ReturnRequestAmendDialog）。
    ReturnRequestAmendDialog(vm)
}

/**
 * 状态导航色：全部=蓝、待处理=黄 —— **直接取订单列表那一套**（[ORDER_TAB_COLORS] 的
 * 「全部」与「派单中」），不在这里另写一份 hex（与货主端那一页同源）。
 */
private val RETURN_TODO_TAB_COLORS = listOf(ORDER_TAB_COLORS[0], ORDER_TAB_COLORS[1])

/**
 * 一行待办：订单号 ＋ 申请人 ＋ 申请时间 ＋ 要退的商品×件数 ＋ 申请备注（待处理行带三个动作）。
 *
 * 2026-10-15 外观轮（用户：「卡片没有按设计要求…没有详细信息和重点」）：四段各归其位 ——
 * 模块图标 ＋ 订单号（主标题）＋ 状态胶囊（行首）→ 两行「圆底图标 ＋ 灰标签 ＋ 值」→
 * 商品胶囊（甲案，与订单卡同一套）→ 备注走弱化容器 → 驳回理由走红底红字。
 */
@Composable
private fun ReturnTodoRow(
    req: ReturnRequestDto,
    acting: Boolean,
    onClick: () -> Unit,
    onFulfill: () -> Unit,
    onReject: () -> Unit,
    /** 「改明细」：只改这张申请要退的商品×件数，钱和货都不动（2026-10-15 CHG-0130）。 */
    onAmend: () -> Unit,
    /** true = 这一行就是"从消息中心点进来的那一条"（排在最前 + 打标记）。 */
    focused: Boolean = false,
) {
    SectionCard(modifier = Modifier.clickable(onClick = onClick)) {
        // 行首（定位徽章 + 模块图标 + 订单号 + 状态徽章）与货主端**同一处实现**：
        // 那个徽章是用户"点通知进来后确认就是这一条"的唯一依据，两端必须同形。
        ReturnRequestsHeading(req = req, focused = focused)
        Spacer(Modifier.height(8.dp))
        // 谁申请的、什么时候提的：两行同一套「圆底图标 ＋ 灰标签 ＋ 值」。
        // 人员走人员色（ShipperTeal）、时间走信息色（一色一功能、跨端同色）。
        ReturnRequestMetaRow(
            icon = Icons.Default.Person,
            label = "申请人",
            value = req.shipperName.ifBlank { "—" },
            tint = Color(ShipperTeal),
        )
        ReturnRequestMetaRow(
            icon = Icons.Default.Schedule,
            label = "申请时间",
            value = formatDateTime(req.createdAt),
            tint = Color(ThemeGreen),
        )
        Spacer(Modifier.height(8.dp))
        // 要退的东西单独成块（一行一个商品、右侧是件数）：这是派单员真正要核对的内容。
        ReturnRequestLinesBlock(lines = req.lines, summary = req.linesSummary)
        if (req.note.isNotBlank()) {
            Spacer(Modifier.height(6.dp))
            ReturnRequestNoteBlock(text = req.note)
        }
        // 已驳回的也把理由显示出来：货主来问"为什么驳"时，派单员在同一屏就能看到答案
        if (req.status == "rejected" && req.rejectReason.isNotBlank()) {
            Spacer(Modifier.height(6.dp))
            ReturnRequestReasonBlock(text = req.rejectReason)
        }
        // 三个按钮**只在待处理行**出现：已办理/已驳回/已撤回/已自动关闭的申请再点必然被后端拒
        // （能不能改的判据就是 [canAmendReturnRequest]，与货主端**同一句**）。
        // 位置的房子规矩：**左＝反向/警示**（驳回，红字），**右＝编辑与主行动**（用户原话
        // 「我们的惯用手是右手」）—— 改明细最轻，排在主行动「办理退货」前面；
        // 「办理退货」是这一行唯一的主行动（按下去钱和货就动了），所以给它实心按钮。
        if (canAmendReturnRequest(req)) {
            Spacer(Modifier.height(10.dp))
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.End,
            ) {
                TextButton(
                    onClick = onReject,
                    enabled = !acting,
                    colors = ButtonDefaults.textButtonColors(contentColor = MaterialTheme.colorScheme.error),
                ) {
                    Icon(Icons.Default.Close, contentDescription = null, modifier = Modifier.size(16.dp))
                    Spacer(Modifier.width(4.dp))
                    Text("驳回")
                }
                Spacer(Modifier.width(6.dp))
                TextButton(
                    onClick = onAmend,
                    enabled = !acting,
                    colors = ButtonDefaults.textButtonColors(contentColor = Color(ThemeGreen)),
                ) {
                    Icon(Icons.Default.Edit, contentDescription = null, modifier = Modifier.size(16.dp))
                    Spacer(Modifier.width(4.dp))
                    Text("改明细")
                }
                Spacer(Modifier.width(6.dp))
                Button(
                    onClick = onFulfill,
                    enabled = !acting,
                    colors = ButtonDefaults.buttonColors(containerColor = Color(ThemeGreen)),
                ) {
                    Icon(Icons.Default.Done, contentDescription = null, modifier = Modifier.size(16.dp))
                    Spacer(Modifier.width(4.dp))
                    Text("办理退货")
                }
            }
        }
    }
}
