package com.tapmoay.sorders.ui.dispatcher

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Person
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
import com.tapmoay.sorders.core.UserSearch
import com.tapmoay.sorders.data.remote.dto.DriverBillDto
import com.tapmoay.sorders.data.remote.dto.DriverBillGenerateRequest
import com.tapmoay.sorders.data.remote.dto.SettlementCreateRequest
import com.tapmoay.sorders.data.remote.dto.SettlementDto
import com.tapmoay.sorders.data.remote.dto.UserDto
import com.tapmoay.sorders.data.repo.toApiException
import com.tapmoay.sorders.ui.common.*
import com.tapmoay.sorders.ui.driver.SalaryChange
import com.tapmoay.sorders.ui.driver.SalaryTotals
import com.tapmoay.sorders.ui.driver.isSettledBill
import com.tapmoay.sorders.ui.driver.salaryBillsOf
import com.tapmoay.sorders.ui.driver.salaryChangesOf
import com.tapmoay.sorders.ui.driver.settledBillCountOf
import com.tapmoay.sorders.ui.driver.salaryMonthWord
import com.tapmoay.sorders.ui.driver.salaryTotalsOf
import com.tapmoay.sorders.ui.theme.MgrGreen
import com.tapmoay.sorders.ui.theme.MoneyOrange
import com.tapmoay.sorders.util.formatMoney
import com.tapmoay.sorders.util.moneyToDouble
import kotlinx.coroutines.launch
import java.time.LocalDate

/**
 * 司机工资（按月）—— 派单员给**固定工资司机**核销工资的落点（2026-10-15，CHG-0127）。
 *
 * ## 为什么单开一页
 * 用户口径（m43131）：「我们那个派单员可以在司机账本这里啊，对他的工资进行核销」。
 * 司机账本（`Routes.FREIGHT_SETTLEMENT`，`FreightSettlementScreen`）算的是**运费**
 * （`freight-settlement`，跟时间档位走）；工资是**另一条账**：数据源是 `driver-bills`
 * （`bill_type = salary`，按 `month`），核销走**结算单**（`settle_type = salary` ——
 * 后端取数是 `DriverBill.bill_type == settle_type`，见 `services/accounting_service.py:613`）。
 * 把两种钱塞进同一屏，就会出现"明细加起来不等于上面那个数"的老毛病 —— 所以入口挂在那一页上、
 * 账本身各算各的。
 *
 * ## 与「司机结算（按月）」的分工
 * `Routes.DISPATCH_SETTLEMENTS`（`SettlementsScreen`）是**通用**的：选人 + 选类型 + 填月份，
 * 走完一张单。这一页是**专做工资**的快捷方式：只认 salary，一次点完「生成 / 重算 + 核销」，
 * 并把这个司机全部月份的工资单、已核销/未核销、任职期间的工资变更一次列全。
 * ⛔ 这一页**不新增任何写接口、不改任何取数口径**：只调既有的三个（`driver-bills`、
 * `driver-bills/generate`、`driver-settlements`）。
 */
class DriverSalaryViewModel(private val container: AppContainer) : ViewModel() {
    var drivers by mutableStateOf<List<UserDto>>(emptyList())
        private set

    /** 现在在看哪位司机（null = 还没选 —— 这一页没有"全部"这一档：工资必须落到人头上）。 */
    var selectedId by mutableStateOf<Long?>(null)
        private set

    /** 要核销/生成哪个月（`YYYY-MM`）。默认当月 —— 派单员核销时十次有九次是"这个月"。 */
    var month by mutableStateOf(LocalDate.now().toString().substring(0, 7))

    /** 抽屉里的搜索词（与账本/运费结算同一套零件）。 */
    var query by mutableStateOf("")

    /** 这位司机**全部月份**的工资单（不过滤月份：下面的明细与变更记录都要看全）。 */
    var bills by mutableStateOf<List<DriverBillDto>>(emptyList())
        private set

    /** 这位司机的结算单（含草稿：草稿已经把工资锁住了 —— 再点核销必须认出它）。 */
    var settlements by mutableStateOf<List<SettlementDto>>(emptyList())
        private set

    var loading by mutableStateOf(false)
        private set

    /** 有写在跑（生成/核销/付款/作废）——期间按钮要禁用：重复点等于发两遍。 */
    var working by mutableStateOf(false)
        private set

    var error by mutableStateOf<String?>(null)
        private set

    /** 一次性提示（生成/核销/付款/作废的结果）—— 界面读完置空，所以**不能** private set。 */
    var notice by mutableStateOf<String?>(null)

    val thisMonth: String get() = LocalDate.now().toString().substring(0, 7)
    val lastMonth: String get() = LocalDate.now().minusMonths(1).toString().substring(0, 7)

    val selectedName: String get() = drivers.firstOrNull { it.id == selectedId }?.let { driverText(it) }.orEmpty()

    /**
     * 抽屉里那份名册：按 [query] 过滤。
     *
     * 走唯一实现 `UserSearch`（姓名 / 手机号，**后 4 位天然命中**：`8006` 命中 `13800000006`）——
     * 名册一次回全量（`/users?role=driver&limit=500`，71 人），不筛的话搜索框就是画着好看：
     * 找一个人只能靠滚。2026-10-15 真机走查时发现的（在框里打 0006，名册纹丝不动）。
     */
    val visibleDrivers: List<UserDto> get() = UserSearch.filter(drivers, query, { driverText(it) }, { it.phone })

    val salaryRows: List<DriverBillDto> get() = salaryBillsOf(bills)
    val totals: SalaryTotals get() = salaryTotalsOf(bills)
    val changes: List<SalaryChange> get() = salaryChangesOf(bills)

    /** 这个月**还没核销**的工资单（"要核多少钱"就看它）。 */
    val monthOpen: List<DriverBillDto> get() = salaryRows.filter { it.month == month && !isSettledBill(it) }

    /**
     * 这个月那张**还没作废**的工资结算单（草稿也算）。
     *
     * 为什么要连草稿一起认：建单当刻后端就把这批工资单的 `settled_doc_id` 写成了这张单的 id
     * （`accounting_service.create_settlement` 末尾）—— 再建一张会直接被拒「已经被别的结算单锁住了」。
     */
    val monthSettlement: SettlementDto? get() = settlements.firstOrNull {
        it.settleType == "salary" && it.month == month && it.status != "cancelled"
    }

    fun load() {
        loading = true
        viewModelScope.launch {
            try {
                drivers = container.repo.drivers()
                if (selectedId == null || drivers.none { it.id == selectedId }) selectedId = drivers.firstOrNull()?.id
                reload()
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                loading = false
            }
        }
    }

    fun select(id: Long?) {
        selectedId = id
        refresh()
    }

    fun refresh() {
        viewModelScope.launch {
            try { reload() } catch (e: Exception) { error = toApiException(e).message }
        }
    }

    private suspend fun reload() {
        val id = selectedId ?: return
        bills = container.repo.driverBills(driverId = id)
        settlements = container.repo.settlements(driverId = id)
    }

    /** 生成 / 重算：只碰**没被核销**的那几张（后端的 `refresh_unsettled`，缺省不会覆盖）。 */
    fun generate() {
        val id = selectedId ?: run { error = "请先选一位司机"; return }
        working = true
        viewModelScope.launch {
            try {
                container.repo.generateBills(
                    DriverBillGenerateRequest(
                        driverId = id,
                        month = month,
                        billType = "salary",
                        refreshUnsettled = true,
                    ),
                )
                reload()
                notice = "已按他现在的固定工资核对 " + month + " 的工资单（未核销的跟着变，已核销的一分没动）"
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                working = false
            }
        }
    }

    /**
     * **一键核销这个月的工资**。
     *
     * 三种情况：已有草稿单 → 确认它；这个月还没有单 → 建单再确认；已经有确认/已付款的单 →
     * 如实说"已经在哪张单上"，**不重复建单**（后端也会拒）。
     */
    fun settle() {
        val id = selectedId ?: run { error = "请先选一位司机"; return }
        working = true
        viewModelScope.launch {
            try {
                val existing = monthSettlement
                if (existing != null && existing.status != "draft") {
                    notice = month + " 的工资已经在结算单 #" + existing.id + " 上（" + settlementWord(existing.status) + "）"
                    return@launch
                }
                val docId = existing?.id ?: container.repo.createSettlement(
                    SettlementCreateRequest(driverId = id, settleType = "salary", month = month),
                ).id
                container.repo.settlementAction(docId, "confirm")
                reload()
                notice = month + " 的工资已核销（结算单 #" + docId + "）"
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                working = false
            }
        }
    }

    /** 已确认的单子：标记已付款（钱真的出去了 —— 这一步只有派单员能做）。 */
    fun pay(s: SettlementDto) {
        working = true
        viewModelScope.launch {
            try {
                container.repo.settlementAction(s.id, "pay")
                reload()
                notice = "结算单 #" + s.id + " 已标记付款"
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                working = false
            }
        }
    }

    /** 作废草稿：那一批工资的锁会放开（后端 `cancel_settlement` 把 `settled_doc_id` 放回）。 */
    fun cancel(s: SettlementDto) {
        working = true
        viewModelScope.launch {
            try {
                container.repo.settlementAction(s.id, "cancel")
                reload()
                notice = "结算单 #" + s.id + " 已作废"
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                working = false
            }
        }
    }
}

/** 结算单状态 → 人话（与 `AccountToolsScreens.statusLabel` 同一套词，故意重复一份：那边的私有）。 */
private fun settlementWord(s: String): String = when (s) {
    "draft" -> "草稿"
    "confirmed" -> "已确认"
    "paid" -> "已付款"
    "cancelled" -> "已作废"
    else -> s
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DriverSalaryScreen(
    container: AppContainer,
    onBack: () -> Unit,
    /** 通用结算单页的出口（这一页只做工资；要看全部类型的单子去那儿）。 */
    onOpenSettlements: () -> Unit = {},
) {
    val vm: DriverSalaryViewModel = appViewModel { DriverSalaryViewModel(container) }
    val snackbar = remember { SnackbarHostState() }
    OneShotSnackbar(snackbar, vm.notice, onConsumed = { vm.notice = null })
    LaunchedEffect(Unit) { vm.load() }
    // 选人 = 侧边抽屉（与运费结算/账本同一个零件）：人一多，一排 chip 就选不过来
    val drawer = rememberDrawerState(DrawerValue.Closed)
    val scope = rememberCoroutineScope()
    var pendingCancel by remember { mutableStateOf<SettlementDto?>(null) }

    ModalNavigationDrawer(
        drawerState = drawer,
        drawerContent = {
            ModalDrawerSheet {
                PersonDrawer(
                    title = "选择司机",
                    options = vm.visibleDrivers.map {
                        PersonOption(
                            key = it.id.toString(),
                            title = driverText(it),
                            subtitle = it.phone.orEmpty(),
                        )
                    },
                    selectedKey = vm.selectedId?.toString(),
                    query = vm.query,
                    onQueryChange = { vm.query = it },
                    onPick = { key ->
                        vm.select(key?.toLongOrNull())
                        scope.launch { drawer.close() }
                    },
                    emptyText = UserSearch.noMatchText(vm.query) + "司机",
                )
            }
        },
    ) {
        Scaffold(
            snackbarHost = { SnackbarHost(snackbar) },
            topBar = { AppTopBar(title = "司机工资（按月）", onBack = onBack) },
        ) { pad ->
            Column(Modifier.fillMaxSize().padding(pad)) {
                PersonTriggerRow(
                    icon = Icons.Default.Person,
                    color = Color(MgrGreen),
                    label = "司机",
                    value = vm.selectedName.ifBlank { "请选择司机" },
                    onOpen = {
                        vm.query = ""
                        scope.launch { drawer.open() }
                    },
                )
                when {
                    vm.loading && vm.drivers.isEmpty() -> LoadingBox()
                    vm.error != null -> ErrorView(vm.error.orEmpty(), onRetry = { vm.load() })
                    vm.selectedId == null -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                        EmptyView("还没有可选的司机 —— 先去「司机管理」把司机建出来")
                    }
                    else -> SalaryBody(vm, onOpenSettlements) { pendingCancel = it }
                }
            }
        }
    }

    pendingCancel?.let { s ->
        DangerConfirmDialog(
            title = "作废这张草稿？",
            message = "作废之后 " + s.month + " 这批工资的锁会放开，可以重新核销。",
            confirmText = "作废",
            onConfirm = {
                vm.cancel(s)
                pendingCancel = null
            },
            onDismiss = { pendingCancel = null },
            enabled = !vm.working,
        )
    }
}

@Composable
private fun SalaryBody(
    vm: DriverSalaryViewModel,
    onOpenSettlements: () -> Unit,
    onAskCancel: (SettlementDto) -> Unit,
) {
    LazyColumn(
        Modifier.fillMaxSize(),
        contentPadding = PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        item { MonthCard(vm) }
        item { TotalCard(vm) }
        if (vm.salaryRows.isEmpty()) {
            item { EmptyView("这位司机还没有工资单 —— 点上面「生成 / 重算」", Modifier.fillMaxWidth()) }
        } else {
            item { Text("按月明细", style = MaterialTheme.typography.titleMedium) }
            items(vm.salaryRows, key = { "bill-" + it.id }) { b -> BillRow(b) }
        }
        if (vm.changes.isNotEmpty()) item { ChangeCard(vm.changes) }
        item { SettlementCard(vm, onOpenSettlements, onAskCancel) }
    }
}

/** 核销哪个月 + 两颗按钮（生成/重算、一键核销）。 */
@Composable
private fun MonthCard(vm: DriverSalaryViewModel) {
    val openBills = vm.monthOpen
    val openMoney = openBills.sumOf { moneyToDouble(it.amount) }
    val doc = vm.monthSettlement
    SectionCard {
        Text("核销哪个月", style = MaterialTheme.typography.titleMedium)
        Spacer(Modifier.height(6.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            FilterChip(selected = vm.month == vm.thisMonth, onClick = { vm.month = vm.thisMonth }, label = { Text("本月") })
            FilterChip(selected = vm.month == vm.lastMonth, onClick = { vm.month = vm.lastMonth }, label = { Text("上个月") })
        }
        Spacer(Modifier.height(6.dp))
        OutlinedTextField(
            value = vm.month,
            onValueChange = { vm.month = it },
            label = { Text("月份 YYYY-MM") },
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
        )
        Spacer(Modifier.height(6.dp))
        Text(
            if (openBills.isEmpty()) {
                vm.month + " 没有待核销的工资单"
            } else {
                vm.month + " 待核销 ¥" + formatMoney(openMoney.toString()) + "（" + openBills.size + " 笔）"
            },
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        doc?.let {
            Text(
                "这个月已经有一张结算单 #" + it.id + "（" + settlementWord(it.status) + "）",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        Spacer(Modifier.height(8.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedButton(
                onClick = { vm.generate() },
                enabled = !vm.working,
                modifier = Modifier.weight(1f),
            ) { Text("生成 / 重算") }
            Button(
                onClick = { vm.settle() },
                enabled = !vm.working && (openBills.isNotEmpty() || doc?.status == "draft"),
                modifier = Modifier.weight(1f),
                colors = ButtonDefaults.buttonColors(containerColor = Color(MgrGreen)),
            ) { Text(if (vm.working) "处理中…" else "核销这个月的工资") }
        }
        Spacer(Modifier.height(4.dp))
        Hint(
            "「生成 / 重算」只动没核销的那几张（按他现在的固定工资重算）；已核销的一分不变 —— 那是拍过板的凭据。",
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

/** 已核销 / 未核销两个数（口径见 `ui/driver/DriverSalary.kt`）。 */
@Composable
private fun TotalCard(vm: DriverSalaryViewModel) {
    val t = vm.totals
    SectionCard {
        Text("总共（" + t.count + " 个月）", style = MaterialTheme.typography.titleMedium)
        Spacer(Modifier.height(6.dp))
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text("已核销（" + t.settledCount + " 个月）", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                Text("¥" + formatMoney(t.settled.toString()), style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold, color = Color(MgrGreen))
            }
            Column(Modifier.weight(1f)) {
                Text("未核销（" + t.openCount + " 个月）", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                Text("¥" + formatMoney(t.open.toString()), style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold, color = Color(MoneyOrange))
            }
        }
    }
}

/** 一个月一张工资单：月份 + 金额 + 核销状态。 */
@Composable
private fun BillRow(b: DriverBillDto) {
    val settled = isSettledBill(b)
    SectionCard {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text(salaryMonthWord(b.month), style = MaterialTheme.typography.titleSmall)
                Text(
                    b.note.ifBlank { b.ruleName }.ifBlank { "固定工资" },
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            Column(horizontalAlignment = Alignment.End) {
                Text("¥" + formatMoney(b.amount), style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold, color = Color(MoneyOrange))
                Text(
                    if (settled) "已核销" else "未核销",
                    style = MaterialTheme.typography.labelSmall,
                    color = if (settled) Color(MgrGreen) else MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
    }
}

/** 任职期间的工资变更记录（相邻两张工资单不一样就是一次）。 */
@Composable
private fun ChangeCard(changes: List<SalaryChange>) {
    SectionCard {
        Text("工资变更记录", style = MaterialTheme.typography.titleMedium)
        Spacer(Modifier.height(6.dp))
        changes.forEach { c ->
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(salaryMonthWord(c.month) + "起", style = MaterialTheme.typography.bodyMedium, modifier = Modifier.weight(1f))
                Text(
                    "¥" + formatMoney(c.from.toString()) + " → ¥" + formatMoney(c.to.toString()),
                    style = MaterialTheme.typography.bodyMedium,
                    fontWeight = FontWeight.Medium,
                    color = Color(MoneyOrange),
                )
            }
            if (c.ruleName.isNotBlank()) {
                Text(c.ruleName, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            Spacer(Modifier.height(4.dp))
        }
        Text(
            "相邻两张工资单不一样就算一次变更；中间月份没生成工资单时，以改规则那次为准。",
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

/** 这位司机的工资结算单（草稿 → 确认 → 已付款；草稿可作废放开锁）。 */
@Composable
private fun SettlementCard(
    vm: DriverSalaryViewModel,
    onOpenSettlements: () -> Unit,
    onAskCancel: (SettlementDto) -> Unit,
) {
    val rows = vm.settlements.filter { it.settleType == "salary" }
    SectionCard {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("工资结算单", style = MaterialTheme.typography.titleMedium, modifier = Modifier.weight(1f))
            TextButton(onClick = onOpenSettlements) { Text("全部结算单") }
        }
        if (rows.isEmpty()) {
            Text(
                "还没有工资结算单 —— 上面点「核销这个月的工资」就会生成一张。",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            return@SectionCard
        }
        rows.forEach { s ->
            Spacer(Modifier.height(6.dp))
            Row(verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text("#" + s.id + " · " + s.month + " · " + settlementWord(s.status), style = MaterialTheme.typography.bodyMedium)
                    Text(
                        s.paidAt?.let { "已付 " + it.take(10) } ?: "工资单 " + settledBillCountOf(vm.bills, s.id) + " 笔",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                Text("¥" + formatMoney(s.amount), style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Bold, color = Color(MoneyOrange))
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                if (s.status == "draft") {
                    OutlinedButton(onClick = { onAskCancel(s) }, enabled = !vm.working, modifier = Modifier.weight(1f)) { Text("作废") }
                } else if (s.status == "confirmed") {
                    Button(
                        onClick = { vm.pay(s) },
                        enabled = !vm.working,
                        modifier = Modifier.weight(1f),
                        colors = ButtonDefaults.buttonColors(containerColor = Color(MgrGreen)),
                    ) { Text("标记已付款") }
                }
            }
        }
    }
}
