package com.tapmoay.sorders.ui.dispatcher

/**
 * **线路分类管理**（2026-10-04）。
 *
 * 用户 2026-10-04 原话：「**干脆给线路联系人以及地点，这3个的界面玩个框了框的位置加一个分类显示**…
 * 它就会弹出一个在左侧来…**可以去参考账本管理的那些代码**」。
 *
 * ## 为什么是"面板"而不是"一页"
 * 与 [PlaceCategoriesPanel] / [ContactCategoriesPanel] 同一条理由（用户 2026-09-19 在真机上抓到的）：
 * 「切换的时候突然会闪一下…要干脆就不要弹一个界面…**它 2 个抽屉**」。
 * 所以它是**同一个左侧抽屉里的第二层**：点抽屉最后一行「管理分类」→ 抽屉内容换成这一块 + 一个返回。
 * ⛔ 不要再给它新建一条路由，也不要为它再开一层抽屉。
 *
 * ## 与 [PlaceCategoriesPanel] 的关系
 * 同一套做法（名册管顺序、字符串管归属、改名级联、整份顺序提交幂等），差别只有级联目标：
 * 那边挂的是地点，这边挂的是线路 —— 所以条数文案是「N 条线路」。
 *
 * ## 排序（2026-10-06：按钮 → 拖动）
 * 用户原话：「它的排序**最好不要用那个按钮排序**，我们直接像**拖动卡片式**的排序」——
 * 上下箭头因此退役，改成**长按一行拖动**（手势 / 行高量尺 / 拖动换算照
 * `ui/dispatcher/ProductCategoriesScreen.kt` 那一份，换算函数 `dragSteps()` 与那一页共用）。
 * 左边的位次框留着：拖动与"直接填第几位"并存（与商品分类管理页一样）；提交的始终是**整份顺序**
 * （后端 /reorder 要整份）。
 *
 * ## 返回（2026-10-06）
 * 面板**自己不画返回**：`onBack` 由宿主点名才画。地址与联系人页的返回在**页面顶栏**——
 * 用户原话「虽然你在这里也有像什么搞了那个返回路线或者返回联系人，但这样子不好，互相容易误解」；
 * 下单页的地点抽屉没有顶栏，所以那一处仍然点名它。
 */

import androidx.compose.foundation.gestures.detectDragGesturesAfterLongPress
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.LocalHapticFeedback
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.tapmoay.sorders.data.remote.dto.RouteCategoryDto
import com.tapmoay.sorders.ui.common.*
import com.tapmoay.sorders.ui.theme.MessageRed
import com.tapmoay.sorders.ui.theme.OriginTeal
import com.tapmoay.sorders.ui.common.Hint

/**
 * 行高 = 位次框 52dp + 白卡上下各 16dp（[SectionCard] 的内边距）。
 *
 * 拖动换算（`dragSteps`）按它算，所以**不能自适应** —— 与商品分类管理页那个 68dp 同一个理由
 * （那边不用 SectionCard，所以那边是 68dp；两处数值不同、语义相同）。
 */
private val CATEGORY_ROW_HEIGHT = 84.dp

@Composable
fun RouteCategoriesPanel(
    vm: RouteCategoriesViewModel,
    onBack: (() -> Unit)? = null,
) {
    // 操作回执（台账 L-11，2026-10-06）：VM 里早就把「已新建分类：xxx」这类回执写好了
    // （`actionResult`），可这三档面板一次都没渲染过 —— 建了/改了/删了分类界面上一点回声
    // 都没有，用户只能自己猜到底成没成。这里照全 App 的同一套写法把它接上。
    val snackbar = remember { SnackbarHostState() }
    OneShotSnackbar(snackbar, vm.actionResult, onConsumed = { vm.actionResult = null })
    // Box 只当"托住提示条"的壳：它原样把父约束传给子 Column，面板内部布局一行都不动。
    Box(Modifier.fillMaxSize()) {
        RouteCategoriesBody(vm, onBack)
        SnackbarHost(snackbar, Modifier.align(Alignment.BottomCenter))
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun RouteCategoriesBody(
    vm: RouteCategoriesViewModel,
    /** 宿主给的"返回上一层"。本面板自己不画返回（见文件头 KDoc）：宿主没有顶栏时才会点它。 */
    onBack: (() -> Unit)?,
) {
    // 长按拖动三件套：状态住面板这一层（行零件只负责画与报位移），
    // 「拖了多少像素 = 几格」的换算走 ProductCategoriesViewModel.dragSteps 那一份。
    var draggingId by remember { mutableStateOf<Long?>(null) }
    var dragOffset by remember { mutableStateOf(0f) }
    val haptic = LocalHapticFeedback.current
    val rowHeightPx = with(LocalDensity.current) { CATEGORY_ROW_HEIGHT.toPx() }

    Column(Modifier.fillMaxWidth()) {
        Row(
            Modifier.fillMaxWidth().padding(horizontal = 20.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text("线路分类", style = MaterialTheme.typography.titleLarge, modifier = Modifier.weight(1f))
            // 顶栏已经有一颗返回时这里不再画第二颗（用户：「互相容易误解」）。
            if (onBack != null) {
                TextButton(onClick = onBack) {
                    Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = null, modifier = Modifier.size(18.dp))
                    Spacer(Modifier.width(4.dp))
                    Text("返回线路")
                }
            }
        }
        Row(
            Modifier.fillMaxWidth().padding(horizontal = 20.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            SoTextField(
                value = vm.draftName,
                onValueChange = { vm.draftName = it },
                placeholder = "新分类名（如：常送工地 / 城东片区）",
                modifier = Modifier.weight(1f),
            )
            Spacer(Modifier.width(8.dp))
            PrimaryActionButton(
                text = if (vm.acting) "…" else "新建",
                onClick = { vm.create() },
                enabled = !vm.acting && vm.draftName.isNotBlank(),
            )
        }
        Hint(
            "只影响你自己看到的分类，别人看不到；顺序就是左栏的顺序。长按一行可以拖动排序。",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.padding(horizontal = 20.dp),
        )
        Spacer(Modifier.height(8.dp))
        when {
            vm.loading && vm.rows.isEmpty() -> LoadingBox(Modifier.fillMaxWidth().height(160.dp))
            vm.loadError != null -> ErrorView(vm.loadError.orEmpty(), onRetry = { vm.load() })
            vm.rows.isEmpty() -> Text(
                "还没有分类。分类是可选的：不建分类，线路就是一份名单，照样能挑、能搜。",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(horizontal = 20.dp, vertical = 18.dp),
            )
            // ⚠️ 这里是 Column + verticalScroll，**不是** LazyColumn：拖动要靠"一行一个固定高度"
            //    来把位移换算成格数，LazyColumn 的 item 复用会让这个换算变成靠测量
            //    （与商品分类管理页同一个理由；代价是拖到边缘不会自动滚）。
            else -> Column(
                Modifier.fillMaxWidth()
                    .weight(1f, fill = false)
                    .heightIn(max = 460.dp)
                    .verticalScroll(rememberScrollState())
                    .padding(horizontal = 20.dp, vertical = 4.dp),
            ) {
                vm.rows.forEachIndexed { idx, c ->
                    // ⚠️ `key(c.id)` 不能省：被拖动那一行的 `pointerInput` 要跟着它自己的 id，
                    //    不给稳定 key 时节点会随位置重建 ⇒ 手势被取消（表现是"拖了半天只挪一格就自己松手"）。
                    key(c.id) {
                        RouteCategoryRow(
                            c = c,
                            // ⚠️ 显示的是**列表里的位次**（1 起），不是 `sort_order`：
                            //    后端新建时给的是 `max+1`（第一个是 1 不是 0），拿它 +1 会显示成 2。
                            position = idx + 1,
                            busy = vm.acting,
                            dragging = draggingId == c.id,
                            dragOffset = if (draggingId == c.id) dragOffset else 0f,
                            onDragStart = {
                                draggingId = c.id
                                dragOffset = 0f
                                haptic.performHapticFeedback(HapticFeedbackType.LongPress)
                            },
                            onDrag = { dy ->
                                dragOffset += dy
                                val steps = dragSteps(dragOffset, rowHeightPx)
                                if (steps != 0) {
                                    vm.moveBy(c.id, steps)
                                    dragOffset -= steps * rowHeightPx
                                }
                            },
                            onDragEnd = { draggingId = null; dragOffset = 0f },
                            onPosition = { pos -> vm.moveTo(c.id, pos) },
                            onRename = { vm.openRename(c) },
                            onDelete = { vm.deleting = c },
                        )
                    }
                    Spacer(Modifier.height(8.dp))
                }
            }
        }
        vm.error?.let {
            Text(
                it,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.error,
                modifier = Modifier.padding(horizontal = 20.dp, vertical = 6.dp),
            )
        }
    }

    vm.renaming?.let { target ->
        CardAlertDialog(
            onDismissRequest = { vm.renaming = null },
            title = { Text("重命名分类") },
            text = {
                Column {
                    SoTextField(vm.renameText, { vm.renameText = it }, placeholder = "分类名")
                    Spacer(Modifier.height(6.dp))
                    Text(
                        "改名会把挂在这个分类下的线路一起改过去（不会掉回未分类）。",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    if (target.addressCount > 0) {
                        Spacer(Modifier.height(4.dp))
                        Text(
                            "现在有 " + target.addressCount + " 条线路挂在这一类下。",
                            style = MaterialTheme.typography.bodySmall,
                            color = Color(OriginTeal),
                        )
                    }
                }
            },
            confirmButton = { TextButton(onClick = { vm.rename() }, enabled = !vm.acting) { Text("保存") } },
            dismissButton = { TextButton(onClick = { vm.renaming = null }) { Text("取消") } },
        )
    }

    vm.deleting?.let { target ->
        DangerConfirmDialog(
            title = "删除分类？",
            message = "「" + target.name + "」会从线路左栏消失。挂在这一类下的线路不会被删。" +
                "（后端不允许删还有线路挂着的分类，真要删请先把它们改到别的类）",
            confirmText = "删除",
            onConfirm = { vm.confirmDelete() },
            onDismiss = { vm.deleting = null },
        )
    }
}

/**
 * 一行分类：位次输入框 + 长按拖动区（名字 + 条线路 + ⠿）+ 更多操作（改名 / 删除）。
 *
 * 颜色跟着**模块语义色**走 ——「地址与联系人」这一页的三档各有一个（设计规范 §2 一色一功能）。
 *
 * ⚠️ 拖动手势只挂在"名字 + ⠿"那一块上，**不挂整行**：位次框还要长按选字、⋮ 还要点开菜单
 * （与 `ui/dispatcher/ProductCategoriesScreen.kt` 同一套）。
 */
@Composable
private fun RouteCategoryRow(
    c: RouteCategoryDto,
    position: Int,
    busy: Boolean,
    dragging: Boolean,
    dragOffset: Float,
    onDragStart: () -> Unit,
    onDrag: (Float) -> Unit,
    onDragEnd: () -> Unit,
    onPosition: (Int) -> Unit,
    onRename: () -> Unit,
    onDelete: () -> Unit,
) {
    var menu by remember { mutableStateOf(false) }
    SectionCard(
        modifier = Modifier
            .fillMaxWidth()
            .height(CATEGORY_ROW_HEIGHT)
            // 拖动中的那一行跟着手指走 + 轻微放大（卡片样式仍走共用件 SectionCard ——
            // 商品分类页那套自绘 Surface 的描边/阴影变化这边没有，因为这几档本来就是白卡。
            .graphicsLayer {
                translationY = dragOffset
                if (dragging) {
                    scaleX = 1.02f
                    scaleY = 1.02f
                }
            },
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            var posField by remember(c.id, position) { mutableStateOf(position.toString()) }
            // 「填第几位」用 SoTextField（浅灰底 + 圆角）而不是 OutlinedTextField：
            // 全库描边输入框的总数是**只减不许增**的基线（判据 _check_form_panel_style.py：
            // 「新页面又写描边框了？用 FormRows.kt 那五行」）。
            Box(Modifier.width(58.dp)) {
                SoTextField(
                    value = posField,
                    onValueChange = { v ->
                        val clean = com.tapmoay.sorders.core.InputRules.intInput(v, 3)
                        posField = clean
                        clean.toIntOrNull()?.let(onPosition)
                    },
                    enabled = !busy,
                    keyboardType = androidx.compose.ui.text.input.KeyboardType.Number,
                )
            }
            Spacer(Modifier.width(10.dp))
            Row(
                Modifier
                    .weight(1f)
                    .fillMaxHeight()
                    .pointerInput(c.id) {
                        detectDragGesturesAfterLongPress(
                            onDragStart = { onDragStart() },
                            onDrag = { change, drag ->
                                change.consume()
                                onDrag(drag.y)
                            },
                            onDragEnd = { onDragEnd() },
                            onDragCancel = { onDragEnd() },
                        )
                    },
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Column(Modifier.weight(1f)) {
                    Text(
                        c.name,
                        style = MaterialTheme.typography.titleSmall,
                        fontWeight = FontWeight.Bold,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                        // 显式占满这一列：maxLines=1 + 省略号却不给宽度的文本会去吃兄弟的宽度
                        // （判据 _check_adaptive_layout.py 的存量基线只许减不许增）
                        modifier = Modifier.fillMaxWidth(),
                    )
                    Text(
                        c.addressCount.toString() + " 条线路",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                Icon(
                    Icons.Default.DragHandle,
                    contentDescription = "长按拖动排序",
                    tint = MaterialTheme.colorScheme.outline,
                )
            }
            Box {
                IconButton(onClick = { menu = true }, enabled = !busy) {
                    Icon(Icons.Default.MoreVert, contentDescription = "更多操作", modifier = Modifier.size(20.dp))
                }
                DropdownMenu(expanded = menu, onDismissRequest = { menu = false }) {
                    DropdownMenuItem(
                        text = { Text("改名") },
                        leadingIcon = { Icon(Icons.Default.DriveFileRenameOutline, null) },
                        onClick = { menu = false; onRename() },
                    )
                    DropdownMenuItem(
                        text = { Text("删除", color = Color(MessageRed)) },
                        leadingIcon = { Icon(Icons.Default.DeleteOutline, null, tint = Color(MessageRed)) },
                        onClick = { menu = false; onDelete() },
                    )
                }
            }
        }
    }
}
