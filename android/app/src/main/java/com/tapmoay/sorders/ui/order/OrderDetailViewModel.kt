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

    /**
     * 当前登录人是不是**批发商**（`users.is_member` 的货主）——「拨打司机电话」那一档要用它。
     *
     * 为什么要单独取一次 `/users/me`：会话（`core/TokenStore.kt::Session`）里只有角色 / 姓名 /
     * 电话，**没有 `is_member`**，而"批发商"在这里是**权限**（那颗拨号按钮给不给他），不能靠猜。
     * ⚠️ 取不到时保持 `false` ＝ **不给**：拿不准的动作就不递出去（真门还在后端，这里只决定画不画）。
     */
    var isMemberShipper by mutableStateOf(false)
        private set

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

    /** 正在传**位置图片**（与送达凭证的 `uploading` 分开：两个按钮不互相禁用）。 */
    var uploadingPlace by mutableStateOf(false)
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
        // 「我是不是批发商」——只给「拨打司机电话」那颗按钮用（判据 `ui/common/DriverCall.kt`）。
        viewModelScope.launch {
            isMemberShipper = runCatching { container.repo.me().isMember }.getOrDefault(false)
        }
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

    /**
     * 撤销这一单。
     *
     * ⚠️ 这里原来有个 `reason: String = ""` 参数，一路传到 `repo.cancelOrder(orderId, reason)`
     * —— 而**后端 `POST /orders/{id}/cancel` 根本不接收 reason**（`cancel_order` 只收 order_id），
     * 图层上也没有任何地方让它填：弹窗正文只有一句「撤销后派单员不再处理。」。
     * 也就是说"撤销原因"是个从头到尾都不存在的功能（`OrderCancelBody` 这个 DTO 全仓只有定义、零引用）。
     * 2026-09-23 复核 H8 把它删掉了：留着它会让人以为"原因已经传下去了"。
     * 真要做，就做成后端字段 + 界面输入框 + 审计留痕，而不是一个被静默丢掉的形参。
     */
    fun cancel() {
        acting = true
        error = null
        viewModelScope.launch {
            try {
                order = container.repo.cancelOrder(orderId)
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

    /**
     * 传一张**位置图片**（收货地址参考图）—— 货主 / 派单员 / **这单的司机**都能传。
     *
     * 用户 2026-09-20：
     * > 还有一个就是司机他也可以去上交补交照片，如果他到了地方没有照片的话，他也可以补。
     *
     * 后端会**同时**把这张图挂到这一单对应的「我的地点」那一条上
     * （`place_service.attach_order_photo`）：用户要的是"照片跟地点一样自动保存在库里"——
     * 下次下单选到这个位置，图已经在库里，不用再让每个货主各拍一次。
     */
    fun uploadPlacePhoto(file: java.io.File) {
        uploadingPlace = true
        error = null
        viewModelScope.launch {
            try {
                order = container.repo.uploadOrderAddressImage(orderId, file)
                actionResult = "位置图片已保存"
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                uploadingPlace = false
            }
        }
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

    /**
     * 挂账到**一个还不存在的单位名** —— 就地建一个再挂上（用户 2026-09-22 要的"自动添加"）。
     *
     * 用户原话：「我们这个挂账有个联动：假如有个订单，他没有结账，**直接点击挂账**，
     * 这个**挂账单位是自动添加的**」。
     *
     * ⚠️ **两步而不是一步**（先建单位、再挂账）：两个动作各自都有审计（`ARREARS_UNIT_UPSERT`
     * 与 `ORDER_CHARGE`），出问题时能看出是"建单位那步失败"还是"挂账那步失败"；
     * 而"一步完成"要新开后端契约，收益只有省一次往返。
     * ⚠️ **建成功、挂失败**时必须让用户看见：这时单位已经建出来了（列表里已经有了），
     * 所以那句话要写清"单位已建好，重新点一次挂账即可"，而不是一句笼统的失败。
     */
    fun chargeNewUnit(rawName: String) {
        val name = rawName.trim()
        if (name.isEmpty()) {
            error = "请先写一个挂账单位名"
            return
        }
        // 名册里已经有同名的 → 不重复建，直接用它挂（与后端 `find_or_create_unit` 同口径）
        arrearsUnits.firstOrNull { it.name == name }?.let { charge(it.id); return }
        acting = true
        viewModelScope.launch {
            try {
                val created = container.repo.createArrearsUnit(
                    com.tapmoay.sorders.data.remote.dto.ArrearsUnitCreateRequest(name = name),
                )
                arrearsUnits = container.repo.arrearsUnits()
                try {
                    order = container.repo.chargeOrder(orderId, created.id)
                    actionResult = "已挂账到「" + created.name + "」（单位是新建的）"
                    showChargeSheet = false
                } catch (e: Exception) {
                    error = "单位「" + created.name + "」已建好，但挂账没成功：" +
                        toApiException(e).message + "（再点一次挂账，从名册里选它）"
                }
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