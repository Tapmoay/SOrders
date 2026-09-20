package com.tapmoay.sorders.ui.common

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp

/**
 * 订单状态导航色：全部/派单中/已接单/已送达/已撤销/已退货。
 *
 * ⚠️ 新档位**只能往后面加**：这一份是派单端与货主端**共用**的，按位置取色 ——
 *    插在中间会把后面每一档的颜色都顶掉（而两端的档位个数不同，
 *    顶掉之后没有人会收到任何报错，只会看到"已送达"变成灰色）。
 * ⚠️ 已退货的棕橙与「派单中」的黄、「已撤销」的灰两两 RGB 距离都 > 60（肉眼分得开）。
 */
val ORDER_TAB_COLORS = listOf(
    Color(0xFF1E6FFF),  // 全部 · 蓝
    Color(0xFFFFB300),  // 派单中 · 黄
    Color(0xFF00A2C7),  // 已接单 · 湖蓝
    Color(0xFF00B578),  // 已送达 · 绿
    Color(0xFF8A8A8E),  // 已撤销 · 灰
    Color(0xFFBF5B00),  // 已退货 · 棕橙
)

/** 独立块导航：每项各自独立圆角块（间距分隔，不连成一条），选中块淡色底+语义色加粗 */
@Composable
fun SegmentedStatusTabs(
    labels: List<String>,
    colors: List<Color>,
    selected: Int,
    onSelect: (Int) -> Unit,
    modifier: Modifier = Modifier,
) {
    Row(
        modifier = modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp)
            .padding(top = 4.dp, bottom = 8.dp),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        labels.forEachIndexed { i, label ->
            val sel = selected == i
            val c = colors.getOrElse(i) { Color(0xFF1E6FFF) }
            Surface(
                onClick = { onSelect(i) },
                shape = RoundedCornerShape(12.dp),
                color = if (sel) c.copy(alpha = 0.14f) else MaterialTheme.colorScheme.surface,
                border = BorderStroke(1.dp, if (sel) c.copy(alpha = 0.6f) else MaterialTheme.colorScheme.outlineVariant),
                modifier = Modifier.weight(1f).height(40.dp),
            ) {
                Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                    Text(
                        label,
                        style = MaterialTheme.typography.labelMedium,
                        fontWeight = if (sel) FontWeight.Bold else FontWeight.Medium,
                        color = if (sel) c else MaterialTheme.colorScheme.onSurfaceVariant,
                        maxLines = 1,
                    )
                }
            }
        }
    }
}
