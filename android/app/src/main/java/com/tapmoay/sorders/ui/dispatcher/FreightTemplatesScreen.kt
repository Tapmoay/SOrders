package com.tapmoay.sorders.ui.dispatcher

import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.DeleteOutline
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.LocalShipping
import androidx.compose.material.icons.filled.PriceChange
import androidx.compose.material.icons.filled.Tune
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.core.InputRules
import com.tapmoay.sorders.ui.common.*
import com.tapmoay.sorders.ui.theme.ProductPurple
import com.tapmoay.sorders.util.formatMoney

/**
 * 运费模板（派单员）—— **按路线定价的一本价目表**，2026-09-21 改版。
 *
 * ## 用户这一轮要的三件事
 * 1. 「这个运费模板，我们也可以按商品做一个相应的分类，也可以**创建分类进行管理**」
 *    → 左边是**分类栏**（名册可维护，见「分类管理」），一条价目可以挂**多个**分类；
 * 2. 「运费管理它会是有一个**拉取地点库里的路线**，按照地点库的路线进行定价」
 *    → 表单里的起点/终点不再是两段手打文字，而是**选一条线路**（「地址与联系人 → 常用线路」）；
 * 3. 「运费模板的卡片也做得美观一点，**重要信息主要做得明确一点**」
 *    → 卡片从上到下：`分类标签 + 车型` → **起点 → 终点（大字）** → `价目名` → **价格（大字橙色）**
 *      → `可用司机 / 备注`。同一屏里**价格与路线是最大的两块**，其余降级成小字。
 *
 * ⛔ 这一页**只管价目**：匹配与"没匹配到怎么办"在 `services/freight_pricing.py` 与
 *    「待定价」那一页（派单员手动定价）。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun FreightTemplatesScreen(
    container: AppContainer,
    onBack: () -> Unit,
    onManageCategories: () -> Unit = {},
    /** 「待定价」那些单（已派单、没运费）—— 派单员手动定价的那一页。 */
    onOpenUnpriced: () -> Unit = {},
) {
    val vm: FreightTemplatesViewModel = appViewModel { FreightTemplatesViewModel(container) }
    val snackbar = remember { SnackbarHostState() }
    OneShotSnackbar(snackbar, vm.actionResult, onConsumed = { vm.actionResult = null })
    OneShotSnackbar(snackbar, vm.error, onConsumed = { vm.error = null })

    Scaffold(
        snackbarHost = { SnackbarHost(snackbar) },
        topBar = {
            AppTopBar(
                title = "运费模板",
                onBack = onBack,
                actions = {
                    TextButton(onClick = onOpenUnpriced) {
                        Icon(Icons.Default.PriceChange, null, Modifier.size(18.dp))
                        Spacer(Modifier.width(4.dp))
                        Text("待定价")
                    }
                    TextButton(onClick = onManageCategories) {
                        Icon(Icons.Default.Tune, null, Modifier.size(18.dp))
                        Spacer(Modifier.width(4.dp))
                        Text("分类管理")
                    }
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
            if (vm.templates.isEmpty() && !vm.loading) {
                Column(
                    Modifier.fillMaxSize(),
                    verticalArrangement = Arrangement.Center,
                    horizontalAlignment = Alignment.CenterHorizontally,
                ) {
                    Text("还没有运费价目", style = MaterialTheme.typography.titleMedium)
                    Spacer(Modifier.height(6.dp))
                    Text(
                        "一条价目 = 一条线路 + 一车价（可以挂多个分类）。派单时按「线路 + 分类 + 司机」自动带价；" +
                            "没匹配到的单会进「待定价」，由派单员手动定价。",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.padding(horizontal = 32.dp),
                    )
                    Spacer(Modifier.height(16.dp))
                    Button(onClick = { vm.openCreate() }) { Text("创建第一条价目") }
                }
                return@Column
            }
            Row(Modifier.weight(1f)) {
                // 左：分类栏（共用那一份实现：与商品/库存/开销同一个观感）
                CategoryRail(
                    tabs = vm.tabs(),
                    selected = vm.tab,
                    onSelect = { vm.tab = it },
                    modifier = Modifier.width(96.dp).fillMaxHeight(),
                )
                val list = vm.visible()
                if (list.isEmpty()) {
                    Box(Modifier.weight(1f).fillMaxHeight()) {
                        EmptyView(
                            if (vm.tab == "全部") "还没有运费价目" else "这一类下还没有价目",
                            Modifier.align(Alignment.TopCenter).padding(top = 60.dp),
                        )
                    }
                } else {
                    LazyColumn(
                        Modifier.weight(1f).fillMaxHeight(),
                        contentPadding = PaddingValues(start = 12.dp, end = 12.dp, top = 4.dp, bottom = 16.dp),
                        verticalArrangement = Arrangement.spacedBy(10.dp),
                    ) {
                        items(list, key = { it.id }) { t ->
                            FreightTemplateCard(
                                vm = vm,
                                t = t,
                                onEdit = { vm.openEdit(t) },
                                onDelete = { vm.requestDelete(t) },
                            )
                        }
                    }
                }
            }
        }
    }

    if (vm.showDialog) {
        FreightTemplateDialog(vm)
    }

    vm.deleteTarget?.let { t ->
        DangerConfirmDialog(
            title = "删除价目「" + t.name + "」？",
            message = "删掉之后派单时匹配不到这条价目（已经派出去的单不受影响，它们记的是当时的快照）。",
            confirmText = "删除",
            onConfirm = { vm.confirmDelete() },
            onDismiss = { vm.deleteTarget = null },
        )
    }
}

/**
 * 一张价目卡：**路线与价格最大**，其余降级成小字。
 *
 * 用户 2026-09-21：「运费模板的卡片也做得美观一点，**重要信息主要做得明确一点**」——
 * 所以这里刻意不把"分类 / 车型 / 司机 / 备注"揉成一行小字：分类用色块（一眼看出这类货怎么走）、
 * 路线与价格各占一行大字、司机与备注在小字行里。
 */
@Composable
private fun FreightTemplateCard(
    vm: FreightTemplatesViewModel,
    t: com.tapmoay.sorders.data.remote.dto.FreightTemplateDto,
    onEdit: () -> Unit,
    onDelete: () -> Unit,
) {
    SectionCard {
        // ① 分类标签 + 车型徽章（这一条价目算哪几类货）
        Row(verticalAlignment = Alignment.CenterVertically) {
            if (t.categoryNames.isEmpty()) {
                TagChip("未分类", Color(0xFF8A8A8E))
            } else {
                Row(Modifier.weight(1f).horizontalScroll(rememberScrollState())) {
                    t.categoryNames.forEach { name ->
                        TagChip(name, Color(ProductPurple))
                        Spacer(Modifier.width(6.dp))
                    }
                }
            }
            Spacer(Modifier.weight(1f))
            // 价目**不匹配车型也不匹配司机**（2026-09-21 用户）——这里只写"它被哪几份规则用着"
            Text(
                if (t.ruleNames.isEmpty()) "还没被任何规则勾" else "${t.ruleNames.size} 份规则在用",
                style = MaterialTheme.typography.labelMedium,
                color = if (t.ruleNames.isEmpty()) MaterialTheme.colorScheme.error
                else MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        Spacer(Modifier.height(8.dp))
        // ② 路线（大字）+ 价格（大字橙色）—— 卡片上最该看清的两件事
        Row(verticalAlignment = Alignment.CenterVertically) {
            TintedIcon(Icons.Default.LocalShipping, Color(0xFF283593), size = 18.dp, container = 36.dp)
            Spacer(Modifier.width(10.dp))
            Column(Modifier.weight(1f)) {
                Text(
                    vm.routeLabelOf(t),
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.Bold,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                )
                Text(
                    if (t.priceName.isBlank()) t.name else t.name + " · " + t.priceName,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 1,
                )
            }
            Spacer(Modifier.width(10.dp))
            Text(
                "¥" + formatMoney(t.fee),
                style = MaterialTheme.typography.titleLarge,
                fontWeight = FontWeight.Bold,
                color = Color(0xFFFF9500),
            )
        }
        Spacer(Modifier.height(8.dp))
        // ③ 归哪几份规则用（价目归规则）+ 备注；**右侧**是操作按钮。
        //    用户 2026-09-21 第二轮修正：「编辑和删除移到最右边去……卡片高度变窄一点」——
        //    按钮不再单独占一行，信息吃掉剩余宽度（`weight(1f)`），卡片因此矮一行。
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text(
                    if (t.ruleNames.isEmpty()) "还没有规则勾它 —— 到「计费规则」里勾上，派单才会用它带价"
                    else "用在：" + t.ruleNames.joinToString("、"),
                    style = MaterialTheme.typography.bodySmall,
                    color = if (t.ruleNames.isEmpty()) MaterialTheme.colorScheme.error
                    else MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
                if (t.remark.isNotBlank()) {
                    Text(
                        t.remark,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.outline,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                }
            }
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

/** 小色块标签（分类名之类）。 */
@Composable
private fun TagChip(text: String, color: Color) {
    Surface(color = color.copy(alpha = 0.12f), shape = MaterialTheme.shapes.small) {
        Text(
            text,
            style = MaterialTheme.typography.labelMedium,
            color = color,
            modifier = Modifier.padding(horizontal = 8.dp, vertical = 3.dp),
        )
    }
}

/** 新建 / 编辑一张价目。 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun FreightTemplateDialog(vm: FreightTemplatesViewModel) {
    var routeExpanded by remember { mutableStateOf(false) }
    val pickedRoute = vm.routes.firstOrNull { it.id == vm.draftRouteId }
    AlertDialog(
        onDismissRequest = { if (!vm.acting) vm.showDialog = false },
        title = { Text(if (vm.editing == null) "新建价目" else "编辑价目") },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState())) {
                // ① 线路：**从线路库选**（价目是按路线定价的）
                ExposedDropdownMenuBox(expanded = routeExpanded, onExpandedChange = { routeExpanded = it }) {
                    OutlinedTextField(
                        value = pickedRoute?.let { vm.routeLabel(it) }
                            ?: (vm.editing?.let { vm.routeLabelOf(it) } ?: "请选择线路"),
                        onValueChange = {},
                        readOnly = true,
                        label = { Text("线路（起点 → 终点）") },
                        trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(expanded = routeExpanded) },
                        modifier = Modifier.fillMaxWidth().menuAnchor(),
                    )
                    ExposedDropdownMenu(expanded = routeExpanded, onDismissRequest = { routeExpanded = false }) {
                        if (vm.routes.isEmpty()) {
                            DropdownMenuItem(
                                text = { Text("线路库是空的 —— 先去「地址与联系人」建一条常用线路") },
                                onClick = { routeExpanded = false },
                            )
                        }
                        vm.routes.forEach { a ->
                            DropdownMenuItem(
                                text = { Text(vm.routeLabel(a), maxLines = 1, overflow = TextOverflow.Ellipsis) },
                                onClick = { vm.draftRouteId = a.id; routeExpanded = false },
                            )
                        }
                    }
                }
                Spacer(Modifier.height(8.dp))
                SoTextField(vm.draftName, { vm.draftName = it }, placeholder = "价目名称（如：蔬菜 城南→城北）")
                Spacer(Modifier.height(8.dp))
                Row {
                    SoTextField(
                        vm.draftFee,
                        { vm.draftFee = InputRules.moneyInput(it) },
                        Modifier.weight(1f),
                        placeholder = "一车价格 ¥",
                        keyboardType = KeyboardType.Decimal,
                    )
                    Spacer(Modifier.width(8.dp))
                    SoTextField(vm.draftPriceName, { vm.draftPriceName = it }, Modifier.weight(1f), placeholder = "价目名（如 小车价）")
                }
                Spacer(Modifier.height(10.dp))
                // ② 这条价目算哪几类货（可多选）
                Text("算哪几类货（可多选；不选 = 派单时只能手动挑它）", style = MaterialTheme.typography.labelMedium)
                Spacer(Modifier.height(4.dp))
                if (vm.categories.isEmpty()) {
                    Text(
                        "还没有运费分类 —— 点右上角「分类管理」建几个（如 蔬菜 / 水果 / 冻品）",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                } else {
                    MultiChipRow(
                        options = vm.categories.map { it.id to it.name },
                        selected = vm.draftCategoryIds,
                        onToggle = { vm.toggleCategory(it) },
                    )
                }
                // ⛔ 这里**没有**「适用车型」与「可用司机」（2026-09-21 用户）：
                //    「运费模板不会去匹配车型也不会匹配司机，匹配车型和匹配司机在**计费规则**中……
                //      这一目录就归这个计费规则」。所以价目只管"这条路线上这一类货多少钱"，
                //    谁来用它由「计费规则」勾选决定。
                Text(
                    "这条价目归「计费规则」勾选使用 —— 车型与司机在计费规则里匹配，不在这里。",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.fillMaxWidth(),
                )
                Spacer(Modifier.height(8.dp))
                SoTextField(vm.draftRemark, { vm.draftRemark = it }, Modifier.fillMaxWidth(), placeholder = "备注（选填）")
            }
        },
        confirmButton = { TextButton(onClick = { vm.save() }, enabled = !vm.acting) { Text("保存") } },
        dismissButton = { TextButton(onClick = { vm.showDialog = false }, enabled = !vm.acting) { Text("取消") } },
    )
}

/** 可多选的小色块（分类 / 司机共用一份：形态一样、语义一样）。 */
@Composable
private fun MultiChipRow(
    options: List<Pair<Long, String>>,
    selected: Set<Long>,
    onToggle: (Long) -> Unit,
) {
    Column {
        options.chunked(3).forEach { row ->
            Row(Modifier.padding(bottom = 6.dp)) {
                row.forEach { (id, label) ->
                    val sel = id in selected
                    Surface(
                        color = if (sel) Color(ProductPurple).copy(alpha = 0.16f) else MaterialTheme.colorScheme.surfaceVariant,
                        shape = MaterialTheme.shapes.small,
                        modifier = Modifier.padding(end = 6.dp).clickable { onToggle(id) },
                    ) {
                        Text(
                            label,
                            style = MaterialTheme.typography.labelLarge,
                            color = if (sel) Color(ProductPurple) else MaterialTheme.colorScheme.onSurfaceVariant,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                            modifier = Modifier.padding(horizontal = 10.dp, vertical = 6.dp),
                        )
                    }
                }
            }
        }
    }
}
