package com.tapmoay.sorders.ui.order

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Checkbox
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.tapmoay.sorders.core.InputRules
import com.tapmoay.sorders.data.remote.dto.OrderDto
import com.tapmoay.sorders.ui.common.CardAlertDialog
import com.tapmoay.sorders.ui.common.FormInputRow
import com.tapmoay.sorders.ui.common.Hint
import com.tapmoay.sorders.ui.theme.MoneyOrange
import com.tapmoay.sorders.util.formatDateTime
import com.tapmoay.sorders.util.formatMoney

/**
 * 派单员打折的弹层（台账 L-34 / CHG-0071）。
 *
 * ## 这一层只做两件事
 * ① 把两种表达（减百分比 / 抹零）与两种范围（整单 / 只打勾选的几件）摆出来；
 * ② 把服务端算好的结果**原样**念给用户听（已经减了多少、谁减的、为什么）。
 *
 * ⛔ **一个乘法都不做**：打完要付多少、每行摊到多少，全部由服务端算
 *    （算法唯一一份在 `backend/app/services/order_discount.py`）。客户端算一遍再显示，
 *    迟早与账上的数差几毛 —— 而账单上差一毛就是两本账。
 * ⛔ 不预演"打完省多少"：抹零会被"最后一行没那么多钱"改小，预演出来的数与服务端不一样。
 *
 * 故意做成**无状态**（值都在 `OrderDetailViewModel` 里）：弹层被系统回收再打开时，
 * 用户填了一半的字还在 —— 与核销那扇门（`SettleConfirmDialog`）同一套写法。
 */
@Composable
fun OrderDiscountDialog(
    order: OrderDto,
    kind: String,
    value: String,
    reason: String,
    wholeOrder: Boolean,
    pickedLines: Set<Long>,
    busy: Boolean,
    errorText: String?,
    onKindChange: (String) -> Unit,
    onValueChange: (String) -> Unit,
    onReasonChange: (String) -> Unit,
    onWholeOrderChange: (Boolean) -> Unit,
    onToggleLine: (Long) -> Unit,
    onDismiss: () -> Unit,
    onConfirm: () -> Unit,
    onClear: () -> Unit,
) {
    val saved = discountHeadline(order)
    CardAlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(if (saved == null) "打折" else "改折扣") },
        confirmButton = {
            TextButton(onClick = onConfirm, enabled = !busy) {
                Text(if (busy) "处理中…" else if (saved == null) "打折" else "保存折扣")
            }
        },
        dismissButton = { TextButton(onClick = onDismiss, enabled = !busy) { Text("取消") } },
        text = {
            Column(
                Modifier.verticalScroll(rememberScrollState()),
                verticalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                // 已经打过折：先把"现在是什么样"念一遍（谁打的、为什么、什么时候）
                if (saved != null) {
                    Text(saved, fontWeight = FontWeight.SemiBold, color = Color(MoneyOrange))
                    discountTrace(order)?.let {
                        Text(it, style = MaterialTheme.typography.bodySmall)
                    }
                    order.discountAt?.takeIf { it.isNotBlank() }?.let {
                        Text(formatDateTime(it), style = MaterialTheme.typography.bodySmall)
                    }
                }

                // ① 哪种表达：减百分比 / 抹零（用户 m01347 要两种都有）
                Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    listOf(DISCOUNT_KIND_PERCENT, DISCOUNT_KIND_AMOUNT).forEach { k ->
                        FilterChip(
                            selected = kind == k,
                            onClick = { onKindChange(k) },
                            label = { Text(discountKindLabel(k), maxLines = 1) },
                        )
                    }
                }

                // ② 值：百分比就是"减 10%"；抹零就是"减 20 元"。
                //    输入过滤用 `priceInput`（数字 + 一个小数点，最多四位）—— 与后端
                //    `discount_value Numeric(14,4)` 同一档精度；业务规则（抹零比整单还多、
                //    百分比 ≥100）由 `discountValueError` 与服务端各判一次。
                FormInputRow(
                    label = if (kind == DISCOUNT_KIND_AMOUNT) "抹零（元）" else "减多少（%）",
                    value = value,
                    onValueChange = { onValueChange(InputRules.priceInput(it)) },
                    placeholder = if (kind == DISCOUNT_KIND_AMOUNT) "20" else "10",
                    keyboardType = KeyboardType.Decimal,
                    iconTint = Color(MoneyOrange),
                )
                if (errorText != null) {
                    Text(
                        errorText,
                        color = MaterialTheme.colorScheme.error,
                        style = MaterialTheme.typography.bodySmall,
                    )
                }

                // ③ 范围：整单 / 只打勾选的几件（用户 m01347 要两档粒度都有）
                Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    FilterChip(
                        selected = wholeOrder,
                        onClick = { onWholeOrderChange(true) },
                        label = { Text("整单", maxLines = 1) },
                    )
                    FilterChip(
                        selected = !wholeOrder,
                        onClick = { onWholeOrderChange(false) },
                        label = { Text("只打几件", maxLines = 1) },
                    )
                }
                if (!wholeOrder) {
                    order.orderProducts.forEach { line ->
                        val on = line.id in pickedLines
                        Row(
                            Modifier
                                .fillMaxWidth()
                                .clickable { onToggleLine(line.id) }
                                .padding(vertical = 2.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Checkbox(checked = on, onCheckedChange = { onToggleLine(line.id) })
                            Text(
                                line.productNameSnapshot + " ×" + line.quantity,
                                Modifier.weight(1f),
                                maxLines = 1,
                                overflow = TextOverflow.Ellipsis,
                                style = MaterialTheme.typography.bodyMedium,
                            )
                            Text("¥" + formatMoney(line.lineTotal))
                        }
                    }
                }

                // ④ 理由（选填）：写进操作日志与订单详情那一行（用户 m13365）
                FormInputRow(
                    label = "理由",
                    value = reason,
                    onValueChange = onReasonChange,
                    placeholder = "选填，比如：老客户",
                )

                // ⚠️ 这句是**警告**（"不能勾"）不是解释句 —— `_check_hints.py` 第 2 组钉着
                //    「一次 Hint 调用里一段解释句都没有」= 0：挂开关就等于"关掉提示顺手把这条规则也关了"。
                Text("商品档案上勾了「不参与打折」的：整单打折时自动跳过，只打几件时不能勾。")
                if (saved != null) {
                    Hint("取消折扣会把每一行还原成打折前的金额 —— 不是按现在的价重算。")
                    TextButton(onClick = onClear, enabled = !busy) {
                        Text("取消折扣", color = MaterialTheme.colorScheme.error)
                    }
                }
            }
        },
    )
}
