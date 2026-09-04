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

    var tab by mutableStateOf(initialTab.coerceIn(0, 3))
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
    var actionResult by mutableStateOf<String?>(null)

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

    /** 往来账日期窗口（账本账户按 entry_date） */
    val dateRange: Pair<String, String> get() {
        val d = LocalDate.parse(anchor)
        when (mode) {
            "week" -> { val s = d.minusDays((d.dayOfWeek.value - 1).toLong()); s.toString() to d.toString() }
            "month" -> d.withDayOfMonth(1).toString() to d.toString()
            else -> d.toString() to d.toString()
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
                        // 司机绩效窗口跟随时间导航（锚点 + 模式）
                        val d = LocalDate.parse(anchor)
                        val (from, to) = when (mode) {
                            "week" -> d.minusDays((d.dayOfWeek.value - 1).toLong()) to d
                            "month" -> d.withDayOfMonth(1) to d
                            else -> d to d
                        }
                        drivers = container.repo.driverPerformance(from.toString(), to.toString())
                    }
                    else -> {
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