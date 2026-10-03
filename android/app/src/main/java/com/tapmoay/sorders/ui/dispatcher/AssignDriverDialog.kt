package com.tapmoay.sorders.ui.dispatcher

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import com.tapmoay.sorders.core.InputRules
import com.tapmoay.sorders.ui.common.*
import com.tapmoay.sorders.util.formatMoney

/**
 * 派单弹窗（选司机）—— 一处实现，两个入口共用：待派单池的「派单」/「批量派单」与
 * 订单详情底部的「派单」（P12：派单员点开待派单的单，底部只有 现场支付 / 挂账 /
 * 拆分订单 / 删除订单，想派单还得回池子里把这张单再找一遍 —— 那不是入口）。
 *
 * ⛔ 为什么不各写一份：派单是同一个动作（选司机 + 运费 / 单独定价 / 收现金 / 备注，
 *    成功后 PENDING_DISPATCH → 派单中）。两套界面一定会走散，而走散的表现是
 *    「同一个司机在这一页能派、在那一页报错」—— 那时用户不知道信哪一页。
 *
 * ## P8 在这一份里怎么修的
 * · 页签原来是「大车司机 / 挂车司机」两档，而大车那一档把小车司机也吞了进来
 *   （过滤条件写的是 vehicleType != trailer）。司机分三种 —— 小车 / 大车 / 挂车
 *   （docs/plan-driver-freight.md:6-9）⇒ 按三种分档，且只显示真的有人 的档位
 *   （空页签点进去一片空白，而「这档没人」与「还没拉到司机」在界面上长得一样）；
 * · 输入框上方的标签原来只跟页签走（写死大车司机/挂车司机）：选中王强（小车司机）
 *   后标签还写「大车司机」⇒ 现在标签跟选中的人走，车型标签复用
 *   UsersManageScreen.kt::driverKindLabel（全 App 唯一一份，别在这里另写）。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AssignDriverDialog(
    vm: DispatcherPoolViewModel,
    /** 派单成功之后回调（订单详情页用它刷新自己那一份；待派单池不需要）。 */
    onAssigned: () -> Unit = {},
) {
    // 运费模板子弹窗的开关属于「这一次派单」，所以跟着本组件走（原来是池子页的局部状态）
    var templatePick by remember { mutableStateOf(false) }

    // 派单弹窗（单选/批量共用）
    if (vm.showAssignDialog) {
        AlertDialog(
            onDismissRequest = { vm.showAssignDialog = false },
            title = { Text(if (vm.selectionMode) "批量派单（" + vm.selectedIds.size + " 单）" else "派单") },
            text = {
                Column {
                    Text("选择司机", style = MaterialTheme.typography.labelLarge)
                    Spacer(Modifier.height(8.dp))
                    if (vm.drivers.isEmpty()) {
                        Text(
                            "暂无可用司机账号，请先在「司机管理」中添加",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.error,
                        )
                    } else {
                        // ⚠️ 页签是车型分组（判据就是 vehicle_type）。三种车各一档，三种之外
                        // （没设过车型的账号）单独一档 —— ⛔ 不能让他们无处可派。
                        val kindOrder = listOf("small", "large", "trailer")
                        val kinds = kindOrder.filter { k -> vm.drivers.any { (it.vehicleType ?: "") == k } } +
                            if (vm.drivers.any { (it.vehicleType ?: "") !in kindOrder }) listOf("") else emptyList()
                        var pickState by remember { mutableStateOf<String?>(null) }
                        // 默认落在第一个真的有人 的档位（都没有时按大车组，与老行为一致）
                        val pick = pickState?.takeIf { k -> kinds.contains(k) } ?: kinds.firstOrNull() ?: "large"
                        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                            kinds.forEach { k ->
                                val sel = k == pick
                                Surface(
                                    color = if (sel) MaterialTheme.colorScheme.primary.copy(alpha = 0.14f) else MaterialTheme.colorScheme.surfaceVariant,
                                    shape = MaterialTheme.shapes.small,
                                    modifier = Modifier.weight(1f).clickable {
                                        pickState = k
                                        // 切页签顺带选中这一档第一位：原有行为，本轮保留
                                        vm.selectedDriverId = vm.drivers.firstOrNull { (it.vehicleType ?: "") == k }?.id
                                    },
                                ) {
                                    Column(
                                        Modifier.fillMaxWidth().padding(vertical = 8.dp),
                                        horizontalAlignment = Alignment.CenterHorizontally,
                                    ) {
                                        Icon(
                                            kindIcon(k), contentDescription = null,
                                            tint = if (sel) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurfaceVariant,
                                        )
                                        Spacer(Modifier.height(2.dp))
                                        Text(
                                            driverKindLabel(k.ifBlank { null }),
                                            style = MaterialTheme.typography.labelMedium,
                                            fontWeight = if (sel) FontWeight.Bold else FontWeight.Normal,
                                            color = if (sel) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurfaceVariant,
                                        )
                                    }
                                }
                            }
                        }
                        Spacer(Modifier.height(8.dp))
                        var dExp by remember { mutableStateOf(false) }
                        ExposedDropdownMenuBox(expanded = dExp, onExpandedChange = { dExp = it }) {
                            OutlinedTextField(
                                value = if (vm.selectedDriver != null) (vm.selectedDriver?.fullName?.ifBlank { vm.selectedDriver?.username ?: "" } ?: "") + " " + (vm.selectedDriver?.phone ?: "") else "请选择司机",
                                onValueChange = {},
                                readOnly = true,
                                // P8：标签跟着选中的人走（他是什么车型就写什么）；一位都没选时才写档位名
                                label = { Text(driverKindLabel(vm.selectedDriver?.vehicleType ?: pick.ifBlank { null })) },
                                trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(expanded = dExp) },
                                modifier = Modifier.fillMaxWidth().menuAnchor(),
                            )
                            ExposedDropdownMenu(expanded = dExp, onDismissRequest = { dExp = false }) {
                                // P8：只列这一档的人（原来写的是 vehicleType != trailer）
                                vm.drivers.filter { (it.vehicleType ?: "") == pick }.forEach { d ->
                                    DropdownMenuItem(
                                        text = { Text((d.fullName.ifBlank { d.username }) + " " + d.phone) },
                                        onClick = {
                                            vm.selectedDriverId = d.id
                                            dExp = false
                                        },
                                    )
                                }
                            }
                        }
                    }
                    Spacer(Modifier.height(12.dp))
                    if (!vm.selectionMode && vm.isPieceDriver(vm.selectedDriver)) {
                        Text("运费（该司机按单计费）", style = MaterialTheme.typography.labelLarge)
                        Spacer(Modifier.height(6.dp))
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            OutlinedTextField(
                                value = vm.assignFreight,
                                // 金额规则唯一实现在 core/InputRules.kt（原来这三个框都没有过滤）
                                onValueChange = { vm.assignFreight = InputRules.moneyInput(it) },
                                label = { Text("一车运费 ¥（可后补）") },
                                singleLine = true,
                                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                                modifier = Modifier.weight(1f),
                            )
                            Spacer(Modifier.width(8.dp))
                            TextButton(onClick = { templatePick = true }) { Text("模板") }
                        }
                        Spacer(Modifier.height(8.dp))
                    }
                    val ruleName = vm.selectedDriver?.driverRuleName?.takeIf { it.isNotBlank() }
                    if (!vm.selectionMode && ruleName != null) {
                        Text("这一单单独定（不填就按他的规则算）", style = MaterialTheme.typography.labelLarge)
                        Spacer(Modifier.height(4.dp))
                        Text(
                            "他现在的规则：$ruleName" +
                                vm.selectedDriver?.paySummary?.takeIf { it.isNotBlank() }?.let { " · $it" }.orEmpty(),
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                        Spacer(Modifier.height(6.dp))
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            OutlinedTextField(
                                value = vm.assignPieceAmount,
                                onValueChange = { vm.assignPieceAmount = InputRules.moneyInput(it) },
                                label = { Text("这一单的钱 ¥") },
                                singleLine = true,
                                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                                modifier = Modifier.weight(1f),
                            )
                            OutlinedTextField(
                                value = vm.assignCommissionRate,
                                onValueChange = { vm.assignCommissionRate = InputRules.moneyInput(it, maxDecimals = 2, maxWhole = 3) },
                                label = { Text("提成 %") },
                                singleLine = true,
                                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                                modifier = Modifier.weight(1f),
                            )
                        }
                        Spacer(Modifier.height(8.dp))
                    }
                    Spacer(Modifier.height(4.dp))
                    Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.fillMaxWidth()) {
                        Checkbox(
                            checked = vm.assignCollectCash,
                            onCheckedChange = { vm.assignCollectCash = it },
                        )
                        Spacer(Modifier.width(8.dp))
                        Column {
                            Text("收取现金", style = MaterialTheme.typography.bodyMedium, fontWeight = androidx.compose.ui.text.font.FontWeight.Bold)
                            Text(
                                "勾选后司机送达时可选择「收现金」或「挂账」；不勾选则送达自动挂账",
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        }
                    }
                    Spacer(Modifier.height(4.dp))
                    OutlinedTextField(
                        value = vm.assignNote,
                        onValueChange = { vm.assignNote = it },
                        label = { Text("内部备注（可选，与司机可见）") },
                        minLines = 2,
                        modifier = Modifier.fillMaxWidth(),
                    )
                    // P8 附带（与 BUG-0003 同源）：这个弹窗以前从不渲染 vm.error —— 没选司机就点
                    // 「确认派单」，那句「请选择司机」界面上没人看得见（用户侧＝点了没反应）。
                    // 规范 §4.8：表单的错画在表单里，位置在提交按钮上方。
                    FormErrorLine(vm.error)
                }
            },
            confirmButton = {
                TextButton(onClick = { vm.confirmAssign(onAssigned) }, enabled = !vm.acting) {
                    Text(if (vm.acting) "派单中…" else "确认派单")
                }
            },
            dismissButton = { TextButton(onClick = { vm.showAssignDialog = false }) { Text("取消") } },
        )
    }
    // 运费模板选择
    if (templatePick) {
        AlertDialog(
            onDismissRequest = { templatePick = false },
            title = { Text("选择运费模板") },
            text = {
                Column(Modifier.heightIn(max = 320.dp)) {
                    if (vm.templates.isEmpty()) {
                        Text(
                            "暂无模板，请先在「订单模板」中维护",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    } else {
                        vm.templates.forEach { t ->
                            Row(
                                Modifier.fillMaxWidth().clickable {
                                    vm.applyTemplate(t)
                                    templatePick = false
                                }.padding(vertical = 6.dp),
                                verticalAlignment = Alignment.CenterVertically,
                            ) {
                                Column(Modifier.weight(1f)) {
                                    Text(t.name, style = MaterialTheme.typography.bodyMedium, fontWeight = androidx.compose.ui.text.font.FontWeight.Bold)
                                    Text(
                                        t.fromPlace + " → " + t.toPlace +
                                            (t.vehicleType?.let { v -> when (v) {
                                                "small" -> " · 小车"; "large" -> " · 大车"; "trailer" -> " · 挂车"; else -> "" } } ?: ""),
                                        style = MaterialTheme.typography.bodySmall,
                                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                                    )
                                }
                                Text(
                                    "¥" + formatMoney(t.fee),
                                    style = MaterialTheme.typography.titleSmall,
                                    fontWeight = androidx.compose.ui.text.font.FontWeight.Bold,
                                    color = androidx.compose.ui.graphics.Color(0xFFFF9500),
                                )
                            }
                            HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
                        }
                    }
                }
            },
            confirmButton = { TextButton(onClick = { templatePick = false }) { Text("关闭") } },
        )
    }
}

/** 页签上的车型图标（空串 = 没设过车型的账号：用最中性的那个人形，别猜成某一种车）。 */
private fun kindIcon(kind: String): ImageVector = when (kind) {
    "small" -> Icons.Default.DirectionsCar
    "large" -> Icons.Default.LocalShipping
    "trailer" -> Icons.Default.AirportShuttle
    else -> Icons.Default.Person
}
