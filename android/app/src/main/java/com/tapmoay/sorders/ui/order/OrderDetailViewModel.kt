package com.tapmoay.sorders.ui.order

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.data.remote.dto.OrderDto
import com.tapmoay.sorders.data.repo.toApiException
import kotlinx.coroutines.launch
import java.io.File

class OrderDetailViewModel(
    private val container: AppContainer,
    private val orderId: Long,
) : ViewModel() {

    var order by mutableStateOf<OrderDto?>(null)
    var loading by mutableStateOf(false)
    var error by mutableStateOf<String?>(null)
    var acting by mutableStateOf(false)

    // 货主撤销
    var showCancelDialog by mutableStateOf(false)

    // 派单员：收款/挂账（仅派单员界面显示）
    var showPayConfirm by mutableStateOf(false)
    var showChargeSheet by mutableStateOf(false)
    var arrearsUnits by mutableStateOf<List<com.tapmoay.sorders.data.remote.dto.ArrearsUnitDto>>(emptyList())
    var loadingUnits by mutableStateOf(false)
    var actionResult by mutableStateOf<String?>(null)

    // 司机：确认 / 备注 / 拍照送达
    var showNoteDialog by mutableStateOf(false)
    var noteText by mutableStateOf("")
    var showDeliverySheet by mutableStateOf(false)
    var capturedPhotos by mutableStateOf<List<String>>(emptyList())
    var pendingRawPhoto by mutableStateOf<String?>(null)
    var driverRemark by mutableStateOf("")
    var uploading by mutableStateOf(false)
    // 货损（选填，公司自担）：商品行 id → 货损数量；damageNote 订单备注
    val damageByProduct = mutableStateMapOf<Long, Int>()
    var damageNote by mutableStateOf("")
    fun resetDamage() {
        damageByProduct.clear()
        damageNote = ""
    }

    // 派单员：修改运费
    var showFreightDialog by mutableStateOf(false)
    var draftFreight by mutableStateOf("")

    fun openFreightDialog() {
        draftFreight = order?.freightFee ?: ""
        showFreightDialog = true
    }

    fun saveFreight() {
        viewModelScope.launch {
            acting = true
            error = null
            try {
                container.repo.updateFreight(orderId, draftFreight.trim().ifBlank { null })
                actionResult = "运费已更新"
                showFreightDialog = false
                load()
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                acting = false
            }
        }
    }

    // 派单员：拆分订单
    var showSplitDialog by mutableStateOf(false)
    var splitPartsText by mutableStateOf("")

    fun openSplitDialog() {
        splitPartsText = ""
        showSplitDialog = true
    }

    fun saveSplit() {
        val parts = splitPartsText.split("/", "，", ",")
            .map { it.trim().toIntOrNull() }.filterNotNull()
        if (parts.size < 2) {
            error = "请按份填写比例，如 150/150"
            return
        }
        viewModelScope.launch {
            acting = true
            error = null
            try {
                val kids = container.repo.splitOrder(orderId, parts)
                actionResult = "已拆分为 " + kids.size + " 单，可分别派单"
                showSplitDialog = false
                load()
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                acting = false
            }
        }
    }

    init {
        load()
        // 状态变化（接单/送达/派单等）自动刷新详情页，无需手动刷新
        viewModelScope.launch {
            container.realtimeHub.refreshOrders.collect { load() }
        }
    }

    fun load() {
        loading = order == null
        error = null
        viewModelScope.launch {
            try {
                order = container.repo.order(orderId)
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                loading = false
            }
        }
    }

    fun cancel(reason: String = "") {
        acting = true
        error = null
        viewModelScope.launch {
            try {
                order = container.repo.cancelOrder(orderId, reason)
                showCancelDialog = false
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                acting = false
            }
        }
    }

    // ---- 司机操作 ----

    fun ack() {
        acting = true
        viewModelScope.launch {
            try {
                order = container.repo.driverAck(orderId)
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                acting = false
            }
        }
    }

    fun saveNote() {
        val note = noteText.trim()
        if (note.isBlank()) return
        acting = true
        viewModelScope.launch {
            try {
                order = container.repo.driverNote(orderId, note)
                noteText = ""
                showNoteDialog = false
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                acting = false
            }
        }
    }

    fun addCapturedPhoto(path: String) {
        capturedPhotos = capturedPhotos + path
    }

    fun removeCapturedPhoto(index: Int) {
        capturedPhotos = capturedPhotos.filterIndexed { i, _ -> i != index }
    }

    fun pay() {
        acting = true
        viewModelScope.launch {
            try {
                order = container.repo.payOrder(orderId)
                actionResult = "已确认现场收款"
                showPayConfirm = false
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                acting = false
            }
        }
    }

    fun openCharge() {
        loadingUnits = true
        viewModelScope.launch {
            try {
                arrearsUnits = container.repo.arrearsUnits()
                showChargeSheet = true
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                loadingUnits = false
            }
        }
    }

    fun charge(unitId: Long) {
        acting = true
        viewModelScope.launch {
            try {
                order = container.repo.chargeOrder(orderId, unitId)
                actionResult = "已挂账"
                showChargeSheet = false
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                acting = false
            }
        }
    }

    /** payment：cash=收取现金 arrears=挂账 null=默认（未勾选收现时自动挂账） */
    fun completeDirect(onDone: () -> Unit, payment: String? = null) {
        acting = true
        error = null
        val dmg = damageItems()
        viewModelScope.launch {
            try {
                order = container.repo.completeDirect(orderId, driverRemark.trim(), payment, dmg, damageNote.trim())
                actionResult = if (payment == "cash") "已完成并收取现金" else if (payment == "arrears") "已完成并挂账" else "订单已完成"
                driverRemark = ""
                resetDamage()
                onDone()
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                acting = false
            }
        }
    }

    /** payment：cash=收取现金 arrears=挂账 null=自动挂账 */
    fun completeDelivery(onDone: () -> Unit, payment: String? = null) {
        if (capturedPhotos.isEmpty()) {
            error = "请至少拍摄一张送达照片"
            return
        }
        uploading = true
        error = null
        val dmg = damageItems()
        viewModelScope.launch {
            try {
                order = container.repo.completeWithUpload(
                    orderId,
                    capturedPhotos.map { File(it) },
                    driverRemark.trim(),
                    payment,
                    dmg,
                    damageNote.trim(),
                )
                driverRemark = ""
                resetDamage()
                showDeliverySheet = false
                onDone()
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                uploading = false
            }
        }
    }

    fun damageItems(): List<com.tapmoay.sorders.data.remote.dto.DamageItem> =
        damageByProduct.filter { it.value > 0 }
            .map { com.tapmoay.sorders.data.remote.dto.DamageItem(it.key, it.value) }
}