package com.tapmoay.sorders.ui.common
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneOffset

import androidx.compose.animation.core.animateFloatAsState
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
import androidx.compose.ui.unit.dp
import com.tapmoay.sorders.ui.theme.Success
import com.tapmoay.sorders.ui.theme.SuccessDark
import com.tapmoay.sorders.util.formatMoney

/** 订单状态徽章（三通道：图标 + 颜色 + 文字；老人/色弱均有兜底） */
@Composable
fun OrderStatusChip(status: String) {
    val icon: ImageVector
    val (label, bg, fg) = when (status) {
        "DISPATCHED" -> {
            icon = Icons.Default.Flag
            Triple("已派单", Color(0xFFFFE8C2), Color(0xFF8A5300))
        }
        "PENDING_DISPATCH" -> {
            icon = Icons.Default.Schedule
            Triple("派单中", Color(0xFFFFF1C6), Color(0xFF7A5900))
        }
        "ACCEPTED" -> {
            icon = Icons.Default.LocalShipping
            Triple("已接单", Color(0xFFD6E3FF), Color(0xFF0F4690))
        }
        "DELIVERED" -> {
            icon = Icons.Default.CheckCircle
            Triple("已送达", Color(0xFFD9F0DA), Success)
        }
        "CANCELLED" -> {
            icon = Icons.Default.Close
            Triple("已撤销", Color(0xFFF1E4E4), Color(0xFF8C4040))
        }
        else -> {
            icon = Icons.Default.Info
            Triple(status, Color(0xFFE1E2EC), Color(0xFF44464F))
        }
    }
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

/** 页面顶栏（融入背景：iOS 大标题风格，顶栏与页面同灰色底，内容优先） */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AppTopBar(
    title: String,
    subtitle: String? = null,
    onBack: (() -> Unit)? = null,
    actions: @Composable RowScope.() -> Unit = {},
) {
    TopAppBar(
        colors = TopAppBarDefaults.topAppBarColors(
            containerColor = MaterialTheme.colorScheme.background,
        ),
        title = {
            Column {
                Text(title, style = MaterialTheme.typography.titleLarge, maxLines = 1)
                if (!subtitle.isNullOrBlank()) {
                    Text(subtitle, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1)
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

/** 分组卡片容器（iOS 分组卡片：白色圆角16 + 极轻阴影，无边框，靠灰底分层） */
@Composable
fun SectionCard(modifier: Modifier = Modifier, content: @Composable ColumnScope.() -> Unit) {
    Surface(
        modifier = modifier.fillMaxWidth(),
        shape = MaterialTheme.shapes.medium,
        color = MaterialTheme.colorScheme.surface,
        tonalElevation = 0.dp,
        shadowElevation = 1.dp,
    ) {
        Column(Modifier.padding(16.dp), content = content)
    }
}

/** 角色徽章 */
@Composable
fun RoleBadge(role: String) {
    val (label, bg, fg) = when (role) {
        "shipper" -> Triple("货主", Color(0xFFD6F3FA), Color(0xFF005A78))
        "driver" -> Triple("司机", Color(0xFFD5F5E9), Color(0xFF00624A))
        "dispatcher" -> Triple("派单员", Color(0xFFDBE9FF), Color(0xFF0A4DAF))
        else -> Triple(role, Color(0xFFE1E2EC), Color(0xFF44464F))
    }
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

