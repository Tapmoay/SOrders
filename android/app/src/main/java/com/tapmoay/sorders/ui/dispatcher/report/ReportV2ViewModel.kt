package com.tapmoay.sorders.ui.dispatcher.report

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.data.remote.dto.CashFlowBreakdownDto
import com.tapmoay.sorders.data.remote.dto.CashFlowBreakdownRowDto
import com.tapmoay.sorders.data.remote.dto.CashFlowSummaryDto
import com.tapmoay.sorders.data.remote.dto.CostCoverageReportDto
import com.tapmoay.sorders.data.remote.dto.CustomerBalancesDto
import com.tapmoay.sorders.data.remote.dto.DriverPerformanceDto
import com.tapmoay.sorders.data.remote.dto.ExceptionOrderDto
import com.tapmoay.sorders.data.remote.dto.ExpenseDto
import com.tapmoay.sorders.data.remote.dto.InventorySummaryItemDto
import com.tapmoay.sorders.data.remote.dto.ProductReportDto
import com.tapmoay.sorders.data.remote.dto.ProfitReportDto
import com.tapmoay.sorders.data.remote.dto.SupplierPayableDto
import com.tapmoay.sorders.data.remote.dto.TaxSummaryReportDto
import com.tapmoay.sorders.data.remote.dto.TurnoverReportDto
import com.tapmoay.sorders.data.remote.dto.VehicleCostReportDto
import com.tapmoay.sorders.ui.common.DatePresets
import com.tapmoay.sorders.ui.dispatcher.ReportFinance
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Deferred
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.launch
import java.time.LocalDate
import java.time.temporal.ChronoUnit

/**
 * 报表中心 v2 的取数（CHG-0034）。
 *
 * ## 这一版与老页签的三个区别（都要留住）
 * 1. **一个窗口管全部**：首页五张表、下钻的每一层、走势，全部用同一段 `dateRange`
 *    —— 老页签是"每个页签自己一颗药丸"，用户从营业纵览点进经营利润会**换一段时间**，
 *    两次读到的钱对不上。这里药丸只有一个，窗口是**页面级**的。
 * 2. **先定窗口再取数**（`windowSettled`）：定下来之前整页 loading，一次都不许画错窗口
 *    —— 规矩与老页签同源（`DatePresets.pickWindow` + 各页注释里那条"闪两下已经不行了"）。
 * 3. **按时取数、按节点补数**：首页只要 7 个接口；点进某一张表的某一行，才去补那一块
 *    （成本覆盖、税账、费用明细、库存、应付……），不去的不打。
 *
 * ## ⛔ 三条不许破的规矩
 * - **页面不做钱的加减**：屏上每个金额都是接口字段本身。唯二的两个合计
 *   （[driverOwed] 司机待结、[supplierUnpaid] 应付供应商）接口只按人/按单给、没有给合计，
 *   所以在这里相加，并且**在页面上写明白"这一行是页面相加的"**。
 * - **比率是页面算的**：[grossMarginRate] 这类接口没有，是按接口给的两个数相除算的，
 *   分母为 0 时显示"—"（不是 0%）。页面上同样写明。
 * - **时点账与区间账不许混**：「别人欠我」是**时点**（后端 `as_of = min(窗口末, 今天)`），
 *   与「这一段营业额」不是同一段时间，页面上各写各的时间。
 */
class ReportV2ViewModel(private val container: AppContainer) : ViewModel() {

    // ------------------------------------------------------------ 时间窗口
    var preset by mutableStateOf(DatePresets.TODAY)
        private set
    var customFrom by mutableStateOf<String?>(null)
        private set
    var customTo by mutableStateOf<String?>(null)
        private set

    /** 窗口定下来没有（false = 整页 loading，一次都不画错窗口）。 */
    var windowSettled by mutableStateOf(false)
        private set

    var loading by mutableStateOf(false)
        private set
    var error by mutableStateOf<String?>(null)
        private set

    /** 自动挪过档位时给用户的那句话（挪到哪一档）；没挪就是 null。 */
    var autoNote by mutableStateOf<String?>(null)
        private set

    /** 导航栈：首页永远是第 0 个（栈本身也是面包屑）。 */
    var stack by mutableStateOf(listOf(ReportNodes.home))
        private set

    val current: ReportNode get() = stack.last()

    val periodWord: String
        get() = if (preset == DatePresets.CUSTOM) DatePresets.customLabel(customFrom, customTo) else preset

    /** 这一次要看的窗口 —— 五张表与所有下钻共用这一处（与老页签同一个纯函数）。 */
    val dateRange: Pair<String, String>
        get() = ReportFinance.windowOf(preset, customFrom, customTo, LocalDate.now())

    /** 「别人欠我」那个时点（后端给；拿不到就用今天）。 */
    val asOfText: String get() = customers?.asOf?.take(10) ?: LocalDate.now().toString()

    // ------------------------------------------------------------ 数据
    var turnover by mutableStateOf<TurnoverReportDto?>(null)
        private set
    var profit by mutableStateOf<ProfitReportDto?>(null)
        private set
    var customers by mutableStateOf<CustomerBalancesDto?>(null)
        private set
    var drivers by mutableStateOf<DriverPerformanceDto?>(null)
        private set
    var vehicleCost by mutableStateOf<VehicleCostReportDto?>(null)
        private set
    var cashSummary by mutableStateOf<CashFlowSummaryDto?>(null)
        private set
    /**
     * 收支分项：接口按「进来的几路 / 出去的几路」分两组给（[cashInRows] / [cashOutRows]），
     * ⛔ 页面不自己按金额正负号去分方向（分错了没人报错，只会静静少一行）。
     */
    var cashBreakdown by mutableStateOf<CashFlowBreakdownDto?>(null)
        private set
    var costCoverage by mutableStateOf<CostCoverageReportDto?>(null)
        private set
    var products by mutableStateOf<ProductReportDto?>(null)
        private set
    var taxSummary by mutableStateOf<TaxSummaryReportDto?>(null)
        private set
    var expenses by mutableStateOf<List<ExpenseDto>>(emptyList())
        private set
    var inventory by mutableStateOf<List<InventorySummaryItemDto>>(emptyList())
        private set
    var payables by mutableStateOf<List<SupplierPayableDto>>(emptyList())
        private set
    var exceptions by mutableStateOf<List<ExceptionOrderDto>>(emptyList())
        private set

    /** 已经取到的那些块（选节点时只补没取过的）。 */
    private var loaded: Set<String> = emptySet()

    private var lastError: String? = null

    // ------------------------------------------------------------ 派生（只读接口字段，不做钱的加减）
    val revenueAmount: Double get() = num(turnover?.totalAmount)
    val revenueOrders: Int get() = turnover?.totalOrders ?: 0
    val grossProfit: Double get() = num(profit?.grossProfit)
    val operatingProfit: Double get() = num(profit?.operatingProfit)
    val receivableBalance: Double get() = num(customers?.totals?.balance)
    val netCash: Double get() = num(cashSummary?.net)

    /** 进来的那几路（金额降序）。 */
    val cashInRows: List<CashFlowBreakdownRowDto>
        get() = (cashBreakdown?.income ?: emptyList()).sortedByDescending { num(it.amount) }

    /** 出去的那几路（金额降序）。 */
    val cashOutRows: List<CashFlowBreakdownRowDto>
        get() = (cashBreakdown?.expense ?: emptyList()).sortedByDescending { num(it.amount) }

    /** 司机待结 = 每个司机那一行的`待结运费`相加（接口按人给，**没有给合计**）—— 页面上要写明这一句。 */
    val driverOwed: Double get() = drivers?.drivers?.sumOf { num(it.freightOwed) } ?: 0.0
    val driverOwedCount: Int get() = drivers?.drivers?.count { num(it.freightOwed) != 0.0 } ?: 0

    /** 应付供应商 = 每张应付单的`未付`相加（接口按单给，**没有给合计**）。 */
    val supplierUnpaid: Double get() = payables.sumOf { num(it.unpaid) }

    val stockKinds: Int get() = inventory.count { it.stock != 0 }
    val overLimitCount: Int get() = customers?.totals?.overLimitCount ?: 0

    /** 这一段有几天（走势要不要画、画得出来画不出来）。 */
    val spanDays: Long
        get() {
            val (f, t) = dateRange
            return try {
                ChronoUnit.DAYS.between(LocalDate.parse(f), LocalDate.parse(t)) + 1
            } catch (e: Exception) {
                0L
            }
        }

    init {
        viewModelScope.launch {
            val today = LocalDate.now()
            val picked = DatePresets.pickWindow(DatePresets.ORDER_PRESET_LADDER) { label ->
                val span = DatePresets.rangeOf(label, today) ?: return@pickWindow false
                windowHasData(span.first, span.second)
            }
            if (picked != DatePresets.ALL && picked != preset) {
                preset = picked
                // ⚠️ 这里存的是**屏上要显示的那一整句**，不是一个档位名：外壳（ReportV2Screen）
                //    会把它原样画在列表最上面；只存一个「上周」的话，用户看到的就是一行没头没尾的
                //    档位名（2026-10-05 走查抓到的）。
                autoNote = "「" + picked + "」是自动挑的：一打开那个档位这一段没有已送达的单，" +
                    "页面自动挪到离得最近、确实有数的那一档。"
            }
            windowSettled = true
            loading = true
            loadAll(CORE_KEYS)
            loading = false
        }
    }

    /**
     * 这一段有没有数（探测）。
     * ⚠️ 判据必须与页面自己的取数**同源**：打的就是首页要打的那个接口（`/reports/turnover`）、
     *    用的就是同一段区间。网络出错一律当"这一档没数"继续往后退（不能因为一次失败卡住整页），
     *    但协程取消要**原样抛出**。
     */
    private suspend fun windowHasData(from: String, to: String): Boolean = try {
        val r = container.repo.turnoverReport(ReportFinance.LEGACY_MODE, from, from, to)
        ReportFinance.hasData(r.totalOrders, r.totalAmount)
    } catch (e: CancellationException) {
        throw e
    } catch (e: Exception) {
        false
    }

    // ------------------------------------------------------------ 用户动作
    fun applyPreset(label: String) {
        preset = label
        autoNote = null
        reloadForCurrent()
    }

    fun applyCustomRange(from: String?, to: String?) {
        if (from != null && to != null) {
            preset = DatePresets.CUSTOM
            customFrom = from
            customTo = to
            autoNote = null
            reloadForCurrent()
        }
    }

    /** 用户重试（取数失败时那颗按钮）。 */
    fun retry() = reloadForCurrent()

    fun open(node: ReportNode) {
        if (stack.last().id == node.id) return
        stack = stack + node
        ensure(node)
    }

    fun openCustomer(index: Int) {
        val row = customers?.rows?.getOrNull(index) ?: return
        open(ReportNodes.customer(row, index))
    }

    /** 返回上一层；已经在首页就返回 false（调用方退到上一张屏）。 */
    fun backOne(): Boolean {
        if (stack.size <= 1) return false
        stack = stack.dropLast(1)
        return true
    }

    fun backToHome() {
        stack = listOf(ReportNodes.home)
        ensure(ReportNodes.home)
    }

    // ------------------------------------------------------------ 取数
    /**
     * 换窗口 = **把旧数全部作废**再取新数。
     * ⛔ 不许"先留着旧窗口的数、新的来了再换"：那一瞬间屏幕上写的是新窗口、数的是旧窗口
     *    （用户对账时看到的就是"同一个药丸两个数"）。
     */
    private fun reloadForCurrent() {
        invalidate()
        loading = true
        error = null
        viewModelScope.launch {
            loadAll(CORE_KEYS + keysFor(current.id))
            loading = false
        }
    }

    private fun invalidate() {
        loaded = emptySet()
        turnover = null
        profit = null
        customers = null
        drivers = null
        vehicleCost = null
        cashSummary = null
        cashBreakdown = null
        costCoverage = null
        products = null
        taxSummary = null
        expenses = emptyList()
        inventory = emptyList()
        payables = emptyList()
        exceptions = emptyList()
    }

    private fun ensure(node: ReportNode) {
        val need = keysFor(node.id)
        if (need.isEmpty() || (need - loaded).isEmpty()) return
        loading = true
        error = null
        viewModelScope.launch {
            loadAll(need)
            loading = false
        }
    }

    /**
     * 某个节点要哪几块数据。
     * ⛔ 别在这里"顺手多取几块"：用户点一行却打了五个接口，慢的是他自己。
     */
    private fun keysFor(id: String): Set<String> = when {
        id.startsWith("cust:") -> emptySet()
        id == ReportNodes.revenue.id -> setOf("turnover", "costCoverage")
        id == ReportNodes.cost.id -> setOf("costCoverage")
        id == ReportNodes.driverFee.id -> setOf("drivers")
        id == ReportNodes.expense.id -> setOf("expenses")
        id == ReportNodes.depreciation.id -> setOf("vehicleCost")
        id == ReportNodes.tax.id -> setOf("tax")
        id == ReportNodes.balance.id || id == ReportNodes.receivable.id -> setOf("customers")
        id == ReportNodes.stock.id -> setOf("inventory")
        id == ReportNodes.driverPayable.id -> setOf("drivers")
        id == ReportNodes.supplierPayable.id -> setOf("payables")
        id == ReportNodes.cash.id -> setOf("cash", "cashBreakdown")
        id == ReportNodes.ops.id -> setOf("products")
        id == ReportNodes.opsProducts.id -> setOf("products")
        id == ReportNodes.opsDrivers.id -> setOf("drivers")
        id == ReportNodes.opsVehicles.id -> setOf("vehicleCost")
        id == ReportNodes.opsExceptions.id -> setOf("exceptions")
        else -> emptySet()
    }

    private suspend fun loadAll(keys: Set<String>) {
        val need = keys - loaded
        if (need.isEmpty()) return
        val (from, to) = dateRange
        val today = LocalDate.now()
        lastError = null
        var failed = false
        coroutineScope {
            val jobs = mutableListOf<Deferred<*>>()
            if ("turnover" in need) jobs += async {
                val v = fetch { container.repo.turnoverReport(ReportFinance.LEGACY_MODE, from, from, to) }
                if (v == null) failed = true else { turnover = v; loaded = loaded + "turnover" }
            }
            if ("profit" in need) jobs += async {
                val v = fetch { container.repo.profitReport(ReportFinance.LEGACY_MODE, from, from, to) }
                if (v == null) failed = true else { profit = v; loaded = loaded + "profit" }
            }
            if ("customers" in need) jobs += async {
                val v = fetch { container.repo.customerBalancesReport(ReportFinance.LEGACY_MODE, from, from, to, true) }
                if (v == null) failed = true else { customers = v; loaded = loaded + "customers" }
            }
            if ("drivers" in need) jobs += async {
                val v = fetch { container.repo.driverPerformance(from, to) }
                if (v == null) failed = true else { drivers = v; loaded = loaded + "drivers" }
            }
            if ("vehicleCost" in need) jobs += async {
                val v = fetch { container.repo.vehicleCostReport(ReportFinance.LEGACY_MODE, from, from, to) }
                if (v == null) failed = true else { vehicleCost = v; loaded = loaded + "vehicleCost" }
            }
            if ("cash" in need) jobs += async {
                val v = fetch { container.repo.cashFlowSummary(from, to) }
                if (v == null) failed = true else { cashSummary = v; loaded = loaded + "cash" }
            }
            if ("cashBreakdown" in need) jobs += async {
                val v = fetch { container.repo.cashFlowBreakdown(from, to) }
                if (v == null) failed = true else { cashBreakdown = v; loaded = loaded + "cashBreakdown" }
            }
            if ("costCoverage" in need) jobs += async {
                val v = fetch { container.repo.costCoverageReport(ReportFinance.LEGACY_MODE, from, from, to) }
                if (v == null) failed = true else { costCoverage = v; loaded = loaded + "costCoverage" }
            }
            if ("products" in need) jobs += async {
                val v = fetch { container.repo.productReport(ReportFinance.LEGACY_MODE, from, from, to) }
                if (v == null) failed = true else { products = v; loaded = loaded + "products" }
            }
            if ("tax" in need) jobs += async {
                val v = fetch { container.repo.taxSummaryReport(ReportFinance.LEGACY_MODE, from, from, to) }
                if (v == null) failed = true else { taxSummary = v; loaded = loaded + "tax" }
            }
            if ("expenses" in need) jobs += async {
                val v = fetch { container.repo.expenses(null, null, from, to) }
                if (v == null) failed = true else { expenses = v; loaded = loaded + "expenses" }
            }
            if ("inventory" in need) jobs += async {
                val v = fetch { container.repo.inventorySummary() }
                if (v == null) failed = true else { inventory = v; loaded = loaded + "inventory" }
            }
            if ("payables" in need) jobs += async {
                val v = fetch { container.repo.allSupplierPayables(false) }
                if (v == null) failed = true else { payables = v; loaded = loaded + "payables" }
            }
            if ("exceptions" in need) jobs += async {
                // ⚠️ 异常单窗口与别的报表**不一样**（固定近 30 天，老页签也是这么定的）：
                //    所以屏幕上必须写"近 30 天"，不能让人以为它是"这一段"。
                val v = fetch { container.repo.exceptionOrders(today.minusDays(30).toString(), today.toString()) }
                if (v == null) failed = true else { exceptions = v; loaded = loaded + "exceptions" }
            }
            jobs.awaitAll()
        }
        if (failed) error = lastError ?: "有一块没取到（网络或权限），点重试再来一次"
    }

    /** 取一块数据：失败只记错、不抛（别让一个接口把整屏拖垮），取消照旧抛。 */
    private suspend fun <T> fetch(block: suspend () -> T): T? = try {
        block()
    } catch (e: CancellationException) {
        throw e
    } catch (e: Exception) {
        lastError = e.message?.takeIf { it.isNotBlank() }
        null
    }

    companion object {
        /**
         * 首页要的那几块（点进节点再补别的）。
         *
         * ⚠️ `exceptions` 必须在里面：首页「要盯的事」那张卡上的「异常单（近 30 天）」直接读
         *    `exceptions.size`（ReportV2Home.kt 的 AlertsCard）—— 不取这一块，那一行就**永远写 0 单**，
         *    而老页签同一件事写着 51 单（2026-10-05 走查抓到：首页 0 单 vs 老页 51 单）。
         *    这一块**与时间药丸无关**：接口按"最近 30 天"固定取（见下面 `exceptionOrders`，
         *    与老页签同一段），屏上也照老页签写着「近 30 天」。
         */
        private val CORE_KEYS = setOf(
            "turnover", "profit", "customers", "drivers", "vehicleCost", "cash", "costCoverage",
            "exceptions",
        )
    }
}
