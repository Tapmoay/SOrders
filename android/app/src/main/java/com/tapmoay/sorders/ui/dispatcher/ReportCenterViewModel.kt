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
    // 客户账分组（营业纵览）
    var shipperAccounts by mutableStateOf<List<LedgerAccountOut>>(emptyList())
    var memberAccounts by mutableStateOf<List<LedgerAccountOut>>(emptyList())
    // 营业纵览挂账TOP（后端 turnover 已含）；客户经营页独立汇总
    var customerArrears by mutableStateOf<List<ReportArrearsUnitDto>>(emptyList())
    // 资金收支
    var cashFlows by mutableStateOf<List<CashFlowDto>>(emptyList())
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

    /** 完整时段标题（参考截图起止时间样式） */
    val periodText: String get() {
        val d = LocalDate.parse(anchor)
        val (start, end) = when (mode) {
            "week" -> d.minusDays((d.dayOfWeek.value - 1).toLong()) to d.plusDays((7 - d.dayOfWeek.value).toLong())
            "month" -> d.withDayOfMonth(1) to d.withDayOfMonth(d.lengthOfMonth())
            else -> d to d
        }
        val fmt = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss")
        return start.atStartOfDay().format(fmt) + "~" + end.atTime(LocalTime.MAX).format(fmt)
    }

    /** 往来账日期窗口（账本账户/挂账按 entry_date/送达日） */
    val dateRange: Pair<String, String> get() {
        val d = LocalDate.parse(anchor)
        return when (mode) {
            "week" -> { val s = d.minusDays((d.dayOfWeek.value - 1).toLong()); s.toString() to d.toString() }
            "month" -> d.withDayOfMonth(1).toString() to d.toString()
            else -> d.toString() to d.toString()
        }
    }

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
                    }
                    1 -> products = container.repo.productReport(mode, anchor)
                    2 -> {
                        val d = LocalDate.parse(anchor)
                        val (from, to) = when (mode) {
                            "week" -> d.minusDays((d.dayOfWeek.value - 1).toLong()) to d
                            "month" -> d.withDayOfMonth(1) to d
                            else -> d to d
                        }
                        drivers = container.repo.driverPerformance(from.toString(), to.toString())
                    }
                    3 -> {
                        // 客户经营：货主账/批发商账 + 挂账未收
                        val (f, t) = dateRange
                        shipperAccounts = container.repo.ledgerAccounts(f, t, "shipper")
                        memberAccounts = container.repo.ledgerAccounts(f, t, "member")
                        customerArrears = container.repo.arrearsSummary(f, t)
                    }
                    4 -> {
                        // 资金收支
                        val (f, t) = dateRange
                        cashFlows = container.repo.cashFlows(dateFrom = f, dateTo = t)
                        expenses = container.repo.expenses(dateFrom = f, dateTo = t)
                    }
                    else -> {
                        // 异常与审计
                        val today = LocalDate.now()
                        exceptions = container.repo.exceptionOrders(today.minusDays(30).toString(), today.toString())
                        operationLogs = container.repo.operationLogs(60)
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