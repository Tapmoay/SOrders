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
    var actionResult by mutableStateOf<String?>(null)

    var resolveTarget by mutableStateOf<ExceptionOrderDto?>(null)
    var resolveNote by mutableStateOf("")
    var resolving by mutableStateOf(false)

    val pendingExceptionCount: Int get() = exceptions.count { it.exceptionResolvedAt == null }

    /** 完整时段标题（参考截图起止时间样式） */
    val periodText: String by lazy {
        val d = LocalDate.parse(anchor)
        val (start, end) = when (mode) {
            "week" -> d.minusDays((d.dayOfWeek.value - 1).toLong()) to d.plusDays((7 - d.dayOfWeek.value).toLong())
            "month" -> d.withDayOfMonth(1) to d.withDayOfMonth(d.lengthOfMonth())
            else -> d to d
        }
        val fmt = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss")
        start.atStartOfDay().format(fmt) + "~" + end.atTime(LocalTime.MAX).format(fmt)
    }

    init {
        load()
    }

    fun load() {
        loading = true
        error = null
        viewModelScope.launch {
            try {
                if (tab == 0) turnover = container.repo.turnoverReport(mode, anchor)
                else if (tab == 1) products = container.repo.productReport(mode, anchor)
                else if (tab == 2) {
                    val today = LocalDate.now()
                    val from = when (mode) {
                        "week" -> today.minusDays((today.dayOfWeek.value - 1).toLong()).toString()
                        "month" -> today.withDayOfMonth(1).toString()
                        else -> today.toString()
                    }
                    drivers = container.repo.driverPerformance(from, today.toString())
                } else {
                    val today = LocalDate.now()
                    exceptions = container.repo.exceptionOrders(today.minusDays(30).toString(), today.toString())
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
