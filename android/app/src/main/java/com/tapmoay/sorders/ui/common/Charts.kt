package com.tapmoay.sorders.ui.common

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.*
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.nativeCanvas
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
