package com.tapmoay.sorders.ui.shipper

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.core.OrderStatusModel
import com.tapmoay.sorders.data.remote.api.ShipperLedgerSummaryDto
import com.tapmoay.sorders.data.remote.api.ShipperSettlementCreateRequest
import com.tapmoay.sorders.data.remote.api.ShipperSettlementDto
import com.tapmoay.sorders.data.remote.api.ShipperSettlementLineRequest
import com.tapmoay.sorders.data.remote.dto.LedgerEntryDto
import com.tapmoay.sorders.data.remote.dto.OrderDto
import com.tapmoay.sorders.data.repo.toApiException
import com.tapmoay.sorders.ui.common.DatePresets
import com.tapmoay.sorders.util.moneyToDouble
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import java.time.LocalDate

/**
 * 货主账本（**以订单为基础**）。
 *
 * ## 用户 2026-09-20 定的形状
 * 1. 顶部**搜索框** → 批发商搜的是**联系人（他的货主）**，普通货主搜的是**订单**；
 * 2. **日期档位**（今天/昨天/前天/这周/上月/自定义）→ 按**订单送达日**筛
 *    （与派单员的账本同一个窗口口径，走 `delivered_from/delivered_to`）；
 * 3. **批发商货主**多一段：`① 我欠总分销商多少` + `② 我的货主欠我多少`（先联系人总计、
 *    再他名下的订单明细），并且能**就地核销**（整单 / 按商品 / 可撤销）；
 * 4. **普通货主**只有搜索 + 档位 + 自己的订单列表（点进详情）+ 一个"欠总分销商"合计，
 *    **没有核销**（他给自己下单，没有第二个债务人）。
 *
 * ## 两本账绝不互相写
 * 批发商那本核销走 `shipper-ledger`（后端新表），**一个字节都不写** `orders.paid` /
 * `cash_flows` / `ledgers` —— 所以这里的"已核销"只影响 `②`，永远不会让 `①` 变小。
 */
class ShipperLedgerViewModel(private val container: AppContainer) : ViewModel() {

    // ===== 身份：只有批发商货主才有第二段（给下游货主核销）=====
    //
    // 为什么要问一次 `users/me`：登录返回的 `TokenDto` 只有角色与编号，**不带 is_member**
    // （`core/TokenStore.kt::Session` 也没有）。而"是不是批发商"决定了这一页的**整段结构**，
    // 猜错的代价是把一个没有的功能画给普通货主，他点下去只会拿到 403。
    var isMember by mutableStateOf(false)
        private set
    var meLoaded by mutableStateOf(false)
        private set

    // ===== 这一段要看的账 =====
    var loading by mutableStateOf(false)
    var error by mutableStateOf<String?>(null)
    var actionResult by mutableStateOf<String?>(null)

    /**
     * **窗口定下来了没有**（2026-09-21 加）。
     *
     * 用户报的原话：「我点击我的账本的时候，它会**闪两下**再跳到「前天」……**闪两下已经不行了**」。
     * 老写法要先按「今天」取一次数（没单 → 闪一版空态），再退档到「前天」——
     * 所以这一页在最坏情况下会画三帧（今天·加载 → 今天·空态 → 前天·有数据）。
     *
     * 现在 `init` 只做**探测**：定下"真有数的那一档"之后才取那一次数；
     * 界面在 `windowSettled` 为 false 时整页显示 loading —— **一次都不画错窗口**（连药丸上的字
     * 也先写「…」，免得"今天 → 前天"那一下被看见）。
     *
     * ⚠️ 它只在 `init` 那条路上会从 false 变 true；用户自己换档（[applyPreset]）不改它
     *    ——换档是"我就是要看这一段"，不涉及"先盘点"。
     */
    var windowSettled by mutableStateOf(false)
        private set

    var keyword by mutableStateOf("")
        private set

    /** 搜索防抖用的 job（见 [onKeywordChange]：每个字都发请求会把输入框打废）。 */
    private var searchJob: Job? = null

    /**
     * 当前时间档位（顶栏那个**药丸**上写的字就是它）。
     *
     * 2026-09-20 用户第二次要求（对照片第 4 张）：「时间都是这样子滑动的话非常不方便……
     * 看一下派单员账本那个形式，**右上角一个时间丸**」——所以这一页不再铺那条 9 档胶囊行
     * （[DatePresetRow] 留给订单/库存那种**筛选条**用，两处长得一样是设计规范明确要避免的）。
     */
    var preset by mutableStateOf(DatePresets.TODAY)
        private set
    var customFrom by mutableStateOf<String?>(null)
        private set
    var customTo by mutableStateOf<String?>(null)
        private set

    /**
     * 用户**手动**挑过档位没有 —— 挑过就永不自动改（见 `init` 里那次 `pickWindow`）。
     *
     * 自动挑默认档位只该发生在"刚打开这一页"的时候；用户已经说了"我要看本月"，
     * 再替他改回去就是抢方向盘。
     */
    private var userPickedPreset = false

    /** 侧边抽屉里那个搜索框（**只筛人名单**，不筛订单——与派单员账本同一套做法）。 */
    var drawerQuery by mutableStateOf("")
        private set

    /**
     * 批发商账里**选中了哪个货主**（抽屉里点的）；null = 全部（默认）。
     *
     * 只对批发商有意义：普通货主没有第二个债务人，也就没有"人"可挑。
     */
    var selectedCustomerKey by mutableStateOf<String?>(null)
        private set

    var rangeFrom by mutableStateOf<String?>(null)
        private set
    var rangeTo by mutableStateOf<String?>(null)
        private set

    var orders by mutableStateOf<List<OrderDto>>(emptyList())
        private set

    /** 我记下的核销（含已撤销的；钱的计算只看没撤销的那些，见 [ShipperLedgerGrouping]）。 */
    var settlements by mutableStateOf<List<ShipperSettlementDto>>(emptyList())
        private set

    /**
     * **这一段他自己的收支统计**（2026-09-22 用户要求）—— **服务端算的**。
     *
     * ⛔ 它的三个数必须走端点，**不许**拿 [orders] 自己加：那一页是带 limit 的一页，
     *    单子一多客户端加出来的合计就偏小，而卡片上写着"这一段"（"同一个数两个答案"）。
     *    这一条有红线钉着（`_tools/qa/_check_shipper_ledger_stats.py`）。
     */
    var summary by mutableStateOf<ShipperLedgerSummaryDto?>(null)
        private set

    /** 这一页不是全部（响应头 `X-Truncated`）：上面的合计只含取到的这些行。 */
    var ordersTruncated by mutableStateOf(false)
        private set
    var ordersLimit by mutableStateOf<Int?>(null)
        private set

    // ===== 核销弹层（整单 / 按商品）=====
    var settleTarget by mutableStateOf<OrderDto?>(null)
        private set
    var settlePicked by mutableStateOf<Set<Long>>(emptySet())
        private set
    var settleMethod by mutableStateOf("cash")
    var settleNote by mutableStateOf("")
    var settleSubmitting by mutableStateOf(false)
        private set
    var settleError by mutableStateOf<String?>(null)
        private set

    // ===== 撤销核销 =====
    var revokeTarget by mutableStateOf<ShipperSettlementDto?>(null)
        private set
    var restoreTarget by mutableStateOf<ShipperSettlementDto?>(null)
        private set

    /** 这一单的核销记录弹层（一笔单可能收过好几次，撤销要能挑具体哪一笔）。 */
    var settlementListTarget by mutableStateOf<OrderDto?>(null)
        private set
    var acting by mutableStateOf(false)
        private set

    // ===== 旧「账目流水」视图（保留，不删能力）=====
    //
    // 用户这一轮要的是"以订单为基础的账本"，但账目流水是唯一能看到**手动记账 / 货损红冲**
    // 那些行的入口 —— 直接删掉等于删能力。所以它降级成顶栏上的一个二级入口。
    //
    // ⚠️ 2026-09-20 22:5x 用户第三次点名：「你这个账目流水为什么也不做对应的那个右上角的
    //    时间图标？他还是那个滑动型的」—— 于是它**不再有自己的时间窗口**，改用页面顶上那一个
    //    药丸（[preset] / [rangeFrom] / [rangeTo]），与订单账同一个窗口。
    //    这不是"顺手统一"：账本行的 `entry_date` 本来就等于**订单送达日**
    //    （`backend/app/services/ledger_sync.py:27` 是 `business_date(order.delivered_at) or
    //    order.order_date`，`api/v1/orders.py:204` 的注释也写明两边口径对齐），
    //    所以共用一个窗口不会让任何一边少算 —— 反而"同一页两个视图各看一段时间"才是假象。
    //    形态照的是派单员账本：`DispatcherLedgerScreen` 的订单账 tab 与别的 tab 共用
    //    顶栏那一个药丸、共用 `vm.rangeFrom/rangeTo`。
    var showFlow by mutableStateOf(false)
    var entries by mutableStateOf<List<LedgerEntryDto>>(emptyList())
        private set
    var entriesTruncated by mutableStateOf(false)
        private set
    var entriesLimit by mutableStateOf<Int?>(null)
        private set
    var chartType by mutableStateOf("line")

    var expandedOrderId by mutableStateOf<Long?>(null)
        private set
    var expandedOrder by mutableStateOf<OrderDto?>(null)
        private set
    var expandedOrderLoading by mutableStateOf(false)
        private set

    init {
        // ⚠️ 顺序有讲究：**先问清身份再取数** —— 是不是批发商决定了要不要拉核销记录，
        //    两次并发的话第一次加载会在"还不知道身份"时拉出一个没有核销状态的列表
        //    （界面先闪一版"全都没核销"，用户会以为数据错了）。
        viewModelScope.launch {
            try {
                isMember = container.repo.me().isMember
            } catch (_: Exception) {
                // 问不到就当普通货主：这一页最坏退化成"只有搜索 + 档位 + 订单列表"，
                // 而不是把一段用不了的功能画出来（核销按钮点了必然 403）。
                isMember = false
            } finally {
                meLoaded = true
            }
            // 默认档位 = **今天**；今天没单就自己往后退（用户 2026-09-20 点名要这个行为）。
            //
            // ⚠️⚠️ 2026-09-21 改成 **"先盘点、再取数"**（用户报的正是这里）：
            //     > 「我点击我的账本的时候，它会**闪两下**再跳到「前天」……我在点击账本之前，
            //     >   它就已经提前盘点好了：今天有账就直接出今天，今天没账再换前天。」
            //     老写法是"先按今天就位并**取一次数**，真没单再退档"——最坏要画三帧
            //     （今天·加载 → 今天·空态 → 前天·有数据），用户看到的就是闪两下，
            //     而且白发了一次注定被丢掉的请求（他点名的"占用性能"就是它）。
            //     现在只做**探测**（每档 limit=1），定下来之后**只取一次数**；
            //     页面那边用 [windowSettled] 把"还没定下来"这一帧挡成 loading。
            //
            // ⚠️ 仍然必须走 `switchPreset`（不能直接 `load()`）：它把"档位 → 区间 → 取数"
            //    锁在一条路上；绕开它就会拿 null 区间去查（= 不带日期条件 = 全部）。
            // ⚠️ **用户可能在探测期间自己挑了档位**（探测是网络请求，来回一秒很正常）：
            //    那时再按阶梯的结果 switchPreset 就是**抢方向盘** —— 与 `fallbackForPerson`
            //    共用同一个开关（"默认"只在你还没表态的时候替你选）。
            if (!userPickedPreset) {
                switchPreset(DatePresets.pickWindow(DatePresets.AUTO_LADDER) { periodHasData(it) })
            }
            windowSettled = true
        }
        // 订单送达自动记账 / 派单员收款后实时刷新（**两个视图一起**，见 [reloadWindow]）
        viewModelScope.launch { container.realtimeHub.refreshLedger.collect { reloadWindow() } }
        viewModelScope.launch { container.realtimeHub.refreshOrders.collect { reloadWindow() } }
    }

    // ---------------------------------------------------------------- 时间档位（顶栏药丸）

    /**
     * 自动退档的顺序：今天 → 昨天 → 前天 → 近 7 天（都没有再落到「全部」）。
     *
     * ⚠️ 用**共享的那一份** `DatePresets.AUTO_LADDER`，不再在本文件里另写一个 list：
     *    这一页与开销管理页是同一种页面（"一打开就该有数"），两份写死的清单必然走散 ——
     *    而走散的表现是"同一个默认行为在两个页面上不一样"，用户只会觉得系统不稳。
     *    （司机端那两页用更长的 `DRIVER_PRESET_LADDER`，按送达日看任务，是另一套，见那边的注释。）
     */
    /** 药丸上写的字（当前窗口**永远看得见**——这一页最容易搞错的就是口径词）。 */
    val periodWord: String
        get() = when {
            // 还没盘点完 → 先写「…」：这时候写任何档位都是**假话**（窗口还没定），
            // 而"今天 → 前天"那一下正是用户说的"闪两下"里最扎眼的一半。
            !windowSettled -> "…"
            preset == DatePresets.CUSTOM -> DatePresets.customLabel(customFrom, customTo)
            else -> preset
        }

    /**
     * 这一段**有没有单**（只探测、不动页面状态）。
     *
     * ⚠️ 判据必须与页面自己那一份取数**同源**（这里是 `GET /orders?delivered_from&delivered_to`）：
     *    用别的接口猜"有没有单"，会出现"退档到的那一档页面还是空的"。
     * ⚠️ 探测失败（网络/权限）当"没单"处理：不能因为探测不通就把用户按在一个看不见的窗口上。
     * ⚠️ 只取 1 条：退档最多探 4 次，一次 500 行的探测是白花的流量。
     */
    private suspend fun periodHasData(label: String): Boolean {
        val r = DatePresets.rangeOf(label, LocalDate.now()) ?: return true
        return try {
            container.repo.myLedgerOrders(
                deliveredFrom = r.first,
                deliveredTo = r.second,
                limit = 1,
            ).rows.isNotEmpty()
        } catch (_: Exception) {
            false
        }
    }

    /** 用户自己在药丸里挑的档位（**手动**：从此不再自动退档）。 */
    fun applyPreset(label: String) {
        userPickedPreset = true
        // 用户已经表态 = 窗口就算是定下来了（不必再等他那一秒的探测跑完才开闸，
        // 否则他挑完档位之后画面还要再 loading 一下）。
        windowSettled = true
        switchPreset(label)
    }

    /** 真正的换档（自动退档与手动换档都走这一条路，**不许各写一份**）。 */
    private fun switchPreset(label: String) {
        preset = label
        val r = DatePresets.rangeOf(label, LocalDate.now())
        rangeFrom = r?.first
        rangeTo = r?.second
        reloadWindow()
    }

    /**
     * 自定义区间（日期弹层回来的）。两头都没选 = 清掉区间，退回「全部」。
     * ⚠️ 手输的窗口同样是**手动**：不再自动退档。
     */
    fun applyCustomRange(from: String?, to: String?) {
        userPickedPreset = true
        windowSettled = true // 同上：手输的窗口也算"用户已经表态"
        if (from == null || to == null) {
            customFrom = null
            customTo = null
            switchPreset(DatePresets.ALL)
            return
        }
        customFrom = from
        customTo = to
        preset = DatePresets.CUSTOM
        rangeFrom = from
        rangeTo = to
        reloadWindow()
    }

    /**
     * 换窗口（或实时推送来了）之后要重取的**两件事**：订单账（[load]）与账目流水（[loadFlow]）。
     *
     * ⚠️ 必须**一起走**。2026-09-20 两个视图共用一个窗口之后，只刷新一个的后果是：
     *    切到另一个视图会看到**上一个窗口**的数 —— 而药丸上写着新窗口，
     *    两个数各自都对、摆在一起就是假的（这一页已经栽过一次同类问题，见 [totals]）。
     * 流水视图没开着时不取（省一次请求；开的时候 [toggleFlow] 会取）。
     */
    private fun reloadWindow() {
        load()
        if (showFlow) loadFlow()
    }

    // ---------------------------------------------------------------- 选人（侧边抽屉）

    fun onDrawerQueryChange(text: String) {
        drawerQuery = text
    }

    /**
     * 抽屉里点了某个货主 → 只看他；再点一次同一个 = 回到全部。
     *
     * ⚠️ **换人必须重取统计**（[load]）：顶上那张卡的数现在是**服务端算的**
     *    （`GET /shipper-ledger/summary?customer_name=…`），换人**不会**让它自己变
     *    —— 2026-09-22 真机实测抓到过：标题写着「这一段 · 江玉兰」，数字还是全部那 14 单的。
     *    （原来那张卡是客户端把这一页加起来，所以换人不取数也"看着对"。）
     *    红线 `_check_shipper_ledger_stats.py` 有一条专门钉这件事。
     */
    fun selectCustomer(key: String?) {
        selectedCustomerKey = if (key != null && key == selectedCustomerKey) null else key
        load()
    }

    fun clearCustomer() {
        selectedCustomerKey = null
        load()
    }

    fun onKeywordChange(text: String) {
        keyword = text
        // ⚠️ **防抖**：每敲一个字就发一次请求的后果不只是浪费 ——
        //    真机上实测（`adb shell input text 13565516587`）**11 位只落进去 2 位**：
        //    每次都回一整页数据 + 重组整个列表，输入框在重组中被重建，字符就丢了。
        //    用户看到的是"搜索框打不进字"，而没有任何报错。
        //    所以：状态立刻更新（字要能打进去），查询等手停下来再发。
        searchJob?.cancel()
        searchJob = viewModelScope.launch {
            delay(SEARCH_DEBOUNCE_MS)
            load()
        }
    }

    fun load() {
        loading = orders.isEmpty()
        error = null
        viewModelScope.launch {
            try {
                val page = container.repo.myLedgerOrders(
                    // 搜索词只给**普通货主**用（他搜的是订单：单号/收货人/地址）。
                    // 批发商搜的是"人"，那件事在侧边抽屉里做（翻到哪个人由 [selectedCustomerKey] 决定），
                    // 所以这里不能把抽屉的搜索词当成订单关键词发下去 —— 那会把账**筛小**
                    // （抽屉里输个名字，页面上的合计跟着变，用户会以为钱少了）。
                    q = if (isMember) null else keyword.trim().ifBlank { null },
                    deliveredFrom = rangeFrom,
                    deliveredTo = rangeTo,
                    limit = LEDGER_PAGE_LIMIT,
                )
                orders = page.rows
                ordersTruncated = page.meta.hasMore
                ordersLimit = page.meta.limit

                // 核销记录：**不带关键词**（要的是这些单各自的完整核销状态），
                // 但带窗口 —— 与订单列表同一个集合，界面上不会出现"订单在、状态不在"。
                settlements = if (isMember) {
                    container.repo.mySettlements(
                        deliveredFrom = rangeFrom,
                        deliveredTo = rangeTo,
                        includeDeleted = true,
                        limit = LEDGER_PAGE_LIMIT,
                    ).rows
                } else {
                    emptyList()
                }
                // ⚠️ 顺序要紧：先把"那个人还在这段里吗"判掉（见下），再取统计 ——
                //    否则会用**已经不在这一段的那个人**去筛，卡上出现"全部"却只有 0 单。
                selectedCustomerKey?.let { k ->
                    if (orders.isNotEmpty() && allCustomers.none { it.key == k }) selectedCustomerKey = null
                }
                // 顶上那段**收支统计**：同一窗口 + **同一个下游货主**（侧边抽屉选中的人）。
                // ⚠️ 必须与下面那些按人分组的行**同源**（同窗口、同一个人），否则卡上的数会与
                //    那个人名下的行对不上 —— 那一页栽过一次同类问题（见 [totals] 的注释）。
                summary = container.repo.myLedgerSummary(
                    deliveredFrom = rangeFrom,
                    deliveredTo = rangeTo,
                    customerName = summaryCustomerName(),
                    customerPhone = summaryCustomerPhone(),
                )
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                loading = false
            }
        }
    }

    /**
     * 统计要按哪个下游货主筛（null = 全部）。
     *
     * ⚠️ 名字与电话**必须成对**传：服务端的判据是"名字 + 电话"（与 [customerKeyOf] 同一个键）
     *    —— 只传名字会把两个同名的货主并成一个（"他的欠款翻倍、另一个人的不见了"，两边都不报错）。
     * ⚠️ 「未指定货主」那一档不过滤：它是"老单没记收货人"，不是一个真的人。
     */
    private fun summaryCustomerName(): String? =
        selectedCustomer?.name?.takeIf { it.isNotBlank() && it != UNSET_CUSTOMER }

    private fun summaryCustomerPhone(): String? =
        if (summaryCustomerName() == null) null else selectedCustomer?.phone.orEmpty()

    // ---------------------------------------------------------------- 派生（纯函数算）

    /** 每一行已经核销了多少（分）。 */
    val settledByLine: Map<Long, Long> get() = settledByLineCents(settlements)

    /** 这一段的**全部**货主（按欠款倒序），抽屉里那一份名册。 */
    val allCustomers: List<LedgerCustomer>
        get() = groupByCustomer(orders, settlements)

    /** 抽屉里已经按搜索词筛过的名册（**只筛名单**，不影响页面上的账）。 */
    val drawerCustomers: List<LedgerCustomer>
        get() = filterByCustomer(allCustomers, drawerQuery)

    /**
     * 页面上要画的那几个货主：选中了某人就只画他，否则画全部。
     *
     * ⚠️ 普通货主走的是另一条路（服务端 `q` 搜订单，见 [keyword]）—— 他没有"人"可挑，
     *    [selectedCustomerKey] 永远是 null，这里返回的就是空表（界面那一整段都不画）。
     */
    val customers: List<LedgerCustomer>
        get() {
            val all = allCustomers
            val key = selectedCustomerKey ?: return all
            return all.filter { it.key == key }
        }

    /** 抽屉里选中那个人（选中态要靠它打勾）。 */
    val selectedCustomer: LedgerCustomer?
        get() = selectedCustomerKey?.let { k -> allCustomers.firstOrNull { it.key == k } }

    /**
     * 顶卡片上的数 = **服务端的收支统计**（[summary]，在 [load] 里取）。
     *
     * ⛔ 这里原来有一份客户端求和（`ledgerTotals`：把这一页订单的 `arrears_amount` 加起来）。
     *    它的形状是"拿一页数据当全部" —— 列表一带 limit（`LEDGER_PAGE_LIMIT`），
     *    单子多的那一段**合计就偏小**，而卡片上写着"这一段"（期① 审计里"客户端求和少算 62%"
     *    是同一个形状：同一个数两个答案，两边都不报错）。现在整条删掉，只留服务端那一个来源。
     */

    /** 已撤销的核销（界面上那个「已撤销」折叠区）。 */
    val revoked: List<ShipperSettlementDto> get() = settlements.filter { it.isDeleted }

    fun settledOfOrder(orderId: Long): List<ShipperSettlementDto> =
        settlements.filter { it.orderId == orderId && !it.isDeleted }

    fun remainingOf(order: OrderDto): Long = orderRemainingCents(order, settledByLine)

    fun remainingOfLine(lineId: Long): Long {
        val order = settleTarget ?: return 0
        val line = order.orderProducts.firstOrNull { it.id == lineId } ?: return 0
        return lineRemainingCents(line, settledByLine)
    }

    /**
     * 这一单现在能不能核销（**界面上的门**）。
     *
     * 状态门与后端 `services/shipper_settle.py::settle_blocker` 一致：只放**已送达**
     * （退过货/没送达/已撤销都不该收这笔钱）。这里复用 `OrderStatusModel.RETURNABLE`
     * 而不是新写一个 `status == "DELIVERED"` —— 那条常量就是后端"只认已送达"那一档。
     * 后端仍然是最终判据：真被拦下时它的中文原因会显示在弹层里（[settleError]）。
     */
    fun canSettle(order: OrderDto): Boolean =
        isMember && order.status in OrderStatusModel.RETURNABLE && remainingOf(order) > 0L

    // ---------------------------------------------------------------- 核销弹层

    fun openSettle(order: OrderDto) {
        settleTarget = order
        settlePicked = emptySet()      // 不勾任何商品 = 整单核销
        settleMethod = "cash"
        settleNote = ""
        settleError = null
    }

    fun closeSettle() {
        settleTarget = null
        settlePicked = emptySet()
        settleError = null
    }

    fun toggleSettleLine(lineId: Long) {
        settlePicked = if (lineId in settlePicked) settlePicked - lineId else settlePicked + lineId
    }

    fun pickAllSettleLines() {
        val o = settleTarget ?: return
        settlePicked = o.orderProducts.filter { lineRemainingCents(it, settledByLine) > 0L }
            .map { it.id }.toSet()
    }

    fun clearSettleLines() {
        settlePicked = emptySet()
    }

    /**
     * 本次核销的金额（分，**界面只读显示、由这里算**）。
     *
     * 与后端同一个式子：不勾任何商品 = 整单（各行还可核销之和）；勾了就只算勾中的那些行。
     * 金额**不许让用户手输** —— 后端要求逐行对得上，手输必然对不上（那边会 400）。
     */
    fun settleAmountCents(): Long {
        val o = settleTarget ?: return 0
        val picked = settlePicked
        return if (picked.isEmpty()) {
            orderRemainingCents(o, settledByLine)
        } else {
            o.orderProducts.filter { it.id in picked }.sumOf { lineRemainingCents(it, settledByLine) }
        }
    }

    fun submitSettle() {
        val o = settleTarget ?: return
        val picked = settlePicked
        settleSubmitting = true
        settleError = null
        viewModelScope.launch {
            try {
                val lines = if (picked.isEmpty()) {
                    emptyList()
                } else {
                    o.orderProducts
                        .filter { it.id in picked }
                        .map {
                            ShipperSettlementLineRequest(
                                orderProductId = it.id,
                                amount = com.tapmoay.sorders.ui.dispatcher.centsToMoney(
                                    lineRemainingCents(it, settledByLine)
                                ),
                            )
                        }
                }
                container.repo.createMySettlement(
                    ShipperSettlementCreateRequest(
                        orderId = o.id,
                        lines = lines,
                        method = settleMethod,
                        note = settleNote.trim(),
                        source = "app",
                    )
                )
                actionResult = "已核销：订单 #" + o.orderNo
                closeSettle()
                load()
            } catch (e: Exception) {
                // 失败要把后端那句中文原样显示（"还可核销 ¥60，不能核 ¥100"这类话要看得见）
                settleError = toApiException(e).message
            } finally {
                settleSubmitting = false
            }
        }
    }

    // ---------------------------------------------------------------- 撤销 / 恢复

    fun openSettlements(order: OrderDto) {
        settlementListTarget = order
    }

    fun closeSettlements() {
        settlementListTarget = null
    }

    fun askRevoke(s: ShipperSettlementDto) {
        revokeTarget = s
    }

    fun cancelRevoke() {
        revokeTarget = null
    }

    fun confirmRevoke() {
        val s = revokeTarget ?: return
        acting = true
        viewModelScope.launch {
            try {
                container.repo.revokeMySettlement(s.id)
                actionResult = "已撤销这笔核销（可在下方「已撤销」里恢复）"
                revokeTarget = null
                load()
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                acting = false
            }
        }
    }

    fun askRestore(s: ShipperSettlementDto) {
        restoreTarget = s
    }

    fun cancelRestore() {
        restoreTarget = null
    }

    fun confirmRestore() {
        val s = restoreTarget ?: return
        acting = true
        viewModelScope.launch {
            try {
                container.repo.restoreMySettlement(s.id)
                actionResult = "已恢复这笔核销"
                restoreTarget = null
                load()
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                acting = false
            }
        }
    }

    // ---------------------------------------------------------------- 旧流水视图
    //
    // ⚠️ 这里**没有**自己的时间状态：窗口就是页面顶上那一个药丸（[rangeFrom] / [rangeTo]，
    //    换档走 [applyPreset] / [applyCustomRange] → [reloadWindow]）。
    //    2026-09-20 之前它有一份 `flowFrom/flowTo` + 一套"按日/周/月翻页"的残留
    //    （`applyFlowMode` / `setFlowAnchor` / `flowPeriodText`）—— 那套东西**界面上一处都没接**
    //    （全项目 grep 只命中它们自己），留着只会让下一个人以为流水有时间导航。已删。

    /**
     * 切进 / 切出流水视图。
     *
     * ⚠️ 切进去时**总是重取**（不是 `if (entries.isEmpty())`）：期间可能已经换过窗口
     *    （订单账那边点了药丸、或实时推送刷新过），只按"列表非空"判断会**留下上一个窗口的行**，
     *    而药丸上写着新窗口 —— 那种错界面上看不出来。
     */
    fun toggleFlow() {
        showFlow = !showFlow
        if (showFlow) loadFlow()
    }

    fun flowTotal(): Double = entries.sumOf { moneyToDouble(it.total) }

    val flowChartSeries: List<Pair<String, Double>> get() {
        val map = LinkedHashMap<String, Double>()
        entries.forEach { e ->
            val key = (e.entryDate ?: "").take(10)
            if (key.isNotBlank()) map[key] = (map[key] ?: 0.0) + moneyToDouble(e.total)
        }
        return map.entries.map { it.key to it.value }
    }

    /**
     * 取这一段流水 —— 窗口**就是页面顶上那一个药丸**（不是自己的一份）。
     *
     * 口径依据（为什么可以共用）：账本行的 `entry_date` = **订单送达日**
     * （`backend/app/services/ledger_sync.py:27`；`api/v1/orders.py:204` 的注释也写明
     * "按送达日筛订单、口径与账本行的 entry_date 对齐"），所以订单账的窗口与流水是同一段时间。
     * 手动记账那些行按它自己的记账日期落在这段时间里 —— 「全部」那一档（无区间）仍能看到它们全部。
     */
    fun loadFlow() {
        viewModelScope.launch {
            try {
                val page = container.repo.ledgerEntries(from = rangeFrom, to = rangeTo)
                entries = page.rows
                entriesTruncated = page.meta.hasMore
                entriesLimit = page.meta.limit
            } catch (e: Exception) {
                error = toApiException(e).message
            }
        }
    }

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
                error = toApiException(e).message
                expandedOrderId = null
            } finally {
                expandedOrderLoading = false
            }
        }
    }

    companion object {
        /**
         * 一页取多少单。
         *
         * 500 ≈ 后端上限（5000）之下的一个稳妥值：账本页把"这些单的钱"加在一起当合计，
         * 300（后端缺省）对一天几十单的批发商很快就不够 —— 而**被截断时界面会说出来**
         * （[ordersTruncated] → `TruncationNote`），不会把一页当全部。
         */
        const val LEDGER_PAGE_LIMIT = 500

        /** 搜索防抖窗口（毫秒）：手停下来再查，别一个字一次请求。 */
        const val SEARCH_DEBOUNCE_MS = 350L

        /** 收款方式（与后端 `schemas/shipper_settlement.py::SETTLE_METHODS` 同一套词）。 */
        val METHODS: List<Pair<String, String>> = listOf(
            "cash" to "现金",
            "wechat" to "微信",
            "transfer" to "转账",
            "arrears_settle" to "结清欠款",
        )
    }
}
