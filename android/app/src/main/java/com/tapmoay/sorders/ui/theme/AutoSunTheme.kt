package com.tapmoay.sorders.ui.theme

import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.ui.platform.LocalContext
import com.tapmoay.sorders.core.SunClock
import kotlinx.coroutines.delay

private const val MAX_SLEEP_MS = 15 * 60 * 1000L

private const val MIN_SLEEP_MS = 30 * 1000L

/** 挂在根节点上的定时器：到点切换外观。睡眠上限 15 分钟，用于改系统时间/换时区后自愈。 */
@Composable
fun AutoSunThemeEffect() {
    val context = LocalContext.current
    val auto = ThemeMode.autoBySun
    LaunchedEffect(auto) {
        if (!auto) return@LaunchedEffect
        while (true) {
            ThemeMode.refreshAuto(context)
            val next = SunClock.stateHere().nextSwitchAt
            val wait = if (next == null) MAX_SLEEP_MS else next - System.currentTimeMillis()
            delay(wait.coerceIn(MIN_SLEEP_MS, MAX_SLEEP_MS))
        }
    }
}
