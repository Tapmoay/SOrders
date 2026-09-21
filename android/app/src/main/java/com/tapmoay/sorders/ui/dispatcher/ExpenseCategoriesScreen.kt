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
import com.tapmoay.sorders.core.ExpenseLink
// 位次输入框的数字过滤走 `InputRules.intInput`（红线：手写 filter = 规则的一份副本）
import com.tapmoay.sorders.core.InputRules
import com.tapmoay.sorders.data.remote.dto.ExpenseCategoryDto
import com.tapmoay.sorders.data.repo.toApiException
import com.tapmoay.sorders.ui.common.*
import kotlinx.coroutines.launch

/**
 * 开销分类管理（2026-09-20 用户第六轮：「开销分类……也有个分类管理」）。
 *
 * 与「商品分类管理」「地点分组管理」**同一套规矩**（改之前先读
 * `ProductCategoriesViewModel` 顶部那两段）：
 * · 建 / 改名（**级联**改掉挂着的开销）/ 删除（**还有开销挂着时后端拒绝**，把那句话原样给用户看）；
 * · **排序是本地草稿**，点「保存顺序」才提交（后端要求整份顺序，拖一下就发一次会留下半新半旧的顺序）；
 * · 排序两种方式（填位次 / 上下移）**共用 `moveItemTo`**（商品/地点那边已经泛化好的那一份）。
 *
 * 这一页比商品那边**多一列**「主要关联」：开销卡片上突出哪一项由它决定
 * （用户：「燃油/维修主要是车辆 → 首要突出车辆……**不能一刀切**」）。
 *
 * ⚠️ 名册外的分类（`id == 0`，老数据）**排在最后、不能改名/删除/排序** ——
 *    它名下的开销仍然照常显示（不在名册里 ≠ 那笔钱不存在）。
 */
class ExpenseCategoriesViewModel(private val container: AppContainer) : ViewModel() {

    val categories = mutableStateListOf<ExpenseCategoryDto>()
    var loading by mutableStateOf(true)
        private set
    var busy by mutableStateOf(false)
        private set
    var loadError by mutableStateOf<String?>(null)
    var error by mutableStateOf<String?>(null)
    var notice by mutableStateOf<String?>(null)

    /** (id 或 null=新建, 当前名字) */
    var editing by mutableStateOf<Pair<Long?, String>?>(null)
    var deleting by mutableStateOf<ExpenseCategoryDto?>(null)

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
                val list = container.repo.expenseCategories()
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

    fun openRename(c: ExpenseCategoryDto) {
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
        // 三条规则只有一处实现（`ui/common/CategoryRoster.kt`）：见那里的文件头
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
                val list = container.repo.reorderExpenseCategories(ids)
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
                    container.repo.createExpenseCategory(name)
                    notice = "已新建分类「$name」"
                } else {
                    container.repo.updateExpenseCategory(id, name = name)
                    notice = "已改名为「$name」（挂在这个分类下的开销一起改了）"
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

    /** 改「这类开销卡片上突出哪一项」。 */
    fun setLinkKind(c: ExpenseCategoryDto, kind: String) {
        if (c.id <= 0 || c.linkKind == kind) return
        busy = true
        error = null
        viewModelScope.launch {
            try {
                container.repo.updateExpenseCategory(c.id, linkKind = kind)
                notice = "「${c.name}」的卡片现在突出：" + ExpenseLink.label(kind)
                load()
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                busy = false
            }
        }
    }

    fun askDelete(c: ExpenseCategoryDto) {
        deleting = c
    }

    fun confirmDelete(c: ExpenseCategoryDto) {
        busy = true
        error = null
        viewModelScope.launch {
            try {
                container.repo.deleteExpenseCategory(c.id)
                deleting = null
                notice = "已删除分类「${c.name}」"
                load()
            } catch (e: Exception) {
                // 后端会因为"还有开销挂着"而拒绝 —— 那句话带数量，原样给用户看
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
fun ExpenseCategoriesScreen(container: AppContainer, onBack: () -> Unit) {
    val vm: ExpenseCategoriesViewModel = appViewModel { ExpenseCategoriesViewModel(container) }
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
                title = { Text("开销分类管理", style = MaterialTheme.typography.titleLarge) },
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
                        "顺序 = 开销页左边那一列的顺序；「主要关联」决定开销卡片上突出哪一项"
                            + "（比如燃油选「车辆」，卡片上就显示车牌）。",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                items(vm.categories, key = { it.id }) { c ->
                    ExpenseCategoryRow(
                        c = c,
                        position = vm.categories.indexOf(c) + 1,
                        busy = vm.busy,
                        onMoveTo = { vm.moveTo(c.id, it) },
                        onUp = { vm.moveBy(c.id, -1) },
                        onDown = { vm.moveBy(c.id, 1) },
                        onRename = { vm.openRename(c) },
                        onDelete = { vm.askDelete(c) },
                        onLinkKind = { vm.setLinkKind(c, it) },
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
            title = { Text(if (id == null) "新建开销分类" else "改分类名") },
            text = {
                Column {
                    SoTextField(text, { text = it }, placeholder = "分类名（如 违章罚款）")
                    if (id != null) {
                        Spacer(Modifier.height(6.dp))
                        Text(
                            "改名会连带改掉挂在这个分类下的所有开销（不改的话那些开销会变成孤儿）。",
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

    // 删除确认（危险操作二次确认；后端还会挡"还有开销挂着"）
    vm.deleting?.let { c ->
        DangerConfirmDialog(
            title = "删除分类「${c.name}」？",
            message = "还有开销挂在这个分类下时会被拒绝（不会把那些开销改成别的分类）。",
            confirmText = "删除",
            onConfirm = { vm.confirmDelete(c) },
            onDismiss = { vm.deleting = null },
        )
    }
}

/** 名册里的一行：位次框 + 名字 + 「主要关联」下拉 + 上下移 + 改名/删除。 */
@Composable
private fun ExpenseCategoryRow(
    c: ExpenseCategoryDto,
    position: Int,
    busy: Boolean,
    onMoveTo: (Int) -> Unit,
    onUp: () -> Unit,
    onDown: () -> Unit,
    onRename: () -> Unit,
    onDelete: () -> Unit,
    onLinkKind: (String) -> Unit,
) {
    var posText by remember(c.id, position) { mutableStateOf(position.toString()) }
    SectionCard {
        Row(verticalAlignment = Alignment.CenterVertically) {
            // 位次：填几就排到第几（0/越界夹到两端）—— 与商品分类管理同一个交互
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
                Text(
                    c.name + if (c.id == 0L) "（名册外）" else "",
                    style = MaterialTheme.typography.titleSmall,
                    fontWeight = FontWeight.Bold,
                )
                Text(
                    if (c.id == 0L) "老数据里的分类名，改不了也排不了序；它名下的开销照常显示"
                    else "共 " + c.expenseCount + " 笔 · 卡片突出：" + ExpenseLink.label(c.linkKind),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            IconButton(onClick = onUp, enabled = !busy) { Icon(Icons.Default.KeyboardArrowUp, contentDescription = "上移") }
            IconButton(onClick = onDown, enabled = !busy) { Icon(Icons.Default.KeyboardArrowDown, contentDescription = "下移") }
        }
        if (c.id != 0L) {
            Spacer(Modifier.height(6.dp))
            Row(verticalAlignment = Alignment.CenterVertically) {
                DropField(
                    label = "卡片突出哪一项",
                    text = ExpenseLink.label(c.linkKind),
                    options = ExpenseLink.CHOICES.map { it.first to it.second },
                    onSelect = onLinkKind,
                    modifier = Modifier.weight(1f),
                )
                Spacer(Modifier.width(6.dp))
                IconButton(onClick = onRename, enabled = !busy) { Icon(Icons.Default.Edit, contentDescription = "改名") }
                IconButton(onClick = onDelete, enabled = !busy) {
                    Icon(Icons.Default.DeleteOutline, contentDescription = "删除", tint = MaterialTheme.colorScheme.error)
                }
            }
        }
    }
}
