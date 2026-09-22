package com.tapmoay.sorders.ui.common

import android.app.Activity
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.ui.platform.LocalView
import androidx.core.view.WindowCompat
import com.tapmoay.sorders.ui.theme.ThemeMode

/**
 * 这一段内容在屏上期间，把**状态栏图标改成浅色（白图标）**；离开时还原成主题该有的值。
 *
 * ## 为什么必须有它
 * 本 App 是 `enableEdgeToEdge()`（`MainActivity`），状态栏是**透明**的、内容直接铺到它下面。
 * 而 `SOrdersTheme` 在每次主题变化时会把图标设成 `isAppearanceLightStatusBars = !darkTheme`
 * ——也就是**浅色主题下是深色图标**。于是「我的」页那种**深墨蓝头部铺到状态栏下面**的写法
 * 会撞上它：浅色模式下深色图标压在深墨蓝上，**一个都看不见**（时间、电量、信号全消失，
 * 而且不报错、截图缩小看才发现）。
 *
 * ## 为什么是 DisposableEffect 而不是全局开关
 * 需要它的只有「我的」这一页。切 Tab、或从这一页推进子页（基础设置 / 消息提醒）时，
 * 这个 composable 会离开组合 → `onDispose` 把状态栏还原，子页的浅色 AppBar 上又变回深色图标。
 * 写成全局状态的话，就得有人在"离开"时记得关掉——**没人记得的那一天就是白图标压在浅色页上**。
 *
 * ⚠️ 它和 `SOrdersTheme` 的 `SideEffect` 是**同一个窗口属性**：主题切换（白天↔夜间）时
 *    主题后写一次、值仍然是"白图标"（因为这里要的就是不跟主题走），不会互相打架。
 */
@Composable
fun LightStatusBarIcons() {
    val view = LocalView.current
    DisposableEffect(view) {
        val window = (view.context as? Activity)?.window
        val controller = window?.let { WindowCompat.getInsetsController(it, view) }
        controller?.isAppearanceLightStatusBars = false
        onDispose {
            // 还原成主题自己的口径（与 SOrdersTheme 里那一行同一个表达式，**不另立一套**）
            controller?.isAppearanceLightStatusBars = !ThemeMode.isDark
        }
    }
}
