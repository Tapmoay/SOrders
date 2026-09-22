package com.tapmoay.sorders.ui.dispatcher

import androidx.compose.foundation.gestures.detectDragGesturesAfterLongPress
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.BookmarkAdded
import androidx.compose.material.icons.filled.DeleteOutline
import androidx.compose.material.icons.filled.DragHandle
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.Folder
import androidx.compose.material.icons.filled.SwapVert
import androidx.compose.material.icons.filled.VerticalAlignTop
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
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.data.remote.dto.OrderTemplateCategoryCreateRequest
import com.tapmoay.sorders.data.remote.dto.OrderTemplateCategoryDto
import com.tapmoay.sorders.data.remote.dto.OrderTemplateCategoryUpdateRequest
import com.tapmoay.sorders.ui.common.*

/**
 * 预订单分类管理（2026-09-22 用户：「这个模板我们是要**做一个分类**的 —— 也是一样的，
 * **左边是分类管理**，就是**复用**嘛，复用那些**商品管理**的形式；**我右边就是订单**」）。
 *
 * 与「商品分类管理」「地点分组管理」「开销分类管理」「运费分类管理」**同一套规矩**
 * （改之前先读 `ExpenseCategoriesViewModel` / `FreightCategoriesViewModel` 顶部那两段）：
 * · 建 / 改名（**级联**：预设单是按**名字**归属这个分类的，改名会在**同一事务**里
 *   把挂着的预设单一起改过去）/ 删除（**还有预设单挂着时后端拒绝**，
 *   把那句「还有 N 张预设单挂在这个分类下」**原样**给用户看 —— 带数量才好照着改）；
 * · **排序是本地草稿**，点「保存顺序」才提交（后端要求整份顺序：拖一步发一次
 *   会在中途失败时留下半新半旧的顺序）；
 * · 排序两种方式（填位次 / 上下移）**共用 `moveItemTo`**（商品那边泛化好的那一份）。
 *
 * ⚠️ 为什么整页照抄运费那页而不是自己写一套：这一套名册的三条规则
 * （提交只带名册内的行 / 「改过没有」的判据 / 撤销）**各抄一遍就已经走散过一次**
 * —— 运费页的「撤销」曾经会把保存后新建的分类丢掉，三页存完「未保存」还亮着。
 * 所以"怎么把名册管好"只有 `ui/common/CategoryRosterViewModel.kt` 那一份，
 * 这一页只交代"这是什么"（拉哪个接口、提交到哪个接口）。
 */
class OrderTemplateCategoriesViewModel(container: AppContainer) :
    CategoryRosterViewModel<OrderTemplateCategoryDto>(container) {

    init {
        // ⚠️ 必须由**子类**来调：基类的 init 早于子类初始化，而 load() 在 Main.immediate 下
        //    会同步跑到第一个挂起点（见基类文件头）。
        load()
    }

    override fun idOf(item: OrderTemplateCategoryDto) = item.id

    override fun nameOf(item: OrderTemplateCategoryDto) = item.name

    override suspend fun fetchAll() = container.repo.orderTemplateCategories()

    override suspend fun reorder(ids: List<Long>) = container.repo.reorderOrderTemplateCategories(ids)

    override suspend fun create(name: String) {
        container.repo.createOrderTemplateCategory(OrderTemplateCategoryCreateRequest(name))
    }

    override suspend fun rename(id: Long, name: String) {
        container.repo.updateOrderTemplateCategory(id, OrderTemplateCategoryUpdateRequest(name = name))
    }

    override suspend fun delete(id: Long) {
        container.repo.deleteOrderTemplateCategory(id)
    }

    /**
     * 改名会**级联**改掉挂在这个分类下的预设单（预设单是按**名字**归属分类的，
     * 后端在**同一事务**里一起改），所以提示里必须说出来 ——
     * 不说的话用户以为只改了个名字，下次看到"预设单自己换了分类"会以为见鬼了。
     */
    override fun renamedNotice(name: String) =
        "已改名为「$name」（挂在这个分类下的预设单也跟着改了）"
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun OrderTemplateCategoriesScreen(container: AppContainer, onBack: () -> Unit) {
    val vm: OrderTemplateCategoriesViewModel = appViewModel { OrderTemplateCategoriesViewModel(container) }
    val snackbar = remember { SnackbarHostState() }
    OneShotSnackbar(snackbar, vm.notice, onConsumed = { vm.notice = null })
    OneShotSnackbar(snackbar, vm.error, onConsumed = { vm.error = null })

    // 拖动状态（与「商品排序」页、商品分类管理页同一套：长按 → 位移换算成格数 → 到半行就换位）
    var draggingId by remember { mutableStateOf<Long?>(null) }
    var dragOffset by remember { mutableStateOf(0f) }
    val haptic = LocalHapticFeedback.current
    val rowPx = with(LocalDensity.current) { CATEGORY_ROW_HEIGHT.toPx() }

    Scaffold(
        snackbarHost = { SnackbarHost(snackbar) },
        topBar = {
            TopAppBar(
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = MaterialTheme.colorScheme.background,
                ),
                title = { Text("预订单分类管理", style = MaterialTheme.typography.titleLarge) },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
                    }
                },
                actions = {
                    TextButton(onClick = { vm.openCreate() }) {
                        Icon(Icons.Default.Add, contentDescription = null, modifier = Modifier.size(18.dp))
                        Text("新建")
                    }
                },
            )
        },
    ) { padding ->
        Column(Modifier.fillMaxSize().padding(padding)) {
            // 顺序是**本地草稿**，点「保存顺序」才提交（照商品排序/商品分类管理那两页）：
            // 连拖几下只产生一次请求，也不会"拖一步发一次、中途失败顺序半新半旧"。
            if (vm.dirty) {
                Surface(color = MaterialTheme.colorScheme.primaryContainer, modifier = Modifier.fillMaxWidth()) {
                    Row(
                        Modifier.padding(horizontal = 16.dp, vertical = 10.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Icon(Icons.Default.SwapVert, contentDescription = null, modifier = Modifier.size(18.dp))
                        Spacer(Modifier.width(8.dp))
                        Text("顺序改过了，记得保存", style = MaterialTheme.typography.bodyMedium, modifier = Modifier.weight(1f))
                        TextButton(enabled = !vm.busy, onClick = { vm.saveOrder() }) { Text("保存顺序") }
                        TextButton(enabled = !vm.busy, onClick = { vm.revertOrder() }) { Text("撤销") }
                    }
                }
            }
            when {
                vm.loading -> LoadingBox()
                vm.loadError != null -> ErrorView(vm.loadError.orEmpty(), onRetry = { vm.load() })
                else -> Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState())) {
                    // ⚠️ 这两句放在 `when` **外面**（一直看得见）：第一版放进去被判成空态句，
                    //    而且说明书本来就不该藏在"有数据"那一支里。
                    Hint(
                        "顺序 = 预订单页左边那一列分类的顺序。按住一行长按拖动，或点右边的 ↑ 置顶。",
                        style = MaterialTheme.typography.bodySmall,
                        color = Color(TemplateIndigo),
                        modifier = Modifier.padding(start = 16.dp, end = 16.dp, top = 12.dp),
                    )
                    Hint(
                        "改名会连带改掉挂着的预设单（同一次提交里改完）；删除要先把挂着的预设单改成别的分类。",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.padding(start = 16.dp, end = 16.dp, top = 4.dp, bottom = 8.dp),
                    )
                    vm.categories.forEachIndexed { idx, c ->
                        // ⚠️ `key(c.id)` **不是可选的**（真机上踩出来的）：不给稳定 key 的话
                        //    Compose 按位置复用节点，被拖那一行的 `pointerInput` 会随节点销毁
                        //    → 手势被取消，表现是"长按拖了半天只挪一格就自己松手"。
                        key(c.id) {
                            OrderTemplateCategoryRow(
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
                                    val steps = dragSteps(dragOffset, rowPx)
                                    if (steps != 0) {
                                        vm.moveBy(c.id, steps)
                                        // 换过位之后把"已消耗的位移"减掉，剩下的继续攒
                                        dragOffset -= steps * rowPx
                                    }
                                },
                                onDragEnd = {
                                    draggingId = null
                                    dragOffset = 0f
                                },
                                onTop = { vm.moveTo(c.id, 1) },
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

    // 建 / 改名
    vm.editing?.let { (id, current) ->
        var text by remember(id) { mutableStateOf(current) }
        AlertDialog(
            onDismissRequest = { if (!vm.busy) vm.editing = null },
            title = { Text(if (id == null) "新建预订单分类" else "改分类名") },
            text = {
                Column {
                    SoTextField(text, { text = it }, placeholder = "分类名（如 每周固定单）")
                    if (id != null) {
                        Spacer(Modifier.height(6.dp))
                        Text(
                            "改名会连带改掉挂在这个分类下的所有预设单（不改的话它们会变成未分类）。",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
            },
            confirmButton = {
                TextButton(onClick = { vm.submit(id, text) }, enabled = !vm.busy) { Text("保存") }
            },
            dismissButton = { TextButton(onClick = { vm.editing = null }, enabled = !vm.busy) { Text("取消") } },
        )
    }

    // 删除确认（后端还会挡"还有预设单挂着"，并把有几张说出来）
    vm.deleting?.let { c ->
        DangerConfirmDialog(
            title = "删除分类「${c.name}」？",
            message = "还有预设单挂在这个分类下时会被拒绝（不会把它们顺手改成别的分类）。",
            confirmText = "删除",
            onConfirm = { vm.confirmDelete(c) },
            onDismiss = { vm.deleting = null },
        )
    }
}

/**
 * 名册里的一行：**序号 + 语义色圆底图标 + 名字（加粗）+ 挂着几张预设单**，
 * 右边是「置顶↑」+ 拖动把手 + 改名 / 删除。
 *
 * ## 换过一版（2026-09-22 用户第二轮）
 * 用户原话：「分类管理中的排序**不是点击上上下下这种**」—— 第一版是"位次输入框 + ↑/↓ 按钮"
 * （照运费分类那一页抄的）。现在与**商品排序页**（`ProductSortScreen`）、**商品分类管理页**
 * （`ProductCategoriesScreen`）同一形态：**长按整行拖动**（+ 一个「置顶↑」快捷键），
 * 搬运逻辑是同两份共用件（`ui/common/CategoryRoster.kt::moveItemTo`、`dragSteps`）。
 *
 * ⚠️ 行高必须**固定**（拖动的"位移 → 挪几格"靠它算）：[CATEGORY_ROW_HEIGHT] 改之前先用
 *    真机截图确认行内没被切（商品排序页那次是从 64dp 抬到 96dp 才不裁的）。
 */
@Composable
private fun OrderTemplateCategoryRow(
    index: Int,
    c: OrderTemplateCategoryDto,
    busy: Boolean,
    dragging: Boolean,
    dragOffset: Float,
    onDragStart: () -> Unit,
    onDrag: (Float) -> Unit,
    onDragEnd: () -> Unit,
    onTop: () -> Unit,
    onRename: () -> Unit,
    onDelete: () -> Unit,
) {
    SectionCard(
        modifier = Modifier
            .padding(horizontal = 16.dp)
            .height(CATEGORY_ROW_HEIGHT)
            .graphicsLayer {
                translationY = dragOffset
                if (dragging) {
                    scaleX = 1.02f
                    scaleY = 1.02f
                }
            },
    ) {
        Row(Modifier.fillMaxSize(), verticalAlignment = Alignment.CenterVertically) {
            // 拖动区：序号 + 图标 + 名字/计数（**不挂整行** —— 右边那几个按钮要留着自己的点击）
            Row(
                Modifier
                    .weight(1f)
                    .fillMaxHeight()
                    .pointerInput(c.id) {
                        detectDragGesturesAfterLongPress(
                            onDragStart = { onDragStart() },
                            onDrag = { change, drag -> change.consume(); onDrag(drag.y) },
                            onDragEnd = { onDragEnd() },
                            onDragCancel = { onDragEnd() },
                        )
                    },
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    (index + 1).toString(),
                    style = MaterialTheme.typography.titleMedium,
                    textAlign = TextAlign.Center,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.width(28.dp),
                )
                Spacer(Modifier.width(6.dp))
                // 语义色圆底图标：与预订单页左栏、工作台那一格同色
                TintedIcon(Icons.Default.Folder, Color(TemplateIndigo), size = 20.dp, container = 40.dp)
                Spacer(Modifier.width(10.dp))
                Column(Modifier.weight(1f)) {
                    Text(c.name, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold, maxLines = 1)
                    // 只有这一个计数（运费那页有"价目 / 计费规则"两个）——
                    // 它是删除前的唯一判据，所以挂在每一行上，删之前看得见。
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Icon(
                            Icons.Default.BookmarkAdded, contentDescription = null,
                            tint = Color(TemplateIndigo), modifier = Modifier.size(13.dp),
                        )
                        Spacer(Modifier.width(3.dp))
                        Text(
                            "预设单",
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                        Spacer(Modifier.width(3.dp))
                        Text(
                            c.templateCount.toString() + " 张",
                            style = MaterialTheme.typography.labelMedium,
                            // ⚠️ **文字不上色**（用户 2026-09-22 第二轮：「文字就不需要加颜色了，
                            //    这样的反而显得太花了」）—— 语义色只给图标，强调靠加粗。
                            color = MaterialTheme.colorScheme.onSurface,
                            fontWeight = FontWeight.Bold,
                        )
                    }
                }
            }
            IconButton(onClick = onTop, enabled = !busy) {
                Icon(Icons.Default.VerticalAlignTop, contentDescription = "置顶", tint = Color(TemplateIndigo))
            }
            Icon(
                Icons.Default.DragHandle,
                contentDescription = "长按拖动排序",
                tint = MaterialTheme.colorScheme.outline,
            )
            IconButton(onClick = onRename, enabled = !busy) {
                Icon(Icons.Default.Edit, contentDescription = "改名")
            }
            IconButton(onClick = onDelete, enabled = !busy) {
                Icon(Icons.Default.DeleteOutline, contentDescription = "删除", tint = MaterialTheme.colorScheme.error)
            }
        }
    }
}

/**
 * 名册行的**固定**高度（拖动的"位移 → 挪几格"靠它算，所以不能自适应）。
 * 内容高 = 名字 24 + 计数 18 + 卡内边距 32 ≈ 74，留到 88 免得被裁（真机截图确认过）。
 */
private val CATEGORY_ROW_HEIGHT = 88.dp

/**
 * 预订单功能的语义色：**靛蓝**（与工作台那一格、预订单页的图标同色）。
 * ⛔ 别改用橙色 —— 橙色在这个 App 里是**钱**（账本 / 收款）。
 */
private const val TemplateIndigo = 0xFF3949ABL
