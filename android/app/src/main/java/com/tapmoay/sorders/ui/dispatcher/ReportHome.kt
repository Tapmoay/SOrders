package com.tapmoay.sorders.ui.dispatcher

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Inventory2
import androidx.compose.material.icons.filled.LocalShipping
import androidx.compose.material.icons.filled.Payments
import androidx.compose.material.icons.filled.ReportProblem
import androidx.compose.material.icons.filled.Storefront
import androidx.compose.material.icons.filled.SwapHoriz
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.ui.common.AppTopBar

/** 报表中心入口页：参考图样式——两列、彩色圆角方形图标（白线图形）+ 黑色文字 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ReportHomeScreen(container: AppContainer, onBack: () -> Unit, onOpen: (Int) -> Unit) {
    val items = listOf(
        ReportEntry(0, "营业纵览", Icons.Default.Payments, Color(0xFFFF9500)),
        ReportEntry(1, "商品经营", Icons.Default.Inventory2, Color(0xFF8455E6)),
        ReportEntry(2, "司机绩效", Icons.Default.LocalShipping, Color(0xFF00B578)),
        ReportEntry(3, "客户经营", Icons.Default.Storefront, Color(0xFF00A2C7)),
        ReportEntry(4, "资金收支", Icons.Default.SwapHoriz, Color(0xFF6950F5)),
        ReportEntry(5, "异常与审计", Icons.Default.ReportProblem, Color(0xFFFF4D4F)),
    )
    Scaffold(
        topBar = { AppTopBar(title = "报表中心", onBack = onBack) },
    ) { pad ->
        LazyVerticalGrid(
            columns = GridCells.Fixed(2),
            modifier = Modifier.fillMaxSize().padding(pad).padding(horizontal = 16.dp, vertical = 12.dp),
            horizontalArrangement = Arrangement.spacedBy(12.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            items(items) { e ->
                Surface(
                    shape = MaterialTheme.shapes.medium,
                    color = MaterialTheme.colorScheme.surface,
                    border = BorderStroke(1.dp, Color(0xFFECEFF5)),
                    onClick = { onOpen(e.tabIndex) },
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
}

private data class ReportEntry(val tabIndex: Int, val label: String, val icon: ImageVector, val color: Color)
