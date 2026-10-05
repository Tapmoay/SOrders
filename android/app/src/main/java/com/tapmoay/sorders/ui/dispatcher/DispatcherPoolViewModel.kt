package com.tapmoay.sorders.ui.dispatcher

import androidx.compose.runtime.*
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.data.remote.dto.FreightTemplateDto
import com.tapmoay.sorders.data.remote.dto.OrderDto
import com.tapmoay.sorders.data.remote.dto.UserDto
import com.tapmoay.sorders.data.repo.toApiException
import com.tapmoay.sorders.ui.common.ORDER_LIST_LIMIT
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch
import kotlinx.serialization.json.jsonPrimitive

class DispatcherPoolViewModel(
    private val container: AppContainer,
    /**
     * 是否在 init 里拉整个待派单池、并订阅实时刷新。
     *
     * 订单详情页只借**派单弹窗**（P12：详情页底部要有「派单」），它不该为弹一个框去拉
     * 几百条待派单，更不该被「别人又下了新单」刷自己的屏。
     */
    private val autoLoadPool: Boolean = true,
) : ViewModel() {

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
    /**
     * 派单员对**这一单**单独定的计费参数（v3.37）。空 = 走司机挂着的规则。
     *
     * 为什么要有这两个框：用户 2026-09-18「每单是不固定的，可能这一单是几百块，
     * 那一单是几十块，这些单价是由派单员来决定的」「提成…可能设置这一单」。
     * 只在**这个司机挂着规则**时才显示——没挂规则时后端会直接拒绝
     * （`driver_pay.override_problem`），先显示等于给用户一个填了必然报错的框。
     */
    var assignPieceAmount by mutableStateOf("")
    var assignCommissionRate by mutableStateOf("")
    var templates by mutableStateOf<List<FreightTemplateDto>>(emptyList())

    // 撤销弹窗（未派送订单）
    var showCancelDialog by mutableStateOf(false)
    var cancelOrderId by mutableStateOf<Long?>(null)

    var actionResult by mutableStateOf<String?>(null)

    /** 一次性提示（全选被截断、模板没加载出来……）。界面用 Snackbar 显示后置回 null。 */
    var notice by mutableStateOf<String?>(null)

    /** 待派总数（后端真实值）。null = 取不到（界面就不显示那句话，不编一个数）。 */
    var totalPending by mutableStateOf<Int?>(null)
        private set

    /** 运费模板没加载出来的原因（有值 = 下拉是空的，但不是"没配模板"）。 */
    var templateError by mutableStateOf<String?>(null)

    // ---- 分页：待派单池 / 已完成派单（CHG-0039）----

    /** 当前分页（[TAB_POOL] / [TAB_COMPLETED]）。 */
    var tab by mutableStateOf(TAB_POOL)

    /** 「已完成派单」那一档的单（`ACCEPTED` + `DISPATCHED` 两档相加，见 [loadDispatched]）。 */
    var dispatched by mutableStateOf<List<OrderDto>>(emptyList())

    /** 那一档的两次查询有没有撞上 300 条上限（界面据此说一句实话）。 */
    var dispatchedHitCap by mutableStateOf(false)

    // 退回派单池弹窗（静默动作：货主端无感）
    var showReleaseDialog by mutableStateOf(false)
    var releaseOrderId by mutableStateOf<Long?>(null)
    /** 退回原因（可选：这个动作不依赖理由，理由只是派单员自己的事后线索）。 */
    var releaseReason by mutableStateOf("")
    /**
     * 弹窗里的错误（退回失败的原因）。
     *
     * 与页面级 [error] 分开：弹窗还开着，不能把整页换成 ErrorView（那会让列表一起消失、
     * 用户以为数据没了）—— 同 `ui/common/Components.kt::FormErrorLine` 的那条教训。
     */
    var dialogError by mutableStateOf<String?>(null)

    private var loadJob: Job? = null

    init {
        if (autoLoadPool) {
            load()
            // 实时事件：待派单池变化自动刷新
            viewModelScope.launch {
                container.realtimeHub.refreshOrders.collect { load() }
            }
        }
    }

    /**
     * 按**当前分页**拉数据（待派单池 / 已完成派单）。
     *
     * 为什么合成一个入口：init 的实时订阅、各处的「重试」、派完/退完之后的"再拉一次"
     * 都只认 `load()`；分页切换只是换一个数据源，不该让每个调用点都去判断档位。
     */
    fun load() {
        if (tab == TAB_COMPLETED) loadDispatched() else loadPool()
    }

    private fun loadPool() {
        loadJob?.cancel()
        loadJob = viewModelScope.launch {
            loading = orders.isEmpty()
            error = null
            try {
                orders = container.repo.orders(status = "PENDING_DISPATCH")
                loadDrivers()
                // 后端的真实待派总数。
                // 为什么必须单独取：`GET /orders?status=PENDING_DISPATCH` 对派单员**服务端强制 300 条**
                // （积压几千单时接口会返回十几 MB），所以列表里的条数**不等于**待派总数。
                // 不取这个数，界面上就没有任何地方能告诉用户"你只看到了最近 300 单"。
                totalPending = try {
                    // 端点回的是 `{"count": N}`（JsonObject），不是裸数字
                    container.repo.pendingCount()["count"]?.jsonPrimitive?.content?.toIntOrNull()
                } catch (_: Exception) {
                    null
                }
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                loading = false
            }
        }
    }

    /**
     * 「已完成派单」那一档：**已经交到司机手里的单**（他已接单的 + 派了他还没点的）。
     *
     * 为什么是两次查询相加：这一档在数据上不是一个状态 —— `ACCEPTED`（司机点了接单）与
     * `DISPATCHED`（派给他了、他还没点）在货主与派单员眼里是同一件事（"货在这个司机手上"），
     * 而 `GET /orders` 的 `status` 只吃**一个**状态值（`api/v1/orders_query.py`）。
     *
     * ⚠️ 截断判据必须按**两次查询各自**判：两档合并后条数可能正好是 300 的两倍，
     *    用 `dispatched.size >= ORDER_LIST_LIMIT` 会把"恰好 300 单"误判成截断。
     */
    private fun loadDispatched() {
        loadJob?.cancel()
        loadJob = viewModelScope.launch {
            loading = dispatched.isEmpty()
            error = null
            try {
                val assigned = container.repo.orders(status = "DISPATCHED")
                val accepted = container.repo.orders(status = "ACCEPTED")
                dispatched = assigned + accepted
                dispatchedHitCap = assigned.size >= ORDER_LIST_LIMIT || accepted.size >= ORDER_LIST_LIMIT
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                loading = false
            }
        }
    }

    /**
     * 切分页：清掉选择态（批量选择只在待派那一档有意义），再按新档拉一次。
     *
     * 用户 2026-10-05：「在派单词（派单池）再加一个分页为已完成派单，这个已完成派单跟
     * 派单词是一样的。但是有一点不同，就是派单完成之后，他会进入到这里订单」。
     */
    fun selectTab(index: Int) {
        if (index == tab) return
        tab = index
        clearSelection()
        load()
    }

    /**
     * 单独拉司机名册（派单弹窗要用）。
     *
     * 抽出来是因为详情页那份 VM 是 autoLoadPool = false：它只借弹窗、不拉池子，
     * 名册得在**打开弹窗那一刻**按需拉（openAssign 里触发）。
     */
    private fun loadDrivers() {
        viewModelScope.launch {
            try {
                drivers = container.repo.drivers().filter { it.isActive }
            } catch (e: Exception) {
                error = toApiException(e).message
            }
        }
    }

    fun pendingCount(): Int = orders.count { it.status == "PENDING_DISPATCH" }

    /** 列表是不是被后端的 300 条上限截断了（界面据此显示一句实话）。 */
    val listTruncated: Boolean
        get() = (totalPending ?: 0) > orders.size

    /**
     * 「已完成派单」按司机分组：**一张卡 = 一个司机，卡里的小卡 = 他手上的单**。
     *
     * 用户 2026-10-05 逐字：「司机一个卡片是一个司机，然后司机里面有很多小卡片，
     * 小卡片就是订单，然后派单员可以点进去，对这些订单进行修改」。
     *
     * 组间顺序：谁手里有更新的单谁在前。这里没有"最后更新时间"可用（订单列表不带），
     * 用组内最大的 id 近似 —— 派单员刚退回/刚派出去的那张单所属的司机排在最上面。
     */
    val dispatchedGroups: List<DriverOrderGroup>
        get() = dispatched
            .groupBy { it.driverId }
            .map { (driverId, list) ->
                val sorted = list.sortedByDescending { it.id }
                val head = sorted.first()
                DriverOrderGroup(
                    driverId = driverId,
                    // 名字取不到时**不能空着**：卡片头只剩个电话，派单员认不出是谁
                    driverName = head.driverName?.takeIf { it.isNotBlank() }
                        ?: if (driverId == null) "未指派司机" else "司机 #" + driverId,
                    driverPhone = head.driverPhone,
                    orders = sorted,
                )
            }
            .sortedByDescending { it.orders.first().id }

    fun toggleSelect(id: Long) {
        val next = if (id in selectedIds) selectedIds - id else selectedIds + id
        // 上限在**勾选这一步**就拦住：让用户勾到 150 单、点了批量派单才报错，
        // 等于让他白选一遍（而且报的还是后端的英文 422）。
        if (next.size > MAX_BATCH_ASSIGN) {
            notice = "一次最多派 $MAX_BATCH_ASSIGN 单，已经选满了；要派更多请分两次"
            return
        }
        selectedIds = next
        if (selectedIds.isEmpty()) selectionMode = false
    }

    /**
     * 全选。
     *
     * ⚠️ **最多选 [MAX_BATCH_ASSIGN] 单**：后端 `POST /orders/batch-assign` 的
     * `order_ids` 上限是 100（`schemas/order.py`），选 300 单点「批量派单」会直接 422，
     * 一张单都派不出去。以前这里是"全选整个列表"，而池子最多 300 单——
     * 也就是"单子一多，批量派单必然失败"。
     */
    fun selectAll() {
        val all = orders.map { it.id }
        selectedIds = if (selectedIds.size == all.size && all.isNotEmpty()) {
            emptySet()
        } else {
            all.take(MAX_BATCH_ASSIGN).toSet()
        }
        if (all.size > MAX_BATCH_ASSIGN && selectedIds.isNotEmpty()) {
            notice = "一次最多派 $MAX_BATCH_ASSIGN 单，已替你选中前 $MAX_BATCH_ASSIGN 单（池里共 ${all.size} 单）"
        }
    }

    fun clearSelection() {
        selectionMode = false
        selectedIds = emptySet()
    }

    // ---- 派单 ----
    fun openAssign(orderId: Long? = null) {
        assignOrderId = orderId
        // ⚠️ 默认选谁：以前是 `drivers.firstOrNull()`，而司机名册按 id 倒序
        //    → 默认预选的是"最新建的那个司机"，派单员一路点下去就会派错人。
        //    现在**不预选**：让"选司机"这一步真的发生一次
        //    （少了这一步，确认按钮的意义只剩"确认我没改过"）。
        selectedDriverId = null
        assignNote = ""
        assignFreight = ""
        assignCollectCash = false
        assignPieceAmount = ""
        assignCommissionRate = ""
        // 名册可能还没拉过（详情页那份 VM 是 autoLoadPool = false，只借弹窗不拉池子）
        // —— 打开框之前按需拉一次，否则下拉里一个司机都没有。
        if (drivers.isEmpty()) loadDrivers()
        loadTemplates()
        showAssignDialog = true
    }

    fun loadTemplates() {
        viewModelScope.launch {
            try {
                templates = container.repo.freightTemplates()
            } catch (e: Exception) {
                // 静默失败在这里的后果很具体：模板下拉是空的，派单员以为"没配过模板"，
                // 于是运费全靠手打（而模板存在的意义就是不用手打）。
                templateError = toApiException(e).message
            }
        }
    }

    fun applyTemplate(t: FreightTemplateDto) {
        assignFreight = t.fee
    }

    val selectedDriver: UserDto?
        get() = drivers.find { it.id == selectedDriverId }

    /**
     * 这个司机是不是"按单拿钱"（决定要不要给他显示运费框、以及列表按哪一组展示）。
     *
     * ⛔ 判据必须**与账单同源**（2026-09-19 全项目报告 P0-3，high）：后端是**规则优先**
     *    （`driver_pay.snapshot_mode`：挂了规则就按规则算，`billing_mode` 只是兜底）。
     *    这里原来自己按 `billingMode ?: 车型` 猜 —— 挂着**运费提成**规则的大车司机被判成
     *    工资制 → 运费框**根本不显示** → 运费永远是空的 → 提成 = 0 × 比例 = 0
     *    → 送达时 `pay.total <= 0` **连账单都不生成**（司机白跑，账面上查不到异常）。
     *    现在直接读后端算好的 `paysPerOrder`（与 `freight_visible`、账单同一处口径）；
     *    老后端没有这个字段时才退回兜底判据（与 `resolve_billing_mode` 一字不差）。
     */
    fun isPieceDriver(u: UserDto?): Boolean {
        if (u == null) return false
        u.paysPerOrder?.let { return it }
        val mode = u.billingMode ?: (if (u.vehicleType == "trailer") "PIECE" else "SALARY")
        return mode == "PIECE"
    }

    /**
     * 确认派单。
     *
     * @param onAssigned 派成功之后回调 —— 订单详情页借这个 VM 弹框，靠它刷新自己那一份。
     */
    fun confirmAssign(onAssigned: () -> Unit = {}) {
        if (acting) return  // 防连点：一次网络往返期间再点一次会派两遍
        val driverId = selectedDriverId ?: run { error = "请选择司机"; return }
        if (selectedIds.size > MAX_BATCH_ASSIGN) {
            // 正常走不到这里（勾选和全选都拦了），但**并发/历史状态**下可能超——
            // 与其发一个必然 422 的请求，不如在这里说清楚。
            error = "一次最多派 $MAX_BATCH_ASSIGN 单（现在选了 ${selectedIds.size} 单），请分批"
            return
        }
        acting = true
        error = null
        viewModelScope.launch {
            try {
                val note = assignNote.trim().ifBlank { null }
                val collect = assignCollectCash
                val result = if (selectionMode && selectedIds.isNotEmpty()) {
                    // ⚠️ 后端是**逐单**返回结果的（`results[].success`），所以这里可以、也必须
                    // 如实报"成了几单、败了几单"。只回一句"派单成功：N 单"会让用户以为全成了。
                    val resp = container.repo.batchAssign(selectedIds.toList(), driverId, note, collect)
                    val okCount = resp.results.count { it.success }
                    val failed = resp.results.filter { !it.success }
                    if (failed.isNotEmpty()) {
                        val detail = failed.take(3).joinToString("；") {
                            "#${it.orderId}（" + (it.detail?.takeIf { s -> s.isNotBlank() } ?: "未说明原因") + "）"
                        }
                        actionResult = "派单结果：成功 $okCount 单、失败 ${failed.size} 单 —— " + detail +
                            if (failed.size > 3) " …（其余同理）" else ""
                    } else {
                        actionResult = "派单成功：$okCount 单"
                    }
                    okCount
                } else {
                    val oid = assignOrderId ?: 0L
                    if (oid == 0L) 0 else {
                        // ⛔ 派单员**填了什么就发什么**（2026-09-19 报告 P0-3）：这里原来写着
                        //    `if (isPieceDriver(...)) … else null` —— 判成工资制就把用户输入的
                        //    运费**整条丢掉**。就算判据本身是对的，也不该拿界面的猜测去丢用户的
                        //    输入：后端收不到运费，提成型的规则只能算成 0（老账口径更是直接 0 元）。
                        val fee = assignFreight.trim().ifBlank { null }
                        val piece = assignPieceAmount.trim().ifBlank { null }
                        val rate = assignCommissionRate.trim().ifBlank { null }
                        container.repo.assignOrder(oid, driverId, note, fee, collect, piece, rate)
                        actionResult = "派单成功：1 单"
                        1
                    }
                }
                if (result > 0) {
                    showAssignDialog = false
                    clearSelection()
                    // 派完了就闭嘴：这一单已经不在待派池里，手机还在喊「有新订单待派单」
                    // 会让他回头去找一张已经派掉的单。语义与司机「接单成功立刻停」完全一样
                    // （见 NewOrderAlert.speaks：待派单那条只播给派单员，所以只有这里能打断它）。
                    container.newOrderPlayer.stop()
                    // 订单详情页借这个 VM 弹派单框：派成了得让它刷新自己那一份
                    onAssigned()
                }
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

    // ---- 退回派单池（静默：货主端无感，CHG-0039）----
    fun openRelease(orderId: Long) {
        releaseOrderId = orderId
        releaseReason = ""
        dialogError = null
        showReleaseDialog = true
    }

    /**
     * 确认退回。
     *
     * ⛔ 这一个动作**不许**给货主发任何提醒、也**不许**改货主看到的状态
     * （用户 2026-10-05 逐字：「货主端仍然会显示状态为已派单或者说司机已接单；
     * 订单的状态会默默发生改变，不会有任何的消息提醒」）—— 所以这里只调后端那一个
     * 静默端点，成功后什么也不广播；司机那边掉单是后端发 `orders.revoked` 的事。
     */
    fun confirmRelease() {
        val oid = releaseOrderId ?: return
        if (acting) return  // 防连点：一次网络往返期间再点一次会退两遍
        acting = true
        dialogError = null
        viewModelScope.launch {
            try {
                container.repo.releaseOrder(oid, releaseReason.trim())
                showReleaseDialog = false
                actionResult = "已退回派单池，货主端不会有任何变化"
                load()
            } catch (e: Exception) {
                // 弹窗级错误：框还开着，不能把整页换成 ErrorView（那会让列表一起消失）
                dialogError = toApiException(e).message
            } finally {
                acting = false
            }
        }
    }

    companion object {
        /**
         * 一次批量派单最多几单。
         *
         * ⚠️ **必须与后端一致**：`backend/app/schemas/order.py` 里
         * `order_ids: list[int] = Field(..., min_length=1, max_length=100)`。
         * 后端放宽/收紧了这个数，这里也要跟着改（否则用户会在"选得下、派不出"之间撞墙）。
         */
        const val MAX_BATCH_ASSIGN = 100

        /** 分页下标（界面 `SegmentedPicker` 的 `selected`）。 */
        const val TAB_POOL = 0
        const val TAB_COMPLETED = 1
    }
}

/**
 * 「已完成派单」那一档里**一个司机 + 他手上的单**。
 *
 * 界面上就是"一张卡里套几张小卡"（用户 2026-10-05：「司机一个卡片是一个司机，
 * 然后司机里面有很多小卡片，小卡片就是订单」）。
 */
data class DriverOrderGroup(
    val driverId: Long?,
    val driverName: String,
    val driverPhone: String?,
    val orders: List<OrderDto>,
)
