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
import androidx.compose.material.icons.filled.Notes
import androidx.compose.material.icons.filled.PriceChange
import androidx.compose.material.icons.filled.Tune
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.core.InputRules
import com.tapmoay.sorders.ui.common.*
import com.tapmoay.sorders.ui.theme.ProductPurple
import com.tapmoay.sorders.util.formatMoney
import com.tapmoay.sorders.ui.common.Hint

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
        // 顶栏只留标题与返回：**三个动作全部搬到底栏那条三格里**
        // （用户 2026-09-22：「右上角不是有 3 个…挪到底部做成三格，照抄商品管理」）。
        topBar = {
            AppTopBar(
                title = "运费模板",
                onBack = onBack,
            )
        },
        // 底栏三格：左「分类管理」· 中「新建价目」语义色圆钮 · 右「待定价」
        bottomBar = {
            FreightBottomBar(
                onCategories = onManageCategories,
                onAdd = { vm.openCreate() },
                onUnpriced = onOpenUnpriced,
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

    // 新建 / 编辑一条价目：**底部抽屉**（用户 2026-09-22：「他不要使用弹窗啊，使用底部抽屉，
    // 并且底部抽屉是**拉到最上面**」）。
    // ⛔ 底色不在这里定：全 App 19 个抽屉一处说了算（`Theme::surfaceContainerLow = SheetSurface`），
    //    在这一页传一个自己的 containerColor 就是"每个抽屉各说各的"的起点。
    if (vm.showSheet) {
        ModalBottomSheet(
            onDismissRequest = { if (!vm.acting) vm.showSheet = false },
            sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true),
        ) {
            FreightTemplateSheet(vm)
        }
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
 * 运费模板的**底部三格**：左「分类管理」· 中「新建价目」（语义色圆钮）· 右「待定价」。
 *
 * ## 为什么从右上角搬到底部（用户 2026-09-22）
 * 他圈着右上角那三个（待定价 / 分类管理 / 新建）说「**你这个没改啊**」，选的做法是
 * 「**挪到底部做成三格，照抄商品管理**」（`ProductsScreen.kt::ProductsBottomBar`，2026-09-19 定）。
 * 那一条栏的道理同样适用：三个动作挤在右上一个角、视线要跑一趟，
 * 而**主操作居中**是拇指最容易够到的位置。
 *
 * ⛔ 左右两格是**无边框的「图标 + 文字」**，不是描边按钮 —— 参考图那一栏就是这么分主次的，
 *    摆三个描边按钮会变成"三个并排的框"（商品管理那一轮已经否掉过一次）。
 * ⛔ 颜色用**运费模板的语义色深靛** `0xFF283593`（一色一功能：工作台那一格、卡片上的车图标同色）。
 *    不要用钱的橙：同屏每张卡上的价格已经是橙的。
 *
 * ⚠️ **这是同一套形态的第二处**（第一处是商品管理）。若第三页也要，就把它提成共用件
 * （`ui/common/`）—— 与 `FormRows.kt::FormGroup` 那次的处理一样；那时两处一起换。
 */
@Composable
private fun FreightBottomBar(
    onCategories: () -> Unit,
    onAdd: () -> Unit,
    onUnpriced: () -> Unit,
) {
    val accent = Color(0xFF283593)
    Surface(shadowElevation = 8.dp) {
        Row(
            Modifier
                .fillMaxWidth()
                // 底部系统导航条留白：这一栏不是 M3 的 NavigationBar，不会自己处理 insets
                .navigationBarsPadding()
                .padding(horizontal = 8.dp, vertical = 6.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            FreightBottomCell(Icons.Default.Tune, "分类管理", onCategories, Modifier.weight(1f))
            // 中间：语义色圆钮 + 文字（主操作居中）
            Column(
                Modifier.weight(1f).clickable(onClick = onAdd).padding(vertical = 4.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                FilledIconButton(
                    onClick = onAdd,
                    modifier = Modifier.size(52.dp),
                    colors = IconButtonDefaults.filledIconButtonColors(
                        containerColor = accent,
                        contentColor = Color.White,
                    ),
                ) {
                    Icon(Icons.Default.Add, contentDescription = "新建价目", modifier = Modifier.size(26.dp))
                }
                Spacer(Modifier.height(2.dp))
                Text(
                    "新建价目",
                    style = MaterialTheme.typography.labelMedium,
                    fontWeight = FontWeight.Bold,
                    color = accent,
                )
            }
            FreightBottomCell(Icons.Default.PriceChange, "待定价", onUnpriced, Modifier.weight(1f))
        }
    }
}

/** 底栏左右那两格：图标 + 文字，**没有边框**（与商品管理那一栏同一个形态）。 */
@Composable
private fun FreightBottomCell(
    icon: ImageVector,
    label: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Column(
        modifier.clickable(onClick = onClick).padding(vertical = 2.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Icon(
            icon,
            contentDescription = null,
            tint = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.size(22.dp),
        )
        Spacer(Modifier.height(2.dp))
        Text(
            label,
            style = MaterialTheme.typography.labelMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
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
        // ② 路线（**A → B 轨道**）+ 价格（大字橙色）—— 卡片上最该看清的两件事
        //
        // ⚠️ 2026-09-22 用户第三次改这一块：「那个**运费模板**…也要**参考我们那个路线的选择**。
        //    如果他是路线的话，就要参考我们路线的形式，比如**起点到终点**，
        //    那个**图标可以去掉**…比如说**车的图标可以去掉**啊，**卡片形式要改一下**」。
        // 所以：① 那辆卡车（`LocalShipping`）的圈底图标拿掉了 —— 它只重复了"这是一条线路"，
        //        而"从哪到哪"由下面那根轨道自己说清楚；
        //      ② 路线改用**全库共用**的 `RouteRail`（与常用线路卡、地址库、订单详情同一份）：
        //        圆点—竖线—定位针，起点在上、终点在下。
        Row(verticalAlignment = Alignment.Top) {
            Column(Modifier.weight(1f)) {
                RouteRail(origin = t.fromPlace, dest = t.toPlace)
                Spacer(Modifier.height(4.dp))
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
        //    ⚠️ 2026-09-22 顺序调了一次（用户当天定的规范）：**左＝反向/警示、右＝编辑** ——
        //    「编辑一定在右边…相反的操作，就在左边」（设计系统 §4.2c）。
        //    所以这一行是「删除 · 编辑」而不是原来的「编辑 · 删除」。
        //    ⚠️ 这两个还是 `TextButton`（图标+文字），不是规范里那种"圈底图标"——
        //    要不要一起换成 `CardActionIcon(label = …)` 等用户点头（那是外观改动，他没指着这一页说过）。
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
            TextButton(
                onClick = onDelete,
                colors = ButtonDefaults.textButtonColors(contentColor = MaterialTheme.colorScheme.error),
            ) {
                Icon(Icons.Default.DeleteOutline, null, Modifier.size(18.dp))
                Spacer(Modifier.width(2.dp))
                Text("删除")
            }
            TextButton(onClick = onEdit) {
                Icon(Icons.Default.Edit, null, Modifier.size(18.dp))
                Spacer(Modifier.width(2.dp))
                Text("编辑")
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

/**
 * 新建 / 编辑一条价目 —— **底部抽屉**（2026-09-22 改）。
 *
 * ## 为什么从弹窗换成抽屉（用户原话）
 * 「**新增模板也按照我们的样式**进行来，但是他**不要使用弹窗**啊，**使用底部抽屉**，
 *  并且**底部抽屉是拉到最上面**。」
 *
 * 这一页的表单是「一条线路 + 一车价 + 几个分类 + 备注」，塞进居中弹窗只能给一个小框、
 * 还得在框里滚；抽屉是**拉满到最上面**的（`fillMaxHeight()` ＋ `skipPartiallyExpanded`），
 * 一次看全，键盘弹起来也不挤。
 *
 * ## 形态（规范：设计系统 §5.0「分组一律白卡」）
 * 三张白卡（`FormGroup`：**卡外**一行小字组标题 + `SectionCard`），卡里**一个描边输入框都没有** ——
 * 全是 `ui/common/FormRows.kt` 的无边框行（"值即占位符"）。
 *
 * ⛔ **分类是多选**（用户 2026-09-21：「一个模板可以有多个分类」），所以这里是**填充色块** chips、
 *    不是下拉：下拉是单选的形态，"选了三个"用下拉表达不了。它与被否掉的那种描边 `FilterChip`
 *    不是一回事 —— 色块没有边。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun FreightTemplateSheet(vm: FreightTemplatesViewModel) {
    var routeExpanded by remember { mutableStateOf(false) }
    val isEdit = vm.editing != null
    // 选中的线路：先看这次选的；编辑既有价目时草稿里存的就是它自己那条
    val routeText = vm.routes.firstOrNull { it.id == vm.draftRouteId }?.let { vm.routeLabel(it) }
        ?: if (vm.draftRouteId != null) vm.editing?.let { vm.routeLabelOf(it) }.orEmpty() else ""

    Column(
        Modifier
            .fillMaxWidth()
            // 「拉到最上面」：一打开就占满可用高度（不是半截），内容在这块里滚
            .fillMaxHeight()
            .padding(horizontal = 16.dp)
            .imePadding()
            .verticalScroll(rememberScrollState()),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        // 标题下面**直接进白卡**（与「新增地点」那个抽屉同形）。
        // ⛔ 这里刻意**没有**再加一句"一条价目 = 线路 + 一车价"的说明：
        //    ① 它与下面「算哪几类货」卡里那句（归计费规则勾选使用）说的是同一件事；
        //    ② 那句话里带「一车价」，会被 `_hint_inventory` 的分类器判成 DATA（带单位词），
        //       而 DATA 是**永不隐藏**的那一类 —— 写成 `Hint` 就会被红线判成"把数据藏进提示"，
        //       而分类器的 `OVERRIDE` 表**只许往"更不藏"的方向改**（不许把 DATA 改成 EXPLAIN）。
        //    少一句重复的解释，比给分类器开一个例外干净。
        Text(
            if (isEdit) "编辑价目" else "新建价目",
            style = MaterialTheme.typography.titleLarge,
            fontWeight = FontWeight.Bold,
        )

        // ---- 白卡 1：走哪条线、多少钱 ----
        FormGroup(
            icon = Icons.Default.LocalShipping,
            title = "线路与价格",
            tint = Color(0xFF283593),
        ) {
            // 线路：**从线路库选**（价目是按路线定价的）
            ExposedDropdownMenuBox(expanded = routeExpanded, onExpandedChange = { routeExpanded = it }) {
                FormPickRow(
                    label = "线路",
                    value = routeText,
                    placeholder = "从线路库选",
                    required = true,
                    onClick = { routeExpanded = true },
                    modifier = Modifier.menuAnchor(),
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
            FormInputRow(
                label = "价目名称",
                value = vm.draftName,
                onValueChange = { vm.draftName = it },
                placeholder = "如：蔬菜 城南 → 城北",
                required = true,
            )
            FormInputRow(
                label = "一车价格",
                value = vm.draftFee,
                // 金额过滤的唯一实现在 core/InputRules.kt（过滤写在调用点上，这样"这个框走的是哪条规则"
                // 在同一行就能看见，`_check_input_rules.py` 也是这么认的）
                onValueChange = { vm.draftFee = InputRules.moneyInput(it) },
                placeholder = "¥（选填，留空记 0）",
                keyboardType = KeyboardType.Decimal,
            )
            FormInputRow(
                label = "价目名",
                value = vm.draftPriceName,
                onValueChange = { vm.draftPriceName = it },
                placeholder = "如：小车价（选填）",
            )
        }

        // ---- 白卡 2：这条价目算哪几类货（可多选）----
        FormGroup(icon = Icons.Default.Tune, title = "算哪几类货", tint = Color(ProductPurple)) {
            if (vm.categories.isEmpty()) {
                // 空态指路句：**永远显示**（它不是解释句 —— 被提示总开关藏掉，这一格就成了空卡片）
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
        }
        // ⛔ 这里**没有**「适用车型」与「可用司机」（2026-09-21 用户）：
        //    「运费模板不会去匹配车型也不会匹配司机，匹配车型和匹配司机在**计费规则**中……
        //      这一目录就归这个计费规则」。所以价目只管"这条路线上这一类货多少钱"。
        Hint(
            "这条价目归「计费规则」勾选使用 —— 车型与司机在计费规则里匹配，不在这里。",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.fillMaxWidth(),
        )

        // ---- 白卡 3：备注 ----
        FormGroup(icon = Icons.Default.Notes, title = "备注", tint = MaterialTheme.colorScheme.outline) {
            FormInputRow(
                label = "备注",
                value = vm.draftRemark,
                onValueChange = { vm.draftRemark = it },
                placeholder = "选填",
            )
        }

        // 校验/保存失败的那句话画在**抽屉里面**（见 FormErrorLine 的注释：写进页面级错误
        // 会退化成"点保存没有任何反应" —— 那句话被抽屉盖住了，而抽屉本身就是另一个窗口）
        FormErrorLine(vm.formError)
        Spacer(Modifier.height(6.dp))
        Button(
            onClick = { vm.save() },
            enabled = !vm.acting,
            modifier = Modifier.fillMaxWidth().height(50.dp),
        ) {
            if (vm.acting) {
                CircularProgressIndicator(Modifier.size(22.dp), color = Color.White, strokeWidth = 2.dp)
            } else {
                Text("保存", style = MaterialTheme.typography.titleMedium)
            }
        }
        Spacer(Modifier.height(12.dp))
    }
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
