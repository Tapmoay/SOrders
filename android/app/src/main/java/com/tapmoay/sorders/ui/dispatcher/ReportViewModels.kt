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

/** 报表通用状态 */
open class ReportViewModel(protected val container: AppContainer) : ViewModel() {
    var mode by mutableStateOf("day")
    var anchor by mutableStateOf(LocalDate.now().toString())
    var loading by mutableStateOf(false)
    var error by mutableStateOf<String?>(null)

    open fun load() {}

    protected fun launch(block: suspend (AppContainer) -> Unit) {
        loading = true
        error = null
        viewModelScope.launch {
            try {
                block(container)
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                loading = false
            }
        }
    }
}

/** 营业额 */
class TurnoverReportViewModel(container: AppContainer) : ReportViewModel(container) {
    var data by mutableStateOf<TurnoverReportDto?>(null)
    var chartType by mutableStateOf("line") // line | bar

    init {
        load()
    }

    override fun load() = launch { data = it.repo.turnoverReport(mode, anchor) }
}

/** 商品明细 */
class ProductReportViewModel(container: AppContainer) : ReportViewModel(container) {
    var data by mutableStateOf<ProductReportDto?>(null)

    init {
        load()
    }

    override fun load() = launch { data = it.repo.productReport(mode, anchor) }
}

/** 司机绩效 */
class DriverReportViewModel(container: AppContainer) : ReportViewModel(container) {
    var data by mutableStateOf<DriverPerformanceDto?>(null)

    init {
        load()
    }

    override fun load() {
        val today = LocalDate.now()
        val from = when (mode) {
            "week" -> today.minusDays(today.dayOfWeek.value - 1L).toString()
            "month" -> today.withDayOfMonth(1).toString()
            else -> today.toString()
        }
        launch { data = it.repo.driverPerformance(from, today.toString()) }
    }
}

/** 异常订单 */
class ExceptionReportViewModel(container: AppContainer) : ReportViewModel(container) {
    var items by mutableStateOf<List<ExceptionOrderDto>>(emptyList())
    var resolving by mutableStateOf(false)
    var resolveTarget by mutableStateOf<ExceptionOrderDto?>(null)
    var resolveNote by mutableStateOf("")
    var actionResult by mutableStateOf<String?>(null)

    init {
        load()
    }

    override fun load() {
        val today = LocalDate.now()
        val from = today.minusDays(30)
        launch { items = it.repo.exceptionOrders(from.toString(), today.toString()) }
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
