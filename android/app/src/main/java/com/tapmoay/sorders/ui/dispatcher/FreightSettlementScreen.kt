package com.tapmoay.sorders.ui.dispatcher

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ExpandLess
import androidx.compose.material.icons.filled.ExpandMore
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.tapmoay.sorders.core.AppContainer
import androidx.compose.foundation.clickable
import com.tapmoay.sorders.data.remote.dto.FreightSettlementGroupDto
import com.tapmoay.sorders.data.remote.dto.FreightSettlementOrderDto
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
                    DriverSettlementCard(g)
                }
            }
        }
    }
}

/** 折叠时先露几单。为什么不是 0：一单都不露的话，卡片只剩一个数字，
 *  派单员得逐个点开才知道"这钱是怎么来的"；露两单既能看出明细长什么样，
 *  又不至于把卡片撑长（用户要的是"稍微缩短"，不是"藏起来"）。 */
private const val PREVIEW_ORDERS = 2

/**
 * 一个司机的结算卡：**默认只露 2 单，点标题展开全部**。
 *
 * ## 为什么要能折叠（用户 2026-09-19）
 * 原话：「他的那个卡片下面会显示订单，那个订单太长了，导致整个卡片太长了，
 * 我们可以把那个详情订单给稍微缩短，然后有个展开页就是可以点击展开详情」。
 * 一个司机一个月几十单是常事，全列出来这一页就没法扫了 ——
 * 而这一页真正要一眼看到的只有「谁、几单、多少钱」。
 *
 * ## "缩短"具体缩在哪
 * 每条明细原来是"单号一行 + （送达说明 + 地址 + 时间）一行"，而那行文案很长、
 * 会自己折成两三行，**地址把时间挤到看不见的地方**。现在：
 * - 时间**提到最前面**（结算时要看的是哪天送的），地址截断成一行（`maxLines = 1`）；
 * - 金额两栏仍然分开：**司机应得**（大字）与**货主运费**（小字）—— 这两个数不一样，
 *   混在一起就会出现"明细加起来 ≠ 组头那个数"（老毛病，见下面注释）。
 */
@Composable
private fun DriverSettlementCard(g: FreightSettlementGroupDto) {
    var expanded by remember { mutableStateOf(false) }
    val shown = if (expanded) g.orders else g.orders.take(PREVIEW_ORDERS)
    val hidden = g.orders.size - shown.size

    SectionCard {
        Column {
            // 标题行 = 展开/收起开关（整行可点，右上角给箭头；箭头是"这里能展开"的通用语言）
            Row(
                Modifier.fillMaxWidth().clickable { expanded = !expanded },
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Column(Modifier.weight(1f)) {
                    Text(
                        g.driverName.ifBlank { "司机 " + g.driverId },
                        style = MaterialTheme.typography.titleSmall,
                        fontWeight = FontWeight.Bold,
                    )
                    Text(
                        g.count.toString() + " 单" + if (expanded || hidden <= 0) "" else " · 展开看全部",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                Text(
                    "¥" + formatMoney(g.total.toString()),
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.Bold,
                    color = Color(0xFFFF9500),
                )
                Spacer(Modifier.width(6.dp))
                Icon(
                    if (expanded) Icons.Default.ExpandLess else Icons.Default.ExpandMore,
                    contentDescription = if (expanded) "收起明细" else "展开明细",
                    tint = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.size(22.dp),
                )
            }
            Spacer(Modifier.height(8.dp))
            HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)

            shown.forEach { o ->
                SettlementOrderRow(o)
            }

            if (hidden > 0) {
                TextButton(
                    onClick = { expanded = true },
                    modifier = Modifier.align(Alignment.CenterHorizontally),
                ) {
                    Text("还有 $hidden 单，点展开")
                }
            } else if (expanded && g.orders.size > PREVIEW_ORDERS) {
                TextButton(
                    onClick = { expanded = false },
                    modifier = Modifier.align(Alignment.CenterHorizontally),
                ) {
                    Text("收起")
                }
            }
        }
    }
}

/** 一条结算明细（**一行**：左边单号+时间+地址，右边应得+运费）。 */
@Composable
private fun SettlementOrderRow(o: FreightSettlementOrderDto) {
    Row(
        Modifier.fillMaxWidth().padding(vertical = 7.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(Modifier.weight(1f)) {
            Text(o.orderNo, style = MaterialTheme.typography.bodyMedium, maxLines = 1, overflow = TextOverflow.Ellipsis)
            // ⚠️ 时间是**结算**要看的（哪天送的），所以排在地址前面；
            //    地址长，让它占剩下的位置并截断 —— 原来顺序反过来，时间被挤没了。
            val where = listOfNotNull(
                o.deliveredAt?.let { formatDateTime(it) },
                o.addressDetail.takeIf { it.isNotBlank() },
            ).joinToString(" · ")
            Text(
                where.ifBlank { o.deliveryDescription },
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }
        Spacer(Modifier.width(8.dp))
        // 明细行显示**司机应得**（pay_total，与组头同一个来源），运费另标注：
        // 以前这里取 `freightFee`（货主运费）→ 明细加起来 ≠ 组头那个数。
        Column(horizontalAlignment = Alignment.End) {
            Text(
                "¥" + formatMoney(o.payTotal),
                style = MaterialTheme.typography.titleSmall,
                fontWeight = FontWeight.Bold,
                color = MaterialTheme.colorScheme.onSurface,
            )
            Text(
                if (o.freightFee != null) "运费 ¥" + formatMoney(o.freightFee) else "运费 待定价",
                style = MaterialTheme.typography.labelSmall,
                color = if (o.freightFee != null) MaterialTheme.colorScheme.onSurfaceVariant else Color(0xFFFF6B2C),
            )
        }
    }
}
