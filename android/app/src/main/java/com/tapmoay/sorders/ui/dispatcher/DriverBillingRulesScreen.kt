package com.tapmoay.sorders.ui.dispatcher

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.DeleteOutline
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.RestoreFromTrash
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.core.InputRules
import com.tapmoay.sorders.data.remote.dto.DriverBillingRuleDto
import com.tapmoay.sorders.ui.common.*

/**
 * 司机计费规则模板（派单员）。
 *
 * ### 这个页面只管"规则库"本身
 * 「把规则挂给某个司机」不在这里 —— 挂载走 `POST /driver-billing-rules/attach`，
 * 入口在司机编辑页（后端把写路径收成唯一一条，见 `api/v1/driver_billing_rules.py` 的文件注释）。
 * 这里只回答"有哪些规则、每条怎么算钱、改它、删它、把它从回收站拿回来"。
 *
 * ### 规则怎么算钱，只说后端那一句
 * 卡片上那行是后端的 `summary`（`services/driver_pay.py::PayRule.describe()`），
 * **不在客户端按字段重拼**：拼了就会和后端账单口径分叉，而分叉时没人知道该信哪个。
 */
private val VEHICLE_OPTIONS = listOf("" to "通用", "small" to "小型车", "large" to "大车", "trailer" to "挂车")
private val PIECE_UNIT_OPTIONS = listOf("order" to "每单/每车", "item" to "每件")
private val COMMISSION_OPTIONS = listOf("none" to "不提成", "freight" to "按运费", "goods" to "按商品金额")

private fun vehicleCn(raw: String?): String =
    VEHICLE_OPTIONS.firstOrNull { it.first == raw.orEmpty() }?.second ?: "通用"

private fun indexOfValue(options: List<Pair<String, String>>, value: String): Int =
    options.indexOfFirst { it.first == value }.coerceAtLeast(0)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DriverBillingRulesScreen(container: AppContainer, onBack: () -> Unit) {
    val vm: DriverBillingRulesViewModel = appViewModel { DriverBillingRulesViewModel(container) }
    val snackbar = remember { SnackbarHostState() }

    OneShotSnackbar(snackbar, vm.actionResult, onConsumed = { vm.actionResult = null })
    OneShotSnackbar(snackbar, vm.error, onConsumed = { vm.error = null })

    Scaffold(
        snackbarHost = { SnackbarHost(snackbar) },
        topBar = {
            AppTopBar(
                title = "司机计费规则",
                subtitle = "建好规则后，去司机编辑里挂给他",
                onBack = onBack,
                actions = {
                    TextButton(onClick = { vm.openCreate() }) {
                        Icon(Icons.Default.Add, null, Modifier.size(20.dp))
                        Spacer(Modifier.width(4.dp))
                        Text("新建")
                    }
                },
            )
        },
    ) { pad ->
        Column(Modifier.fillMaxSize().padding(pad)) {
            // 在用 / 回收站：撤回底线是"删错了要能拿回来"，那条路必须摆在明面上。
            SegmentedPicker(
                labels = listOf("在用", "回收站"),
                selected = if (vm.recycleBin) 1 else 0,
                onSelect = { vm.switchRecycleBin(it == 1) },
                modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp),
            )

            if (vm.loading && vm.rules.isEmpty()) {
                LoadingBox()
                return@Column
            }
            if (vm.rules.isEmpty()) {
                EmptyView(
                    text = if (vm.recycleBin) {
                        "回收站是空的"
                    } else {
                        "还没有计费规则\n规则 = 固定工资 / 每单多少钱 / 提成，三件可以任意组合"
                    },
                )
                if (!vm.recycleBin) {
                    Box(Modifier.fillMaxWidth(), contentAlignment = Alignment.Center) {
                        Button(onClick = { vm.openCreate() }) { Text("创建第一条规则") }
                    }
                }
                if (vm.loadFailed) {
                    Box(Modifier.fillMaxWidth().padding(top = 12.dp), contentAlignment = Alignment.Center) {
                        TextButton(onClick = { vm.load() }) { Text("重新加载") }
                    }
                }
                return@Column
            }

            LazyColumn(
                Modifier.fillMaxSize(),
                contentPadding = PaddingValues(16.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                items(vm.rules, key = { it.id }) { r ->
                    RuleCard(
                        rule = r,
                        inRecycleBin = vm.recycleBin,
                        onEdit = { vm.openEdit(r) },
                        onDelete = { vm.requestDelete(r) },
                        onRestore = { vm.restore(r) },
                    )
                }
            }
        }
    }

    if (vm.showDialog) {
        RuleDialog(vm)
    }

    // 删除确认：被拦时**框不关**，把后端那句话显示在里面（"还有 N 个司机挂着这份规则…"）。
    vm.deleteTarget?.let { r ->
        AlertDialog(
            onDismissRequest = { vm.deleteTarget = null; vm.deleteError = null },
            title = { Text("删除计费规则") },
            text = {
                Column {
                    Text("确定删除「${r.name}」？删错了可以在回收站里恢复。")
                    if (r.attachedCount > 0) {
                        Spacer(Modifier.height(8.dp))
                        Text(
                            "⚠️ 现在有 ${r.attachedCount} 个司机挂着它，后端会拦下这次删除。",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.error,
                        )
                    }
                    vm.deleteError?.let {
                        Spacer(Modifier.height(8.dp))
                        Text(it, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.error)
                    }
                }
            },
            confirmButton = {
                TextButton(onClick = { vm.confirmDelete() }, enabled = !vm.acting) {
                    Text("删除", color = MaterialTheme.colorScheme.error)
                }
            },
            dismissButton = {
                TextButton(onClick = { vm.deleteTarget = null; vm.deleteError = null }) { Text("取消") }
            },
        )
    }
}

/** 一条规则：名称（大）＋ 后端那一句 summary ＋ 车型/在用司机数 ＋ 备注 ＋ 操作。 */
@Composable
private fun RuleCard(
    rule: DriverBillingRuleDto,
    inRecycleBin: Boolean,
    onEdit: () -> Unit,
    onDelete: () -> Unit,
    onRestore: () -> Unit,
) {
    SectionCard(modifier = Modifier.fillMaxWidth()) {
        Text(rule.name, style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Bold)
        Spacer(Modifier.height(4.dp))
        // 后端算好的那句话，直接显示（见本文件顶部的说明）。
        Text(rule.summary, style = MaterialTheme.typography.bodyMedium)
        Spacer(Modifier.height(4.dp))
        Text(
            buildString {
                append(vehicleCn(rule.vehicleType))
                if (rule.attachedCount > 0) append(" · ${rule.attachedCount} 个司机在用")
            },
            style = MaterialTheme.typography.bodySmall,
            color = if (rule.attachedCount > 0) {
                MaterialTheme.colorScheme.primary
            } else {
                MaterialTheme.colorScheme.onSurfaceVariant
            },
        )
        if (rule.remark.isNotBlank()) {
            Spacer(Modifier.height(2.dp))
            Text(
                rule.remark,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        Spacer(Modifier.height(8.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            if (inRecycleBin) {
                TextButton(onClick = onRestore) {
                    Icon(Icons.Default.RestoreFromTrash, null, Modifier.size(18.dp))
                    Spacer(Modifier.width(2.dp))
                    Text("恢复")
                }
            } else {
                TextButton(onClick = onEdit) {
                    Icon(Icons.Default.Edit, null, Modifier.size(18.dp))
                    Spacer(Modifier.width(2.dp))
                    Text("编辑")
                }
                TextButton(
                    onClick = onDelete,
                    colors = ButtonDefaults.textButtonColors(contentColor = MaterialTheme.colorScheme.error),
                ) {
                    Icon(Icons.Default.DeleteOutline, null, Modifier.size(18.dp))
                    Spacer(Modifier.width(2.dp))
                    Text("删除")
                }
            }
        }
    }
}

/** 新建 / 编辑弹窗。三个金额框都能留空（空 = 0）。 */
@Composable
private fun RuleDialog(vm: DriverBillingRulesViewModel) {
    AlertDialog(
        onDismissRequest = { vm.showDialog = false },
        title = { Text(if (vm.editing == null) "新建计费规则" else "编辑计费规则") },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState())) {
                SoTextField(
                    vm.draftName,
                    { vm.draftName = it },
                    placeholder = "规则名称（如：挂车计件 / 小型车月薪+提成）",
                )

                Spacer(Modifier.height(12.dp))
                Text("适用车型", style = MaterialTheme.typography.labelMedium)
                Spacer(Modifier.height(4.dp))
                SegmentedPicker(
                    labels = VEHICLE_OPTIONS.map { it.second },
                    selected = indexOfValue(VEHICLE_OPTIONS, vm.draftVehicle),
                    onSelect = { vm.draftVehicle = VEHICLE_OPTIONS[it].first },
                    fontSize = 14.sp,
                    height = 38.dp,
                )
                Spacer(Modifier.height(4.dp))
                Text(
                    "选了车型 = 这份规则只能挂给那种车的司机（挂错了后端会拦）",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )

                Spacer(Modifier.height(12.dp))
                SoTextField(
                    vm.draftSalary,
                    // 金额规则唯一实现在 core/InputRules.kt（只数字 + 至多一个小数点 + 两位小数）。
                    // 这三个框原来什么过滤都没有，键盘还是 Number（没有小数点）。
                    { vm.draftSalary = InputRules.moneyInput(it) },
                    placeholder = "固定工资（元/月，留空 = 0）",
                    keyboardType = KeyboardType.Decimal,
                )

                Spacer(Modifier.height(12.dp))
                SoTextField(
                    vm.draftPieceAmount,
                    { vm.draftPieceAmount = InputRules.moneyInput(it) },
                    placeholder = "每单金额（元，留空 = 0）",
                    keyboardType = KeyboardType.Decimal,
                )
                Spacer(Modifier.height(6.dp))
                SegmentedPicker(
                    labels = PIECE_UNIT_OPTIONS.map { it.second },
                    selected = indexOfValue(PIECE_UNIT_OPTIONS, vm.draftPieceUnit),
                    onSelect = { vm.draftPieceUnit = PIECE_UNIT_OPTIONS[it].first },
                    fontSize = 14.sp,
                    height = 38.dp,
                )

                Spacer(Modifier.height(12.dp))
                Text("提成", style = MaterialTheme.typography.labelMedium)
                Spacer(Modifier.height(4.dp))
                SegmentedPicker(
                    labels = COMMISSION_OPTIONS.map { it.second },
                    selected = indexOfValue(COMMISSION_OPTIONS, vm.draftCommissionBase),
                    onSelect = { vm.draftCommissionBase = COMMISSION_OPTIONS[it].first },
                    fontSize = 14.sp,
                    height = 38.dp,
                )
                Spacer(Modifier.height(6.dp))
                SoTextField(
                    vm.draftCommissionRate,
                    { vm.draftCommissionRate = InputRules.moneyInput(it, maxDecimals = 2, maxWhole = 3) },
                    placeholder = "提成比例（%，如 5 表示 5%）",
                    enabled = vm.draftCommissionBase != "none",
                    keyboardType = KeyboardType.Decimal,
                )

                // 抽成范围：只有"按商品金额抽成"才有这回事（按运费抽成时后端会拒这个组合）。
                if (vm.draftCommissionBase == "goods") {
                    Spacer(Modifier.height(10.dp))
                    Text("只对哪些商品抽成", style = MaterialTheme.typography.labelMedium)
                    Spacer(Modifier.height(4.dp))
                    Text(
                        if (vm.draftScopeIds.isEmpty()) "现在：全部商品都抽（点下面的商品可以缩小范围）"
                        else "现在：只抽这 ${vm.draftScopeIds.size} 个商品（再点一下取消）",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    Spacer(Modifier.height(6.dp))
                    if (vm.products.isEmpty()) {
                        Text(
                            "没拉到商品库，暂时只能「全部商品都抽」——退出重进这一页再试",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.error,
                        )
                    } else {
                        FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                            vm.products.forEach { p ->
                                val on = p.id in vm.draftScopeIds
                                FilterChip(
                                    selected = on,
                                    onClick = {
                                        vm.draftScopeIds =
                                            if (on) vm.draftScopeIds - p.id else vm.draftScopeIds + p.id
                                    },
                                    label = { Text(p.name, style = MaterialTheme.typography.bodySmall) },
                                )
                            }
                        }
                    }
                }

                Spacer(Modifier.height(12.dp))
                SoTextField(vm.draftRemark, { vm.draftRemark = it }, placeholder = "备注（选填）")

                vm.dialogError?.let {
                    Spacer(Modifier.height(12.dp))
                    // 后端/轻校验的中文原因：留在框里，用户对着它改完再点保存。
                    Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.error)
                }
            }
        },
        confirmButton = {
            TextButton(onClick = { vm.save() }, enabled = !vm.acting) { Text("保存") }
        },
        dismissButton = { TextButton(onClick = { vm.showDialog = false }) { Text("取消") } },
    )
}
