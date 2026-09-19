package com.tapmoay.sorders.ui.shipper

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.data.remote.dto.LedgerEntryDto
import com.tapmoay.sorders.data.repo.toApiException
import com.tapmoay.sorders.util.moneyToDouble
import kotlinx.coroutines.launch
import java.time.LocalDate

class ShipperLedgerViewModel(private val container: AppContainer) : ViewModel() {

    var entries by mutableStateOf<List<LedgerEntryDto>>(emptyList())

    /**
     * 这一页不是全部（响应头 `X-Truncated`，走 `AppRepository.pageMeta()`）。
     *
     * `total()` 与 `chartSeries` 都是拿 [entries] 在客户端算的，而"不传日期"是本页初始状态
     * （后端走全量路径、缺省只回最近 1000 条）——不说的话「当前范围内合计」就是**只含可见行的错钱数**。
     */
    var entriesTruncated by mutableStateOf(false)
        private set

    /** 本次服务器上限（`X-Result-Limit`）；null = 老后端没回报，界面不许自己编一个数。 */
    var entriesLimit by mutableStateOf<Int?>(null)
        private set
    var loading by mutableStateOf(false)
    var error by mutableStateOf<String?>(null)
    var rangeFrom by mutableStateOf<String?>(null)
    var rangeTo by mutableStateOf<String?>(null)

    // 时间导航（按日/按周/按月）+ 图表
    var chartMode by mutableStateOf("day")
    var chartAnchor by mutableStateOf(LocalDate.now().toString())
    var chartType by mutableStateOf("line")

    // ===== 明细里那一单可以**就地展开**（用户 2026-09-19：
    //       「账本相近的明细…订单是可以展开进行查看的…**包括货主的账本啊，都一样的**」）=====
    //
    // 与派单员账本共用 `ui/common/OrderPeek.kt` 那一份渲染：各写一遍必然走散。
    // 原来点一行是**跳到订单详情页** —— 跳过去再回来，时间范围/滚动位置全没了，
    // 想连着核几笔就得来回跳。跳转那条路仍然留着（展开块右上角「打开订单」）。
    var expandedOrderId by mutableStateOf<Long?>(null)
    var expandedOrder by mutableStateOf<com.tapmoay.sorders.data.remote.dto.OrderDto?>(null)
    var expandedOrderLoading by mutableStateOf(false)

    fun toggleOrderDetail(id: Long) {
        if (expandedOrderId == id) {
            expandedOrderId = null
            expandedOrder = null
            return
        }
        expandedOrderId = id
        expandedOrder = null
        expandedOrderLoading = true
        viewModelScope.launch {
            try {
                expandedOrder = container.repo.order(id)
            } catch (e: Exception) {
                // 拉失败要**说出来**，不能显示成"这一单没有内容"（两句是完全不同的结论）
                error = toApiException(e).message
                expandedOrderId = null
            } finally {
                expandedOrderLoading = false
            }
        }
    }

    init {
        load()
        // 订单送达自动记账后实时刷新账本
        viewModelScope.launch {
            container.realtimeHub.refreshLedger.collect { load() }
        }
    }

    fun total(): Double = entries.sumOf { moneyToDouble(it.total) }

    val periodText: String get() {
        val d = LocalDate.parse(chartAnchor)
        val (start, end) = when (chartMode) {
            "week" -> d.minusDays((d.dayOfWeek.value - 1).toLong()) to d.plusDays((7 - d.dayOfWeek.value).toLong())
            "month" -> d.withDayOfMonth(1) to d.withDayOfMonth(d.lengthOfMonth())
            else -> d to d
        }
        return start.toString() + " 00:00:00~" + end.toString() + " 23:59:59"
    }

    fun applyMode(mode: String) {
        chartMode = mode
        val d = LocalDate.parse(chartAnchor)
        val (from, to) = when (mode) {
            "week" -> (d.minusDays((d.dayOfWeek.value - 1).toLong()).toString() to d.plusDays((7 - d.dayOfWeek.value).toLong()).toString())
            "month" -> (d.withDayOfMonth(1).toString() to d.withDayOfMonth(d.lengthOfMonth()).toString())
            else -> (d.toString() to d.toString())
        }
        applyRange(from, to)
    }

    fun setAnchor(anchor: String) {
        chartAnchor = anchor
        applyMode(chartMode)
    }

    /** 按日汇总（图表 x 轴） */
    val chartSeries: List<Pair<String, Double>> get() {
        val map = LinkedHashMap<String, Double>()
        entries.forEach { e ->
            val key = (e.entryDate ?: "").take(10)
            if (key.isNotBlank()) map[key] = (map[key] ?: 0.0) + moneyToDouble(e.total)
        }
        return map.entries.map { it.key to it.value }
    }

    fun applyRange(from: String?, to: String?) {
        rangeFrom = from
        rangeTo = to
        load()
    }

    fun load() {
        loading = entries.isEmpty()
        error = null
        viewModelScope.launch {
            try {
                val page = container.repo.ledgerEntries(from = rangeFrom, to = rangeTo)
                entries = page.rows
                entriesTruncated = page.meta.hasMore
                entriesLimit = page.meta.limit
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                loading = false
            }
        }
    }
}