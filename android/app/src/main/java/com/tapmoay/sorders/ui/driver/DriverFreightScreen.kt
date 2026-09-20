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
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.ui.common.*
import com.tapmoay.sorders.ui.theme.MoneyOrange
import com.tapmoay.sorders.util.formatMoney

/**
 * 司机「我的账本」：**时间档位（顶栏右上角药丸）+ 趋势图 + 合计 + 明细**。
 *
 * 2026-09-20 用户点名换时间控件：「时间也按那个（药丸）进行，预设**默认是今天**的，
 * 如果今天没有单则也按老规则**一直推到有单为止**」。
 * 原来那行是按日/周/月翻页的 `ReportTimeNav` —— 那个组件**报表中心还在用**
 * （`ui/dispatcher/ReportCenter.kt`），所以只换这一页的用法，没动它本身。
 *
 * ⚠️ 明细行**本来就点得进详情**（`clickable { onOpenOrder(e.orderId) }`），这一点没改。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DriverFreightScreen(
    container: AppContainer,
    onBack: () -> Unit,
    onOpenOrder: (Long) -> Unit = {},
) {
    val vm: DriverFreightViewModel = appViewModel { DriverFreightViewModel(container) }
    var showDatePresets by remember { mutableStateOf(false) }

    Column(Modifier.fillMaxSize()) {
        TopAppBar(
            title = { Text("我的账本") },
            navigationIcon = {
                IconButton(onClick = onBack) {
                    Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
                }
            },
            actions = {
                // 右：时间药丸（点开是全部预设 + 自定义）—— 与司机任务页/货主账同一个控件
                DatePresetPill(label = vm.periodWord, onClick = { showDatePresets = true })
            },
        )

        Box(Modifier.fillMaxSize()) {
            when {
                // ⚠️ 「先盘点、再取数」那一帧：窗口定下来之前整页 loading
                //    （2026-09-21 用户：「它会闪两下再跳到前天……闪两下已经不行了」）。
                !vm.windowSettled -> LoadingBox()
                vm.loading -> LoadingBox()
                vm.error != null -> ErrorView(vm.error.orEmpty(), onRetry = { vm.load() })
                else -> LazyColumn(
                    Modifier.fillMaxSize(),
                    contentPadding = PaddingValues(16.dp),
                    verticalArrangement = Arrangement.spacedBy(10.dp),
                ) {
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
                                ChartEmpty("「" + vm.periodWord + "」暂无运费")
                            } else {
                                val vals = cs.map { it.second.toFloat() }
                                // 标签由 VM 按窗口粒度生成好（单日 `18时` / 跨日 `09/15`）：
                                // 页面里再切一次字符串，按小时分桶时就会切错位。
                                val labels = cs.map { it.first }
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
                        item {
                            // 空态文案必须**指到右上角那个药丸**：默认档位是今天，
                            // 今天没跑单时这一页本来就该是空的，不指路就会被当成"坏了"。
                            EmptyView(
                                "「" + vm.periodWord + "」没有运费 —— 点右上角可以换一段时间",
                                Modifier.fillMaxWidth().padding(top = 32.dp),
                            )
                        }
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
                                        // 主信息 = **从哪到哪**（用户 2026-09-20：「主要是从哪到哪里，
                                        // 然后那个运费是多少」）：订单里有起点就「起点 → 终点」，没有就只显示终点。
                                        // ⚠️ 后端目前不出起点（`origin` 恒为 null）→ 现在一律只走 else 分支；
                                        //    哪天补上了，这里自动变成两段，App 不用改。
                                        Text(
                                            if (e.origin.isNullOrBlank()) {
                                                e.address.ifBlank { e.desc.ifBlank { "（无地址）" } }
                                            } else {
                                                e.origin + " → " + e.address
                                            },
                                            style = MaterialTheme.typography.bodyLarge,
                                            fontWeight = FontWeight.Medium,
                                            maxLines = 2,
                                            overflow = TextOverflow.Ellipsis,
                                        )
                                        Spacer(Modifier.height(4.dp))
                                        Text(
                                            listOfNotNull(e.deliveredAt, e.desc.ifBlank { null }).joinToString(" · "),
                                            style = MaterialTheme.typography.bodySmall,
                                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                                            maxLines = 2,
                                        )
                                        Spacer(Modifier.height(2.dp))
                                        // 订单号退居次要（用户：「订单号都不是非常重要」—— 点进详情就能看到/复制）
                                        Text(
                                            e.orderNo,
                                            style = MaterialTheme.typography.labelSmall,
                                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                                            maxLines = 1,
                                            overflow = TextOverflow.Ellipsis,
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
                                        // 「司机应得」是怎么来的：**计件 + 提成**拆开写
                                        // （用户 2026-09-20：「每个订单会显示他每个单抽成多少」；
                                        //  说法与派单员结算页 `FreightSettlementScreen` 同一套）。
                                        // ⚠️ 两项都不是正数时整行不画 —— 空着比写「计件 ¥0.00 + 提成 ¥0.00」清楚。
                                        val parts = buildList {
                                            if ((e.payPiece.toBigDecimalOrNull()?.signum() ?: 0) > 0) {
                                                add("计件 ¥" + formatMoney(e.payPiece))
                                            }
                                            if ((e.payCommission.toBigDecimalOrNull()?.signum() ?: 0) > 0) {
                                                add("提成 ¥" + formatMoney(e.payCommission))
                                            }
                                        }
                                        if (parts.isNotEmpty()) {
                                            Text(
                                                parts.joinToString(" + "),
                                                style = MaterialTheme.typography.labelSmall,
                                                textAlign = TextAlign.End,
                                                color = androidx.compose.ui.graphics.Color(MoneyOrange),
                                                modifier = Modifier.widthIn(min = 92.dp),
                                            )
                                        }
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

    // 档位清单 + 自定义区间：两个弹层的状态机在 `DateFilterDialogs` 里（五个页面共用一份）
    DateFilterDialogs(
        showPresets = showDatePresets,
        onDismissPresets = { showDatePresets = false },
        preset = vm.preset,
        customFrom = vm.customFrom,
        customTo = vm.customTo,
        onPickPreset = { vm.applyPreset(it) },
        onApplyCustom = { f, t -> vm.applyCustomRange(f, t) },
    )
}
