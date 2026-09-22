package com.tapmoay.sorders.ui.common

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Place
import androidx.compose.material.icons.filled.TripOrigin
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp

/**
 * # 「从 A 到 B」那一竖条 —— **全库唯一一处**（起点、终点、中间那条连着两个图标的线）
 *
 * 用户 2026-09-22（第三轮，指着线路卡上的那个小箭头）：
 * > 「这个**箭头**的样式**不行**啊。最好就是啊，有个**连接 2 个图标**而且**处于中间**的…」
 *
 * 上一版是两个图标中间飘着一个孤零零的 `↓`（箭头既没连上起点、也没连上终点，
 * 而且各页各画一次，间距/大小都不一样）。现在是一条**真正的连接线**：
 * 竖线处在那一列的正中、从上图标接到下图标，两个端点各自是"起点 / 终点"。
 *
 * ## ⚠️ 为什么必须是共用的
 * 同一件事在三处出现：常用线路卡（`AddressScreen::AddressCard`）、
 * 地址库抽屉的线路行（`OrderCreateScreen::SheetRow`）、订单详情的收货信息。
 * 各写一份就会出现"有的连线、有的还是箭头""图标大小差 2dp、缩进差 4dp"
 * —— 用户对订单详情页的原话就是：「那个图标**都没有连成一个线**了，都**非常的参差不齐**」。
 *
 * ## ⛔ 起点为空时**不隐藏轨道**
 * 隐藏的话，有起点的卡片两行、没起点的一行 —— 一列卡片高矮不一，就是"参差不齐"本身。
 * 所以起点为空时那个圆点画成灰色、文字写「起点未填」（这是**真的信息**：
 * 这条线路没填起点，不是坏了）。
 */
@Composable
fun RouteRail(
    origin: String?,
    dest: String,
    modifier: Modifier = Modifier,
) {
    val hasOrigin = !origin.isNullOrBlank()
    Row(modifier.fillMaxWidth().height(IntrinsicSize.Min)) {
        // 左：一竖列 = 圆点 + **连接线** + 定位针（线在正中间把它们连起来）
        Column(
            Modifier.width(18.dp).fillMaxHeight(),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Spacer(Modifier.height(4.dp))
            Icon(
                Icons.Default.TripOrigin,
                contentDescription = null,
                tint = if (hasOrigin) OriginTeal else MaterialTheme.colorScheme.outline,
                modifier = Modifier.size(13.dp),
            )
            Box(
                Modifier
                    .width(2.dp)
                    .weight(1f)
                    .padding(vertical = 2.dp)
                    .background(MaterialTheme.colorScheme.outlineVariant),
            )
            Icon(
                Icons.Default.Place,
                contentDescription = null,
                tint = DestOrange,
                modifier = Modifier.size(15.dp),
            )
            Spacer(Modifier.height(2.dp))
        }
        Spacer(Modifier.width(8.dp))
        Column(Modifier.weight(1f)) {
            Text(
                if (hasOrigin) "起点" else "起点未填",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Spacer(Modifier.height(2.dp))
            Text(
                origin.orEmpty().ifBlank { "—" },
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.SemiBold,
                color = if (hasOrigin) MaterialTheme.colorScheme.onSurface else MaterialTheme.colorScheme.outline,
                maxLines = 2,
                overflow = TextOverflow.Ellipsis,
            )
            Spacer(Modifier.height(8.dp))
            Text(
                "终点",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Spacer(Modifier.height(2.dp))
            Text(
                dest.ifBlank { "—" },
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.Bold,
                maxLines = 3,
                overflow = TextOverflow.Ellipsis,
            )
        }
    }
}

/** 起点的颜色（`InventoryTeal`「库存管理」那一族的青绿，与"起点"图标同源）。 */
private val OriginTeal = Color(0xFF00BCD4)

/** 终点的颜色（地点 = 橙，一色一功能：与「地址与联系人」模块同色）。 */
private val DestOrange = Color(0xFFF5A623)
