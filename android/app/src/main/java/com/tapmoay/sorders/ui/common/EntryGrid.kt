package com.tapmoay.sorders.ui.common

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.shape.RoundedCornerShape
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
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/**
 * 「入口页」上的一格：彩色圆角方形图标（白线图形）+ 黑色文字。
 *
 * @param key 这一格指向哪里（路由或页签号）——本组件**不认识**路由，原样交回给调用方，
 *   所以报表中心（页签号）与账本管理（路由）能共用同一份版式。
 */
data class EntryCard(
    val key: String,
    val label: String,
    val icon: ImageVector,
    val color: Color,
)

/**
 * 入口页的**唯一一份版式**：两列、白卡 + 1dp 描边 + 40dp 圆角彩底图标。
 *
 * 为什么抽出来（2026-09-20）：用户先让报表中心用这个样式（「入口页一律用 2x2 彩色圆角图标卡」），
 * 紧接着又要求账本管理「跟报表中心是一样的形式」。照着抄一遍是最省事的，但同一个 App 里
 * 两份"入口页版式"迟早长得不一样（图标大小、圆角、行距各偏一点，用户第一眼就看得出来）——
 * 所以版式只留这一处，两页都调它。
 */
@Composable
fun EntryCardGrid(
    entries: List<EntryCard>,
    onOpen: (EntryCard) -> Unit,
    modifier: Modifier = Modifier,
) {
    LazyVerticalGrid(
        columns = GridCells.Fixed(2),
        modifier = modifier.fillMaxSize().padding(horizontal = 16.dp, vertical = 12.dp),
        horizontalArrangement = Arrangement.spacedBy(12.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        items(entries) { e ->
            Surface(
                shape = MaterialTheme.shapes.medium,
                color = MaterialTheme.colorScheme.surface,
                border = BorderStroke(1.dp, Color(0xFFECEFF5)),
                onClick = { onOpen(e) },
            ) {
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    modifier = Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 12.dp),
                ) {
                    Box(
                        Modifier.size(40.dp).background(e.color, RoundedCornerShape(10.dp)),
                        contentAlignment = Alignment.Center,
                    ) {
                        Icon(e.icon, null, Modifier.size(22.dp), tint = Color.White)
                    }
                    Spacer(Modifier.width(12.dp))
                    Text(
                        e.label,
                        style = MaterialTheme.typography.bodyLarge.copy(fontSize = 16.sp),
                        fontWeight = FontWeight.Medium,
                        color = MaterialTheme.colorScheme.onSurface,
                    )
                }
            }
        }
    }
}
