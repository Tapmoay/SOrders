package com.tapmoay.sorders.ui.dispatcher

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
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
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.launch
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.core.InputRules
import com.tapmoay.sorders.data.remote.dto.*
import com.tapmoay.sorders.data.repo.toApiException
import com.tapmoay.sorders.ui.common.*
import com.tapmoay.sorders.ui.theme.MgrGreen
import com.tapmoay.sorders.ui.theme.MoneyOrange
import com.tapmoay.sorders.util.formatMoney
import java.math.BigDecimal
import java.time.LocalDate

// ============================================================
// 账本 V2 工具屏幕：客户收款 / 司机结算 / 开销管理 / 车辆台账
// ============================================================

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun ReuseTopBar(title: String, onBack: () -> Unit) {
    TopAppBar(
        colors = TopAppBarDefaults.topAppBarColors(containerColor = MaterialTheme.colorScheme.background),
        title = { Text(title, style = MaterialTheme.typography.titleLarge) },
        navigationIcon = {
            IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回") }
        },
    )
}

private fun today(): String = LocalDate.now().toString()

/** 统一下拉选择框：人员/类型/分类等改为下拉，避免选项多时按钮堆积；白底贴合页面背景、淡灰细边框，聚焦时才变蓝 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun DropField(
    label: String,
    text: String,
    options: List<Pair<String, String>>,
    onSelect: (String) -> Unit,
) {
    var expanded by remember { mutableStateOf(false) }
    ExposedDropdownMenuBox(expanded = expanded, onExpandedChange = { expanded = it }) {
        OutlinedTextField(
            value = text,
            onValueChange = {},
            readOnly = true,
            label = { Text(label) },
            trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(expanded = expanded) },
            colors = OutlinedTextFieldDefaults.colors(
                focusedBorderColor = MaterialTheme.colorScheme.primary,
                unfocusedBorderColor = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.55f),
                focusedLabelColor = MaterialTheme.colorScheme.primary,
                unfocusedLabelColor = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.85f),
                cursorColor = MaterialTheme.colorScheme.primary,
            ),
            modifier = Modifier.fillMaxWidth().menuAnchor(),
        )
        ExposedDropdownMenu(
            expanded = expanded,
            onDismissRequest = { expanded = false },
            // 仅比白色稍深一点：贴合白色背景又有浮层层次，不再是灰色大块
            containerColor = Color(0xFFF6F6F8),
        ) {
            options.forEach { (v, l) ->
                DropdownMenuItem(
                    text = { Text(l, maxLines = 1, overflow = TextOverflow.Ellipsis) },
                    onClick = { onSelect(v); expanded = false },
                )
            }
        }
    }
}

private fun customerText(c: CustomerDto): String = c.name + (c.phone?.takeIf { it.isNotBlank() }?.let { " " + it } ?: "")
private fun driverText(d: UserDto): String = d.fullName ?: d.phone ?: d.username

// ---------------- 客户收款（逐单核销） ----------------
class ReceiptsViewModel(private val container: AppContainer) : androidx.lifecycle.ViewModel() {
    var customers by mutableStateOf<List<CustomerDto>>(emptyList())
    var orders by mutableStateOf<List<OrderDto>>(emptyList())
    var receipts by mutableStateOf<List<ReceiptDto>>(emptyList())
    var loading by mutableStateOf(false)
    var error by mutableStateOf<String?>(null)
    var actionResult by mutableStateOf<String?>(null)

    var selectedCustomer by mutableStateOf<CustomerDto?>(null)
    var amount by mutableStateOf("")
    var method by mutableStateOf("cash")
    var receivedAt by mutableStateOf("")
    var selectedOrderIds by mutableStateOf<Set<Long>>(emptySet())
    var submitting by mutableStateOf(false)

    fun load() {
        loading = true
        viewModelScope.launch {
            try {
                customers = container.repo.customers()
                receipts = container.repo.receipts()
                if (receivedAt.isBlank()) receivedAt = today()
                orders = emptyList()
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                loading = false
            }
        }
    }

    fun onCustomerSelect(c: CustomerDto) {
        selectedCustomer = c
        selectedOrderIds = emptySet()
        amount = ""
        loadCustomerOrders()
    }

    fun loadCustomerOrders() {
        val c = selectedCustomer ?: return
        // ⛔ 临时客户（散客）**没有绑定账号**（`user_id == null`）。原来这里的 `shipperId = c.userId`
        //    会把 null 交给 Retrofit，而 null 的查询参数会被**整条丢掉** → 后端对派单员不带
        //    `shipper_id` 时返回**全库**已送达单 → 界面标题写着「该客户的未收款订单」，
        //    列出的却是**全公司**所有未收款订单（用户照着这个列表勾选、算合计），提交才 400。
        //    这是跨客户数据显示：宁可不给列表，也不能给错的列表（2026-09-19 审计）。
        if (c.userId == null) {
            orders = emptyList()
            error = "「${c.name}」是临时客户（没有绑定账号），逐单核销用不了。" +
                "请改用「滚动收款」，或先把这个客户关联到一个货主账号。"
            return
        }
        error = null
        viewModelScope.launch {
            try {
                orders = container.repo.orders(status = "DELIVERED", shipperId = c.userId).filter { !it.paid }
            } catch (e: Exception) {
                error = toApiException(e).message
            }
        }
    }

    /**
     * 一张订单的商品行合计（**定点**，两位小数）。
     *
     * 本屏**唯一**的金额求和实现：明细行的 ¥ 与「合计 ¥」都走它，保证"显示的数 = 判据的数"。
     */
    fun orderTotal(o: OrderDto): BigDecimal =
        o.orderProducts.fold(BigDecimal.ZERO) { a, p -> a.add(p.lineTotal?.toBigDecimalOrNull() ?: BigDecimal.ZERO) }

    /**
     * 所选订单合计（**定点**）。
     *
     * ⛔ 这里不许用 `Double` 累加（2026-09-19 全项目 bug 报告 P0-4，high）：
     * 后端 `accounting_service` 用 **Decimal 定点**相加，而界面把**后端算出的那个数**（两位小数）
     * 显示给用户、让用户照抄填进输入框——原来判据用的却是 `Double` 顺序累加的结果，
     * 也就是**两个不同的数**。守护者 20 万次随机试验的失配率：2 行 22.72% / 3 行 26.59% /
     * 4 行 33.44% / 5 行 37.68%。实测表现是「界面显示合计 ¥3190.68 → 照抄填入 → 红字说
     * 需要 ¥3190.68」，而唯一的"自救"办法（把位数打多成 3190.6800000000003）会被后端
     * `Decimal(body.amount) != total` 立刻 400 → **多行/多单时永久收不了款**。
     * 写法与本仓库既有实现同源（`ai/AiWriteService.kt:473`）。
     */
    fun computeTotal(): BigDecimal = orders
        .filter { it.id in selectedOrderIds }
        .fold(BigDecimal.ZERO) { acc, o -> acc.add(orderTotal(o)) }

    fun submit() {
        val c = selectedCustomer ?: return
        if (selectedOrderIds.isEmpty()) { error = "请勾选绑定订单"; return }
        val total = computeTotal()
        // 金额按**定点**比（`compareTo`），不按 Double 比；显示与判据用同一个 BigDecimal。
        if (amount.trim().toBigDecimalOrNull()?.compareTo(total) != 0) {
            error = "收款金额需等于所选订单合计 ¥" + formatMoney(total.toPlainString())
            return
        }
        submitting = true
        viewModelScope.launch {
            try {
                container.repo.createReceipt(ReceiptCreateRequest(c.id, amount, method, receivedAt, selectedOrderIds.toList(), "itemized"))
                actionResult = "收款已记录"
                receipts = container.repo.receipts()
                selectedOrderIds = emptySet()
                amount = ""
                loadCustomerOrders()
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                submitting = false
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ReceiptsScreen(container: AppContainer, onBack: () -> Unit) {
    val vm: ReceiptsViewModel = appViewModel { ReceiptsViewModel(container) }
    val snackbar = remember { SnackbarHostState() }
    OneShotSnackbar(snackbar, vm.actionResult, onConsumed = { vm.actionResult = null })
    LaunchedEffect(Unit) { vm.load() }
    Scaffold(
        snackbarHost = { SnackbarHost(snackbar) },
        topBar = { ReuseTopBar("客户收款", onBack) },
    ) { padding ->
        LazyColumn(Modifier.fillMaxSize().padding(padding), contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            item {
                SectionCard {
                    Text("选择客户（逐单核销）", style = MaterialTheme.typography.titleSmall)
                    Spacer(Modifier.height(6.dp))
                    if (vm.customers.isEmpty()) {
                        Text("暂无客户档案（散客需先创建：名称+电话）", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    } else {
                        DropField(
                            label = "客户",
                            text = vm.selectedCustomer?.let { customerText(it) } ?: "请选择客户",
                            options = vm.customers.map { it.id.toString() to customerText(it) },
                            onSelect = { id -> vm.customers.find { it.id.toString() == id }?.let { vm.onCustomerSelect(it) } },

                        )
                    }
                    vm.selectedCustomer?.let { c ->
                        Spacer(Modifier.height(8.dp))
                        Text("未收款订单", style = MaterialTheme.typography.titleSmall)
                        Spacer(Modifier.height(4.dp))
                        if (vm.orders.isEmpty()) {
                            Text("该客户暂无未收款订单", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        } else {
                            vm.orders.forEach { o ->
                                Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.fillMaxWidth().clickable {
                                    vm.selectedOrderIds = if (o.id in vm.selectedOrderIds) vm.selectedOrderIds - o.id else vm.selectedOrderIds + o.id
                                }.padding(vertical = 2.dp)) {
                                    Checkbox(checked = o.id in vm.selectedOrderIds, onCheckedChange = {
                                        vm.selectedOrderIds = if (o.id in vm.selectedOrderIds) vm.selectedOrderIds - o.id else vm.selectedOrderIds + o.id
                                    })
                                    Text(o.orderNo + "  ¥" + formatMoney(vm.orderTotal(o).toPlainString()), style = MaterialTheme.typography.bodyMedium, maxLines = 1, overflow = TextOverflow.Ellipsis)
                                }
                            }
                        }
                        Spacer(Modifier.height(6.dp))
                        Text("合计 ¥" + formatMoney(vm.computeTotal().toPlainString()), style = MaterialTheme.typography.titleSmall, color = Color(MoneyOrange))
                        OutlinedTextField(value = vm.amount, onValueChange = { vm.amount = InputRules.moneyInput(it) }, label = { Text("收款金额＝所选订单合计") }, modifier = Modifier.fillMaxWidth(), singleLine = true, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal))
                        Spacer(Modifier.height(6.dp))
                        DropField(
                            label = "收款方式",
                            text = methodLabel(vm.method),
                            options = listOf("cash" to "现金", "transfer" to "转账", "wechat" to "微信", "arrears_settle" to "挂账结清"),
                            onSelect = { vm.method = it },

                        )
                        Spacer(Modifier.height(6.dp))
                        OutlinedTextField(value = vm.receivedAt, onValueChange = { vm.receivedAt = it }, label = { Text("收款日期") }, modifier = Modifier.fillMaxWidth(), singleLine = true)
                        Spacer(Modifier.height(10.dp))
                        Button(onClick = { vm.submit() }, enabled = !vm.submitting, modifier = Modifier.fillMaxWidth().height(48.dp), colors = ButtonDefaults.buttonColors(containerColor = Color(MoneyOrange))) {
                            if (vm.submitting) CircularProgressIndicator(Modifier.size(20.dp), color = Color.White, strokeWidth = 2.dp)
                            else Text("确认收款（逐单核销）")
                        }
                        vm.error?.let { Text(it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall) }
                    }
                }
            }
            item { Text("收款记录", style = MaterialTheme.typography.titleMedium) }
            if (vm.receipts.isEmpty()) item { EmptyView("暂无收款记录", Modifier.fillMaxWidth()) }
            else items(vm.receipts, key = { it.id }) { r ->
                SectionCard {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Icon(Icons.Default.Payments, contentDescription = null, tint = Color(MoneyOrange), modifier = Modifier.size(22.dp))
                        Spacer(Modifier.width(8.dp))
                        Column(Modifier.weight(1f)) {
                            Text(r.customerName ?: "客户", style = MaterialTheme.typography.titleSmall)
                            Text(r.receivedAt + " · " + methodLabel(r.method), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                        Text("¥" + formatMoney(r.amount), style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Bold, color = Color(MoneyOrange))
                    }
                    Spacer(Modifier.height(4.dp))
                    Text("核销订单：" + r.orderIds.joinToString(", "), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
        }
    }
}

private fun methodLabel(m: String): String = when (m) { "cash" -> "现金"; "transfer" -> "转账"; "wechat" -> "微信"; "arrears_settle" -> "挂账结清"; else -> m }

// ---------------- 司机结算（按月） ----------------
class SettlementsViewModel(private val container: AppContainer) : androidx.lifecycle.ViewModel() {
    var drivers by mutableStateOf<List<UserDto>>(emptyList())
    var settlements by mutableStateOf<List<SettlementDto>>(emptyList())
    var bills by mutableStateOf<List<DriverBillDto>>(emptyList())
    var loading by mutableStateOf(false)
    var error by mutableStateOf<String?>(null)
    var actionResult by mutableStateOf<String?>(null)

    var selectedDriver by mutableStateOf<Long?>(null)
    var month by mutableStateOf("")
    var settleType by mutableStateOf("piece")
    var submitting by mutableStateOf(false)

    fun load() {
        loading = true
        viewModelScope.launch {
            try {
                drivers = container.repo.drivers()
                settlements = container.repo.settlements()
                if (month.isBlank()) month = LocalDate.now().toString().substring(0, 7)
                loadBills()
            } catch (e: Exception) { error = toApiException(e).message } finally { loading = false }
        }
    }

    fun loadBills() {
        viewModelScope.launch {
            try { bills = container.repo.driverBills(month = month, status = "open") } catch (e: Exception) { error = toApiException(e).message }
        }
    }

    fun createSettlement() {
        val d = selectedDriver ?: run { error = "请选择司机"; return }
        submitting = true
        viewModelScope.launch {
            try {
                container.repo.createSettlement(SettlementCreateRequest(d, settleType, month))
                actionResult = "结算单已创建（草稿）"
                settlements = container.repo.settlements()
                loadBills()
            } catch (e: Exception) { error = toApiException(e).message } finally { submitting = false }
        }
    }

    fun act(s: SettlementDto, action: String) {
        viewModelScope.launch {
            try {
                container.repo.settlementAction(s.id, action)
                actionResult = when (action) { "confirm" -> "已确认"; "pay" -> "已付款"; "cancel" -> "已取消"; else -> "已操作" }
                settlements = container.repo.settlements()
                loadBills()
            } catch (e: Exception) { error = toApiException(e).message }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SettlementsScreen(container: AppContainer, onBack: () -> Unit) {
    val vm: SettlementsViewModel = appViewModel { SettlementsViewModel(container) }
    val snackbar = remember { SnackbarHostState() }
    OneShotSnackbar(snackbar, vm.actionResult, onConsumed = { vm.actionResult = null })
    LaunchedEffect(Unit) { vm.load() }
    Scaffold(snackbarHost = { SnackbarHost(snackbar) }, topBar = { ReuseTopBar("司机结算（按月）", onBack) }) { padding ->
        LazyColumn(Modifier.fillMaxSize().padding(padding), contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            item {
                SectionCard {
                    Text("新建结算单", style = MaterialTheme.typography.titleSmall)
                    Spacer(Modifier.height(6.dp))
                    DropField(
                        label = "司机",
                        text = vm.drivers.find { it.id == vm.selectedDriver }?.let { driverText(it) } ?: "请选择司机",
                        options = vm.drivers.map { it.id.toString() to driverText(it) },
                        onSelect = { vm.selectedDriver = it.toLongOrNull() },

                    )
                    Spacer(Modifier.height(8.dp))
                    DropField(
                        label = "结算类型",
                        text = if (vm.settleType == "piece") "按单 PIECE" else "固定工资",
                        options = listOf("piece" to "按单 PIECE", "salary" to "固定工资"),
                        onSelect = { vm.settleType = it },

                    )
                    Spacer(Modifier.height(6.dp))
                    OutlinedTextField(value = vm.month, onValueChange = { vm.month = it; vm.loadBills() }, label = { Text("结算月份 YYYY-MM") }, modifier = Modifier.fillMaxWidth(), singleLine = true)
                    Spacer(Modifier.height(4.dp))
                    Text("本月待结明细 ¥" + formatMoney(vm.bills.sumOf { b -> b.amount.toDoubleOrNull() ?: 0.0 }.toString()) + "（" + vm.bills.size + " 笔）", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    vm.error?.let { Text(it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall) }
                    Spacer(Modifier.height(8.dp))
                    Button(onClick = { vm.createSettlement() }, enabled = !vm.submitting, modifier = Modifier.fillMaxWidth().height(48.dp), colors = ButtonDefaults.buttonColors(containerColor = Color(MgrGreen))) {
                        Text(if (vm.submitting) "生成中…" else "创建结算单（草稿）")
                    }
                }
            }
            item { Text("结算单列表", style = MaterialTheme.typography.titleMedium) }
            if (vm.settlements.isEmpty()) item { EmptyView("暂无结算单", Modifier.fillMaxWidth()) }
            else items(vm.settlements, key = { it.id }) { s ->
                SectionCard {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Column(Modifier.weight(1f)) {
                            Text((s.driverName ?: "司机") + " · " + s.month + " · " + (if (s.settleType == "piece") "按单" else "工资"), style = MaterialTheme.typography.titleSmall)
                            Text(statusLabel(s.status), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                        Text("¥" + formatMoney(s.amount), style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Bold, color = Color(MoneyOrange))
                    }
                    Spacer(Modifier.height(6.dp))
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        if (s.status == "draft") {
                            OutlinedButton(onClick = { vm.act(s, "confirm") }, modifier = Modifier.weight(1f)) { Text("确认") }
                            OutlinedButton(onClick = { vm.act(s, "cancel") }, modifier = Modifier.weight(1f)) { Text("取消") }
                        } else if (s.status == "confirmed") {
                            Button(onClick = { vm.act(s, "pay") }, modifier = Modifier.weight(1f), colors = ButtonDefaults.buttonColors(containerColor = Color(MgrGreen))) { Text("标记已付款") }
                        } else {
                            Text(s.paidAt?.let { "已付 " + it.substring(0, 10) } ?: statusLabel(s.status), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                    }
                }
            }
        }
    }
}

private fun statusLabel(s: String): String = when (s) { "draft" -> "草稿"; "confirmed" -> "已确认"; "paid" -> "已付款"; "cancelled" -> "已取消"; else -> s }

// ---------------- 开销管理 ----------------
class ExpensesViewModel(private val container: AppContainer) : androidx.lifecycle.ViewModel() {
    var expenses by mutableStateOf<List<ExpenseDto>>(emptyList())
    var drivers by mutableStateOf<List<UserDto>>(emptyList())
    var loading by mutableStateOf(false)
    var error by mutableStateOf<String?>(null)
    var actionResult by mutableStateOf<String?>(null)

    var category by mutableStateOf("fuel")
    var amount by mutableStateOf("")
    var expDate by mutableStateOf("")
    var driverId by mutableStateOf<Long?>(null)
    var note by mutableStateOf("")
    var submitting by mutableStateOf(false)

    fun load() {
        loading = true
        viewModelScope.launch {
            try {
                expenses = container.repo.expenses()
                drivers = container.repo.drivers()
                if (expDate.isBlank()) expDate = today()
            } catch (e: Exception) { error = toApiException(e).message } finally { loading = false }
        }
    }

    fun submit() {
        if ((amount.toDoubleOrNull() ?: 0.0) <= 0) { error = "请输入金额"; return }
        submitting = true
        viewModelScope.launch {
            try {
                container.repo.createExpense(ExpenseCreateRequest(expDate, category, amount, driverId, null, null, note))
                actionResult = "开销已记录"
                expenses = container.repo.expenses()
                amount = ""; note = ""
            } catch (e: Exception) { error = toApiException(e).message } finally { submitting = false }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ExpensesScreen(container: AppContainer, onBack: () -> Unit) {
    val vm: ExpensesViewModel = appViewModel { ExpensesViewModel(container) }
    val snackbar = remember { SnackbarHostState() }
    OneShotSnackbar(snackbar, vm.actionResult, onConsumed = { vm.actionResult = null })
    LaunchedEffect(Unit) { vm.load() }
    Scaffold(snackbarHost = { SnackbarHost(snackbar) }, topBar = { ReuseTopBar("开销管理", onBack) }) { padding ->
        LazyColumn(Modifier.fillMaxSize().padding(padding), contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            item {
                SectionCard {
                    Text("新增开销", style = MaterialTheme.typography.titleSmall)
                    Spacer(Modifier.height(6.dp))
                    val cats = listOf("fuel" to "加油", "repair" to "维修", "toll" to "过路", "parking" to "停车", "fine" to "罚款", "insurance" to "保险", "loss" to "货损", "other" to "其他")
                    DropField(label = "开销分类", text = catLabel(vm.category), options = cats, onSelect = { vm.category = it })
                    Spacer(Modifier.height(8.dp))
                    OutlinedTextField(value = vm.amount, onValueChange = { vm.amount = InputRules.moneyInput(it) }, label = { Text("金额") }, modifier = Modifier.fillMaxWidth(), singleLine = true, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal))
                    Spacer(Modifier.height(6.dp))
                    OutlinedTextField(value = vm.expDate, onValueChange = { vm.expDate = it }, label = { Text("日期") }, modifier = Modifier.fillMaxWidth(), singleLine = true)
                    Spacer(Modifier.height(6.dp))
                    DropField(
                        label = "关联司机（可选）",
                        text = vm.drivers.find { it.id == vm.driverId }?.let { driverText(it) } ?: "不指定",
                        options = listOf("" to "不指定") + vm.drivers.map { it.id.toString() to driverText(it) },
                        onSelect = { vm.driverId = it.toLongOrNull() },

                    )
                    Spacer(Modifier.height(8.dp))
                    OutlinedTextField(value = vm.note, onValueChange = { vm.note = it }, label = { Text("备注") }, modifier = Modifier.fillMaxWidth(), singleLine = true)
                    vm.error?.let { Text(it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall) }
                    Spacer(Modifier.height(8.dp))
                    Button(onClick = { vm.submit() }, enabled = !vm.submitting, modifier = Modifier.fillMaxWidth().height(48.dp), colors = ButtonDefaults.buttonColors(containerColor = Color(MoneyOrange))) {
                        Text(if (vm.submitting) "保存中…" else "保存开销")
                    }
                }
            }
            item { Text("开销记录", style = MaterialTheme.typography.titleMedium) }
            if (vm.expenses.isEmpty()) item { EmptyView("暂无开销记录", Modifier.fillMaxWidth()) }
            else items(vm.expenses, key = { it.id }) { e ->
                SectionCard {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Icon(Icons.Default.ReceiptLong, contentDescription = null, tint = Color(0xFF00A2C7), modifier = Modifier.size(22.dp))
                        Spacer(Modifier.width(8.dp))
                        Column(Modifier.weight(1f)) {
                            Text(catLabel(e.category), style = MaterialTheme.typography.titleSmall)
                            Text(e.expDate + (e.driverName?.let { " · " + it } ?: "") + (e.orderNo?.let { " · " + it } ?: ""), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                            if (e.note.isNotBlank()) Text(e.note, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                        Text("¥" + formatMoney(e.amount), style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Bold, color = Color(MoneyOrange))
                    }
                }
            }
        }
    }
}

private fun catLabel(c: String): String = when (c) { "fuel" -> "加油"; "repair" -> "维修"; "toll" -> "过路"; "parking" -> "停车"; "fine" -> "罚款"; "insurance" -> "保险"; "loss" -> "货损"; else -> "其他" }

// ---------------- 车辆：已迁到 VehicleManageScreen.kt（v3.44） ----------------
//
// 原来这里只有一个「新增车辆 + 只读列表」的台账：没有编辑、没有解绑司机。
// 用户原话「司机的车辆绑定 App 端做不到」指的就是这件事 —— 想换车只能改数据库。
// 现在整屏（列表/编辑/绑司机/停用）都在 VehicleManageScreen.kt，
// 而且**司机管理页也能绑**（同一个接口，两个视角）。
