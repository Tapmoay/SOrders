package com.tapmoay.sorders.ui.dispatcher

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Payments
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Checkbox
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.unit.dp
import com.tapmoay.sorders.ui.common.OrderStatusChip
import com.tapmoay.sorders.ui.common.SectionCard
import com.tapmoay.sorders.ui.common.TruncationNote
import com.tapmoay.sorders.ui.theme.DangerRed
import com.tapmoay.sorders.ui.theme.MgrGreen
import com.tapmoay.sorders.ui.theme.MoneyOrange
import com.tapmoay.sorders.util.formatDateTime
import com.tapmoay.sorders.util.formatMoney
import com.tapmoay.sorders.ui.common.Hint

/**
 * 账本**选中某个人之后的第二层**：他在这段时期里**按订单的账**（2026-09-20 用户要求）。
 *
 * 用户原话：「第一层就是货主选择，第 2 层是时间上的统计（昨天/今天/前天/这周/这个月、自定义）
 * ……然后就会出现对应的账本，这个月账本是**按那个订单来算的、按订单来结算的**。
 * 然后它还**有一个统计**：它**哪些货物**下来、哪些货物**欠了多少钱**、哪些货物**对应哪些价**、
 * 然后它欠多少钱。包括我们核销账也是在这里核销，**点击订单点击核销**，可以**全部核销**，
 * 也可以**按商品进行核销**」。
 *
 * 第三轮又补了批量核销的口径：「如果是今天，那就是今天的**所有订单**；如果是这周，
 * 那就这周的所有订单。这样就可以**直接点这个合计将它核销掉**，相当于一个**可控的批量处理**」。
 *
 * ## 这一层的四块（顺序就是用户说的顺序）
 * ① 这是谁 + 这一段的单数；② 三个数（应收 / 已收 / 欠款）+ **核销全部**；
 * ③ 「这些货」的统计（数量 / 均价 / 金额 / 其中未收）；④ 逐单列表，每单一个「核销」。
 *
 * ## ⚠️ 口径：这里的钱是"**这些单现在**欠多少"，不是"这一段发生额"
 * 时间档位筛的是**送达日在窗口内**的订单（`delivered_from/delivered_to`，与账本流水的
 * `entry_date` 同一个口径），而每张单的应收/已收/欠款是**它自己的累计数**
 * （`order_money` 一处算的）。所以：
 * · 「上个月送的货、这个月还欠着」→ 选上个月能看到它欠多少，这才是催收要问的问题；
 * · 反过来说，**这一段的账目发生额**要看「订单账」那一档（那是流水口径）。
 * 两个数都对，只是回答的问题不同 —— 所以页面上的口径词必须写出来（设计规范 §4.9）。
 *
 * ## 司机那一层不一样（同一支函数，两种内容）
 * 司机的钱是「我们该给他多少」（`driver_pay`），与客户应收是两套口径，**没有核销**；
 * 而且他那些单**已经在账户列表响应里**（`/freight-settlement` 的 group 自带 `orders`），
 * 不再请求一次。硬把"按订单核销"套到司机身上，会让人以为司机也能被"核销"。
 */
fun LazyListScope.ledgerPersonItems(
    vm: DispatcherLedgerViewModel,
    onOpenOrder: (Long) -> Unit,
) {
    if (vm.personTruncated) {
        item {
            TruncationNote(
                vm.personLimit,
                "上面的应收/已收/欠款与下面的商品统计只含已取到的这些单；" +
                    "要完整的账请点右上角的日期档位把范围缩小一点",
            )
        }
    }

    // 司机：他跑的单（不再请求；口径是"该给他多少"，所以这里没有核销）
    if (vm.tab == 1) {
        item { DriverPersonOrders(vm, onOpenOrder) }
        return
    }

    // ③ 「哪些货物、什么价、欠多少」
    if (vm.personStats.isNotEmpty()) {
        item {
            SectionCard {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Icon(
                        Icons.Default.Payments,
                        contentDescription = null,
                        tint = Color(MoneyOrange),
                        modifier = Modifier.size(18.dp),
                    )
                    Spacer(Modifier.width(6.dp))
                    Text(
                        "这些货（" + vm.periodWord + "）",
                        style = MaterialTheme.typography.titleSmall,
                        fontWeight = FontWeight.Bold,
                    )
                }
                Spacer(Modifier.height(8.dp))
                Row(Modifier.fillMaxWidth()) {
                    Text("货物", style = MaterialTheme.typography.labelMedium, modifier = Modifier.weight(1.4f))
                    Text("数量", style = MaterialTheme.typography.labelMedium, modifier = Modifier.weight(0.7f))
                    Text("均价", style = MaterialTheme.typography.labelMedium, modifier = Modifier.weight(0.8f))
                    Text("金额", style = MaterialTheme.typography.labelMedium, modifier = Modifier.weight(0.9f))
                    Text("未收", style = MaterialTheme.typography.labelMedium, modifier = Modifier.weight(0.9f))
                }
                Spacer(Modifier.height(4.dp))
                HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
                vm.personStats.forEach { s ->
                    Row(
                        Modifier.fillMaxWidth().padding(vertical = 6.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Text(
                            s.name,
                            style = MaterialTheme.typography.bodyMedium,
                            modifier = Modifier.weight(1.4f),
                        )
                        Text(
                            s.quantity.toString() + (s.unit.ifBlank { "" }),
                            style = MaterialTheme.typography.bodySmall,
                            modifier = Modifier.weight(0.7f),
                        )
                        Text(
                            "¥" + formatMoney(s.unitPrice.toPlainString()),
                            style = MaterialTheme.typography.bodySmall,
                            modifier = Modifier.weight(0.8f),
                        )
                        Text(
                            "¥" + formatMoney(s.amount.toPlainString()),
                            style = MaterialTheme.typography.bodySmall,
                            modifier = Modifier.weight(0.9f),
                        )
                        Text(
                            if (s.owed.signum() == 0) "—" else "¥" + formatMoney(s.owed.toPlainString()),
                            style = MaterialTheme.typography.bodySmall,
                            color = if (s.owed.signum() == 0) MaterialTheme.colorScheme.onSurfaceVariant else Color(DangerRed),
                            modifier = Modifier.weight(0.9f),
                        )
                    }
                }
                Spacer(Modifier.height(6.dp))
                Text(
                    "「未收」= 还欠着的那部分按每张单的欠款比例摊到这几样货上，" +
                        "所以它加起来正好等于上面的欠款（不按比例摊会在报表上多出没人认领的钱）。",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
    }

    // ④ 逐单：点「核销」就地核销（整单 / 按商品）
    if (vm.personOrders.isNotEmpty()) {
        item {
            Text(
                "订单（" + vm.personOrders.size + " 单）",
                style = MaterialTheme.typography.titleSmall,
                modifier = Modifier.padding(start = 4.dp, top = 4.dp),
            )
        }
        items(vm.personOrders, key = { "o" + it.id }) { o ->
            PersonOrderCard(
                order = o,
                canSettle = vm.canSettle(o),
                onSettle = { vm.openSettle(o) },
                onOpen = { onOpenOrder(o.id) },
            )
        }
    }
}

/**
 * 第二层顶部那张卡：**这是谁** + 这一段他的钱 + （货主/批发商）批量核销的入口。
 *
 * 「核销全部」为什么放在这张卡的**合计**下面：用户 2026-09-20 说的就是"直接点这个合计
 * 将它核销掉"。所以按钮跟三个数在同一张卡里、金额就写在按钮上 —— 用户点之前看得见要收多少。
 * ⛔ 司机没有这个按钮（他的钱不是应收，见文件头那段）。
 */
@Composable
internal fun PersonHeaderCard(vm: DispatcherLedgerViewModel) {
    val isDriver = vm.tab == 1
    val (receivable, settled, arrears) = vm.personKpi()
    val targets = vm.settleAllTargets()
    val (driverTotal, driverCount) = vm.driverPersonTotal()
    SectionCard {
        Row(verticalAlignment = Alignment.CenterVertically) {
            IconButton(onClick = { vm.closePerson() }) {
                Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回全部")
            }
            Column(Modifier.weight(1f)) {
                Text(
                    vm.personTitle(),
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.Bold,
                )
                Text(
                    when {
                        vm.personLoading -> "正在拉他这一段的账…"
                        isDriver -> "这一段跑了 " + driverCount + " 单（" + vm.periodWord + "）"
                        else -> "按送达日期筛出 " + vm.personOrders.size + " 单（" + vm.periodWord + "）"
                    },
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
        Spacer(Modifier.height(10.dp))
        if (vm.personLoading) return@SectionCard
        if (isDriver) {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                MiniKpi("应得运费", "¥" + formatMoney(driverTotal.toString()), Color(MgrGreen), Modifier.weight(1f))
                MiniKpi("单数", driverCount.toString() + " 单", Color(MoneyOrange), Modifier.weight(1f))
            }
            Spacer(Modifier.height(6.dp))
            Hint(
                "司机那笔钱的口径是「按规则该给他多少」，与客户应收不是一回事，" +
                    "所以这里没有核销；要结他的账请到工作台的「司机运费结算」。",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        } else {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                MiniKpi("应收", "¥" + formatMoney(receivable.toString()), Color(MoneyOrange), Modifier.weight(1f))
                MiniKpi("已收", "¥" + formatMoney(settled.toString()), Color(MgrGreen), Modifier.weight(1f))
                MiniKpi("欠款", "¥" + formatMoney(arrears.toString()), Color(DangerRed), Modifier.weight(1f))
            }
            Spacer(Modifier.height(10.dp))
            Button(
                onClick = { vm.openSettleAll() },
                enabled = targets.isNotEmpty() && !vm.settleSubmitting,
                modifier = Modifier.fillMaxWidth(),
            ) {
                Icon(Icons.Default.Payments, contentDescription = null, modifier = Modifier.size(16.dp))
                Spacer(Modifier.width(4.dp))
                Text(
                    if (targets.isEmpty()) "这一段没有还没结清的单"
                    else "核销全部（" + targets.size + " 单 · ¥" + formatMoney(vm.settleAllAmount()) + "）"
                )
            }
            Spacer(Modifier.height(4.dp))
            Text(
                if (vm.personOrders.isEmpty()) {
                    "这一段没有送达的单。" + vm.personTimeHint()
                } else {
                    "「核销全部」= 把这一段里还没结清的 " + targets.size + " 单合成一笔收款、一次收清；" +
                        "只想收其中一张，点下面那一单的「核销」。"
                },
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

/**
 * 三个数里的一格（钱单独一行、大号加粗 —— 与账本页别处的 KPI 同一个形态）。
 *
 * ⚠️ [value] 收的是**已经格式化好的字符串**：这一格既要显示钱（`¥1,234.00`）也要显示单数
 *    （`12 单`），让调用方自己拼，比在这里按 label 猜"这一格是不是钱"稳得多。
 */
@Composable
private fun MiniKpi(label: String, value: String, color: Color, modifier: Modifier = Modifier) {
    Column(modifier) {
        Text(label, style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Spacer(Modifier.height(2.dp))
        Text(
            value,
            style = MaterialTheme.typography.titleMedium,
            fontWeight = FontWeight.Bold,
            color = color,
        )
    }
}

/** 逐单一行：单号 + 状态 + 送达时间 + 这单的钱 + 「核销」。 */
@Composable
private fun PersonOrderCard(
    order: com.tapmoay.sorders.data.remote.dto.OrderDto,
    canSettle: Boolean,
    onSettle: () -> Unit,
    onOpen: () -> Unit,
) {
    // ⚠️ 金额一律用后端算好的三个数（`arrears_amount` 等），**不许**在这里 `总价 − 已收`：
    //    退货红冲与退现都不在"已收"里，减出来的欠款偏大 —— 用户会照着它多要钱。
    val receivable = centsToMoney(orderReceivableCents(order))
    val arrears = order.arrearsAmount.ifBlank { "0.00" }
    val returned = order.returnedAmount.toDoubleOrNull() ?: 0.0
    SectionCard {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text(order.orderNo, style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Bold)
                Spacer(Modifier.height(4.dp))
                Row(verticalAlignment = Alignment.CenterVertically) {
                    // 状态徽章走**全项目唯一那一份**（`OrderStatusChip`）——它同时给"已退货"这一档
                    // 中文名与配色；在这里自己写一个 when，就会出现"账本页显示 RETURNED"这种原始码
                    com.tapmoay.sorders.ui.common.OrderStatusChip(order.status)
                    // ⚠️ 时间戳必须换算到当地（`formatDateTime`）：直接 `take(16)` = UTC，真机早 8 小时
                    formatDateTime(order.deliveredAt).ifBlank { null }?.let {
                        Spacer(Modifier.width(8.dp))
                        Text(
                            it,
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
            }
            if (order.paid) {
                Icon(Icons.Default.CheckCircle, contentDescription = null, tint = Color(MgrGreen), modifier = Modifier.size(18.dp))
                Spacer(Modifier.width(4.dp))
                Text("已结清", style = MaterialTheme.typography.labelMedium, color = Color(MgrGreen))
            }
        }
        Spacer(Modifier.height(6.dp))
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            Text("应收 ¥" + formatMoney(receivable), style = MaterialTheme.typography.bodySmall)
            Text(
                "欠 ¥" + formatMoney(arrears),
                style = MaterialTheme.typography.bodySmall,
                color = if ((arrears.toDoubleOrNull() ?: 0.0) > 0) Color(DangerRed) else MaterialTheme.colorScheme.onSurfaceVariant,
            )
            if (returned > 0) {
                Text(
                    "已退 ¥" + formatMoney(order.returnedAmount),
                    style = MaterialTheme.typography.bodySmall,
                    color = Color(MoneyOrange),
                )
            }
        }
        if (order.orderProducts.isNotEmpty()) {
            Spacer(Modifier.height(4.dp))
            Text(
                order.orderProducts.joinToString("、") {
                    it.productNameSnapshot + "×" + (it.quantity - it.returnedQuantity).coerceAtLeast(0) +
                        if (it.returnedQuantity > 0) "（已退 ${it.returnedQuantity}）" else ""
                },
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        Spacer(Modifier.height(8.dp))
        Row(verticalAlignment = Alignment.CenterVertically) {
            TextButton(onClick = onOpen) { Text("看订单") }
            Spacer(Modifier.weight(1f))
            Button(onClick = onSettle, enabled = canSettle) {
                Icon(Icons.Default.Payments, contentDescription = null, modifier = Modifier.size(16.dp))
                Spacer(Modifier.width(4.dp))
                Text(if (canSettle) "核销" else "无可收")
            }
        }
    }
}

/**
 * 核销弹层：**全部核销 / 按商品核销**（用户：「可以全部核销，也可以按商品进行核销」）。
 *
 * ⛔ 金额**不可手输**：后端要求 `amount` 精确等于所选行的应收合计，让用户手打一个数
 * 只会出现"输入框里看着对、提交被拒"（这正是客户收款页当初踩过的坑，
 * `AccountToolsScreens` 里那段关于定点数的注释记着 20 万次随机试验的失配率）。
 * 所以这里把金额**算出来只读显示**，用户能做的是"勾哪些行"。
 */
@Composable
fun SettleOrderDialog(vm: DispatcherLedgerViewModel, onDismiss: () -> Unit) {
    val order = vm.settleTarget ?: return
    AlertDialog(
        onDismissRequest = { if (!vm.settleSubmitting) onDismiss() },
        title = { Text("核销 " + order.orderNo) },
        text = {
            Column {
                Text(
                    "这一单现在欠 ¥" + formatMoney(order.arrearsAmount.ifBlank { "0.00" }) +
                        "（应收 ¥" + formatMoney(centsToMoney(orderReceivableCents(order))) + "）",
                    style = MaterialTheme.typography.bodyMedium,
                )
                Spacer(Modifier.height(4.dp))
                Text(
                    "不勾任何商品 = 整单核销；只想收其中几样就勾上它们（按商品核销）。",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Spacer(Modifier.height(10.dp))
                // 「全部核销」是一个**动作**（把每一行勾上），不是另一条提交路径 ——
                // 两条路径迟早会分叉（一条按行校验、一条不按），而钱只该有一条路。
                Row(verticalAlignment = Alignment.CenterVertically) {
                    TextButton(onClick = { vm.pickAllSettleLines() }) { Text("全部勾上") }
                    TextButton(onClick = { vm.clearSettleLines() }) { Text("清空（=整单）") }
                }
                Spacer(Modifier.height(4.dp))
                order.orderProducts.forEach { line ->
                    val netQty = (line.quantity - line.returnedQuantity).coerceAtLeast(0)
                    val paid = line.id in vm.settlePicked
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        modifier = Modifier.fillMaxWidth().clickable { vm.toggleSettleLine(line.id) },
                    ) {
                        Checkbox(checked = paid, onCheckedChange = { vm.toggleSettleLine(line.id) })
                        Column(Modifier.weight(1f)) {
                            Text(
                                line.productNameSnapshot,
                                style = MaterialTheme.typography.bodyMedium,
                                textDecoration = if (netQty <= 0) TextDecoration.LineThrough else null,
                            )
                            Text(
                                buildString {
                                    append(netQty).append(line.unit.ifBlank { "件" })
                                    append(" × ¥").append(formatMoney(line.unitPrice ?: "0"))
                                    if (line.returnedQuantity > 0) append("（已退 ").append(line.returnedQuantity).append("）")
                                },
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        }
                        Text(
                            "¥" + formatMoney(centsToMoney(lineReceivableCents(line))),
                            style = MaterialTheme.typography.bodyMedium,
                        )
                    }
                }
                Spacer(Modifier.height(10.dp))
                SettleMethodChips(vm)
                Spacer(Modifier.height(8.dp))
                SettleAmountRow("本次核销", vm.settleAmount())
                NoCustomerWarning(vm)
            }
        },
        confirmButton = {
            TextButton(onClick = { vm.submitSettle() }, enabled = !vm.settleSubmitting) {
                Text(if (vm.settleSubmitting) "处理中…" else "确认核销")
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss, enabled = !vm.settleSubmitting) { Text("取消") }
        },
    )
}

/**
 * 批量核销弹层：**点合计 → 把这一段里这个人还没结清的单一次收清**（用户 2026-09-20 要求）。
 *
 * 三条写在这里，免得下一轮有人把它做成"全屏一键收钱"：
 * ① 只有**进到某个人**才给（[DispatcherLedgerViewModel.openSettleAll] 里那道门）：
 *    收款单绑的是一个客户的档案，在"全部人"那一层批量收就是把钱记到某个人头上；
 * ② 金额**算出来只读显示**（与单张核销同一条理由：后端要求逐单对得上，手输必然对不上）；
 * ③ 逐单列出来（最多列 [LIST_MAX] 张，其余的用一句"另 N 单"带过）—— 用户说的是"可控"，
 *    看不见收了哪几张就不叫可控。
 */
@Composable
fun SettleAllDialog(vm: DispatcherLedgerViewModel, onDismiss: () -> Unit) {
    val targets = vm.settleAllTargets()
    AlertDialog(
        onDismissRequest = { if (!vm.settleSubmitting) onDismiss() },
        title = { Text("核销全部（" + targets.size + " 单）") },
        text = {
            Column {
                Text(
                    vm.personShortName() + " 在「" + vm.periodWord + "」里还没结清的 " + targets.size +
                        " 单，合成一笔收款一次收清。",
                    style = MaterialTheme.typography.bodyMedium,
                )
                Spacer(Modifier.height(8.dp))
                targets.take(LIST_MAX).forEach { o ->
                    Row(Modifier.fillMaxWidth().padding(vertical = 2.dp)) {
                        Text(o.orderNo, style = MaterialTheme.typography.bodySmall, modifier = Modifier.weight(1f))
                        Text(
                            "¥" + formatMoney(o.arrearsAmount.ifBlank { "0.00" }),
                            style = MaterialTheme.typography.bodySmall,
                        )
                    }
                }
                if (targets.size > LIST_MAX) {
                    Text(
                        "……另 " + (targets.size - LIST_MAX) + " 单（合计仍按全部 " + targets.size + " 单收）",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                Spacer(Modifier.height(10.dp))
                SettleMethodChips(vm)
                Spacer(Modifier.height(8.dp))
                SettleAmountRow("本次核销", vm.settleAllAmount())
                NoCustomerWarning(vm)
            }
        },
        confirmButton = {
            TextButton(onClick = { vm.submitSettleAll() }, enabled = !vm.settleSubmitting && targets.isNotEmpty()) {
                Text(if (vm.settleSubmitting) "处理中…" else "确认核销")
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss, enabled = !vm.settleSubmitting) { Text("取消") }
        },
    )
}

/** 批量核销弹层里逐单最多列几张（再长就是把整页账本塞进一个弹窗）。 */
private const val LIST_MAX = 6

/**
 * 收款方式那几个胶囊 —— **两种核销弹层共用这一份**。
 *
 * 各写一份的后果很具体：单张核销加了"挂账结清"、批量核销没加，用户按批量收的时候
 * 就选不到这个方式，只能当"现金"收进去（报表上那笔钱的性质直接变了）。
 */
@Composable
private fun SettleMethodChips(vm: DispatcherLedgerViewModel) {
    Text("收款方式", style = MaterialTheme.typography.titleSmall)
    FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
        listOf(
            "cash" to "现金",
            "transfer" to "转账",
            "wechat" to "微信",
            "arrears_settle" to "挂账结清",
        ).forEach { (v, l) ->
            FilterChip(
                selected = vm.settleMethod == v,
                onClick = { vm.settleMethod = v },
                label = { Text(l, maxLines = 1) },
            )
        }
    }
}

/** 「本次核销 ¥X」那一行（只读 —— 金额由界面算，见 [SettleOrderDialog] 顶部那段）。 */
@Composable
private fun SettleAmountRow(label: String, amount: String) {
    Surface(
        color = MaterialTheme.colorScheme.surfaceVariant,
        shape = MaterialTheme.shapes.small,
    ) {
        Row(
            Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 10.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(label, style = MaterialTheme.typography.bodyMedium)
            Spacer(Modifier.weight(1f))
            Text(
                "¥" + formatMoney(amount),
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.Bold,
                color = Color(MoneyOrange),
            )
        }
    }
}

/**
 * 「这位货主还没有客户档案」那条警告 —— 两种核销弹层共用。
 *
 * 它是**拦得住一次错账**的那一条：没有客户档案时后端会拒（收款单必须绑客户），
 * 与其让用户点了确认才看到一句报错，不如在弹层里先说明白。
 */
@Composable
private fun NoCustomerWarning(vm: DispatcherLedgerViewModel) {
    if (vm.personCustomerId != null) return
    Spacer(Modifier.height(8.dp))
    Row(verticalAlignment = Alignment.CenterVertically) {
        Icon(Icons.Default.Warning, contentDescription = null, tint = Color(DangerRed), modifier = Modifier.size(16.dp))
        Spacer(Modifier.width(6.dp))
        Text(
            "这位货主还没有客户档案，核销记不到谁头上 —— 请先到「货主管理」把账号关联成客户。",
            style = MaterialTheme.typography.bodySmall,
            color = Color(DangerRed),
        )
    }
}
