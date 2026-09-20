package com.tapmoay.sorders.ui.dispatcher

import androidx.compose.runtime.*
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.core.InputRules
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
    // 已退货（2026-09-20）：与「已撤销」**不是一回事**（撤销＝单没发生过，
    // 退货＝送了、入了账、事后货退回来了）。两者都有各自的页签，别合并成一档。
    "RETURNED" to "已退货",
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
    // 与两个电话一一对应的名称（2026-09-20 加）：dongjia=收货人、boss=下单人
    var editDongjiaName by mutableStateOf("")
    var editBossName by mutableStateOf("")
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
        editDongjiaName = o.contactDongjiaName
        editBossName = o.contactBossName
        editRemark = o.remark
        editInternal = o.internalNotes
        showEditDialog = true
    }

    fun saveEdit() {
        val o = editingOrder ?: return
        // 电话格式先在这一侧挡一道（与后端同一条规则）。老单里可能是"嘿嘿"这种旧数据，
        // 它不会被静默清空 —— 而是明确告诉用户"这一单的电话要改一下才能存"。
        InputRules.phoneError(editDongjia.trim())?.let {
            error = it
            return
        }
        InputRules.phoneError(editBoss.trim())?.let {
            error = it
            return
        }
        acting = true
        viewModelScope.launch {
            try {
                val updated = container.repo.updateOrder(
                    o.id,
                    OrderUpdateRequest(
                        addressDetail = editAddress.trim(),
                        contactDongjiaPhone = editDongjia.trim(),
                        contactBossPhone = editBoss.trim(),
                        contactDongjiaName = editDongjiaName.trim(),
                        contactBossName = editBossName.trim(),
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

    // 退出/作废弹窗
    // 退货（2026-09-20 用户要求）：「订单管理……我们可以进行一个退货」，
    // 「可以整单退货，也可以只退其中的某几个商品或者是一个商品，他自己勾选」。
    var showReturnDialog by mutableStateOf(false)
    var returnTarget by mutableStateOf<OrderDto?>(null)
    /** 每行退几件（`order_products.id` → 数量）。**只有 > 0 的行才会提交**。 */
    var returnQty by mutableStateOf<Map<Long, Int>>(emptyMap())
    var returnNote by mutableStateOf("")
    var returnSubmitting by mutableStateOf(false)

    /** 这一行**最多还能退几件**（规则只有一份：`core/ReturnRules`，与后端 `max_returnable` 同源）。 */
    fun maxReturnable(line: com.tapmoay.sorders.data.remote.dto.OrderProductDto): Int =
        com.tapmoay.sorders.core.ReturnRules.maxReturnable(
            line.quantity,
            line.damageQuantity,
            line.returnedQuantity,
        )

    fun hasReturnable(o: OrderDto): Boolean = o.orderProducts.any { maxReturnable(it) > 0 }

    /** 打开发货单：默认**全部退满**（用户最常见的就是整单退，再自己往下减）。 */
    fun openReturn(o: OrderDto) {
        returnTarget = o
        returnQty = o.orderProducts.associate { it.id to maxReturnable(it) }
        returnNote = ""
        showReturnDialog = true
    }

    fun setReturnQty(lineId: Long, qty: Int) {
        val o = returnTarget ?: return
        val line = o.orderProducts.firstOrNull { it.id == lineId } ?: return
        // 上限夹在这一处：手输、加减号、整单三条路都走它，所以不可能有"填了 5 却只退 3"的鬼状态
        returnQty = returnQty + (lineId to qty.coerceIn(0, maxReturnable(line)))
    }

    fun returnAll() {
        val o = returnTarget ?: return
        returnQty = o.orderProducts.associate { it.id to maxReturnable(it) }
    }

    fun returnNone() {
        val o = returnTarget ?: return
        returnQty = o.orderProducts.associate { it.id to 0 }
    }

    /** 这次要退的金额（元）—— 与后端红冲公式同一份：单价 × 数量。 */
    fun returnAmount(): String {
        val o = returnTarget ?: return "0.00"
        val total = o.orderProducts.fold(java.math.BigDecimal.ZERO) { acc, line ->
            val q = returnQty[line.id] ?: 0
            acc.add(
                (line.unitPrice?.toBigDecimalOrNull() ?: java.math.BigDecimal.ZERO)
                    .multiply(java.math.BigDecimal(q)),
            )
        }.setScale(2, java.math.RoundingMode.HALF_UP)
        return total.toPlainString()
    }

    fun confirmReturn() {
        val o = returnTarget ?: return
        val items = o.orderProducts
            .mapNotNull { line -> (returnQty[line.id] ?: 0).takeIf { it > 0 }?.let { line.id to it } }
        if (items.isEmpty()) {
            error = "请至少勾一个要退的商品（数量大于 0）"
            return
        }
        returnSubmitting = true
        error = null
        viewModelScope.launch {
            try {
                val r = container.repo.returnOrder(
                    o.id,
                    items.map { com.tapmoay.sorders.data.remote.dto.OrderReturnItem(it.first, it.second) },
                    returnNote.trim(),
                )
                actionResult = buildString {
                    append("已退货 ¥").append(r.returnedAmount)
                    if ((r.refundAmount.toDoubleOrNull() ?: 0.0) > 0.0) {
                        append("，并退给客户 ¥").append(r.refundAmount)
                    }
                    if (r.fullyReturned) append("（整单退完，订单已变为「已退货」）")
                    r.warnings.forEach { append("；").append(it) }
                }
                showReturnDialog = false
                returnTarget = null
                load()
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                returnSubmitting = false
            }
        }
    }

    // 复用：编辑/撤回/异常用
    fun dismissDialogs() {
        showEditDialog = false
        showRecallDialog = false
        showExceptionDialog = false
        showReturnDialog = false
    }
}

/** 服务端 `GET /orders` 的缺省条数上限（与后端 `DEFAULT_LIST_LIMIT` 对齐）。 */
private const val ORDER_LIST_LIMIT = 300
