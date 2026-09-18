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

    fun pendingCount(): Int = orders.count { it.status == "PENDING_DISPATCH" }

    /** 列表是不是被后端的 300 条上限截断了（界面据此显示一句实话）。 */
    val listTruncated: Boolean
        get() = (totalPending ?: 0) > orders.size

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

    /** 按单计费司机（挂车默认按单；显式 salary 覆盖） */
    fun isPieceDriver(u: UserDto?): Boolean {
        if (u == null) return false
        val mode = u.billingMode ?: (if (u.vehicleType == "trailer") "PIECE" else "SALARY")
        return mode == "PIECE"
    }

    fun confirmAssign() {
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
                        val fee = if (isPieceDriver(drivers.find { it.id == driverId })) assignFreight.trim().ifBlank { null } else null
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

    companion object {
        /**
         * 一次批量派单最多几单。
         *
         * ⚠️ **必须与后端一致**：`backend/app/schemas/order.py` 里
         * `order_ids: list[int] = Field(..., min_length=1, max_length=100)`。
         * 后端放宽/收紧了这个数，这里也要跟着改（否则用户会在"选得下、派不出"之间撞墙）。
         */
        const val MAX_BATCH_ASSIGN = 100
    }
}
