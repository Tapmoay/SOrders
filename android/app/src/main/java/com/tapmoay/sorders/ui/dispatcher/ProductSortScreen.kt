package com.tapmoay.sorders.ui.dispatcher

import androidx.compose.foundation.gestures.detectDragGesturesAfterLongPress
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.DragHandle
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
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.data.remote.api.ProductUpdateRequest
import com.tapmoay.sorders.data.remote.dto.ProductDto
import com.tapmoay.sorders.data.repo.toApiException
import com.tapmoay.sorders.ui.common.*
import com.tapmoay.sorders.ui.theme.ProductPurple
import kotlinx.coroutines.launch

/**
 * 排序行固定高度：拖动的"位移 → 挪几格"靠它算，所以不能是自适应高度。
 *
 * ⚠️ 2026-09-21 从 **64dp 抬到 96dp**：这一轮行里的"售价 · 库存"那一行字
 * 改成了共用的**两条事实行**（`ProductLine` + `productFacts`，与商品卡同版式），
 * 于是内容高 = 名称 24 + 间隔 2 + 两条事实 35 ≈ 61dp，而 `SectionCard` 自己还要
 * 上下各 16dp 内边距 —— 64dp 会**把事实行裁掉**（截图上看着像"这一行没有库存"，
 * 而它其实是被裁了）。改这个数字前先用真机截图确认行内没被切。
 */
private val SORT_ROW_HEIGHT = 96.dp

/**
 * 商品排序页的状态（2026-09-21，用户：「那个排序你没加啊」）。
 *
 * ## 它解决什么
 * 在这之前商品列表顺序是后端写死的 `is_active desc, id desc` —— **最新建的排最前**。
 * 一个分类里几十个商品时，最常用的老商品沉到最底下，而用户**没有任何办法调它**。
 *
 * ## 排序是**本地草稿**，点「完成」才提交
 * 与四个分类名册页同一个套路（`common/CategoryRoster.kt` 那三条规则共用）：
 * 连拖几下只产生一次提交、中途失败也不会留下"半新半旧"的顺序。
 *
 * ## 提交走**逐条 PATCH**（不新增后端端点）
 * `sort_order` 是 `PATCH /products/{id}` 的一个普通字段，所以一行发一次请求：
 * 好处是每条改动由后端各自写一行 `operation_logs`（可回查），也不用动 AI 写能力的覆盖表。
 * 代价如实说：一次排 50 行 = 50 个请求；汇报必须**逐条**（成功 N / 失败哪几个）。
 *
 * ⚠️ 序号**从 1 开始**：0 是"没排过"的默认值（见 `models/product.py` 的注释），
 * 拿 0 当第一名会让"没排过"和"排在第一"分不出来。
 */
class ProductSortViewModel(private val container: AppContainer) : ViewModel() {

    /** 本地草稿顺序（= 页面上从上到下的顺序）。 */
    val rows = mutableStateListOf<ProductDto>()

    var loading by mutableStateOf(true)
    var loadError by mutableStateOf<String?>(null)
    var saving by mutableStateOf(false)
    var notice by mutableStateOf<String?>(null)
    var error by mutableStateOf<String?>(null)

    /** 顺序改过没有（页面靠它决定要不要显示提示条）。 */
    var dirty by mutableStateOf(false)
        private set

    private var savedOrder: List<Long> = emptyList()

    init {
        load()
    }

    fun load() {
        loading = rows.isEmpty()
        loadError = null
        viewModelScope.launch {
            try {
                val all = container.repo.products()
                replaceAll(all.filter { it.isActive })
            } catch (e: Exception) {
                loadError = toApiException(e).message
            } finally {
                loading = false
            }
        }
    }

    private fun replaceAll(list: List<ProductDto>) {
        rows.clear()
        rows.addAll(list)
        savedOrder = list.map { it.id }
        dirty = false
    }

    /** 挪到第 [position] 位（**1-based**，拖动的"位移→格数"也走它）。 */
    fun moveTo(id: Long, position: Int) {
        val next = moveItemTo(rows, { it.id }, id, position)
        if (next === rows) return
        rows.clear()
        rows.addAll(next)
        dirty = rows.map { it.id } != savedOrder
    }

    fun moveBy(id: Long, steps: Int) {
        val idx = rows.indexOfFirst { it.id == id }
        if (idx < 0) return
        moveTo(id, idx + 1 + steps)
    }

    /** 「置顶」：排到第一位（参考图里那一列 ↑ 按键）。 */
    fun top(id: Long) = moveTo(id, 1)

    fun revert() {
        if (savedOrder.isEmpty()) return
        val back = revertedOrder(rows, savedOrder, { it.id })
        rows.clear()
        rows.addAll(back)
        dirty = false
    }

    /** 提交：逐条 PATCH `sort_order`（第 1 行写 1、第 2 行写 2 …）。 */
    fun save(onDone: () -> Unit) {
        if (rows.isEmpty()) return
        saving = true
        error = null
        viewModelScope.launch {
            val failed = mutableListOf<String>()
            var ok = 0
            rows.forEachIndexed { idx, p ->
                val want = idx + 1
                if (p.sortOrder == want) return@forEachIndexed
                try {
                    container.api.productApi.updateProduct(p.id, ProductUpdateRequest(sortOrder = want))
                    ok++
                } catch (e: Exception) {
                    failed += p.name + "（" + toApiException(e).message + "）"
                }
            }
            notice = buildString {
                append("顺序已保存：写了 ").append(ok).append(" 个商品")
                if (failed.isNotEmpty()) {
                    append("；失败 ").append(failed.size).append(" —— ")
                    append(failed.take(3).joinToString("、"))
                }
            }
            saving = false
            onDone()
        }
    }
}

/**
 * 「商品排序」页（照参考图：成列的商品 + 每行一个置顶↑ + 拖动手柄 + 底部「完成」）。
 *
 * 两种排序方式**共用同一处搬运逻辑**（`ui/common/CategoryRoster.kt::moveItemTo`，四个名册页同款）：
 * - **长按拖动**：按住名称区或右边的手柄拖，划过半行就换位；开始拖时振动一次（不然"抓住没有"靠眼睛猜）。
 * - **置顶↑**：一步排到最前（最常用的一种"我想让它显眼"）。
 *
 * ⚠️ 用 `Column + verticalScroll` 而不是 `LazyColumn`：拖动的位移→格数换算需要一个**可预测的行高**
 *    （与 `ProductCategoriesScreen` 同一个理由与同一个代价：拖到边缘不会自动滚动）。
 * ⚠️ `key(p.id)` 不是可选的：换位时若按位置复用节点，被拖那一行的手势会被销毁 → "拖了半天只挪一格"。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ProductSortScreen(container: AppContainer, onBack: () -> Unit) {
    val vm: ProductSortViewModel = appViewModel { ProductSortViewModel(container) }
    val snackbar = remember { SnackbarHostState() }
    OneShotSnackbar(snackbar, vm.notice, onConsumed = { vm.notice = null })
    OneShotSnackbar(snackbar, vm.error, onConsumed = { vm.error = null })

    var draggingId by remember { mutableStateOf<Long?>(null) }
    var dragOffset by remember { mutableStateOf(0f) }
    val haptic = LocalHapticFeedback.current
    val rowPx = with(LocalDensity.current) { SORT_ROW_HEIGHT.toPx() }

    Scaffold(
        snackbarHost = { SnackbarHost(snackbar) },
        topBar = {
            TopAppBar(
                colors = TopAppBarDefaults.topAppBarColors(containerColor = MaterialTheme.colorScheme.background),
                title = { Text("商品排序", style = MaterialTheme.typography.titleLarge) },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
                    }
                },
                actions = {
                    TextButton(
                        enabled = !vm.saving && vm.dirty,
                        onClick = { vm.save { } },
                    ) { Text("完成", fontWeight = FontWeight.Bold, color = Color(ProductPurple)) }
                },
            )
        },
    ) { padding ->
        Column(Modifier.fillMaxSize().padding(padding)) {
            if (vm.dirty) {
                Surface(color = MaterialTheme.colorScheme.primaryContainer, modifier = Modifier.fillMaxWidth()) {
                    Row(
                        Modifier.padding(horizontal = 16.dp, vertical = 8.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Text("顺序改过了（点右上角「完成」保存）", style = MaterialTheme.typography.bodySmall, modifier = Modifier.weight(1f))
                        TextButton(enabled = !vm.saving, onClick = { vm.revert() }) { Text("撤销") }
                    }
                }
            }
            // ⚠️ 这句"这一页怎么用"放在 `when` **外面**：它要一直看得见。
            //    第一版写在 `else ->` 分支里，被 `_check_hints.py` 判成了**空态句**
            //    —— 那个判据看的是"调用点前面 600 字里有没有**判空调用**"，
            //    而 `when` 里判空的那一支正好在它前面。这次不是判据错，是**位置错**：
            //    说明书本来就不该藏在"有数据"那一支里。
            //    ⚠️ 顺带一个坑：**这段解释本身不许把那个函数名写出来**（我第一次就是这么写的，
            //       结果注释里的那串字符反过来命中了判据，页面照样被判成空态句）。
            Hint(
                "从上到下就是商品管理页里的顺序。按住一行长按拖动，或点右边的 ↑ 置顶。",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.primary,
                modifier = Modifier.padding(start = 16.dp, end = 16.dp, top = 12.dp, bottom = 6.dp),
            )
            when {
                vm.loading -> LoadingBox()
                vm.loadError != null -> ErrorView(vm.loadError.orEmpty(), onRetry = { vm.load() })
                vm.rows.isEmpty() -> EmptyView("没有在售的商品可以排序")
                else -> Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState())) {
                    vm.rows.forEachIndexed { idx, p ->
                        key(p.id) {
                            SortRow(
                                index = idx,
                                p = p,
                                dragging = draggingId == p.id,
                                dragOffset = if (draggingId == p.id) dragOffset else 0f,
                                onDragStart = {
                                    draggingId = p.id
                                    dragOffset = 0f
                                    haptic.performHapticFeedback(HapticFeedbackType.LongPress)
                                },
                                onDrag = { dy ->
                                    dragOffset += dy
                                    val steps = dragSteps(dragOffset, rowPx)
                                    if (steps != 0) {
                                        vm.moveBy(p.id, steps)
                                        dragOffset -= steps * rowPx
                                    }
                                },
                                onDragEnd = { draggingId = null; dragOffset = 0f },
                                onTop = { vm.top(p.id) },
                            )
                        }
                        Spacer(Modifier.height(6.dp))
                    }
                    Spacer(Modifier.height(20.dp))
                }
            }
        }
    }
}

@Composable
private fun SortRow(
    index: Int,
    p: ProductDto,
    dragging: Boolean,
    dragOffset: Float,
    onDragStart: () -> Unit,
    onDrag: (Float) -> Unit,
    onDragEnd: () -> Unit,
    onTop: () -> Unit,
) {
    SectionCard(
        modifier = Modifier
            .padding(horizontal = 16.dp)
            .height(SORT_ROW_HEIGHT)
            .graphicsLayer {
                translationY = dragOffset
                if (dragging) {
                    scaleX = 1.02f
                    scaleY = 1.02f
                }
            },
    ) {
        Row(Modifier.fillMaxSize(), verticalAlignment = Alignment.CenterVertically) {
            // 拖动区：名称 + 事实（**不挂整行** —— 右边那个 ↑ 要留着自己的点击）
            // ⛔ 名称/售价/库存的外观与顺序全部来自 `ui/common/ProductCardKit.kt`
            //    （原来这里是自己拼的一行 `"¥… · 库存 …"`）。
            ProductLine(
                name = p.name,
                nameColor = p.nameColor,
                facts = productFacts(p.defaultUnitPrice, p.unit, p.stock, p.lowStockAlert),
                dense = true,
                bodyModifier = Modifier
                    .fillMaxHeight()
                    .pointerInput(p.id) {
                        detectDragGesturesAfterLongPress(
                            onDragStart = { onDragStart() },
                            onDrag = { change, drag -> change.consume(); onDrag(drag.y) },
                            onDragEnd = { onDragEnd() },
                            onDragCancel = { onDragEnd() },
                        )
                    },
                leading = {
                    Text(
                        (index + 1).toString(),
                        style = MaterialTheme.typography.titleMedium,
                        textAlign = TextAlign.Center,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.width(30.dp),
                    )
                },
                trailing = {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        IconButton(onClick = onTop) {
                            Icon(Icons.Default.VerticalAlignTop, contentDescription = "置顶", tint = Color(ProductPurple))
                        }
                        Icon(
                            Icons.Default.DragHandle,
                            contentDescription = "长按拖动排序",
                            tint = MaterialTheme.colorScheme.outline,
                        )
                        Spacer(Modifier.width(6.dp))
                    }
                },
            )
        }
    }
}
