package com.tapmoay.sorders.ui.common

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.tapmoay.sorders.data.remote.dto.OrderDto
import com.tapmoay.sorders.ui.theme.MoneyOrange
import com.tapmoay.sorders.util.formatMoney

/**
 * 账本流水行下面**就地展开的那一单**（派单员账本与货主账本共用这一份）。
 *
 * 用户 2026-09-19：「账本相近的明细，比如他这个账本对应什么订单，
 * **订单是可以展开进行查看的**…包括货主的账本啊，都一样的」。
 *
 * ## 为什么不是"点了跳到订单详情页"
 * 跳过去再回来，**筛选条件、展开的账户、滚动位置全没了** —— 想连着核几笔账就得来回跳十几趟。
 * 就地展开之后核对是连贯的。跳转那条路**仍然留着**（右上角那个「打开订单」），
 * 因为要看照片/导航/司机备注这些还得进详情页。
 *
 * ⚠️ 两个页面共用这一份：各写一遍必然走散（一处加了状态、另一处没加），
 * 而"账本明细能看到哪一单"这件事在两个角色眼里应该是**同一件事**。
 */
@Composable
fun OrderPeek(
    loading: Boolean,
    order: OrderDto?,
    onOpenFull: () -> Unit,
) {
    Surface(
        color = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.5f),
        shape = MaterialTheme.shapes.small,
        modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp),
    ) {
        Column(Modifier.padding(10.dp)) {
            when {
                loading -> Text(
                    "加载订单…",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                order == null -> Text(
                    "订单读取失败",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.error,
                )
                else -> {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(order.orderNo, style = MaterialTheme.typography.labelLarge, fontWeight = FontWeight.Bold)
                        Spacer(Modifier.width(8.dp))
                        Text(
                            orderStatusLabel(order.status),
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                        Spacer(Modifier.weight(1f))
                        TextButton(onClick = onOpenFull, contentPadding = PaddingValues(horizontal = 6.dp)) {
                            Text("打开订单", style = MaterialTheme.typography.labelMedium)
                        }
                    }
                    val who = order.shipperName ?: order.tempShipperName
                    if (!who.isNullOrBlank()) {
                        Text(
                            "货主：" + who,
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                    if (order.deliveryDescription.isNotBlank()) {
                        Text(
                            "送达：" + order.deliveryDescription,
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            maxLines = 2,
                            overflow = TextOverflow.Ellipsis,
                        )
                    }
                    // 商品行：账本上一行是"某个商品 × 数量"，这里把整单的商品一起给出来，
                    // 才能回答"这一笔在这张单里处于什么位置"。
                    // 两列宽度按**本单最宽的那一条**量出来（与详情页同一把尺）：
                    // 数量与数量右对齐、金额与金额右对齐（用户 2026-09-22 点名的那个"没做对齐"）。
                    // ⚠️ 只能 fold、不能 map —— `rememberTextWidth` 是 @Composable（见 Adaptive.kt）。
                    val qtyStyle = MaterialTheme.typography.bodySmall
                    val moneyStyle = MaterialTheme.typography.bodySmall.copy(fontWeight = FontWeight.Bold)
                    val qtyW = order.orderProducts.fold(0.dp) { acc, lp ->
                        maxOf(acc, rememberTextWidth("×" + qtyWithUnit(lp.quantity, lp.unit), qtyStyle))
                    }
                    val moneyW = order.orderProducts.fold(0.dp) { acc, lp ->
                        maxOf(acc, rememberTextWidth("¥" + formatMoney(lp.lineTotal), moneyStyle))
                    }
                    order.orderProducts.forEach { lp ->
                        Row(
                            Modifier.fillMaxWidth().padding(top = 2.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Text(
                                lp.productNameSnapshot,
                                style = MaterialTheme.typography.bodySmall,
                                modifier = Modifier.weight(1f),
                                maxLines = 1,
                                overflow = TextOverflow.Ellipsis,
                            )
                            Spacer(Modifier.width(10.dp))
                            Text(
                                // 数量带单位（`unit_snapshot` 为空的老单只给数字，不编「件」）
                                "×" + qtyWithUnit(lp.quantity, lp.unit),
                                style = qtyStyle,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                                textAlign = TextAlign.End,
                                modifier = Modifier.width(qtyW),
                            )
                            Spacer(Modifier.width(10.dp))
                            Text(
                                "¥" + formatMoney(lp.lineTotal),
                                style = moneyStyle,
                                color = Color(MoneyOrange),
                                textAlign = TextAlign.End,
                                modifier = Modifier.width(moneyW),
                            )
                        }
                    }
                    if (order.remark.isNotBlank()) {
                        Spacer(Modifier.height(2.dp))
                        Text(
                            "备注：" + order.remark,
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.outline,
                            maxLines = 2,
                            overflow = TextOverflow.Ellipsis,
                        )
                    }
                }
            }
        }
    }
}

/** 订单状态的中文名（与后端 `enums.py::OrderStatus` 一一对应）。 */
fun orderStatusLabel(status: String): String = when (status) {
    "PENDING_DISPATCH" -> "待派单"
    "DISPATCHED" -> "派单中"
    "ACCEPTED" -> "已接单"
    "DELIVERED" -> "已送达"
    "CANCELLED" -> "已撤销"
    // 已退货（2026-09-21 补）：这一档漏了太久 —— 账本展开行会把原始码 `RETURNED`
    // 直接印给用户（与状态徽章当初漏它同一类，那边 2026-09-20 就补过并写明理由）。
    // 判据：`_tools/qa/_check_order_return.py` 拿 `OrderStatusModel.ALL` 逐档核对，
    // 少一档就红（不手写状态名，以后加状态也会被点名）。
    "RETURNED" -> "已退货"
    else -> status
}
