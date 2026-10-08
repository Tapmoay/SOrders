package com.tapmoay.sorders.ui.dispatcher

import com.tapmoay.sorders.ui.theme.ThemeGreen
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.data.remote.dto.InvoiceDto
import com.tapmoay.sorders.data.repo.toApiException
import com.tapmoay.sorders.ui.common.*
import com.tapmoay.sorders.util.formatMoney
import kotlinx.coroutines.launch

/**
 * 发票台账（FEAT-0014 第四期 税账）：一张一张登记销项票 / 进项票。
 *
 * ⚠️ 这一页**只管登记与状态**，一分钱都不算：税额、该交多少增值税全在后端（`tax_service`）算，
 *    页面上连"价税合计减税额"都不做 —— 界面自己算一遍就会出现"明细对得上、汇总对不上"。
 * ⚠️ 四种状态动作各有各的意思，⛔ 别混成一个"删除"：
 *    - **开具**（REGISTERED → ISSUED）：票开出去了；
 *    - **作废**（→ VOIDED）：票**留在台账里**，只是退出税汇（客户退票、开错了都在这里）；
 *    - **撤票**（软删进回收站）：这张票不再出现在台账里，可是**票号还被占着** ——
 *      再登记同一个号会被后端 409 拦住并指路"先把它恢复出来"；
 *    - **恢复**：把回收站里的票放回来（放回时票号若被别人用了，后端如实报冲突，⛔ 不悄悄改号）。
 */
private val OUTPUT_BLUE = Color(ThemeGreen)
private val INPUT_GREEN = Color(0xFF00B578)
private val VOID_RED = Color(0xFFE53935)

/** 方向筛选的三档：`null` = 全部（后端那边不筛）。 */
private val DIRECTION_TABS: List<Pair<String?, String>> = listOf(
    null to "全部",
    "OUTPUT" to "销项票",
    "INPUT" to "进项票",
)

/** 一张票该用什么颜色：销项蓝、进项绿、作废红。 */
private fun directionColor(direction: String): Color =
    if (direction.trim().uppercase() == "INPUT") INPUT_GREEN else OUTPUT_BLUE

/** 金额：后端给的一律是两位小数字符串，显示统一走这里。 */
private fun yuan(s: String?): String = "¥" + formatMoney(s ?: "0")

/** 票的另一方（进项看供应商、销项看客户）；没填就如实说没填。 */
private fun otherParty(inv: InvoiceDto): String {
    val name = if (inv.direction.trim().uppercase() == "INPUT") inv.supplierName else inv.customerName
    return if (name.isBlank()) "没填对方" else name
}

class InvoicesViewModel(private val container: AppContainer) : ViewModel() {

    var rows by mutableStateOf<List<InvoiceDto>>(emptyList())
        private set
    var loading by mutableStateOf(true)
        private set
    var loadError by mutableStateOf<String?>(null)
    var actionResult by mutableStateOf<String?>(null)
    var showDeleted by mutableStateOf(false)
        private set
    /** 方向筛选：`null` = 全部。 */
    var direction by mutableStateOf<String?>(null)
        private set
    var lastDeleted by mutableStateOf<InvoiceDto?>(null)
        private set

    fun start() {
        load()
    }

    fun load() {
        viewModelScope.launch {
            if (rows.isEmpty()) loading = true
            loadError = null
            try {
                rows = container.repo.invoices(direction = direction, includeDeleted = showDeleted)
            } catch (e: Exception) {
                loadError = toApiException(e).message
            } finally {
                loading = false
            }
        }
    }

    fun chooseDirection(d: String?) {
        if (direction == d) return
        direction = d
        rows = emptyList()
        load()
    }

    fun toggleDeleted() {
        showDeleted = !showDeleted
        rows = emptyList()
        load()
    }

    /** 开具 / 作废：这两个动作后端都会拦"已经开具过""已经作废过"，原话照搬给用户看。 */
    private fun act(ok: String, body: suspend () -> Unit) {
        viewModelScope.launch {
            try {
                body()
                actionResult = ok
            } catch (e: Exception) {
                actionResult = toApiException(e).message
            }
            load()
        }
    }

    fun issue(inv: InvoiceDto) = act("已开具票 #" + inv.id + "（票开出去了）") { container.repo.issueInvoice(inv.id) }

    fun void(inv: InvoiceDto) = act("已作废票 #" + inv.id + "（票还在台账里，只是退出税汇）") { container.repo.voidInvoice(inv.id) }

    fun restore(inv: InvoiceDto) = act("已恢复票 #" + inv.id) { container.repo.restoreInvoice(inv.id) }

    /** 撤票：回执交给带「撤回」的 snackbar，所以这里只记下撤掉的是哪一张。 */
    fun delete(inv: InvoiceDto) {
        viewModelScope.launch {
            try {
                container.repo.deleteInvoice(inv.id)
                lastDeleted = inv
            } catch (e: Exception) {
                actionResult = toApiException(e).message
            }
            load()
        }
    }

    fun restoreLastDeleted() {
        val inv = lastDeleted ?: return
        lastDeleted = null
        viewModelScope.launch {
            try {
                container.repo.restoreInvoice(inv.id)
                actionResult = "已恢复票 #" + inv.id
            } catch (e: Exception) {
                actionResult = toApiException(e).message
            }
            load()
        }
    }
}

/**
 * 发票台账页：顶部「回收站 / 看在用的」+ 方向筛选 + 一行一张票。
 *
 * ⚠️ 点卡片进的是**同一张票的表单页**：已开具 / 已作废的票在那边是只读的（后端也不让改），
 *    所以这里不为"看一张老票"另开一页。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun InvoicesScreen(
    container: AppContainer,
    onBack: () -> Unit,
    onOpenForm: (Long?) -> Unit,
) {
    val vm: InvoicesViewModel = appViewModel { InvoicesViewModel(container) }
    val snackbar = remember { SnackbarHostState() }
    LaunchedEffect(Unit) { vm.start() }
    OneShotSnackbar(snackbar, vm.actionResult, onConsumed = { vm.actionResult = null })
    // 撤票的回执带一个「撤回」：手滑撤掉的票，不用跑去回收站找回来。
    LaunchedEffect(vm.lastDeleted) {
        val inv = vm.lastDeleted ?: return@LaunchedEffect
        val res = snackbar.showSnackbar("已撤销票 #" + inv.id, actionLabel = "撤回", withDismissAction = false)
        if (res == SnackbarResult.ActionPerformed) vm.restoreLastDeleted()
    }
    var confirmVoid by remember { mutableStateOf<InvoiceDto?>(null) }
    var confirmDelete by remember { mutableStateOf<InvoiceDto?>(null) }

    Scaffold(
        snackbarHost = { SnackbarHost(snackbar) },
        topBar = {
            AppTopBar(
                title = if (vm.showDeleted) "发票台账 · 回收站" else "发票台账",
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
                    onClick = { onOpenForm(null) },
                    containerColor = OUTPUT_BLUE,
                    contentColor = Color.White,
                    icon = { Icon(Icons.Default.Add, null) },
                    text = { Text("登记一张票") },
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
                    item { InvoiceIntroCard() }
                    item { DirectionFilterRow(vm.direction) { vm.chooseDirection(it) } }
                    if (vm.rows.isEmpty()) {
                        item {
                            EmptyView(
                                if (vm.showDeleted) "回收站是空的。"
                                else "还没有票。点右下角登记第一张。",
                            )
                        }
                    }
                    items(vm.rows, key = { it.id }) { inv ->
                        InvoiceCard(
                            inv = inv,
                            onOpen = { onOpenForm(inv.id) },
                            onIssue = { vm.issue(inv) },
                            onVoid = { confirmVoid = inv },
                            onDelete = { confirmDelete = inv },
                            onRestore = { vm.restore(inv) },
                        )
                    }
                }
            }
        }
    }

    confirmVoid?.let { inv ->
        CardAlertDialog(
            tone = DialogTone.DANGER,
            onDismissRequest = { confirmVoid = null },
            title = { Text("作废票 #" + inv.id + "？") },
            text = {
                Text(
                    "作废不等于删除。这张票会留在台账里、标成已作废，并从税汇里退出来" +
                        "（销项 / 进项两边都不再算它）。票号也还占着 —— 要它重新算数只能重新登记一张。",
                )
            },
            confirmButton = {
                TextButton(onClick = { confirmVoid = null; vm.void(inv) }) { Text("作废这张票") }
            },
            dismissButton = { TextButton(onClick = { confirmVoid = null }) { Text("再想想") } },
        )
    }

    confirmDelete?.let { inv ->
        CardAlertDialog(
            tone = DialogTone.DANGER,
            onDismissRequest = { confirmDelete = null },
            title = { Text("撤销票 #" + inv.id + "？") },
            text = {
                Text(
                    "撤票 = 进回收站：它从台账里消失、退出税汇。可它占的票号还在 —— " +
                        "想用同一个号再登记一张，得先把它恢复出来（或者换号）。",
                )
            },
            confirmButton = {
                TextButton(onClick = { confirmDelete = null; vm.delete(inv) }) { Text("撤销这张票") }
            },
            dismissButton = { TextButton(onClick = { confirmDelete = null }) { Text("再想想") } },
        )
    }
}

/** 这一页是干什么的（第一眼就得说清"这里不算钱"）。 */
@Composable
private fun InvoiceIntroCard() {
    SectionCard {
        Text("这一页是发票台账", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
        Spacer(Modifier.height(6.dp))
        Text(
            "登记销项票（我们开给客户）与进项票（供应商开给我们）。税额由后端按税率算，" +
                "这一页一个数都不自己算。",
            style = MaterialTheme.typography.bodyMedium,
        )
        Spacer(Modifier.height(6.dp))
        Hint(
            "进项票要挂在采购单上（抵的得是真实进过的货）；销项票不用。每张票在「税账」那一页" +
                "能看到算不算数。",
        )
    }
}

/** 方向筛选：三档，选中那档高亮。 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun DirectionFilterRow(selected: String?, onSelect: (String?) -> Unit) {
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        DIRECTION_TABS.forEach { (value, label) ->
            FilterChip(
                selected = selected == value,
                onClick = { onSelect(value) },
                label = { Text(label) },
            )
        }
    }
}

/** 票号：空票号是**允许的**（月结代开先登记、后补号），这里如实显示成没填。 */
private fun noText(no: String): String = if (no.isBlank()) "（没填票号）" else no

/** 税额那一栏：未税票是"没算过税"，⛔ 不是"税额 0"。 */
private fun taxText(inv: InvoiceDto): String {
    val tax = inv.taxAmount ?: return "未税票"
    val rate = inv.taxRate?.takeIf { it.isNotBlank() }
    return if (rate == null) "税额 " + yuan(tax) else "税额 " + yuan(tax) + "（" + rate + "%）"
}

/** 一行一张票。长名字各占一行 —— 挤在一行会在真机上被裁掉。 */
@Composable
private fun InvoiceCard(
    inv: InvoiceDto,
    onOpen: () -> Unit,
    onIssue: () -> Unit,
    onVoid: () -> Unit,
    onDelete: () -> Unit,
    onRestore: () -> Unit,
) {
    val status = inv.status.trim().uppercase()
    val registered = status == "REGISTERED"
    val voided = status == "VOIDED"
    SectionCard(Modifier.fillMaxWidth().clickable(onClick = onOpen)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Icon(
                if (inv.direction.trim().uppercase() == "INPUT") Icons.Default.CallReceived else Icons.Default.CallMade,
                contentDescription = null,
                tint = directionColor(inv.direction),
                modifier = Modifier.size(18.dp),
            )
            Spacer(Modifier.width(8.dp))
            Text(
                ReportFinance.directionLabel(inv.direction) + " · " + noText(inv.invoiceNo),
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.SemiBold,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
                modifier = Modifier.weight(1f),
            )
            if (inv.isDeleted) {
                Text("回收站", style = MaterialTheme.typography.bodySmall, color = Color(0xFF8A8A8E))
            } else if (voided) {
                Text("已作废", style = MaterialTheme.typography.bodySmall, color = VOID_RED)
            }
        }
        Text(
            otherParty(inv),
            style = MaterialTheme.typography.bodyMedium,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
            modifier = Modifier.fillMaxWidth(),
        )
        Text(
            inv.invoiceDate + " · " + ReportFinance.invoiceStatusLabel(inv.status),
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            Text("价税合计 " + yuan(inv.amount), style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold)
            Spacer(Modifier.weight(1f))
            Text(
                taxText(inv),
                style = MaterialTheme.typography.bodySmall,
                color = if (inv.taxAmount == null) Color(0xFF8A8A8E) else directionColor(inv.direction),
            )
        }
        if (inv.purchaseOrderIds.isNotEmpty()) {
            Text(
                "挂着 " + inv.purchaseOrderIds.size + " 张采购单",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        if (!inv.countsInTax && !inv.isDeleted) {
            Text("这张票不进税汇", style = MaterialTheme.typography.bodySmall, color = Color(0xFFFF9500))
        }
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End) {
            if (inv.isDeleted) {
                TextButton(onClick = onRestore) { Text("恢复") }
            } else {
                if (registered) TextButton(onClick = onOpen) { Text("改票") }
                if (registered) TextButton(onClick = onIssue) { Text("开具") }
                if (!voided) TextButton(onClick = onVoid) { Text("作废") }
                TextButton(onClick = onDelete) { Text("撤票") }
            }
        }
    }
}