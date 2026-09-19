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
    /**
     * 「刷新失败但旧数据还在」时的一行提示（2026-09-19 审计）。
     *
     * 与 [error] 的分工：`error` = 没有数据可显示（整页 ErrorView）；
     * `refreshWarning` = 有数据、只是这次没刷新成功（界面显示一行提示，别把内容换掉）。
     * 本页有 socket 自动刷新，网络一抖就整页报错是真实发生过的体验事故。
     */
    var refreshWarning by mutableStateOf<String?>(null)
    var acting by mutableStateOf(false)

    // 货主撤销
    var showCancelDialog by mutableStateOf(false)

    // 软删除（隔离区 30 天，派单员可恢复）
    var showDeleteDialog by mutableStateOf(false)

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
        // ⚠️ 已经有数据时失败**不要整页变错误**（2026-09-19 审计）：本页会被 socket 事件高频触发刷新
        //    （谁派单/接单/撤回都会 `refreshOrders`），网络抖一下就 `error != null`，
        //    而界面的 `when` 里 error 优先于 order（`OrderDetailScreen`）→ 司机在路上最需要看单的
        //    那一刻整页被"网络连接失败"顶掉、刚看的东西全没了。有旧数据时把失败降级成一行提示。
        error = null
        viewModelScope.launch {
            try {
                order = container.repo.order(orderId)
            } catch (e: Exception) {
                val msg = toApiException(e).message
                if (order == null) error = msg else refreshWarning = msg
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

    /** 软删除：进入隔离区 30 天（用户不可见；派单员可恢复）；成功后返回列表 */
    fun delete(onDone: () -> Unit) {
        acting = true
        error = null
        viewModelScope.launch {
            try {
                container.repo.deleteOrder(orderId)
                showDeleteDialog = false
                container.realtimeHub.notifyOrdersChanged()
                onDone()
            } catch (e: Exception) {
                error = toApiException(e).message
                showDeleteDialog = false
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
                // 接单成功 = 司机已经动手了，立刻停止「来单了」播报：
                // 接完还在喊，司机会怀疑到底接上没有（另一端还在播报是同一个理由的反面）
                container.newOrderPlayer.stop()
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

    // ---- 司机/派单员：给没有坐标的订单补导航信息 ----
    //
    // 为什么入口开在订单详情而不是列表：这是**到场之后**做的动作，
    // 那时人已经在看这一单了；列表上一个"补导航"按钮既挤又会误触。
    var showNavPicker by mutableStateOf(false)
    var showNavDialog by mutableStateOf(false)
    var navDraftLat by mutableStateOf("")
    var navDraftLng by mutableStateOf("")
    var navDraftName by mutableStateOf("")
    var navDraftAddress by mutableStateOf("")

    /** 这单是否需要/允许补导航（司机或派单员 + 没有坐标 + 未撤销）。 */
    fun canFillNavigation(role: String): Boolean {
        val o = order ?: return false
        if (role != "driver" && role != "dispatcher") return false
        if (o.status == "CANCELLED") return false
        // 回收站里的单不在这里判：客户端拿不到"是否在隔离区"（OrderDto 没有这个字段），
        // 后端会回一句「这张订单在回收站里，不能补导航信息」——那句话比客户端猜要准。
        return o.addressLat.isNullOrBlank() || o.addressLng.isNullOrBlank()
    }

    fun openNavDialog(lat: Double, lng: Double, address: String) {
        navDraftLat = lat.toString()
        navDraftLng = lng.toString()
        navDraftAddress = address.trim()
        // 默认地点名 = 收货人称呼（货主地点库里显示的就是它）；用户可以改
        navDraftName = order?.addressDetail?.trim().orEmpty().ifBlank { address.trim() }
        showNavPicker = false
        showNavDialog = true
    }

    fun saveNavigation() {
        val lat = navDraftLat.toDoubleOrNull()
        val lng = navDraftLng.toDoubleOrNull()
        if (lat == null || lng == null) {
            error = "还没选到坐标，请先在地图上点一下"
            return
        }
        acting = true
        error = null
        viewModelScope.launch {
            try {
                order = container.repo.fillOrderNavigation(
                    orderId,
                    com.tapmoay.sorders.data.remote.dto.OrderNavigationBody(
                        addressLat = navDraftLat,
                        addressLng = navDraftLng,
                        name = navDraftName.trim(),
                        detailAddress = navDraftAddress,
                    ),
                )
                actionResult = "导航信息已补上，并存入共享地点库"
                showNavDialog = false
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