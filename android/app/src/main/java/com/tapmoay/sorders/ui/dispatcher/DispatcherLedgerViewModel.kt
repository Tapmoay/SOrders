package com.tapmoay.sorders.ui.dispatcher

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.data.remote.dto.FreightSettlementGroupDto
import com.tapmoay.sorders.data.remote.dto.LedgerAccountOut
import com.tapmoay.sorders.data.remote.dto.LedgerCreateRequest
import com.tapmoay.sorders.data.remote.dto.LedgerEntryDto
import com.tapmoay.sorders.data.repo.PageMeta
import com.tapmoay.sorders.data.repo.toApiException
import com.tapmoay.sorders.util.moneyToDouble
import kotlinx.coroutines.launch
import java.time.LocalDate

/**
 * 派单员账本（信息优先：日期范围流水 + 汇总金额 + 手动记账）。
 * 查询/记账全部复用 ledger API 与通用日期解析，不写死业务。
 */
class DispatcherLedgerViewModel(private val container: AppContainer) : ViewModel() {

    var entries by mutableStateOf<List<LedgerEntryDto>>(emptyList())

    /**
     * 这一页不是全部（响应头 `X-Truncated`，走 `AppRepository.pageMeta()`）。
     *
     * ⚠️ 这一页**尤其**要说：`total()` 与 `chartSeries` 都是拿 [entries] 在客户端算的，
     *    而"不传日期"正是本页的初始状态（后端走全量路径，缺省只回最近 1000 条）——
     *    不说的话「当前范围内合计」就是在报一个**只含可见行的错钱数**。
     */
    var entriesTruncated by mutableStateOf(false)
        private set

    /** 本次服务器上限（`X-Result-Limit`）；null = 老后端没回报，界面不许自己编一个数。 */
    var entriesLimit by mutableStateOf<Int?>(null)
        private set
    var loading by mutableStateOf(false)
    /**
     * **动作**失败（记账、改流水被后端拒绝…）：提示条弹一次就该消失。
     */
    var error by mutableStateOf<String?>(null)
    /**
     * **加载**失败：要留在页面上（配合整页 ErrorView + 重试），**不能**被提示条消费掉。
     *
     * 为什么要拆（2026-09-18）：原来共用一个 `error`。提示条是"消费即清"的语义，
     * 不拆的话加载失败会先弹一次提示条、把 error 清掉，**整页「加载失败 + 重试」当场消失**，
     * 用户掉进一个空列表而且没法重试。两种错误的生命周期本来就不一样。
     */
    var loadError by mutableStateOf<String?>(null)
    var acting by mutableStateOf(false)
    var actionResult by mutableStateOf<String?>(null)
    var rangeFrom by mutableStateOf<String?>(null)
    var rangeTo by mutableStateOf<String?>(null)

    // ===== 账本分类：0=订单账 1=司机账 2=货主账 3=批发商账 =====
    var tab by mutableStateOf(0)
    var driverAccounts by mutableStateOf<List<FreightSettlementGroupDto>>(emptyList())
    var shipperAccounts by mutableStateOf<List<LedgerAccountOut>>(emptyList())
    var memberAccounts by mutableStateOf<List<LedgerAccountOut>>(emptyList())
    var accountsLoading by mutableStateOf(false)
    var expandedDriver by mutableStateOf<Long?>(null)
    var expandedAccount by mutableStateOf<String?>(null)
    var accountEntries by mutableStateOf<Map<String, List<LedgerEntryDto>>>(emptyMap())

    /**
     * 逐账户明细的截断位（key → 本次上限）。**不能只留 [accountEntries]**：
     * 一个货主的全量流水同样超过一页，卡上写着"服务端 N 笔"、展开却只有 1000 条 ——
     * 那正是"看不到 ≠ 没有"的老坑（2026-09-19）。
     */
    var accountEntriesMeta by mutableStateOf<Map<String, PageMeta>>(emptyMap())
    var accountEntriesLoading by mutableStateOf(false)

    val periodStart: String get() = _periodRange().first
    val periodEnd: String get() = _periodRange().second

    private fun _periodRange(): Pair<String, String> {
        val d = LocalDate.parse(chartAnchor)
        return when (chartMode) {
            "week" -> (d.minusDays((d.dayOfWeek.value - 1).toLong()).toString() to d.plusDays((7 - d.dayOfWeek.value).toLong()).toString())
            "month" -> (d.withDayOfMonth(1).toString() to d.withDayOfMonth(d.lengthOfMonth()).toString())
            else -> (d.toString() to d.toString())
        }
    }

    fun selectTab(i: Int) {
        tab = i
        if (i != 0) loadAccounts()
    }

    /** 司机账/货主账/批发商账：按当前时间范围拉取账户汇总 */
    fun loadAccounts() {
        accountsLoading = true
        loadError = null
        viewModelScope.launch {
            try {
                val from = periodStart
                val to = periodEnd
                if (tab == 1) {
                    driverAccounts = container.repo.freightSettlementRange(from + " 00:00:00", to + " 23:59:59").groups
                } else {
                    if (tab == 2) shipperAccounts = container.repo.ledgerAccounts(from, to, "shipper")
                    if (tab == 3) memberAccounts = container.repo.ledgerAccounts(from, to, "member")
                }
            } catch (e: Exception) {
                loadError = toApiException(e).message
            } finally {
                accountsLoading = false
            }
        }
    }

    fun toggleDriver(id: Long) {
        expandedDriver = if (expandedDriver == id) null else id
    }

    /** 展开账户明细（货主/批发商）：按账户拉取其范围内流水 */
    fun toggleAccount(key: String) {
        if (expandedAccount == key) {
            expandedAccount = null
            return
        }
        expandedAccount = key
        if (accountEntries[key] != null) return
        accountEntriesLoading = true
        viewModelScope.launch {
            try {
                val (id, name) = key.split("|", limit = 2)
                val page = if (id == "u") {
                    container.repo.ledgerEntries(shipperId = name.toLongOrNull(), from = periodStart, to = periodEnd)
                } else {
                    container.repo.ledgerEntries(tempShipperName = name, from = periodStart, to = periodEnd)
                }
                accountEntries = accountEntries + (key to page.rows)
                accountEntriesMeta = accountEntriesMeta + (key to page.meta)
            } catch (e: Exception) {
                loadError = toApiException(e).message
            } finally {
                accountEntriesLoading = false
            }
        }
    }

    var showCreate by mutableStateOf(false)
    var draftShipperName by mutableStateOf("")
    var draftProduct by mutableStateOf("")
    var draftQty by mutableStateOf("")
    var draftPrice by mutableStateOf("")
    var draftDate by mutableStateOf(LocalDate.now().toString())
    var draftNote by mutableStateOf("")
    var deleteTarget by mutableStateOf<LedgerEntryDto?>(null)

    init {
        load()
        // 账本变动（送达自动记账/手动记账端联动）实时刷新
        viewModelScope.launch {
            container.realtimeHub.refreshLedger.collect { load() }
        }
    }

    fun total(): Double = entries.sumOf { moneyToDouble(it.total) }

    fun applyRange(from: String?, to: String?) {
        rangeFrom = from
        rangeTo = to
        load()
    }

    // 时间导航（按日/按周/按月）+ 图表
    var chartMode by mutableStateOf("day")
    var chartAnchor by mutableStateOf(LocalDate.now().toString())
    var chartType by mutableStateOf("line")

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
        if (tab != 0) loadAccounts()
    }

    fun setAnchor(anchor: String) {
        chartAnchor = anchor
        applyMode(chartMode)  // applyMode 内部会刷新非订单账
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

    fun openCreate() {
        draftShipperName = ""
        draftProduct = ""
        draftQty = ""
        draftPrice = ""
        draftDate = LocalDate.now().toString()
        draftNote = ""
        showCreate = true
    }

    fun create() {
        val qty = draftQty.toIntOrNull()
        val price = draftPrice.toDoubleOrNull()
        if (draftProduct.isBlank()) {
            error = "请填写商品名称"
            return
        }
        if (qty == null || qty <= 0) {
            error = "请填写正确的数量"
            return
        }
        if (price == null || price < 0) {
            error = "请填写正确的单价"
            return
        }
        acting = true
        error = null
        viewModelScope.launch {
            try {
                container.repo.createLedger(
                    LedgerCreateRequest(
                        tempShipperName = draftShipperName.trim().ifBlank { null },
                        entryDate = draftDate.trim(),
                        productName = draftProduct.trim(),
                        quantity = qty,
                        unitPrice = price.toString(),
                        total = (qty * price).toString(),
                        source = "manual",
                        note = draftNote.trim(),
                    )
                )
                actionResult = "已记一笔账"
                showCreate = false
                load()
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                acting = false
            }
        }
    }

    fun confirmDelete() {
        val t = deleteTarget ?: return
        acting = true
        error = null
        viewModelScope.launch {
            try {
                container.repo.deleteLedger(t.id)
                actionResult = "已删除该笔账目"
                deleteTarget = null
                load()
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                acting = false
            }
        }
    }
}