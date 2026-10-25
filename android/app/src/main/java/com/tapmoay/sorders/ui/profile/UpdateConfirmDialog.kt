package com.tapmoay.sorders.ui.profile

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.height
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.tapmoay.sorders.ui.common.CardAlertDialog

/**
 * 「发现新版本」确认框 —— **唯一那一份**（CHG-0137）。
 *
 * 两个入口共用它：
 * 1. 用户手动点「我的 → 关于与更新」（[ProfileScreen]）；
 * 2. 冷启动自动提示（[com.tapmoay.sorders.ui.home.RoleHomeScreen]，见 CHG-0137）。
 *
 * ⛔ 别在第二处再抄一遍这段文案：两处的措辞、按钮名、带不带构建号会各自漂移，
 *    用户看到的就是"同一个 App 里两种更新提示"。
 *
 * ⚠️ 两行**都要带构建号**（2026-09-23 用户报障：只显示 0.2.3 时，
 *    「发现新版本 v0.2.3」与「当前版本：v0.2.3 · 2026092204」看着一模一样，他读成
 *    "让我重装当前版本"）。判新旧本来就是 versionCode，就把它显示出来 ——
 *    口径只有一处：[UpdateProgress.versionLabel]（有单测）。
 */
@Composable
fun UpdateConfirmDialog(
    version: String?,
    versionCode: Int?,
    currentVersion: String,
    note: String,
    onDownload: () -> Unit,
    onLater: () -> Unit,
) {
    CardAlertDialog(
        onDismissRequest = onLater,
        title = { Text("发现新版本 v" + UpdateProgress.versionLabel(version, versionCode)) },
        text = {
            Column {
                Text("当前版本：v" + currentVersion)
                Spacer(Modifier.height(6.dp))
                if (note.isNotBlank()) {
                    Text(note, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                Spacer(Modifier.height(10.dp))
                Text("是否立即下载并安装更新？", style = MaterialTheme.typography.titleSmall)
            }
        },
        confirmButton = {
            TextButton(onClick = onDownload) { Text("下载并更新") }
        },
        dismissButton = {
            TextButton(onClick = onLater) { Text("稍后") }
        },
    )
}
