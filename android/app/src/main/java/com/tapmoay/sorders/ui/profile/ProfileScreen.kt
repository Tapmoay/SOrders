package com.tapmoay.sorders.ui.profile

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.Logout
import androidx.compose.material.icons.filled.AccountBalanceWallet
import androidx.compose.material.icons.filled.DarkMode
import androidx.compose.material.icons.filled.Notifications
import androidx.compose.material.icons.filled.WbSunny
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.ui.common.ErrorView
import com.tapmoay.sorders.ui.common.LoadingBox
import com.tapmoay.sorders.ui.common.RoleBadge
import com.tapmoay.sorders.ui.common.TintedIcon
import com.tapmoay.sorders.ui.common.appViewModel
import com.tapmoay.sorders.ui.theme.ThemeMode
import com.tapmoay.sorders.ui.theme.MoneyOrange
import com.tapmoay.sorders.ui.theme.MessageRed
import com.tapmoay.sorders.ui.theme.ProductPurple

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ProfileScreen(
    container: AppContainer,
    onBack: () -> Unit,
    onOpenMessages: () -> Unit,
    onOpenFreight: () -> Unit = {},
    /** true = 作为底部导航内容内嵌（隐藏返回矢头/双重 inset） */
    embedded: Boolean = false,
) {
    val vm: ProfileViewModel = appViewModel { ProfileViewModel(container) }
    val unread by container.realtimeHub.unreadCount.collectAsState()

    Column(Modifier.fillMaxSize()) {
        TopAppBar(
            title = { Text("我的") },
            windowInsets = if (embedded) WindowInsets(0, 0, 0, 0) else TopAppBarDefaults.windowInsets,
            navigationIcon = {
                if (!embedded) {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
                    }
                }
            },
        )
        when {
            vm.loading -> LoadingBox()
            vm.error != null -> ErrorView(vm.error.orEmpty(), onRetry = { vm.loadMe() })
            else -> {
                val u = vm.user
                Column(Modifier.fillMaxSize().padding(horizontal = 20.dp)) {
                    Spacer(Modifier.height(12.dp))
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Surface(
                            color = MaterialTheme.colorScheme.primaryContainer,
                            shape = CircleShape,
                        ) {
                            Box(Modifier.size(60.dp), contentAlignment = Alignment.Center) {
                                Text(
                                    text = (u?.fullName ?: u?.username ?: "S").take(1),
                                    style = MaterialTheme.typography.titleLarge,
                                    color = MaterialTheme.colorScheme.onPrimaryContainer,
                                )
                            }
                        }
                        Spacer(Modifier.width(16.dp))
                        Column {
                            Text(
                                u?.fullName?.ifBlank { u.username } ?: "-",
                                style = MaterialTheme.typography.titleLarge,
                            )
                            Spacer(Modifier.height(4.dp))
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                if (u != null) RoleBadge(u.role)
                                Spacer(Modifier.width(8.dp))
                                Text(
                                    u?.phone ?: "",
                                    style = MaterialTheme.typography.bodyMedium,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                )
                            }
                        }
                    }
                    Spacer(Modifier.height(24.dp))

                    // 司机「我的账本」（其余角色的账本在工作台入口）
                    if (vm.user?.role == "driver") {
                        ListItem(
                            headlineContent = { Text("我的账本") },
                            leadingContent = {
                                TintedIcon(Icons.Default.AccountBalanceWallet, Color(MoneyOrange), size = 18.dp, container = 34.dp)
                            },
                            trailingContent = {
                                Text("按单计费明细", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                            },
                            modifier = Modifier
                                .clickable(onClick = onOpenFreight)
                                .fillMaxWidth(),
                        )
                        HorizontalDivider()
                    }
                    ListItem(
                        headlineContent = { Text("消息中心") },
                        leadingContent = {
                            TintedIcon(Icons.Default.Notifications, Color(MessageRed), size = 18.dp, container = 34.dp)
                        },
                        trailingContent = {
                            if (unread > 0) {
                                Surface(
                                    color = MaterialTheme.colorScheme.error,
                                    shape = MaterialTheme.shapes.small,
                                ) {
                                    Text(
                                        unread.toString(),
                                        style = MaterialTheme.typography.labelMedium,
                                        color = MaterialTheme.colorScheme.onError,
                                        modifier = Modifier.padding(horizontal = 8.dp, vertical = 2.dp),
                                    )
                                }
                            }
                        },
                        modifier = Modifier
                            .clickable(onClick = onOpenMessages)
                            .fillMaxWidth(),
                    )
                    HorizontalDivider()
                    ListItem(
                        headlineContent = { Text(if (ThemeMode.isDark) "夜间模式" else "白天模式") },
                        leadingContent = {
                            TintedIcon(
                                if (ThemeMode.isDark) Icons.Default.DarkMode else Icons.Default.WbSunny,
                                Color(ProductPurple),
                                size = 18.dp, container = 34.dp,
                            )
                        },
                        trailingContent = { Switch(checked = ThemeMode.isDark, onCheckedChange = { ThemeMode.isDark = it }) },
                        modifier = Modifier.clickable { ThemeMode.isDark = !ThemeMode.isDark }.fillMaxWidth(),
                    )
                    HorizontalDivider()
                    ListItem(
                        headlineContent = { Text("退出登录", color = MaterialTheme.colorScheme.error) },
                        leadingContent = {
                            TintedIcon(Icons.AutoMirrored.Filled.Logout, MaterialTheme.colorScheme.error, size = 18.dp, container = 34.dp)
                        },
                        modifier = Modifier
                            .clickable { vm.logout { } }
                            .fillMaxWidth(),
                    )
                }
            }
        }
    }
}
