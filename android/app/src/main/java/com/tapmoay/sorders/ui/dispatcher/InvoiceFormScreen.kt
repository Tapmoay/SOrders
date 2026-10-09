package com.tapmoay.sorders.ui.dispatcher

import com.tapmoay.sorders.ui.theme.ThemeGreen
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.clickable
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.core.InputRules
import com.tapmoay.sorders.data.remote.dto.CustomerDto
import com.tapmoay.sorders.data.remote.dto.InvoiceCreateRequest
import com.tapmoay.sorders.data.remote.dto.InvoiceUpdateRequest
import com.tapmoay.sorders.data.remote.dto.PurchaseOrderDto
import com.tapmoay.sorders.data.remote.dto.SupplierCreateRequest
import com.tapmoay.sorders.data.remote.dto.SupplierDto
import com.tapmoay.sorders.data.repo.toApiException
import com.tapmoay.sorders.ui.common.*
import com.tapmoay.sorders.util.formatMoney
import kotlinx.coroutines.launch
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId

/**
 * 登记 / 改一张发票（FEAT-0014 第四期 税账）。
 *
 * ⚠️ **方向只在建票时定**：销项票（我们开给客户）与进项票（供应商开给我们）的必填项不一样
 *    （进项要挂采购单与供应商），改方向＝作废重开一张 —— 所以改单模式下方向是只读的。
 * ⚠️ 这一页**一个数都不算**：价税合计是用户填的，税额是后端按税率算的（前端不写 `amount * rate` 那套）。
 *    填了税率、没填税额 ⇒ 后端按「价税合计 / (1 + 税率)」倒推（这是发票上的印法）。
 * ⚠️ 税率与税额**同生同灭**：要么都填、要么都不填（都不填 = 未税票，不进税汇）。
 * ⚠️ 只有**已登记**的票能改（后端也是这么拦的）：已开具 / 已作废 / 回收站里的票这一页只读。
 */
class InvoiceFormViewModel(private val container: AppContainer, private val invoiceId: Long?) : ViewModel() {

    val isNew: Boolean get() = invoiceId == null

    // ---- 票面 ----
    var direction by mutableStateOf("OUTPUT")
        private set
    var invoiceNo by mutableStateOf("")
        private set
    var invoiceDate by mutableStateOf(LocalDate.now().toString())
        private set
    var amount by mutableStateOf("")
        private set
    var taxRate by mutableStateOf("")
        private set
    var taxAmount by mutableStateOf("")
        private set
    var note by mutableStateOf("")
        private set

    // ---- 对方与关联单据 ----
    var supplierId by mutableStateOf<Long?>(null)
        private set
    var supplierName by mutableStateOf("")
        private set
    var customerId by mutableStateOf<Long?>(null)
        private set
    var customerName by mutableStateOf("")
        private set
    var purchaseOrderIds by mutableStateOf<List<Long>>(emptyList())
        private set

    // ---- 这张票现在是什么状态（只读模式的依据） ----
    var status by mutableStateOf("REGISTERED")
        private set
    var isDeleted by mutableStateOf(false)
        private set
    var countsInTax by mutableStateOf(true)
        private set
    var backendTaxAmount by mutableStateOf<String?>(null)
        private set

    // ---- 页面状态 ----
    var loading by mutableStateOf(invoiceId != null)
        private set
    var loadError by mutableStateOf<String?>(null)
    var saving by mutableStateOf(false)
        private set
    var saved by mutableStateOf(false)
        private set
    var formError by mutableStateOf<String?>(null)
    var suppliers by mutableStateOf<List<SupplierDto>>(emptyList())
        private set
    var customers by mutableStateOf<List<CustomerDto>>(emptyList())
        private set
    var orders by mutableStateOf<List<PurchaseOrderDto>>(emptyList())
        private set
    var ordersLoading by mutableStateOf(false)
        private set

    val isInput: Boolean get() = direction.trim().uppercase() == "INPUT"

    /** 能动笔的只有「已登记、还在用」的票。 */
    val editable: Boolean get() = !isDeleted && status.trim().uppercase() == "REGISTERED"

    fun start() {
        val id = invoiceId ?: return
        viewModelScope.launch {
            loading = true
            loadError = null
            try {
                val inv = container.repo.invoice(id)
                direction = inv.direction.ifBlank { "OUTPUT" }
                invoiceNo = inv.invoiceNo
                invoiceDate = inv.invoiceDate
                amount = inv.amount
                taxRate = inv.taxRate.orEmpty()
                taxAmount = inv.taxAmount.orEmpty()
                note = inv.note
                supplierId = inv.supplierId
                supplierName = inv.supplierName
                customerId = inv.customerId
                customerName = inv.customerName
                purchaseOrderIds = inv.purchaseOrderIds
                status = inv.status
                isDeleted = inv.isDeleted
                countsInTax = inv.countsInTax
                backendTaxAmount = inv.taxAmount
            } catch (e: Exception) {
                loadError = toApiException(e).message
            } finally {
                loading = false
            }
        }
    }

    fun chooseDirection(v: String) { direction = v }

    fun updateNo(v: String) { invoiceNo = v }
    fun updateDate(v: String) { invoiceDate = v }
    fun updateAmount(v: String) { amount = v }
    fun updateTaxRate(v: String) { taxRate = v }
    fun updateTaxAmount(v: String) { taxAmount = v }
    fun updateNote(v: String) { note = v }

    fun pickSupplier(s: SupplierDto) {
        supplierId = s.id
        supplierName = s.name
        // 换了供应商 = 之前挂的采购单都不作数了（进项票只能抵同一家的货）。
        purchaseOrderIds = emptyList()
        orders = emptyList()
        loadOrders()
    }

    /**
     * 就地新建一家供应商（CHG-0068 / 台账 L-40）：进项票这边**也要能建**，别支使用户跑一趟档案页。
     *
     * 只送**名称 ＋ 电话**（用户拍板的"最小可建"：地址/备注以后到「供应商 / 厂商」页补）。
     * 建完顺手把刚建的那家选上。
     *
     * ⚠️ 刷新名册**不能**走 [loadSuppliers]：它带头一句 `if (suppliers.isNotEmpty()) return` 早退守卫
     *    （那是"进页面才拉一次"的意思），就地新建之后名册还是旧的 ⇒ 这里直接重拉一遍。
     */
    fun createSupplierInline(name: String, phone: String, onCreated: (SupplierDto) -> Unit) {
        viewModelScope.launch {
            try {
                val s = container.repo.createSupplier(SupplierCreateRequest(name = name, phone = phone))
                suppliers = container.repo.suppliers()
                pickSupplier(s)
                onCreated(s)
            } catch (e: Exception) {
                // 重名之类由后端拦（400），它那句人话直接显示在这一页已有的错误行上。
                formError = toApiException(e).message
            }
        }
    }

    fun pickCustomer(c: CustomerDto) {
        customerId = c.id
        customerName = c.name
    }

    fun toggleOrder(id: Long) {
        purchaseOrderIds = if (purchaseOrderIds.contains(id)) purchaseOrderIds.filter { it != id } else purchaseOrderIds + id
    }

    fun loadSuppliers() {
        if (suppliers.isNotEmpty()) return
        viewModelScope.launch {
            try {
                suppliers = container.repo.suppliers()
            } catch (e: Exception) {
                formError = toApiException(e).message
            }
        }
    }

    fun loadCustomers() {
        if (customers.isNotEmpty()) return
        viewModelScope.launch {
            try {
                customers = container.repo.customers()
            } catch (e: Exception) {
                formError = toApiException(e).message
            }
        }
    }

    /** 只列**这一家供应商**的采购单：进项票只能抵同一家的货，列表里混进别家只会让人选错。 */
    fun loadOrders() {
        val sid = supplierId ?: return
        viewModelScope.launch {
            ordersLoading = true
            try {
                orders = container.repo.purchaseOrders(supplierId = sid)
            } catch (e: Exception) {
                formError = toApiException(e).message
            } finally {
                ordersLoading = false
            }
        }
    }

    fun save() {
        val amt = amount.trim()
        if (amt.isBlank()) { formError = "价税合计得填个数 —— 票面上印了多少就填多少。"; return }
        val rate = taxRate.trim().ifBlank { null }
        val tax = taxAmount.trim().ifBlank { null }
        if (rate == null && tax != null) {
            formError = "填了税额就得填税率 —— 没税率的票不该有税额（把税率填上，或者把税额清空）。"
            return
        }
        if (isInput) {
            if (supplierId == null) { formError = "进了谁的货就选谁：进项票得挂在一家供应商上。"; return }
            if (purchaseOrderIds.isEmpty()) { formError = "进项票至少要挂一张采购单 —— 税要抵的是真实进过的货。"; return }
        } else if (customerId == null) {
            formError = "销项票得选一个客户：票是开给谁的。";
            return
        }
        val no = invoiceNo.trim()
        val memo = note.trim()
        saving = true
        viewModelScope.launch {
            try {
                if (invoiceId == null) {
                    container.repo.createInvoice(
                        InvoiceCreateRequest(
                            direction = direction,
                            invoiceNo = no,
                            invoiceDate = invoiceDate,
                            amount = amt,
                            taxRate = rate,
                            taxAmount = tax,
                            supplierId = if (isInput) supplierId else null,
                            customerId = if (isInput) null else customerId,
                            purchaseOrderIds = if (isInput) purchaseOrderIds else emptyList(),
                            note = memo,
                        ),
                    )
                } else {
                    container.repo.updateInvoice(
                        invoiceId,
                        InvoiceUpdateRequest(
                            invoiceNo = no,
                            invoiceDate = invoiceDate,
                            amount = amt,
                            taxRate = rate,
                            taxAmount = tax,
                            supplierId = if (isInput) supplierId else null,
                            customerId = if (isInput) null else customerId,
                            purchaseOrderIds = if (isInput) purchaseOrderIds else null,
                            note = memo,
                        ),
                    )
                }
                saved = true
            } catch (e: Exception) {
                formError = toApiException(e).message
            } finally {
                saving = false
            }
        }
    }
}

// ------------------------------------------------------------ 这一页自己的几个色与小块

private val TAX_BROWN = Color(0xFFA98F76)   // 与工作台那一格 / 报表第 10 格同色（#795548 太深，宫格亮度带判据否过）
private val FORM_BLUE = Color(ThemeGreen)
private val FORM_GREEN = Color(0xFF567A5F)
private val FORM_ORANGE = Color(0xFFC9855A)

/**
 * 登记 / 改一张发票（FEAT-0014 第四期 税账）。
 *
 * ⚠️ **方向在建票时定**：销项票要客户、进项票要供应商 + 至少一张采购单 —— 两种票的必填项
 *    根本不是一套，所以改单模式下方向只读展示，换方向＝作废重开一张。
 * ⚠️ 底部那颗按钮只在 [InvoiceFormViewModel.editable] 为真时出现
 *    （已开具 / 已作废 / 回收站里的票这一页只读，后端也是这么拦的）。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun InvoiceFormScreen(container: AppContainer, invoiceId: Long?, onBack: () -> Unit) {
    val vm: InvoiceFormViewModel = appViewModel { InvoiceFormViewModel(container, invoiceId) }
    LaunchedEffect(Unit) { vm.start() }
    LaunchedEffect(vm.saved) { if (vm.saved) onBack() }
    var showDate by remember { mutableStateOf(false) }
    var showSupplierSheet by remember { mutableStateOf(false) }
    var showCustomerSheet by remember { mutableStateOf(false) }
    var showOrderSheet by remember { mutableStateOf(false) }
    // 就地新建供应商（CHG-0068）：下面弹层里那颗「新建供应商」把这张最小表单打开。
    var creatingSupplier by remember { mutableStateOf(false) }

    Scaffold(
        topBar = { AppTopBar(title = if (vm.isNew) "登记一张票" else "改这张票", onBack = onBack) },
        bottomBar = {
            if (vm.editable) {
                Surface(color = MaterialTheme.colorScheme.surface) {
                    PrimaryActionButton(
                        text = if (vm.isNew) "登记这张票" else "保存修改",
                        icon = Icons.Default.Check,
                        onClick = { vm.save() },
                        enabled = !vm.saving,
                        modifier = Modifier.fillMaxWidth().padding(16.dp),
                    )
                }
            }
        },
    ) { padding ->
        Box(Modifier.fillMaxSize().padding(padding)) {
            if (vm.loading) {
                LoadingBox()
            } else if (vm.loadError != null) {
                ErrorView(vm.loadError.orEmpty(), onRetry = { vm.start() })
            } else {
                Column(
                    Modifier
                        .fillMaxSize()
                        .verticalScroll(rememberScrollState())
                        .padding(16.dp),
                ) {
                    if (!vm.editable) LockedNotice(vm)

                    FormGroup(icon = Icons.Default.Receipt, title = "票面", tint = TAX_BROWN) {
                        if (vm.isNew) {
                            FormRow(label = "方向", required = true, icon = Icons.Default.SwapHoriz, iconTint = FORM_BLUE) {
                                FilterChip(
                                    selected = !vm.isInput,
                                    onClick = { vm.chooseDirection("OUTPUT") },
                                    label = { Text("销项票") },
                                )
                                Spacer(Modifier.width(8.dp))
                                FilterChip(
                                    selected = vm.isInput,
                                    onClick = { vm.chooseDirection("INPUT") },
                                    label = { Text("进项票") },
                                )
                            }
                        } else {
                            FormRow(label = "方向", icon = Icons.Default.SwapHoriz, iconTint = FORM_BLUE) {
                                Text(
                                    ReportFinance.directionLabel(vm.direction),
                                    style = MaterialTheme.typography.bodyLarge,
                                )
                            }
                        }
                        FormInputRow(
                            label = "票号",
                            value = vm.invoiceNo,
                            onValueChange = { vm.updateNo(it) },
                            placeholder = "发票上的号码（可不填）",
                            icon = Icons.Default.Tag,
                            iconTint = FORM_GREEN,
                        )
                        FormRow(
                            label = "开票日期",
                            required = true,
                            icon = Icons.Default.Event,
                            iconTint = FORM_BLUE,
                            onClick = { showDate = true },
                        ) {
                            Text(vm.invoiceDate, style = MaterialTheme.typography.bodyLarge)
                            Spacer(Modifier.width(6.dp))
                            Icon(
                                Icons.AutoMirrored.Filled.KeyboardArrowRight,
                                contentDescription = null,
                                tint = MaterialTheme.colorScheme.outline,
                                modifier = Modifier.size(18.dp),
                            )
                        }
                        FormInputRow(
                            label = "价税合计",
                            value = vm.amount,
                            onValueChange = { vm.updateAmount(InputRules.moneyInput(it)) },
                            placeholder = "票面上印了多少",
                            required = true,
                            keyboardType = KeyboardType.Decimal,
                            icon = Icons.Default.Payments,
                            iconTint = FORM_BLUE,
                        )
                        FormInputRow(
                            label = "税率（%）",
                            value = vm.taxRate,
                            onValueChange = { vm.updateTaxRate(InputRules.moneyInput(it)) },
                            placeholder = "不填就是未税票",
                            keyboardType = KeyboardType.Decimal,
                            icon = Icons.Default.Percent,
                            iconTint = TAX_BROWN,
                        )
                        FormInputRow(
                            label = "税额",
                            value = vm.taxAmount,
                            onValueChange = { vm.updateTaxAmount(InputRules.moneyInput(it)) },
                            placeholder = "留空就按税率算",
                            keyboardType = KeyboardType.Decimal,
                            icon = Icons.Default.Calculate,
                            iconTint = TAX_BROWN,
                        )
                        Hint("税率和税额：只填税率，税额由后端按「价税合计 ÷ (1 + 税率)」倒推；两个都不填就是未税票。")
                        Hint("未税票不进税汇（销项进项两边都不算数）—— 它不是「0% 税率的票」。")
                    }

                    Spacer(Modifier.height(14.dp))

                    if (vm.isInput) {
                        FormGroup(icon = Icons.Default.LocalShipping, title = "这张票是谁开给我们的", tint = FORM_GREEN) {
                            FormPickRow(
                                label = "供应商",
                                value = vm.supplierName,
                                onClick = { showSupplierSheet = true; vm.loadSuppliers() },
                                placeholder = "进了谁的货就选谁",
                                required = true,
                                icon = Icons.Default.Store,
                                iconTint = FORM_GREEN,
                            )
                            FormPickRow(
                                label = "挂着的采购单",
                                value = orderLabel(vm.purchaseOrderIds),
                                onClick = { showOrderSheet = true; vm.loadOrders() },
                                placeholder = "至少要挂一张",
                                required = true,
                                icon = Icons.Default.ShoppingCart,
                                iconTint = FORM_BLUE,
                            )
                            Hint("进项票要抵的税得来自真实进过的货：所以它必须挂在这一家的采购单上（换供应商会清空已挂的单）。")
                        }
                    } else {
                        FormGroup(icon = Icons.Default.Person, title = "这张票开给谁", tint = FORM_BLUE) {
                            FormPickRow(
                                label = "客户",
                                value = vm.customerName,
                                onClick = { showCustomerSheet = true; vm.loadCustomers() },
                                placeholder = "票是开给谁的",
                                required = true,
                                icon = Icons.Default.Person,
                                iconTint = FORM_BLUE,
                            )
                            Hint("销项票挂在客户上（这批货卖给了谁）；它不用挂采购单。")
                        }
                    }

                    Spacer(Modifier.height(14.dp))

                    FormGroup(icon = Icons.Default.Notes, title = "备注", tint = MaterialTheme.colorScheme.onSurfaceVariant) {
                        FormTextAreaRow(
                            label = "备注",
                            value = vm.note,
                            onValueChange = { vm.updateNote(it) },
                            placeholder = "想写就写（可不填）",
                            icon = Icons.Default.Notes,
                        )
                    }

                    Spacer(Modifier.height(10.dp))
                    FormErrorLine(vm.formError.orEmpty())
                    Spacer(Modifier.height(28.dp))
                }
            }
        }
    }

    if (showDate) {
        val dpState = rememberDatePickerState()
        DatePickerDialog(
            onDismissRequest = { showDate = false },
            confirmButton = {
                TextButton(onClick = {
                    val ms = dpState.selectedDateMillis
                    if (ms != null) {
                        vm.updateDate(
                            Instant.ofEpochMilli(ms).atZone(ZoneId.systemDefault()).toLocalDate().toString(),
                        )
                    }
                    showDate = false
                }) { Text("就用这天") }
            },
            dismissButton = { TextButton(onClick = { showDate = false }) { Text("取消") } },
        ) {
            DatePicker(state = dpState)
        }
    }

    if (showSupplierSheet) {
        PickSheet(
            title = "选供应商",
            // 空态本身就是入口（下面那颗「新建供应商」）：不用跑去档案页建。
            empty = "还没有供应商 —— 现在就建一家",
            createLabel = "新建供应商",
            onCreate = { creatingSupplier = true },
            rows = vm.suppliers.map { it.id to listOf(it.name, contactOf(it.contactName, it.phone)) },
            onPick = { id ->
                vm.suppliers.firstOrNull { it.id == id }?.let { vm.pickSupplier(it) }
                showSupplierSheet = false
            },
            onDismiss = { showSupplierSheet = false },
        )
    }

    if (creatingSupplier) {
        SupplierEditorDialog(
            initial = null,
            minimal = true,
            onDismiss = { creatingSupplier = false },
            onSave = { name, _, phone, _, _ ->
                vm.createSupplierInline(name, phone) {
                    creatingSupplier = false
                    showSupplierSheet = false
                }
            },
        )
    }

    if (showCustomerSheet) {
        PickSheet(
            title = "选客户",
            empty = "还没有客户 —— 先去「客户」里建一个。",
            rows = vm.customers.map { it.id to listOf(it.name, it.phone.orEmpty()) },
            onPick = { id ->
                vm.customers.firstOrNull { it.id == id }?.let { vm.pickCustomer(it) }
                showCustomerSheet = false
            },
            onDismiss = { showCustomerSheet = false },
        )
    }

    if (showOrderSheet) {
        OrderPickSheet(vm) { showOrderSheet = false }
    }
}

/** 已挂几张采购单（⛔ 这一页不做算术：金额让后端与列表页去算）。 */
private fun orderLabel(ids: List<Long>): String = if (ids.isEmpty()) "" else "已挂 " + ids.size + " 张"

private fun contactOf(name: String, phone: String): String =
    listOf(name, phone).filter { it.isNotBlank() }.joinToString(" · ").ifBlank { "没填联系方式" }

/** 只读的那三种情形：已开具 / 已作废 / 回收站里。 */
@Composable
private fun LockedNotice(vm: InvoiceFormViewModel) {
    SectionCard {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Icon(
                Icons.Default.Lock,
                contentDescription = null,
                tint = FORM_ORANGE,
                modifier = Modifier.size(18.dp),
            )
            Spacer(Modifier.width(8.dp))
            Text(
                if (vm.isDeleted) "这张票在回收站里"
                else "这张票已经「" + ReportFinance.invoiceStatusLabel(vm.status) + "」了",
                style = MaterialTheme.typography.titleSmall,
                fontWeight = FontWeight.SemiBold,
            )
        }
        Spacer(Modifier.height(6.dp))
        Hint(
            if (vm.isDeleted) "先把它从回收站恢复，才有得改；恢复后票号还算它的，不会被别人占走。"
            else "只有「已登记」的票能改 —— 已开具 / 已作废的票一个字都不动。要改就作废重开一张。",
        )
    }
}

/**
 * 通用单选弹层：一行一个选项（标题 + 一行小字）。
 *
 * ⚠️ 用纯文本行（不是 `ListItem`）：手感跟采购单表单页那两个弹层保持一致。
 *
 * [createLabel] ＋ [onCreate] 都给上时，弹层底部多一颗按钮（**就地新建**，CHG-0068 / 台账 L-40）。
 * 两个都是可选的：选客户那处不传，形态与以前逐字一致。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun PickSheet(
    title: String,
    empty: String,
    rows: List<Pair<Long, List<String>>>
    ,
    onPick: (Long) -> Unit,
    createLabel: String? = null,
    onCreate: (() -> Unit)? = null,
    onDismiss: () -> Unit,
) {
    ModalBottomSheet(onDismissRequest = onDismiss) {
        Text(
            title,
            style = MaterialTheme.typography.titleMedium,
            fontWeight = FontWeight.SemiBold,
            modifier = Modifier.padding(start = 20.dp, end = 20.dp, bottom = 8.dp),
        )
        if (rows.isEmpty()) {
            Text(
                empty,
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(20.dp),
            )
        } else {
            LazyColumn(Modifier.heightIn(max = 420.dp)) {
                items(rows, key = { it.first }) { row ->
                    Column(
                        Modifier
                            .fillMaxWidth()
                            .clickable { onPick(row.first) }
                            .padding(horizontal = 20.dp, vertical = 12.dp),
                    ) {
                        Text(
                            row.second.firstOrNull().orEmpty(),
                            style = MaterialTheme.typography.bodyLarge,
                            fontWeight = FontWeight.Medium,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                            modifier = Modifier.fillMaxWidth(),
                        )
                        Text(
                            row.second.getOrNull(1).orEmpty().ifBlank { "没填联系方式" },
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                            modifier = Modifier.fillMaxWidth(),
                        )
                    }
                    HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
                }
            }
        }
        if (createLabel != null && onCreate != null) {
            TextButton(
                onClick = onCreate,
                modifier = Modifier.padding(start = 20.dp, end = 20.dp),
            ) { Text(createLabel) }
        }
        Spacer(Modifier.height(28.dp))
    }
}

/**
 * 挂采购单（可多选）。
 *
 * ⚠️ 只列**这家供应商**的单，且**不含回收站里的单**（后端会 `ensure_alive` 每一张挂上来的单：
 *    挂一张撤掉的采购单会被 400 弹回来，所以这一层就不该让它出现）。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun OrderPickSheet(vm: InvoiceFormViewModel, onDismiss: () -> Unit) {
    ModalBottomSheet(onDismissRequest = onDismiss) {
        Text(
            "挂采购单",
            style = MaterialTheme.typography.titleMedium,
            fontWeight = FontWeight.SemiBold,
            modifier = Modifier.padding(start = 20.dp, end = 20.dp, bottom = 4.dp),
        )
        Hint(
            "一张进项票可以挂多张采购单（都是这一家的货）；点一下就是选上 / 去掉。",
            modifier = Modifier.padding(start = 20.dp, end = 20.dp, bottom = 8.dp),
        )
        if (vm.ordersLoading) {
            LoadingBox(Modifier.height(140.dp))
        } else if (vm.orders.isEmpty()) {
            Text(
                "这家供应商还没有采购单 —— 进项票要抵的税得来自真实进过的货，先去「采购单」里建一张。",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(20.dp),
            )
        } else {
            LazyColumn(Modifier.heightIn(max = 400.dp)) {
                items(vm.orders, key = { it.id }) { po ->
                    val on = vm.purchaseOrderIds.contains(po.id)
                    Row(
                        Modifier
                            .fillMaxWidth()
                            .clickable { vm.toggleOrder(po.id) }
                            .padding(horizontal = 20.dp, vertical = 10.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Checkbox(checked = on, onCheckedChange = { vm.toggleOrder(po.id) })
                        Spacer(Modifier.width(8.dp))
                        Column(Modifier.weight(1f)) {
                            Text(
                                "#" + po.id + " · " + po.docDate,
                                style = MaterialTheme.typography.bodyLarge,
                                fontWeight = FontWeight.Medium,
                                maxLines = 1,
                                overflow = TextOverflow.Ellipsis,
                                modifier = Modifier.fillMaxWidth(),
                            )
                            Text(
                                po.itemCount.toString() + " 种 · ¥" + formatMoney(po.total),
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                                maxLines = 1,
                                overflow = TextOverflow.Ellipsis,
                                modifier = Modifier.fillMaxWidth(),
                            )
                        }
                    }
                    HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
                }
            }
        }
        PrimaryActionButton(
            text = "就挂这些（已挂 " + vm.purchaseOrderIds.size + " 张）",
            icon = Icons.Default.Check,
            onClick = onDismiss,
            modifier = Modifier.fillMaxWidth().padding(horizontal = 20.dp, vertical = 10.dp),
        )
        Spacer(Modifier.height(24.dp))
    }
}