package com.tapmoay.sorders.ui.dispatcher

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Storefront
import androidx.compose.material3.Button
import androidx.compose.material3.Checkbox
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import com.tapmoay.sorders.core.InputRules
import com.tapmoay.sorders.data.remote.dto.ProductDto
import com.tapmoay.sorders.data.remote.dto.UserDto
import com.tapmoay.sorders.ui.common.SoTextField
import com.tapmoay.sorders.ui.common.productNameColor
import com.tapmoay.sorders.ui.common.productPriceFact

/**
 * 批量调价底部抽屉（两个场景共用同一组件）：
 * - members 为空 + lockedShipperId 非空 = 锁定单个批发商（定价页内：仅对该批发商的部分商品批量调价）
 * - members 非空 = 按商品维度（批发商管理页：同一商品可同时修改多个批发商专属价）
 */
@OptIn(ExperimentalMaterial3Api::class, ExperimentalLayoutApi::class)
@Composable
fun BatchPriceSheet(
    products: List<ProductDto>,
    members: List<UserDto>,
    lockedShipperId: Long?,
    lockedShipperName: String = "",
    acting: Boolean,
    onExecute: (shipperIds: List<Long>, productIds: List<Long>, mode: String, value: String?) -> Unit,
    onDismiss: () -> Unit,
) {
    val locked = lockedShipperId != null
    var selShippers by remember { mutableStateOf(if (locked) setOf(lockedShipperId!!) else members.map { it.id }.toSet()) }
    var selProducts by remember { mutableStateOf(products.map { it.id }.toSet()) }
    var mode by remember { mutableStateOf("fixed") }
    var fixedValue by remember { mutableStateOf("") }
    var percentValue by remember { mutableStateOf("") }

    ModalBottomSheet(
        onDismissRequest = onDismiss,
        sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true),
    ) {
        Column(
            Modifier
                .fillMaxWidth()
                .verticalScroll(rememberScrollState())
                .padding(horizontal = 20.dp)
                .padding(bottom = 32.dp),
            verticalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("批量调价", style = MaterialTheme.typography.titleLarge, modifier = Modifier.weight(1f))
                IconButton(onClick = onDismiss) {
                    Icon(Icons.Default.Close, contentDescription = "关闭")
                }
            }
            val shipperLabel = lockedShipperName.ifBlank { "当前批发商" }
            Text(
                if (locked) "仅调整当前批发商（" + shipperLabel + "）的所选商品价格；已有特价将被覆盖"
                else "按商品批量调价：同一商品可同时修改多个批发商专属价；已有特价将被覆盖",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Spacer(Modifier.height(2.dp))

            // ---------- 批发商：锁定（单批发商）或 多选 ----------
            if (locked) {
                Text("批发商", style = MaterialTheme.typography.titleSmall)
                Surface(
                    shape = MaterialTheme.shapes.small,
                    color = Color(0xFFF5A623).copy(alpha = 0.12f),
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        modifier = Modifier.padding(horizontal = 12.dp, vertical = 10.dp),
                    ) {
                        Icon(
                            Icons.Default.Storefront,
                            contentDescription = null,
                            tint = Color(0xFFB07700),
                            modifier = Modifier.size(18.dp),
                        )
                        Spacer(Modifier.width(8.dp))
                        Text(
                            shipperLabel,
                            style = MaterialTheme.typography.bodyMedium,
                            fontWeight = FontWeight.SemiBold,
                            color = Color(0xFFB07700),
                        )
                    }
                }
            } else {
                Text("批发商（可多选，同一商品一起改）", style = MaterialTheme.typography.titleSmall)
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        "多个批发商一份价格一次写入",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.weight(1f),
                    )
                    TextButton(onClick = { selShippers = members.map { it.id }.toSet() }) { Text("全选") }
                }
                if (members.isEmpty()) {
                    Text("暂无批发商（可在货主管理中升级）", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                } else {
                    members.forEach { m ->
                        Row(
                            verticalAlignment = Alignment.CenterVertically,
                            modifier = Modifier.fillMaxWidth().clickable {
                                selShippers = if (m.id in selShippers) selShippers - m.id else selShippers + m.id
                            },
                        ) {
                            Checkbox(checked = m.id in selShippers, onCheckedChange = {
                                selShippers = if (m.id in selShippers) selShippers - m.id else selShippers + m.id
                            })
                            Text(m.fullName ?: m.phone ?: m.username, style = MaterialTheme.typography.bodyMedium, maxLines = 1)
                        }
                    }
                }
            }
            Spacer(Modifier.height(4.dp))

            // ---------- 商品 多选 ----------
            Text("商品（可多选）", style = MaterialTheme.typography.titleSmall)
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    if (locked) "该批发商要批量调整的商品" else "多个商品批同一价",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.weight(1f),
                )
                TextButton(onClick = { selProducts = products.map { it.id }.toSet() }) { Text("全选") }
            }
            if (products.isEmpty()) {
                Text("暂无商品（可在商品管理中新增）", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            } else {
                products.forEach { p ->
                    // 名称色判据只有一处（`productNameColor`，见 ui/common/ProductCardKit.kt）
                    val pc = productNameColor(p.nameColor)
                    // 售价文案与格式化也只有一处（`productPriceFact`）：原来这里是自己拼的
                    // `"¥" + formatMoney(…)` —— 而且那版**不带单位**，与商品卡上的
                    // 「¥25.00/袋」对不上（同一件商品在这张表里少了一截，看着像被截断）。
                    val pf = productPriceFact(p.defaultUnitPrice, p.unit)
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        modifier = Modifier.fillMaxWidth().clickable {
                            selProducts = if (p.id in selProducts) selProducts - p.id else selProducts + p.id
                        },
                    ) {
                        Checkbox(checked = p.id in selProducts, onCheckedChange = {
                            selProducts = if (p.id in selProducts) selProducts - p.id else selProducts + p.id
                        })
                        Text(p.name, style = MaterialTheme.typography.bodyMedium, color = pc, maxLines = 1, modifier = Modifier.weight(1f))
                        Text(pf.value, style = MaterialTheme.typography.bodySmall, color = pf.color)
                    }
                }
            }
            Spacer(Modifier.height(4.dp))

            // ---------- 定价方式 ----------
            // ⚠️ 原来的「引用批发价档」（mode=tier）已于 2026-09-19 删除：
            //    它读的是**商品上的批发价档位**，而那套东西看起来像批发价、下单时谁都不照它走
            //    （用户拍板整个概念删掉）。批量调价现在只剩"直接给一个价"和"按默认价百分比"两种，
            //    两种都是**真的会生效**的口径。
            Text("定价方式", style = MaterialTheme.typography.titleSmall)
            FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                listOf("fixed" to "统一单价", "percent" to "按售价%").forEach { (v, l) ->
                    FilterChip(selected = mode == v, onClick = { mode = v }, label = { Text(l, maxLines = 1) })
                }
            }
            when (mode) {
                "fixed" -> SoTextField(
                    value = fixedValue,
                    // 单价规则唯一实现在 core/InputRules.kt（只数字 + 至多一个小数点）。
                    // 4 位小数：`price_rules.special_unit_price` 是 `Numeric(14,4)`。
                    onValueChange = { fixedValue = InputRules.priceInput(it) },
                    placeholder = "统一单价（元）",
                    keyboardType = KeyboardType.Decimal,
                    modifier = Modifier.fillMaxWidth(),
                )
                "percent" -> SoTextField(
                    value = percentValue,
                    // 百分比与金额同一条规则：都是"至多两位小数的数字"
                    onValueChange = { percentValue = InputRules.moneyInput(it, maxDecimals = 2, maxWhole = 3) },
                    placeholder = "默认售价的百分比（如 95 = 95%）",
                    keyboardType = KeyboardType.Decimal,
                    modifier = Modifier.fillMaxWidth(),
                )
            }
            Spacer(Modifier.height(10.dp))
            Button(
                onClick = {
                    val value = when (mode) { "percent" -> percentValue; else -> fixedValue }
                    onExecute(
                        selShippers.toList(),
                        selProducts.toList(),
                        mode,
                        value.takeIf { it.isNotBlank() },
                    )
                },
                enabled = !acting && selShippers.isNotEmpty() && selProducts.isNotEmpty(),
                modifier = Modifier.fillMaxWidth().height(52.dp),
            ) {
                Text(if (acting) "执行中…" else "执行调价", style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold)
            }
        }
    }
}
