package com.tapmoay.sorders.ui.dispatcher

import androidx.compose.runtime.*
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.data.remote.dto.OrderDto
import com.tapmoay.sorders.data.remote.dto.OrderUpdateRequest
import com.tapmoay.sorders.data.repo.toApiException
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch

val DISPATCH_TABS = listOf(
    null to "全部",
    "PENDING_DISPATCH" to "派单中",
    "ACCEPTED" to "已接单",
    "DELIVERED" to "已送达",
    "CANCELLED" to "已撤销",
)

class DispatcherOrdersViewModel(private val container: AppContainer) : ViewModel() {

    var orders by mutableStateOf<List<OrderDto>>(emptyList())
    var loading by mutableStateOf(false)
    var error by mutableStateOf<String?>(null)
    var acting by mutableStateOf(false)
    var actionResult by mutableStateOf<String?>(null)

    var tab by mutableStateOf(0)
    var search by mutableStateOf("")
    var dateFrom by mutableStateOf<String?>(null)
    var dateTo by mutableStateOf<String?>(null)

    // 编辑弹窗
    var showEditDialog by mutableStateOf(false)
    var editingOrder by mutableStateOf<OrderDto?>(null)
    var editAddress by mutableStateOf("")
    var editDongjia by mutableStateOf("")
    var editBoss by mutableStateOf("")
    var editRemark by mutableStateOf("")
    var editInternal by mutableStateOf("")

    // 撤回派单
    var showRecallDialog by mutableStateOf(false)
    var recallOrderId by mutableStateOf<Long?>(null)
    var recallReason by mutableStateOf("")

    // 异常标记
    var showExceptionDialog by mutableStateOf(false)
    var exceptionOrderId by mutableStateOf<Long?>(null)
    var exceptionReason by mutableStateOf("")
    var exceptionResolution by mutableStateOf("")
    var expectedBefore by mutableStateOf("")

    private var loadJob: Job? = null

    init {
        load()
        viewModelScope.launch {
            container.realtimeHub.refreshOrders.collect { load() }
        }
    }

    fun applyRange(from: String?, to: String?) {
        dateFrom = from
        dateTo = to
        load()
    }


    /**
     * 这次列表**可能被服务端截断**（2026-09-19 审计）。
     *
     * `GET /orders` 现在对所有角色都有缺省上限 300（以前除"派单员+待派单"外是全量下发，
     * 3 年数据后就是几万单十几 MB）。判据只用"返回条数 == 上限"——少于上限就一定没有更多，
     * 等于上限则**可能**还有，所以文案说"可能"，不撒谎也不吓人。
     */
    val maybeTruncated: Boolean get() = orders.size >= ORDER_LIST_LIMIT

    fun load() {
        loadJob?.cancel()
        loadJob = viewModelScope.launch {
            loading = orders.isEmpty()
            error = null
            try {
                orders = container.repo.orders(
                    status = DISPATCH_TABS[tab].first,
                    q = search.trim().ifBlank { null },
                    dateFrom = if (tab == 3 || tab == 4) dateFrom else null,
                    dateTo = if (tab == 3 || tab == 4) dateTo else null,
                )
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                loading = false
            }
        }
    }

    fun selectTab(i: Int) {
        if (tab != i) {
            tab = i
            load()
        }
    }

    fun searchNow() = load()

    // ---- 编辑 ----
    fun openEdit(o: OrderDto) {
        editingOrder = o
        editAddress = o.addressDetail
        editDongjia = o.contactDongjiaPhone
        editBoss = o.contactBossPhone
        editRemark = o.remark
        editInternal = o.internalNotes
        showEditDialog = true
    }

    fun saveEdit() {
        val o = editingOrder ?: return
        acting = true
        viewModelScope.launch {
            try {
                val updated = container.repo.updateOrder(
                    o.id,
                    OrderUpdateRequest(
                        addressDetail = editAddress.trim(),
                        contactDongjiaPhone = editDongjia.trim(),
                        contactBossPhone = editBoss.trim(),
                        remark = editRemark.trim(),
                        internalNotes = editInternal.trim(),
                    ),
                )
                actionResult = "订单已更新"
                showEditDialog = false
                load()
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                acting = false
            }
        }
    }

    // ---- 撤回派单 ----
    fun openRecall(o: OrderDto) {
        recallOrderId = o.id
        recallReason = ""
        showRecallDialog = true
    }

    fun confirmRecall() {
        val oid = recallOrderId ?: return
        if (recallReason.isBlank()) {
            error = "请填写撤回原因"
            return
        }
        acting = true
        viewModelScope.launch {
            try {
                container.repo.recallOrder(oid, recallReason.trim())
                actionResult = "已撤回派单，订单回到派单中"
                showRecallDialog = false
                load()
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                acting = false
            }
        }
    }

    // ---- 异常 ----
    fun openException(o: OrderDto) {
        exceptionOrderId = o.id
        exceptionReason = o.exceptionReason
        exceptionResolution = o.exceptionResolution
        expectedBefore = o.expectedDeliverBefore?.take(16) ?: ""
        showExceptionDialog = true
    }

    fun confirmException() {
        val oid = exceptionOrderId ?: return
        acting = true
        viewModelScope.launch {
            try {
                val body = com.tapmoay.sorders.data.remote.dto.OrderExceptionBody(
                    isException = true,
                    exceptionReason = exceptionReason.trim(),
                    exceptionResolution = exceptionResolution.trim(),
                    expectedDeliverBefore = expectedBefore.trim().ifBlank { null },
                )
                container.repo.markException(oid, body)
                actionResult = "异常已登记"
                showExceptionDialog = false
                load()
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                acting = false
            }
        }
    }

    // 复用：编辑/撤回/异常用
    fun dismissDialogs() {
        showEditDialog = false
        showRecallDialog = false
        showExceptionDialog = false
    }
}

/** 服务端 `GET /orders` 的缺省条数上限（与后端 `DEFAULT_LIST_LIMIT` 对齐）。 */
private const val ORDER_LIST_LIMIT = 300
