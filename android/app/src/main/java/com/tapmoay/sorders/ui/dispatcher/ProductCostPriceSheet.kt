package com.tapmoay.sorders.ui.dispatcher

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
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
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.tapmoay.sorders.core.InputRules
import com.tapmoay.sorders.data.remote.dto.ProductCostPriceDto
import com.tapmoay.sorders.ui.common.DangerConfirmDialog
import com.tapmoay.sorders.ui.common.FormErrorLine
import com.tapmoay.sorders.ui.common.Hint
import com.tapmoay.sorders.ui.common.SheetCloseButton
import com.tapmoay.sorders.ui.common.SoTextField
import com.tapmoay.sorders.ui.theme.QuickPriceGreen
import com.tapmoay.sorders.util.trimMoneyZeros

/**
 * 「成本价口径」弹层（FEAT-0025，用户 2026-10-11 派单）。
 *
 * 用户的原话：「我们是可以设置多个成本价的……只不过我们一般情况下是默认按一个成本价，也就是真实成本价，
 * 按那个来计算的……当然，我们有时候计算的时候还有第二个成本价 —— 这个成本价可能是加了其他东西、
 * 或者比如说有补贴啊等等之后的成本价。所以一定要有多个成本价。」
 *
 * 这个弹层就是那个"多个"：**第一条永远是默认口径**（[ProductCostPriceDto.isDefault]，后端从
 * `products.cost_price` 合成出来的投影，`id = 0`）—— 订单与毛利算账用的就是它，
 * 所以它**没有**改 / 删入口（改它只有编辑页「成本价」那一格，那会记进成本价时间轴）。
 * 下面其余几条是**参考口径**，能加、能改名改价、能软删 —— 它们一个字节都不参与金额计算。
 *
 * ⚠️ 每一条要显示的口径说明**照抄后端**（[ProductCostPriceDto.note]，后端只有一份措辞），
 * ⛔ 界面上不另写一套"这个算不算毛利"的说法（两处说法迟早会不一致，而这是钱的事）。
 *
 * ⚠️ 软删掉的条目在同一个弹层下面的「回收站」里，**手边就有恢复入口**（用户 2026-09-20 的硬规矩：
 * 有删除按钮的地方必须有恢复入口）。
 *
 * @param rows 默认口径 + 全部参考口径（顺序由后端给：默认那条 `sortOrder = -1`，永远排最前）。
 * @param deletedRows 软删掉的参考口径（回收站）。
 * @param onSave 新增（第一参 `null`）或改某一条；成功后调用第三参把编辑器清空。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun ProductCostPriceSheet(
    productName: String,
    unit: String,
    rows: List<ProductCostPriceDto>,
    deletedRows: List<ProductCostPriceDto>,
    loading: Boolean,
    busy: Boolean,
    error: String?,
    onSave: (Long?, String, String, () -> Unit) -> Unit,
    onDelete: (Long) -> Unit,
    onRestore: (Long) -> Unit,
    onDismiss: () -> Unit,
) {
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    val u = unit.ifBlank { "件" }

    // 编辑器：正在改哪一条（null = 正在"加一条"）、框里的名字与金额。
    var editorId by remember { mutableStateOf<Long?>(null) }
    var editorName by remember { mutableStateOf("") }
    var editorAmount by remember { mutableStateOf("") }
    // 2026-10-10（BUG-0028 / TA-09）的口径：输入里"会被过滤掉的东西"要让用户看见。
    // note 非空 = 他打的字会被改成别的值 —— 原样留着 + 拒绝保存，⛔ 不许静默改数。
    var editorNote by remember { mutableStateOf<String?>(null) }
    var confirming by remember { mutableStateOf<ProductCostPriceDto?>(null) }

    fun clearEditor() {
        editorId = null
        editorName = ""
        editorAmount = ""
        editorNote = null
    }

    ModalBottomSheet(onDismissRequest = onDismiss, sheetState = sheetState) {
        Column(
            // 「拉到最上面」（`_check_sheet_form_pages.py` 的形态三件套之一）：抽屉一打开就占满可用高度，
            // 字段比一屏高时由下面那两处滚动容器接管 —— 少了这一行抽屉就退回「半截」。
            Modifier.fillMaxWidth().fillMaxHeight(0.9f).padding(horizontal = 20.dp).padding(bottom = 24.dp),
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    "成本价口径",
                    style = MaterialTheme.typography.titleLarge,
                    fontWeight = FontWeight.Bold,
                    modifier = Modifier.weight(1f),
                )
                SheetCloseButton(onClick = onDismiss)
            }
            Text(
                productName.ifBlank { "这个商品" } + "（单位：" + u + "）",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Spacer(Modifier.height(8.dp))
            // ⚠️ 这一句是**钱的口径**（`_check_hints.py` 的四族关键解释句之一）⇒ **走 Text，不走 Hint**：
            //    关掉提示开关的人也必须看得见"哪个成本价参与算账"——它不属于「不重要的 / 繁琐的」。
            Text(
                "一个商品可以有好几个成本价：最上面那条「真实成本价」是订单与毛利算账用的，要改它请回编辑页改「成本价」那一格（改了会记进成本价历史）。下面加的其它口径是参考口径 —— 比如加了运费、补贴或者返点之后的成本，它们不参与订单与毛利的计算。",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Spacer(Modifier.height(10.dp))

            if (loading) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    CircularProgressIndicator(Modifier.size(16.dp), strokeWidth = 2.dp)
                    Spacer(Modifier.width(8.dp))
                    Text("正在读取…", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            } else {
                Column(
                    Modifier.fillMaxWidth().heightIn(max = 260.dp).verticalScroll(rememberScrollState()),
                    verticalArrangement = Arrangement.spacedBy(6.dp),
                ) {
                    rows.forEach { row ->
                        CostPriceLine(
                            row = row,
                            unit = u,
                            busy = busy,
                            onEdit = {
                                editorId = row.id
                                editorName = row.name
                                editorAmount = trimMoneyZeros(row.costPrice)
                                editorNote = null
                            },
                            onDelete = { confirming = row },
                        )
                    }
                    if (rows.count { !it.isDefault } == 0) {
                        Text(
                            "还没有别的成本价。",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            modifier = Modifier.padding(vertical = 6.dp),
                        )
                    }
                }
            }

            Spacer(Modifier.height(12.dp))
            Text(
                if (editorId == null) "加一条成本价" else "改这一条",
                style = MaterialTheme.typography.labelLarge,
            )
            Spacer(Modifier.height(6.dp))
            SoTextField(
                value = editorName,
                onValueChange = { editorName = it },
                placeholder = "口径名称，例如「返点后成本」",
                enabled = !busy,
            )
            Spacer(Modifier.height(6.dp))
            SoTextField(
                value = editorAmount,
                onValueChange = { raw ->
                    // 规则唯一实现在 core/InputRules.kt（过滤走 priceInput、说明走 priceRewriteNote，
                    // 同一份规则的两面）。有改写就保留用户打的字，让他看见自己被改了什么。
                    val next = InputRules.priceInput(raw)
                    val note = InputRules.priceRewriteNote(raw)
                    editorNote = note
                    editorAmount = if (note == null) next else raw
                },
                placeholder = "成本价（元 / " + u + "）",
                keyboardType = KeyboardType.Decimal,
                enabled = !busy,
            )
            if (editorNote != null) {
                Spacer(Modifier.height(4.dp))
                Text(
                    editorNote!!,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.error,
                )
            }
            FormErrorLine(error)
            Spacer(Modifier.height(8.dp))
            Row(verticalAlignment = Alignment.CenterVertically) {
                Button(
                    onClick = {
                        onSave(editorId, editorName, editorAmount) { clearEditor() }
                    },
                    enabled = !busy && editorNote == null && editorName.isNotBlank(),
                ) { Text(if (busy) "保存中…" else "保存这条") }
                Spacer(Modifier.width(8.dp))
                TextButton(onClick = { clearEditor() }, enabled = !busy) { Text("清空") }
            }

            if (deletedRows.isNotEmpty()) {
                Spacer(Modifier.height(14.dp))
                Text("回收站（删掉的口径）", style = MaterialTheme.typography.labelLarge)
                Spacer(Modifier.height(4.dp))
                // 同样不走 Hint：这是「删了还能拿回来」的**状态说明**（数据类），不是可开关的提示。
                Text(
                    "删除是「伪装」删除：这一条只是从上面的清单里收起来，随时能在这里放回来，放回来之后名字、金额和排序都和删之前一模一样。",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Spacer(Modifier.height(6.dp))
                Column(
                    Modifier.fillMaxWidth().heightIn(max = 160.dp).verticalScroll(rememberScrollState()),
                    verticalArrangement = Arrangement.spacedBy(6.dp),
                ) {
                    deletedRows.forEach { row ->
                        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                            Text(
                                row.name + " · " + trimMoneyZeros(row.costPrice) + " 元",
                                style = MaterialTheme.typography.bodyMedium,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                                maxLines = 1,
                                overflow = TextOverflow.Ellipsis,
                                modifier = Modifier.weight(1f),
                            )
                            TextButton(onClick = { onRestore(row.id) }, enabled = !busy) { Text("恢复") }
                        }
                    }
                }
            }
        }
    }

    confirming?.let { row ->
        DangerConfirmDialog(
            title = "删除成本价口径「" + row.name + "」？",
            message = "删掉之后这一条不再出现在上面，订单与毛利的算法一个字都不变；删错了可以在下面的回收站里放回来。",
            onConfirm = {
                onDelete(row.id)
                confirming = null
                if (editorId == row.id) clearEditor()
            },
            onDismiss = { confirming = null },
            enabled = !busy,
        )
    }
}

/** 清单里的一条：默认那条只显示口径说明，参考口径右边有「改」和「删」。 */
@Composable
private fun CostPriceLine(
    row: ProductCostPriceDto,
    unit: String,
    busy: Boolean,
    onEdit: () -> Unit,
    onDelete: () -> Unit,
) {
    // 口径说明照抄后端（只有一份措辞）；万一后端没给，就只说它是哪一类，不另写"算不算毛利"。
    val note = row.note.ifBlank { if (row.isDefault) "默认口径" else "参考口径" }
    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
        Column(Modifier.weight(1f)) {
            Text(row.name, style = MaterialTheme.typography.bodyLarge, fontWeight = if (row.isDefault) FontWeight.Bold else null)
            Text(
                trimMoneyZeros(row.costPrice) + " 元 / " + unit,
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurface,
            )
            Text(
                note,
                style = MaterialTheme.typography.bodySmall,
                color = if (row.isDefault) Color(QuickPriceGreen) else MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        if (!row.isDefault) {
            TextButton(onClick = onEdit, enabled = !busy) { Text("改") }
            TextButton(onClick = onDelete, enabled = !busy) { Text("删") }
        }
    }
}
