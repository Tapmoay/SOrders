package com.tapmoay.sorders.ui.dispatcher

import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Inventory2
import androidx.compose.material.icons.filled.LocalShipping
import androidx.compose.material.icons.filled.Payments
import androidx.compose.material.icons.filled.ReportProblem
import androidx.compose.material.icons.filled.Storefront
import androidx.compose.material.icons.filled.SwapHoriz
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Scaffold
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.ui.common.AppTopBar
import com.tapmoay.sorders.ui.common.EntryCard
import com.tapmoay.sorders.ui.common.EntryCardGrid

/**
 * 报表中心入口页：两列、彩色圆角方形图标（白线图形）+ 黑色文字。
 *
 * 版式在 [EntryCardGrid]（与「账本管理」入口页**共用一份**）——这里只负责"有哪 6 件事"。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ReportHomeScreen(container: AppContainer, onBack: () -> Unit, onOpen: (Int) -> Unit) {
    val items = listOf(
        EntryCard("0", "营业纵览", Icons.Default.Payments, Color(0xFFFF9500)),
        EntryCard("1", "商品经营", Icons.Default.Inventory2, Color(0xFF8455E6)),
        EntryCard("2", "司机绩效", Icons.Default.LocalShipping, Color(0xFF00B578)),
        EntryCard("3", "客户经营", Icons.Default.Storefront, Color(0xFF00A2C7)),
        EntryCard("4", "资金收支", Icons.Default.SwapHoriz, Color(0xFF6950F5)),
        EntryCard("5", "异常与审计", Icons.Default.ReportProblem, Color(0xFFFF4D4F)),
    )
    Scaffold(
        topBar = { AppTopBar(title = "报表中心", onBack = onBack) },
    ) { pad ->
        EntryCardGrid(
            entries = items,
            onOpen = { onOpen(it.key.toInt()) },
            modifier = Modifier.padding(pad),
        )
    }
}
