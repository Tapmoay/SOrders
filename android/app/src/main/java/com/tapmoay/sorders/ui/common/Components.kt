package com.tapmoay.sorders.ui.common
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneOffset

import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
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
import androidx.compose.material.icons.automirrored.filled.AssignmentReturn
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
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
import com.tapmoay.sorders.core.HintPrefs
import com.tapmoay.sorders.data.remote.dto.OrderProductDto
import kotlinx.coroutines.launch
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
        // 已退货（2026-09-20）：⛔ 这一档**必须**有中文名与配色 ——
        // 落到下面的 `else` 分支上，徽章里会直接印出 `RETURNED` 这个原始码。
        // 配色是"货回来了、钱退了"的橙棕，与「已撤销」的灰红分得开（一个是没发生过、一个是发生过又退回来）。
        "RETURNED" -> {
            icon = Icons.AutoMirrored.Filled.AssignmentReturn
            label = "已退货"
            p = listOf(Color(0xFFFFE3D2), Color(0xFF8A3B00), Color(0xFF43230F), Color(0xFFFFC9A8))
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
 * 通用日期范围筛选（订单/账本/库存流水复用）：档位胶囊 + 自定义起止日期。
 * 回调 onChange(dateFrom, dateTo)：null=不限；格式 YYYY-MM-DD。
 *
 * ⚠️ 档位与它们的区间在 `DatePresets`（**唯一一份实现**），胶囊那一行在 [DatePresetRow]。
 *    自己在这里再写一遍 `when(档位)`，就会出现"账本页的本月和这里的本月差几天"。
 * ⚠️ 状态在这个组件内部（筛选条用完就丢）；账本页要把它存进 ViewModel（换档要联动查询），
 *    所以直接用 [DatePresetRow] + [DateRangeDialog]，不要用这个。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DateRangeFilter(onChange: (String?, String?) -> Unit, modifier: Modifier = Modifier) {
    var preset by remember { mutableStateOf(DatePresets.ALL) }
    var customFrom by remember { mutableStateOf<String?>(null) }
    var customTo by remember { mutableStateOf<String?>(null) }
    var showDialog by remember { mutableStateOf(false) }

    DatePresetRow(
        selected = preset,
        customFrom = customFrom,
        customTo = customTo,
        onPick = { p ->
            if (p == DatePresets.CUSTOM) {
                showDialog = true
            } else {
                preset = p
                val r = DatePresets.rangeOf(p, LocalDate.now())
                onChange(r?.first, r?.second)
            }
        },
        modifier = modifier,
    )

    if (showDialog) {
        DateRangeDialog(
            initialFrom = customFrom,
            initialTo = customTo,
            onDismiss = { showDialog = false },
            onApply = { f, t ->
                preset = if (f == null && t == null) DatePresets.ALL else DatePresets.CUSTOM
                customFrom = f
                customTo = t
                onChange(f, t)
            },
        )
    }
}

/**
 * 日期档位那一行（胶囊）—— **唯一一份实现**：订单/账本/库存流水的筛选条与派单员账本都用它。
 *
 * 状态由调用方持有（[selected] / [customFrom] / [customTo]，见 [DateRangeFilter] 与
 * `DispatcherLedgerViewModel`）：账本页换一档要联动重新查询，所以它必须存在 ViewModel 里；
 * 那几个筛选条 `remember` 就够。这一行只负责画。
 */
@Composable
fun DatePresetRow(
    selected: String,
    customFrom: String?,
    customTo: String?,
    onPick: (String) -> Unit,
    modifier: Modifier = Modifier,
) {
    Row(
        modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        DatePresets.ROW.forEach { p ->
            DatePill(label = p, selected = selected == p, onClick = { onPick(p) })
        }
        DatePill(
            label = DatePresets.customLabel(customFrom, customTo),
            selected = selected == DatePresets.CUSTOM,
            onClick = { onPick(DatePresets.CUSTOM) },
        )
    }
}

/**
 * **紧凑时间药丸**：写着当前窗口（「本月」/「09-01~09-20」/「全部」），点开是档位清单。
 *
 * 为什么要有它（2026-09-20 账本页第五轮）：用户看真机说
 * 「那个时间也太复杂了，换一种**崭新形式**，但是**时间和选择人物不要一样的展现形式**」。
 * [DatePresetRow] 那条胶囊行是给**筛选条**用的（横着铺、和别的筛选控件并排）；
 * 账本页上面已经有"人员"那一行，再铺一行胶囊就是两排长得一样的控件，而且 9 档要滑两屏。
 *
 * 药丸放在**顶栏**：当前窗口**永远看得见** —— 这一页最容易搞错的就是口径词
 * （「本月」和「近 7 天」差的那几天没人说得清）。
 */
@Composable
fun DatePresetPill(label: String, onClick: () -> Unit, modifier: Modifier = Modifier) {
    Surface(
        onClick = onClick,
        shape = CircleShape,
        color = MaterialTheme.colorScheme.surface,
        contentColor = MaterialTheme.colorScheme.onSurface,
        shadowElevation = 1.dp,
        modifier = modifier.padding(end = 12.dp).height(36.dp),
    ) {
        Row(
            Modifier.padding(horizontal = 12.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Icon(Icons.Default.CalendarMonth, contentDescription = "时间", modifier = Modifier.size(16.dp))
            Spacer(Modifier.width(6.dp))
            Text(label, style = MaterialTheme.typography.labelLarge, maxLines = 1)
            Icon(Icons.Default.ArrowDropDown, contentDescription = null, modifier = Modifier.size(18.dp))
        }
    }
}

/**
 * 时间档位清单（点 [DatePresetPill] 打开）—— 一档一行、右边打勾。
 *
 * ⚠️ 档位与区间**仍然只有一份实现**（`DatePresets.rangeOf`）：这里只负责把 [DatePresets.ROW]
 *    画出来、把选中的那一档回给调用方。谁也别在这里 `when(档位)` 自己算日期。
 * ⚠️ 「自定义」那一行显示的是**选中的那段日期**（`09-01~09-20`），不是光写"自定义"三个字 ——
 *    只写那三个字，用户就分不清自己选的到底是哪一段。
 */
@Composable
fun DatePresetDialog(
    selected: String,
    customFrom: String?,
    customTo: String?,
    onPick: (String) -> Unit,
    onDismiss: () -> Unit,
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("看哪一段时间") },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState())) {
                (DatePresets.ROW + DatePresets.CUSTOM).forEach { label ->
                    val shown = if (label == DatePresets.CUSTOM) {
                        DatePresets.customLabel(customFrom, customTo)
                    } else {
                        label
                    }
                    Row(
                        Modifier.fillMaxWidth().clickable { onPick(label) }.padding(vertical = 12.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Text(
                            shown,
                            style = MaterialTheme.typography.bodyLarge,
                            fontWeight = if (label == selected) FontWeight.Bold else FontWeight.Normal,
                            modifier = Modifier.weight(1f),
                        )
                        if (label == selected) {
                            Icon(
                                Icons.Default.Check,
                                contentDescription = "当前档位",
                                tint = MaterialTheme.colorScheme.primary,
                            )
                        }
                    }
                }
            }
        },
        confirmButton = { TextButton(onClick = onDismiss) { Text("关闭") } },
    )
}

/**
 * 「时间药丸」的**两个弹层 + 它们之间的状态机** —— 五个页面共用这一份（2026-09-21 精简轮）。
 *
 * ## 原来是什么样
 * 派单账本 / 货主账本 / 司机任务 / 司机运费 / 开销**各写一遍**同样的两段：
 * `if (showDatePresets) { DatePresetDialog(…) }` ＋ `if (showCustomRange) { DateRangeDialog(…) }`，
 * 一共约 130 行，而且里面藏着一条最容易写错的规矩 ——
 * **选中「自定义」要"先关档位清单、再开日期弹层"**（顺序反了或漏了，表现是"点了自定义什么都没发生"）。
 * 五份副本＝这条规矩要改五次，漏一处只有用户点得到才发现。
 *
 * ## 页面只需要记住一个开关
 * ```kotlin
 * var showPresets by remember { mutableStateOf(false) }
 * DatePresetPill(label = vm.periodWord, onClick = { showPresets = true })
 * DateFilterDialogs(
 *     showPresets = showPresets,
 *     onDismissPresets = { showPresets = false },
 *     preset = vm.preset, customFrom = vm.customFrom, customTo = vm.customTo,
 *     onPickPreset = vm::applyPreset, onApplyCustom = vm::applyCustomRange,
 * )
 * ```
 * 第二个弹层（自定义区间）的开关**由这里自己持有**：页面从来不需要读它，只需要"要不要画"。
 * ⚠️ [showPresets] 与 [onDismissPresets] 由调用方给（账本页那份状态在 ViewModel 里，
 * 别的页面 `remember` 就够），所以这里**不替调用方持有第一个开关** —— 否则账本页换档
 * 要联动重新查询的那条链就断了。
 */
@Composable
fun DateFilterDialogs(
    showPresets: Boolean,
    onDismissPresets: () -> Unit,
    preset: String,
    customFrom: String?,
    customTo: String?,
    onPickPreset: (String) -> Unit,
    onApplyCustom: (String?, String?) -> Unit,
) {
    var showCustom by remember { mutableStateOf(false) }

    if (showPresets) {
        DatePresetDialog(
            selected = preset,
            customFrom = customFrom,
            customTo = customTo,
            onPick = { label ->
                onDismissPresets()
                // 「自定义」不由档位表给区间（它要选两头日期）→ 接着开日期弹层。
                // ⛔ 顺序不能反：先关清单、再开弹层，同一帧里切换不会闪。
                if (label == DatePresets.CUSTOM) showCustom = true else onPickPreset(label)
            },
            onDismiss = onDismissPresets,
        )
    }
    if (showCustom) {
        DateRangeDialog(
            initialFrom = customFrom,
            initialTo = customTo,
            onDismiss = { showCustom = false },
            onApply = { f, t ->
                showCustom = false
                onApplyCustom(f, t)
            },
        )
    }
}

@Composable
private fun DatePill(label: String, selected: Boolean, onClick: () -> Unit) {
    Surface(
        onClick = onClick,
        shape = CircleShape,
        color = if (selected) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.surface,
        contentColor = if (selected) Color.White else MaterialTheme.colorScheme.onSurfaceVariant,
        shadowElevation = if (selected) 0.dp else 1.dp,
        modifier = Modifier.height(38.dp),
    ) {
        Box(Modifier.padding(horizontal = 16.dp), contentAlignment = Alignment.Center) {
            Text(label, style = MaterialTheme.typography.labelLarge)
        }
    }
}

/**
 * 「选一段日期」的弹层 —— **唯一实现**：通用筛选 [DateRangeFilter] 与司机运费结算页共用。
 *
 * [onApply] 只在**两头都选好**、或者**两头都没选**（= 清掉区间）时回调；
 * 只选了一头就点「应用」＝什么都不做（半截区间在两边都不成立：一个没有起点或没有终点的窗口，
 * 拿它去查询要么查全量、要么查出个空列表，两种都不是用户想要的）。
 *
 * ⚠️ 抽出来是因为 2026-09-20 司机运费结算页也要"选一段时间看" ——
 *    再抄一份 `DatePickerDialog` 的后果是两处的"取消/应用"语义、日期换算各走各的，
 *    而这类差异只有在某个页面表现不对时才会被发现。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DateRangeDialog(
    initialFrom: String?,
    initialTo: String?,
    onDismiss: () -> Unit,
    onApply: (String?, String?) -> Unit,
) {
    // 草稿态：选了不点「应用」就不算数（与弹层的通用语义一致）
    var from by remember { mutableStateOf(initialFrom) }
    var to by remember { mutableStateOf(initialTo) }
    var pickingField by remember { mutableStateOf("from") }
    var showDatePicker by remember { mutableStateOf(false) }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("选择日期范围") },
        text = {
            Column {
                TextButton(onClick = { pickingField = "from"; showDatePicker = true }) {
                    Text("开始日期：" + (from ?: "未选择"))
                }
                TextButton(onClick = { pickingField = "to"; showDatePicker = true }) {
                    Text("结束日期：" + (to ?: "未选择"))
                }
            }
        },
        confirmButton = {
            TextButton(onClick = {
                val f = from
                val t = to
                when {
                    f != null && t != null -> onApply(f, t)
                    f == null && t == null -> onApply(null, null)
                    // 只选了一头：不回调（见上面的注释），弹层照常关掉，用户能立刻重选
                }
                onDismiss()
            }) { Text("应用") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("取消") } },
    )

    if (showDatePicker) {
        val dpState = rememberDatePickerState()
        DatePickerDialog(
            onDismissRequest = { showDatePicker = false },
            confirmButton = {
                TextButton(onClick = {
                    dpState.selectedDateMillis?.let { millis ->
                        val d = Instant.ofEpochMilli(millis).atZone(ZoneOffset.UTC).toLocalDate()
                        if (pickingField == "from") from = d.toString() else to = d.toString()
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
 * ## ⛔ 显示必须挂在**不受 key 变化影响**的作用域上（2026-09-22 真机实证的回归）
 *
 * 上面那条"先消费、再显示"的修法本身**换来了一个新 bug**：`onConsumed()` 会把 `message`
 * 置空，而 `message` 正是 `LaunchedEffect(message)` 的 **key** —— key 一变，正在跑的协程
 * 立刻被取消，于是紧接着那句 `showSnackbar` 要么没跑、要么刚注册就被撤掉：
 * **提示条全 App 都不显示**。真机连拍 30+ 帧（每帧 MD5 相同）实证：界面上从来没有提示条，
 * 而操作本身是成功的（列表状态都变了）—— 这是最难发现的一类 bug：**它只是不说话**。
 *
 * 所以两件事要**同时**成立（只做一件就会回到某一个旧 bug）：
 * 1. **先消费**（保住"切页回来不重放"——用户 2026-09-18 要的行为）；
 * 2. **显示交给 [rememberCoroutineScope]**：那个作用域的生命周期是这个 Composable 本身，
 *    不随 key 变化取消（离开页面时自然取消，提示条跟着消失，正是期望行为）。
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
    val scope = rememberCoroutineScope()
    LaunchedEffect(message) {
        val text = message ?: return@LaunchedEffect
        onConsumed()
        scope.launch { hostState.showSnackbar(text) }
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

/**
 * 表单里的一句话错误 —— 画在**抽屉 / 弹窗内部**、提交按钮的上方。
 *
 * ## 为什么必须有这么一个东西（2026-09-19 真机缺陷）
 * 用户报：「我新建了一个地点，但是我没有填任何地址，直接点击保存，然后再返回去的时候，
 * 它那个地点库的**所有列表全消失了**，需要重新连接」。根因不是断线，是**错误的落点**：
 * 表单的校验错误写进了**页面级**的错误状态，而页面级错误会把整页换成
 * 「一句话 + 重试」（`ErrorView`）—— 于是同一句话造成两个假象：
 *
 * | 用户看到的 | 真相 |
 * |---|---|
 * | 点「保存」**没有任何反应** | 那句话画在抽屉**背后**，被抽屉盖住了 |
 * | 关掉抽屉后**三个列表全没了** | 那句话还挂着，整页被 `ErrorView` 顶掉；一条数据都没丢 |
 *
 * 所以规矩是：**表单的错误必须和表单同生共死** —— 画在表单里、打开表单时清掉。
 * 页面级错误状态只留给"这一页的数据没加载出来"。
 */
@Composable
fun FormErrorLine(text: String?, modifier: Modifier = Modifier) {
    if (text.isNullOrBlank()) return
    Row(
        modifier.fillMaxWidth().padding(top = 4.dp),
        verticalAlignment = Alignment.Top,
    ) {
        Icon(
            Icons.Default.ErrorOutline,
            contentDescription = null,
            tint = MaterialTheme.colorScheme.error,
            modifier = Modifier.size(16.dp),
        )
        Spacer(Modifier.width(6.dp))
        Text(
            text,
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.error,
        )
    }
}

/**
 * 解释性提示：**最多出现 3 次**，第 4 次起再也不出现（用户 2026-09-20 定的规矩）。
 *
 * 用户原话：
 * > 有些功能不需要说太多，只需要简单的一句话，大概字数最多是 7 到 8 个字就可以了…
 * > 或者你可以这样子：第一次和第二次的时候它是出现在那里，下次再点击的时候它就不会有了…
 * > 第四次就不会有了。
 *
 * 于是界面上的文字分两类，各归各的：
 * - **常驻的数/标签/按钮** → 几个字（"地点名"「补导航」），给已经会的人看；
 * - **解释"按下去会发生什么"的话** → 走这里，说三遍就够，之后让位给功能本身。
 *
 * ⚠️ [key] 是**永久身份**（`"order.nav_block"`），不是屏幕上那句话：
 *    改文案不该让用户重新看三遍，换一句话也不该共用别人的额度。
 * ⚠️ 计数在**进入这一次**就 +1（不是"停留时长"）：用户在三个页面之间来回切，
 *    那就是三次"看到"——这也正是他要的"下次再点击就没有了"。
 */
@Composable
fun HintOnce(prefs: HintPrefs, key: String, text: String, modifier: Modifier = Modifier) {
    // 同步读（SharedPreferences）：合成时就要决定画不画（见 `HintPrefs` 的注释）
    val show = remember(key) { prefs.hasLeft(key) }
    LaunchedEffect(key) {
        if (show) prefs.markSeen(key)
    }
    if (!show) return
    Text(
        text,
        style = MaterialTheme.typography.bodySmall,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        modifier = modifier,
    )
}

/**
 * 两栏版式左边那一列（"篮子"）的一行。
 *
 * [key] 用来判选中（分类名 / 司机 id / 来源名），[label] 是给人看的。
 * 两者**故意分开**：司机那一列的 key 是 `d|12`，而屏幕上写的是「王建国」——
 * 拿显示名当 key 的话，两个同名司机就会互相点亮（真机上有 293 个司机，重名不是假想）。
 */
data class RailItem(
    val key: String,
    val label: String,
    /** 第二行小字（数量/金额/单数…）；null = 只有一行。 */
    val subtitle: String? = null,
    /**
     * 图标。**只有"这一列是页面级导航"时才给**（派单员账本那 8 格要"图标 + 文字"）；
     * 分类/司机/地址来源那些不带 —— 它们本身就是有名字的类别，加图标只会让一列更花。
     */
    val icon: ImageVector? = null,
    /** 图标语义色；null = 跟着选中态走（未选中用弱化色）。 */
    val iconTint: Color? = null,
    /**
     * 分组标题：这一格的分组**与上一格不同**时，在它上面画一条小标题
     * （账本的「账本 / 工具」——不分组的话用户分不清哪几格是切右边、哪几格是离开这一页）。
     */
    val section: String? = null,
)

/**
 * 两栏版式左边那一列 —— **分类 / 司机 / 地址来源三处共用这一份**（用户 2026-09-19 连着要了
 * 三个"像商品管理那样"的界面：库存、运费结算、下单地址库）。
 *
 * 选中态：整块换白底 + 左侧一条**语义色**竖条（外卖 App 的通用写法，一眼看出现在在哪一类），
 * 未选中是半透明灰底。语义色由调用方给（商品/库存=主题主色，运费结算=它的珊瑚橙）。
 *
 * ⚠️ 行高跟着 [RailItem.subtitle] 自动变（52dp / 60dp）：有副标题还压 52dp 会把两行字挤在一起，
 *    而"挤"在老人用户那里等于看不清。
 * ⚠️ 有副标题的那一列，副标题**必须**能一行放下（`maxLines = 1` + 省略号）：
 *    让它折行会把行高顶开、整列的节奏全乱。
 */
@Composable
fun MasterRail(
    items: List<RailItem>,
    selectedKey: String,
    onSelect: (String) -> Unit,
    modifier: Modifier = Modifier,
    accent: Color = MaterialTheme.colorScheme.primary,
) {
    val twoLine = items.any { it.subtitle != null }
    val rowHeight = if (twoLine) 60.dp else 52.dp
    LazyColumn(
        modifier = modifier.background(MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.45f)),
    ) {
        itemsIndexed(items, key = { _, it -> it.key }) { _, item ->
            val on = item.key == selectedKey
            Box(
                Modifier
                    .fillMaxWidth()
                    .height(rowHeight)
                    .background(if (on) MaterialTheme.colorScheme.surface else Color.Transparent)
                    .clickable { onSelect(item.key) },
                contentAlignment = Alignment.CenterStart,
            ) {
                if (on) {
                    Box(Modifier.fillMaxHeight().width(4.dp).background(accent))
                }
                Column(Modifier.padding(horizontal = 12.dp)) {
                    Text(
                        item.label,
                        style = MaterialTheme.typography.bodyMedium,
                        fontWeight = if (on) FontWeight.Bold else FontWeight.Normal,
                        color = if (on) MaterialTheme.colorScheme.onSurface else MaterialTheme.colorScheme.onSurfaceVariant,
                        maxLines = 2,
                        overflow = TextOverflow.Ellipsis,
                    )
                    if (item.subtitle != null) {
                        Text(
                            item.subtitle,
                            style = MaterialTheme.typography.labelSmall,
                            color = if (on) accent else MaterialTheme.colorScheme.outline,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                        )
                    }
                }
            }
        }
    }
}

/**
 * 搜索框 —— **按人搜索只有这一份实现**（账本仪表盘 + 司机/货主/批发商/账户管理 4 个名册页）。
 *
 * 三件事必须同源，各页抄一份就一定会分叉：
 * 1. **提示文案**（默认 [UserSearch.HINT]）—— 用户得先知道能按手机号后 4 位搜才会去试；
 * 2. **放大镜图标**（看形状就知道这是搜索，不是录入）；
 * 3. **一键清空**（`✕`）—— 手机号敲错一位不该让人退格 11 次，这也是"一个一个去选"那类
 *    抱怨的同一个来源：把力气花在重复劳动上。
 *
 * ⚠️ 只负责"长什么样"，**不含**匹配规则：按人匹配走 `core/UserSearch`，服务端走 `?q=`。
 *    两者是同一条规则的两份实现（客户端的规则在 `UserSearchTest` 里钉着）。
 */
@Composable
fun SearchField(
    value: String,
    onValueChange: (String) -> Unit,
    modifier: Modifier = Modifier,
    placeholder: String = com.tapmoay.sorders.core.UserSearch.HINT,
    enabled: Boolean = true,
) {
    OutlinedTextField(
        value = value,
        onValueChange = onValueChange,
        enabled = enabled,
        placeholder = { Text(placeholder, style = MaterialTheme.typography.bodyMedium) },
        leadingIcon = { Icon(Icons.Default.Search, contentDescription = null, modifier = Modifier.size(20.dp)) },
        trailingIcon = {
            if (value.isNotEmpty()) {
                IconButton(onClick = { onValueChange("") }) {
                    Icon(Icons.Default.Close, contentDescription = "清空搜索", modifier = Modifier.size(18.dp))
                }
            }
        },
        singleLine = true,
        textStyle = MaterialTheme.typography.bodyMedium,
        shape = RoundedCornerShape(12.dp),
        modifier = modifier.fillMaxWidth(),
    )
}

/**
 * 「逐行填退货数量」那一块 —— 派单员（执行退货）与货主（申请退货）**共用这一份**。
 *
 * ### 为什么必须共用（2026-09-21 精简轮）
 * 两个角色页面里这段原来是**逐字抄的两遍**（约 31 行）：每行显示「下单 / 货损 / 已退 / 可退」、
 * 用 − / + 调数量、`+` 的上限就是 `maxReturnable(line)`。而这是**退货金额的入口** ——
 * 「能退几件」算错一件，红冲金额与补回库存就跟着错（用户点名不许出错的那几块之一）。
 * 只改一份的后果不会报错：**两个角色对同一张单会给出不同的可退数量**。
 *
 * ⚠️ 刻意**不**抽走的：引导语、两个按钮的措辞、以及下面的汇总行 ——
 *   货主那边是「申请」（提交后库存账本都不变），派单员那边是「执行」，说明与措辞本来就该不同。
 *   共用的是**逐行编辑器本身**（同一个操作、同一套上限），不是整张弹层。
 */
@Composable
fun OrderReturnLines(
    lines: List<OrderProductDto>,
    returnQty: Map<Long, Int>,
    /** 这一行最多能退几件（判据在各自的 ViewModel 里，与后端同一口径）。 */
    maxReturnable: (OrderProductDto) -> Int,
    onSetQty: (lineId: Long, qty: Int) -> Unit,
) {
    lines.forEach { line ->
        val max = maxReturnable(line)
        val qty = returnQty[line.id] ?: 0
        Row(
            verticalAlignment = Alignment.CenterVertically,
            modifier = Modifier.fillMaxWidth().padding(vertical = 2.dp),
        ) {
            Column(Modifier.weight(1f)) {
                Text(line.productNameSnapshot, style = MaterialTheme.typography.bodyMedium)
                Text(
                    buildString {
                        append("下单 ").append(line.quantity)
                        if (line.damageQuantity > 0) append(" · 货损 ").append(line.damageQuantity)
                        if (line.returnedQuantity > 0) append(" · 已退 ").append(line.returnedQuantity)
                        append(" · 可退 ").append(max)
                    },
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            IconButton(
                onClick = { onSetQty(line.id, qty - 1) },
                enabled = qty > 0,
            ) { Icon(Icons.Default.Remove, contentDescription = "减") }
            Text(qty.toString(), style = MaterialTheme.typography.titleMedium)
            IconButton(
                onClick = { onSetQty(line.id, qty + 1) },
                enabled = qty < max,
            ) { Icon(Icons.Default.Add, contentDescription = "加") }
        }
    }
}

