package com.tapmoay.sorders.ui.shipper

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.data.remote.dto.LedgerEntryDto
import com.tapmoay.sorders.ui.common.*
import com.tapmoay.sorders.ui.theme.MoneyOrange
import com.tapmoay.sorders.util.formatMoney

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ShipperLedgerScreen(
    container: AppContainer,
    onBack: () -> Unit,
    onOpenOrder: (Long) -> Unit = {},
) {
    val vm: ShipperLedgerViewModel = appViewModel { ShipperLedgerViewModel(container) }

    Column(Modifier.fillMaxSize()) {
        TopAppBar(
            title = { Text("我的账本") },
            navigationIcon = {
                IconButton(onClick = onBack) {
                    Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
                }
            },
        )

        Box(Modifier.fillMaxSize()) {
            when {
                vm.loading -> LoadingBox()
                vm.error != null -> ErrorView(vm.error.orEmpty(), onRetry = { vm.load() })
                else -> LazyColumn(
                    Modifier.fillMaxSize(),
                    contentPadding = PaddingValues(16.dp),
                    verticalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                    item {
                        ReportTimeNav(
                            mode = vm.chartMode,
                            anchor = vm.chartAnchor,
                            periodText = vm.periodText,
                            onModeChange = { vm.applyMode(it) },
                            onAnchorChange = { vm.setAnchor(it) },
                        )
                    }
                    item {
                        SectionCard {
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                Text("账单趋势", style = MaterialTheme.typography.titleMedium, modifier = Modifier.weight(1f))
                                TextButton(onClick = { vm.chartType = if (vm.chartType == "line") "bar" else "line" }) {
                                    Text(if (vm.chartType == "line") "条形图" else "折线图")
                                }
                            }
                            Spacer(Modifier.height(6.dp))
                            val cs = vm.chartSeries
                            if (cs.isEmpty()) {
                                ChartEmpty("该时段暂无账单")
                            } else {
                                val vals = cs.map { it.second.toFloat() }
                                val labels = cs.map { it.first.substring(5).replace("-", "/") }
                                if (vm.chartType == "line") LineChart(vals, labels, androidx.compose.ui.graphics.Color(MoneyOrange))
                                else BarChart(vals, labels, androidx.compose.ui.graphics.Color(MoneyOrange))
                            }
                        }
                    }
                    item {
                        SectionCard {
                            Text("当前范围内合计", style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                            Spacer(Modifier.height(2.dp))
                            Text(
                                "¥" + formatMoney(vm.total().toString()),
                                style = MaterialTheme.typography.headlineSmall,
                                fontWeight = FontWeight.Bold,
                                color = androidx.compose.ui.graphics.Color(MoneyOrange),
                            )
                        }
                    }
                    if (vm.entries.isEmpty()) {
                        item { EmptyView("该时段暂无账目", Modifier.fillMaxWidth()) }
                    } else {
                        items(vm.entries, key = { it.id }) { e ->
                            LedgerCard(e, onOpenOrder = onOpenOrder)
                        }
                    }
                    item { Spacer(Modifier.height(56.dp)) }
                }
            }
        }
    }
}

@Composable
private fun LedgerCard(e: LedgerEntryDto, onOpenOrder: (Long) -> Unit) {
    SectionCard {
        Row(
            Modifier.fillMaxWidth().clickable(enabled = e.orderId != null) { e.orderId?.let(onOpenOrder) },
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(Modifier.weight(1f)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    // 核心：名称（加粗突出 + 小图标语义色）
                    Icon(
                        if (e.source == "manual") Icons.Default.EditNote else Icons.Default.ReceiptLong,
                        contentDescription = null,
                        tint = androidx.compose.ui.graphics.Color(if (e.source == "manual") 0xFF8455E6 else 0xFF1E6FFF),
                        modifier = Modifier.size(14.dp),
                    )
                    Spacer(Modifier.width(5.dp))
                    Text(e.productName, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
                    Spacer(Modifier.width(8.dp))
                    val isManual = e.source == "manual"
                    Surface(
                        color = if (isManual) MaterialTheme.colorScheme.secondaryContainer else MaterialTheme.colorScheme.surfaceVariant,
                        shape = MaterialTheme.shapes.small,
                    ) {
                        Text(
                            if (isManual) "手动" else "订单",
                            style = MaterialTheme.typography.labelMedium,
                            modifier = Modifier.padding(horizontal = 6.dp, vertical = 1.dp),
                        )
                    }
                }
                Spacer(Modifier.height(3.dp))
                // 次要信息：一行灰字（日期·关联订单）
                Text(
                    (listOfNotNull(e.entryDate, e.orderNo?.let { "订单 #" + it }).joinToString(" · ")),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 1,
                )
                if (e.note.isNotBlank()) {
                    Text(e.note, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.outline, maxLines = 1)
                }
            }
            Spacer(Modifier.width(10.dp))
            // 金额：固定宽度右对齐 + 橙金加粗（真正的重点）
            Text(
                "¥" + formatMoney(e.total),
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.Bold,
                textAlign = TextAlign.End,
                color = androidx.compose.ui.graphics.Color(0xFFFF9500),
                modifier = Modifier.widthIn(min = 92.dp),
            )
        }
    }
}
