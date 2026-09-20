package com.tapmoay.sorders.ui.messages

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.data.remote.dto.NotificationDto
import com.tapmoay.sorders.ui.common.*
import com.tapmoay.sorders.util.formatDateTime

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun MessagesScreen(
    container: AppContainer,
    onBack: () -> Unit,
    onOpenOrder: (Long) -> Unit,
    /**
     * 「退货申请」类通知的去处 —— 传的是**整条路由**（`?focus=<申请单号>` 已经拼好）。
     *
     * 为什么由这一页决定去哪一页：该去派单端还是货主端由 **type + 当前角色**共同决定，
     * 而这两样都在这一页手里（`noticeReturnRoute`，纯函数、一处判断）。让三个调用方
     * 各自再写一遍"哪种消息去哪个端"，就是同一套路由的第二、三份实现 —— 改了这边忘了那边
     * 的那一天，表现是"点了通知去了错误的那一页、或者 403"。
     * 默认空实现 = 不接这条直达（老调用方/预览不会因此崩），此时点通知退回老行为。
     */
    onOpenReturnRequest: (String) -> Unit = {},
    /** true = 作为底部导航内容内嵌（隐藏返回矢头/双重 inset） */
    embedded: Boolean = false,
) {
    val vm: MessagesViewModel = appViewModel { MessagesViewModel(container) }
    val unread by container.realtimeHub.unreadCount.collectAsState()
    val snackbar = remember { SnackbarHostState() }

    // 当前角色的 key（同步缓存，登录/登出时由 TokenStore 维护）。
    // ⚠️ 读**原文**而不是 `Role.fromKey(...)`：那个函数对空串会回落成 SHIPPER，
    //    于是"会话还没恢复"的那一瞬间会被当成货主（`NoticeRouting.kt` 头部解释了后果）。
    val roleKey = container.tokenStore.cachedRole()

    // 删除确认对话框：null=不弹；emptyList=清空确认
    var pendingBatchDelete by remember { mutableStateOf<List<Long>?>(null) }

    // 每次进入这一页都重新拉一次列表。
    // 为什么必须有：这个页面是底栏的一个 Tab，ViewModel 挂在 Activity 上**不会随切页销毁**，
    // 而 init 里的 load() 只跑一次 —— 以前从这里切出去再回来，看到的是很久以前的那份快照
    // （别人在别的设备上发的消息、或者别处改动过的已读状态都看不到）。
    LaunchedEffect(Unit) { vm.load(silent = vm.messages.isNotEmpty()) }

    // 一次性提示（成功/失败都用它说人话）。
    // ⚠️ 必须走 `OneShotSnackbar`：它在**显示之前**就把 `notice` 置空。
    //    以前是 `showSnackbar(it)` 之后才置空，而 showSnackbar 会挂起几秒 ——
    //    用户在这几秒里切到别的 Tab，协程被取消，置空那一行永远不执行，
    //    切回来时 `notice` 还在，于是**提示条又冒出来一次**（2026-09-18 用户报的）。
    OneShotSnackbar(snackbar, vm.notice, onConsumed = { vm.notice = null })

    Box(Modifier.fillMaxSize()) {
    Column(Modifier.fillMaxSize()) {
        TopAppBar(
            title = {
                Text(if (vm.selectionMode) ("已选 " + vm.selectedIds.size + " 条") else "消息中心")
            },
            windowInsets = if (embedded) WindowInsets(0, 0, 0, 0) else TopAppBarDefaults.windowInsets,
            navigationIcon = {
                when {
                    vm.selectionMode -> IconButton(onClick = { vm.exitSelection() }) {
                        Icon(Icons.Default.Close, contentDescription = "取消多选")
                    }
                    !embedded -> IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
                    }
                }
            },
            actions = {
                if (vm.selectionMode) {
                    TextButton(
                        enabled = vm.selectedIds.isNotEmpty() && !vm.busy,
                        onClick = { pendingBatchDelete = vm.selectedIds.toList() },
                    ) {
                        Text("删除(" + vm.selectedIds.size + ")", color = MaterialTheme.colorScheme.error)
                    }
                } else {
                    // ⚠️ **常显，不许因为没有未读就把它藏起来**（2026-09-20 用户第二次报同一件事：
                    //    「消息中心没有全部已读的功能了……其他 2 个都有」——实测司机端 8 条消息全已读，
                    //    按钮按老条件被隐藏；派单员那边有 12 条未读，所以看得到）。
                    //    2026-09-17 那次报的也是这件事，当时的修法（补 `listUnread` 判据）只放宽了
                    //    触发条件，没解决"看起来没有"：只要恰好没有未读，功能就又"消失"一次。
                    //    现在改成一直画出来，没有未读时**置灰** —— 灰 = 现在没什么可标的，而不是没这功能。
                    //    `unread` 是全局计数（`realtimeHub.unreadCount`，靠 socket 推送与
                    //    `syncUnreadFromApi` 维护），`listUnread` 是列表里这些消息的未读数；
                    //    「全部已读」真正作用的对象是列表里这些消息，两个都算上才不会误灰。
                    val listUnread = vm.messages.count { it.readAt == null }
                    TextButton(
                        enabled = !vm.busy && (unread > 0 || listUnread > 0),
                        onClick = { vm.markAllRead() },
                    ) { Text("全部已读") }
                    if (vm.messages.isNotEmpty()) {
                        TextButton(
                            enabled = !vm.busy,
                            onClick = { pendingBatchDelete = emptyList() },
                        ) {
                            Text("清空", color = MaterialTheme.colorScheme.error)
                        }
                    }
                    IconButton(enabled = !vm.busy, onClick = { vm.load(silent = true) }) {
                        Icon(Icons.Default.Refresh, contentDescription = "刷新")
                    }
                }
            },
        )
        when {
            vm.loading -> LoadingBox()
            vm.error != null -> ErrorView(vm.error.orEmpty(), onRetry = { vm.load() })
            vm.messages.isEmpty() -> EmptyView("暂无消息")
            else -> LazyColumn(
                Modifier.fillMaxSize(),
                contentPadding = PaddingValues(12.dp),
                verticalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                items(vm.messages, key = { it.id }) { m ->
                    MessageCard(
                        m = m,
                        selectionMode = vm.selectionMode,
                        selected = m.id in vm.selectedIds,
                        onClick = {
                            if (vm.selectionMode) {
                                vm.toggleSelect(m.id)
                            } else {
                                vm.markRead(m)
                                // 退货申请类的通知 → **直达那一页并定位那一条**（2026-09-21 用户要求：
                                // 「到消息中心哦。其实本来就要做到直达的」）。
                                // 认不出来（别的 type / 角色对不上 / payload 里没有申请单号）时
                                // 退回老行为：有单号就开订单详情 —— 绝不出现"点了没反应"。
                                val direct = noticeReturnRoute(roleKey, m.type, m.payload)
                                if (direct != null) {
                                    onOpenReturnRequest(direct)
                                } else {
                                    m.payload?.get("order_id")?.toString()?.toLongOrNull()?.let { onOpenOrder(it) }
                                }
                            }
                        },
                        onLongClick = { if (!vm.selectionMode) vm.enterSelection(m.id) },
                        onDelete = { vm.delete(m) },
                    )
                }
                // 「加载更多」：服务端说了还有更早的消息（响应头 X-Truncated）才显示。
                // R14-8（2026-09-19 审计）：这条接口原来没有分页、也不回报截断，
                // 于是第 201 条以前的旧消息在 App 里一个入口都没有。
                if (vm.hasMore) {
                    item(key = "load-more") {
                        Box(Modifier.fillMaxWidth().padding(vertical = 10.dp), contentAlignment = Alignment.Center) {
                            if (vm.loadingMore) {
                                CircularProgressIndicator(Modifier.size(20.dp), strokeWidth = 2.dp)
                            } else {
                                TextButton(onClick = { vm.loadMore() }) { Text("加载更早的消息") }
                            }
                        }
                    }
                }
            }
        }
    }

        SnackbarHost(
            hostState = snackbar,
            modifier = Modifier.align(Alignment.BottomCenter),
        )
    }

    // 批量删除确认
    val batchIds = pendingBatchDelete
    if (batchIds != null) {
        AlertDialog(
            onDismissRequest = { pendingBatchDelete = null },
            title = { Text(if (batchIds.isEmpty()) "清空全部消息" else "删除消息") },
            text = {
                Text(
                    // 文案写清"清空的是谁的消息"：这条界线以前是含糊的——
                    // 派单员的列表里混着别人的消息，而清空只清自己的。
                    // ⚠️ Text 不渲染 Markdown，别在这里写星号。
                    if (batchIds.isEmpty()) "将删除发给当前账户的全部消息（当前 ${vm.messages.size} 条），删除后不可恢复。确定清空吗？"
                    else ("确定删除选中的 " + batchIds.size + " 条消息吗？删除后不可恢复。")
                )
            },
            confirmButton = {
                TextButton(
                    enabled = !vm.busy,
                    onClick = {
                        pendingBatchDelete = null
                        if (batchIds.isEmpty()) vm.clearAll() else vm.deleteSelected()
                    },
                ) {
                    Text("删除", color = MaterialTheme.colorScheme.error)
                }
            },
            dismissButton = {
                TextButton(onClick = { pendingBatchDelete = null }) { Text("取消") }
            },
        )
    }
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun MessageCard(
    m: NotificationDto,
    selectionMode: Boolean,
    selected: Boolean,
    onClick: () -> Unit,
    onLongClick: () -> Unit,
    onDelete: () -> Unit,
) {
    val unread = m.readAt == null
    Surface(
        modifier = Modifier
            .fillMaxWidth()
            .combinedClickable(onClick = onClick, onLongClick = onLongClick),
        shape = MaterialTheme.shapes.medium,
        color = when {
            selected -> MaterialTheme.colorScheme.primaryContainer
            unread -> MaterialTheme.colorScheme.surfaceContainerHigh
            else -> MaterialTheme.colorScheme.surface
        },
        tonalElevation = 1.dp,
        border = if (selected) BorderStroke(1.dp, MaterialTheme.colorScheme.primary) else null,
    ) {
        Row(Modifier.padding(14.dp), verticalAlignment = Alignment.CenterVertically) {
            if (selectionMode) {
                Checkbox(checked = selected, onCheckedChange = { onClick() })
                Spacer(Modifier.width(4.dp))
            } else if (unread) {
                Surface(
                    color = MaterialTheme.colorScheme.primary,
                    shape = MaterialTheme.shapes.small,
                ) { Spacer(Modifier.size(8.dp)) }
                Spacer(Modifier.width(10.dp))
            }
            Column(Modifier.weight(1f)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        m.title.ifBlank { "系统通知" },
                        style = MaterialTheme.typography.titleSmall,
                        modifier = Modifier.weight(1f),
                    )
                    Text(
                        formatDateTime(m.createdAt),
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.outline,
                    )
                }
                if (m.content.isNotBlank()) {
                    Spacer(Modifier.height(4.dp))
                    Text(
                        m.content,
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        maxLines = 3,
                    )
                }
            }
            if (!selectionMode) {
                IconButton(onClick = onDelete) {
                    Icon(
                        Icons.Default.Delete,
                        contentDescription = "删除",
                        modifier = Modifier.size(18.dp),
                        tint = MaterialTheme.colorScheme.outline,
                    )
                }
            }
        }
    }
}
