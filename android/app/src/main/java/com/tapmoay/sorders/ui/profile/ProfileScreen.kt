package com.tapmoay.sorders.ui.profile

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.Logout
import androidx.compose.material.icons.filled.AccountBalanceWallet
import androidx.compose.material.icons.filled.DarkMode
import androidx.compose.material.icons.filled.Download
import androidx.compose.material.icons.filled.Notifications
import androidx.compose.material.icons.filled.NotificationsActive
import androidx.compose.material.icons.filled.SystemUpdateAlt
import androidx.compose.material.icons.filled.Update
import androidx.compose.material.icons.filled.VolumeUp
import androidx.compose.material.icons.filled.WbSunny
import androidx.compose.material.icons.filled.WbTwilight
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.core.NewOrderAlert
import com.tapmoay.sorders.core.SunClock
import com.tapmoay.sorders.core.SunLocation
import com.tapmoay.sorders.ui.common.ErrorView
import com.tapmoay.sorders.ui.nav.Role
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
fun ProfileScreen(    container: AppContainer,
    onBack: () -> Unit,
    onOpenMessages: () -> Unit,
    onOpenFreight: () -> Unit = {},
    /** 消息提醒设置（语音提醒/念几遍/关掉 App 也收单） */
    onOpenAlerts: () -> Unit = {},
    /** true = 作为底部导航内容内嵌（隐藏返回矢头/双重 inset） */
    embedded: Boolean = false,
) {
    val vm: ProfileViewModel = appViewModel { ProfileViewModel(container) }
    val unread by container.realtimeHub.unreadCount.collectAsState()
    val context = LocalContext.current

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
                    // 消息提醒：把「来单了会不会喊、喊几遍、关掉 App 还收不收」摆在明面上。
                    // 右侧直接写当前状态——不写的话，用户只能进去看一遍才知道现在是开是关。
                    ListItem(
                        headlineContent = { Text("消息提醒") },
                        // 副标题也按角色说：对货主/派单员写「语音播报」同样是承诺一件不会发生的事
                        supportingContent = {
                            Text(
                                if (NewOrderAlert.isSpoken(Role.fromKey(container.tokenStore.cachedRole() ?: ""))) {
                                    "语音播报 / 后台接收新单"
                                } else {
                                    "通知栏提醒 / 后台接收新单"
                                }
                            )
                        },
                        leadingContent = {
                            TintedIcon(
                                if (NewOrderAlert.isSpoken(Role.fromKey(container.tokenStore.cachedRole() ?: ""))) {
                                    Icons.Default.VolumeUp
                                } else {
                                    Icons.Default.NotificationsActive
                                },
                                Color(0xFF1E6FFF), size = 18.dp, container = 34.dp,
                            )
                        },
                        trailingContent = {
                            Text(
                                alertSummary(container),
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        },
                        modifier = Modifier
                            .clickable(onClick = onOpenAlerts)
                            .fillMaxWidth(),
                    )
                    HorizontalDivider()
                    ListItem(
                        headlineContent = { Text("随日落自动切换") },
                        supportingContent = {
                            Text(
                                SunClock.summary(
                                    ThemeMode.autoBySun,
                                    SunClock.stateHere(),
                                    located = SunLocation.hasFix(),
                                )
                            )
                        },
                        leadingContent = {
                            TintedIcon(
                                Icons.Default.WbTwilight,
                                Color(MoneyOrange),
                                size = 18.dp, container = 34.dp,
                            )
                        },
                        trailingContent = {
                            Switch(
                                checked = ThemeMode.autoBySun,
                                onCheckedChange = { ThemeMode.setAuto(context, it) },
                            )
                        },
                        modifier = Modifier
                            .clickable { ThemeMode.setAuto(context, !ThemeMode.autoBySun) }
                            .fillMaxWidth(),
                    )
                    HorizontalDivider()
                    ListItem(
                        headlineContent = { Text(if (ThemeMode.isDark) "夜间模式" else "白天模式") },
                        supportingContent = {
                            if (ThemeMode.autoBySun) Text("已交给自动切换")
                        },
                        leadingContent = {
                            TintedIcon(
                                if (ThemeMode.isDark) Icons.Default.DarkMode else Icons.Default.WbSunny,
                                Color(ProductPurple),
                                size = 18.dp, container = 34.dp,
                            )
                        },
                        // 走 ThemeMode.set（负责落盘）；自动模式下这个开关禁用
                        trailingContent = {
                            Switch(
                                checked = ThemeMode.isDark,
                                onCheckedChange = { ThemeMode.set(context, it) },
                                enabled = !ThemeMode.autoBySun,
                            )
                        },
                        modifier = Modifier
                            .clickable(enabled = !ThemeMode.autoBySun) { ThemeMode.set(context, !ThemeMode.isDark) }
                            .fillMaxWidth(),
                    )
                    HorizontalDivider()
                    ListItem(
                        headlineContent = { Text("关于与更新") },
                        leadingContent = {
                            TintedIcon(Icons.Default.SystemUpdateAlt, Color(0xFF1E6FFF), size = 18.dp, container = 34.dp)
                        },
                        trailingContent = {
                            Text(
                                "v" + vm.currentVersion,
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        },
                        modifier = Modifier.fillMaxWidth(),
                    )
                    HorizontalDivider()
                    ListItem(
                        headlineContent = {
                            // 下载中补第二行：速度 / 已下多少 / 还剩多久。
                            // 只说「正在下载 87%」的话，用户无法判断是"快好了"还是"卡住了"——
                            // 「下载非常慢」这种反馈正是因为屏幕上没有任何可以判断的数字。
                            val extra = when {
                                vm.updateState == "downloading" && vm.downloadDetail.isNotBlank() -> vm.downloadDetail
                                vm.updateState == "installing" -> "安装包已下好：请在系统弹出的界面点「安装」"
                                vm.updateState == "needInstallPermission" -> "安卓要求先允许本应用安装应用，点这里处理"
                                else -> null
                            }
                            Column {
                                Text(
                                    when (vm.updateState) {
                                        "checking" -> "正在检查更新…"
                                        "downloading" -> "正在下载更新 " + vm.downloadProgress + "%"
                                        "installing" -> "等待安装新版…"
                                        "needInstallPermission" -> "还差一步：允许安装应用"
                                        else -> "检查更新"
                                    }
                                )
                                if (extra != null) {
                                    Text(
                                        extra,
                                        style = MaterialTheme.typography.bodySmall,
                                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                                    )
                                }
                            }
                        },
                        leadingContent = {
                            TintedIcon(
                                when (vm.updateState) {
                                    "downloading" -> Icons.Default.Download
                                    else -> Icons.Default.Update
                                },
                                Color(0xFF00B578), size = 18.dp, container = 34.dp,
                            )
                        },
                        trailingContent = {
                            if (vm.updateState == "downloading") {
                                LinearProgressIndicator(
                                    progress = { vm.downloadProgress / 100f },
                                    modifier = Modifier.width(90.dp).height(8.dp),
                                    color = Color(0xFF00B578),
                                )
                            }
                        },
                        modifier = Modifier
                            .clickable(enabled = vm.updateState != "checking" && vm.updateState != "downloading") { vm.checkUpdate() }
                            .fillMaxWidth(),
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

    // 有新版 → 确认弹窗
    if (vm.updateState == "confirm" && vm.latest != null) {
        AlertDialog(
            onDismissRequest = { vm.updateState = "idle" },
            title = { Text("发现新版本 v" + vm.latest?.version) },
            text = {
                Column {
                    Text("当前版本：v" + vm.currentVersion)
                    Spacer(Modifier.height(6.dp))
                    val note = vm.latest?.note.orEmpty()
                    if (note.isNotBlank()) Text(note, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    Spacer(Modifier.height(10.dp))
                    Text("是否立即下载并安装更新？", style = MaterialTheme.typography.titleSmall)
                }
            },
            confirmButton = {
                TextButton(onClick = { vm.downloadAndInstall(context) }) { Text("下载并更新") }
            },
            dismissButton = {
                TextButton(onClick = { vm.updateState = "idle" }) { Text("取消") }
            },
        )
    }

    // 系统不让装 APK → 先把用户领到开关那里。
    // 不这么做的话，用户点完「下载并更新」看到的是系统弹的一句英文
    // "…isn't allowed to install unknown apps from this source"，
    // 绝大多数人的下一步是点 Cancel，然后得出结论「下载完了但没更新」。
    if (vm.updateState == "needInstallPermission") {
        AlertDialog(
            onDismissRequest = { vm.updateState = "idle" },
            title = { Text("还差一步：允许安装应用") },
            text = {
                Column {
                    Text("安卓要求先允许「SOrders 派单送货」安装应用，否则系统会把安装界面直接拦下来。")
                    Spacer(Modifier.height(8.dp))
                    Text(
                        "点「去设置」打开开关，返回后再点一次「检查更新」就行——安装包不用重新下载。",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            },
            confirmButton = {
                TextButton(onClick = { vm.openInstallPermissionSettings(context) }) { Text("去设置") }
            },
            dismissButton = {
                TextButton(onClick = { vm.updateState = "idle" }) { Text("取消") }
            },
        )
    }

    // 结果提示
    if (vm.updateState == "latest" && vm.updateMessage != null) {
        AlertDialog(
            onDismissRequest = { vm.updateState = "idle"; vm.updateMessage = null },
            title = { Text("检查更新") },
            text = { Text(vm.updateMessage.orEmpty()) },
            confirmButton = {
                TextButton(onClick = { vm.updateState = "idle"; vm.updateMessage = null }) { Text("知道了") }
            },
        )
    }
}

/**
 * 「消息提醒」这一行右侧的状态摘要。
 *
 * 为什么要写出来：用户对自己手机的行为没有可靠的记忆，
 * 而这一项直接决定"派单来了会不会响"。写成一句话，用户不用进去看就知道现在是什么状态；
 * 判定（含"按角色说不同的话"）在纯函数 [NewOrderAlert.summary] 里，有单测。
 */
private fun alertSummary(container: AppContainer): String {
    val prefs = container.alertPrefs
    val role = Role.fromKey(container.tokenStore.cachedRole() ?: "")
    return NewOrderAlert.summary(
        role = role,
        notificationsAllowed = container.notifyCenter.canPost(),
        voiceEnabled = prefs.voiceEnabled,
        repeat = prefs.repeatTimes,
        background = prefs.backgroundEnabled(role),
    )
}
