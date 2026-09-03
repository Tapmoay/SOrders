package com.tapmoay.sorders.ui.shipper

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.data.remote.dto.OrderDto
import com.tapmoay.sorders.data.repo.toApiException
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch

data class OrderTab(val key: String?, val label: String)

val SHIPPER_TABS = listOf(
    OrderTab(null, "全部"),
    OrderTab("PENDING_DISPATCH", "派单中"),
    OrderTab("ACCEPTED", "已接单"),
    OrderTab("DELIVERED", "已送达"),
    OrderTab("CANCELLED", "已撤销"),
)

class ShipperOrdersViewModel(private val container: AppContainer) : ViewModel() {

    var selectedTab by mutableStateOf(0)
    var orders by mutableStateOf<List<OrderDto>>(emptyList())
    var loading by mutableStateOf(false)
    var error by mutableStateOf<String?>(null)
    var refreshing by mutableStateOf(false)
    var acting by mutableStateOf(false)
    var actionResult by mutableStateOf<String?>(null)
    var cancelTarget by mutableStateOf<OrderDto?>(null)
    var dateFrom by mutableStateOf<String?>(null)
    var dateTo by mutableStateOf<String?>(null)

    private var loadJob: Job? = null

    init {
        load()
        // Socket 实时事件驱动刷新（派单/送达/撤销等）
        viewModelScope.launch {
            container.realtimeHub.refreshOrders.collect { load() }
        }
    }

    fun selectTab(index: Int) {
        if (selectedTab != index) {
            selectedTab = index
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
                val list = container.repo.orders(status = SHIPPER_TABS[selectedTab].key, dateFrom = if (selectedTab == 3 || selectedTab == 4) dateFrom else null, dateTo = if (selectedTab == 3 || selectedTab == 4) dateTo else null)
                orders = list
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                loading = false
                refreshing = false
            }
        }
    }

    /** 卡片直撤：确认后调取消接口 */
    fun confirmCancel() {
        val target = cancelTarget ?: return
        acting = true
        error = null
        viewModelScope.launch {
            try {
                container.repo.cancelOrder(target.id)
                actionResult = "订单已撤销"
                cancelTarget = null
                load()
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                acting = false
            }
        }
    }

    fun refresh() {
        refreshing = true
        load()
    }
}
