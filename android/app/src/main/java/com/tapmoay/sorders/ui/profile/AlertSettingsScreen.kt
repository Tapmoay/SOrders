package com.tapmoay.sorders.ui.profile

import android.app.NotificationManager
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.PowerManager
import android.provider.Settings
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.BatteryAlert
import androidx.compose.material.icons.filled.NotificationsActive
import androidx.compose.material.icons.filled.NotificationsOff
import androidx.compose.material.icons.filled.PlayCircle
import androidx.compose.material.icons.filled.VolumeUp
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.tapmoay.sorders.core.AlertKind
import com.tapmoay.sorders.core.AlertService
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.core.NewOrderAlert
import com.tapmoay.sorders.ui.common.TintedIcon
import com.tapmoay.sorders.ui.nav.Role

/**
 * 消息提醒设置（司机端最要紧的一页）。
 *
 * 为什么值得单独一页：这一页上的每一项都对应一个**用户能听懂、也必须能自己决定**的事——
 * 「来单了会不会喊」「喊几遍」「关了 App 还收不收」「手机是不是自己把后台掐了」。
 * 以前这四件事全是代码里的行为、用户无法知情更无法调整；
 * 而"司机没听见新单"这类事故，用户连描述都描述不出来。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AlertSettingsScreen(
    container: AppContainer,
    onBack: () -> Unit,
) {
    val context = LocalContext.current
    val prefs = container.alertPrefs
    val role = Role.fromKey(container.tokenStore.cachedRole() ?: "")

    var voice by remember { mutableStateOf(prefs.voiceEnabled) }
    var repeat by remember { mutableIntStateOf(prefs.repeatTimes) }
    var background by remember { mutableStateOf(prefs.backgroundEnabled(role)) }
    var boost by remember { mutableStateOf(prefs.boostVolume) }
    // 语音只有司机有（判定在 NewOrderAlert.isSpoken）。给货主/派单员也摆一个「新单语音提醒」
    // 开关，等于让他们调一个永远不会生效的东西——**能点、但不做事**比没有更糟。
    val voiceRole = NewOrderAlert.isSpoken(role)
    // 系统权限/省电策略会被用户在系统设置里改，回到这一页要重新读一次
    var notifAllowed by remember { mutableStateOf(notificationsAllowed(context)) }
    var batteryFree by remember { mutableStateOf(batteryUnrestricted(context)) }
    val running by AlertService.running.collectAsState()

    Column(Modifier.fillMaxSize()) {
        TopAppBar(
            title = { Text("消息提醒") },
            navigationIcon = {
                IconButton(onClick = onBack) {
                    Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
                }
            },
        )
        Column(
            Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .padding(horizontal = 20.dp),
        ) {
            Spacer(Modifier.height(8.dp))

            // ---- 有没有通知权限：没开的话上面所有设置都是空转，所以放在最前面 ----
            if (!notifAllowed) {
                WarnCard(
                    title = "手机还没允许 SOrders 发通知",
                    body = "不开这个权限，派单来了手机上不会弹任何东西——只有打开 App 才看得到。",
                    action = "去开启",
                    onClick = { openNotificationSettings(context) },
                )
                Spacer(Modifier.height(12.dp))
            }

            if (voiceRole) {
                SwitchRow(
                    icon = Icons.Default.NotificationsActive,
                    color = Color(0xFFFF4D4F),
                    title = "新单语音提醒",
                    subtitle = "有新派单时大声念「来单了」",
                    checked = voice,
                    onCheckedChange = {
                        voice = it
                        prefs.voiceEnabled = it
                        // 立刻生效给用户听一遍：开关拨了却不出声，用户只会怀疑是坏的
                        if (it) container.newOrderPlayer.play(AlertKind.NEW_ORDER, NewOrderAlert.plan(1))
                        else container.newOrderPlayer.stop()
                    },
                )

                if (voice) {
                Spacer(Modifier.height(4.dp))
                ChoiceRow(
                    title = "念几遍",
                    current = repeat,
                    onPick = {
                        repeat = it
                        prefs.repeatTimes = it
                        container.newOrderPlayer.play(AlertKind.NEW_ORDER, NewOrderAlert.planFor(AlertKind.NEW_ORDER, it))
                    },
                )
                Spacer(Modifier.height(8.dp))
                ListItem(
                    headlineContent = { Text("试听一声") },
                    supportingContent = {
                        Text(
                            "按下播一遍（约 3 秒），确认手机上真的听得见",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    },
                    leadingContent = {
                        TintedIcon(Icons.Default.PlayCircle, Color(0xFF00B578), size = 18.dp, container = 34.dp)
                    },
                    modifier = Modifier
                        .clickable {
                            container.newOrderPlayer.play(
                                AlertKind.NEW_ORDER,
                                NewOrderAlert.planFor(AlertKind.NEW_ORDER, repeat),
                            )
                        }
                        .fillMaxWidth(),
                )
                HorizontalDivider()
                SwitchRow(
                    icon = Icons.Default.VolumeUp,
                    color = Color(0xFFFF9500),
                    title = "响的时候自动提高音量",
                    subtitle = "手机音量太低时临时提到 70%，念完恢复原样",
                    checked = boost,
                    onCheckedChange = { boost = it; prefs.boostVolume = it },
                )
                }
            }

            Spacer(Modifier.height(12.dp))
            SwitchRow(
                icon = if (background) Icons.Default.NotificationsActive else Icons.Default.NotificationsOff,
                color = Color(0xFF1E6FFF),
                title = "关掉 App 也收单",
                subtitle = if (running) {
                    "正在后台接收（通知栏有一条常驻提示，随时可关）"
                } else if (background) {
                    "已开启，正在启动…"
                } else {
                    "关闭后只有打开 App 时才收得到新派单"
                },
                checked = background,
                onCheckedChange = {
                    background = it
                    prefs.setBackgroundEnabled(it)
                    // 只在 App 可见时能起前台服务，这一页就是"可见"的时机
                    AlertService.sync(context, role)
                },
            )

            if (background) {
                Spacer(Modifier.height(4.dp))
                if (!batteryFree) {
                    WarnCard(
                        title = "手机可能在后台把 SOrders 掐掉",
                        body = "安卓的省电策略会限制后台运行。把 SOrders 设成「不受限制」，关掉屏幕也能收到派单。",
                        action = "去设置",
                        onClick = { openBatterySettings(context) },
                    )
                } else {
                    ListItem(
                        headlineContent = { Text("系统未限制后台运行") },
                        supportingContent = {
                            Text(
                                "已确认：锁屏 / 关掉 App 后仍会接收并播报",
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        },
                        leadingContent = {
                            TintedIcon(Icons.Default.NotificationsActive, Color(0xFF00B578), size = 18.dp, container = 34.dp)
                        },
                    )
                }
            }

            Spacer(Modifier.height(20.dp))
            Text(
                if (voiceRole) {
                    "语音只对司机端播报：派单员和货主收到的消息只有通知栏提醒。"
                } else {
                    "语音播报只在司机端有（司机才需要边开车边听单）；你收到的消息会进通知栏。"
                },
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Spacer(Modifier.height(24.dp))
        }
    }

    // 系统权限/省电策略会被用户在系统设置里改，所以这一页开着时**轮询**它们：
    // 用户点「去开启」跳到系统页、改完返回，这一页必须自己变过来——
    // 不变的话用户会以为"设了没用"，然后放弃这个功能。
    LaunchedEffect(Unit) {
        while (true) {
            notifAllowed = notificationsAllowed(context)
            batteryFree = batteryUnrestricted(context)
            kotlinx.coroutines.delay(700)
        }
    }
}

@Composable
private fun SwitchRow(
    icon: androidx.compose.ui.graphics.vector.ImageVector,
    color: Color,
    title: String,
    subtitle: String,
    checked: Boolean,
    onCheckedChange: (Boolean) -> Unit,
) {
    ListItem(
        headlineContent = { Text(title) },
        supportingContent = {
            Text(
                subtitle,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        },
        leadingContent = { TintedIcon(icon, color, size = 18.dp, container = 34.dp) },
        trailingContent = { Switch(checked = checked, onCheckedChange = onCheckedChange) },
        modifier = Modifier.clickable { onCheckedChange(!checked) }.fillMaxWidth(),
    )
}

/** 档位选择：固定几档而不是滑杆——司机在车上没空调一个滑杆 */
@Composable
private fun ChoiceRow(title: String, current: Int, onPick: (Int) -> Unit) {
    Column(Modifier.fillMaxWidth().padding(vertical = 6.dp)) {
        Text(title, style = MaterialTheme.typography.bodyLarge)
        Spacer(Modifier.height(6.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            NewOrderAlert.REPEAT_CHOICES.forEach { n ->
                val selected = n == current
                Surface(
                    color = if (selected) Color(0xFF1E6FFF) else MaterialTheme.colorScheme.surfaceVariant,
                    shape = RoundedCornerShape(20.dp),
                    modifier = Modifier.clickable { onPick(n) },
                ) {
                    Text(
                        NewOrderAlert.repeatLabel(n),
                        style = MaterialTheme.typography.bodyMedium,
                        fontWeight = if (selected) FontWeight.Medium else FontWeight.Normal,
                        color = if (selected) Color.White else MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.padding(horizontal = 14.dp, vertical = 8.dp),
                    )
                }
            }
        }
    }
}

/** 需要用户去系统里做一件事的提示：说清"不做会怎样" + 一个能点的按钮 */
@Composable
private fun WarnCard(title: String, body: String, action: String, onClick: () -> Unit) {
    Surface(
        color = Color(0xFFFFF3E0),
        shape = RoundedCornerShape(12.dp),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Row(Modifier.padding(14.dp), verticalAlignment = Alignment.CenterVertically) {
            TintedIcon(Icons.Default.BatteryAlert, Color(0xFFFF9500), size = 18.dp, container = 34.dp)
            Spacer(Modifier.width(12.dp))
            Column(Modifier.weight(1f)) {
                Text(title, style = MaterialTheme.typography.bodyLarge, fontWeight = FontWeight.Medium)
                Spacer(Modifier.height(4.dp))
                Text(
                    body,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            Spacer(Modifier.width(8.dp))
            TextButton(onClick = onClick) { Text(action) }
        }
    }
}

// ---- 系统状态读取 / 跳转（都在这一页里，别处不用） ----

private fun notificationsAllowed(context: Context): Boolean {
    val nm = context.getSystemService(NotificationManager::class.java) ?: return false
    return nm.areNotificationsEnabled()
}

/** 省电策略是否"不受限制"。读这个状态不需要任何权限。 */
private fun batteryUnrestricted(context: Context): Boolean {
    val pm = context.getSystemService(PowerManager::class.java) ?: return true
    return pm.isIgnoringBatteryOptimizations(context.packageName)
}

private fun openNotificationSettings(context: Context) {
    val intent = Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS)
        .putExtra(Settings.EXTRA_APP_PACKAGE, context.packageName)
        .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
    startFirstResolvable(context, intent) {
        Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:" + context.packageName))
    }
}

private fun openBatterySettings(context: Context) {
    val list = Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS)
        .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
    startFirstResolvable(context, list) {
        Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:" + context.packageName))
    }
}

/**
 * 跳系统设置：首选页在个别 ROM 上不存在（各家都改过），
 * 所以留一个"应用详情页"兜底——**必须能点到某个设置页**，
 * 否则用户点「去开启」没反应，会以为 App 坏了。
 */
private fun startFirstResolvable(context: Context, preferred: Intent, fallback: () -> Intent) {
    val candidates = listOf(preferred, fallback().addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
    for (i in candidates) {
        if (i.resolveActivity(context.packageManager) != null) {
            runCatching { context.startActivity(i) }
            return
        }
    }
}
