package com.tapmoay.sorders.ui.driver

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyListScope
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
import com.tapmoay.sorders.data.remote.dto.DriverBillDto
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
 *
 * 2026-10-15（CHG-0127，用户 m43131）：这一页**从"只有运费"变成两半页** —— 上面仍是运费
 * （时间档位 / 趋势 / 合计 / 明细），下面多一段**工资**（统计 + 按月明细 + 变更记录），给
 * **固定工资的司机**看（以前他们这一格是没有的）。两半页各自取各自的数：运费跟右上角药丸走
 * （`freightSettlementRange`），工资只按月（`driver-bills`，**不受药丸影响**）。哪一半都没数据
 * 时那一段不占地方。
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
                    // 两半页各自判各自的，空的那一段不占地方（2026-10-15，CHG-0127）。
                    // ⚠️ 「他是不是拿工资的」只能用 /me 的 has_salary 判：`driver.salary` 这个字段
                    //    对非派单员是 None（后端 services/driver_pay.monthly_salary_of 才是真判据）。
                    val showFreight = vm.rows.isNotEmpty() || !vm.hasSalary || vm.hasPiece
                    val showSalary = vm.hasSalary || vm.salaryRows.isNotEmpty()
                    if (showFreight) freightItems(vm, onOpenOrder)
                    if (showSalary) salaryItems(vm)
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

/**
 * 运费那半页（原样搬进来，2026-10-15 CHG-0127 只是**挪位**，取数与文案一个字没动）：
 * 趋势图 + 合计 + 明细，跟着顶栏右上角的时间药丸走。
 */
private fun LazyListScope.freightItems(vm: DriverFreightViewModel, onOpenOrder: (Long) -> Unit) {
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
                            color = if (e.freightFee != null) MaterialTheme.colorScheme.onSurfaceVariant else androidx.compose.ui.graphics.Color(0xFFCE5C2C),
                            modifier = Modifier.widthIn(min = 92.dp),
                        )
                    }
                }
            }
        }
    }
}

/**
 * 工资那半页（2026-10-15，CHG-0127）：**统计 + 按月明细 + 变更记录**。
 *
 * 用户口径（m43131）：固定工资司机也要有「我的账本」，这本账统计的是**他的工资**；任职期间
 * 固定工资变过要有记录；已核销的标「已核销」，没核销的按现在的固定工资重算。
 *
 * ⚠️ 这一段与右上角那个**时间药丸无关**：工资表本身就是月度的（`driver-bills` 按 `month`）。
 *    药丸只管上面那半页 —— 卡片上写「按月」就是为了省掉"为什么有上个月的工资"这一问。
 */
private fun LazyListScope.salaryItems(vm: DriverFreightViewModel) {
    vm.salaryError?.let { msg ->
        item {
            SectionCard {
                Text(
                    "工资单没拉下来：" + msg,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.error,
                )
            }
        }
    }
    if (vm.salaryRows.isEmpty()) {
        item {
            SectionCard {
                Text("工资", style = MaterialTheme.typography.titleMedium)
                Spacer(Modifier.height(4.dp))
                Text(
                    "还没有工资单 —— 派单员生成之后，这里会按月列出来。",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
        return
    }
    item { SalarySummaryCard(vm) }
    items(vm.salaryRows, key = { "salary-" + it.id }) { b -> SalaryBillCard(b) }
    if (vm.salaryChanges.isNotEmpty()) {
        item { SalaryChangeCard(vm.salaryChanges) }
    }
}

/** 工资统计：**已核销 / 未核销**两个数分开写（怎么分的见 `DriverSalary.kt`）。 */
@Composable
private fun SalarySummaryCard(vm: DriverFreightViewModel) {
    val t = vm.salaryTotals
    SectionCard {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("工资", style = MaterialTheme.typography.titleMedium, modifier = Modifier.weight(1f))
            Text(
                "按月",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        Spacer(Modifier.height(6.dp))
        Text(
            "已核销（" + t.settledCount + " 个月）",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Text(
            "¥" + formatMoney(t.settled.toString()),
            style = MaterialTheme.typography.headlineSmall,
            fontWeight = FontWeight.Bold,
            color = androidx.compose.ui.graphics.Color(com.tapmoay.sorders.ui.theme.MgrGreen),
        )
        Spacer(Modifier.height(6.dp))
        Text(
            "未核销（" + t.openCount + " 个月）",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Text(
            "¥" + formatMoney(t.open.toString()),
            style = MaterialTheme.typography.headlineSmall,
            fontWeight = FontWeight.Bold,
            color = androidx.compose.ui.graphics.Color(MoneyOrange),
        )
        Spacer(Modifier.height(6.dp))
        Text(
            "未核销的按现在的固定工资重算（派单员改过工资的话）；已核销的不再变 —— 那是拍过板的凭据。",
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

/** 一个月的工资单：月份 + 金额 + **核销状态**（用户：「表示已核销」）。 */
@Composable
private fun SalaryBillCard(b: DriverBillDto) {
    val settled = isSettledBill(b)
    SectionCard {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text(salaryMonthWord(b.month), style = MaterialTheme.typography.titleSmall)
                Spacer(Modifier.height(2.dp))
                Text(
                    b.note.ifBlank { b.ruleName }.ifBlank { "固定工资" },
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            Column(horizontalAlignment = Alignment.End) {
                Text(
                    "¥" + formatMoney(b.amount),
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.Bold,
                    color = androidx.compose.ui.graphics.Color(MoneyOrange),
                )
                Text(
                    if (settled) "已核销" else "未核销",
                    style = MaterialTheme.typography.labelSmall,
                    color = if (settled) {
                        androidx.compose.ui.graphics.Color(com.tapmoay.sorders.ui.theme.MgrGreen)
                    } else {
                        androidx.compose.ui.graphics.Color(0xFFCE5C2C)
                    },
                )
            }
        }
    }
}

/**
 * 任职期间的**工资变更记录**（用户：「如果在任职期间如果他的固定工资发生了改变，我们也同样
 * 也是有记录的」）。
 *
 * ⚠️ 数据来源是工资单快照（工资单按当月的固定工资生成，改规则**不改**历史账单 —— 见
 *    `models/driver_billing_rule.py` 那句「改规则参数不改历史账单」）。所以它如实回答的是
 *    哪个月的工资单换了数；中间月份没生成工资单时，准确那天以派单员改规则为准 —— 脚注写明。
 */
@Composable
private fun SalaryChangeCard(changes: List<SalaryChange>) {
    SectionCard {
        Text("工资变更记录", style = MaterialTheme.typography.titleMedium)
        Spacer(Modifier.height(6.dp))
        changes.forEach { c ->
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    salaryMonthWord(c.month) + "起",
                    style = MaterialTheme.typography.bodyMedium,
                    modifier = Modifier.weight(1f),
                )
                Text(
                    "¥" + formatMoney(c.from.toString()) + " → ¥" + formatMoney(c.to.toString()),
                    style = MaterialTheme.typography.bodyMedium,
                    fontWeight = FontWeight.Medium,
                    color = androidx.compose.ui.graphics.Color(MoneyOrange),
                )
            }
            if (c.ruleName.isNotBlank()) {
                Text(
                    c.ruleName,
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            Spacer(Modifier.height(4.dp))
        }
        Text(
            "相邻两张工资单不一样就算一次变更；中间月份没生成工资单时，以派单员改规则那次为准。",
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}
