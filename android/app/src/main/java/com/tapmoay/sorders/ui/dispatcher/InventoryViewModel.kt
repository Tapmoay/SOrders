package com.tapmoay.sorders.ui.dispatcher

import androidx.compose.runtime.*
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.data.remote.api.INVENTORY_MOVEMENT_PAGE_LIMIT
import com.tapmoay.sorders.data.remote.dto.InventoryMovementCreateRequest
import com.tapmoay.sorders.data.remote.dto.InventoryMovementDto
import com.tapmoay.sorders.data.remote.dto.InventorySummaryItemDto
import com.tapmoay.sorders.data.remote.dto.ProductDto
import com.tapmoay.sorders.data.repo.toApiException
import kotlinx.coroutines.launch

class InventoryViewModel(private val container: AppContainer) : ViewModel() {

    var summary by mutableStateOf<List<InventorySummaryItemDto>>(emptyList())
    var movements by mutableStateOf<List<InventoryMovementDto>>(emptyList())

    /**
     * 流水"拿满一页"＝更早的还有，界面必须**说出来**。
     *
     * ⛔ 后端这个端点不回报截断（没有 `X-Truncated`），所以判据只能是"这一页是满的"。
     *    不说出来的后果是"更早的流水在 App 里静默消失"——账实不符时没人知道是没录还是没显示。
     */
    var movementsTruncated by mutableStateOf(false)
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

    init {
        load()
    }

    fun load() {
        loading = summary.isEmpty()
        error = null
        viewModelScope.launch {
            try {
                summary = container.repo.inventorySummary()
                applyMovements(container.repo.inventoryMovements(dateFrom = movDateFrom, dateTo = movDateTo))
                products = container.repo.products()
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                loading = false
            }
        }
    }

    fun refresh() = load()

    /** 流水只有一个赋值口：截断判据跟着一起更新，免得两条加载路径分叉（一处漏判＝又静默消失） */
    private fun applyMovements(rows: List<InventoryMovementDto>) {
        movements = rows
        movementsTruncated = rows.size >= INVENTORY_MOVEMENT_PAGE_LIMIT
    }

    fun applyMovFilter(from: String?, to: String?) {
        movDateFrom = from
        movDateTo = to
        viewModelScope.launch {
            try {
                applyMovements(container.repo.inventoryMovements(dateFrom = movDateFrom, dateTo = movDateTo))
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
        showMovementDialog = true
    }

    fun confirmMovement() {
        val p = movementProduct ?: return
        val qty = movementQty.toIntOrNull()
        if (qty == null || qty <= 0) {
            error = "请输入大于 0 的整数数量"
            return
        }
        acting = true
        error = null
        viewModelScope.launch {
            try {
                val change = if (movementInbound) qty else -qty
                container.repo.createMovement(
                    InventoryMovementCreateRequest(p.id, change, movementNote.trim())
                )
                actionResult = (if (movementInbound) "入库 " else "出库 ") + qty + " " + p.name
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
