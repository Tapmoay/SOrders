package com.tapmoay.sorders.ui.driver

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.LocalShipping
import androidx.compose.material3.Icon
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.ui.common.*
import com.tapmoay.sorders.ui.theme.MoneyOrange
import com.tapmoay.sorders.util.formatMoney

/** 司机「我的账本」：沿用货主/派单员账本模板（时间导航 + 趋势图 + 合计 + 明细）。 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DriverFreightScreen(
    container: AppContainer,
    onBack: () -> Unit,
    onOpenOrder: (Long) -> Unit = {},
) {
    val vm: DriverFreightViewModel = appViewModel { DriverFreightViewModel(container) }

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
                                Text("运费趋势", style = MaterialTheme.typography.titleMedium, modifier = Modifier.weight(1f))
                                TextButton(onClick = { vm.chartType = if (vm.chartType == "line") "bar" else "line" }) {
                                    Text(if (vm.chartType == "line") "条形图" else "折线图")
                                }
                            }
                            Spacer(Modifier.height(6.dp))
                            val cs = vm.chartSeries
                            if (cs.isEmpty()) {
                                ChartEmpty("该时段暂无运费")
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
                    if (vm.rows.isEmpty()) {
                        item { EmptyView("该时段暂无运费", Modifier.fillMaxWidth()) }
                    } else {
                        items(vm.rows, key = { it.orderId }) { e ->
                            SectionCard {
                                Row(
                                    Modifier.fillMaxWidth().clickable { onOpenOrder(e.orderId) },
                                    verticalAlignment = Alignment.CenterVertically,
                                ) {
                                    Icon(
                                        Icons.Default.LocalShipping,
                                        contentDescription = null,
                                        tint = com.tapmoay.sorders.ui.theme.MgrGreen.let { androidx.compose.ui.graphics.Color(it) },
                                        modifier = Modifier.size(15.dp),
                                    )
                                    Spacer(Modifier.width(8.dp))
                                    Column(Modifier.weight(1f)) {
                                        Row(verticalAlignment = Alignment.CenterVertically) {
                                            Text(e.orderNo, style = MaterialTheme.typography.titleSmall)
                                            Spacer(Modifier.width(8.dp))
                                            Surface(
                                                color = MaterialTheme.colorScheme.surfaceVariant,
                                                shape = MaterialTheme.shapes.small,
                                            ) {
                                                Text(
                                                    "运费",
                                                    style = MaterialTheme.typography.labelMedium,
                                                    modifier = Modifier.padding(horizontal = 6.dp, vertical = 1.dp),
                                                )
                                            }
                                        }
                                        Spacer(Modifier.height(4.dp))
                                        Text(
                                            listOfNotNull(e.deliveredAt, e.desc.ifBlank { null }, e.address.ifBlank { null }).joinToString(" · "),
                                            style = MaterialTheme.typography.bodySmall,
                                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                                            maxLines = 2,
                                        )
                                    }
                                    Column(horizontalAlignment = Alignment.End) {
                                        Text(
                                            "¥" + formatMoney(e.payTotal),
                                            style = MaterialTheme.typography.titleMedium,
                                            fontWeight = FontWeight.Bold,
                                            textAlign = TextAlign.End,
                                            color = androidx.compose.ui.graphics.Color(MoneyOrange),
                                            modifier = Modifier.widthIn(min = 92.dp),
                                        )
                                        Text(
                                            if (e.freightFee != null) "运费 ¥" + formatMoney(e.freightFee) else "运费 待定价",
                                            style = MaterialTheme.typography.labelSmall,
                                            textAlign = TextAlign.End,
                                            color = if (e.freightFee != null) MaterialTheme.colorScheme.onSurfaceVariant else androidx.compose.ui.graphics.Color(0xFFFF6B2C),
                                            modifier = Modifier.widthIn(min = 92.dp),
                                        )
                                    }
                                }
                            }
                        }
                    }
                    item { Spacer(Modifier.height(24.dp)) }
                }
            }
        }
    }
}
