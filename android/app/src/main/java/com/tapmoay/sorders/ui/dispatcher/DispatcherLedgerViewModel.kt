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

    // ============================================================ 账户的"自由选择"
    //
    // 用户 2026-09-19：「一个很严重的问题，比如说批发商他只能看到合计的，但如果我想看
    // **单个**的呢？或者我想看 **2 个**人的呢？这要有个**自由选择**，而且页面也非常的反人性」。
    //
    // 所以：账户列表上面加**搜索框 + 多选**，选中的账户单独算合计。
    //   · 一个都不选 = 全部账户（原来的样子，不改默认行为）
    //   · 选 1 个 = 只看那一个   · 选 2 个 = 看那两个
    // 选中的**合计**单独算一行（"我选的这几个一共多少钱、几笔"）——
    // 原来只有每张卡各自的钱，要自己心算相加，这正是"反人性"的地方。

    /** 按名字搜账户（批发商/货主可能有几十个，滚动找人是这一页最烦的事）。 */
    var accountQuery by mutableStateOf("")

    /** 选中的账户 key 集合（`u|<id>` / `t|<名字>`）；**空 = 全部**。 */
    var selectedAccounts by mutableStateOf<Set<String>>(emptySet())

    fun toggleAccountSelected(key: String) {
        selectedAccounts = if (key in selectedAccounts) selectedAccounts - key else selectedAccounts + key
    }

    fun clearAccountSelection() {
        selectedAccounts = emptySet()
    }

    /** 当前 tab 的账户（搜过的）。tab 2=货主账 3=批发商账。 */
    fun accountsForTab(): List<LedgerAccountOut> {
        val all = if (tab == 3) memberAccounts else shipperAccounts
        val kw = accountQuery.trim()
        return if (kw.isEmpty()) all else all.filter { it.name.contains(kw, ignoreCase = true) }
    }

    /**
     * 选中账户的**合计**（钱 + 笔数）。一个都没选 = 全部账户的合计。
     *
     * ⚠️ 笔数取服务端的 `count`（那一栏是**全量**笔数），不是本地明细的行数 ——
     *    明细是分页的，拿它当"一共几笔"会少报。
     */
    fun selectedSummary(): Pair<Double, Int> {
        val all = if (tab == 3) memberAccounts else shipperAccounts
        val picked = if (selectedAccounts.isEmpty()) all else all.filter { accountKey(it) in selectedAccounts }
        return picked.sumOf { moneyToDouble(it.total) } to picked.sumOf { it.count }
    }

    /** 一个账户的 key（与 [toggleAccount] 用的是同一套拼法，**不许各写一份**）。 */
    fun accountKey(a: LedgerAccountOut): String =
        if (a.id != null) "u|${a.id}" else "t|${a.tempName.orEmpty()}"

    // 司机账同样是"自由选择"（用户：「其他其他的都一样」）：司机可能几十个，同样要能搜、能多选。
    // key 直接用 driver_id（司机账本来就是这个维度，不存在"跨 tab 同名不同人"的问题）。
    var driverQuery by mutableStateOf("")
    var selectedDrivers by mutableStateOf<Set<Long>>(emptySet())

    fun toggleDriverSelected(id: Long) {
        selectedDrivers = if (id in selectedDrivers) selectedDrivers - id else selectedDrivers + id
    }

    fun clearDriverSelection() {
        selectedDrivers = emptySet()
    }

    /** 当前时间范围里的司机（搜过的）。 */
    fun driversForTab(): List<FreightSettlementGroupDto> {
        val kw = driverQuery.trim()
        return if (kw.isEmpty()) driverAccounts
        else driverAccounts.filter { it.driverName.contains(kw, ignoreCase = true) }
    }

    /** 选中司机的合计（钱 + 单数）；一个都没选 = 全部。 */
    fun driverSelectedSummary(): Triple<Double, Int, Int> {
        val picked = if (selectedDrivers.isEmpty()) driverAccounts
        else driverAccounts.filter { it.driverId in selectedDrivers }
        return Triple(
            picked.sumOf { it.total },
            picked.sumOf { it.count },
            picked.size,
        )
    }

    // ============================================================ 明细里的订单可以展开
    //
    // 用户 2026-09-19：「账本相近的明细，比如他这个账本对应什么订单，
    // **订单是可以展开进行查看的**」。
    //
    // 原来点一行是**跳到订单详情页**——回来之后筛选/展开状态全没了，
    // 想连着核几笔就得来回跳。现在就地展开：单号、状态、货主、地址、商品行、金额。

    /** 就地展开的那条订单（null = 没展开）。 */
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
        // 换 tab 就把"选中的账户"清掉：key 是跨 tab 混用的（`u|id` 在货主账与批发商账里
        // 指的是不同的人），带过去会出现"选了 2 个、列表里一个都没高亮"的鬼状态。
        selectedAccounts = emptySet()
        accountQuery = ""
        selectedDrivers = emptySet()
        driverQuery = ""
        expandedOrderId = null
        expandedOrder = null
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