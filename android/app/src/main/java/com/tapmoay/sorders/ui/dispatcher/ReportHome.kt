package com.tapmoay.sorders.ui.dispatcher

import androidx.compose.foundation.layout.padding
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Scaffold
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.ui.common.AppTopBar
import com.tapmoay.sorders.ui.common.EntryCardGrid
import com.tapmoay.sorders.ui.dispatcher.report.REPORT_ENTRIES

/**
 * 报表中心**老入口页**：两列彩色圆角图标 + 黑色文字，版式在 [EntryCardGrid]（与「账本管理」共用）。
 *
 * ⚠️ 2026-10-05（CHG-0034）起，报表中心的入口是 \`ReportV2Screen\`（新首页 + 下钻树 + 左侧抽屉），
 *    本页**不再是主入口**，留着是因为它是一键回退的落点：把 \`NavGraph.kt\` 里
 *    \`Routes.REPORT_HOME\` 那一处指回 \`ReportHomeScreen(...)\` 就回到改造前的样子。
 *    老 11 个页签（[ReportCenterScreen]）一直是各自独立的路由，走哪条入口都照旧能用。
 *
 * 清单本体是 \`REPORT_ENTRIES\`（**唯一一份**：左侧抽屉与这里读同一份）——
 * 以前这里手抄过一份 11 格，抄漏一格的表现是"某一页在老入口上点不到"，只有用户会发现。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ReportHomeScreen(container: AppContainer, onBack: () -> Unit, onOpen: (Int) -> Unit) {
    Scaffold(
        topBar = { AppTopBar(title = "报表中心", onBack = onBack) },
    ) { pad ->
        EntryCardGrid(
            entries = REPORT_ENTRIES,
            onOpen = { onOpen(it.key.toInt()) },
            modifier = Modifier.padding(pad),
        )
    }
}
