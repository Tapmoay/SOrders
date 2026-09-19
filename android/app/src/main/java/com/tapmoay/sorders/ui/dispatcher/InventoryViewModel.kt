package com.tapmoay.sorders.ui.dispatcher

import androidx.compose.runtime.*
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.data.remote.dto.InventoryMovementCreateRequest
import com.tapmoay.sorders.data.remote.dto.InventoryMovementDto
import com.tapmoay.sorders.data.remote.dto.InventorySummaryItemDto
import com.tapmoay.sorders.data.remote.dto.ProductDto
import com.tapmoay.sorders.data.repo.PageRows
import com.tapmoay.sorders.data.repo.toApiException
import kotlinx.coroutines.launch

class InventoryViewModel(private val container: AppContainer) : ViewModel() {

    var summary by mutableStateOf<List<InventorySummaryItemDto>>(emptyList())
    var movements by mutableStateOf<List<InventoryMovementDto>>(emptyList())

    /**
     * 流水"这一页不是全部"＝更早的还有，界面必须**说出来**。
     *
     * ⚠️ 判据只有一个：响应头 `X-Truncated`（2026-09-19 后端补的头，见
     *    `AppRepository.parsePageMeta`）。这里原来靠"这一页拿满了 500 条"去猜 ——
     *    后端有了真头之后再猜就会在**刚好 500 条**时提示一句假话。
     * 不说出来的后果是"更早的流水在 App 里静默消失"——账实不符时没人知道是没录还是没显示。
     */
    var movementsTruncated by mutableStateOf(false)
        private set

    /** 本次服务器上限（响应头 `X-Result-Limit`）；读不到 = null，界面不许自己编一个数。 */
    var movementsLimit by mutableStateOf<Int?>(null)
        private set
    var products by mutableStateOf<List<ProductDto>>(emptyList())
    var loading by mutableStateOf(false)
    var error by mutableStateOf<String?>(null)
    var acting by mutableStateOf(false)
    var actionResult by mutableStateOf<String?>(null)
    // 流水日期筛选
    var movDateFrom by mutableStateOf<String?>(null)
    var movDateTo by mutableStateOf<String?>(null)

    // 出入库弹窗
    var showMovementDialog by mutableStateOf(false)
    var movementProduct by mutableStateOf<ProductDto?>(null)
    var movementInbound by mutableStateOf(true)
    var movementQty by mutableStateOf("")
    var movementNote by mutableStateOf("")
    /**
     * 本次**进货价**（只对入库有意义，选填）。
     *
     * 用户 2026-09-19：「包括进货的时候也要输入成本价，因为可能这个时间的进货和
     * 那个时间进货的成本价是不一样的」。填了会把商品成本价一起更新（见请求体注释）。
     */
    var movementCost by mutableStateOf("")

    init {
        load()
    }

    fun load() {
        loading = summary.isEmpty()
        error = null
        viewModelScope.launch {
            try {
                summary = container.repo.inventorySummary()
                applyMovements(container.repo.inventoryMovementsPage(dateFrom = movDateFrom, dateTo = movDateTo))
                products = container.repo.products()
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                loading = false
            }
        }
    }

    fun refresh() = load()

    /** 流水只有一个赋值口：截断位/上限跟着一起更新，免得两条加载路径分叉（一处漏判＝又静默消失） */
    private fun applyMovements(page: PageRows<InventoryMovementDto>) {
        movements = page.rows
        movementsTruncated = page.meta.hasMore
        movementsLimit = page.meta.limit
    }

    fun applyMovFilter(from: String?, to: String?) {
        movDateFrom = from
        movDateTo = to
        viewModelScope.launch {
            try {
                applyMovements(container.repo.inventoryMovementsPage(dateFrom = movDateFrom, dateTo = movDateTo))
            } catch (e: Exception) {
                error = toApiException(e).message
            }
        }
    }

    fun openMovement(p: ProductDto, inbound: Boolean) {
        movementProduct = p
        movementInbound = inbound
        movementQty = ""
        movementNote = ""
        movementCost = ""
        showMovementDialog = true
    }

    fun confirmMovement() {
        val p = movementProduct ?: return
        val qty = movementQty.toIntOrNull()
        if (qty == null || qty <= 0) {
            error = "请输入大于 0 的整数数量"
            return
        }
        // 进货价只在入库时看：出库带着它，后端会 400（"进货价只在入库时填"）
        val cost = if (movementInbound) movementCost.trim().ifBlank { null } else null
        if (cost != null && cost.toDoubleOrNull() == null) {
            error = "进货价请填数字（最多四位小数）"
            return
        }
        acting = true
        error = null
        viewModelScope.launch {
            try {
                val change = if (movementInbound) qty else -qty
                container.repo.createMovement(
                    InventoryMovementCreateRequest(p.id, change, movementNote.trim(), cost)
                )
                actionResult = (if (movementInbound) "入库 " else "出库 ") + qty + " " + p.name +
                    if (cost != null) "（进货价 ¥" + com.tapmoay.sorders.util.trimMoneyZeros(cost) + " 已更新成本价）" else ""
                showMovementDialog = false
                load()
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                acting = false
            }
        }
    }
}
