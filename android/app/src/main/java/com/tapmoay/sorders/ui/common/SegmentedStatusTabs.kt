package com.tapmoay.sorders.ui.common

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.Dp
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

/** 档位格子里文字左右的呼吸。**只在「放不下、要滑动」那一支用**（原因见下面 `needEqual` 那段注释）。 */
private val TAB_H_PADDING = 14.dp

/**
 * 独立块导航：每项各自独立圆角块（间距分隔，不连成一条），选中块淡色底+语义色加粗。
 *
 * **两种形态 —— 放得下时与以前逐像素相同**（2026-09-22 加，规则与出处见 `Adaptive.kt`）：
 *  - **放得下** → 等宽平铺（原样，外观零变化）；
 *  - **放不下** → **整条横向滑动**，每格按内容宽度。
 *
 * ⛔ 为什么宁可滑动也不许截断：真机实测（320dp + 系统字号 1.3）「已接单」被切成「**已接**」、
 * 「已送达」被切成「**已送**」—— 少一个字就变成**另一个意思**，用户根本看不出这两档的区别，
 * 而且界面上没有任何提示说"这里被吃掉了两个字"。状态筛选切错档 = 看到的是另一批订单。
 */
@Composable
fun SegmentedStatusTabs(
    labels: List<String>,
    colors: List<Color>,
    selected: Int,
    onSelect: (Int) -> Unit,
    modifier: Modifier = Modifier,
) {
    val labelStyle = MaterialTheme.typography.labelMedium
    // 先在组合期**无条件**把每格实测宽度算出来（`remember` 不能出现在 if 分支里）
    val widths = ArrayList<Dp>(labels.size)
    labels.forEach { widths += rememberTextWidth(it, labelStyle) }
    val gaps = ROW_ITEM_GAP * (labels.size - 1).coerceAtLeast(0)
    // 等宽平铺时**最宽的那一格**也得放得下 → 按「最宽 × 格数」判定（它恒 ≥ 各格宽度之和，所以更严）。
    // ⚠️ 量的必须是**纯文字宽**：等宽那一支的文字**不加左右内边距**（见下面 `pad` 参数）。
    //    2026-09-22 我在这里踩过一次：量的时候算上内边距、画的时候**也**加内边距，
    //    等于把每格的内容盒子挤窄 28dp → 411dp 上六个档位**全被切掉最后一个字**，
    //    而"放得下"的判定还认为自己是对的，**两边都不报错**。
    val needEqual = (widths.maxOrNull() ?: 0.dp) * labels.size + gaps

    BoxWithConstraints(
        modifier = modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp)
            .padding(top = 4.dp, bottom = 8.dp),
    ) {
        val fits = needEqual <= maxWidth
        Row(
            modifier = if (fits) Modifier.fillMaxWidth()
            else Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),
            horizontalArrangement = Arrangement.spacedBy(ROW_ITEM_GAP),
        ) {
            labels.forEachIndexed { i, label ->
                TabPill(
                    label = label,
                    accent = colors.getOrElse(i) { Color(0xFF1E6FFF) },
                    selected = selected == i,
                    onClick = { onSelect(i) },
                    // 放得下：等宽分掉整行（原样：文字居中、**不加内边距**）；
                    // 放不下：按内容宽度、由外层滑动，这时才需要左右呼吸。
                    modifier = if (fits) Modifier.weight(1f) else Modifier,
                    pad = if (fits) 0.dp else TAB_H_PADDING,
                )
            }
        }
    }
}

@Composable
private fun TabPill(
    label: String,
    accent: Color,
    selected: Boolean,
    onClick: () -> Unit,
    modifier: Modifier,
    pad: Dp,
) {
    Surface(
        onClick = onClick,
        shape = RoundedCornerShape(12.dp),
        color = if (selected) accent.copy(alpha = 0.14f) else MaterialTheme.colorScheme.surface,
        border = BorderStroke(1.dp, if (selected) accent.copy(alpha = 0.6f) else MaterialTheme.colorScheme.outlineVariant),
        modifier = modifier.height(40.dp),
    ) {
        Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
            Text(
                label,
                style = MaterialTheme.typography.labelMedium,
                fontWeight = if (selected) FontWeight.Bold else FontWeight.Medium,
                color = if (selected) accent else MaterialTheme.colorScheme.onSurfaceVariant,
                maxLines = 1,
                // 放不下时整条会滑动（宽度已按实测保证够），所以这里**不需要**任何截断兜底
                softWrap = false,
                modifier = Modifier.padding(horizontal = pad),
            )
        }
    }
}
