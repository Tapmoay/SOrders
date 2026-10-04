package com.tapmoay.sorders.ui.dispatcher

import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.BarChart
import androidx.compose.material.icons.filled.CurrencyYuan
import androidx.compose.material.icons.filled.DirectionsCar
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
 * 版式在 [EntryCardGrid]（与「账本管理」入口页**共用一份**）——这里只负责"有哪 9 件事"。
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
        // 第 7 格只许追加在末尾：key 直接当页签号用（见 ReportFinance.exportKind 的说明）
        EntryCard("6", "经营利润", Icons.Default.CurrencyYuan, Color(0xFF00B3A4)),
        EntryCard("7", "车辆成本", Icons.Default.DirectionsCar, Color(0xFF546E7A)),
        // 第 9 格（FEAT-0013）：这一段卖出去的货里，成本有多少是有出处的（进货价）。
        EntryCard("8", "成本覆盖", Icons.Default.BarChart, Color(0xFF4CAF50)),
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
