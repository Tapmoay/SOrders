package com.tapmoay.sorders.ui.dispatcher

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import com.tapmoay.sorders.core.AppContainer
import androidx.compose.foundation.clickable
import com.tapmoay.sorders.ui.common.*
import com.tapmoay.sorders.util.formatDateTime
import com.tapmoay.sorders.util.formatMoney

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun FreightSettlementScreen(container: AppContainer, onBack: () -> Unit) {
    val vm: FreightSettlementViewModel = appViewModel { FreightSettlementViewModel(container) }

    Scaffold(
        topBar = { AppTopBar(title = "司机运费结算 · " + vm.month, onBack = onBack) },
    ) { pad ->
        Column(Modifier.fillMaxSize().padding(pad)) {
            // 月份胶囊
            Row(
                Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                listOf(-2 to "上上月", -1 to "上月", 0 to "本月").forEach { (delta, label) ->
                    val target = java.time.LocalDate.now().plusMonths(delta.toLong())
                        .format(java.time.format.DateTimeFormatter.ofPattern("yyyy-MM"))
                    val sel = vm.month == target
                    Surface(
                        color = if (sel) MaterialTheme.colorScheme.primary.copy(alpha = 0.14f) else MaterialTheme.colorScheme.surface,
                        shape = MaterialTheme.shapes.small,
                        modifier = Modifier.clickable { vm.shiftMonth(delta) },
                    ) {
                        Text(
                            label,
                            style = MaterialTheme.typography.labelLarge,
                            color = if (sel) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurfaceVariant,
                            modifier = Modifier.padding(horizontal = 14.dp, vertical = 7.dp),
                        )
                    }
                }
            }
            val groups = vm.data?.groups ?: emptyList()
            if (vm.loading && groups.isEmpty()) {
                Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { CircularProgressIndicator() }
                return@Column
            }
            if (groups.isEmpty()) {
                Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                    Text("本月暂无已送达且已计价的运费订单", style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                return@Column
            }
            val total = groups.sumOf { it.total }
            LazyColumn(
                Modifier.fillMaxSize(),
                contentPadding = PaddingValues(16.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                item {
                    SectionCard {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Text("司机运费支出合计", style = MaterialTheme.typography.titleSmall, modifier = Modifier.weight(1f))
                            Text(
                                "¥" + formatMoney(total.toString()),
                                style = MaterialTheme.typography.titleLarge,
                                fontWeight = androidx.compose.ui.text.font.FontWeight.Bold,
                                color = Color(0xFFFF9500),
                            )
                        }
                    }
                }
                items(groups, key = { it.driverId }) { g ->
                    SectionCard {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Column(Modifier.weight(1f)) {
                                Text(g.driverName.ifBlank { "司机 " + g.driverId }, style = MaterialTheme.typography.titleSmall, fontWeight = androidx.compose.ui.text.font.FontWeight.Bold)
                                Text(g.count.toString() + " 单", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                            }
                            Text(
                                "¥" + formatMoney(g.total.toString()),
                                style = MaterialTheme.typography.titleMedium,
                                fontWeight = androidx.compose.ui.text.font.FontWeight.Bold,
                                color = Color(0xFFFF9500),
                            )
                        }
                        Spacer(Modifier.height(8.dp))
                        g.orders.forEach { o ->
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                Column(Modifier.weight(1f)) {
                                    Text(o.orderNo, style = MaterialTheme.typography.bodyMedium)
                                    Text(
                                        o.deliveryDescription + " · " + o.addressDetail + (o.deliveredAt?.let { " · " + formatDateTime(it) } ?: ""),
                                        style = MaterialTheme.typography.bodySmall,
                                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                                    )
                                }
                                if (o.freightFee != null) {
                                    Text("¥" + formatMoney(o.freightFee), style = MaterialTheme.typography.titleSmall, fontWeight = androidx.compose.ui.text.font.FontWeight.Bold, color = MaterialTheme.colorScheme.onSurface)
                                } else {
                                    Text("待定价", style = MaterialTheme.typography.titleSmall, color = Color(0xFFFF6B2C))
                                }
                            }
                            Spacer(Modifier.height(6.dp))
                            HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
                        }
                    }
                }
            }
        }
    }
}
