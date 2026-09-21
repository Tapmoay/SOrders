package com.tapmoay.sorders.ui.dispatcher

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.text.KeyboardOptions
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
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.tapmoay.sorders.core.AppContainer
// 位次输入框的数字过滤走 `InputRules.intInput`（红线：手写 filter = 规则的一份副本）
import com.tapmoay.sorders.core.InputRules
import com.tapmoay.sorders.data.remote.dto.FreightCategoryDto
import com.tapmoay.sorders.data.repo.toApiException
import com.tapmoay.sorders.ui.common.*
import kotlinx.coroutines.launch

/**
 * 运费分类管理（2026-09-21 用户：「**他那个运费模板是有自己的一套分类的**，
 * 只是我们复用他那个**代码和方法**」）。
 *
 * 与「商品分类管理」「开销分类管理」「地点分组管理」**同一套规矩**（改之前先读
 * `ExpenseCategoriesViewModel` 顶部那两段）：
 * · 建 / 改名（**不需要级联**：运费模板与计费规则都按**编号**关联，改名天然安全）/ 删除
 *   （**还有价目或规则挂着时后端拒绝**，把那句话原样给用户看 —— 带数量）；
 * · **排序是本地草稿**，点「保存顺序」才提交（后端要求整份顺序）；
 * · 两种排序方式（填位次 / 上下移）共用 `moveItemTo`（商品那边泛化好的那一份）。
 *
 * ⚠️ 这一页管的是**两件事共用的分类**：① 运费模板"算哪几类货"；② 司机计费规则"按分类定价"。
 *    所以每一行都写明"有几条价目、几份规则在用" —— 删之前要看得见。
 */
class FreightCategoriesViewModel(private val container: AppContainer) : ViewModel() {

    val categories = mutableStateListOf<FreightCategoryDto>()
    var loading by mutableStateOf(true)
        private set
    var busy by mutableStateOf(false)
        private set
    var loadError by mutableStateOf<String?>(null)
    var error by mutableStateOf<String?>(null)
    var notice by mutableStateOf<String?>(null)

    /** (id 或 null=新建, 当前名字) */
    var editing by mutableStateOf<Pair<Long?, String>?>(null)
    var deleting by mutableStateOf<FreightCategoryDto?>(null)

    var dirty by mutableStateOf(false)
        private set
    private var savedOrder: List<Long> = emptyList()

    init {
        load()
    }

    fun load() {
        loading = categories.isEmpty()
        loadError = null
        viewModelScope.launch {
            try {
                val list = container.repo.freightCategories()
                categories.clear()
                categories.addAll(list)
                savedOrder = list.map { it.id }
                dirty = false
            } catch (e: Exception) {
                loadError = toApiException(e).message
            } finally {
                loading = false
            }
        }
    }

    fun openCreate() {
        editing = null to ""
    }

    fun openRename(c: FreightCategoryDto) {
        editing = c.id to c.name
    }

    /** 排序：把某一项挪到第 [position] 位（1-based；0/越界夹到两端）。填数字与上下移都走它。 */
    fun moveTo(id: Long, position: Int) {
        val next = moveItemTo(categories, { it.id }, id, position)
        if (next === categories) return
        categories.clear()
        categories.addAll(next)
        dirty = orderChanged(categories, savedOrder) { it.id }
    }

    fun moveBy(id: Long, steps: Int) {
        val idx = categories.indexOfFirst { it.id == id }
        if (idx < 0) return
        moveTo(id, idx + 1 + steps)
    }

    fun revertOrder() {
        if (savedOrder.isEmpty()) return
        // ⚠️ 原来这里是"只按 savedOrder 重建"的那一版 —— 会把**保存之后新建的分类**从列表里丢掉
        //    （后端还在，用户以为被删了）。开销/商品那两页一直是保留的，三页两种行为。
        //    三条规则现在只有一处实现：`ui/common/CategoryRoster.kt`。
        val back = revertedOrder(categories, savedOrder) { it.id }
        categories.clear()
        categories.addAll(back)
        dirty = false
    }

    fun saveOrder() {
        // ⚠️ 只提交**名册里的**（id > 0）：名册外的那些后端不认识，带上就被整体拒绝
        val ids = submittableIds(categories) { it.id }
        if (ids.isEmpty()) return
        busy = true
        error = null
        viewModelScope.launch {
            try {
                val list = container.repo.reorderFreightCategories(ids)
                categories.clear()
                categories.addAll(list)
                savedOrder = list.map { it.id }
                dirty = false
                notice = "顺序已保存"
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                busy = false
            }
        }
    }

    fun submit(id: Long?, rawName: String) {
        val name = rawName.trim()
        if (name.isBlank()) {
            error = "分类名不能为空"
            return
        }
        busy = true
        error = null
        viewModelScope.launch {
            try {
                if (id == null) {
                    container.repo.createFreightCategory(
                        com.tapmoay.sorders.data.remote.dto.FreightCategoryCreateRequest(name)
                    )
                    notice = "已新建分类「$name」"
                } else {
                    container.repo.updateFreightCategory(
                        id,
                        com.tapmoay.sorders.data.remote.dto.FreightCategoryUpdateRequest(name = name),
                    )
                    notice = "已改名为「$name」（价目和计费规则都是按编号挂的，不用改）"
                }
                editing = null
                load()
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                busy = false
            }
        }
    }

    fun askDelete(c: FreightCategoryDto) {
        deleting = c
    }

    fun confirmDelete(c: FreightCategoryDto) {
        busy = true
        error = null
        viewModelScope.launch {
            try {
                container.repo.deleteFreightCategory(c.id)
                deleting = null
                notice = "已删除分类「${c.name}」"
                load()
            } catch (e: Exception) {
                // 后端会因为"还有价目/规则挂着"而拒绝 —— 那句话带数量，原样给用户看
                error = toApiException(e).message
                deleting = null
            } finally {
                busy = false
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun FreightCategoriesScreen(container: AppContainer, onBack: () -> Unit) {
    val vm: FreightCategoriesViewModel = appViewModel { FreightCategoriesViewModel(container) }
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
                title = { Text("运费分类管理", style = MaterialTheme.typography.titleLarge) },
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
                    Text(
                        "这一套分类是「运费模板」与「司机计费规则」共用的：价目挂哪几类货、「按分类定价」"
                            + "按哪几类给司机算钱，都看它。顺序 = 运费模板页左边那一列的顺序。",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                items(vm.categories, key = { it.id }) { c ->
                    FreightCategoryRow(
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
            title = { Text(if (id == null) "新建运费分类" else "改分类名") },
            text = {
                Column {
                    SoTextField(text, { text = it }, placeholder = "分类名（如 冻品）")
                    if (id != null) {
                        Spacer(Modifier.height(6.dp))
                        Text(
                            "改名不需要连带改价目/规则（它们按编号挂），但已经派出去的单上" +
                                "留的是当时的名字快照，不追改。",
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

    // 删除确认（后端还会挡"还有价目/规则挂着"）
    vm.deleting?.let { c ->
        DangerConfirmDialog(
            title = "删除分类「${c.name}」？",
            message = "还有运费价目或计费规则挂着它时会被拒绝（不会顺手把它们改成别的分类）。",
            confirmText = "删除",
            onConfirm = { vm.confirmDelete(c) },
            onDismiss = { vm.deleting = null },
        )
    }
}

/** 名册里的一行：位次框 + 名字 + "有几条价目/几份规则在用" + 上下移 + 改名/删除。 */
@Composable
private fun FreightCategoryRow(
    c: FreightCategoryDto,
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
            OutlinedTextField(
                value = posText,
                // ⚠️ 数字过滤走 `InputRules`（手写 filter 就是规则的一份副本，见红线）
                onValueChange = { v ->
                    val digits = InputRules.intInput(v, 3)
                    posText = digits
                    digits.toIntOrNull()?.let(onMoveTo)
                },
                singleLine = true,
                modifier = Modifier.width(64.dp),
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
            )
            Spacer(Modifier.width(10.dp))
            Column(Modifier.weight(1f)) {
                Text(c.name, style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Bold)
                Text(
                    "价目 " + c.templateCount + " 条 · 计费规则 " + c.ruleCount + " 份",
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
