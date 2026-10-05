package com.tapmoay.sorders.ui.order

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Inventory2
import androidx.compose.material.icons.filled.Person
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.tapmoay.sorders.data.remote.dto.OrderDto
import com.tapmoay.sorders.data.remote.dto.OrderProductDto
import com.tapmoay.sorders.ui.common.FormActionRow
import com.tapmoay.sorders.ui.common.FormErrorLine
import com.tapmoay.sorders.ui.common.FormGroup
import com.tapmoay.sorders.ui.common.FormPickRow
import com.tapmoay.sorders.ui.common.FormRow
import com.tapmoay.sorders.ui.common.Hint
import com.tapmoay.sorders.ui.common.QtyStepper
import com.tapmoay.sorders.ui.common.SheetCloseButton
import com.tapmoay.sorders.ui.common.UnitTag
import com.tapmoay.sorders.ui.theme.ProductPurple
import com.tapmoay.sorders.ui.theme.ShipperTeal
import com.tapmoay.sorders.util.formatMoney

/**
 * 「转货」抽屉 —— 派单期把某一张单里的货转给**别的货主**（拆 / 并 / 整单转出）。
 *
 * 用户原话（历史记录）：「假如 A 老板下了 50 单货、B 老板下了 40 单货，然后一起由一个司机直接发车，
 * 但 B 老板非常着急，所以派单员决定将 A 的 50 单货中的 30 单货和 40 单货合并在一起变成 70 单货给 B 老板，
 * 有时候可能是全部货都直接给这个老板；也有时候会把 A 的 50 单货拆成 20 单和 30 单，另外 30 单给另一个老板 C」。
 *
 * 三种形状其实是**同一件事**：把若干行货从这一张单挪到另一位货主名下。
 * 后端命令 `commands/order.py::transfer_lines` 自己处理「并进他本来在途的那张同地址单」或
 * 「为这一位新开一张待派单的单」；界面只负责说清两件事：**转给谁**、**转哪几件、各转几件**。
 *
 * ⛔ 界面**不预告**两边各剩多少：以接口回参为准，转完重新拉一次详情（`vm.load()`）。
 * ⛔ 数量控件全 App 只有一份（`ui/common/QtyStepper.kt`），这里不另写加减器。
 * ⛔ 抽屉不传 containerColor：底色由主题一处说了算（判据 `_check_sheet_form_pages`）。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun OrderTransferSheet(
    order: OrderDto,
    targetLabel: String,
    qtyOf: (Long) -> Int,
    onQtyChange: (Long, Int) -> Unit,
    onFillAll: () -> Unit,
    onPickShipper: () -> Unit,
    busy: Boolean,
    error: String?,
    onConfirm: () -> Unit,
    onDismiss: () -> Unit,
) {
    // 源单现在是不是在某位司机手上（司机名字只有真派过单才有；命令层看的是 status ∈ 已派单/已接单）。
    val holder = order.driverName?.takeIf { it.isNotBlank() }
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    ModalBottomSheet(onDismissRequest = onDismiss, sheetState = sheetState) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .fillMaxHeight()
                .padding(horizontal = 16.dp)
                .imePadding()
                .verticalScroll(rememberScrollState()),
            verticalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    "转货",
                    style = MaterialTheme.typography.titleLarge,
                    fontWeight = FontWeight.Bold,
                    modifier = Modifier.weight(1f),
                )
                SheetCloseButton(onClick = onDismiss)
            }
            // 解释句走 Hint（判据 _check_hints：裸 Text 写解释句会红）。这一句是纯静态字面量，
            // 没有任何变量拼进来 —— 一旦带插值，整句会被降级成「数据」，那这条 Hint 就白写了。
            Hint(
                "填上的数量就是转出去的数量；留着不填的，原样不动；全填满就把原来那张作废。" +
                    "原来那趟活儿在谁手上，新开的那张单就直接派给谁（并进他手上那张单时，就在那张单上加货）。"
            )
            FormGroup(icon = Icons.Default.Person, title = "转给谁", tint = Color(ShipperTeal)) {
                FormPickRow(
                    label = "目标货主",
                    value = targetLabel,
                    onClick = onPickShipper,
                    placeholder = "点这里选一位货主",
                    icon = Icons.Default.Person,
                    iconTint = Color(ShipperTeal),
                )
                // 新单归谁跑（CHG-0043）：只**说清后果**，具体人名等后端算完由结果文案点名。
                // 这里不预告能不能跟上（司机离职 / 那一单刚被别人派走都可能变），所以只读展示。
                FormRow(label = "新单归谁跑") {
                    Text(
                        text = if (holder != null) "跟原司机 " + holder else "进待派单池",
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
            FormGroup(icon = Icons.Default.Inventory2, title = "转哪几件货", tint = Color(ProductPurple)) {
                FormActionRow(
                    label = "全部转出（整张给这一位）",
                    onClick = onFillAll,
                    icon = Icons.Default.Check,
                    iconTint = Color(ProductPurple),
                )
                order.orderProducts.forEach { line ->
                    TransferLineRow(
                        line = line,
                        qty = qtyOf(line.id),
                        onQtyChange = { q -> onQtyChange(line.id, q) },
                    )
                }
            }
            FormErrorLine(error)
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                OutlinedButton(
                    onClick = onDismiss,
                    enabled = !busy,
                    modifier = Modifier.weight(1f).height(48.dp),
                ) { Text("取消") }
                Button(
                    onClick = onConfirm,
                    enabled = !busy,
                    modifier = Modifier.weight(1f).height(48.dp),
                ) {
                    Text(if (busy) "转货中…" else "确认转货")
                }
            }
            Spacer(Modifier.height(8.dp))
        }
    }
}

/**
 * 一行货：上面是商品名，下面一行写「这一行现在有多少 · 单价」，再下面才是步进器。
 *
 * ⚠️ 商品名与「现有 N 件 · 单价」**各占一行**，不许塞回同一个 Row：那样两者会互相挤宽度、
 *    两边都截断（这一行的身份是商品名，名字被截成「洗衣液…」就认不出来了）。
 *
 * 步进器的下限是它自己的最小值（＝`至少一件`），**0 表示这一行不转**，显示成 0、减号点不动；
 * 上限由这里夹住（`QtyStepper` 没有上限参数，超了要调用方自己 `coerceIn`）。
 */
@Composable
private fun TransferLineRow(
    line: OrderProductDto,
    qty: Int,
    onQtyChange: (Int) -> Unit,
) {
    Surface(
        color = MaterialTheme.colorScheme.surfaceContainerLow,
        shape = MaterialTheme.shapes.medium,
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(
            modifier = Modifier.padding(horizontal = 14.dp, vertical = 12.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Text(
                line.productNameSnapshot.ifBlank { "未命名商品" },
                style = MaterialTheme.typography.bodyLarge,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
                modifier = Modifier.fillMaxWidth(),
            )
            Text(
                "现有 " + line.quantity + " 件 · 单价 " + formatMoney(line.unitPrice),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Row(
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                Text(
                    "转出",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                QtyStepper(
                    qty = qty,
                    onQtyChange = { onQtyChange(it.coerceIn(0, line.quantity)) },
                    modifier = Modifier.weight(1f),
                )
                UnitTag(line.unit)
            }
        }
    }
}
