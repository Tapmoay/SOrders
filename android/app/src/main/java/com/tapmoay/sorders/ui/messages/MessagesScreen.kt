package com.tapmoay.sorders.ui.messages

import androidx.compose.foundation.clickable
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
import com.tapmoay.sorders.ui.nav.Routes
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

    Column(Modifier.fillMaxSize()) {
        TopAppBar(
            title = { Text("消息中心") },
            windowInsets = if (embedded) WindowInsets(0, 0, 0, 0) else TopAppBarDefaults.windowInsets,
            navigationIcon = {
                if (!embedded) {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
                    }
                }
            },
            actions = {
                if (unread > 0) {
                    TextButton(onClick = { vm.markAllRead() }) { Text("全部已读") }
                }
                IconButton(onClick = { vm.load(silent = true) }) {
                    Icon(Icons.Default.Refresh, contentDescription = "刷新")
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
                        onClick = {
                            vm.markRead(m)
                            m.payload?.get("order_id")?.toString()?.toLongOrNull()?.let { onOpenOrder(it) }
                        },
                        onDelete = { vm.delete(m) },
                    )
                }
            }
        }
    }
}

@Composable
private fun MessageCard(
    m: NotificationDto,
    onClick: () -> Unit,
    onDelete: () -> Unit,
) {
    val unread = m.readAt == null
    Surface(
        modifier = Modifier.fillMaxWidth().clickable(onClick = onClick),
        shape = MaterialTheme.shapes.medium,
        color = if (unread) MaterialTheme.colorScheme.surfaceContainerHigh
        else MaterialTheme.colorScheme.surface,
        tonalElevation = 1.dp,
    ) {
        Row(Modifier.padding(14.dp), verticalAlignment = Alignment.CenterVertically) {
            if (unread) {
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
                        style = if (unread) MaterialTheme.typography.titleSmall
                        else MaterialTheme.typography.titleSmall,
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
