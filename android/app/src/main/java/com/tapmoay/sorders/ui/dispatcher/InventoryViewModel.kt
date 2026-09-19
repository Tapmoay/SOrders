package com.tapmoay.sorders.ui.dispatcher

import androidx.compose.runtime.*
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.data.remote.dto.InventoryMovementCreateRequest
import com.tapmoay.sorders.data.remote.dto.InventoryMovementDto
import com.tapmoay.sorders.data.remote.dto.InventorySummaryItemDto
import com.tapmoay.sorders.data.remote.dto.ProductCategoryDto
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

    /**
     * 商品分类名册（**顺序由它定**）。
     *
     * 用户 2026-09-19：「库存管理也是跟商品管理一样的，左边是分类、右边是商品」——
     * 左侧导航条必须与商品管理/选品页**同一套顺序与同一套判据**，
     * 否则同一件商品在三个页面会落在不同位置（甚至"这一页有、那一页没有"）。
     * 分类本身随 `/inventory/summary` 的行下发（见 `InventorySummaryItemDto.category`），
     * 这里拉的只是**顺序**。
     *
     * ⚠️ 这里原来拉的是**全量商品列表**（`repo.products()`），只为了
     *    `firstOrNull { it.id == s.productId }` 把库存概览的一行"翻译"成 `ProductDto`
     *    再打开出入库弹窗 —— 而那一行本来就带着 id/名称/库存。
     *    多一次请求不说，商品不在列表里时那个按钮**点了什么都不发生**（静默）。
     *    现在弹窗直接吃概览行，省掉的这次请求正好用来取名册顺序。
     */
    var categories by mutableStateOf<List<ProductCategoryDto>>(emptyList())

    /** 按名称搜索（用户要求："通过搜索名称来搜索商品，来盘查实时库存是怎样的"）。 */
    var query by mutableStateOf("")

    var loading by mutableStateOf(false)
    var error by mutableStateOf<String?>(null)
    var acting by mutableStateOf(false)
    var actionResult by mutableStateOf<String?>(null)
    // 流水日期筛选
    var movDateFrom by mutableStateOf<String?>(null)
    var movDateTo by mutableStateOf<String?>(null)

    // 出入库弹窗
    var showMovementDialog by mutableStateOf(false)

    /** 弹窗针对的那一行库存概览（不是 `ProductDto` —— 见 [categories] 的注释）。 */
    var movementProduct by mutableStateOf<InventorySummaryItemDto?>(null)
    var movementInbound by mutableStateOf(true)
    var movementQty by mutableStateOf("")
    var movementNote by mutableStateOf("")
    /**
     * 本次**进货价**（只对入库有意义，选填）。
     *
     * 用户 2026-09-19：「包括进货的时候也要输入成本价，因为可能这个时间的进货和
     * 那个时间进货的成本价是不一样的」。填了会做两件事：记在这条流水上
     * （毛利按入库流水的平均进货价算）、并把商品的成本价也更新成它。
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
                // 名册顺序只是为了左侧导航条好看/一致：取不到就退回"按商品数排"，
                // **不许**因为它失败就让整页报错（库存才是这一页的正事）
                categories = try {
                    container.repo.productCategories()
                } catch (_: Exception) {
                    emptyList()
                }
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

    fun openMovement(s: InventorySummaryItemDto, inbound: Boolean) {
        movementProduct = s
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
                    InventoryMovementCreateRequest(p.productId, change, movementNote.trim(), cost)
                )
                actionResult = (if (movementInbound) "入库 " else "出库 ") + qty + " " + p.productName +
                    if (cost != null) "（进货价 ¥" + com.tapmoay.sorders.util.trimMoneyZeros(cost) + " 已记进这批货）" else ""
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
