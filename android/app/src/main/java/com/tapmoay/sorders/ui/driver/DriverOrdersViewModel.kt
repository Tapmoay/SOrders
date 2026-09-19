package com.tapmoay.sorders.ui.driver

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.core.OrderStatusModel
import com.tapmoay.sorders.data.remote.dto.OrderDto
import com.tapmoay.sorders.data.repo.toApiException
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch

class DriverOrdersViewModel(private val container: AppContainer) : ViewModel() {

    var tab by mutableStateOf(0) // 0=进行中 1=已完成
    var orders by mutableStateOf<List<OrderDto>>(emptyList())
    var loading by mutableStateOf(false)
    var error by mutableStateOf<String?>(null)
    var refreshing by mutableStateOf(false)
    var dateFrom by mutableStateOf<String?>(null)
    var dateTo by mutableStateOf<String?>(null)

    private var loadJob: Job? = null

    init {
        load()
        // Socket 实时事件驱动刷新（新单/撤回/完成等），新单由 RealtimeHub 语音播报
        viewModelScope.launch {
            container.realtimeHub.refreshOrders.collect { load() }
        }
    }

    fun selectTab(index: Int) {
        if (tab != index) {
            tab = index
            load()
        }
    }

    fun applyRange(from: String?, to: String?) {
        dateFrom = from
        dateTo = to
        load()
    }

    fun load() {
        loadJob?.cancel()
        loadJob = viewModelScope.launch {
            loading = orders.isEmpty()
            error = null
            try {
                // 进行中 = 已派单（还没接）+ 已接单。状态取自 `OrderStatusModel.DRIVER_OPEN`
                // （原来这里硬写两个字面量；只查 ACCEPTED 时新派来的单在司机端**根本不出现**）。
                val statuses = if (tab == 0) OrderStatusModel.DRIVER_OPEN else listOf("DELIVERED")
                orders = statuses
                    .flatMap { container.repo.orders(status = it, dateFrom = if (tab == 1) dateFrom else null, dateTo = if (tab == 1) dateTo else null) }
                    .sortedByDescending { it.createdAt }
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                loading = false
                refreshing = false
            }
        }
    }

    fun refresh() {
        refreshing = true
        load()
    }
}
