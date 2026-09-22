package com.tapmoay.sorders.ui.dispatcher

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.detectDragGesturesAfterLongPress
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.LocalHapticFeedback
import androidx.compose.ui.text.TextRange
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.TextFieldValue
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.core.InputRules
import com.tapmoay.sorders.data.remote.dto.ProductCategoryDto
import com.tapmoay.sorders.ui.common.*

/** 分类行的固定高度。**拖动的"位移 → 挪几格"靠它算**，所以不能是自适应高度。 */
private val CATEGORY_ROW_HEIGHT = 68.dp

/**
 * 商品分类管理：**新建 / 改名 / 排序 / 删除**。
 *
 * ## 为什么要有这一页（用户 2026-09-18）
 * 之前的分类顺序是**推出来的**（按商品数倒序）—— 那是"现在哪类货多"，
 * 不是"店家想让人先看哪类"。用户要的是：
 * > 派单端可以创建商品分类，甚至可以更改商品分类的显示顺序。
 *
 * ## 排序为什么从"上移/下移按钮"改成拖动 + 填数字（用户 2026-09-19）
 * 原话：「商品分类的排序不是按个按钮进行排序。我们可以选择数字排序，比如说把这个编号
 * 0/1/2/3 进行排序，也可以长按这个卡片进行拖动，也就是长按显示进行拖动，进行手动排序」。
 *
 * 两种方式**共用同一处排序逻辑**（`ProductCategoriesViewModel.moveTo` ← `ui/common/CategoryRoster.kt::moveItemTo`）：
 * - **长按拖动**：按住行的名称区（或右边的 `⠿` 手柄）拖，划过半行就换位，
 *   松手前一直能拖回来；开始拖时有一次振动反馈（不然"到底抓住了没有"要靠眼睛猜）。
 * - **填数字**：左边那个序号框可以直接改成想去的位次（填 0 或超过总数会被夹到两端）。
 *
 * ⚠️ 原来那段注释说"拖拽会没有位置放删除和改名（长按拖动与长按菜单冲突）"——
 *    那个担心在**长按弹出菜单**的前提下成立，但这里的长按是**拖动**、改名/删除在 `⋮` 菜单里，
 *    两者不抢同一个手势。所以这条限制不再存在，注释也一并改掉（过期注释比没有注释更糟）。
 *
 * ⚠️ **顺序仍然是本地草稿**，点「保存顺序」才提交（后端要求整份顺序）。
 *    拖动或改数字之后顶部会出现那条提示条，不是"自动保存"。
 *
 * ⚠️ 这里用 `Column` + `verticalScroll` 而不是 `LazyColumn`：拖动的位移→格数换算需要一个
 *    **可预测的行高**，而 LazyColumn 的 item 复用会让这个换算变成靠测量。
 *    分类一般几个到十几个（后端上限 200），这个代价换来的手感是值得的；
 *    真到几百个再换实现（届时要在拖动时自动滚动，那是另一件事）。
 *    副作用：拖到屏幕边缘**不会自动滚动** —— 分类多到需要滚动时这一点会硌手。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ProductCategoriesScreen(
    container: AppContainer,
    onBack: () -> Unit,
) {
    val vm: ProductCategoriesViewModel = appViewModel { ProductCategoriesViewModel(container) }
    val snackbar = remember { SnackbarHostState() }

    OneShotSnackbar(snackbar, vm.notice, onConsumed = { vm.notice = null })
    OneShotSnackbar(snackbar, vm.loadError, onConsumed = { vm.loadError = null })

    // 拖动状态：只记"正在拖谁"和"拖出去多远"，位置本身在 vm.categories 里（换位就改它）
    var draggingId by remember { mutableStateOf<Long?>(null) }
    var dragOffset by remember { mutableStateOf(0f) }
    val haptic = LocalHapticFeedback.current
    val rowHeightPx = with(LocalDensity.current) { CATEGORY_ROW_HEIGHT.toPx() }

    Scaffold(
        snackbarHost = { SnackbarHost(snackbar) },
        topBar = {
            TopAppBar(
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = MaterialTheme.colorScheme.background,
                ),
                title = { Text("商品分类", style = MaterialTheme.typography.titleLarge) },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
                    }
                },
                actions = {
                    TextButton(onClick = { vm.openCreate() }) {
                        Icon(Icons.Default.Add, contentDescription = null, modifier = Modifier.size(18.dp))
                        Spacer(Modifier.width(4.dp))
                        Text("新建分类")
                    }
                },
            )
        },
    ) { padding ->
        Column(Modifier.fillMaxSize().padding(padding)) {
            // 顺序改动是**本地草稿**，要点「保存顺序」才提交 —— 这样连拖几下
            // 只产生一次请求，也不会出现"拖一步发一次、中途失败顺序半新半旧"。
            if (vm.dirty) {
                Surface(
                    color = MaterialTheme.colorScheme.primaryContainer,
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Row(
                        Modifier.padding(horizontal = 16.dp, vertical = 10.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Icon(Icons.Default.SwapVert, contentDescription = null, modifier = Modifier.size(18.dp))
                        Spacer(Modifier.width(8.dp))
                        Text(
                            "顺序改过了，记得保存",
                            style = MaterialTheme.typography.bodyMedium,
                            modifier = Modifier.weight(1f),
                        )
                        TextButton(enabled = !vm.busy, onClick = { vm.saveOrder() }) { Text("保存顺序") }
                        TextButton(enabled = !vm.busy, onClick = { vm.revertOrder() }) { Text("撤销") }
                    }
                }
            }

            when {
                vm.loading -> LoadingBox()
                vm.error != null -> ErrorView(vm.error.orEmpty(), onRetry = { vm.load() })
                vm.categories.isEmpty() -> EmptyBox()
                else -> Column(
                    Modifier.fillMaxSize().verticalScroll(rememberScrollState()),
                ) {
                    Text(
                        "这一列的顺序 = 下单页「选择商品」左侧的顺序（从上到下）。" +
                            "没有商品的分类不会出现在下单页里，但会留在这里。",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.padding(start = 16.dp, end = 16.dp, top = 16.dp),
                    )
                    Spacer(Modifier.height(4.dp))
                    Hint(
                        // ⚠️ 界面文案里**不许写 Markdown**（`_check_ai_guardrails.py` 有一条红线扫 ui/**）：
                        //    用户在屏幕上看到的是**字面的星号**，不是加粗 —— 这条第一版就是写错的。
                        "改顺序：按住一行长按拖动，或直接改左边的序号。",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.primary,
                        modifier = Modifier.padding(horizontal = 16.dp),
                    )
                    Spacer(Modifier.height(8.dp))

                    vm.categories.forEachIndexed { idx, c ->
                        // ⚠️ `key(c.id)` **不是可选的**（真机上踩出来的）：
                        //    拖动时每换一次位就重排一次 `categories`；不给稳定 key 的话
                        //    Compose 按**位置**复用/重建这些 composable，被拖动那一行的
                        //    `pointerInput` 会连同节点一起被销毁 → **手势被取消**，
                        //    表现是"长按拖了半天只挪了一格就自己松手了"。
                        //    给了 key，节点是**被移动**的，手势在整段拖动里一直活着。
                        key(c.id) {
                            CategoryRow(
                                index = idx,
                                c = c,
                                busy = vm.busy,
                                dragging = draggingId == c.id,
                                dragOffset = if (draggingId == c.id) dragOffset else 0f,
                                onDragStart = {
                                    draggingId = c.id
                                    dragOffset = 0f
                                    // 抓住了给一次手感反馈：没有它，用户不知道长按是否生效
                                    haptic.performHapticFeedback(HapticFeedbackType.LongPress)
                                },
                                onDrag = { dy ->
                                    dragOffset += dy
                                    val steps = dragSteps(dragOffset, rowHeightPx)
                                    if (steps != 0) {
                                        vm.moveBy(c.id, steps)
                                        // 换过位之后把"已消耗的位移"减掉，剩下的继续攒
                                        dragOffset -= steps * rowHeightPx
                                    }
                                },
                                onDragEnd = {
                                    draggingId = null
                                    dragOffset = 0f
                                },
                                onPosition = { pos -> vm.moveTo(c.id, pos) },
                                onRename = { vm.openRename(c) },
                                onDelete = { vm.askDelete(c) },
                            )
                        }
                        Spacer(Modifier.height(8.dp))
                    }
                    Spacer(Modifier.height(24.dp))
                }
            }
        }
    }

    // 新建 / 改名
    vm.editing?.let { editing ->
        CategoryNameDialog(
            initial = editing.second,
            isNew = editing.first == null,
            busy = vm.busy,
            onConfirm = { name -> vm.submit(editing.first, name) },
            onDismiss = { vm.editing = null },
        )
    }

    // 删除确认：把"还有几个商品挂在这一类"写在脸上（后端也会拦，这里先说清楚）
    vm.deleting?.let { c ->
        AlertDialog(
            onDismissRequest = { vm.deleting = null },
            title = { Text("删除分类「${c.name}」？") },
            text = {
                Text(
                    if (c.productCount > 0) {
                        "还有 ${c.productCount} 个商品挂在这个分类下，删不掉。" +
                            "先把这些商品改成别的分类（或给它改个名）再来删。"
                    } else {
                        "这个分类下没有商品，删除后不影响任何商品。"
                    }
                )
            },
            confirmButton = {
                TextButton(
                    enabled = !vm.busy && c.productCount == 0,
                    onClick = { vm.confirmDelete(c) },
                ) { Text("删除", color = MaterialTheme.colorScheme.error) }
            },
            dismissButton = { TextButton(onClick = { vm.deleting = null }) { Text("取消") } },
        )
    }
}

@Composable
private fun EmptyBox() {
    Column(
        Modifier.fillMaxSize().padding(24.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
    ) {
        Text(
            "还没有任何分类",
            style = MaterialTheme.typography.titleMedium,
        )
        Spacer(Modifier.height(6.dp))
        Text(
            "分类只影响下单页左侧怎么分组。建好之后在商品编辑页把商品归到对应分类即可。",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

/**
 * 一行分类：`[序号] [名称 / 商品数 ⠿] [⋮]`。
 *
 * - **序号框可改**：填几就排到第几（用户要的"数字排序"）；
 * - **名称区 + 手柄是拖动区**：长按拖动排序（手势挂在这一块上，
 *   **不能挂整行** —— 序号框要留着自己的长按选字、`⋮` 要留着自己的点击）；
 * - **改名 / 删除收进 `⋮`**：与商品卡同一个理由（用户 2026-09-19：右边按钮太占位置）。
 */
@Composable
private fun CategoryRow(
    index: Int,
    c: ProductCategoryDto,
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
    // 序号框：**聚焦时全选**（见下面 `onFocusChanged`），位置变了才回填。
    //
    // ⚠️ 这两条都是真机上踩出来的，不是想当然：
    //    第一版是普通 String 状态 + 直接改。真机上点一下框（光标落在数字**前面**）、
    //    按退格没删掉、再打一个 `2` —— 文本成了 `42`，被夹到末尾，用户想"放到第 2 位"
    //    结果它跑到了最后一名。所以：
    //    ① 聚焦即全选，打字就是**替换**（这类"第几位"的框就该这样）；
    //    ② 位置变化时才回填，回填时光标放末尾 —— 否则边打边被覆盖。
    var posField by remember(c.id) { mutableStateOf(TextFieldValue((index + 1).toString())) }
    LaunchedEffect(index) {
        val want = (index + 1).toString()
        if (posField.text != want) posField = TextFieldValue(want, selection = TextRange(want.length))
    }

    Surface(
        shape = RoundedCornerShape(12.dp),
        color = if (dragging) MaterialTheme.colorScheme.surfaceVariant else MaterialTheme.colorScheme.surface,
        border = BorderStroke(
            1.dp,
            if (dragging) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.outlineVariant,
        ),
        shadowElevation = if (dragging) 8.dp else 0.dp,
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp)
            .height(CATEGORY_ROW_HEIGHT)
            // 拖起来的那一行跟着手指走、并稍微放大 —— 没有这个反馈，
            // 用户看到的是"列表自己在跳"，不知道自己抓住了哪一行
            .graphicsLayer {
                translationY = dragOffset
                if (dragging) {
                    scaleX = 1.02f
                    scaleY = 1.02f
                }
            },
    ) {
        Row(
            Modifier.fillMaxSize().padding(horizontal = 10.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            OutlinedTextField(
                value = posField,
                onValueChange = { v ->
                    val clean = InputRules.intInput(v.text, 3)
                    posField = if (clean == v.text) v else TextFieldValue(clean, selection = TextRange(clean.length))
                    clean.toIntOrNull()?.let(onPosition)
                },
                singleLine = true,
                textStyle = MaterialTheme.typography.titleMedium.copy(textAlign = TextAlign.Center),
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                enabled = !busy,
                modifier = Modifier
                    .width(58.dp)
                    .onFocusChanged { st ->
                        if (st.isFocused) {
                            posField = posField.copy(selection = TextRange(0, posField.text.length))
                        }
                    },
            )
            Spacer(Modifier.width(8.dp))
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
                        style = MaterialTheme.typography.bodyLarge,
                        fontWeight = FontWeight.SemiBold,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                    Text(
                        if (c.productCount > 0) "${c.productCount} 个商品" else "暂无商品",
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
                        leadingIcon = { Icon(Icons.Default.DriveFileRenameOutline, contentDescription = null) },
                        onClick = { menu = false; onRename() },
                    )
                    DropdownMenuItem(
                        text = { Text("删除", color = MaterialTheme.colorScheme.error) },
                        leadingIcon = {
                            Icon(Icons.Default.DeleteOutline, contentDescription = null, tint = MaterialTheme.colorScheme.error)
                        },
                        onClick = { menu = false; onDelete() },
                    )
                }
            }
        }
    }
}

@Composable
private fun CategoryNameDialog(
    initial: String,
    isNew: Boolean,
    busy: Boolean,
    onConfirm: (String) -> Unit,
    onDismiss: () -> Unit,
) {
    var name by remember { mutableStateOf(initial) }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(if (isNew) "新建分类" else "给分类改名") },
        text = {
            Column {
                SoTextField(
                    value = name,
                    onValueChange = { name = it.take(8) },
                    placeholder = "分类名，如 饮料 / 粮油 / 日化",
                )
                if (!isNew) {
                    Spacer(Modifier.height(8.dp))
                    Text(
                        "改名会把挂在这个分类下的商品「一起改过去」（同一事务），不会让它们变成未分类。",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
        },
        confirmButton = {
            TextButton(enabled = !busy && name.isNotBlank(), onClick = { onConfirm(name) }) {
                Text(if (busy) "提交中…" else "确定")
            }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("取消") } },
    )
}
