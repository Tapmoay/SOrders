package com.tapmoay.sorders.ui.common

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.nativeCanvas
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlin.math.max

/** 迷你折线图（自绘 Canvas：网格 + 折线 + 数据点 + 底部标签） */
@Composable
fun LineChart(
    values: List<Float>,
    labels: List<String>,
    color: Color = Color(0xFF1E6FFF),
    modifier: Modifier = Modifier,
) {
    Column(modifier) {
        Canvas(Modifier.fillMaxWidth().height(180.dp)) {
            if (values.isEmpty()) return@Canvas
            val maxV = max(values.maxOrNull() ?: 1f, 1f)
            val w = size.width
            val h = size.height
            val padL = 8f
            val padR = 8f
            val padT = 12f
            val padB = 4f
            val stepX = (w - padL - padR) / max(values.size - 1, 1)
            for (i in 0..3) {
                val y = padT + (h - padT - padB) * i / 3f
                drawLine(Color(0xFFE5E5EA), Offset(padL, y), Offset(w - padR, y), strokeWidth = 1f)
            }
            val pts = values.mapIndexed { i, v ->
                Offset(padL + stepX * i, padT + (h - padT - padB) * (1f - v / maxV))
            }
            val path = Path().apply {
                moveTo(pts[0].x, pts[0].y)
                pts.drop(1).forEach { lineTo(it.x, it.y) }
            }
            drawPath(path, color, style = Stroke(width = 3f, cap = StrokeCap.Round))
            pts.forEach { p -> drawCircle(color, radius = 4f, center = p) }
            val paint = android.graphics.Paint()
            paint.setColor(android.graphics.Color.parseColor("#8E8E93"))
            paint.textSize = 22f
            drawContext.canvas.nativeCanvas.drawText(maxV.toString(), padL, padT + 2f, paint)
            drawContext.canvas.nativeCanvas.drawText("0", padL, h - padB - 4f, paint)
        }
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
            val step = max(labels.size / 6, 1)
            labels.filterIndexed { i, _ -> i % step == 0 }.take(6).forEach {
                Text(it, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant, fontSize = 10.sp)
            }
        }
    }
}

/** 迷你条形图（自绘 Canvas） */
@Composable
fun BarChart(
    values: List<Float>,
    labels: List<String>,
    color: Color = Color(0xFF00B578),
    modifier: Modifier = Modifier,
) {
    Column(modifier) {
        Canvas(Modifier.fillMaxWidth().height(180.dp)) {
            if (values.isEmpty()) return@Canvas
            val maxV = max(values.maxOrNull() ?: 1f, 1f)
            val w = size.width
            val h = size.height
            val padT = 12f
            val padB = 4f
            val slot = w / values.size
            val barW = slot * 0.55f
            values.forEachIndexed { i, v ->
                val bh = (h - padT - padB) * (v / maxV)
                val left = slot * i + (slot - barW) / 2f
                drawRoundRect(
                    color = color.copy(alpha = 0.85f),
                    topLeft = Offset(left, padT + (h - padT - padB) - bh),
                    size = androidx.compose.ui.geometry.Size(barW, bh),
                    cornerRadius = androidx.compose.ui.geometry.CornerRadius(6f, 6f),
                )
            }
        }
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
            val step = max(labels.size / 6, 1)
            labels.filterIndexed { i, _ -> i % step == 0 }.take(6).forEach {
                Text(it, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant, fontSize = 10.sp)
            }
        }
    }
}

/** 通用空态 */
@Composable
fun ChartEmpty(message: String = "暂无数据") {
    Box(Modifier.fillMaxWidth().height(180.dp), contentAlignment = Alignment.Center) {
        Text(message, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

// ============================================================ 扇形（环形）统计图

/**
 * 扇形图的一块。
 *
 * [display] 是**已经格式化好的数**（「¥1,234.00」）：组件不管钱怎么显示（那是 `util/formatMoney`
 * 的事）。[value] 只用来算角度与占比 —— 两者分开的另一个理由：`value` 是 Float（画图用），
 * 钱的精确值在 `display` 里，格式化不会因为 Float 精度掉一分钱。
 */
data class PieSlice(val label: String, val value: Float, val display: String)

/**
 * 纯函数：每块的 (起始角, 扫角)，单位度；0° = 三点方向、正值顺时针（Compose `drawArc` 的口径）。
 *
 * · 总值 ≤ 0 → 返回**空**（调用方画空态）：全零时画一个圆出来，等于告诉用户"这里有钱"；
 * · 最后一块的扫角取**余数**（360 − 已用），这样角度和恒等于 360 —— 不补这个零头，
 *   各块的浮点误差会在环上留一条缝，切换图表时一眼能看见。
 */
fun pieAngles(values: List<Float>): List<Pair<Float, Float>> {
    val positive = values.map { if (it.isFinite() && it > 0f) it else 0f }
    val total = positive.sum()
    if (total <= 0f) return emptyList()
    val out = ArrayList<Pair<Float, Float>>(positive.size)
    var start = 0f
    positive.forEachIndexed { i, v ->
        val sweep = if (i == positive.lastIndex) 360f - start else 360f * (v / total)
        out += start to sweep
        start += sweep
    }
    return out
}

/**
 * 纯函数：占比文字。**小于 1% 的块也显示一位小数**（`0.4%`），不显示成 `0%` ——
 * 一个明明看得见的小扇形写着 0%，会被读成"数据错了"。
 */
fun percentText(value: Float, total: Float): String {
    if (total <= 0f) return "0%"
    val p = (value / total * 100f).toDouble()
    return if (p < 1.0 || p > 99.0) String.format("%.1f%%", p) else String.format("%.0f%%", p)
}

/**
 * 环形（甜甜圈）统计图 + 图例。
 *
 * 画成**环形**而不是实心饼：中间那圈正好放"一共多少"——那是看这张图第一个要问的数，
 * 实心饼的正中间反而什么都放不下。
 */
@Composable
fun PieChart(
    slices: List<PieSlice>,
    colors: List<Color>,
    centerTitle: String,
    centerValue: String,
    modifier: Modifier = Modifier,
) {
    val angles = pieAngles(slices.map { it.value })
    val total = slices.map { it.value }.sum()
    Column(modifier) {
        Box(Modifier.fillMaxWidth().height(168.dp), contentAlignment = Alignment.Center) {
            Canvas(Modifier.size(156.dp)) {
                if (angles.isEmpty()) return@Canvas
                val ring = size.minDimension * 0.24f
                val d = size.minDimension - ring
                val topLeft = Offset((size.width - d) / 2f, (size.height - d) / 2f)
                angles.forEachIndexed { i, (start, sweep) ->
                    drawArc(
                        color = colors[i % colors.size],
                        startAngle = start,
                        sweepAngle = sweep,
                        useCenter = false,
                        topLeft = topLeft,
                        size = androidx.compose.ui.geometry.Size(d, d),
                        style = Stroke(width = ring, cap = StrokeCap.Butt),
                    )
                }
            }
            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                Text(centerTitle, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                Text(
                    centerValue,
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = androidx.compose.ui.text.font.FontWeight.Bold,
                )
            }
        }
        Spacer(Modifier.height(8.dp))
        slices.forEachIndexed { i, s ->
            Row(
                Modifier.fillMaxWidth().padding(vertical = 3.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Box(Modifier.size(10.dp).clip(CircleShape).background(colors[i % colors.size]))
                Spacer(Modifier.width(8.dp))
                Text(
                    s.label,
                    style = MaterialTheme.typography.bodyMedium,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.weight(1f),
                )
                Text(
                    percentText(s.value, total),
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Spacer(Modifier.width(10.dp))
                Text(
                    s.display,
                    style = MaterialTheme.typography.bodyMedium,
                    fontWeight = androidx.compose.ui.text.font.FontWeight.Bold,
                )
            }
        }
    }
}
