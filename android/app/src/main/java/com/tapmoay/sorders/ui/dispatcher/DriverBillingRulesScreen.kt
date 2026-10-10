package com.tapmoay.sorders.ui.dispatcher

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Badge
import androidx.compose.material.icons.filled.CurrencyYuan
import androidx.compose.material.icons.filled.DeleteOutline
import androidx.compose.material.icons.filled.DirectionsCar
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.Notes
import androidx.compose.material.icons.filled.Payments
import androidx.compose.material.icons.filled.PriceChange
import androidx.compose.material.icons.filled.RestoreFromTrash
import androidx.compose.material.icons.filled.Route
import androidx.compose.material.icons.filled.ShoppingCart
import androidx.compose.material.icons.filled.Straighten
import androidx.compose.material3.*
import androidx.compose.foundation.clickable
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.sp
import com.tapmoay.sorders.util.formatMoney
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.core.InputRules
import com.tapmoay.sorders.data.remote.dto.DriverBillingRuleDto
import com.tapmoay.sorders.ui.common.*
import com.tapmoay.sorders.ui.common.Hint
import com.tapmoay.sorders.ui.theme.DestOrange
import com.tapmoay.sorders.ui.theme.MoneyOrange
import com.tapmoay.sorders.ui.theme.OriginTeal
import com.tapmoay.sorders.ui.theme.ProductPurple
import com.tapmoay.sorders.ui.theme.ShipperTeal

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

    // 表单开着时，系统返回键先关表单（不是退出这一页）—— 与真的「单独一页」完全一样的手感。
    // ⚠️ 价目选择层（[FreightPickSheet]）在下面**后**注册，所以它开着时返回键先关的是那一层。
    BackHandler(enabled = vm.showForm) { vm.closeForm() }

    Scaffold(
        snackbarHost = { SnackbarHost(snackbar) },
        topBar = {
            // 表单开着就换成表单自己的标题 + 返回：两个顶栏叠着出现，用户说不清「现在在哪儿」。
            if (vm.showForm) {
                AppTopBar(
                    title = if (vm.editing == null) "新建计费规则" else "编辑计费规则",
                    subtitle = "固定工资 / 每单多少钱 / 提成，三件可以任意组合",
                    onBack = { vm.closeForm() },
                )
            } else {
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
            }
        },
        bottomBar = {
            // 保存栏**常驻**（不跟着内容滚）：这份表单很长，错误行滚到底才看得见等于没有 ——
            // 见 [FormErrorLine] 的 KDoc「表单的错误必须和表单同生共死」。
            if (vm.showForm) RuleFormBottomBar(vm)
        },
    ) { pad ->
        // 表单开着 = 整页表单（同屏第二层）：早返回，列表那一段原样留在下面、不缩进。
        if (vm.showForm) {
            RuleFormBody(vm, pad)
            return@Scaffold
        }
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

    if (vm.showTemplatePicker) FreightPickSheet(vm)

    // 删除确认：被拦时**框不关**，把后端那句话显示在里面（"还有 N 个司机挂着这份规则…"）。
    vm.deleteTarget?.let { r ->
        CardAlertDialog(
            tone = DialogTone.DANGER,
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
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(
                rule.name,
                style = MaterialTheme.typography.titleSmall,
                fontWeight = FontWeight.Bold,
                modifier = Modifier.weight(1f),
            )
            // 没勾价目 = 这条规则还没配好（下面那句会解释后果）。挂个角标：卡片一多，
            // 光看名字看不出哪条还没配好，得逐张读完才知道（E2E 走查 P19）。
            if (rule.templateBriefs.isEmpty()) {
                Spacer(Modifier.width(6.dp))
                MiniChip("缺价目", MaterialTheme.colorScheme.error)
            }
        }
        Spacer(Modifier.height(4.dp))
        // 「每单 ¥22」是**给司机的钱**，不是货主付的运费 —— 不写这四个字，用户会把它读成
        // "这单的运费已经定了"（E2E 走查 P19：同一张卡既说按单计件，又说还没勾价目）。
        Text("给司机的钱", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
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
                                row.pieceAmount.takeIf { it != "0" && it != "0.00" }?.let { "每单 ¥" + formatMoney(it) },
                                row.commissionRate.takeIf { it != "0" && it != "0.00" }?.let { "提成 " + formatMoney(it) + "%" },
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
            // 卡片上「小货车每单 ¥22」与「还没勾价目」看着像自相矛盾，其实是两笔钱：
            // 上面那笔是**给司机的工资**，货主付的**运费**要按「价目」算。把两笔钱的关系
            // 明说出来，用户才知道"钱在哪一步卡住的"（E2E 走查 P19）。
            Spacer(Modifier.height(2.dp))
            Text(
                "「给司机的钱」是工资；运费按价目算，没勾价目运费就出不来（点「编辑」勾上）",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
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

/**
 * 新建 / 编辑计费规则 = **同屏整页**（用户看到的东西与「新增商品」那种单独一页一模一样）。
 *
 * ### 为什么不弹窗（2026-10-05 · CHG-0022）
 * 规范 `docs/PROJECT_MAP/06_DESIGN_SYSTEM.md:762-763`：「**表单带选择器时用单独一页**，
 * 不要塞进 `AlertDialog`：全屏选品层套在弹窗里就是两层 modal 窗口叠着，而且字段一多弹窗会顶到
 * 屏幕边」（:765 明说这条不限于记账）。这份表单两条都踩：字段十来个（按分类定价时每类再加两行），
 * 并且里面能开「用哪些运费价目」那个整层选择器 —— 原来是「弹窗里再弹一个全屏层」。
 *
 * ### 为什么是「同屏第二层」而不是开新路由
 * 后端没有「按编号取一条规则」的接口（`api/v1/driver_billing_rules.py` 只有整表与增删改），
 * 开新路由就得在新页面里拉全表再按编号找；而且 `appViewModel` 按 `NavBackStackEntry` 作用域，
 * 列表页那份草稿态搬不过去。先例是地址与联系人页的「管理分类」（`CategoryManagePanel`）——
 * 用户看到的东西与真路由**完全一样**：整屏表单 + 顶部返回 + 底部保存栏 + 返回键先关表单。
 *
 * ### 每一格都走共用行
 * 分组用 `FormGroup`（组标题在卡外）、格用 `FormInputRow` / `FormPickRow` / `FormTextAreaRow`
 * （规范 §5.0「分组一律白卡」，判据 `_tools/qa/_check_form_panel_style.py`）。
 * 四处「少量互斥选项」仍然是 `SegmentedPicker`：它天然满宽等宽，塞进 `FormRow` 右侧那半栏会挤，
 * 所以按 `AiSettingsScreen` 那块「标签在上、选择器在下」的形态放进卡里（见 [PickerBlock]）。
 */
@Composable
private fun RuleFormBody(vm: DriverBillingRulesViewModel, pad: PaddingValues) {
    Column(
        Modifier
            .fillMaxSize()
            .padding(pad)
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 16.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        // ---- 这条规则叫什么、挂给谁 ----
        FormGroup(icon = Icons.Default.Badge, title = "这条规则叫什么", tint = Color(ShipperTeal)) {
            FormInputRow(
                label = "规则名称",
                value = vm.draftName,
                onValueChange = { vm.draftName = it },
                placeholder = "如：挂车计件 / 小型车月薪+提成",
                required = true,
                icon = Icons.Default.Badge,
                iconTint = Color(ShipperTeal),
            )
            PickerBlock(label = "适用车型", icon = Icons.Default.DirectionsCar, iconTint = Color(OriginTeal)) {
                SegmentedPicker(
                    labels = VEHICLE_OPTIONS.map { it.second },
                    selected = indexOfValue(VEHICLE_OPTIONS, vm.draftVehicle),
                    onSelect = { vm.draftVehicle = VEHICLE_OPTIONS[it].first },
                    fontSize = 14.sp,
                    height = 38.dp,
                )
            }
            Hint(
                "选了车型 = 这份规则只能挂给那种车的司机（挂错了后端会拦）",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }

        // ---- 三件钱：固定工资 / 每单多少钱 / 提成 ----
        FormGroup(icon = Icons.Default.Payments, title = "钱怎么算", tint = Color(MoneyOrange)) {
            FormInputRow(
                label = "固定工资",
                value = vm.draftSalary,
                // 金额规则唯一实现在 core/InputRules.kt（只数字 + 至多一个小数点 + 两位小数）。
                // 这几个框原来什么过滤都没有，键盘还是 Number（没有小数点）。
                onValueChange = { vm.draftSalary = InputRules.moneyInput(it) },
                placeholder = "元/月，留空 = 0",
                keyboardType = KeyboardType.Decimal,
                icon = Icons.Default.Payments,
                iconTint = Color(MoneyOrange),
            )
            // 每单金额怎么定（用户 2026-09-21：「按单计费有两种规则」）
            PickerBlock(label = "每单金额怎么定", icon = Icons.Default.CurrencyYuan, iconTint = Color(MoneyOrange)) {
                SegmentedPicker(
                    labels = PIECE_MODE_OPTIONS.map { it.second },
                    selected = indexOfValue(PIECE_MODE_OPTIONS, vm.draftPieceMode),
                    onSelect = { vm.draftPieceMode = PIECE_MODE_OPTIONS[it].first },
                    fontSize = 14.sp,
                    height = 38.dp,
                )
            }
            if (vm.draftPieceMode == "uniform") {
                FormInputRow(
                    label = "每单金额",
                    value = vm.draftPieceAmount,
                    onValueChange = { vm.draftPieceAmount = InputRules.moneyInput(it) },
                    placeholder = "元，留空 = 0",
                    keyboardType = KeyboardType.Decimal,
                    icon = Icons.Default.CurrencyYuan,
                    iconTint = Color(MoneyOrange),
                )
            } else {
                // 按分类定价：一类两行（每单金额 / 提成），空着的那一类 = 不定价
                Text(
                    "逐类填：哪一类货每单给多少、抽多少。没填的那些类，这一单就没有这份钱 —— " +
                        "（这一单属于哪一类，由派单时匹配到的运价带过来）",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                if (vm.categories.isEmpty()) {
                    Text(
                        "还没有运费分类 —— 先到「运费模板 → 分类管理」建几个",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.error,
                    )
                }
                vm.categories.forEach { c ->
                    val row = vm.draftCategoryRows[c.id] ?: ("" to "")
                    FormInputRow(
                        label = c.name + " · 每单金额",
                        value = row.first,
                        onValueChange = { vm.setCategoryRow(c.id, piece = InputRules.moneyInput(it), rate = null) },
                        placeholder = "每单 ¥",
                        keyboardType = KeyboardType.Decimal,
                        icon = Icons.Default.CurrencyYuan,
                        iconTint = Color(MoneyOrange),
                    )
                    FormInputRow(
                        label = c.name + " · 提成",
                        value = row.second,
                        onValueChange = {
                            vm.setCategoryRow(
                                c.id,
                                piece = null,
                                rate = InputRules.moneyInput(it, maxDecimals = 2, maxWhole = 3),
                            )
                        },
                        placeholder = "提成 %",
                        keyboardType = KeyboardType.Decimal,
                        icon = Icons.Default.PriceChange,
                        iconTint = Color(MoneyOrange),
                    )
                }
            }
            PickerBlock(label = "计价单位", icon = Icons.Default.Straighten, iconTint = Color(OriginTeal)) {
                SegmentedPicker(
                    labels = PIECE_UNIT_OPTIONS.map { it.second },
                    selected = indexOfValue(PIECE_UNIT_OPTIONS, vm.draftPieceUnit),
                    onSelect = { vm.draftPieceUnit = PIECE_UNIT_OPTIONS[it].first },
                    fontSize = 14.sp,
                    height = 38.dp,
                )
            }
        }

        FormGroup(icon = Icons.Default.PriceChange, title = "提成", tint = MaterialTheme.colorScheme.tertiary) {
            PickerBlock(
                label = "按什么提成",
                icon = Icons.Default.PriceChange,
                iconTint = MaterialTheme.colorScheme.tertiary,
            ) {
                SegmentedPicker(
                    labels = COMMISSION_OPTIONS.map { it.second },
                    selected = indexOfValue(COMMISSION_OPTIONS, vm.draftCommissionBase),
                    onSelect = { vm.draftCommissionBase = COMMISSION_OPTIONS[it].first },
                    fontSize = 14.sp,
                    height = 38.dp,
                )
            }
            FormInputRow(
                label = "提成比例",
                value = vm.draftCommissionRate,
                onValueChange = {
                    vm.draftCommissionRate = InputRules.moneyInput(it, maxDecimals = 2, maxWhole = 3)
                },
                placeholder = "%，如 5 表示 5%",
                enabled = vm.draftCommissionBase != "none",
                keyboardType = KeyboardType.Decimal,
                icon = Icons.Default.PriceChange,
                iconTint = MaterialTheme.colorScheme.tertiary,
            )
            // 抽成范围：只有「按商品金额抽成」才有这回事（按运费抽成时后端会拒这个组合）。
            if (vm.draftCommissionBase == "goods") {
                PickerBlock(
                    label = "只对哪些商品抽成",
                    icon = Icons.Default.ShoppingCart,
                    iconTint = Color(ProductPurple),
                ) {
                    // 勾选区是一整排会换行的 FilterChip，塞不进 FormRow 右侧那半栏 ——
                    // 所以这一块自己排（同卡里放自定义内容的先例：地址页的图片条 + 备注同卡）。
                    Column(Modifier.fillMaxWidth()) {
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
                }
            }
        }

        // ---- 价目归规则（用户 2026-09-21：「规则也就是取运费模板吧，也就是价目……勾选的时候
        //      就像一个商品界面，可以全选本分类，也可以单独勾」）----
        FormGroup(icon = Icons.Default.Route, title = "用哪些运费价目", tint = Color(DestOrange)) {
            FormPickRow(
                label = "价目",
                value = if (vm.draftTemplateIds.isEmpty()) "" else "已勾 " + vm.draftTemplateIds.size + " 条",
                onClick = { vm.showTemplatePicker = true },
                placeholder = "还没勾",
                icon = Icons.Default.Route,
                iconTint = Color(DestOrange),
            )
            Text(
                if (vm.draftTemplateIds.isEmpty()) {
                    "还没勾 —— 派单时这个司机的单会进「待定价」（点上面这一行去勾）"
                } else {
                    "派单选了他，就从这几条价目里按「路线 + 分类」带价"
                },
                style = MaterialTheme.typography.bodySmall,
                color = if (vm.draftTemplateIds.isEmpty()) {
                    MaterialTheme.colorScheme.error
                } else {
                    MaterialTheme.colorScheme.onSurfaceVariant
                },
            )
        }

        FormGroup(icon = Icons.Default.Notes, title = "备注", tint = MaterialTheme.colorScheme.outline) {
            FormTextAreaRow(
                label = "备注",
                value = vm.draftRemark,
                onValueChange = { vm.draftRemark = it },
                placeholder = "选填：给同事看的一句话",
                minLines = 2,
                icon = Icons.Default.Notes,
                iconTint = MaterialTheme.colorScheme.outline,
            )
        }
        Spacer(Modifier.height(4.dp))
    }
}

/**
 * 「标签 + 一整排选择器」那一块。
 *
 * ⚠️ 为什么不把它做成 [FormRow]：`SegmentedPicker` 天生 `fillMaxWidth` + 每段 `weight(1f)`，
 * 而 `FormRow` 把内容放在右侧那半栏里 —— 四段挤在半栏里会一字一行。
 * 所以形态是「标签在上、选择器在下」（先例 `ui/ai/AiSettingsScreen.kt` 的「思考强度」那块），
 * 图标与语义色照旧不省（`FormRows.kt` 顶部那条规矩）。
 */
@Composable
private fun PickerBlock(
    label: String,
    icon: ImageVector,
    iconTint: Color,
    content: @Composable () -> Unit,
) {
    Column(Modifier.fillMaxWidth().padding(top = 4.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Icon(icon, contentDescription = null, tint = iconTint, modifier = Modifier.size(16.dp))
            Spacer(Modifier.width(6.dp))
            Text(
                label,
                style = MaterialTheme.typography.bodyLarge,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        Spacer(Modifier.height(8.dp))
        content()
    }
}

/**
 * 底部那条保存栏。**常驻**（不跟着内容滚）：
 * 表单很长，错误行要是滚到底才看得见，等于没有 —— 见 `FormErrorLine` 的 KDoc
 * （「表单的错误必须和表单同生共死 —— 画在表单里、打开表单时清掉」）。
 */
@Composable
private fun RuleFormBottomBar(vm: DriverBillingRulesViewModel) {
    Surface(shadowElevation = 8.dp) {
        Column(
            Modifier
                .fillMaxWidth()
                .navigationBarsPadding()
                .padding(horizontal = 16.dp, vertical = 12.dp),
        ) {
            FormErrorLine(vm.formError)
            Spacer(Modifier.height(2.dp))
            Button(
                onClick = { vm.save() },
                enabled = !vm.acting,
                modifier = Modifier.fillMaxWidth().height(52.dp),
                shape = MaterialTheme.shapes.medium,
                colors = ButtonDefaults.buttonColors(containerColor = Color(MoneyOrange)),
            ) {
                Text(
                    if (vm.acting) "保存中…" else "保存",
                    style = MaterialTheme.typography.titleSmall,
                    fontWeight = FontWeight.Bold,
                )
            }
        }
    }
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
                                    color = Color(0xFFBC7730),
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
