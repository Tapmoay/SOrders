package com.tapmoay.sorders.ui.dispatcher

import androidx.compose.foundation.layout.*
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
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
 * | 批量固价（不参与打折）/ 恢复打折 | `PATCH /products/{id}` `{no_discount}`（CHG-0109：就是用户口语里的「固价」；语义只有一条 —— 订单打折时跳过它，⛔ 价格照旧可改） |
 * | 批量删除 | `DELETE /products/{id}`（**软删**，界面上撤不回来 —— 误删重建即可，见 CHG-0106） |
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

    /**
     * 「全选这一类」/「取消全选」作用在**当前看得见的那一批**（搜索/分类筛过之后的），不是整个库。
     *
     * ⚠️ 参数是 id 而不是 `List<ProductDto>`（CHG-0062）：筛选已经搬进共用零件
     * `ui/common/ProductCheckList.kt`，它算出来的「看得见的那一批」就是这几个 id，
     * 页面上再筛一遍 = 同一件事两份判据（两处一旦不一致，全选就会选中屏幕外的商品）。
     */
    fun toggleAll(ids: List<Long>) {
        val set = ids.toSet()
        selected = if (set.isNotEmpty() && set.all { it in selected }) selected - set else selected + set
    }

    fun clearSelection() {
        selected = emptySet()
    }

    /**
     * 点动作之前先问一句"勾了吗" —— 没勾就把话说在明处。
     *
     * ⚠️ 不能让弹层自己去说：`selected` 为空时弹层会写成"把**选中的 0 个**商品沽清？"，
     *    用户看到的是一句废话，还要再点一次「取消」。`run()` 里那道判据**保留**
     *    （界面上的入口堵住了，动作本身也得自证）。
     */
    fun canAct(): Boolean {
        if (selected.isEmpty()) {
            error = "先勾选商品"
            return false
        }
        return true
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

    /**
     * 批量「固价（不参与打折）」/「恢复打折」（CHG-0109，用户 2026-10-10 报的缺口）。
     *
     * ⚠️ 走**既有**的 `PATCH /products/{id}`（`no_discount`）—— 不新增端点、⛔ 一个价格字段都不碰。
     * ⛔ 文案不许写成「价格锁死/不能改价」：这个 flag 的语义**只有一条** —— 订单打折时跳过它；
     *    改默认单价、给批发商设专属价都不受影响（见 `backend/app/services/order_discount.py`）。
     */
    fun setNoDiscount(fixed: Boolean) = run(if (fixed) "设成固价（不参与打折）" else "设回参与打折") { p ->
        container.api.productApi.updateProduct(p.id, ProductUpdateRequest(noDiscount = fixed))
    }

    fun delete() = run("删除（软删，界面撤不回来）") { p ->
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
 * 把它扩成两种模式要让它同时承担两套模型。
 *
 * ## 勾选那一整块现在是共用零件（CHG-0062，2026-10-06）
 * 原来这里自己拼了「搜索框 + CategoryRail + LazyColumn + 全选这一类」，
 * 商品可见范围（`UsersManageScreen` 的第二层）要的是**同一套动作**，于是整套提到
 * `ui/common/ProductCheckList.kt`（三态分类头也一并搬过去：原来那个两态勾选框
 * 看不出"这一类勾了一半"）。这里的差别只剩回调：勾一行 = 选中这件商品。
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
    // 失败**必须**看得见（与商品管理页同一条规矩）：这一页以前只挂了 `vm.result`，
    // 于是 `vm.error`（"先勾选商品"这类）写进去之后**界面上一个字都没有**。
    OneShotSnackbar(snackbar, vm.error, onConsumed = { vm.error = null })

    var showCategoryPicker by remember { mutableStateOf(false) }
    var confirmingDelete by remember { mutableStateOf(false) }
    /**
     * 沽清（下架）/ 上架的二次确认（CHG-0025 / P29）：non-null = 弹层开着，
     * 值就是**这次要变成的状态**（`true` 上架 / `false` 沽清）。
     */
    var confirmingActive by remember { mutableStateOf<Boolean?>(null) }
    /**
     * 固价（不参与打折）的二次确认（CHG-0109）：non-null = 弹层开着，值就是这次要设成的状态
     * （`true` 固价 / `false` 恢复打折）。批量改折扣口径同样值得先问一句。
     */
    var confirmingFixed by remember { mutableStateOf<Boolean?>(null) }

    // ⚠️ 「搜索词 / 选中哪一分类 / 筛出来哪一批」这三样**不再在这里**：它们随着勾选那一块
    //    一起搬进了 `ProductCheckList`（搜索词仍由这里拿着 —— 见下面 keyword = vm.query）。

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
                    // ⚠️ 这两个胶囊只**打开确认弹层**，不许直接调 `vm.setActive(…)`：
                    //    批量沽清一下点掉一整页商品，比单卡更需要那一句确认（P29）。
                    //    `canAct()`：一个都没勾就别弹（弹层里写"选中的 0 个"是句废话）。
                    ActionChip("沽清（下架）", vm.acting) { if (vm.canAct()) confirmingActive = false }
                    ActionChip("上架", vm.acting) { if (vm.canAct()) confirmingActive = true }
                    // 固价（不参与打折）与恢复打折（CHG-0109）：与上下架同形 —— 只**打开确认弹层**，
                    // 不直接调 vm；`canAct()` 先把"一个都没勾"拦住（弹层里写"选中的 0 个"是废话）。
                    ActionChip("固价（不打折）", vm.acting) { if (vm.canAct()) confirmingFixed = true }
                    ActionChip("恢复打折", vm.acting) { if (vm.canAct()) confirmingFixed = false }
                    ActionChip("删除", vm.acting, danger = true) { confirmingDelete = true }
                }
                Spacer(Modifier.height(6.dp))
            }

            // ---- 搜索 + 左分类栏 + 勾选行：**共用那一份零件**（CHG-0062）----
            ProductCheckList(
                products = vm.products,
                checkedIds = vm.selected,
                onToggleProduct = { vm.toggle(it) },
                onToggleCategory = { _, _, ids -> vm.toggleAll(ids) },
                keyword = vm.query,
                onKeywordChange = { vm.query = it },
                modifier = Modifier.weight(1f),
                categoryOrder = vm.categories.map { it.name },
                loading = vm.loading,
                error = vm.loadError,
                onRetry = { vm.load() },
            )
        }
    }

    if (showCategoryPicker) {
        CategoryPickerSheet(
            title = "把这些商品改到哪个分组",
            choices = vm.categories.map { CategoryChoice(it.name, categoryCountLabel(it.productCount)) },
            current = "",
            onPick = { name -> showCategoryPicker = false; vm.setCategory(name) },
            onDismiss = { showCategoryPicker = false },
        )
    }

    if (confirmingDelete) {
        DangerConfirmDialog(
            title = "删除选中的 " + vm.selected.size + " 个商品？",
            message = "删除是软删：它们从列表里消失，但库存流水、订单行、账本都原样留着。" +
                "界面上撤不回来，删错了逐个重新建即可（商品重建成本低）。",
            confirmText = "删除",
            onConfirm = { confirmingDelete = false; vm.delete() },
            onDismiss = { confirmingDelete = false },
        )
    }

    // 固价（不参与打折）/ 恢复打折的确认（CHG-0109）：说清**它到底改了什么、没改什么** ——
    // 用户口语叫「固价」，系统里的规范词是「不参与打折」，同一个 `products.no_discount`。
    confirmingFixed?.let { fixed ->
        val n = vm.selected.size
        AlertDialog(
            onDismissRequest = { confirmingFixed = null },
            title = { Text(if (fixed) "把选中的 $n 个商品设成固价（不参与打折）？" else "把选中的 $n 个商品设回参与打折？") },
            text = {
                Text(
                    if (fixed) "设成固价后：订单打折会自动跳过这些商品（它们的行金额保持原价）；" +
                        "只打勾选的几行时，它们不能被勾。\n" +
                        "它们的价格照旧可以改（改单价、给批发商设专属价都不受影响）；" +
                        "已经打过的折不回溯。"
                    else "设回之后：这些商品和别的商品一样照常参与订单打折；已经打过的折同样不回溯。"
                )
            },
            confirmButton = { TextButton(onClick = { confirmingFixed = null; vm.setNoDiscount(fixed) }) { Text(if (fixed) "设成固价" else "恢复打折") } },
            dismissButton = { TextButton(onClick = { confirmingFixed = null }) { Text("取消") } },
        )
    }

    // 沽清 / 上架的确认（CHG-0025 / P29）：与商品管理页**同一个弹层、同一份文案**。
    confirmingActive?.let { target ->
        ProductActiveConfirmDialog(
            toActive = target,
            subject = "选中的 " + vm.selected.size + " 个商品",
            onConfirm = { confirmingActive = null; vm.setActive(target) },
            onDismiss = { confirmingActive = null },
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
