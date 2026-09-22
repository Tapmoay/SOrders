package com.tapmoay.sorders.ui.dispatcher

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.DeleteOutline
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.KeyboardArrowDown
import androidx.compose.material.icons.filled.KeyboardArrowUp
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import com.tapmoay.sorders.core.AppContainer
// 位次输入框的数字过滤走 `InputRules.intInput`（红线：手写 filter = 规则的一份副本）
import com.tapmoay.sorders.core.InputRules
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
        when {
            vm.loading -> LoadingBox(Modifier.padding(padding))
            vm.loadError != null -> ErrorView(vm.loadError.orEmpty(), onRetry = { vm.load() })
            else -> LazyColumn(
                Modifier.fillMaxSize().padding(padding),
                contentPadding = PaddingValues(16.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                item {
                    Hint(
                        "顺序 = 预订单页左边那一列分类的顺序。改名会连带改掉挂着的预设单（同一次提交里改完），"
                            + "删除要先把挂着的预设单改成别的分类。",
                        style = MaterialTheme.typography.bodySmall,
                        // 强调色用预订单功能的语义色（与工作台那一格、预订单页的图标同色）
                        color = Color(TemplateIndigo),
                    )
                }
                items(vm.categories, key = { it.id }) { c ->
                    OrderTemplateCategoryRow(
                        c = c,
                        position = vm.categories.indexOf(c) + 1,
                        busy = vm.busy,
                        onMoveTo = { vm.moveTo(c.id, it) },
                        onUp = { vm.moveBy(c.id, -1) },
                        onDown = { vm.moveBy(c.id, 1) },
                        onRename = { vm.openRename(c) },
                        onDelete = { vm.askDelete(c) },
                    )
                }
                if (vm.dirty) {
                    item {
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            OutlinedButton(onClick = { vm.revertOrder() }, enabled = !vm.busy) { Text("撤销改动") }
                            Button(onClick = { vm.saveOrder() }, enabled = !vm.busy) { Text("保存顺序") }
                        }
                    }
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

/** 名册里的一行：位次框 + 名字 + "有几张预设单挂着" + 上下移 + 改名/删除。 */
@Composable
private fun OrderTemplateCategoryRow(
    c: OrderTemplateCategoryDto,
    position: Int,
    busy: Boolean,
    onMoveTo: (Int) -> Unit,
    onUp: () -> Unit,
    onDown: () -> Unit,
    onRename: () -> Unit,
    onDelete: () -> Unit,
) {
    var posText by remember(c.id, position) { mutableStateOf(position.toString()) }
    SectionCard {
        Row(verticalAlignment = Alignment.CenterVertically) {
            // ⚠️ 位次框用 `SoTextField`（本项目的 iOS 风输入框）**不是**运费页那个描边输入框：
            //    全库描边输入框"只许减不许增"（基线 `_tools/qa/_form_panel_baseline.txt`），
            //    新页面加一个就会把那页又变回"一堆矩形框浮在灰底上"。
            SoTextField(
                value = posText,
                // ⚠️ 数字过滤走 `InputRules`（手写 filter 就是规则的一份副本，见红线）
                onValueChange = { v ->
                    val digits = InputRules.intInput(v, 3)
                    posText = digits
                    digits.toIntOrNull()?.let(onMoveTo)
                },
                placeholder = "位次",
                keyboardType = KeyboardType.Number,
                modifier = Modifier.width(64.dp),
            )
            Spacer(Modifier.width(10.dp))
            Column(Modifier.weight(1f)) {
                Text(c.name, style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Bold)
                // 只有这一个计数（运费那页有"价目 / 计费规则"两个）——
                // 它是删除前的唯一判据，所以挂在每一行上，删之前看得见。
                Text(
                    "预设单 " + c.templateCount + " 张",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            IconButton(onClick = onUp, enabled = !busy) { Icon(Icons.Default.KeyboardArrowUp, contentDescription = "上移") }
            IconButton(onClick = onDown, enabled = !busy) { Icon(Icons.Default.KeyboardArrowDown, contentDescription = "下移") }
            IconButton(onClick = onRename, enabled = !busy) { Icon(Icons.Default.Edit, contentDescription = "改名") }
            IconButton(onClick = onDelete, enabled = !busy) {
                Icon(Icons.Default.DeleteOutline, contentDescription = "删除", tint = MaterialTheme.colorScheme.error)
            }
        }
    }
}

/**
 * 预订单功能的语义色：**靛蓝**（与工作台那一格、预订单页的图标同色）。
 * ⛔ 别改用橙色 —— 橙色在这个 App 里是**钱**（账本 / 收款）。
 */
private const val TemplateIndigo = 0xFF3949ABL
