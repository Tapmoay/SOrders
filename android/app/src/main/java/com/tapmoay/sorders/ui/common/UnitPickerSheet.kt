package com.tapmoay.sorders.ui.common

import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp

/**
 * 「请选择单位」——**一屏把单位挑完**（2026-09-21 商品管理改版第 1 期，P5）。
 *
 * ## 抄的是**布局**，不是它的功能（用户 2026-09-21 原话）
 * > 「单位就是做到我们现在有的（那）档…他的档位不要超，只是抄他的那个**布局**的样式。」
 *
 * 所以照抄的是那个选择页的形态：**顶上搜索框 + 下面一片 chips + 选中实底 + 底部一对按钮**；
 * ⛔ **没有**抄它那 60 个餐饮单位词表，也**没有**「称重单位」那个勾选
 * （称重对我们的意义是"整车/整件"，不是电子秤读数）。
 *
 * ## ⚠️ 这一处是设计规范 §5 的**例外**，理由写在这里
 * §5 原来写着「下拉一律 `ExposedDropdownMenuBox` 点选回填，**不要**用点选 chips 替代下拉」
 * （商品编辑里那个单位下拉就是照它做的）。这一页是**例外**，两条理由：
 * 1. 单位是**枚举得很死的短词**（一两个字），而这里要的是"把候选**一次全看见**"——
 *    下拉要点开、再滚动找，多两次交互；chips 一屏铺完、点一下就选中；
 * 2. 这里**不是"用一个 chips 冒充下拉"**：它是一条独立的**选择页**（有搜索、有选中态、
 *    有确定的取消），与"把下拉摊成几个块"不是一回事。
 * 落地这一版时已同步把 §5 那一条改成"（下拉仍是默认；单位选择页是登记在案的例外）"。
 *
 * ## 为什么单位是**封闭词表**
 * 见 `Units.kt` 的文件头：词表 = 原来的 16 个预设 **+ 商品库里已经在用的**。
 * 后者是硬要求 —— 否则编辑一个单位是"提"的老商品时，用户在这个页面里找不到它。
 *
 * @param current 这个商品**现在**的单位（默认选中它；它在不在列表里由 `unitChoices` 保证）
 * @param inUse 商品库里**已经在用**的单位（各页面从自己的商品目录去重得到，见 [unitsInUse]）
 * @param onPick 点「确定」时回传选中的单位（点「取消」不回传）
 */
@OptIn(ExperimentalMaterial3Api::class, ExperimentalLayoutApi::class)
@Composable
fun UnitPickerSheet(
    current: String,
    inUse: List<String> = emptyList(),
    onPick: (String) -> Unit,
    onDismiss: () -> Unit,
) {
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    val units = remember(current, inUse) { unitChoices(current, inUse) }
    // 草稿态：**点了 chips 不等于生效**，要点「确定」才回传 ——
    // 与参考图那个页面同一套交互（它有取消/确定），也让"手滑点错"可以退回来。
    var picked by remember(current) { mutableStateOf(unitOrDefault(current)) }
    var keyword by remember { mutableStateOf("") }
    val shown = remember(units, keyword) { filterUnits(units, keyword) }

    ModalBottomSheet(onDismissRequest = onDismiss, sheetState = sheetState) {
        Column(
            Modifier
                .fillMaxWidth()
                .padding(horizontal = 20.dp)
                .padding(bottom = 24.dp),
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    "请选择单位",
                    style = MaterialTheme.typography.titleLarge,
                    fontWeight = FontWeight.Bold,
                    modifier = Modifier.weight(1f),
                )
                SheetCloseButton(onClick = onDismiss)
            }
            Spacer(Modifier.height(8.dp))

            // 搜索框：与全库同一个形态（`SoTextField`：浅灰底 + 圆角 12 + 无漂浮标签）
            SoTextField(
                value = keyword,
                onValueChange = { keyword = it },
                placeholder = "搜索单位",
            )

            Spacer(Modifier.height(12.dp))

            if (shown.isEmpty()) {
                // ⚠️ 这两句是**空态文案**（搜不到时这一屏就只剩它们），必须**常显**：
                //    它们不是"解释句"、不能走 `Hint` —— 总开关关掉之后藏了它，用户看到的是**一片空白**，
                //    「搜不到」和「这个单位不存在」就分不出来了。
                //    （`_tools/qa/_check_hints.py` 抓出来的：空态句一律归 EMPTY、永不被开关藏掉。）
                Text(
                    "没有匹配「${keyword.trim()}」的单位",
                    style = MaterialTheme.typography.bodyMedium,
                )
                Spacer(Modifier.height(4.dp))
                Text(
                    "单位是固定词表 + 商品库里已经在用的那些；这一版不支持自己新增单位。",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            } else {
                FlowRow(
                    horizontalArrangement = Arrangement.spacedBy(6.dp),
                    verticalArrangement = Arrangement.spacedBy(2.dp),
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    shown.forEach { u ->
                        FilterChip(
                            selected = u == picked,
                            onClick = { picked = u },
                            label = { Text(u, maxLines = 1) },
                        )
                    }
                }
            }

            Spacer(Modifier.height(18.dp))
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                OutlinedButton(
                    onClick = onDismiss,
                    modifier = Modifier.weight(1f).height(48.dp),
                ) { Text("取消") }
                Button(
                    onClick = { onPick(picked) },
                    enabled = picked.isNotBlank(),
                    modifier = Modifier.weight(1.4f).height(48.dp),
                ) { Text("确定") }
            }
        }
    }
}

/**
 * 一堆商品里"已经在用"的单位（去重、按出现顺序）—— 给 [UnitPickerSheet] 的 `inUse`。
 *
 * 单独一个入口的理由：**每个调用点都自己去 `map{unit}.distinct()` 就会各写一份**
 * （而 `unit` 还可能是 null/空白，各写一份时兜底就会不一致）。
 * 这里只管"取出来"，怎么排由 `unitChoices` 说了算。
 */
fun unitsInUse(units: List<String?>): List<String> =
    units.mapNotNull { it?.trim()?.ifEmpty { null } }.distinct()
