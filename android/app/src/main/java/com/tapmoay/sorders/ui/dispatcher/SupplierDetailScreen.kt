package com.tapmoay.sorders.ui.dispatcher

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
import com.tapmoay.sorders.data.remote.dto.*
import com.tapmoay.sorders.data.repo.toApiException
import com.tapmoay.sorders.ui.common.*
import com.tapmoay.sorders.ui.theme.CashOut
import com.tapmoay.sorders.util.formatMoney
import java.time.LocalDate
import kotlinx.coroutines.launch

/**
 * 一个供应商的账：**几笔应付、每笔付了多少、每笔付款是什么时候付的**（2026-09-22）。
 *
 * ## 这一页的三个动作
 * 1. **挂一笔应付款**（欠他多少）——不动钱；
 * 2. **付一笔款**（钱真的出去：一张单可以分很多次付）——HIGH，卡片上要写清"还差多少 → 付完还差多少"；
 * 3. **撤销一笔付款**（软删那一行流水，可撤回）——付错了的回头路。
 *
 * ## ⛔ 欠款的口径只有一个
 * 界面上的「还欠」全部来自后端（`paid` / `unpaid` 字段）。拉一页明细自己求和会同时踩两个坑：
 * 列表可能被截断（少算）+ 与后端口径走散。这件事在账本那一期定过案（客户端求和少算 62%）。
 */
class SupplierDetailViewModel(private val container: AppContainer, private val supplierId: Long) : ViewModel() {

    var supplier by mutableStateOf<SupplierDto?>(null)
        private set
    var payables by mutableStateOf<List<SupplierPayableDto>>(emptyList())
        private set
    var payments by mutableStateOf<List<SupplierPaymentDto>>(emptyList())
        private set
    var loading by mutableStateOf(true)
        private set
    var loadError by mutableStateOf<String?>(null)
    var actionResult by mutableStateOf<String?>(null)

    /** 刚撤销掉的那一笔付款（给「撤回」用）。 */
    var lastCancelled by mutableStateOf<SupplierPaymentDto?>(null)
        private set

    private var started = false

    fun start() {
        if (!started) {
            started = true
            load()
        }
    }

    fun load() {
        loading = supplier == null
        loadError = null
        viewModelScope.launch {
            try {
                supplier = container.repo.supplier(supplierId)
                payables = container.repo.supplierPayables(supplierId)
                payments = container.repo.supplierPayments(supplierId = supplierId)
            } catch (e: Exception) {
                loadError = toApiException(e).message
            } finally {
                loading = false
            }
        }
    }

    /** 挂一笔应付（欠他多少）。**这一步不动钱**。 */
    fun createPayable(title: String, category: String, amount: String, docDate: String, remark: String, onDone: () -> Unit) {
        viewModelScope.launch {
            try {
                container.repo.createSupplierPayable(
                    supplierId,
                    SupplierPayableCreateRequest(
                        supplierId = supplierId, title = title, category = category,
                        amount = amount, docDate = docDate, remark = remark,
                    ),
                )
                actionResult = "已挂上应付：${title}"
                onDone()
                load()
            } catch (e: Exception) {
                actionResult = toApiException(e).message
            }
        }
    }

    /** 付一笔款。⚠️ 金额超过"还差"时后端会拒绝（那句话原样给用户看）。 */
    fun pay(p: SupplierPayableDto, amount: String, payDate: String, channel: String, remark: String, onDone: () -> Unit) {
        viewModelScope.launch {
            try {
                container.repo.paySupplierPayable(
                    p.id,
                    SupplierPaymentCreateRequest(amount = amount, payDate = payDate, channel = channel, remark = remark),
                )
                actionResult = "已付款 ${formatMoney(amount)} 元（${p.title}）"
                onDone()
                load()
            } catch (e: Exception) {
                actionResult = toApiException(e).message
            }
        }
    }

    /** 撤销一笔付款（软删那一行流水）。 */
    fun cancel(f: SupplierPaymentDto) {
        viewModelScope.launch {
            try {
                container.repo.cancelSupplierPayment(f.id)
                lastCancelled = f
                // ⚠️ 回执由那条带「撤回」的 snackbar 说，这里不重复写一句
                load()
            } catch (e: Exception) {
                actionResult = toApiException(e).message
            }
        }
    }

    fun restoreLastCancelled() {
        val f = lastCancelled ?: return
        lastCancelled = null
        viewModelScope.launch {
            try {
                container.repo.restoreSupplierPayment(f.id)
                actionResult = "已恢复这一笔付款"
                load()
            } catch (e: Exception) {
                actionResult = toApiException(e).message
            }
        }
    }

    fun deletePayable(p: SupplierPayableDto) {
        viewModelScope.launch {
            try {
                container.repo.deleteSupplierPayable(p.id)
                actionResult = "已删除应付单「${p.title}」"
                load()
            } catch (e: Exception) {
                actionResult = toApiException(e).message
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SupplierDetailScreen(container: AppContainer, supplierId: Long, onBack: () -> Unit) {
    val vm: SupplierDetailViewModel = appViewModel { SupplierDetailViewModel(container, supplierId) }
    val snackbar = remember { SnackbarHostState() }
    LaunchedEffect(Unit) { vm.start() }
    OneShotSnackbar(snackbar, vm.actionResult, onConsumed = { vm.actionResult = null })
    LaunchedEffect(vm.lastCancelled) {
        val f = vm.lastCancelled ?: return@LaunchedEffect
        val res = snackbar.showSnackbar(
            message = "已撤销这一笔付款（${formatMoney(f.amount)} 元）",
            actionLabel = "撤回",
            withDismissAction = false,
        )
        if (res == SnackbarResult.ActionPerformed) vm.restoreLastCancelled()
    }
    var addingPayable by remember { mutableStateOf(false) }
    var paying by remember { mutableStateOf<SupplierPayableDto?>(null) }

    Scaffold(
        snackbarHost = { SnackbarHost(snackbar) },
        topBar = { AppTopBar(title = vm.supplier?.name ?: "供应商", onBack = onBack) },
    ) { padding ->
        Box(Modifier.fillMaxSize().padding(padding)) {
            when {
                vm.loading -> LoadingBox()
                vm.loadError != null -> ErrorView(vm.loadError.orEmpty(), onRetry = { vm.load() })
                else -> LazyColumn(
                    Modifier.fillMaxSize(),
                    contentPadding = PaddingValues(16.dp),
                    verticalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                    item { OweCard(s = vm.supplier, onAddPayable = { addingPayable = true }) }
                    item {
                        Text(
                            "应付单（欠他的钱，一张单可以分多次付）",
                            style = MaterialTheme.typography.titleSmall,
                            fontWeight = FontWeight.Bold,
                        )
                    }
                    if (vm.payables.isEmpty()) {
                        item {
                            EmptyView(
                                "这个供应商名下还没有应付单" +
                                    "\n点上面那张卡的「挂一笔应付款」记上欠他多少" +
                                    "\n也可以让 AI 帮你挂（例如「给永盛食品挂一笔应付 1200.5，9 月货款」）",
                            )
                        }
                    }
                    items(vm.payables, key = { it.id }) { p ->
                        PayableCard(
                            p = p,
                            onPay = { paying = p },
                            onDelete = { vm.deletePayable(p) },
                        )
                    }
                    item {
                        Spacer(Modifier.height(4.dp))
                        Text(
                            "付款记录（钱什么时候出去的）",
                            style = MaterialTheme.typography.titleSmall,
                            fontWeight = FontWeight.Bold,
                        )
                    }
                    if (vm.payments.isEmpty()) {
                        item { EmptyView("还没有给他付过款") }
                    }
                    items(vm.payments, key = { it.id }) { f ->
                        PaymentCard(f = f, onCancel = { vm.cancel(f) })
                    }
                }
            }
        }
    }

    if (addingPayable) {
        PayableEditorDialog(
            supplierName = vm.supplier?.name.orEmpty(),
            onDismiss = { addingPayable = false },
            onSave = { title, category, amount, docDate, remark ->
                vm.createPayable(title, category, amount, docDate, remark) { addingPayable = false }
            },
        )
    }
    paying?.let { p ->
        PayDialog(
            p = p,
            onDismiss = { paying = null },
            onSave = { amount, date, channel, remark ->
                vm.pay(p, amount, date, channel, remark) { paying = null }
            },
        )
    }
}

/** 顶上那张卡：**还欠多少**（主角）+ 累计应付/已付（后端算好的三个数）。 */
@Composable
private fun OweCard(s: SupplierDto?, onAddPayable: () -> Unit) {
    if (s == null) return
    val owes = s.unpaidTotal.toDoubleOrNull() ?: 0.0
    SectionCard {
        Text("还欠", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Text(
            "¥" + formatMoney(s.unpaidTotal),
            style = MaterialTheme.typography.headlineMedium,
            fontWeight = FontWeight.Bold,
            color = if (owes > 0) Color(CashOut) else MaterialTheme.colorScheme.onSurface,
        )
        Spacer(Modifier.height(4.dp))
        InfoRow("累计应付", "¥" + formatMoney(s.payableTotal))
        InfoRow("已经付过", "¥" + formatMoney(s.paidTotal))
        val contact = listOf(s.contactName, s.phone).filter { it.isNotBlank() }.joinToString(" · ")
        if (contact.isNotBlank()) InfoRow("联系人", contact)
        if (s.address.isNotBlank()) InfoRow("地址", s.address)
        if (s.remark.isNotBlank()) InfoRow("备注", s.remark)
        Spacer(Modifier.height(8.dp))
        Button(onClick = onAddPayable, modifier = Modifier.fillMaxWidth()) {
            Icon(Icons.Default.PostAdd, contentDescription = null, modifier = Modifier.size(18.dp))
            Spacer(Modifier.width(6.dp))
            Text("挂一笔应付款（欠他多少）")
        }
        Text(
            "挂账不动钱：这一步只是把欠款记上；真的付出去要用下面每张单上的「付款」",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

/** 一张应付单：事由、金额、已付/还差、付过几次 + 两个动作。 */
@Composable
private fun PayableCard(p: SupplierPayableDto, onPay: () -> Unit, onDelete: () -> Unit) {
    val unpaid = p.unpaid.toDoubleOrNull() ?: 0.0
    val done = unpaid <= 0.0
    SectionCard {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text(p.title, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
                Text(
                    (if (p.category.isBlank()) "货款" else p.category) + " · " + p.docDate,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            Text(
                if (done) "已付清" else "还差 ¥" + formatMoney(p.unpaid),
                style = MaterialTheme.typography.titleSmall,
                fontWeight = FontWeight.SemiBold,
                color = if (done) MaterialTheme.colorScheme.onSurfaceVariant else Color(CashOut),
            )
        }
        Spacer(Modifier.height(4.dp))
        InfoRow("应付", "¥" + formatMoney(p.amount))
        InfoRow(
            "已付",
            "¥" + formatMoney(p.paid) + if (p.paymentCount > 0) "（分 ${p.paymentCount} 次）" else "",
        )
        if (p.remark.isNotBlank()) InfoRow("备注", p.remark)
        Spacer(Modifier.height(8.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedButton(onClick = onDelete, modifier = Modifier.height(40.dp)) { Text("删") }
            Spacer(Modifier.weight(1f))
            // 付清了就不给「付款」按钮：点了必然被后端拒绝（一张点下去必然失败的按钮是最坏的一种）
            Button(onClick = onPay, enabled = !done, modifier = Modifier.height(40.dp)) {
                Icon(Icons.Default.Payments, contentDescription = null, modifier = Modifier.size(16.dp))
                Spacer(Modifier.width(4.dp))
                Text(if (done) "已付清" else "付款")
            }
        }
    }
}

/** 一条付款记录：金额 + 日期 + 方式 + 「撤销」（付错了的回头路）。 */
@Composable
private fun PaymentCard(f: SupplierPaymentDto, onCancel: () -> Unit) {
    SectionCard {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Icon(
                Icons.Default.Payments, contentDescription = null,
                modifier = Modifier.size(18.dp), tint = Color(CashOut),
            )
            Spacer(Modifier.width(8.dp))
            Column(Modifier.weight(1f)) {
                Text(
                    "¥" + formatMoney(f.amount),
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.SemiBold,
                )
                Text(
                    f.payDate + " · " + channelLabel(f.channel) +
                        if (f.payableTitle.isNotBlank()) " · " + f.payableTitle else "",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            TextButton(onClick = onCancel) { Text("撤销") }
        }
        if (f.remark.isNotBlank()) InfoRow("备注", f.remark)
    }
}

/**
 * 付款方式 → 中文。
 *
 * ⚠️ 后端存的是 code（`cash`/`transfer`/`wechat`/`bank`）。界面上一律显示中文 ——
 * 用户看到 `transfer` 只会以为系统出错了。
 */
private fun channelLabel(code: String): String = when (code) {
    "cash" -> "现金"
    "transfer" -> "转账"
    "wechat" -> "微信"
    "bank" -> "银行"
    else -> code
}

/** 挂一笔应付款：**表单行走共用那一套**（`ui/common/FormRows.kt`，不是 `OutlinedTextField` —— 见设计规范 §5.0）。 */
@Composable
private fun PayableEditorDialog(
    supplierName: String,
    onDismiss: () -> Unit,
    onSave: (title: String, category: String, amount: String, docDate: String, remark: String) -> Unit,
) {
    var title by remember { mutableStateOf("") }
    var amount by remember { mutableStateOf("") }
    var category by remember { mutableStateOf(SupplierCategories.first()) }
    var docDate by remember { mutableStateOf(LocalDate.now().toString()) }
    var remark by remember { mutableStateOf("") }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("挂一笔应付款") },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState())) {
                Text(
                    "记下「我们欠 $supplierName 一笔钱」。⛔ 这一步不动钱 —— 钱在「付款」那一步才出去。",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Spacer(Modifier.height(8.dp))
                FormInputRow(
                    label = "这笔账是什么", value = title, onValueChange = { title = it },
                    placeholder = "如 9 月货款 / 采购叉车", required = true,
                    icon = Icons.Default.ReceiptLong, iconTint = Color(CashOut),
                )
                FormInputRow(
                    label = "应付总额", value = amount, onValueChange = { amount = it },
                    placeholder = "只填数字（元）", required = true, keyboardType = KeyboardType.Decimal,
                    icon = Icons.Default.Payments, iconTint = Color(CashOut),
                )
                Spacer(Modifier.height(6.dp))
                Text("用途分类", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                FlowChips(values = SupplierCategories, selected = category, onPick = { category = it })
                FormInputRow(
                    label = "单据日期", value = docDate, onValueChange = { docDate = it },
                    placeholder = "YYYY-MM-DD（这笔欠款从哪天算）",
                    icon = Icons.Default.Event, iconTint = Color(CashOut),
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
                enabled = title.isNotBlank() && amount.isNotBlank(),
                onClick = { onSave(title.trim(), category, amount.trim(), docDate.trim(), remark.trim()) },
            ) { Text("挂上") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("取消") } },
    )
}

/**
 * 付一笔款。
 *
 * ⚠️ 卡上要写清**还差多少 → 付完还差多少**：用户核对一笔付款时真正看的就是这两个数
 * （不写的话他只能凭记忆判断"这 800 是不是付多了"，而钱付出去撤不回来）。
 */
@Composable
private fun PayDialog(
    p: SupplierPayableDto,
    onDismiss: () -> Unit,
    onSave: (amount: String, payDate: String, channel: String, remark: String) -> Unit,
) {
    // 默认填"还差多少"（最常见的用法是把它付清）；用户改成小数就是分次付款
    var amount by remember { mutableStateOf(p.unpaid) }
    var payDate by remember { mutableStateOf(LocalDate.now().toString()) }
    var channel by remember { mutableStateOf("cash") }
    var remark by remember { mutableStateOf("") }
    val unpaid = p.unpaid.toBigDecimalOrNull()
    val typed = amount.toBigDecimalOrNull()
    val over = unpaid != null && typed != null && typed > unpaid
    val after = if (unpaid != null && typed != null) (unpaid - typed).setScale(2).toPlainString() else null

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("付款：${p.title}") },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState())) {
                InfoRow("应付总额", "¥" + formatMoney(p.amount))
                InfoRow("已经付过", "¥" + formatMoney(p.paid))
                InfoRow("还差", "¥" + formatMoney(p.unpaid))
                Spacer(Modifier.height(8.dp))
                FormInputRow(
                    label = "这次付多少", value = amount, onValueChange = { amount = it },
                    placeholder = "只填数字（元）", required = true, keyboardType = KeyboardType.Decimal,
                    icon = Icons.Default.Payments, iconTint = Color(CashOut),
                )
                // ⚠️ 「付完之后还差多少」是这张卡上**最该看得见的一行**（用户核对一笔付款看的就是它）。
                //    三种形态分三种控件（判据 `_check_hints.py` 盯着这件事）：
                //    · 超付 = **警告** → `Text`（⚠️ 前缀 + 红字，绝不能被提示总开关关掉）；
                //    · 付完还差 X = **带插值的数据** → `Text`；
                //    · 还没填时那句"填一个金额，这里会算出…" = **解释** → `Hint`（总开关关掉时不显示）。
                if (over) {
                    Text(
                        "⛔ 超过了还差的 ¥" + formatMoney(p.unpaid) + "；要付这么多请另挂一张应付单",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.error,
                    )
                } else if (after != null) {
                    Text(
                        "付完之后还差 ¥" + formatMoney(after) + if (after == "0.00") "（这一笔付清）" else "",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                } else {
                    Hint(
                        "填一个金额，这里会算出付完还差多少",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                Spacer(Modifier.height(4.dp))
                FormInputRow(
                    label = "付款日期", value = payDate, onValueChange = { payDate = it },
                    placeholder = "YYYY-MM-DD",
                    icon = Icons.Default.Event, iconTint = Color(CashOut),
                )
                Spacer(Modifier.height(6.dp))
                Text("付款方式", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                FlowChips(values = ChannelCodes, selected = channel, onPick = { channel = it }, label = ::channelLabel)
                FormInputRow(
                    label = "备注", value = remark, onValueChange = { remark = it },
                    placeholder = "一句话（可选）",
                    icon = Icons.Default.Notes, iconTint = Color(CashOut),
                )
                Spacer(Modifier.height(8.dp))
                Hint(
                    "钱真的出去了：会写一行资金流水，账本「收支」里立刻看得到。付错了可以在付款记录上「撤销」。",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        },
        confirmButton = {
            TextButton(
                enabled = typed != null && typed.signum() > 0 && !over,
                onClick = { onSave(amount.trim(), payDate.trim(), channel, remark.trim()) },
            ) { Text("确认付款") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("取消") } },
    )
}

/** 应付款的用途分类**建议值**（后端 `SUPPLIER_PAYABLE_CATEGORIES` 同一份：是建议，不是枚举）。 */
private val SupplierCategories = listOf("货款", "设备采购", "运费", "尾款", "其他")

/** 付款方式（后端 `pattern="^(cash|transfer|wechat|bank)$"`）。 */
private val ChannelCodes = listOf("cash", "transfer", "wechat", "bank")

/** 一排可点的小胶囊（分类/付款方式都只有 4~5 个取值，横排比下拉快一步）。 */
@Composable
private fun FlowChips(
    values: List<String>,
    selected: String,
    onPick: (String) -> Unit,
    label: (String) -> String = { it },
) {
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        values.forEach { v ->
            FilterChip(
                selected = v == selected,
                onClick = { onPick(v) },
                label = { Text(label(v)) },
            )
        }
    }
}
