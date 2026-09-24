package com.tapmoay.sorders.ui.common

import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import com.tapmoay.sorders.core.InputRules
import com.tapmoay.sorders.data.remote.api.UnitConversionCreateRequest
import com.tapmoay.sorders.data.remote.api.UnitConversionDto

/**
 * 「添加单位换算」那个**新弹窗**（用户 2026-09-24 点名的形态）。
 *
 * 用户原话：
 * > 「这换算单位啊，我们就把它加在那个**添加单位的那个页面**当中，添加单位那里再加个按钮可以说
 * >  **添加单位换算**，那个按钮点进去，就是一个**新的弹窗**，就可以在那里设置新的单位换算了。」
 *
 * ## 一份实现、两处消费
 * | 从哪打开 | 谁在管 | 建完做什么 |
 * |---|---|---|
 * | 「单位换算」页的「新增换算」 | `UnitConversionsViewModel` | 列表就地刷新 |
 * | 「请选择单位」页里的「添加单位换算」 | `ProductFormViewModel` | 顺带把商品的单位设成 `from_unit` |
 *
 * ## 界面上写清"这一条会被记成什么"
 * 底下那行 `1 车 = 8 方` 是**照着用户刚填的两栏实时拼出来的** —— 换算表的行是
 * 「1 个单位 = 多少个另一个单位」，方向填反了会得到 `1 方 = 0.125 车` 这种"也对但不想要"的行。
 * 让人在**提交之前**看见这一行，比事后在列表里发现方向反了强得多。
 *
 * ## 判据在**后端**（`services/unit_conversion.py`）
 * 空单位 / 两边同名 / 换算率 ≤ 0 / 一个源单位只能一条 / 反向对不许并存 —— 这些**不在这里
 * 再写一遍**（写了就会与后端走散，而两个数都不报错）。这里只做两件本地的事：
 * ① 输入层过滤（换算率走 `core/InputRules.kt`，与金额同一条规则）；
 * ② 后端的拒绝**原样显示**在弹窗里（那是一句能照着改的中文）。
 *
 * @param initial 非空 = 编辑那一条（预填三栏）
 * @param inUse 单位候选里要排在前面的那些（调用方给：换算表里出现过的单位）。
 *   候选算法只有一处（`unitChoices`）—— 与「请选择单位」页共用，免得两处给出的候选不一样。
 */
@Composable
fun UnitConversionDialog(
    initial: UnitConversionDto?,
    onSave: (UnitConversionCreateRequest) -> Unit,
    onDismiss: () -> Unit,
    inUse: List<String> = emptyList(),
    saving: Boolean = false,
    error: String? = null,
) {
    var from by remember(initial) { mutableStateOf(initial?.fromUnit.orEmpty()) }
    var to by remember(initial) { mutableStateOf(initial?.toUnit.orEmpty()) }
    var factor by remember(initial) { mutableStateOf(initial?.factor?.let { trimZeros(it) }.orEmpty()) }
    var remark by remember(initial) { mutableStateOf(initial?.remark.orEmpty()) }

    // 候选：出现的单位（换算表里用过的）+ 预设 16 个；当前填的那个保证在列表里（`unitChoices` 的第三条）
    val fromChips = remember(from, inUse) { unitChoices(from, inUse).take(10) }
    val toChips = remember(to, inUse) { unitChoices(to, inUse).take(10) }

    val f = from.trim()
    val t = to.trim()
    val rate = factor.trim()
    // 本地只挡"明显还没填完"（空、两边同名、率不是正数）—— 真正的判据在后端
    val ready = f.isNotEmpty() && t.isNotEmpty() && f != t && (rate.toBigDecimalOrNull()?.signum() ?: 0) > 0

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(if (initial == null) "添加单位换算" else "编辑单位换算") },
        text = {
            Column(Modifier.fillMaxWidth()) {
                SoTextField(
                    value = from,
                    onValueChange = { from = it },
                    placeholder = "1 个什么单位（例如：车）",
                )
                UnitChips(fromChips) { from = it }
                Spacer(Modifier.height(10.dp))
                SoTextField(
                    value = factor,
                    // 换算率的输入规则与金额同一条（`core/InputRules.kt`，唯一实现处）：
                    // 只让数字与小数点进来，小数位与列精度 `Numeric(14,4)` 对齐。
                    onValueChange = { factor = InputRules.moneyInput(it, maxDecimals = 4, maxWhole = 8) },
                    placeholder = "等于多少个（例如：8）",
                    keyboardType = KeyboardType.Decimal,
                )
                Spacer(Modifier.height(10.dp))
                SoTextField(
                    value = to,
                    onValueChange = { to = it },
                    placeholder = "换算成什么单位（例如：方）",
                )
                UnitChips(toChips) { to = it }
                Spacer(Modifier.height(10.dp))
                SoTextField(
                    value = remark,
                    onValueChange = { remark = it },
                    placeholder = "备注（选填，例如：沙子按 8 方算）",
                )
                Spacer(Modifier.height(10.dp))
                // 这一行是**照着刚填的实时拼的**：方向填反了在这里就能看出来
                Text(
                    if (ready) "将记成：1 $f = $rate $t" else "填完这两个单位与换算率，这里会显示这一条的样子",
                    style = MaterialTheme.typography.bodyMedium,
                    fontWeight = if (ready) FontWeight.Bold else FontWeight.Normal,
                    color = if (ready) MaterialTheme.colorScheme.onSurface
                    else MaterialTheme.colorScheme.onSurfaceVariant,
                )
                if (error != null) {
                    Spacer(Modifier.height(6.dp))
                    Text(error, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.error)
                }
            }
        },
        confirmButton = {
            TextButton(
                onClick = {
                    onSave(
                        UnitConversionCreateRequest(
                            fromUnit = f,
                            toUnit = t,
                            factor = rate,
                            remark = remark.trim(),
                        )
                    )
                },
                enabled = ready && !saving,
            ) { Text(if (saving) "保存中…" else "保存") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("取消") } },
    )
}

/** 一排可点的单位候选（点一下就填进上面那一栏）。**不占宽度**：候选多时横向滚动。 */
@Composable
private fun UnitChips(units: List<String>, onPick: (String) -> Unit) {
    Row(
        Modifier
            .fillMaxWidth()
            .padding(top = 6.dp)
            .horizontalScroll(rememberScrollState()),
        horizontalArrangement = Arrangement.spacedBy(6.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        units.forEach { u ->
            SuggestionChip(onClick = { onPick(u) }, label = { Text(u) })
        }
    }
}

/** `8.0000` → `8`（与后端 `format_factor` 同一个口径：末尾多余的 0 一律去掉）。 */
private fun trimZeros(raw: String): String {
    val s = raw.trim()
    if (!s.contains('.')) return s
    return s.trimEnd('0').trimEnd('.')
}
