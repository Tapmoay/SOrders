package com.tapmoay.sorders.ui.dispatcher

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.core.UserSearch
import com.tapmoay.sorders.data.remote.dto.FreightSettlementGroupDto
import com.tapmoay.sorders.data.remote.dto.FreightSettlementOrderDto
import com.tapmoay.sorders.data.remote.dto.LedgerAccountOut
import com.tapmoay.sorders.data.remote.dto.LedgerCreateRequest
import com.tapmoay.sorders.data.remote.dto.LedgerEntryDto
import com.tapmoay.sorders.data.repo.PageMeta
import com.tapmoay.sorders.data.repo.toApiException
import com.tapmoay.sorders.ui.common.DatePresets
import com.tapmoay.sorders.util.moneyToDouble
import kotlinx.coroutines.launch
import java.time.LocalDate

/**
 * 账本仪表盘的一行 —— **司机账 / 货主账 / 批发商账共用同一个视图模型**。
 *
 * 三种账的数据源不同（`/freight-settlement` 的 group vs `/ledger/accounts` 的账户汇总），
 * 但**仪表盘要看的四件事是同一件**：这是谁（名字）+ 怎么找到他（手机号）+
 * 他有几笔 + 一共多少钱。上一版把这一层拆成两套卡片 + 两套挑选器，
 * 结果是"同一个需求改两处、改一处漏一处"。
 */
data class LedgerAccountRow(
    /** `d|<司机 id>` / `u|<货主 id>` / `t|<临时货主名>`（跨 tab 不通用，换 tab 会清）。 */
    val key: String,
    /** 名字（**原样**，可能是空串 —— 空名要靠手机号搜，所以不在这里兜底成「货主」）。 */
    val title: String,
    /** 手机号（临时货主为 null）。同名不同人**只能靠它分开**。 */
    val phone: String?,
    /** 这个账号还能不能登录（停用/已删除）。 */
    val inactive: Boolean,
    /** 笔数/单数 —— 取**服务端**的全量数，不是本地明细行数（明细是分页的）。 */
    val count: Int,
    /** 「笔」/「单」。 */
    val countUnit: String,
    val total: Double,
)

/** 仪表盘上的三个数（**当前搜索过滤之后**的集合）。 */
data class LedgerDashboard(val accounts: Int, val count: Int, val total: Double)

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

    // ⚠️ 下面这几个**必须声明在 `init { applyPreset(...) }` 之前**：Kotlin 的属性初始化与
    //    init 块按**书写顺序**执行，写在 init 之后的话，init 里那句 `preset = …` 会抛
    //    `MutableState.setValue … on a null object reference` —— **打开这一页就崩**
    //    （2026-09-20 真机抓到的就是这一次）。判据：`_tools/qa/_check_vm_state_before_init.py`。

    /** 当前选中的日期档位（[DatePresets.ROW] 里的一档，或「自定义」）。 */
    var preset by mutableStateOf(DatePresets.THIS_MONTH)
        private set

    /** 「自定义」那一档的两端（用户在日期弹层里选的）。 */
    var customFrom by mutableStateOf<String?>(null)
        private set
    var customTo by mutableStateOf<String?>(null)
        private set

    /** 图表类型：`line` 折线 / `bar` 条形 / `pie` 扇形。 */
    var chartType by mutableStateOf(CHART_LINE)

    // ===== 账本分类：0=订单账 1=司机账 2=货主账 3=批发商账 =====
    var tab by mutableStateOf(0)
    var driverAccounts by mutableStateOf<List<FreightSettlementGroupDto>>(emptyList())
    var shipperAccounts by mutableStateOf<List<LedgerAccountOut>>(emptyList())
    var memberAccounts by mutableStateOf<List<LedgerAccountOut>>(emptyList())
    var accountsLoading by mutableStateOf(false)

    /** 就地展开的那一行（账户 key；null = 没展开）。三个 tab 共用这一个。 */
    var expandedKey by mutableStateOf<String?>(null)

    /** 货主/批发商那一行的流水（**要另取**；司机账的明细已经跟在列表响应里）。 */
    var accountEntries by mutableStateOf<Map<String, List<LedgerEntryDto>>>(emptyMap())

    /**
     * 逐账户明细的截断位（key → 本次上限）。**不能只留 [accountEntries]**：
     * 一个货主的全量流水同样超过一页，卡上写着"服务端 N 笔"、展开却只有 1000 条 ——
     * 那正是"看不到 ≠ 没有"的老坑（2026-09-19）。
     */
    var accountEntriesMeta by mutableStateOf<Map<String, PageMeta>>(emptyMap())
    var accountEntriesLoading by mutableStateOf(false)

    // ============================================================ 账本仪表盘（不是"挑选器"）
    //
    // 用户 2026-09-19 第二次拍板（推翻了上一版的"搜索 + 多选 chip 墙"）：
    // 「你这样子改不对啊…**假如客户非常多司机非常多，那用户要是一个一个去选的话，
    //   那要有多麻烦啊**。其实我觉得像这个账本啊，**所有的账本你可以一个仪表盘的思维
    //   进行去构建**」。
    //
    // 所以上一版那套被**删掉**了，两个理由：
    //   ① 那一版的交互是"先在一堆 chip 里把人一个个点出来、再看下面的列表" ——
    //      账户一多，"找到我要点的那几个"比看账本身还花时间（这正是用户说的"麻烦"）；
    //   ② chip 上写的名字+金额，和下面列表里的名字+金额**是同一份信息**（重复一遍），
    //      而重复的信息放在两处，就一定会出现"两边对不上"的困惑。
    //
    // 现在这一套：
    //   · **一屏看完所有账户各自的数**（仪表盘）—— 不需要先选，默认就是全量；
    //   · 一个搜索框把范围收窄（姓名 / 手机号 / **手机号后 4 位**，规则见 `core/UserSearch`）；
    //   · **收窄之后的合计**写在仪表盘上（"这两家一共多少"就是这么看的，不用勾选）；
    //   · 点账户行**就地展开**它自己的流水。
    //
    // ⚠️ 搜索是**本地**过滤：`/ledger/accounts` 与 `/freight-settlement` 都是**一次回全量**
    //    （没有分页、没有 500 上限），再走服务端只是每次打字多打一次后端。
    //    名册页（`/users` 一页最多 500 条）就**必须**走服务端 `?q=`，见 `UsersManageViewModel`。

    /** 搜索词（三个 tab 共用一个；换 tab 会清）。 */
    var query by mutableStateOf("")

    /** 当前 tab 的**全部**账户行（顺序 = 服务端顺序，已按金额倒序）。 */
    fun accountRows(): List<LedgerAccountRow> = when (tab) {
        1 -> driverAccounts.map {
            LedgerAccountRow(
                key = "d|" + it.driverId,
                title = it.driverName,
                phone = it.driverPhone,
                inactive = !it.driverActive,
                count = it.count,
                countUnit = "单",
                total = it.total,
            )
        }
        else -> {
            val isMember = tab == 3
            (if (isMember) memberAccounts else shipperAccounts).map {
                LedgerAccountRow(
                    key = accountKey(it),
                    title = it.name,
                    phone = it.phone,
                    inactive = !it.isActive,
                    count = it.count,
                    countUnit = "笔",
                    total = moneyToDouble(it.total),
                )
            }
        }
    }

    /** 搜索过滤之后要显示的行。 */
    fun visibleAccountRows(): List<LedgerAccountRow> =
        UserSearch.filter(accountRows(), query, { it.title }, { it.phone })

    /**
     * 仪表盘三个数：**过滤之后**的账户数 / 笔数 / 金额。
     *
     * ⚠️ 笔数取服务端的 `count`（那一栏是**全量**笔数），不是本地明细的行数 ——
     *    明细是分页的，拿它当"一共几笔"会少报。
     */
    fun dashboard(): LedgerDashboard {
        val rows = visibleAccountRows()
        return LedgerDashboard(rows.size, rows.sumOf { it.count }, rows.sumOf { it.total })
    }

    /** 一个账户的 key（与 [accountRows] 用的是同一套拼法，**不许各写一份**）。 */
    fun accountKey(a: LedgerAccountOut): String =
        if (a.id != null) "u|${a.id}" else "t|${a.tempName.orEmpty()}"

    /** 司机账那一行自己在响应里带的订单明细（不用再请求）。 */
    fun driverOrdersOf(key: String): List<FreightSettlementOrderDto> =
        driverAccounts.firstOrNull { "d|" + it.driverId == key }?.orders.orEmpty()

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

    val periodStart: String? get() = rangeFrom
    val periodEnd: String? get() = rangeTo

    fun selectTab(i: Int) {
        tab = i
        // 换 tab 就把搜索词与展开态清掉：key 是跨 tab 混用的（`u|id` 在货主账与批发商账里
        // 指的是不同的人），带过去会出现"搜了 2 个、列表里一个都没高亮"的鬼状态。
        query = ""
        expandedKey = null
        expandedOrderId = null
        expandedOrder = null
        // 新档位不支持当前图（比如从司机账带着"折线"切到货主账）→ 落到它支持的第一个，
        // 否则切换条上会出现一个"选中了但画不出来"的档
        if (chartType !in chartTypes()) chartType = chartTypes().first()
        if (i != 0) loadAccounts()
    }

    /** 司机账/货主账/批发商账：按当前时间范围拉取账户汇总 */
    fun loadAccounts() {
        accountsLoading = true
        loadError = null
        // ⛔ 时间范围一变，**已展开的流水就过期了**：账户卡上的笔数/金额换了新时段、
        //    展开的明细还是上一段的（而且 `toggleRow` 见缓存非空就直接返回，不会重取）——
        //    界面上两个数对不上，谁都不报错（2026-09-19 修）。
        accountEntries = emptyMap()
        accountEntriesMeta = emptyMap()
        expandedKey = null
        viewModelScope.launch {
            try {
                if (tab == 1) {
                    // ⚠️ 结算接口**必须**给 from/to（不给直接 400），所以「全部」那一档用一对
                    //    宽到没有实际边界的端点：业务数据不可能早于 2000 年，也不会有 2099 年后的单。
                    val f = rangeFrom ?: WIDE_FROM
                    val t = rangeTo ?: WIDE_TO
                    driverAccounts = container.repo.freightSettlementRange(f + " 00:00:00", t + " 23:59:59").groups
                } else {
                    // 账户汇总接口的 from/to 可以省：省掉就是**真·全部**（不传一个假区间进去）
                    if (tab == 2) shipperAccounts = container.repo.ledgerAccounts(rangeFrom, rangeTo, "shipper")
                    if (tab == 3) memberAccounts = container.repo.ledgerAccounts(rangeFrom, rangeTo, "member")
                }
            } catch (e: Exception) {
                loadError = toApiException(e).message
            } finally {
                accountsLoading = false
            }
        }
    }

    /**
     * 展开/收起一个账户的明细。
     *
     * ⚠️ 司机账**不用再取数**：`/freight-settlement` 每个 group 自带 `orders`；
     *    货主/批发商账的流水要按账户另取一次（取过就缓存，同一时段内不重复请求）。
     */
    fun toggleRow(key: String) {
        if (expandedKey == key) {
            expandedKey = null
            return
        }
        expandedKey = key
        if (tab == 1) return
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
        // 默认档位 = **本月**（不是"今天"）：账本第一屏看一天，几乎什么都没有，
        // 而"这个月一共多少"才是打开账本要问的第一句话。
        applyPreset(DatePresets.THIS_MONTH)
        // 账本变动（送达自动记账/手动记账端联动）实时刷新
        viewModelScope.launch {
            container.realtimeHub.refreshLedger.collect { load() }
        }
    }

    private companion object {
        /**
         * 「全部」那一档给**结算接口**的边界（见 [loadAccounts]）。
         * 账户汇总接口不需要它们 —— 那边省掉 from/to 就是真的不加条件。
         */
        const val WIDE_FROM = "2000-01-01"
        const val WIDE_TO = "2099-12-31"
    }

    fun total(): Double = entries.sumOf { moneyToDouble(it.total) }

    fun applyRange(from: String?, to: String?) {
        rangeFrom = from
        rangeTo = to
        load()
    }

    // 日期档位**不在这里算**：档位与它们的区间在 `ui/common/DatePresets`（唯一一份实现），
    // 本页只把选中的那一档翻成 from/to。自己再写一遍 `when("本月")`，
    // 就会出现"账本页的本月和订单筛选条的本月差几天"——而两边都看着对。
    // （`preset` / `customFrom` / `customTo` / `chartType` 四个状态声明在**文件开头**：
    //   init 块会写它们，写在 init 之后就是"打开这一页必崩"，原因见那边的注释。）

    /**
     * 口径词 —— **跟着实际窗口走**（设计规范 §4.9）：选着"全部"却在标题上写"本月"，
     * 就是对不上账的第一步。
     */
    val periodWord: String get() = when {
        preset != DatePresets.CUSTOM -> preset
        rangeFrom == null || rangeTo == null -> DatePresets.ALL
        else -> rangeFrom!!.take(10).substring(5) + "~" + rangeTo!!.take(10).substring(5)
    }

    /** 切档位（含「全部」：那一档**不带日期条件**）。 */
    fun applyPreset(label: String) {
        preset = label
        val r = DatePresets.rangeOf(label, LocalDate.now())
        applyRange(r?.first, r?.second)
        if (tab != 0) loadAccounts()
    }

    /** 自定义区间（日期弹层回来的）。两头都没选 = 清掉区间，退回「全部」。 */
    fun applyCustomRange(from: String?, to: String?) {
        customFrom = from
        customTo = to
        preset = if (from == null && to == null) DatePresets.ALL else DatePresets.CUSTOM
        applyRange(from, to)
        if (tab != 0) loadAccounts()
    }

    /**
     * 这一档 tab 有哪几种图可选（规则在 `LedgerCharts.chartTypesFor`，有单测）。
     *
     * ⚠️ 货主账 / 批发商账**没有折线**：`/ledger/accounts` 只回账户汇总，没有按天的数。
     *    拿明细接口（`/ledger/entries`，一页最多 1000 条）去凑一条曲线，会在明细被截断时
     *    画出一条**比上面合计小**的线 —— 同一屏两个数，比"少一种图"糟得多。
     */
    fun chartTypes(): List<String> = chartTypesFor(tab)

    /** 当前选中档位的图表类型（切档位后原类型不支持时自动落到第一个）。 */
    val chartTypeNow: String get() = if (chartType in chartTypes()) chartType else chartTypes().first()

    /** 折线/条形要的**按天**序列（账户类没有按天的数 → 空）。 */
    fun seriesForChart(): List<Pair<String, Double>> = when (tab) {
        0 -> orderDailySeries(entries, rangeFrom, rangeTo)
        1 -> driverDailySeries(visibleDriverGroups(), rangeFrom, rangeTo)
        else -> emptyList()
    }

    /**
     * 扇形/排行要的切片。
     *
     * ⚠️ 集合**跟着搜索走**（与仪表盘同一个）：图上一个数、仪表盘另一个数，
     *    用户只会以为其中一个坏了。
     */
    fun slicesForChart(): List<Pair<String, Double>> = when (tab) {
        0 -> topSlices(orderSourceTotals(entries))
        1 -> topSlices(driverTotals(visibleDriverGroups()))
        else -> topSlices(accountTotals(visibleAccountRows()))
    }

    /** 条形图的数值与标签（账户类用"账户排行"当条形，图上会写明）。 */
    fun barsForChart(): Pair<List<Float>, List<String>> {
        val byDay = tab == 0 || tab == 1
        val rows = if (byDay) seriesForChart() else slicesForChart()
        // 标签：按天用 `09/20`（与折线同一份 dayLabel），账户用短名（长了会把旁边的挤掉）
        val labels = if (byDay) rows.map { dayLabel(it.first) } else rows.map { shortLabel(it.first) }
        return rows.map { it.second.toFloat() } to labels
    }

    /** 搜索过滤之后的司机组（图表与仪表盘**必须**是同一个集合）。 */
    fun visibleDriverGroups(): List<FreightSettlementGroupDto> =
        UserSearch.filter(driverAccounts, query, { it.driverName }, { it.driverPhone })

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
