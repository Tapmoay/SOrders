package com.tapmoay.sorders.ui.common
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneOffset

import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsFocusedAsState
import androidx.compose.foundation.interaction.collectIsPressedAsState
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.runtime.setValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.composed
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.TextUnit
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.tapmoay.sorders.ui.theme.Success
import com.tapmoay.sorders.ui.theme.SuccessDark
import com.tapmoay.sorders.ui.theme.ThemeMode
import com.tapmoay.sorders.util.formatMoney

/** 订单状态徽章（三通道：图标 + 颜色 + 文字；老人/色弱均有兜底） */
@Composable
fun OrderStatusChip(status: String) {
    val icon: ImageVector
    val label: String
    /** `[亮底, 亮字, 暗底, 暗字]`——**必须全是 Color**，混进 String 会被推成 `List<Any>` 而编译不过。 */
    val p: List<Color>
    when (status) {
        "DISPATCHED" -> {
            icon = Icons.Default.Flag
            label = "已派单"
            p = listOf(Color(0xFFFFE8C2), Color(0xFF8A5300), Color(0xFF4A3200), Color(0xFFFFD9A0))
        }
        "PENDING_DISPATCH" -> {
            icon = Icons.Default.Schedule
            label = "派单中"
            p = listOf(Color(0xFFFFF1C6), Color(0xFF7A5900), Color(0xFF463800), Color(0xFFFFE08A))
        }
        "ACCEPTED" -> {
            icon = Icons.Default.LocalShipping
            label = "已接单"
            p = listOf(Color(0xFFD6E3FF), Color(0xFF0F4690), Color(0xFF14335E), Color(0xFFBBD3FF))
        }
        "DELIVERED" -> {
            icon = Icons.Default.CheckCircle
            label = "已送达"
            p = listOf(Color(0xFFD9F0DA), Success, Color(0xFF0E3A28), SuccessDark)
        }
        "CANCELLED" -> {
            icon = Icons.Default.Close
            label = "已撤销"
            p = listOf(Color(0xFFF1E4E4), Color(0xFF8C4040), Color(0xFF3A2626), Color(0xFFE0B0B0))
        }
        else -> {
            icon = Icons.Default.Info
            label = status
            p = listOf(Color(0xFFE1E2EC), Color(0xFF44464F), Color(0xFF2A2C33), Color(0xFFC7C9D1))
        }
    }
    val (bg, fg) = badgeColors(p[0], p[1], p[2], p[3])
    Surface(color = bg, shape = CircleShape) {
        Row(
            verticalAlignment = Alignment.CenterVertically,
            modifier = Modifier.padding(horizontal = 10.dp, vertical = 4.dp),
        ) {
            Icon(icon, contentDescription = null, tint = fg, modifier = Modifier.size(14.dp))
            Spacer(Modifier.width(4.dp))
            Text(
                text = label,
                color = fg,
                style = MaterialTheme.typography.labelMedium,
                fontWeight = FontWeight.Medium,
            )
        }
    }
}

/** 金额文本 */
@Composable
fun MoneyText(raw: String?, modifier: Modifier = Modifier, style: androidx.compose.ui.text.TextStyle = MaterialTheme.typography.bodyMedium, prefix: String = "¥") {
    Text(text = prefix + formatMoney(raw), style = style, modifier = modifier)
}

@Composable
fun EmptyView(text: String, modifier: Modifier = Modifier, icon: @Composable () -> Unit = {
    Icon(Icons.Default.Inbox, contentDescription = null, modifier = Modifier.size(56.dp), tint = MaterialTheme.colorScheme.outline)
}) {
    Column(
        modifier = modifier.fillMaxWidth().padding(vertical = 48.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        icon()
        Spacer(Modifier.height(12.dp))
        Text(text, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant, textAlign = TextAlign.Center)
    }
}

@Composable
fun LoadingBox(modifier: Modifier = Modifier) {
    Box(modifier.fillMaxWidth().padding(vertical = 48.dp), contentAlignment = Alignment.Center) {
        CircularProgressIndicator()
    }
}

@Composable
fun ErrorView(message: String, onRetry: (() -> Unit)? = null, modifier: Modifier = Modifier) {
    Column(
        modifier = modifier.fillMaxWidth().padding(vertical = 32.dp, horizontal = 24.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text(message, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.error, textAlign = TextAlign.Center)
        if (onRetry != null) {
            Spacer(Modifier.height(12.dp))
            OutlinedButton(onClick = onRetry) { Text("重试") }
        }
    }
}

/**
 * 页面顶栏（融入背景：iOS 大标题风格，顶栏与页面同灰色底，内容优先）
 *
 * @param subtitleTrailing 放在标题那一行的**行尾**（可空）。
 *   - **没有副标题**时：标题与它**同一行、垂直居中对齐**（整条顶栏就是一行，最紧凑）；
 *   - **有副标题**时：它落到副标题那一行的行尾（标题仍占第一行）。
 *
 *   为什么不放在 `actions` 里：在 `actions` 中放带 `weight` 的子项，Material3 的 `TopAppBar`
 *   会把标题列压成 0 宽——实测标题「AI 助手」直接消失（见 AiChatScreen 的注释）。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AppTopBar(
    title: String,
    subtitle: String? = null,
    onBack: (() -> Unit)? = null,
    subtitleTrailing: @Composable (() -> Unit)? = null,
    actions: @Composable RowScope.() -> Unit = {},
) {
    TopAppBar(
        colors = TopAppBarDefaults.topAppBarColors(
            containerColor = MaterialTheme.colorScheme.background,
        ),
        title = {
            if (subtitle.isNullOrBlank()) {
                // 单行形态：标题 + 行尾内容，整体垂直居中——用户要的"所有元件中心对齐"就是这个
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text(
                        title,
                        style = MaterialTheme.typography.titleLarge,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                        modifier = if (subtitleTrailing != null) Modifier.weight(1f) else Modifier,
                    )
                    subtitleTrailing?.invoke()
                }
            } else {
                Column {
                    Text(title, style = MaterialTheme.typography.titleLarge, maxLines = 1)
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        // 副标题占掉剩余宽度（文字仍靠左）；后面的 trailing 自然被顶到行尾。
                        // 副标题过长时自己省略，绝不把 trailing 挤走。
                        Text(
                            subtitle,
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                            modifier = Modifier.weight(1f),
                        )
                        subtitleTrailing?.invoke()
                    }
                }
            }
        },
        navigationIcon = {
            if (onBack != null) {
                IconButton(onClick = onBack) {
                    Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
                }
            }
        },
        actions = actions,
    )
}

/** 键值信息行 */
@Composable
fun InfoRow(label: String, value: String, modifier: Modifier = Modifier, valueColor: Color? = null) {
    Row(modifier.fillMaxWidth().padding(vertical = 6.dp)) {
        Text(
            label,
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.width(92.dp),
        )
        Text(
            value,
            style = MaterialTheme.typography.bodyMedium,
            color = valueColor ?: MaterialTheme.colorScheme.onSurface,
            modifier = Modifier.weight(1f),
        )
    }
}

/**
 * 分组卡片容器（iOS 分组卡片：白色圆角16 + 极轻阴影，无边框，靠灰底分层）。
 *
 * ⚠️ 暗色下**必须补一条描边**：亮色靠「白卡 + 灰底」分层、阴影只是锦上添花；
 * 而暗色里 `shadowElevation` 几乎看不见（黑底上的黑影），只靠色差的话卡片边缘会糊在一起。
 * 这条描边只在暗色下加，亮色仍然是"无边框靠灰底分层"的原设计。
 */
@Composable
fun SectionCard(modifier: Modifier = Modifier, content: @Composable ColumnScope.() -> Unit) {
    Surface(
        modifier = modifier.fillMaxWidth(),
        shape = MaterialTheme.shapes.medium,
        color = MaterialTheme.colorScheme.surface,
        tonalElevation = 0.dp,
        shadowElevation = 1.dp,
        border = if (ThemeMode.isDark) {
            BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.55f))
        } else {
            null
        },
    ) {
        Column(Modifier.padding(16.dp), content = content)
    }
}

/**
 * 徽章配色：**同一套色相，两种底色**。
 *
 * 亮色用「浅底 + 深字」，暗色必须换成「深底 + 亮字」。
 * 把浅粉彩底直接搬到暗色页面上，会在深色背景里戳出一块**发光的色块**——
 * 既刺眼，又和旁边已经调暗的卡片对不上（用户报的"感觉不是很好"就是这类）。
 *
 * 判据用 [ThemeMode.isDark]（驱动配色方案的那个开关），不用 `isSystemInDarkTheme()`：
 * 本 App 的外观是用户在「我的」里自己切的，和系统设置无关。
 */
@Composable
private fun badgeColors(lightBg: Color, lightFg: Color, darkBg: Color, darkFg: Color): Pair<Color, Color> =
    if (ThemeMode.isDark) darkBg to darkFg else lightBg to lightFg

/** 角色徽章 */
@Composable
fun RoleBadge(role: String) {
    val label: String
    /** `[亮底, 亮字, 暗底, 暗字]` */
    val p: List<Color>
    when (role) {
        "shipper" -> { label = "货主"; p = listOf(Color(0xFFD6F3FA), Color(0xFF005A78), Color(0xFF0B3644), Color(0xFF8FDCF0)) }
        "driver" -> { label = "司机"; p = listOf(Color(0xFFD5F5E9), Color(0xFF00624A), Color(0xFF0B3A2C), Color(0xFF8FE0C0)) }
        "dispatcher" -> { label = "派单员"; p = listOf(Color(0xFFDBE9FF), Color(0xFF0A4DAF), Color(0xFF12294F), Color(0xFFA8C8FF)) }
        else -> { label = role; p = listOf(Color(0xFFE1E2EC), Color(0xFF44464F), Color(0xFF2A2C33), Color(0xFFC7C9D1)) }
    }
    val (bg, fg) = badgeColors(p[0], p[1], p[2], p[3])
    Surface(color = bg, shape = CircleShape) {
        Text(text = label, color = fg, style = MaterialTheme.typography.labelMedium, modifier = Modifier.padding(horizontal = 10.dp, vertical = 4.dp))
    }
}

// ==================== 适老化组件体系（批1：全局统一） ====================

/** 进程内危险操作确认记忆：同一操作弹过一次后，本次运行不再弹（掉线/撤回兜底放宽） */
object ConfirmMemory {
    private val done = mutableSetOf<String>()
    fun shouldConfirm(key: String): Boolean = done.add(key)
}

/** 按压弹性反馈（0.97 缩放，轻快引导） */
fun Modifier.pressScale(interactionSource: MutableInteractionSource): Modifier =
    this.then(
        Modifier.composed {
            val pressed by interactionSource.collectIsPressedAsState()
            val scale by animateFloatAsState(if (pressed) 0.97f else 1f, label = "press")
            graphicsLayer { scaleX = scale; scaleY = scale }
        }
    )

/** 主行动按钮：全宽 56dp，实底语义色 + 白图标 + 加粗文字 + 按压缩放（一屏一眼的主操作） */
@Composable
fun PrimaryActionButton(
    text: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    icon: ImageVector? = null,
    containerColor: Color = Color(0xFF1E6FFF),
    enabled: Boolean = true,
) {
    val interaction = remember { MutableInteractionSource() }
    Button(
        onClick = onClick,
        enabled = enabled,
        interactionSource = interaction,
        modifier = modifier
            .height(56.dp)
            .pressScale(interaction),
        shape = MaterialTheme.shapes.medium,
        colors = ButtonDefaults.buttonColors(
            containerColor = containerColor,
            contentColor = Color.White,
        ),
    ) {
        if (icon != null) {
            Icon(icon, contentDescription = null, modifier = Modifier.size(20.dp))
            Spacer(Modifier.width(8.dp))
        }
        Text(text, style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Bold)
    }
}

/** 危险操作确认框：居中弹窗 + 红色确认钮（首次执行弹，重复执行走 ConfirmMemory 免弹） */
@Composable
fun DangerConfirmDialog(
    title: String,
    message: String,
    confirmText: String = "确认",
    onConfirm: () -> Unit,
    onDismiss: () -> Unit,
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(title, style = MaterialTheme.typography.titleMedium) },
        text = { Text(message, style = MaterialTheme.typography.bodyMedium) },
        confirmButton = {
            Button(
                onClick = onConfirm,
                colors = ButtonDefaults.buttonColors(
                    containerColor = MaterialTheme.colorScheme.error,
                    contentColor = Color.White,
                ),
            ) { Text(confirmText) }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) { Text("取消") }
        },
    )
}

/** iOS 风格输入框：浅灰底 + 圆角12 + 无漂浮标签（聚焦时主色细描边），替代 M3 描边文本域 */
@Composable
fun SoTextField(
    value: String,
    onValueChange: (String) -> Unit,
    modifier: Modifier = Modifier,
    placeholder: String? = null,
    keyboardType: KeyboardType = KeyboardType.Text,
    enabled: Boolean = true,
) {
    val interaction = remember { MutableInteractionSource() }
    val focused by interaction.collectIsFocusedAsState()
    val bg = if (enabled) MaterialTheme.colorScheme.surfaceVariant else MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.5f)
    BasicTextField(
        value = value,
        onValueChange = onValueChange,
        enabled = enabled,
        interactionSource = interaction,
        singleLine = true,
        textStyle = MaterialTheme.typography.bodyLarge.copy(color = MaterialTheme.colorScheme.onSurface),
        keyboardOptions = KeyboardOptions(keyboardType = keyboardType),
        cursorBrush = SolidColor(MaterialTheme.colorScheme.primary),
        modifier = modifier
            .fillMaxWidth()
            .height(52.dp)
            .clip(RoundedCornerShape(12.dp))
            .background(bg)
            .border(
                width = if (focused) 2.dp else 1.dp,
                color = if (focused) MaterialTheme.colorScheme.primary else Color.Transparent,
                shape = RoundedCornerShape(12.dp),
            ),
        decorationBox = { inner ->
            Box(
                modifier = Modifier.fillMaxSize().padding(horizontal = 14.dp),
                contentAlignment = Alignment.CenterStart,
            ) {
                if (value.isEmpty() && !placeholder.isNullOrBlank()) {
                    Text(placeholder, style = MaterialTheme.typography.bodyLarge, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                inner()
            }
        },
    )
}

/**
 * 通用日期范围筛选（订单/账本/库存流水复用）：全部/今天/近7天/本月 + 自定义起止日期。
 * 回调 onChange(dateFrom, dateTo)：null=不限；格式 YYYY-MM-DD。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DateRangeFilter(onChange: (String?, String?) -> Unit, modifier: Modifier = Modifier) {
    var preset by remember { mutableStateOf("全部") }
    var customFrom by remember { mutableStateOf<String?>(null) }
    var customTo by remember { mutableStateOf<String?>(null) }
    var showDialog by remember { mutableStateOf(false) }
    var showDatePicker by remember { mutableStateOf(false) }
    var pickingField by remember { mutableStateOf("from") }

    fun apply(p: String) {
        preset = p
        val today = LocalDate.now()
        when (p) {
            "全部" -> onChange(null, null)
            "今天" -> onChange(today.toString(), today.toString())
            "近7天" -> onChange(today.minusDays(6).toString(), today.toString())
            "本月" -> onChange(today.withDayOfMonth(1).toString(), today.toString())
        }
    }

    Row(modifier.fillMaxWidth().horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        listOf("全部", "今天", "近7天", "本月").forEach { p ->
            val selected = preset == p
            Surface(
                onClick = { apply(p) },
                shape = CircleShape,
                color = if (selected) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.surface,
                contentColor = if (selected) Color.White else MaterialTheme.colorScheme.onSurfaceVariant,
                shadowElevation = if (selected) 0.dp else 1.dp,
                modifier = Modifier.height(38.dp),
            ) {
                Box(Modifier.padding(horizontal = 16.dp), contentAlignment = Alignment.Center) {
                    Text(p, style = MaterialTheme.typography.labelLarge)
                }
            }
        }
        val fromLocal = customFrom
        val toLocal = customTo
        val customLabel = if (fromLocal != null && toLocal != null)
            fromLocal.substring(5) + "~" + toLocal.substring(5) else "自定义"
        val customSelected = preset == "自定义"
        Surface(
            onClick = { showDialog = true },
            shape = CircleShape,
            color = if (customSelected) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.surface,
            contentColor = if (customSelected) Color.White else MaterialTheme.colorScheme.onSurfaceVariant,
            shadowElevation = if (customSelected) 0.dp else 1.dp,
            modifier = Modifier.height(38.dp),
        ) {
            Box(Modifier.padding(horizontal = 16.dp), contentAlignment = Alignment.Center) {
                Text(customLabel, style = MaterialTheme.typography.labelLarge)
            }
        }
    }

    if (showDialog) {
        AlertDialog(
            onDismissRequest = { showDialog = false },
            title = { Text("选择日期范围") },
            text = {
                Column {
                    TextButton(onClick = { pickingField = "from"; showDatePicker = true }) {
                        Text("开始日期：" + (customFrom ?: "未选择"))
                    }
                    TextButton(onClick = { pickingField = "to"; showDatePicker = true }) {
                        Text("结束日期：" + (customTo ?: "未选择"))
                    }
                }
            },
            confirmButton = {
                TextButton(onClick = {
                    showDialog = false
                    val f = customFrom
                    val t = customTo
                    if (f != null && t != null) {
                        preset = "自定义"
                        onChange(f, t)
                    } else if (f == null && t == null) {
                        preset = "全部"
                        onChange(null, null)
                    }
                }) { Text("应用") }
            },
            dismissButton = { TextButton(onClick = { showDialog = false }) { Text("取消") } },
        )
    }

    if (showDatePicker) {
        val dpState = rememberDatePickerState()
        DatePickerDialog(
            onDismissRequest = { showDatePicker = false },
            confirmButton = {
                TextButton(onClick = {
                    dpState.selectedDateMillis?.let { millis ->
                        val d = Instant.ofEpochMilli(millis).atZone(ZoneOffset.UTC).toLocalDate()
                        if (pickingField == "from") customFrom = d.toString() else customTo = d.toString()
                    }
                    showDatePicker = false
                }) { Text("确定") }
            },
            dismissButton = { TextButton(onClick = { showDatePicker = false }) { Text("取消") } },
        ) {
            DatePicker(state = dpState)
        }
    }
}

/**
 * 分段选择器：**同一维度的少量互斥选项**（如「思考强度：关/低/中/高」）。
 *
 * 形态学沿用本 App 已有的 [SegmentedStatusTabs]（独立圆角块 + 间距分隔 + 选中淡色底加粗），
 * 两处区别是有意的：
 * - 这里只有**一个强调色**（同一维度的程度差异，不需要五个语义色）；
 * - 等宽分段（`weight(1f)`），让"一共几档"一眼可见，也不用担心某一档文字长就把别的挤跑。
 *
 * 不用 Material3 的 `SegmentedButton`：它在本项目的 BOM 下仍是实验 API，
 * 而且默认形态（连成一条、只有一条细描边）与本 App 的块状语言不一致。
 *
 * @param accent 选中色（默认主题蓝；AI 页传自己的强调色）
 * @param height 段高，默认 44dp（≥ 手指友好下限，且比 48dp 工具条矮一点，不抢视觉）
 */
@Composable
fun SegmentedPicker(
    labels: List<String>,
    selected: Int,
    onSelect: (Int) -> Unit,
    modifier: Modifier = Modifier,
    accent: Color = Color(0xFF1E6FFF),
    height: Dp = 44.dp,
    fontSize: TextUnit = 16.sp,
) {
    Row(
        modifier = modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        labels.forEachIndexed { i, label ->
            val sel = selected == i
            Surface(
                onClick = { onSelect(i) },
                shape = RoundedCornerShape(12.dp),
                color = if (sel) accent.copy(alpha = 0.14f) else MaterialTheme.colorScheme.surface,
                border = BorderStroke(
                    1.dp,
                    if (sel) accent.copy(alpha = 0.55f) else MaterialTheme.colorScheme.outlineVariant,
                ),
                modifier = Modifier.weight(1f).height(height),
            ) {
                Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                    Text(
                        label,
                        fontSize = fontSize,
                        fontWeight = if (sel) FontWeight.Bold else FontWeight.Medium,
                        color = if (sel) accent else MaterialTheme.colorScheme.onSurfaceVariant,
                        maxLines = 1,
                    )
                }
            }
        }
    }
}

/**
 * **一次性提示条**：先消费消息、再显示。
 *
 * ## 为什么必须集中成一个函数（2026-09-18 用户报的 bug）
 * 之前十几处页面都是这么写的：
 * ```kotlin
 * LaunchedEffect(vm.notice) {
 *     vm.notice?.let {
 *         snackbar.showSnackbar(it)   // ← 会挂起（默认约 4 秒）
 *         vm.notice = null            // ← 切页时协程被取消，这一行**永远不执行**
 *     }
 * }
 * ```
 * 而**页面状态（ViewModel）是 Activity 级的，切页不销毁** —— 于是用户切到别的
 * 底部 Tab 再切回来，`notice` 还在，提示条**又冒出来一次**。
 * 用户原话：「切回来显示框还是存在，应该是切换画面之后那个显示框直接消失」。
 *
 * 修法只有一个方向：**把"消费"挪到"显示"之前**。这样提示条中途被切页打断时，
 * 消息已经被取走，回来自然不会再弹 —— 这正是用户要的行为。
 *
 * ⚠️ 只对**状态驱动**的提示有意义（`LaunchedEffect(vm.xxx)`）。
 *    点一下就弹的那种（`scope.launch { snackbar.showSnackbar("已复制") }`）本来就不会重放，
 *    直接调 `showSnackbar` 即可，不用绕这一层。
 *
 * @param message 待显示的消息；null = 什么都不做
 * @param onConsumed 把消息置空（**在显示之前**调用）
 */
@Composable
fun OneShotSnackbar(
    hostState: SnackbarHostState,
    message: String?,
    onConsumed: () -> Unit,
) {
    LaunchedEffect(message) {
        if (message == null) return@LaunchedEffect
        onConsumed()
        hostState.showSnackbar(message)
    }
}

/**
 * 「服务端这一页不是全部」的提示文案 —— **唯一**一份措辞（6 个只回一页的列表页共用）。
 *
 * 参数 [howToSeeMore] 是"另外还能怎么看到"：这句话必须**能照着做**，而各页能用的
 * 筛选不一样（日期范围 / 搜索框 / 只能导出），所以尾巴由调用方给，前半句同源。
 *
 * ⛔ 为什么不是"加载更多"：这些端点的 `limit` 是**服务端上限**，不是页码；
 *    正确出路是页面上**已有的筛选**（`X-Truncated` 只说"被截断了"，不提供翻页游标）。
 * ⛔ [limit] 读不到时（老后端没有 `X-Result-Limit`）**不说条数** ——
 *    编一个数或说"最近 null 条"都比不说更糟：用户会拿这个数去核对。
 */
fun truncationHint(limit: Int?, howToSeeMore: String): String =
    (if (limit != null) "只显示了最近 $limit 条（服务器上限）" else "只显示了最近一部分（服务器没回报条数）") +
        "，" + howToSeeMore

/** [truncationHint] 的渲染；`truncated = false` 时什么都不显示（判据来自响应头）。 */
@Composable
fun TruncationNote(limit: Int?, howToSeeMore: String, modifier: Modifier = Modifier) {
    Text(
        truncationHint(limit, howToSeeMore),
        style = MaterialTheme.typography.bodySmall,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        modifier = modifier,
    )
}

