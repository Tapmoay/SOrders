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
import androidx.compose.foundation.clickable
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.sp
import com.tapmoay.sorders.util.formatMoney
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
/** 每单金额怎么定：所有单统一 / 按运费分类（用户 2026-09-21）。 */
private val PIECE_MODE_OPTIONS = listOf("uniform" to "所有单统一", "category" to "按分类")
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

    if (vm.showTemplatePicker) FreightPickSheet(vm)

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
        val rows = rule.categories.map { CategoryRow(it.categoryName.ifBlank { "#" + it.categoryId }, it.pieceAmount, it.commissionRate) }
        if (rows.isNotEmpty()) {
            Spacer(Modifier.height(4.dp))
            Column {
                rows.forEach { row ->
                    Text(
                        "· " + row.name + "：" +
                            listOfNotNull(
                                row.pieceAmount.takeIf { it != "0" && it != "0.00" }?.let { "每单 ¥" + it },
                                row.commissionRate.takeIf { it != "0" && it != "0.00" }?.let { "提成 " + it + "%" },
                            ).joinToString(" + ").ifBlank { "（没定价）" },
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
        }
        Spacer(Modifier.height(4.dp))
        if (rule.templateBriefs.isEmpty()) {
            // 没勾价目 = 派给这个司机的单带不出运费，会全部进「待定价」。**必须显示出来**：
            // 卡片上什么都不写的话，用户看不出这条规则其实还没配好。
            Text(
                "还没勾价目 —— 派给这个司机的单会进「待定价」",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.error,
                modifier = Modifier.fillMaxWidth(),
            )
        } else {
            // 勾了 20 条也不能把卡片撑爆：只写前两条，后面用「等」。价格是这张卡的重点（有价才叫价目）。
            val briefs = rule.templateBriefs
            Text(
                text = "价目 ${briefs.size} 条：" + briefs.take(2).joinToString("、") +
                    if (briefs.size > 2) " 等" else "",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                maxLines = 2,
                overflow = TextOverflow.Ellipsis,
                modifier = Modifier.fillMaxWidth(),
            )
        }
        Spacer(Modifier.height(4.dp))
        if (rule.remark.isNotBlank()) {
            Text(
                rule.remark,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Spacer(Modifier.height(2.dp))
        }
        // 用户 2026-09-21 第二轮修正：「编辑和删除移到最右边去……卡片高度变窄一点」——
        // 所以按钮**不再单独占一行**：和最后一行信息同排，信息吃掉剩余宽度（`weight(1f)`）、按钮贴最右。
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            Text(
                modifier = Modifier.weight(1f),
                text = buildString {
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
                // ---- 价目归规则（用户 2026-09-21：「规则也就是取运费模板吧，也就是价目……
                //      勾选的时候就像一个商品界面，可以全选本分类，也可以单独勾」）----
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Text("用哪些运费价目", style = MaterialTheme.typography.labelMedium)
                        Text(
                            if (vm.draftTemplateIds.isEmpty()) "还没勾 —— 派单时这个司机的单会进「待定价」"
                            else "已勾 " + vm.draftTemplateIds.size + " 条（派单选了他就从这里按路线+分类带价）",
                            style = MaterialTheme.typography.bodySmall,
                            color = if (vm.draftTemplateIds.isEmpty()) MaterialTheme.colorScheme.error
                            else MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                    TextButton(onClick = { vm.showTemplatePicker = true }) { Text("选择") }
                }
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
                // ---- 每单金额怎么定（用户 2026-09-21：「按单计费有两种规则」）----
                Text("每单金额怎么定", style = MaterialTheme.typography.labelMedium)
                Spacer(Modifier.height(4.dp))
                SegmentedPicker(
                    labels = PIECE_MODE_OPTIONS.map { it.second },
                    selected = indexOfValue(PIECE_MODE_OPTIONS, vm.draftPieceMode),
                    onSelect = { vm.draftPieceMode = PIECE_MODE_OPTIONS[it].first },
                    fontSize = 14.sp,
                    height = 38.dp,
                )
                Spacer(Modifier.height(6.dp))
                if (vm.draftPieceMode == "uniform") {
                    SoTextField(
                        vm.draftPieceAmount,
                        { vm.draftPieceAmount = InputRules.moneyInput(it) },
                        placeholder = "每单金额（元，留空 = 0）",
                        keyboardType = KeyboardType.Decimal,
                    )
                    Spacer(Modifier.height(6.dp))
                } else {
                    // 按分类定价：一类一行（金额 / 比例），空着的那一类 = 不定价
                    Text(
                        "逐类填：哪一类货每单给多少、抽多少。没填的那些类，这一单就没有这份钱 —— " +
                            "（这一单属于哪一类，由派单时匹配到的运价带过来）",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    Spacer(Modifier.height(4.dp))
                    if (vm.categories.isEmpty()) {
                        Text(
                            "还没有运费分类 —— 先到「运费模板 → 分类管理」建几个",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.error,
                        )
                    }
                    vm.categories.forEach { c ->
                        val row = vm.draftCategoryRows[c.id] ?: ("" to "")
                        Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(bottom = 6.dp)) {
                            Text(
                                c.name,
                                style = MaterialTheme.typography.bodyMedium,
                                modifier = Modifier.width(64.dp),
                                maxLines = 1,
                            )
                            SoTextField(
                                row.first,
                                { vm.setCategoryRow(c.id, piece = InputRules.moneyInput(it), rate = null) },
                                Modifier.weight(1f),
                                placeholder = "每单 ¥",
                                keyboardType = KeyboardType.Decimal,
                            )
                            Spacer(Modifier.width(6.dp))
                            SoTextField(
                                row.second,
                                { vm.setCategoryRow(c.id, piece = null, rate = InputRules.moneyInput(it, maxDecimals = 2, maxWhole = 3)) },
                                Modifier.weight(1f),
                                placeholder = "提成 %",
                                keyboardType = KeyboardType.Decimal,
                            )
                        }
                    }
                    Spacer(Modifier.height(2.dp))
                }
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

/** 卡片上"这一类多少钱"的一行（从 DTO 归一过来，界面不直接读 DTO 字段）。 */
private data class CategoryRow(val name: String, val pieceAmount: String, val commissionRate: String)

/**
 * **用哪些运费价目**（选择器）—— 形制照「选择商品」那一页：
 * 左边按分类竖排，右边是这一格下的价目；顶部一个「全选本分类」。
 *
 * 用户 2026-09-21：「它就像匹配商品一样，在勾选的时候就是一个商品界面，
 * 可以全选本分类，也可以在这个分类里进行单独的勾选」。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun FreightPickSheet(vm: DriverBillingRulesViewModel) {
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    ModalBottomSheet(
        onDismissRequest = { vm.showTemplatePicker = false },
        sheetState = sheetState,
        dragHandle = { BottomSheetDefaults.DragHandle() },
    ) {
        Column(Modifier.fillMaxWidth().fillMaxHeight(0.9f)) {
            Row(Modifier.fillMaxWidth().padding(horizontal = 20.dp), verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text("用哪些运费价目", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
                    Text(
                        "已勾 " + vm.draftTemplateIds.size + " 条 · 派单选了这个司机就从这里按「路线 + 分类」带价",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                TextButton(onClick = { vm.toggleWholeTab() }) { Text("全选本分类") }
            }
            Spacer(Modifier.height(8.dp))
            if (vm.templates.isEmpty()) {
                Box(Modifier.fillMaxWidth().height(200.dp)) {
                    EmptyView(
                        "还没有运费价目 —— 先去「运费模板」建一条",
                        Modifier.align(Alignment.TopCenter).padding(top = 40.dp),
                    )
                }
            } else {
                Row(Modifier.weight(1f)) {
                    CategoryRail(
                        tabs = vm.pickerTabs(),
                        selected = vm.pickTab,
                        onSelect = { vm.pickTab = it },
                        modifier = Modifier.width(96.dp).fillMaxHeight(),
                    )
                    LazyColumn(
                        Modifier.weight(1f).fillMaxHeight(),
                        contentPadding = PaddingValues(start = 8.dp, end = 16.dp, bottom = 16.dp),
                    ) {
                        items(vm.pickerItems(), key = { it.id }) { t ->
                            Row(
                                Modifier.fillMaxWidth().clickable { vm.toggleTemplate(t.id) }.padding(vertical = 10.dp),
                                verticalAlignment = Alignment.CenterVertically,
                            ) {
                                Checkbox(checked = t.id in vm.draftTemplateIds, onCheckedChange = { vm.toggleTemplate(t.id) })
                                Spacer(Modifier.width(6.dp))
                                Column(Modifier.weight(1f)) {
                                    Text(
                                        t.fromPlace.ifBlank { "（无起点）" } + " → " + t.toPlace,
                                        style = MaterialTheme.typography.bodyLarge,
                                        maxLines = 1,
                                        overflow = TextOverflow.Ellipsis,
                                    )
                                    Text(
                                        listOfNotNull(
                                            t.priceName.ifBlank { null },
                                            if (t.categoryNames.isEmpty()) "未分类" else t.categoryNames.joinToString("、"),
                                        ).joinToString(" · "),
                                        style = MaterialTheme.typography.bodySmall,
                                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                                        maxLines = 1,
                                    )
                                }
                                Text(
                                    "¥" + formatMoney(t.fee),
                                    style = MaterialTheme.typography.titleMedium,
                                    fontWeight = FontWeight.Bold,
                                    color = Color(0xFFFF9500),
                                )
                            }
                        }
                    }
                }
            }
            Spacer(Modifier.height(8.dp))
            Row(Modifier.fillMaxWidth().padding(horizontal = 20.dp), horizontalArrangement = Arrangement.End) {
                Button(onClick = { vm.showTemplatePicker = false }) { Text("完成") }
            }
            Spacer(Modifier.height(12.dp))
        }
    }
}
