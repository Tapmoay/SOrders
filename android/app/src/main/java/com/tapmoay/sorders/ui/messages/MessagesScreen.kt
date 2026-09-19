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
    /** true = 作为底部导航内容内嵌（隐藏返回矢头/双重 inset） */
    embedded: Boolean = false,
) {
    val vm: MessagesViewModel = appViewModel { MessagesViewModel(container) }
    val unread by container.realtimeHub.unreadCount.collectAsState()
    val snackbar = remember { SnackbarHostState() }

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
                    // ⚠️ 判据不能只看全局红点。用户 2026-09-17 报「还加一个全部已读的功能」——
                    //    功能其实一直在，但它的显示条件是 `unread > 0`，而 `unread` 来自
                    //    `realtimeHub.unreadCount`（**全局计数**，靠 socket 推送与 syncUnreadFromApi 维护）。
                    //    那个数没同步上时它是 0，于是按钮一直藏着，用户以为没这个功能。
                    //    「全部已读」真正作用的对象是**列表里这些消息**，所以列表里有未读也必须出现。
                    val listUnread = vm.messages.count { it.readAt == null }
                    if (unread > 0 || listUnread > 0) {
                        TextButton(enabled = !vm.busy, onClick = { vm.markAllRead() }) { Text("全部已读") }
                    }
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
                                m.payload?.get("order_id")?.toString()?.toLongOrNull()?.let { onOpenOrder(it) }
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
