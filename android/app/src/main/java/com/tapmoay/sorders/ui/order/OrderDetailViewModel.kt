package com.tapmoay.sorders.ui.order

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.data.remote.dto.OrderDto
import com.tapmoay.sorders.core.InputRules
import com.tapmoay.sorders.data.remote.api.PriceRuleDto
import com.tapmoay.sorders.data.remote.dto.OrderProductCreateRequest
import com.tapmoay.sorders.data.remote.dto.OrderProductDto
import com.tapmoay.sorders.data.remote.dto.OrderProductUpdateRequest
import com.tapmoay.sorders.data.remote.dto.OrderTransferLineBody
import com.tapmoay.sorders.data.remote.dto.OrderTransferRequest
import com.tapmoay.sorders.data.remote.dto.OrderTransferResultDto
import com.tapmoay.sorders.data.remote.dto.OrderUpdateRequest
import com.tapmoay.sorders.data.remote.dto.ProductDto
import com.tapmoay.sorders.data.remote.dto.UserDto
import com.tapmoay.sorders.data.repo.toApiException
import com.tapmoay.sorders.ui.common.PickedLine
import com.tapmoay.sorders.util.trimMoneyZeros
import kotlinx.coroutines.launch
import java.io.File

class OrderDetailViewModel(
    private val container: AppContainer,
    private val orderId: Long,
) : ViewModel(), OrderEditHost {

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

    // 撤销（货主撤自己的单 / 派单员代客撤销 —— 见台账 L-12）
    var showCancelDialog by mutableStateOf(false)

    /**
     * 撤销弹层里的失败原因（2026-10-06，台账 L-13）。
     *
     * ⛔ 不许写页面级 [error]：那会把整页换成 ErrorView —— 弹窗还开着、内容先消失。
     */
    var cancelError by mutableStateOf<String?>(null)

    // 软删除（隔离区 30 天，派单员可恢复）
    var showDeleteDialog by mutableStateOf(false)

    // 派单员：收款/挂账（仅派单员界面显示）
    var showPayConfirm by mutableStateOf(false)
    var showChargeSheet by mutableStateOf(false)
    var arrearsUnits by mutableStateOf<List<com.tapmoay.sorders.data.remote.dto.ArrearsUnitDto>>(emptyList())
    var loadingUnits by mutableStateOf(false)
    var actionResult by mutableStateOf<String?>(null)

    // 司机：确认 / 内部备注 / 拍照送达（2026-10-06 台账 L-04：两个弹层退役，改成页面内的字段）
    //
    // ⛔ 从前这里有 `showNoteDialog`（内部备注弹窗）与 `showDeliverySheet`（拍照送达底部抽屉）
    //    两个开关。现在「要不要弹层」这件事不存在了：照片区、送达备注、提交按钮直接画在详情页
    //    最底下，状态只剩「已经拍了几张」（`capturedPhotos`）与「备注写了什么」
    //    （`driverRemark` / `noteText`）。写入口是**追加**语义，所以 `noteText` 不回填已有备注。
    var noteText by mutableStateOf("")
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

    // ── 派单员：转货（把货转给别的货主，CHG-0042）─────────────────────────────
    //
    // 用户说的三种形状其实是**同一件事**，所以只有一条命令（后端 `commands/order.py::transfer_lines`）：
    // · 把 A 的 50 件里的 30 件并给 B（B 自己还有 40 件）→ 后端会找到 B 在途的那张单并进去；
    // · 把 A 的 50 件拆成 20 + 30 给 B 和 C → 转两次，第二次源单还在（货没被搬空）；
    // · 整单全给 B → 一次全填，源单被搬空 → 后端按「撤销」把它作废。
    //
    // ⚠️ 界面**不预告**"转完两边各剩多少"：那是后端与账的事，这里只负责收齐派单员的意思，
    //    结果以回参为准重拉一次（load()）——自己算一份必然和后端算的不是一个数。
    var showTransferSheet by mutableStateOf(false)
    var showTransferPicker by mutableStateOf(false)

    /** 可选的目标货主名册（与下单页同一份：`repo.shippers()`；含临时货主那条路）。 */
    var transferShippers by mutableStateOf<List<UserDto>>(emptyList())
    var transferTargetId by mutableStateOf<Long?>(null)
    var transferTempName by mutableStateOf<String?>(null)

    /** 订单行 id → 这一行要**转出去几件**（不在表里的行 = 不转）。 */
    val transferQty = mutableStateMapOf<Long, Int>()
    var transferError by mutableStateOf<String?>(null)
    var transferBusy by mutableStateOf(false)

    /** 目标货主在界面上显示成什么（选完人之后那一行要把他写出来）。 */
    val transferTargetLabel: String
        get() {
            transferTargetId?.let { id ->
                transferShippers.firstOrNull { it.id == id }?.let { u ->
                    return u.fullName.ifBlank { u.username }
                }
            }
            return transferTempName.orEmpty()
        }

    /** 打开转货：**先选人**（没定转给谁，填数量没有意义）。 */
    fun openTransfer() {
        transferTargetId = null
        transferTempName = null
        transferQty.clear()
        transferError = null
        showTransferPicker = true
        loadTransferShippers()
    }

    private fun loadTransferShippers() {
        viewModelScope.launch {
            // 名册拉不到**不算错**：临时货主那条路照样能把货转出去（与下单页同一处分寸）。
            transferShippers = runCatching { container.repo.shippers() }.getOrDefault(emptyList())
        }
    }

    fun onPickTransferShipper(id: Long) {
        transferTargetId = id
        transferTempName = null
        showTransferPicker = false
        showTransferSheet = true
    }

    fun onPickTransferTemp(name: String) {
        transferTempName = name.trim()
        transferTargetId = null
        showTransferPicker = false
        showTransferSheet = true
    }

    /**
     * 回到"选人"那一步。
     *
     * ⚠️ 必须**先关这一个再开那一个**：两个 ModalBottomSheet 同时在屏上，底下的会被压没，
     * 关掉上面那个之后它也不一定回来（真机上表现为"点取消，整页空了"）。
     */
    fun reopenTransferPicker() {
        showTransferSheet = false
        showTransferPicker = true
    }

    fun setTransferQty(lineId: Long, qty: Int) {
        transferQty[lineId] = qty
    }

    /** 「全部转出」：每一行都填成它**现在的**数量（整单转走那条路）。 */
    fun fillAllTransfer() {
        order?.orderProducts?.forEach { transferQty[it.id] = it.quantity }
    }

    fun saveTransfer() {
        val o = order ?: return
        val target = transferTargetId
        val temp = transferTempName?.trim().orEmpty()
        if (target == null && temp.isEmpty()) {
            transferError = "请先选一位货主（或填临时货主）"
            return
        }
        // 只报"真的要转的行"：没填的行不传（传 0 会被后端当成非法数量）。
        // 上限夹在**这一行现有数量**之内 —— 后端也会拒，但不该让他先跑一趟网络才知道。
        val lines = o.orderProducts.mapNotNull { line ->
            val q = transferQty[line.id] ?: 0
            if (q >= 1) OrderTransferLineBody(line.id, q.coerceAtMost(line.quantity)) else null
        }
        if (lines.isEmpty()) {
            transferError = "请至少填一件要转出去的货"
            return
        }
        viewModelScope.launch {
            transferBusy = true
            transferError = null
            try {
                val r = container.repo.transferOrderLines(
                    orderId,
                    OrderTransferRequest(
                        shipperId = target,
                        // 二选一：选了已注册货主就不带临时名字（后端也以真货主为准）
                        tempShipperName = if (target == null) temp else null,
                        lines = lines,
                    ),
                )
                actionResult = transferResultText(r)
                showTransferSheet = false
                load()
            } catch (e: Exception) {
                // 错画在抽屉里（与拆单/改行同一条规矩）：整页顶成错误页会把刚填的丢掉。
                transferError = toApiException(e).message
            } finally {
                transferBusy = false
            }
        }
    }

    /** 转货结果说人话：转了几行、去了哪张单、源单有没有被搬空作废。 */
    private fun transferResultText(r: OrderTransferResultDto): String {
        val who = r.order.shipperName?.takeIf { it.isNotBlank() }
            ?: r.order.tempShipperName?.takeIf { it.isNotBlank() }
            ?: "目标货主"
        val head = "已把 " + r.movedLines + " 行货转给「" + who + "」"
        // 新单跟没跟上原来那位司机（CHG-0043）：跟上了点名司机；没跟上把原因原样说出来
        // （⛔ 不许吞掉 —— 单子这时候躺在待派单池里等人派，不说清楚就会以为什么都没发生）。
        val follow = when {
            r.followedDriverName != null -> "，新单已派给原司机 " + r.followedDriverName
            r.followSkippedReason != null -> "，" + r.followSkippedReason
            else -> ""
        }
        return when {
            r.sourceCancelled -> head + "，源单已撤销（货全转走了）" + follow
            r.createdTarget -> head + "，开了一张新单 " + r.order.orderNo + follow
            else -> head + "，并进了 " + r.order.orderNo + "（他本来在途的那张）" + follow
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
        if (acting) return  // 防连点：一次网络往返期间再点两次会发两遍撤销（第二遍必然 400）
        acting = true
        cancelError = null
        viewModelScope.launch {
            try {
                order = container.repo.cancelOrder(orderId)
                showCancelDialog = false
            } catch (e: Exception) {
                // ⛔ 不写页面级 [error]（整页 ErrorView 会把内容一起带走）；错误画在弹层自己里面
                cancelError = toApiException(e).message
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
                // 写完就清空：这一格是**再写一条**，不是编辑框（后端 append-only，见 `driver-note`）。
                noteText = ""
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

    /**
     * 不带照片的那条完成路（`POST /orders/{id}/complete`）。
     *
     * ⛔ 2026-10-06（台账 L-15）起**界面不再走它** —— 所有司机（含挂车）一律先拍照，走 [completeDelivery]。
     *    留在这里是因为那条端点还得对老版本 APK / 外部调用方可用；服务端的照片门已收紧：
     *    空照片列表一律 400「请至少上传一张送达照片」。
     * payment：cash=收取现金 arrears=挂账 null=默认（未勾选收现时自动挂账）
     */
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
                // 已拍的照片**不清**：这一页随后就是「已送达」，照片区随之不再画；
                // 清掉反而会让上传失败后重试时丢图（文件本来也还在 `cacheDir/photos`）。
                onDone()
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                uploading = false
            }
        }
    }

    // ---- 就地在详情页改单（CHG-0041）----
    //
    // 用户 2026-10-05：「编辑订单不是新增一个订单界面而是在详情订单界面……点击对应的 ui 信息
    // 就可以对应进行编辑」。所以这一层只有**草稿 + 保存**两个动作，界面那一侧负责
    // 「点哪一块 → 哪一块变成输入框」（见 ui/order/OrderEditInline.kt）。

    /** 正在就编辑的那一块（null = 没在编辑）。取值见 [OrderEditField]。 */
    override var editingField by mutableStateOf<String?>(null)
        private set

    /**
     * 草稿（键见 [OrderEditField]）。
     *
     * ⚠️ 每次 [startEdit] 都把六个数**从这一单当前的值重新铺一遍**：改一组、其余组原样带回去。
     * 不这么做的话，上一轮改了一半又取消的草稿会混进这一次的请求里 —— 那等于替用户改了别的东西，
     * 而且他看不到（那一块当时没在编辑态）。
     */
    private val editDrafts = mutableStateMapOf<String, String>()

    /** 上一次改动失败的原因（就地显示，**不换整页**：内容还在，只是这一步没成）。 */
    override var editError by mutableStateOf<String?>(null)
        private set

    /** 一次改动进行中：防连点（连点两次会改两遍，司机也会收到两条消息）。 */
    override var editBusy by mutableStateOf(false)
        private set

    /** 正在改的那一行货（行的 id；null = 没在编辑）。 */
    override var editingLineId by mutableStateOf<Long?>(null)
        private set

    override var lineQty by mutableStateOf("")
        private set

    override var linePrice by mutableStateOf("")
        private set

    /** 「加一件货」的选品弹层。 */
    var showLinePicker by mutableStateOf(false)
        private set

    var linePickerProducts by mutableStateOf<List<ProductDto>>(emptyList())
        private set

    var linePickerLoading by mutableStateOf(false)
        private set

    var linePickerCategories by mutableStateOf<List<String>>(emptyList())
        private set

    /**
     * 商品库的专属价（这一单货主的那一份）。
     *
     * editPriceRulesShipper 是「这份 map 属于谁」的守卫：对不上就回退默认价 ——
     * 与 OrderCreateViewModel.priceFor 同一条教训（专属价规则没到 ≠ 这个货主没有专属价）。
     */
    private var editPriceRules by mutableStateOf<Map<Long, PriceRuleDto>>(emptyMap())
    private var editPriceRulesShipper by mutableStateOf<Long?>(null)

    override fun draft(key: String): String = editDrafts[key].orEmpty()

    override fun setDraft(key: String, value: String) {
        editDrafts[key] = value
    }

    override fun startEdit(field: String) {
        val o = order ?: return
        editDrafts[OrderEditField.ADDRESS_DETAIL] = o.addressDetail
        editDrafts[OrderEditField.DONGJIA_NAME] = o.contactDongjiaName
        editDrafts[OrderEditField.DONGJIA_PHONE] = o.contactDongjiaPhone
        editDrafts[OrderEditField.BOSS_NAME] = o.contactBossName
        editDrafts[OrderEditField.BOSS_PHONE] = o.contactBossPhone
        editDrafts[OrderEditField.REMARK_TEXT] = o.remark
        editError = null
        editingLineId = null
        editingField = field
    }

    override fun cancelEdit() {
        editingField = null
        editError = null
    }

    /**
     * 存这一个编辑块。
     *
     * 报的是**六个字段全量**（不是只报改的那一个）：后端 `PATCH /orders/{id}` 是"给什么改什么"，
     * 而其余五个都是刚从这一单读出来的**当前值**，原样带回去等于没动它。
     * 这么写还有个好处：改地址、改收货人、改下单人、改备注走的是**同一条路径** ——
     * 少一条分支就少一处"某个字段忘了带上"的机会。
     *
     * ⚠️ 内部备注（`internalNotes`）原样带回：它是派单员写的内部话，不在这一层改，
     *    但少了它会不会被清掉取决于后端的缺席语义，带上就没有这个疑问。
     * ⛔ 货主归属（`shipper_id`）**不在这里**：那是改账，不是改单（用户 2026-10-05 的两件事分开谈）。
     */
    override fun saveEdit() {
        val o = order ?: return
        // ⚠️ 这两个局部变量**不能叫 dongjiaPhone / bossPhone**：_check_contact_binding.py 按
        //    \bdongjia(Phone|Name)\s*= 找「界面直写收货人两栏」，它连变量声明一起抓 —— 那是误报，
        //    但改名比松判据安全（那条判据管的是下单页的手改入口清 pickedContactId）。
        val phoneDraft = draft(OrderEditField.DONGJIA_PHONE).trim()
        val bossDraft = draft(OrderEditField.BOSS_PHONE).trim()
        // 电话格式先在界面这一侧挡一道（规则只有一份：core/InputRules.kt）。生产库里真的躺着
        // 「嘿嘿」「嘻嘻」这种电话（见 InputRules 文件头），那时要说清「这一单的电话得先改一下」，
        // 而不是让后端甩一句看不懂的话。
        InputRules.phoneError(phoneDraft)?.let { editError = it; return }
        InputRules.phoneError(bossDraft)?.let { editError = it; return }
        if (editBusy) return
        editBusy = true
        editError = null
        viewModelScope.launch {
            try {
                order = container.repo.updateOrder(
                    o.id,
                    OrderUpdateRequest(
                        addressDetail = draft(OrderEditField.ADDRESS_DETAIL).trim(),
                        contactDongjiaPhone = phoneDraft,
                        contactBossPhone = bossDraft,
                        contactDongjiaName = draft(OrderEditField.DONGJIA_NAME).trim(),
                        contactBossName = draft(OrderEditField.BOSS_NAME).trim(),
                        remark = draft(OrderEditField.REMARK_TEXT).trim(),
                        internalNotes = o.internalNotes,
                    ),
                )
                editingField = null
                actionResult = "已经改好，司机那边会收到一条消息"
                load()
            } catch (e: Exception) {
                editError = toApiException(e).message
            } finally {
                editBusy = false
            }
        }
    }

    // ---- 改一件货（数量 / 单价 / 删掉）----

    override fun updateLineQty(value: String) {
        lineQty = value
    }

    override fun updateLinePrice(value: String) {
        linePrice = value
    }

    override fun startLineEdit(line: OrderProductDto) {
        editingField = null
        editingLineId = line.id
        lineQty = line.quantity.toString()
        // 预填走 `trimMoneyZeros`（可编辑金额框的预填规矩，见 util/Money.kt 的 ④）：
        // 后端单价列是 Numeric(14,4)，直接填进去是 `60.0000` 这种，用户得先删掉四个 0 才能改价。
        // ⛔ 不用 `formatMoney` —— 它只留两位，会把 `12.3456` 的价预填成 `12.35`（＝用户没改价、价却变了）。
        linePrice = trimMoneyZeros(line.unitPrice)
        editError = null
    }

    override fun cancelLineEdit() {
        editingLineId = null
        editError = null
    }

    /**
     * 存这一行（数量 + 单价）。
     *
     * ⚠️ 单价与数量必须一起报：后端是把两个值合起来重算行金额的，只报单价它会按旧数量算，
     * 出现「改了价、总额没动」这种没人看得懂的结果。
     */
    override fun saveLine() {
        val lineId = editingLineId ?: return
        val qty = lineQty.trim().toIntOrNull()
        if (qty == null || qty <= 0) {
            editError = "数量要填一个大于 0 的整数"
            return
        }
        val price = linePrice.trim()
        if (price.isEmpty() || price.toDoubleOrNull() == null) {
            editError = "单价要填数字"
            return
        }
        if (editBusy) return
        editBusy = true
        editError = null
        viewModelScope.launch {
            try {
                container.repo.updateOrderProduct(
                    lineId,
                    OrderProductUpdateRequest(quantity = qty, unitPrice = price),
                )
                editingLineId = null
                actionResult = "这件货改好了，司机那边会收到一条消息"
                load()
            } catch (e: Exception) {
                editError = toApiException(e).message
            } finally {
                editBusy = false
            }
        }
    }

    /** 删掉这一行（后端把它从这一单里去掉，货主那边的账跟着变）。 */
    override fun deleteLine() {
        val lineId = editingLineId ?: return
        if (editBusy) return
        editBusy = true
        editError = null
        viewModelScope.launch {
            try {
                container.repo.deleteOrderProduct(lineId)
                editingLineId = null
                actionResult = "这一件货删掉了，司机那边会收到一条消息"
                load()
            } catch (e: Exception) {
                editError = toApiException(e).message
            } finally {
                editBusy = false
            }
        }
    }

    // ---- 加一件货（选品弹层）----

    override fun openLinePicker() {
        showLinePicker = true
        loadEditProducts()
        loadEditPriceRules(order?.shipperId)
    }

    fun closeLinePicker() {
        showLinePicker = false
    }

    /**
     * 商品库（加一件货要用）。
     *
     * [force] = true 时重拉一次（上一次没拉到时的「重试」）；否则已经有货就不动它 ——
     * 每次开弹层都重拉一遍，用户挑到一半的清单会被这一次刷新清掉。
     * 失败原因落在编辑块里（[editError]），**不换整页**。
     */
    fun loadEditProducts(force: Boolean = false) {
        if (linePickerLoading || (!force && linePickerProducts.isNotEmpty())) return
        linePickerLoading = true
        viewModelScope.launch {
            try {
                linePickerProducts = container.repo.products(includeInactive = false)
                linePickerCategories = container.repo.productCategories().map { it.name }
            } catch (e: Exception) {
                editError = toApiException(e).message
            } finally {
                linePickerLoading = false
            }
        }
    }

    /**
     * 拉这一单货主的专属价。
     *
     * 取数只有 repo.priceRules 一处（与 OrderCreateViewModel 同一份规则），界面不许自己拼。
     */
    private fun loadEditPriceRules(shipperId: Long?) {
        if (shipperId == null || editPriceRulesShipper == shipperId) return
        viewModelScope.launch {
            try {
                editPriceRules = container.repo.priceRules(shipperId).associateBy { it.productId }
                editPriceRulesShipper = shipperId
            } catch (_: Exception) {
                // 没拿到就不报价（priceForLinePicker 回退默认价）。
                // ⛔ 不许把「不知道」记成「这个货主没有专属价」
                editPriceRules = emptyMap()
                editPriceRulesShipper = null
            }
        }
    }

    /**
     * 加一件货时报的单价：这一单货主的专属价优先，没有就用商品库默认价。
     *
     * ⚠️ 只有 editPriceRulesShipper 与这一单的货主一致时才认那份规则 —— 对不上意味着「我们还不知道」，
     * 按默认价报给谈好价的批发商就是多收他的钱（不是少赚）。
     */
    fun priceForLinePicker(p: ProductDto): String {
        val sid = order?.shipperId
        if (sid == null || editPriceRulesShipper != sid) return p.defaultUnitPrice
        return editPriceRules[p.id]?.specialUnitPrice ?: p.defaultUnitPrice
    }

    /**
     * 从选品弹层挑回来的一件货。
     *
     * 挑多件 = 调多次接口：一行一次请求，其中一行失败也只丢那一行（整批一起失败会让人
     * 以为「一件都没加上」，然后重复加一遍）。失败原因落在编辑块里，选品页留着让他重试。
     */
    fun addPickedLines(picked: List<PickedLine>) {
        val o = order ?: return
        if (picked.isEmpty() || editBusy) return
        editBusy = true
        editError = null
        viewModelScope.launch {
            var added = 0
            var firstError: String? = null
            for (p in picked) {
                try {
                    container.repo.addOrderProduct(
                        OrderProductCreateRequest(
                            orderId = o.id,
                            productId = p.productId,
                            productNameSnapshot = p.name,
                            quantity = p.qty,
                            unitPrice = p.price,
                            unit = p.unit,
                        ),
                    )
                    added += 1
                } catch (e: Exception) {
                    if (firstError == null) firstError = toApiException(e).message
                }
            }
            if (added > 0) {
                showLinePicker = false
                actionResult = "加了 " + added + " 件货，司机那边会收到一条消息"
                load()
            }
            if (firstError != null) editError = firstError
            editBusy = false
        }
    }

    fun damageItems(): List<com.tapmoay.sorders.data.remote.dto.DamageItem> =
        damageByProduct.filter { it.value > 0 }
            .map { com.tapmoay.sorders.data.remote.dto.DamageItem(it.key, it.value) }
}