package com.tapmoay.sorders.ui.dispatcher

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.LocalShipping
import androidx.compose.material.icons.filled.PeopleAlt
import androidx.compose.material.icons.filled.Storefront
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.core.UserSearch
import com.tapmoay.sorders.data.remote.dto.FreightSettlementGroupDto
import com.tapmoay.sorders.data.remote.dto.FreightSettlementOrderDto
import com.tapmoay.sorders.data.remote.dto.LedgerAccountOut
import com.tapmoay.sorders.data.remote.dto.LedgerEntryDto
import com.tapmoay.sorders.data.remote.dto.OrderDto
import com.tapmoay.sorders.data.remote.dto.ReceiptCreateRequest
import com.tapmoay.sorders.data.repo.toApiException
import com.tapmoay.sorders.ui.common.DatePresets
import com.tapmoay.sorders.ui.theme.MemberGold
import com.tapmoay.sorders.ui.theme.MgrGreen
import com.tapmoay.sorders.ui.theme.ShipperTeal
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
 *
 * ⚠️ [initialTab] 是**这一类账**，由入口页（`LedgerHomeScreen` 的 6 格）定下来，
 *    页面内**不再切换**：用户 2026-09-20 看了真机，把页内那条 4 页签导航否掉了 ——
 *    「最上面的 4 个去掉，那是**老的导航栏**」。
 */
class DispatcherLedgerViewModel(
    private val container: AppContainer,
    initialTab: Int = 0,
) : ViewModel() {

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

    /**
     * 当前选中的日期档位（[DatePresets.ROW] 里的一档，或「自定义」）。
     *
     * ⚠️ 初值 = **今天**（用户 2026-09-20：「这些时间默认是今天的，如果今天没有任何订单的话，
     *    然后再是昨天，以此类推」）。⚠️ 但**不再"先按今天拉一次"了**（2026-09-21）：
     *    那一下就是用户说的"闪两下"——先画一版今天的空态、再退到前天。现在 `init` 只探测、
     *    定下来之后才取一次数，页面在 [windowSettled] 为假时整页 loading。
     */
    var preset by mutableStateOf(DatePresets.TODAY)
        private set

    /**
     * **窗口定下来了没有**（2026-09-21）。
     *
     * 用户原话：「我在点击我的账本的时候，它会**闪两下**再跳到「前天」……其他**派单员那些
     * 账本界面**基本上也是这个逻辑，**闪两下已经不行了**，不美观，且占用性能。」
     * 为假时页面整页 loading（药丸上的字也先写「…」）——**一次都不画错窗口**。
     */
    var windowSettled by mutableStateOf(false)
        private set

    /** 「自定义」那一档的两端（用户在日期弹层里选的）。 */
    var customFrom by mutableStateOf<String?>(null)
        private set
    var customTo by mutableStateOf<String?>(null)
        private set

    // ⛔ 这里**没有** `chartType` 了：账本页整个不画图（2026-09-20 第五轮，用户：
    //    「那个折线图条形图还有扇形图，我们直接去掉就行了……到时候在报表中心看就可以了」）。
    //    图与它们的取数纯函数（`LedgerCharts.kt`）一起删了 —— 留着"没人调的类型开关 +
    //    取数函数"只会让下一个人以为这一页还能切图。

    // ===== 账本分类：0=订单账 1=司机账 2=货主账 3=批发商账 =====
    //
    // ⛔ 页面里**没有**切换它的入口了（用户 2026-09-20：「最上面的 4 个去掉，那是老的导航栏」）——
    //    它由入口页那一格决定，构造时就定死。留着 `selectTab` 那样一个没人调的方法，
    //    下一个人会以为"这一页还能切档位"，然后照着它写一个切档位的入口。
    var tab by mutableStateOf(initialTab)
        private set
    var driverAccounts by mutableStateOf<List<FreightSettlementGroupDto>>(emptyList())
    var shipperAccounts by mutableStateOf<List<LedgerAccountOut>>(emptyList())
    var memberAccounts by mutableStateOf<List<LedgerAccountOut>>(emptyList())
    var accountsLoading by mutableStateOf(false)

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

    /**
     * 搜索过滤之后的名单 —— **侧边抽屉里那一份**（用户 2026-09-20 第五轮：
     * 「选择人物，我们使用那种侧边栏抽屉，可以在那里寻找人物，点击人物就可以了」）。
     *
     * ⚠️ 它是**选人用的清单**，不参与页面上的合计：用户在抽屉里打字只是想"快点找到那个人"，
     *    不是"把这一页的账筛成两家"—— 关掉抽屉后剩一个对不上的合计，那种账最难查。
     */
    fun visibleAccountRows(): List<LedgerAccountRow> =
        UserSearch.filter(accountRows(), query, { it.title }, { it.phone })

    /**
     * 仪表盘三个数：**全部**账户的账户数 / 笔数 / 金额。
     *
     * ⚠️ 笔数取服务端的 `count`（那一栏是**全量**笔数），不是本地明细的行数 ——
     *    明细是分页的，拿它当"一共几笔"会少报。
     * ⚠️ 这里**不跟抽屉里的搜索走**：抽屉是"选人"用的（第五轮用户要求），
     *    边打字边改这一页的合计，关掉抽屉就会剩一个对不上的总数。
     */
    fun dashboard(): LedgerDashboard {
        val rows = accountRows()
        return LedgerDashboard(rows.size, rows.sumOf { it.count }, rows.sumOf { it.total })
    }

    /** 一个账户的 key（与 [accountRows] 用的是同一套拼法，**不许各写一份**）。 */
    fun accountKey(a: LedgerAccountOut): String =
        if (a.id != null) "u|${a.id}" else "t|${a.tempName.orEmpty()}"

    // ===== 这一类账自己的名字 / 颜色 / 图标（页面标题、空态、行卡都取这一份）=====
    //
    // 以前这四样散在页面里的三处 `when (vm.tab)`（标题、仪表盘、行卡图标），改一处漏一处；
    // 页内那条 4 页签导航删掉之后，标题成了**唯一**说明"我在看哪一本账"的地方，
    // 更不能有两份。

    /** 顶栏标题。 */
    fun kindTitle(): String = when (tab) {
        1 -> "司机账"
        2 -> "货主账"
        3 -> "批发商账"
        else -> "订单账"
    }

    /** 行卡/空态里的那两个字（「未命名司机」这种兜底也用它）。 */
    fun kindLabel(): String = if (tab == 3) "批发商" else kindTitle().removeSuffix("账")

    fun kindColor(): Color = when (tab) {
        1 -> Color(MgrGreen)
        3 -> Color(MemberGold)
        else -> Color(ShipperTeal)
    }

    fun kindIcon(): ImageVector = when (tab) {
        1 -> Icons.Default.LocalShipping
        3 -> Icons.Default.Storefront
        else -> Icons.Default.PeopleAlt
    }

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

    /**
     * 这一单/这一类账当前窗口的左端（**只给 `LedgerCharts` 的纯函数用**：它们要按天分桶）。
     * 右端直接用 `rangeTo`。
     */
    val periodStart: String? get() = rangeFrom

    /** 司机账/货主账/批发商账：按当前时间范围拉取账户汇总 */
    fun loadAccounts() {
        accountsLoading = true
        loadError = null
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

    // 记一笔账的草稿状态**不在这一页了**：用户 2026-09-20 第七轮把它改成单独一页
    // （`LedgerCreateScreen.kt`），因为商品要**从商品库选**（全屏底部弹层）——
    // 那个弹层套在 `AlertDialog` 里就是两层 modal 窗口叠着。这里只留"回来重取一次"的钩子。
    var deleteTarget by mutableStateOf<LedgerEntryDto?>(null)

    // ===== 第二层：某个货主 / 批发商**按订单**的账 =====
    //
    // 用户 2026-09-20 拍板：「账本管理的核心单位也就是最小单位是**订单**。首先我们来管一下
    // 货主的账，他这个账**第一层就是货主选择**，**第 2 层是时间上的统计**（昨天/今天/前天/
    // 这周/这个月、自定义，包括我们也可以直接搜索货主）……然后就会出现对应的账本，
    // 这个月账本是**按那个订单来算的、按订单来结算的**。」
    //
    // ⚠️ 第一层仍然是"一屏看完所有账户各自的数"（列表上就写着每人的笔数与金额）——
    //    2026-09-19 用户否掉过"先在一堆 chip 里把人一个个点出来"的那一版，
    //    理由是"客户非常多的时候，一个一个去选太麻烦"。两层与那条并不冲突：
    //    **选人之前就已经看得见每个人的钱**，点进去只是"看他这一段的账"。
    //
    // 2026-09-20 第五轮（**就是这一版**）：用户把"图"和"选人那一排 chip"都否掉了 ——
    //   · 「那个折线图条形图还有扇形图，我们直接去掉就行了啊，其他的都也去掉，其他的像什么
    //     批发商账、货主账，全都去掉这些图，**到时候在报表中心看就可以了**」
    //     → 账本页**一张图都不画**（`LedgerCharts.kt` / `ChartPalette` / `PieChart` 一起删了）；
    //   · 「选择司机那一行，假如司机多的话，那我要选该怎么去选呢？……选择人物，我们使用那种
    //     **侧边栏抽屉**，可以在那里寻找人物，点击人物就可以了」
    //     → 选人改成抽屉（抽屉里带搜索），页面上只留一行「人员：全部（N 人）」当入口；
    //   · 「那个时间也太复杂了，这样的不好，换一种崭新形式」+「时间和选择人物**不要选择一样的
    //     展现形式**」 → 时间挪到顶栏做一个紧凑药丸（点开档位清单），与抽屉是两种形态。
    // 于是这一页从上到下就是：顶栏（这一类账 + 时间）→ 人员那一行 → 数据。
    //
    // ⛔ **这几个状态必须声明在 `init {}` 之前**（`_check_vm_state_before_init.py` 钉着）：
    //    init 会调 `applyPreset(本月)` → `loadPerson()`。Kotlin 按书写顺序初始化属性，
    //    写在 init 之后的话 `personLoading = true` 会对着一个还没初始化的引用赋值 ——
    //    **打开这一页直接崩**（这条坑这个文件已经栽过一次，见文件开头那段注释）。

    /** 选中的那个人（`u|id` / `t|名字`）；null = 还在第一层"选货主"。 */
    var personKey by mutableStateOf<String?>(null)
        private set

    /** 他的订单（按**送达日**落窗口）——KPI 与商品统计都从这一份算出来。 */
    var personOrders by mutableStateOf<List<OrderDto>>(emptyList())
        private set
    var personStats by mutableStateOf<List<ProductStat>>(emptyList())
        private set
    var personLoading by mutableStateOf(false)
        private set

    /** 这一页被截断了没有（KPI 与统计都只含**取到的那一页**，必须说出来）。 */
    var personTruncated by mutableStateOf(false)
        private set
    var personLimit by mutableStateOf<Int?>(null)
        private set

    /** 他对应的客户档案（核销要 `customer_id`）。null = 没有档案（临时货主 / 没关联账号）。 */
    var personCustomerId by mutableStateOf<Long?>(null)
        private set

    /** 正在核销的那张单（null = 没开核销弹层）。 */
    var settleTarget by mutableStateOf<OrderDto?>(null)
        private set

    /** 勾了哪几行（`order_products.id`）。空 = 整单核销。 */
    var settlePicked by mutableStateOf<Set<Long>>(emptySet())
        private set
    var settleMethod by mutableStateOf("cash")
    var settleSubmitting by mutableStateOf(false)
        private set

    /**
     * 批量核销（点合计 → 核销全部）的弹层开着没有。
     *
     * 用户 2026-09-20：「我们那个卡片的最顶端不是一个**全部合计**吗…如果是今天，那就是今天的
     * 所有订单；如果是这周，那就这周的所有订单。这样子我们就可以**直接点这个合计将它核销掉**，
     * 就不用一个一个去核销订单了，它相当于一个**可控的批量处理**。但是如果是**全部**
     * （所有人）的话，那个合计**不能**批量核销，只能下到每个司机/货主才能批量核销」
     * —— 所以 [openSettleAll] 里有一道"必须先选中某个人"的门。
     */
    var settleAllOpen by mutableStateOf(false)
        private set

    /**
     * 用户**手动**挑过档位了没有 —— 挑过就永不自动改（见 `init` 里那次 `pickWindow`）。
     *
     * 自动挑默认档位只该发生在"刚打开这一页、屏幕上空着"的时候；用户已经明确说了
     * "我要看本月"，再替他改回去就是抢方向盘。
     */
    private var userPickedPreset = false

    init {
        // 默认档位 = **今天**；今天没账就往前退（用户 2026-09-20：「这些时间默认是今天的，
        // 如果今天没有任何订单的话，然后再是昨天，以此类推」）。
        //
        // ⚠️⚠️ 2026-09-21 改成 **"先盘点、再取数"**（用户报的是同一类毛病，且点名了派单员这边）：
        //     > 「我在点击我的账本的时候，它会**闪两下**再跳到「前天」……我在点击账本之前，
        //     >   它就已经提前盘点好了……其他**派单员那些账本界面**基本上也是这个逻辑，
        //     >   **闪两下已经不行了**，不美观，且占用性能。」
        //     老写法是"先按今天就位并**取一次数**，真没单再异步退档"——最坏要画三帧
        //     （今天·加载 → 今天·空态 → 前天·有数据），还白发一次注定被丢掉的请求。
        //     现在只做**探测**（每档 limit=1），定下来之后**只取一次数**；
        //     页面那边用 [windowSettled] 把"还没定下来"那一帧挡成 loading。
        viewModelScope.launch {
            // ⚠️ **用户可能在探测期间自己挑了档位**（探测是网络请求，来回一秒很正常）：
            //    那时再按阶梯的结果 switchPreset 就是**抢方向盘** —— 与 `fallbackForPerson`
            //    共用同一个开关（"默认"只在你还没表态的时候替你选）。
            if (!userPickedPreset) {
                switchPreset(DatePresets.pickWindow(DatePresets.AUTO_LADDER) { periodHasData(it) })
            }
            windowSettled = true
        }
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

    /**
     * 这一段有没有账（**只探测、不动页面状态**）。
     *
     * 判据与页面自己那一份取数**同源**：订单账看流水、司机账看结算分组、货主/批发商账看账户汇总
     * —— 用别的接口猜"有没有单"，会出现"退档到的那一天页面还是空的"。
     * ⚠️ 探测失败（网络/权限）当"没数"处理：不能因为探测不通就把用户按在一个看不见的窗口上。
     */
    private suspend fun periodHasData(label: String): Boolean {
        val r = DatePresets.rangeOf(label, LocalDate.now()) ?: return true
        val (f, t) = r
        return try {
            when (tab) {
                0 -> container.repo.ledgerEntries(from = f, to = t).rows.isNotEmpty()
                1 -> container.repo.freightSettlementRange(f + " 00:00:00", t + " 23:59:59").groups.isNotEmpty()
                else -> container.repo.ledgerAccounts(f, t, if (tab == 3) "member" else "shipper").isNotEmpty()
            }
        } catch (e: Exception) {
            false
        }
    }

    fun total(): Double = entries.sumOf { moneyToDouble(it.total) }

    fun applyRange(from: String?, to: String?) {
        rangeFrom = from
        rangeTo = to
        load()
    }

    /** 用户自己挑的档位（**手动**：从此不再自动退档）。 */
    fun applyPreset(label: String) {
        userPickedPreset = true
        // 用户已经表态 = 窗口就算是定下来了（不必再等 init 那次探测跑完才开闸，
        // 否则他挑完档位画面还要再 loading 一下）。
        windowSettled = true
        switchPreset(label)
    }

    /** 真正的换档（自动退档与手动换档都走这一条路，**不许各写一份**）。 */
    private fun switchPreset(label: String) {
        preset = label
        val r = DatePresets.rangeOf(label, LocalDate.now())
        applyRange(r?.first, r?.second)
        refreshForNewWindow()
    }

    /**
     * 自定义区间（日期弹层回来的）。两头都没选 = 清掉区间，退回「全部」。
     * ⚠️ 手输的窗口同样是**手动**：不再自动退档。
     */
    fun applyCustomRange(from: String?, to: String?) {
        userPickedPreset = true
        windowSettled = true // 同上：手输的窗口也算"用户已经表态"
        customFrom = from
        customTo = to
        preset = if (from == null && to == null) DatePresets.ALL else DatePresets.CUSTOM
        applyRange(from, to)
        refreshForNewWindow()
    }

    // 日期档位**不在这里算**：档位与它们的区间在 `ui/common/DatePresets`（唯一一份实现），
    // 本页只把选中的那一档翻成 from/to。自己再写一遍 `when("本月")`，
    // 就会出现"账本页的本月和订单筛选条的本月差几天"——而两边都看着对。
    // （`preset` / `customFrom` / `customTo` 几个状态声明在**文件开头**：
    //   init 块会写它们，写在 init 之后就是"打开这一页必崩"，原因见那边的注释。）

    /**
     * 口径词 —— **跟着实际窗口走**（设计规范 §4.9）：选着"全部"却在标题上写"本月"，
     * 就是对不上账的第一步。
     */
    val periodWord: String get() = when {
        // 还没盘点完 → 先写「…」：这时候写任何档位都是**假话**（窗口还没定），
        // 而"今天 → 前天"那一下正是用户说的"闪两下"里最扎眼的一半。
        !windowSettled -> "…"
        preset != DatePresets.CUSTOM -> preset
        rangeFrom == null || rangeTo == null -> DatePresets.ALL
        else -> rangeFrom!!.take(10).substring(5) + "~" + rangeTo!!.take(10).substring(5)
    }

    /**
     * 时间窗口换了之后要重取的东西。**一处写全**：漏一处就是"上面的合计写着本月、
     * 下面的明细还是上个月"，而两边都不报错。
     * ⚠️ 司机那一层不用重取：他的单**跟在账户汇总响应里**（`/freight-settlement` 的 group 自带
     *    `orders`），账户汇总重取一次，他的第二层就跟着新了。
     */
    private fun refreshForNewWindow() {
        if (tab != 0) loadAccounts()
        // 第二层（某个人的按订单账）也要跟着换窗口
        if (personKey != null && tab != 1) loadPerson()
    }

    /**
     * 侧边抽屉里那一份名单（三类账共用）。
     *
     * ⚠️ 抽屉是**选人用的**，所以它筛的只有"人"（姓名 / 手机号 / 后 4 位）——
     *    与页面上的合计无关（见 [dashboard]）。
     */
    fun drawerPersons(): List<LedgerAccountRow> = visibleAccountRows()

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

    /**
     * 从「记一笔账」那一页回来时重取一次（用户 2026-09-20 第七轮：记账改成单独一页）。
     *
     * ⚠️ 为什么不能只靠 `init`：`init` 只在 VM 第一次创建时跑一次，从记账页 `popBackStack()`
     *    回来时这一屏重新进组合但 VM 还在 —— 不重取的话列表里**没有刚记的那一笔**，
     *    用户会以为没存上，然后再记一遍（账就真的多了一笔）。
     * ⚠️ 第一次进这一页（`entered` 还是 false）不重复拉：那时 `init` 刚拉过。
     */
    private var entered = false

    fun onEnter() {
        if (!entered) {
            entered = true
            return
        }
        load()
        loadAccounts()
        if (personKey != null && tab != 1) loadPerson()
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

    // ============================================================ 第二层：某个货主 / 批发商**按订单**的账
    //
    // 状态声明在 `init {}` **之前**（见那一大段注释：写在 init 之后 = 打开这一页直接崩）。

    /** 第二层顶部那三个数（**这些单现在**的应收/已收/欠款）。 */
    fun personKpi(): Triple<Double, Double, Double> {
        val receivable = personOrders.sumOf { centsToMoney(orderReceivableCents(it)).toDouble() }
        val settled = personOrders.sumOf { (it.settledAmount.toDoubleOrNull() ?: 0.0) }
        val arrears = personOrders.sumOf { (it.arrearsAmount.toDoubleOrNull() ?: 0.0) }
        return Triple(receivable, settled, arrears)
    }

    /**
     * 点账户行 = **看他这一段的账**（第二层）。三类账走同一条路：
     *
     * · 货主 / 批发商：要另取"按送达日落在窗口里的单"（[loadPerson]，它还要找客户档案）；
     * · 司机：那几单**已经在列表响应里**（`/freight-settlement` 每个 group 自带 `orders`），
     *   再打一次后端只是把同样的数再取一遍 —— 所以司机这一层不发请求。
     *   ⚠️ 司机那笔钱的口径是 `driver_pay`（我们该给他多少），与客户应收是两套，
     *      所以他的第二层**没有核销**，只有"他跑了哪几趟、这一共多少"。
     */
    fun openPerson(row: LedgerAccountRow) {
        personKey = row.key
        personOrders = emptyList()
        personStats = emptyList()
        personCustomerId = null
        if (tab != 1) loadPerson()
    }

    /** 选择栏上的「全部」= 回到第一层（所有人）。 */
    fun selectPersonKey(key: String?) {
        if (key == null) {
            closePerson()
            return
        }
        accountRows().firstOrNull { it.key == key }?.let { openPerson(it) } ?: closePerson()
    }

    /** 返回第一层（人列表）。 */
    fun closePerson() {
        personKey = null
        personOrders = emptyList()
        personStats = emptyList()
        personCustomerId = null
    }

    /** 第二层标题：名字 + 手机号（与第一层那张行卡同一份数据，**不留两份**）。 */
    fun personTitle(): String {
        val key = personKey ?: return ""
        return accountRows().firstOrNull { it.key == key }?.let { r ->
            if (r.phone.isNullOrBlank()) r.title.ifBlank { "（没有名字）" }
            else r.title.ifBlank { r.phone } + "（" + r.phone + "）"
        } ?: "（已不在名单里）"
    }

    /** 图表标题用的短名：图上的字要短，但**必须**能看出这是谁的（不许写"他"）。 */
    fun personShortName(): String {
        val key = personKey ?: return ""
        return accountRows().firstOrNull { it.key == key }?.title?.ifBlank { null }
            ?: accountRows().firstOrNull { it.key == key }?.phone
            ?: "这个人"
    }

    /** 空列表时给一句能照着做的话（口径词 + 时间档位）。 */
    fun personTimeHint(): String = "当前是「" + periodWord + "」，可以点右上角换一个日期档位。"

    /**
     * 司机的第二层：他不是"客户应收"，而是**这一段时间我们该给他多少**
     * （口径在 `services/driver_pay.py`，与组头的 `total` 同一份）。返回 (合计, 单数)。
     */
    fun driverPersonTotal(): Pair<Double, Int> {
        val row = accountRows().firstOrNull { it.key == personKey } ?: return 0.0 to 0
        return row.total to row.count
    }

    /** 「清空勾选」= 回到整单核销（不是"什么都不收"）。 */
    fun clearSettleLines() {
        settlePicked = emptySet()
    }

    /**
     * 拉这个人的账。
     *
     * ⚠️ 窗口用 **`delivered_from/delivered_to`（送达日）**而不是下单日：
     *    账本流水的 `entry_date` 是**送达那天**，用下单日筛会漏掉
     *    「上月底下单、这月初送达」的单 —— 而账上明明有它（同一屏两个集合，谁都不报错）。
     * ⚠️ 拉完如果**这一段他没单**，顺手退档到"他最近有单的那一天"（[fallbackForPerson]）：
     *    同一条"默认档位要落到有数的地方"的规矩，否则点开每个人都是空屏。
     */
    fun loadPerson() {
        val key = personKey ?: return
        personLoading = true
        loadError = null
        viewModelScope.launch {
            try {
                val page = fetchPersonOrders(key, rangeFrom, rangeTo, withMeta = true)
                // 只留"有账意义"的单：还没送到的单不进账本（它们没有应收）
                personOrders = page.first.filter { it.deliveredAt != null || it.returnedAt != null }
                personStats = productStats(personOrders)
                personTruncated = page.second?.hasMore ?: false
                personLimit = page.second?.limit
                // 核销要客户档案：按 user_id 找（临时货主没有账号 → 找不到 → 界面如实说）
                val (kind, raw) = key.split("|", limit = 2)
                personCustomerId = if (kind == "u") {
                    container.repo.customers().firstOrNull { it.userId == raw.toLongOrNull() }?.id
                } else {
                    container.repo.customers().firstOrNull { it.name.trim() == raw.trim() }?.id
                }
                if (personOrders.isEmpty()) fallbackForPerson(key)
            } catch (e: Exception) {
                loadError = toApiException(e).message
            } finally {
                personLoading = false
            }
        }
    }

    /**
     * 某个人的账（**探测与正式加载共用一条路**，免得"探测说有、加载却是空"）。
     * 返回 (订单, 分页信息)；探测时不要分页信息（[withMeta] = false）。
     */
    private suspend fun fetchPersonOrders(
        key: String,
        from: String?,
        to: String?,
        withMeta: Boolean,
    ): Pair<List<OrderDto>, com.tapmoay.sorders.data.repo.PageMeta?> {
        val (kind, raw) = key.split("|", limit = 2)
        val page = if (kind == "u") {
            container.repo.ordersByDelivered(shipperId = raw.toLongOrNull(), deliveredFrom = from, deliveredTo = to)
        } else {
            container.repo.ordersByDelivered(tempShipperName = raw, deliveredFrom = from, deliveredTo = to)
        }
        return page.rows to if (withMeta) page.meta else null
    }

    /**
     * 这个人这一段没单 → 退到"他最近有单的那一天"（今天 → 昨天 → 前天 → 近 7 天）。
     *
     * ⚠️ 只在**还是自动档位**的时候退（[userPickedPreset] 为假）：用户自己挑了"本月"来看，
     *    点个人进来又被他退回"近 7 天"，那是抢方向盘 —— 与 `init` 里那次 `pickWindow` 是同一条
     *    规矩，所以两处共用一个开关（"默认"只在你还没表态的时候替你选）。
     */
    private suspend fun fallbackForPerson(key: String) {
        if (userPickedPreset) return
        for (label in DatePresets.AUTO_LADDER) {
            val r = DatePresets.rangeOf(label, LocalDate.now()) ?: continue
            val has = try {
                fetchPersonOrders(key, r.first, r.second, withMeta = false).first
                    .any { it.deliveredAt != null || it.returnedAt != null }
            } catch (e: Exception) {
                false
            }
            if (has) {
                if (label != preset) switchPreset(label)
                return
            }
        }
    }

    // ============================================================ 就地核销（整单 / 按商品）
    //
    // 用户原话：「包括我们核销账也是在这里核销，我们可以点击订单点击核销，
    //   核销订单的这里可以**全部核销**，也可以**按商品进行核销**」。
    // 状态声明在 `init {}` 之前（同上）。

    fun openSettle(o: OrderDto) {
        settleTarget = o
        settlePicked = emptySet()
        settleMethod = "cash"
    }

    fun closeSettle() {
        settleTarget = null
        settlePicked = emptySet()
    }

    fun toggleSettleLine(lineId: Long) {
        settlePicked = if (lineId in settlePicked) settlePicked - lineId else settlePicked + lineId
    }

    /** 「全部核销」：把所有**还能收**的行勾上（已退完的行本来就没有金额）。 */
    fun pickAllSettleLines() {
        val o = settleTarget ?: return
        settlePicked = o.orderProducts.map { it.id }.toSet()
    }

    /**
     * 这次核销的金额（元，两位小数）。
     *
     * ⚠️ 一行都没勾 = **整单核销**，金额取这一单的**欠款**（不是把行金额全加起来 ——
     *    退过货的单上那个数比该收的多）。勾了行 = 那些行的**应收**之和。
     *    两者都必须与后端算出的数**逐分相同**（后端就是这么校验的）。
     */
    fun settleAmount(): String {
        val o = settleTarget ?: return "0.00"
        if (settlePicked.isEmpty()) return o.arrearsAmount.ifBlank { "0.00" }
        val cents = o.orderProducts.filter { it.id in settlePicked }.sumOf { lineReceivableCents(it) }
        return centsToMoney(cents)
    }

    /** 这一单还能不能核销（已收清 / 已退货的单没有可收的钱）。 */
    fun canSettle(o: OrderDto): Boolean =
        !o.paid && o.status.uppercase() != "CANCELLED" && o.status.uppercase() != "RETURNED" &&
            (o.arrearsAmount.toDoubleOrNull() ?: 0.0) > 0.0

    // ============================================================ 批量核销（点合计 → 核销全部）
    //
    // 用户 2026-09-20：「如果是今天，那就是今天的**所有订单**；如果是这周，那就这周的所有订单。
    //   这样子我们就可以直接点这个**合计**将它核销掉，就不用一个一个的去核销订单了，
    //   它相当于一个**可控的批量处理**」。
    //
    // ⚠️ 三件事必须写清楚，否则这个按钮会变成"把钱收错"的入口：
    //   ① **只有选中某个人**才给批量核销（用户明说"全部（所有人）时那个合计不能批量核销"）——
    //      见 [openSettleAll] 的那道门；
    //   ② 一次核销**一个收款人**：收款单绑的是这个人的客户档案，跨人批量会记到别人头上；
    //   ③ 金额 = 各单**欠款**之和（`arrears_amount`，后端算的），一分都不许在这里自己减。

    /** 这一段里**还能核销**的单（这个人的）。 */
    fun settleAllTargets(): List<OrderDto> = personOrders.filter { canSettle(it) }

    /** 批量核销的金额（各单欠款之和，两位小数）。 */
    fun settleAllAmount(): String =
        centsToMoney(settleAllTargets().sumOf { orderArrearsCents(it) })

    fun openSettleAll() {
        // 门：没选人就没有"这个人的合计"可点（用户明确否掉了"全部时批量核销"）。
        if (personKey == null || tab == 1) return
        if (settleAllTargets().isEmpty()) {
            error = "这一段没有还没结清的单。"
            return
        }
        settleMethod = "cash"
        settleAllOpen = true
    }

    fun closeSettleAll() {
        settleAllOpen = false
    }

    fun submitSettleAll() {
        val customerId = personCustomerId
        val targets = settleAllTargets()
        if (customerId == null) {
            error = "这位货主没有客户档案，核销记不到谁头上。" +
                "请先到「货主管理」把这个账号关联成客户（或建一份档案），再回来核销。"
            return
        }
        if (targets.isEmpty()) {
            error = "这一段没有还没结清的单。"
            return
        }
        settleSubmitting = true
        error = null
        viewModelScope.launch {
            try {
                container.repo.createReceipt(
                    ReceiptCreateRequest(
                        customerId = customerId,
                        amount = settleAllAmount(),
                        method = settleMethod,
                        receivedAt = LocalDate.now().toString(),
                        orderIds = targets.map { it.id },
                        settleMode = "itemized",
                    )
                )
                actionResult = "已核销 " + targets.size + " 单 ¥" + settleAllAmount()
                closeSettleAll()
                loadPerson()
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                settleSubmitting = false
            }
        }
    }

    fun submitSettle() {
        val o = settleTarget ?: return
        val customerId = personCustomerId
        if (customerId == null) {
            error = "这位货主没有客户档案，核销记不到谁头上。" +
                "请先到「货主管理」把这个账号关联成客户（或建一份档案），再回来核销。"
            return
        }
        if (!canSettle(o)) {
            error = "这一单已经没有可收的钱了（已收清 / 已退货 / 已撤销）。"
            return
        }
        settleSubmitting = true
        error = null
        viewModelScope.launch {
            try {
                container.repo.createReceipt(
                    ReceiptCreateRequest(
                        customerId = customerId,
                        amount = settleAmount(),
                        method = settleMethod,
                        receivedAt = LocalDate.now().toString(),
                        orderIds = listOf(o.id),
                        orderProductIds = settlePicked.toList(),
                        settleMode = "itemized",
                    )
                )
                actionResult = "已核销 " + o.orderNo + " ¥" + settleAmount()
                closeSettle()
                loadPerson()
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                settleSubmitting = false
            }
        }
    }
}
