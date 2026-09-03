package com.tapmoay.sorders.ui.shipper

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.data.remote.dto.LedgerEntryDto
import com.tapmoay.sorders.data.repo.toApiException
import com.tapmoay.sorders.util.moneyToDouble
import kotlinx.coroutines.launch
import java.time.LocalDate

class ShipperLedgerViewModel(private val container: AppContainer) : ViewModel() {

    var entries by mutableStateOf<List<LedgerEntryDto>>(emptyList())
    var loading by mutableStateOf(false)
    var error by mutableStateOf<String?>(null)
    var rangeFrom by mutableStateOf<String?>(null)
    var rangeTo by mutableStateOf<String?>(null)

    // 时间导航（按日/按周/按月）+ 图表
    var chartMode by mutableStateOf("day")
    var chartAnchor by mutableStateOf(LocalDate.now().toString())
    var chartType by mutableStateOf("line")

    init {
        load()
        // 订单送达自动记账后实时刷新账本
        viewModelScope.launch {
            container.realtimeHub.refreshLedger.collect { load() }
        }
    }

    fun total(): Double = entries.sumOf { moneyToDouble(it.total) }

    val periodText: String get() {
        val d = LocalDate.parse(chartAnchor)
        val (start, end) = when (chartMode) {
            "week" -> d.minusDays((d.dayOfWeek.value - 1).toLong()) to d.plusDays((7 - d.dayOfWeek.value).toLong())
            "month" -> d.withDayOfMonth(1) to d.withDayOfMonth(d.lengthOfMonth())
            else -> d to d
        }
        return start.toString() + " 00:00:00~" + end.toString() + " 23:59:59"
    }

    fun applyMode(mode: String) {
        chartMode = mode
        val d = LocalDate.parse(chartAnchor)
        val (from, to) = when (mode) {
            "week" -> (d.minusDays((d.dayOfWeek.value - 1).toLong()).toString() to d.plusDays((7 - d.dayOfWeek.value).toLong()).toString())
            "month" -> (d.withDayOfMonth(1).toString() to d.withDayOfMonth(d.lengthOfMonth()).toString())
            else -> (d.toString() to d.toString())
        }
        applyRange(from, to)
    }

    fun setAnchor(anchor: String) {
        chartAnchor = anchor
        applyMode(chartMode)
    }

    /** 按日汇总（图表 x 轴） */
    val chartSeries: List<Pair<String, Double>> get() {
        val map = LinkedHashMap<String, Double>()
        entries.forEach { e ->
            val key = (e.entryDate ?: "").take(10)
            if (key.isNotBlank()) map[key] = (map[key] ?: 0.0) + moneyToDouble(e.total)
        }
        return map.entries.map { it.key to it.value }
    }

    fun applyRange(from: String?, to: String?) {
        rangeFrom = from
        rangeTo = to
        load()
    }

    fun load() {
        loading = entries.isEmpty()
        error = null
        viewModelScope.launch {
            try {
                entries = container.repo.ledgerEntries(from = rangeFrom, to = rangeTo)
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                loading = false
            }
        }
    }
}