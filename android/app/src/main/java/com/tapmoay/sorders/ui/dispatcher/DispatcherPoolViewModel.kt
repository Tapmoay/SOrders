package com.tapmoay.sorders.ui.dispatcher

import androidx.compose.runtime.*
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.data.remote.dto.FreightTemplateDto
import com.tapmoay.sorders.data.remote.dto.OrderDto
import com.tapmoay.sorders.data.remote.dto.UserDto
import com.tapmoay.sorders.data.repo.toApiException
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonPrimitive

class DispatcherPoolViewModel(private val container: AppContainer) : ViewModel() {

    var orders by mutableStateOf<List<OrderDto>>(emptyList())
    var drivers by mutableStateOf<List<UserDto>>(emptyList())
    var loading by mutableStateOf(false)
    var error by mutableStateOf<String?>(null)
    var acting by mutableStateOf(false)

    // 批量选择
    var selectionMode by mutableStateOf(false)
    var selectedIds by mutableStateOf<Set<Long>>(emptySet())

    // 派单弹窗
    var showAssignDialog by mutableStateOf(false)
    var assignOrderId by mutableStateOf<Long?>(null)
    var selectedDriverId by mutableStateOf<Long?>(null)
    var assignNote by mutableStateOf("")
    var assignFreight by mutableStateOf("")
    var assignCollectCash by mutableStateOf(false)  // 派单勾选：司机送达时收取现金（否则自动挂账）
    var templates by mutableStateOf<List<FreightTemplateDto>>(emptyList())

    // 撤销弹窗（未派送订单）
    var showCancelDialog by mutableStateOf(false)
    var cancelOrderId by mutableStateOf<Long?>(null)

    var actionResult by mutableStateOf<String?>(null)

    private var loadJob: Job? = null

    init {
        load()
        // 实时事件：待派单池变化自动刷新
        viewModelScope.launch {
            container.realtimeHub.refreshOrders.collect { load() }
        }
    }

    fun load() {
        loadJob?.cancel()
        loadJob = viewModelScope.launch {
            loading = orders.isEmpty()
            error = null
            try {
                orders = container.repo.orders(status = "PENDING_DISPATCH")
                drivers = container.repo.drivers().filter { it.isActive }
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                loading = false
            }
        }
    }

    fun pendingCount(): Int = orders.count { it.status == "PENDING_DISPATCH" }

    // ---- 选择 ----
    fun toggleSelect(id: Long) {
        selectedIds = if (id in selectedIds) selectedIds - id else selectedIds + id
        if (selectedIds.isEmpty()) selectionMode = false
    }

    /** 全选 / 取消全选（批量派单快捷操作） */
    fun selectAll() {
        selectedIds = if (selectedIds.size == orders.size && orders.isNotEmpty()) emptySet()
        else orders.map { it.id }.toSet()
    }

    fun clearSelection() {
        selectionMode = false
        selectedIds = emptySet()
    }

    // ---- 派单 ----
    fun openAssign(orderId: Long? = null) {
        assignOrderId = orderId
        selectedDriverId = drivers.firstOrNull()?.id
        assignNote = ""
        assignFreight = ""
        assignCollectCash = false
        loadTemplates()
        showAssignDialog = true
    }

    fun loadTemplates() {
        viewModelScope.launch {
            try {
                templates = container.repo.freightTemplates()
            } catch (_: Exception) {
            }
        }
    }

    fun applyTemplate(t: FreightTemplateDto) {
        assignFreight = t.fee
    }

    val selectedDriver: UserDto?
        get() = drivers.find { it.id == selectedDriverId }

    /** 按单计费司机（挂车默认按单；显式 salary 覆盖） */
    fun isPieceDriver(u: UserDto?): Boolean {
        if (u == null) return false
        val mode = u.billingMode ?: (if (u.vehicleType == "trailer") "PIECE" else "SALARY")
        return mode == "PIECE"
    }

    fun confirmAssign() {
        val driverId = selectedDriverId ?: run { error = "请选择司机"; return }
        acting = true
        error = null
        viewModelScope.launch {
            try {
                val note = assignNote.trim().ifBlank { null }
                val collect = assignCollectCash
                val result = if (selectionMode && selectedIds.isNotEmpty()) {
                    container.repo.batchAssign(selectedIds.toList(), driverId, note, collect)
                        .results.count { it.success }
                } else {
                    val oid = assignOrderId ?: 0L
                    if (oid == 0L) 0 else {
                        val fee = if (isPieceDriver(drivers.find { it.id == driverId })) assignFreight.trim().ifBlank { null } else null
                        container.repo.assignOrder(oid, driverId, note, fee, collect)
                        1
                    }
                }
                actionResult = "派单成功：" + result + " 单"
                showAssignDialog = false
                clearSelection()
                load()
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                acting = false
            }
        }
    }

    // ---- 撤销（未派送）----
    fun openCancel(orderId: Long) {
        cancelOrderId = orderId
        showCancelDialog = true
    }

    fun confirmCancel() {
        val oid = cancelOrderId ?: return
        acting = true
        viewModelScope.launch {
            try {
                container.repo.cancelOrder(oid)
                actionResult = "订单已撤销"
                showCancelDialog = false
                load()
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                acting = false
            }
        }
    }
}
