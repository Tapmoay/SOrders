package com.tapmoay.sorders.ui.dispatcher

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.data.remote.dto.*
import com.tapmoay.sorders.data.repo.toApiException
import kotlinx.coroutines.launch
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.LocalTime
import java.time.format.DateTimeFormatter

class ReportCenterViewModel(
    private val container: AppContainer,
    initialTab: Int,
) : ViewModel() {

    var tab by mutableStateOf(initialTab.coerceIn(0, 5))
    var mode by mutableStateOf("day")
    var anchor by mutableStateOf(LocalDate.now().toString())
    var loading by mutableStateOf(false)
    var error by mutableStateOf<String?>(null)
    var chartType by mutableStateOf("line")

    var turnover by mutableStateOf<TurnoverReportDto?>(null)
    var products by mutableStateOf<ProductReportDto?>(null)
    var drivers by mutableStateOf<DriverPerformanceDto?>(null)
    var exceptions by mutableStateOf<List<ExceptionOrderDto>>(emptyList())
    var operationLogs by mutableStateOf<List<OperationLogDto>>(emptyList())

    /**
     * 审计日志"这一页不是全部"＝更早的还有。
     *
     * 判据是响应头 `X-Truncated`（2026-09-19 后端补的头，走 `AppRepository.pageMeta()`）——
     * 不说出来的后果不是"少看几条"，而是用户据此判断**"我那次改动没被记录"**。
     */
    var operationLogsTruncated by mutableStateOf(false)

    /** 本次服务器上限（`X-Result-Limit`）；null = 老后端没回报，界面不许自己编一个数。 */
    var operationLogsLimit by mutableStateOf<Int?>(null)
    // 客户账分组（营业纵览）
    var shipperAccounts by mutableStateOf<List<LedgerAccountOut>>(emptyList())
    var memberAccounts by mutableStateOf<List<LedgerAccountOut>>(emptyList())
    // 营业纵览挂账TOP（后端 turnover 已含）；客户经营页独立汇总
    var customerArrears by mutableStateOf<List<ReportArrearsUnitDto>>(emptyList())
    // 资金收支
    var cashFlows by mutableStateOf<List<CashFlowDto>>(emptyList())

    /** 资金流水明细"这一页不是全部"＝这一窗口更早的没取到（判据同样是响应头 `X-Truncated`）。 */
    var cashFlowsTruncated by mutableStateOf(false)
    var cashFlowsLimit by mutableStateOf<Int?>(null)
    /** 资金汇总（流入/流出/净额/笔数）——**服务端算的**，不在这里求和。 */
    var cashFlowSummary by mutableStateOf<CashFlowSummaryDto?>(null)
    var expenses by mutableStateOf<List<ExpenseDto>>(emptyList())
    // 商品明细筛选
    var productSearch by mutableStateOf("")
    var productSort by mutableStateOf("amount") // amount | qty | profit | damage
    var productShowAll by mutableStateOf(false)

    var actionResult by mutableStateOf<String?>(null)
    var exporting by mutableStateOf(false)

    var resolveTarget by mutableStateOf<ExceptionOrderDto?>(null)
    var resolveNote by mutableStateOf("")
    var resolving by mutableStateOf(false)

    val pendingExceptionCount: Int get() = exceptions.count { it.exceptionResolvedAt == null }

    /** 完整时段标题（参考截图起止时间样式）。窗口与 [dateRange] **同一个函数**，不许各写一遍。 */
    val periodText: String get() {
        val (start, end) = ReportFinance.rangeFor(mode, anchor)
        val fmt = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss")
        return LocalDate.parse(start).atStartOfDay().format(fmt) + "~" +
            LocalDate.parse(end).atTime(LocalTime.MAX).format(fmt)
    }

    /**
     * 往来账日期窗口（账本账户 / 挂账 / 资金收支 / 开销 / 司机绩效 / 导出的 date_from~date_to）。
     *
     * ⚠️ **必须与 [periodText] 同一段**（2026-09-19 审计）：原来这里 month 只到**锚点当天**
     * （`9/5` → `2026-09-01 ~ 2026-09-05`），而标题写的是整个月 `2026-09-01 ~ 2026-09-30`。
     * 后果：9/5 打开报表，标题写整月、数字只含 5 天；9/20 打开则少掉后面 10 天的收支 ——
     * 而同一屏的「营业纵览」营业额走的是后端整月窗口，**同一页两个时间段**。
     * 已过去的月份取整月没有副作用（未来那几天本来就没有数据）。
     */
    val dateRange: Pair<String, String> get() = ReportFinance.rangeFor(mode, anchor)

    /** 筛选后的商品明细（按当前排序） */
    val filteredProducts: List<ProductReportItemDto> get() {
        val items = products?.items.orEmpty()
        val base = if (productSearch.isBlank()) items else items.filter { it.productName.contains(productSearch, ignoreCase = true) }
        return when (productSort) {
            "qty" -> base.sortedByDescending { it.qty }
            "profit" -> base.sortedByDescending { (it.amount.toDoubleOrNull() ?: 0.0) - (it.cost.toDoubleOrNull() ?: 0.0) }
            "damage" -> base.sortedByDescending { it.damageQty }
            else -> base // amount 已在后端排序
        }
    }

    init {
        load()
    }

    fun load() {
        loading = true
        error = null
        viewModelScope.launch {
            try {
                when (tab) {
                    0 -> {
                        turnover = container.repo.turnoverReport(mode, anchor)
                        val (f, t) = dateRange
                        shipperAccounts = container.repo.ledgerAccounts(f, t, "shipper")
                        memberAccounts = container.repo.ledgerAccounts(f, t, "member")
                        // 「异常订单数」这一行原来读的是"异常页签加载出来的列表"，而那只在切到
                        // 「异常与审计」时才赋值 → 从工作台直接进营业纵览时**恒显示 0 单**；
                        // 先看过异常页再回来又会显示近 30 天的数（同屏其它数字是当天/周/月的）。
                        // 现在这一页**自己**去取，口径写明是"近 30 天待处理"（2026-09-19 审计）。
                        val today = LocalDate.now()
                        exceptions = container.repo.exceptionOrders(
                            today.minusDays(30).toString(), today.toString(),
                        )
                    }
                    1 -> products = container.repo.productReport(mode, anchor)
                    2 -> {
                        // ⚠️ 取数窗口必须与**标题/导出**同源（2026-09-19 审计 R13-R2）：
                        //    这里原来自己算了一遍（`month -> d.withDayOfMonth(1) to d`，即 1 号到**锚点当天**），
                        //    而标题与导出走 `ReportFinance.rangeFor`（整月）。锚点选 8/15 时，
                        //    页面按 8/1~8/15 取数（16 单）、标题写"8 月"、导出给整月（34 单）——
                        //    同一个页面两个数，用户对不上账。窗口只留一处实现（`rangeFor`）。
                        val (from, to) = ReportFinance.rangeFor(mode, anchor)
                        drivers = container.repo.driverPerformance(from, to)
                    }
                    3 -> {
                        // 客户经营：货主账/批发商账 + 挂账未收
                        val (f, t) = dateRange
                        shipperAccounts = container.repo.ledgerAccounts(f, t, "shipper")
                        memberAccounts = container.repo.ledgerAccounts(f, t, "member")
                        customerArrears = container.repo.arrearsSummary(f, t)
                    }
                    4 -> {
                        // 资金收支：明细用于列表，**金额一律取服务端汇总**（2026-09-19 审计）——
                        // 原来在客户端对"这一页流水"求和，而列表有 limit（默认 200）：
                        // 实测同一窗口 200 条 → 流入 ¥18,842、273 条 → ¥48,905.50（少算 62%），
                        // 而同一页 Excel 导出是 SQL 侧全窗口求和 → 页面一个数、导出一个数。
                        val (f, t) = dateRange
                        // 截断位跟着行一起回来（`X-Truncated`/`X-Result-Limit`）：明细被截断时
                        // 界面要说出来，否则用户会把"看得见的几行"当成整个窗口的明细。
                        val flowPage = container.repo.cashFlowsPage(dateFrom = f, dateTo = t)
                        cashFlows = flowPage.rows
                        cashFlowsTruncated = flowPage.meta.hasMore
                        cashFlowsLimit = flowPage.meta.limit
                        cashFlowSummary = container.repo.cashFlowSummary(dateFrom = f, dateTo = t)
                        expenses = container.repo.expenses(dateFrom = f, dateTo = t)
                    }
                    else -> {
                        // 异常与审计
                        val today = LocalDate.now()
                        exceptions = container.repo.exceptionOrders(today.minusDays(30).toString(), today.toString())
                        val logPage = container.repo.operationLogsPage(60)
                        operationLogs = logPage.rows
                        operationLogsTruncated = logPage.meta.hasMore
                        operationLogsLimit = logPage.meta.limit
                    }
                }
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                loading = false
            }
        }
    }

    /**
     * 导出当前报表为 Excel（保存到系统下载目录），返回保存路径；失败返回 null。
     *
     * ⚠️ 页签→kind 与"要不要日期区间"的映射在 [ReportFinance] 里（纯函数 + 单测）。
     * 这两处**都错过一次**，而且都不会报错：
     * 前者会导出一张"名字对、内容错"的表（客户经营的文件里装着异常审计），
     * 后者会让导出的时间段和页面上显示的不是同一段。
     */
    fun exportCurrent(onDone: (ByteArray?) -> Unit) {
        if (exporting) return
        exporting = true
        viewModelScope.launch {
            val kind = ReportFinance.exportKind(tab)
            // 异常与审计页固定看近 30 天（那个页面没有时间导航），导出必须跟着同一段走
            val range = if (tab == 5) {
                val today = LocalDate.now()
                today.minusDays(30).toString() to today.toString()
            } else {
                dateRange
            }
            val withRange = ReportFinance.usesDateRange(tab)
            try {
                val bytes = container.repo.exportReport(
                    kind = kind,
                    mode = mode,
                    date = anchor,
                    dateFrom = if (withRange) range.first else null,
                    dateTo = if (withRange) range.second else null,
                ).bytes()
                onDone(bytes)
            } catch (e: Exception) {
                actionResult = "导出失败：" + toApiException(e).message
                onDone(null)
            } finally {
                exporting = false
            }
        }
    }

    fun openResolve(target: ExceptionOrderDto) {
        resolveTarget = target
        resolveNote = ""
    }

    fun confirmResolve() {
        val t = resolveTarget ?: return
        resolving = true
        viewModelScope.launch {
            try {
                container.repo.resolveException(t.id, resolveNote.trim().ifBlank { null })
                actionResult = "已标记解决"
                resolveTarget = null
                load()
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                resolving = false
            }
        }
    }
}