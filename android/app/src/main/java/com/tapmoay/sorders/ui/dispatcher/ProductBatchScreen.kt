package com.tapmoay.sorders.ui.dispatcher

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.data.remote.api.ProductUpdateRequest
import com.tapmoay.sorders.data.remote.dto.ProductCategoryDto
import com.tapmoay.sorders.data.remote.dto.ProductDto
import com.tapmoay.sorders.data.repo.toApiException
import com.tapmoay.sorders.ui.common.*
import com.tapmoay.sorders.ui.theme.ProductPurple
import kotlinx.coroutines.launch

/**
 * 「批量操作」（用户 2026-09-21 点名要的底栏第三格：「右边那个**批量操作**」）。
 *
 * ## 它只做商品管理里**真的存在**的动作
 * | 动作 | 走哪个接口 |
 * |---|---|
 * | 批量改分组 | `PATCH /products/{id}` `{category}`（后端会自动把这个分类补进名册） |
 * | 批量沽清 / 上架 | `PATCH /products/{id}` `{is_active}` |
 * | 批量删除 | `DELETE /products/{id}`（**软删**，去「回收站」恢复） |
 *
 * ⛔ **不做"批量改库存"**：库存只能走出入库流水（`inventory_service` 里那条
 * `UPDATE ... WHERE stock + delta >= 0`）。批量改数字 = 账实不符，而且整套流水对不上。
 * ⛔ **不新增后端端点**：逐条调上面这些已有接口 —— 好处是每条改动都由后端各自写一行
 * `operation_logs`（与人工逐条操作同形、可回查），也不用动 AI 写能力的覆盖表。
 *
 * ## 代价如实说：逐条 = N 次请求
 * 用户上一轮已经表过态（「如果用户说全部都做的话…可以搞几分钟」「就做这 50 个，那可能其实很快了」），
 * 所以**不设条数上限**，用进度 + 逐条结果来消化。执行完必须**逐条汇报**
 * （「成功 18 / 失败 2」+ 点名失败的那几个），不能一句"已完成"盖住 —— 那是 AI 那边
 * `AiWriteHandler.commitNote` 的由来，这里是同一个道理。
 */
class ProductBatchViewModel(private val container: AppContainer) : ViewModel() {

    var products by mutableStateOf<List<ProductDto>>(emptyList())
    var categories by mutableStateOf<List<ProductCategoryDto>>(emptyList())
    var loading by mutableStateOf(true)
    var loadError by mutableStateOf<String?>(null)

    var query by mutableStateOf("")
    var acting by mutableStateOf(false)
    var error by mutableStateOf<String?>(null)

    /** 执行结果（成功几条、失败哪几条）——用一次性提示条显示。 */
    var result by mutableStateOf<String?>(null)

    /** 勾选中的商品 id。 */
    var selected by mutableStateOf<Set<Long>>(emptySet())
        private set

    init {
        load()
    }

    fun load() {
        loading = products.isEmpty()
        loadError = null
        viewModelScope.launch {
            try {
                products = container.repo.products()
                categories = container.repo.productCategories()
            } catch (e: Exception) {
                loadError = toApiException(e).message
            } finally {
                loading = false
            }
        }
    }

    fun toggle(id: Long) {
        selected = if (id in selected) selected - id else selected + id
    }

    /** 「全选」/「取消全选」作用在**当前看得见的那一批**（搜索/分类筛过之后的），不是整个库。 */
    fun toggleAll(visible: List<ProductDto>) {
        val ids = visible.map { it.id }.toSet()
        selected = if (ids.isNotEmpty() && ids.all { it in selected }) selected - ids else selected + ids
    }

    fun clearSelection() {
        selected = emptySet()
    }

    /** 逐条执行 [op]，收集成功/失败，最后给一句**能核对**的汇报。 */
    private fun run(label: String, op: suspend (ProductDto) -> Unit) {
        val targets = products.filter { it.id in selected }
        if (targets.isEmpty()) {
            error = "先勾选商品"
            return
        }
        acting = true
        error = null
        viewModelScope.launch {
            val failed = mutableListOf<String>()
            var ok = 0
            for (p in targets) {
                try {
                    op(p)
                    ok++
                } catch (e: Exception) {
                    failed += p.name + "（" + toApiException(e).message + "）"
                }
            }
            // ⚠️ 汇报必须是**逐条**的：只写"已完成"，失败的那几个就被盖住了
            result = buildString {
                append(label)
                append("：成功 ").append(ok).append(" / ").append(targets.size)
                if (failed.isNotEmpty()) {
                    append("；失败 ").append(failed.size).append(" —— ")
                    append(failed.take(5).joinToString("、"))
                    if (failed.size > 5) append(" 等")
                }
            }
            selected = emptySet()
            acting = false
            load()
        }
    }

    fun setCategory(name: String) = run("改分组到「" + name.ifBlank { "未分类" } + "」") { p ->
        container.api.productApi.updateProduct(p.id, ProductUpdateRequest(category = name.trim()))
    }

    fun setActive(active: Boolean) = run(if (active) "上架" else "沽清") { p ->
        container.api.productApi.updateProduct(p.id, ProductUpdateRequest(isActive = active))
    }

    fun delete() = run("删除（软删，可去回收站恢复）") { p ->
        container.api.productApi.deleteProduct(p.id)
    }
}

/**
 * 批量操作页：**上选动作、下勾商品、底部执行**。
 *
 * 版式沿用商品管理页那一套（搜索框横跨整页 + 左边分类 + 右边列表），分类判据走
 * `CategoryRail` / `categoryTabsOf` —— **不许各写一份**（各写一份会出现"同一件商品
 * 在这里属于日化、在商品管理页属于未分类"）。
 *
 * ⚠️ 勾选这一步**没有复用选品页那个全屏弹层**（`ProductPickerBody`）：那一个的状态机是
 * "挑商品 + 填数量 + 汇总金额加入清单"，而这里是"打勾 + 批量改属性"——
 * 把它扩成两种模式要让它同时承担两套模型。这里复用**判据与导航条**（真正共用的那部分）。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ProductBatchScreen(
    container: AppContainer,
    onBack: () -> Unit,
) {
    val vm: ProductBatchViewModel = appViewModel { ProductBatchViewModel(container) }
    val snackbar = remember { SnackbarHostState() }
    OneShotSnackbar(snackbar, vm.result, onConsumed = { vm.result = null })

    var showCategoryPicker by remember { mutableStateOf(false) }
    var confirmingDelete by remember { mutableStateOf(false) }

    val cats = remember(vm.products, vm.categories) { categoryTabs(vm.products, vm.categories.map { it.name }) }
    var category by remember { mutableStateOf(ALL_CATEGORY) }
    LaunchedEffect(cats) { if (category !in cats) category = ALL_CATEGORY }
    val keyword = vm.query.trim()
    val visible = remember(vm.products, category, keyword) {
        vm.products
            .filter { category == ALL_CATEGORY || categoryOf(it) == category }
            .filter { keyword.isEmpty() || it.name.contains(keyword, ignoreCase = true) }
    }

    Scaffold(
        snackbarHost = { SnackbarHost(snackbar) },
        topBar = {
            TopAppBar(
                colors = TopAppBarDefaults.topAppBarColors(containerColor = MaterialTheme.colorScheme.background),
                title = { Text("批量操作", style = MaterialTheme.typography.titleLarge) },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
                    }
                },
            )
        },
        bottomBar = {
            Surface(shadowElevation = 8.dp) {
                Row(
                    Modifier
                        .fillMaxWidth()
                        .navigationBarsPadding()
                        .padding(horizontal = 16.dp, vertical = 10.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text(
                        "已选 " + vm.selected.size + " 个",
                        style = MaterialTheme.typography.bodyMedium,
                        modifier = Modifier.weight(1f),
                    )
                    if (vm.selected.isNotEmpty()) {
                        TextButton(onClick = { vm.clearSelection() }, enabled = !vm.acting) { Text("清空") }
                    }
                }
            }
        },
    ) { padding ->
        Column(Modifier.fillMaxSize().padding(padding)) {
            // ---- 动作区：选一个动作再执行（不选就只是"挑选商品"）----
            Column(Modifier.fillMaxWidth().padding(horizontal = 16.dp)) {
                Spacer(Modifier.height(6.dp))
                Text("先勾商品，再点一个动作", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                Spacer(Modifier.height(6.dp))
                FlowRow2 {
                    ActionChip("改分组", vm.acting) { showCategoryPicker = true }
                    ActionChip("沽清（下架）", vm.acting) { vm.setActive(false) }
                    ActionChip("上架", vm.acting) { vm.setActive(true) }
                    ActionChip("删除", vm.acting, danger = true) { confirmingDelete = true }
                }
                Spacer(Modifier.height(6.dp))
            }

            // ---- 搜索（横跨整页，与商品管理页同一个位置与理由）----
            OutlinedTextField(
                value = vm.query,
                onValueChange = { vm.query = it },
                placeholder = { Text("搜索商品名称", style = MaterialTheme.typography.bodySmall) },
                leadingIcon = { Icon(Icons.Default.Search, contentDescription = null, modifier = Modifier.size(20.dp)) },
                trailingIcon = {
                    if (vm.query.isNotEmpty()) {
                        IconButton(onClick = { vm.query = "" }) {
                            Icon(Icons.Default.Close, contentDescription = "清空搜索", modifier = Modifier.size(18.dp))
                        }
                    }
                },
                singleLine = true,
                textStyle = MaterialTheme.typography.bodyMedium,
                modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 6.dp),
            )

            when {
                vm.loading -> LoadingBox()
                vm.loadError != null -> ErrorView(vm.loadError.orEmpty(), onRetry = { vm.load() })
                vm.products.isEmpty() -> EmptyView("暂无商品")
                else -> Row(Modifier.weight(1f)) {
                    CategoryRail(
                        tabs = cats,
                        selected = category,
                        onSelect = { category = it },
                        modifier = Modifier.width(92.dp).fillMaxHeight(),
                    )
                    Box(Modifier.weight(1f).fillMaxHeight()) {
                        if (visible.isEmpty()) {
                            EmptyView(
                                if (keyword.isNotEmpty()) "没有名称含「" + keyword + "」的商品" else "「" + category + "」下暂无商品",
                                Modifier.align(Alignment.Center),
                            )
                        } else {
                            LazyColumn(
                                Modifier.fillMaxSize(),
                                contentPadding = PaddingValues(start = 8.dp, end = 10.dp, top = 6.dp, bottom = 12.dp),
                                verticalArrangement = Arrangement.spacedBy(4.dp),
                            ) {
                                item {
                                    Row(verticalAlignment = Alignment.CenterVertically) {
                                        val allOn = visible.all { it.id in vm.selected }
                                        Checkbox(checked = allOn, onCheckedChange = { vm.toggleAll(visible) })
                                        Text("全选这一类（" + visible.size + "）", style = MaterialTheme.typography.bodyMedium)
                                    }
                                }
                                items(visible, key = { it.id }) { p ->
                                    val on = p.id in vm.selected
                                    // ⛔ 行外观全部来自 `ui/common/ProductCardKit.kt`：
                                    //    勾选框是**前置槽**、图是**缩略图槽**、售价与库存来自
                                    //    `productFacts()`（顺序与配色都定在那儿，五个页面同源）。
                                    //    原来这里是自己拼的一行 `"¥… · 库存 …"` —— 那正是
                                    //    用户 2026-09-21 说的「其他地方你也得改」要消灭的东西。
                                    ProductLine(
                                        name = p.name,
                                        nameColor = p.nameColor,
                                        facts = productFacts(p.defaultUnitPrice, p.unit, p.stock, p.lowStockAlert),
                                        dense = true,
                                        modifier = Modifier
                                            .clickable { vm.toggle(p.id) }
                                            .padding(vertical = 4.dp),
                                        leading = {
                                            Checkbox(checked = on, onCheckedChange = { vm.toggle(p.id) })
                                        },
                                        thumb = {
                                            ProductThumb(imageUrl = p.imageUrl, nameColor = p.nameColor, size = 40.dp)
                                        },
                                        badge = if (p.isActive) null else ({ ProductSoldOutBadge() }),
                                    )
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    if (showCategoryPicker) {
        CategoryPickerSheet(
            title = "把这些商品改到哪个分组",
            choices = vm.categories.map { CategoryChoice(it.name, it.productCount.toString() + " 个商品") },
            current = "",
            onPick = { name -> showCategoryPicker = false; vm.setCategory(name) },
            onDismiss = { showCategoryPicker = false },
        )
    }

    if (confirmingDelete) {
        DangerConfirmDialog(
            title = "删除选中的 " + vm.selected.size + " 个商品？",
            message = "删除是软删：它们从列表里消失，但库存流水、订单行、账本都原样留着。" +
                "列表顶端的「回收站」里可以逐个恢复。",
            confirmText = "删除",
            onConfirm = { confirmingDelete = false; vm.delete() },
            onDismiss = { confirmingDelete = false },
        )
    }
}

/** 动作小胶囊（批量页顶部那一排）。 */
@Composable
private fun ActionChip(label: String, busy: Boolean, danger: Boolean = false, onClick: () -> Unit) {
    val color = if (danger) MaterialTheme.colorScheme.error else Color(ProductPurple)
    OutlinedButton(
        onClick = onClick,
        enabled = !busy,
        shape = MaterialTheme.shapes.small,
        border = androidx.compose.foundation.BorderStroke(1.2.dp, color),
        colors = ButtonDefaults.outlinedButtonColors(contentColor = color),
        contentPadding = PaddingValues(horizontal = 12.dp, vertical = 6.dp),
        modifier = Modifier.height(36.dp),
    ) {
        Text(label, style = MaterialTheme.typography.labelLarge, fontWeight = FontWeight.Bold, maxLines = 1)
    }
}

/** 动作那一排的布局：`FlowRow` 在本项目里已是标准写法（§5：chips 用 FlowRow 防竖排换行）。 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun FlowRow2(content: @Composable FlowRowScope.() -> Unit) {
    FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(4.dp), content = content)
}
