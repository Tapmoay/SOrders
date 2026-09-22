package com.tapmoay.sorders.ui.dispatcher

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.core.InputRules
import com.tapmoay.sorders.data.remote.dto.SupplierCreateRequest
import com.tapmoay.sorders.data.remote.dto.SupplierDto
import com.tapmoay.sorders.data.remote.dto.SupplierUpdateRequest
import com.tapmoay.sorders.data.repo.toApiException
import com.tapmoay.sorders.ui.common.*
import com.tapmoay.sorders.ui.theme.CashOut
import com.tapmoay.sorders.util.formatMoney
import kotlinx.coroutines.launch

/**
 * 「供应商 / 厂商」档案页（2026-09-22 用户要求，账本管理「支出」那一块）。
 *
 * ## 用户原话与拍板
 * > 「支出主要是**给某个供应商或者说是厂商支付尾款**……**购买一个装备或者说是设备**……
 * > 比如说类似**邮费**啊」；拍板口径：**跟客户一个量级的档案**（**可挂账、可查还欠多少、可分次付款**）。
 *
 * ## 这一页回答什么
 * 「我有哪些供应商、**各自还欠多少**」。点一行进他的账（几笔应付、每笔付了多少钱、什么时候付的）。
 *
 * ## ⛔ 三个数一律取服务端
 * `payableTotal` / `paidTotal` / `unpaidTotal` 都是后端算好的（口径只有一处：
 * `backend/app/services/supplier_service.py`）。**界面上一个减法都不做** ——
 * 界面上再减一遍就是第二个口径，哪天两边不一样，谁都不知道该信哪个。
 */
class SuppliersViewModel(private val container: AppContainer) : ViewModel() {

    var rows by mutableStateOf<List<SupplierDto>>(emptyList())
        private set
    var loading by mutableStateOf(true)
        private set
    var loadError by mutableStateOf<String?>(null)
    var actionResult by mutableStateOf<String?>(null)

    /**
     * 刚删掉的那一条（给界面那条带「撤回」的 snackbar 用）。
     *
     * 用户定的硬规矩：**删除一律软删 + 手边要有一个撤销入口**。所以删完不是一句"已删除"
     * 就完了，而是把「撤回」摆在同一个位置上。
     */
    var lastDeleted by mutableStateOf<SupplierDto?>(null)
        private set

    /** 回收站开关：还有一个"主动去回收站找回来"的入口（不只是删完那一下的撤回）。 */
    var showDeleted by mutableStateOf(false)
        private set

    private var started = false

    fun start() {
        if (!started) {
            started = true
            load()
        }
    }

    fun load() {
        loading = rows.isEmpty()
        loadError = null
        viewModelScope.launch {
            try {
                rows = container.repo.suppliers(includeDeleted = showDeleted)
            } catch (e: Exception) {
                loadError = toApiException(e).message
            } finally {
                loading = false
            }
        }
    }

    fun toggleDeleted() {
        showDeleted = !showDeleted
        rows = emptyList()
        loading = true
        load()
    }

    fun create(name: String, contact: String, phone: String, address: String, remark: String, onDone: () -> Unit) {
        viewModelScope.launch {
            try {
                val s = container.repo.createSupplier(
                    SupplierCreateRequest(
                        name = name, contactName = contact, phone = phone,
                        address = address, remark = remark,
                    ),
                )
                actionResult = "已建档案：${s.name}"
                onDone()
                load()
            } catch (e: Exception) {
                actionResult = toApiException(e).message
            }
        }
    }

    fun update(
        id: Long, name: String, contact: String, phone: String, address: String, remark: String, onDone: () -> Unit,
    ) {
        viewModelScope.launch {
            try {
                container.repo.updateSupplier(
                    id,
                    SupplierUpdateRequest(
                        name = name, contactName = contact, phone = phone,
                        address = address, remark = remark,
                    ),
                )
                actionResult = "已保存"
                onDone()
                load()
            } catch (e: Exception) {
                actionResult = toApiException(e).message
            }
        }
    }

    /**
     * 伪装删除。
     *
     * ⚠️ 名下有应付单时后端会**拒绝**并给出人话（"欠款不能挂在一个看不见的供应商上"）——
     * 那句话**原样显示**给用户，不翻译成"操作失败"（翻译掉以后用户不知道该先去做什么）。
     */
    fun delete(s: SupplierDto) {
        viewModelScope.launch {
            try {
                container.repo.deleteSupplier(s.id)
                lastDeleted = s
                // ⚠️ 这里**不写 `actionResult`**：删除的回执由那条带「撤回」的 snackbar 说
                //    （两处都说一句就是两条重复提示，用户不知道该点哪个）。
                load()
            } catch (e: Exception) {
                actionResult = toApiException(e).message
            }
        }
    }

    fun restoreLastDeleted() {
        val s = lastDeleted ?: return
        lastDeleted = null
        viewModelScope.launch {
            try {
                container.repo.restoreSupplier(s.id)
                actionResult = "已恢复「${s.name}」"
                load()
            } catch (e: Exception) {
                actionResult = toApiException(e).message
            }
        }
    }

    /** 从回收站里把某一条放回来（不是"刚删的那一条"那条路）。 */
    fun restore(s: SupplierDto) {
        viewModelScope.launch {
            try {
                container.repo.restoreSupplier(s.id)
                actionResult = "已恢复「${s.name}」"
                load()
            } catch (e: Exception) {
                actionResult = toApiException(e).message
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SuppliersScreen(
    container: AppContainer,
    onBack: () -> Unit,
    onOpenDetail: (Long) -> Unit,
) {
    val vm: SuppliersViewModel = appViewModel { SuppliersViewModel(container) }
    val snackbar = remember { SnackbarHostState() }
    LaunchedEffect(Unit) { vm.start() }
    OneShotSnackbar(snackbar, vm.actionResult, onConsumed = { vm.actionResult = null })
    // 删完**立刻**给一个「撤回」（硬规矩：删除一律软删 + 手边要有一个撤销入口）。
    LaunchedEffect(vm.lastDeleted) {
        val s = vm.lastDeleted ?: return@LaunchedEffect
        val res = snackbar.showSnackbar(
            message = "已删除「${s.name}」",
            actionLabel = "撤回",
            withDismissAction = false,
        )
        if (res == SnackbarResult.ActionPerformed) vm.restoreLastDeleted()
    }
    var editor by remember { mutableStateOf<SupplierDto?>(null) }
    var creating by remember { mutableStateOf(false) }

    Scaffold(
        snackbarHost = { SnackbarHost(snackbar) },
        topBar = {
            AppTopBar(
                title = "供应商 / 厂商",
                onBack = onBack,
                actions = {
                    TextButton(onClick = { vm.toggleDeleted() }) {
                        Text(if (vm.showDeleted) "看在用的" else "回收站")
                    }
                },
            )
        },
        floatingActionButton = {
            if (!vm.showDeleted) {
                ExtendedFloatingActionButton(
                    onClick = { creating = true },
                    containerColor = Color(CashOut),
                    contentColor = Color.White,
                    icon = { Icon(Icons.Default.Add, contentDescription = null) },
                    text = { Text("新增") },
                )
            }
        },
    ) { padding ->
        Box(Modifier.fillMaxSize().padding(padding)) {
            when {
                vm.loading -> LoadingBox()
                vm.loadError != null -> ErrorView(vm.loadError.orEmpty(), onRetry = { vm.load() })
                else -> LazyColumn(
                    Modifier.fillMaxSize(),
                    contentPadding = PaddingValues(16.dp, 16.dp, 16.dp, 88.dp),
                    verticalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                    item { SupplierExplainerCard(deleted = vm.showDeleted) }
                    if (vm.rows.isEmpty()) {
                        item {
                            EmptyView(
                                if (vm.showDeleted) {
                                    "回收站里没有供应商"
                                } else {
                                    "还没有供应商档案" +
                                        "\n先建一个档案，再给它挂应付款（欠了多少）" +
                                        "\n也可以让 AI 帮你建（例如「新增供应商 永盛食品，电话 13800001111」）"
                                },
                            )
                        }
                    }
                    items(vm.rows, key = { it.id }) { s ->
                        SupplierCard(
                            s = s,
                            deleted = vm.showDeleted,
                            onOpen = { onOpenDetail(s.id) },
                            onEdit = { editor = s },
                            onDelete = { vm.delete(s) },
                            onRestore = { vm.restore(s) },
                        )
                    }
                }
            }
        }
    }

    editor?.let { s ->
        SupplierEditorDialog(
            initial = s,
            onDismiss = { editor = null },
            onSave = { name, contact, phone, address, remark ->
                vm.update(s.id, name, contact, phone, address, remark) { editor = null }
            },
        )
    }
    if (creating) {
        SupplierEditorDialog(
            initial = null,
            onDismiss = { creating = false },
            onSave = { name, contact, phone, address, remark ->
                vm.create(name, contact, phone, address, remark) { creating = false }
            },
        )
    }
}

/** 顶上那张说明卡：这一页是什么、钱是怎么算的、删除之后去哪了。
 *
 * ⚠️ 里面三句都是**解释句**（删掉它用户照样能把事做完）→ 一律走 `Hint`，
 *    提示总开关关掉时整段不显示（判据 `_tools/qa/_check_hints.py`）。
 *    卡片标题是**标题**不是解释，留 `Text`。
 */
@Composable
private fun SupplierExplainerCard(deleted: Boolean) {
    SectionCard {
        Text(
            if (deleted) "回收站" else "这里记的是「我们欠谁的钱」",
            style = MaterialTheme.typography.titleMedium,
            fontWeight = FontWeight.Bold,
        )
        Hint(
            if (deleted) {
                "删掉的供应商在这里躺着（伪装删除：行还在库里）。点「恢复」放回来 —— " +
                    "名称、联系人、电话、地址都是删之前那一份。"
            } else {
                "建档不动钱：先建一个供应商，再给它挂应付款（欠了多少）。付款一笔一笔记，" +
                    "一张单可以分很多次付；每付一次都会写一行资金流水，账本「收支」里立刻看得到。"
            },
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Spacer(Modifier.height(4.dp))
        Hint(
            "· 「还欠」由服务端算（撤销一笔付款，这个数会立刻变回去）\n" +
                "· 名下有应付单的供应商删不掉：欠款不能挂在一个看不见的名字上",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

/** 供应商卡片：名字是主角，**还欠多少**是第二主角（这个是用户真正要看的数）。 */
@Composable
private fun SupplierCard(
    s: SupplierDto,
    deleted: Boolean,
    onOpen: () -> Unit,
    onEdit: () -> Unit,
    onDelete: () -> Unit,
    onRestore: () -> Unit,
) {
    val owes = s.unpaidTotal.toDoubleOrNull() ?: 0.0
    SectionCard {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(
                Modifier
                    .weight(1f)
                    .clickable(enabled = !deleted, onClick = onOpen),
            ) {
                Text(s.name, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
                val contact = listOf(s.contactName, s.phone).filter { it.isNotBlank() }.joinToString(" · ")
                Text(
                    contact.ifBlank { "（没填联系人）" },
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            if (deleted) {
                OutlinedButton(onClick = onRestore, modifier = Modifier.height(40.dp)) { Text("恢复") }
            } else {
                IconButton(onClick = onEdit) { Icon(Icons.Default.Edit, contentDescription = "改资料") }
                IconButton(onClick = onDelete) { Icon(Icons.Default.DeleteOutline, contentDescription = "删除") }
            }
        }
        Spacer(Modifier.height(6.dp))
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(
                if (owes > 0) "还欠 " else "已结清 ",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Text(
                "¥" + formatMoney(s.unpaidTotal),
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.Bold,
                // 欠着钱的时候用"支出色"（账本里支出就是它），结清了退成灰 —— 欠款是这一页的主角
                color = if (owes > 0) Color(CashOut) else MaterialTheme.colorScheme.onSurfaceVariant,
            )
            if (s.openPayables > 0) {
                Spacer(Modifier.width(8.dp))
                Text(
                    "${s.openPayables} 笔应付",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
        Text(
            "累计应付 ¥" + formatMoney(s.payableTotal) + " · 已付 ¥" + formatMoney(s.paidTotal),
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        if (!deleted) {
            Spacer(Modifier.height(6.dp))
            TextButton(onClick = onOpen, contentPadding = PaddingValues(0.dp)) {
                Text("看他的账（应付与付款）")
                Icon(Icons.Default.ChevronRight, contentDescription = null, modifier = Modifier.size(18.dp))
            }
        }
    }
}

/** 建 / 改档案：一张卡里的几个字段（与「新增开销」「新建预设单」同一种形态）。 */
/** 建 / 改档案：**表单行走共用那一套**（`ui/common/FormRows.kt`）。
 *
 * ⚠️ 这里是**共用行、不是 `OutlinedTextField`**：设计规范 §5.0 把「分组一律白卡 + 输入用无边框行」
 *    定成了全局规范（用户 2026-09-22：「把他们改进这种**白色的卡片样式**……**所有都要这样子去改**」），
 *    判据 `_tools/qa/_check_form_panel_style.py` 盯着"全库描边输入框总数只许减不许增"。
 *    对话框本身就是那张"卡"，所以行**不再外面再套一层 SectionCard**（框套框正是用户要消灭的东西）。
 */
@Composable
private fun SupplierEditorDialog(
    initial: SupplierDto?,
    onDismiss: () -> Unit,
    onSave: (name: String, contact: String, phone: String, address: String, remark: String) -> Unit,
) {
    var name by remember { mutableStateOf(initial?.name.orEmpty()) }
    var contact by remember { mutableStateOf(initial?.contactName.orEmpty()) }
    var phone by remember { mutableStateOf(initial?.phone.orEmpty()) }
    var address by remember { mutableStateOf(initial?.address.orEmpty()) }
    var remark by remember { mutableStateOf(initial?.remark.orEmpty()) }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(if (initial == null) "新增供应商 / 厂商" else "改资料") },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState())) {
                FormInputRow(
                    label = "名称", value = name, onValueChange = { name = it },
                    placeholder = "如 永盛食品有限公司", required = true,
                    icon = Icons.Default.Storefront, iconTint = Color(CashOut),
                )
                FormInputRow(
                    label = "联系人", value = contact, onValueChange = { contact = it },
                    placeholder = "对方的联系人",
                    icon = Icons.Default.Person, iconTint = Color(CashOut),
                )
                FormInputRow(
                    // 电话只让数字进来（规则唯一实现在 core/InputRules.kt）。后端那一侧要求
                    // 7~12 位数字 —— 前端在这一步就把汉字/字母挡在外面，别让用户敲完才吃一个 422。
                    label = "电话", value = phone, onValueChange = { phone = InputRules.phoneInput(it) },
                    placeholder = "7~12 位数字，座机写 07521234567",
                    keyboardType = KeyboardType.Phone,
                    icon = Icons.Default.Call, iconTint = Color(CashOut),
                )
                FormTextAreaRow(
                    label = "地址", value = address, onValueChange = { address = it },
                    placeholder = "对方的地址（可选）", minLines = 2,
                    icon = Icons.Default.Place, iconTint = Color(CashOut),
                )
                FormInputRow(
                    label = "备注", value = remark, onValueChange = { remark = it },
                    placeholder = "一句话（可选）",
                    icon = Icons.Default.Notes, iconTint = Color(CashOut),
                )
            }
        },
        confirmButton = {
            TextButton(
                enabled = name.isNotBlank(),
                onClick = { onSave(name.trim(), contact.trim(), phone.trim(), address.trim(), remark.trim()) },
            ) { Text("保存") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("取消") } },
    )
}
