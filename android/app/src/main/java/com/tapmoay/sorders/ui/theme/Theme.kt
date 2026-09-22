package com.tapmoay.sorders.ui.theme

import android.app.Activity
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Shapes
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.runtime.SideEffect
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.unit.dp
import androidx.core.view.WindowCompat
import com.tapmoay.sorders.core.SunClock

/** 全局外观模式（白天/夜间 + 随日落自动）。落盘用 SharedPreferences，启动时同步读回。 */
object ThemeMode {
    var isDark by mutableStateOf(false)
        private set

    /** 随日落自动切换。默认关。 */
    var autoBySun by mutableStateOf(false)
        private set

    private const val PREF = "ui_theme"
    private const val KEY_DARK = "dark"
    private const val KEY_AUTO = "auto_sun"

    fun load(context: android.content.Context) {
        val p = prefs(context)
        autoBySun = p.getBoolean(KEY_AUTO, false)
        val dark = if (autoBySun) SunClock.stateHere().dark else p.getBoolean(KEY_DARK, false)
        isDark = dark
        if (autoBySun) p.edit().putBoolean(KEY_DARK, dark).apply()
    }

    /** 手动切换；自动模式下忽略（否则会被下一次对表改回去）。 */
    fun set(context: android.content.Context, dark: Boolean) {
        if (autoBySun) return
        apply(context, dark)
    }

    /** 打开/关闭自动切换；打开时立刻对一次表。 */
    fun setAuto(context: android.content.Context, on: Boolean) {
        autoBySun = on
        prefs(context).edit().putBoolean(KEY_AUTO, on).apply()
        if (on) refreshAuto(context)
    }

    /** 对一次表：有定位按真实经纬度，没有就退回时区估算。 */
    fun refreshAuto(context: android.content.Context) {
        if (!autoBySun) return
        apply(context, SunClock.stateHere().dark)
    }

    private fun apply(context: android.content.Context, dark: Boolean) {
        if (isDark == dark) return
        isDark = dark
        prefs(context).edit().putBoolean(KEY_DARK, dark).apply()
    }

    private fun prefs(context: android.content.Context) =
        context.applicationContext.getSharedPreferences(PREF, android.content.Context.MODE_PRIVATE)
}

/** 圆角 token（对标 iOS 卡片/控件圆角层级：小控件 10 / 卡片 16 / 弹层 28） */
private val AppShapes = Shapes(
    extraSmall = RoundedCornerShape(8.dp),
    small = RoundedCornerShape(10.dp),
    medium = RoundedCornerShape(16.dp),
    large = RoundedCornerShape(20.dp),
    extraLarge = RoundedCornerShape(28.dp),
)

private val LightColors = lightColorScheme(
    primary = Primary,
    onPrimary = OnPrimary,
    primaryContainer = PrimaryContainer,
    onPrimaryContainer = OnPrimaryContainer,
    secondaryContainer = SecondaryContainer,
    onSecondaryContainer = OnSecondaryContainer,
    tertiary = Tertiary,
    error = ErrorLight,
    errorContainer = ErrorContainerLight,
    background = BackgroundLight,
    onBackground = OnBackgroundLight,
    surface = SurfaceLight,
    onSurface = OnSurfaceLight,
    surfaceVariant = SurfaceVariantLight,
    onSurfaceVariant = OnSurfaceVariantLight,
    // ⚠️ 这一行不是"随手挑一个灰"：M3 的 ModalBottomSheet 容器默认读的就是 surfaceContainerLow
    //    （BottomSheetDefaults.ContainerColor → SheetBottomTokens.DockedContainerColor，
    //     反编译 material3 1.3.2 确认）→ **改这一行 = 改全 App 19 个底部抽屉的底色**。
    //    为什么必须是中性灰、为什么不能是白，见 Color.kt::SheetSurface 那段。
    surfaceContainerLow = SheetSurface,
    surfaceContainer = SurfaceContainer,
    surfaceContainerHigh = SurfaceContainerHigh,
    outline = OutlineLight,
    outlineVariant = OutlineVariantLight,
)

private val DarkColors = darkColorScheme(
    primary = PrimaryDark,
    onPrimary = OnPrimaryDark,
    primaryContainer = PrimaryContainerDark,
    onPrimaryContainer = OnPrimaryContainerDark,
    secondaryContainer = SecondaryContainerDark,
    onSecondaryContainer = OnSecondaryContainerDark,
    tertiary = TertiaryDark,
    error = ErrorDark,
    errorContainer = ErrorContainerDark,
    background = BackgroundDark,
    onBackground = OnBackgroundDark,
    surface = SurfaceDark,
    onSurface = OnSurfaceDark,
    surfaceVariant = SurfaceVariantDark,
    onSurfaceVariant = OnSurfaceVariantDark,
    surfaceContainerLow = SurfaceContainerLowDark,
    surfaceContainer = SurfaceContainerDark,
    surfaceContainerHigh = SurfaceContainerHighDark,
    outline = OutlineDark,
    outlineVariant = OutlineVariantDark,
)

@Composable
fun SOrdersTheme(
    darkTheme: Boolean = ThemeMode.isDark,
    content: @Composable () -> Unit,
) {
    val colorScheme = if (darkTheme) DarkColors else LightColors
    val view = LocalView.current
    if (!view.isInEditMode) {
        SideEffect {
            val window = (view.context as Activity).window
            window.statusBarColor = colorScheme.background.toArgb()
            WindowCompat.getInsetsController(window, view)
                .isAppearanceLightStatusBars = !darkTheme
        }
    }
    MaterialTheme(
        colorScheme = colorScheme,
        typography = Typography,
        shapes = AppShapes,
        content = content,
    )
}
