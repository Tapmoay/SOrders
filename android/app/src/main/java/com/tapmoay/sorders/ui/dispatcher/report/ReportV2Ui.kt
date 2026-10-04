package com.tapmoay.sorders.ui.dispatcher.report

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.IntrinsicSize
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ChevronRight
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp

/**
 * 报表中心 v2 的**共用零件**（CHG-0034）。
 *
 * 为什么不直接复用 `ui/common` 那几个：这里是"一张卡里有很多行、每行自己是个按钮、
 * 右边挂一个大数"的版式，与列表页的 InfoRow 不是一回事。但**卡片容器与空态仍走 ui/common**
 * （SectionCard / LoadingBox / EmptyView / ErrorView），这里只补"行"和"标题"。
 *
 * ⛔ 这里不许出现任何 JSON、任何字段名原文（用户 2026-10-05：「不能出现 JSON 那种数据样式，
 *    那个是完全不能出现的」）。
 */

/** 卡片里的小标题：左边一条竖色条 + 标题（用户要的"重心"就在这条竖条上）。 */
@Composable
internal fun SectionTitle(text: String, color: Color = MaterialTheme.colorScheme.primary) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        Box(Modifier.width(3.dp).height(14.dp).background(color, RoundedCornerShape(2.dp)))
        Spacer(Modifier.width(8.dp))
        Text(text, style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold)
    }
}

/** 小胶囊（一行说明的"标签"）：底色淡、字色就是语义色。 */
@Composable
internal fun Chip(text: String, color: Color) {
    // 宽度 = 文字实测（`IntrinsicSize.Max`）：它**不抢**兄弟的宽度，也⛔ 不截断
    // （截断的风险见 `_check_adaptive_layout.py`：少一个字就是另一个意思）
    Surface(
        shape = CircleShape,
        color = color.copy(alpha = 0.12f),
        modifier = Modifier.width(IntrinsicSize.Max),
    ) {
        Text(
            text,
            style = MaterialTheme.typography.labelSmall,
            color = color,
            modifier = Modifier.padding(horizontal = 8.dp, vertical = 3.dp),
        )
    }
}

/** 一行胶囊。 */
@Composable
internal fun ChipRow(chips: List<Pair<String, Color>>) {
    if (chips.isEmpty()) return
    Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
        chips.take(3).forEach { Chip(it.first, it.second) }
    }
}

/**
 * 通用的一行：左图标（可空）+ 标题 + 小字，右边一个大数（可空）+ 箭头（可空）。
 *
 * [onClick] 非空才画箭头：在点不动的东西上画一个"点我"的记号，
 * 就是把用户引到一个点了没反应的地方（本仓库最贵的一类毛病）。
 */
@Composable
internal fun LineRow(
    icon: ImageVector?,
    iconColor: Color,
    title: String,
    sub: String?,
    value: String?,
    valueColor: Color,
    onClick: (() -> Unit)? = null,
    chevron: Boolean = false,
    valueStyle: androidx.compose.ui.text.TextStyle = MaterialTheme.typography.titleMedium,
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .let { if (onClick != null) it.clickable { onClick() } else it }
            .padding(vertical = 9.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        if (icon != null) {
            Box(
                Modifier.size(30.dp).background(iconColor.copy(alpha = 0.14f), RoundedCornerShape(9.dp)),
                contentAlignment = Alignment.Center,
            ) { Icon(icon, null, Modifier.size(17.dp), tint = iconColor) }
            Spacer(Modifier.width(10.dp))
        }
        Column(Modifier.weight(1f)) {
            Text(
                title,
                style = MaterialTheme.typography.bodyLarge,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
                modifier = Modifier.fillMaxWidth(),
            )
            if (!sub.isNullOrBlank()) {
                Text(
                    sub,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                )
            }
        }
        if (value != null) {
            Spacer(Modifier.width(8.dp))
            Text(
                value,
                style = valueStyle,
                fontWeight = FontWeight.SemiBold,
                color = valueColor,
                maxLines = 1,
                textAlign = TextAlign.End,
            )
        }
        if (chevron || onClick != null) {
            Icon(
                Icons.Default.ChevronRight,
                contentDescription = null,
                modifier = Modifier.size(18.dp),
                tint = MaterialTheme.colorScheme.outline,
            )
        }
    }
}

/** 一条细分隔线（不引 Divider：Material3 各版本名字不一样，自己画更稳）。 */
@Composable
internal fun HairLine() {
    Box(
        Modifier
            .fillMaxWidth()
            .height(1.dp)
            .background(MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.5f)),
    )
}

/** 迷你条：小字标签 + 一根条 + 右边的数（首页五张表卡里就用它）。 */
@Composable
internal fun MiniLine(label: String, fraction: Float, value: String, color: Color = MaterialTheme.colorScheme.primary) {
    Row(
        Modifier.fillMaxWidth().padding(vertical = 2.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            label,
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.width(68.dp),
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
        Box(
            Modifier.weight(1f).height(6.dp),
        ) {
            Box(
                Modifier
                    .fillMaxHeight()
                    .fillMaxWidth(fraction)
                    .background(color.copy(alpha = 0.55f), RoundedCornerShape(3.dp)),
            )
        }
        Spacer(Modifier.width(8.dp))
        Text(
            value,
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurface,
            modifier = Modifier.width(76.dp),
            maxLines = 1,
            textAlign = TextAlign.End,
        )
    }
}

/** 小字说明（口径、公式、接口没有的东西 —— 一律**如实**写出来）。 */
@Composable
internal fun NoteText(text: String) {
    Text(
        text,
        style = MaterialTheme.typography.bodySmall,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        modifier = Modifier.fillMaxWidth().padding(top = 6.dp),
    )
}

/** 五张表那张卡里的**一行表格**：图标在上、标题、白话、大数、迷你行、胶囊。 */
@Composable
internal fun TableTile(
    icon: ImageVector,
    color: Color,
    title: String,
    word: String,
    amount: String,
    amountColor: Color,
    lines: List<Triple<String, Float, String>>,
    chips: List<Pair<String, Color>>,
    onClick: () -> Unit,
) {
    Column(
        Modifier
            .fillMaxWidth()
            .clickable { onClick() }
            .padding(vertical = 12.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            // 图标在**文字上方**（用户 2026-10-05：「图标放文字上方（不是左侧）」）
            Box(
                Modifier.size(30.dp).background(color.copy(alpha = 0.14f), RoundedCornerShape(9.dp)),
                contentAlignment = Alignment.Center,
            ) { Icon(icon, null, Modifier.size(17.dp), tint = color) }
            Spacer(Modifier.width(10.dp))
            Text(title, style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold, maxLines = 1)
            Spacer(Modifier.weight(1f))
            Text(
                amount,
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.Bold,
                color = amountColor,
                maxLines = 1,
            )
            Icon(
                Icons.Default.ChevronRight,
                contentDescription = null,
                modifier = Modifier.size(18.dp),
                tint = MaterialTheme.colorScheme.outline,
            )
        }
        Spacer(Modifier.height(2.dp))
        Text(word, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        if (lines.isNotEmpty()) {
            Spacer(Modifier.height(6.dp))
            lines.forEach { MiniLine(it.first, it.second, it.third, color) }
        }
        if (chips.isNotEmpty()) {
            Spacer(Modifier.height(8.dp))
            ChipRow(chips)
        }
    }
}
