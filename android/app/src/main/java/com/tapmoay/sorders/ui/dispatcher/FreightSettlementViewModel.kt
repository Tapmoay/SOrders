package com.tapmoay.sorders.ui.dispatcher

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.core.UserSearch
import com.tapmoay.sorders.data.remote.dto.FreightSettlementDto
import com.tapmoay.sorders.data.remote.dto.FreightSettlementGroupDto
import com.tapmoay.sorders.data.remote.dto.OrderDto
import com.tapmoay.sorders.data.repo.toApiException
import com.tapmoay.sorders.ui.common.DatePresets
import kotlinx.coroutines.launch
import java.time.LocalDate

/** 一位司机在这份结算里的 key（抽屉选中态、`selectDriver` 收到的都是它，**不许两处各拼一份**）。 */
internal fun driverKey(g: FreightSettlementGroupDto): String = "d|" + g.driverId

/**
 * 司机账 · 运费结算（**侧边抽屉选人 + 顶栏右上角档位药丸**；2026-10-07 CHG-0075 合并后定稿）。
 *
 * ## 这一页原来是两页
 *
 * 「账本管理 → 司机账」（`Routes.dispatcherLedger(1)`）与工作台那格「司机运费结算」。
 * 用户 2026-10-07 说（原话见 `docs/changes/CHG-0075.md`）：
 * > 还有一个就是将司机账，就是账本管理的司机账，以及司机运费结算啊，这 2 个直接合并成一个。
 *
 * 合并之后**只有一个入口**：账本管理入口页那格「司机账 · 运费结算」（路由 `Routes.FREIGHT_SETTLEMENT`）。
 * 司机那一层**没有核销**（司机那笔钱的口径是"按规则该给他多少"，不是应收）—— 这一条没变。
 *
 * | 谁 | 用什么形态 | 为什么 |
 * |---|---|---|
 * | **时间** | 顶栏右上角一个**药丸**，点开是**档位清单**（`DateFilterDialogs`：全部/今天/昨天/…/本月/上月/近一年 + 自定义） | 用户 2026-10-07 的口径：「时间改用账本那套档位」。2026-09-22 那版**年月网格**（「月份的选择形式跟我们平常的不一样」）就此**被覆盖** —— 同一个项目里两个时间控件两套写法，用户得学两次，判据也钉不住 |
 * | **人员** | 页面上**一行入口** → 打开**侧边抽屉**（抽屉里带搜索） | 用户 2026-09-22：「不要按照这样子的**商品的管理**啊……直接换那个**类似于货主的账本管理**的那种形式，是那个**左侧的抽屉栏**在那里选择人物，**也可以在那里搜索**」 |
 * | **数据** | 没选人 = 这一段一共要付多少 + 每人一行（点一行进他的结算）；选了人 = 他的统计 + 价格明细（点一行**就地展开**那一单） |
 *
 * ## 默认档是「本月」——**只换选择形式，不换默认窗口**
 *
 * 这一页问的还是"这个月该给他多少"（月度结算），所以初值仍是本月；
 * 换掉的是**怎么选**（档位清单），不是**默认选哪个**。
 *
 * ## 选中态存的是**字符串 key**（`d|<司机 id>`），不是 DTO
 *
 * 换窗口会整批换掉 `data`，存对象的话选中的那位会指向一个已经被替换掉的旧实例
 * （界面照样亮着，但读出来的单数/金额是上一个窗口的）。
 *
 * ## ⚠️ 换窗口**不清掉选中的人**
 *
 * key 是 `d|<司机 id>`，**与时间窗口无关**：看着张师傅的九月账切到八月，想看的多半还是张师傅。
 * 清掉选中、界面回落到第一位司机 —— 那等于"我明明在看的人被换掉了，还没提示"。
 * 现在窗口里没有他时页面**如实说**「张师傅在这一段没有已计价的单」（见 [selectedName]）。
 *
 * ## 时间口径
 *
 * 只有一条路：`GET /freight-settlement` 的 `from=/to=`。后端另有 `month=` 那条路
 * （AI 工具在用，`AiWriteDataSource`），这一页不再走它 —— 档位翻出来的区间与月份是**同源**的，
 * 走两条路迟早出现"本月这一档两个页面差一天"。
 */
class FreightSettlementViewModel(private val container: AppContainer) : ViewModel() {

    var data by mutableStateOf<FreightSettlementDto?>(null)
    var loading by mutableStateOf(false)
    var error by mutableStateOf<String?>(null)

    /**
     * 选中的**档位**（`DatePresets` 里的一个词，如「本月」「全部」「自定义」）。
     *
     * 档位与区间的换算**只有** `DatePresets.rangeOf` 一处：这一页只把选中的那一档翻成 from/to。
     * 自己再写一遍 `when(本月)`，就会重演"账本页的本月和订单筛选条的本月差几天"那个老毛病。
     */
    var preset by mutableStateOf(DatePresets.THIS_MONTH)

    /** 「自定义」那两头（`DateFilterDialogs` 要把它们回填给日期弹层，所以得记着）。 */
    var customFrom by mutableStateOf<String?>(null)
    var customTo by mutableStateOf<String?>(null)

    /** 当前窗口；「全部」那一档是 `null`/`null`（取数时换成 [DatePresets.WIDE_FROM]/[DatePresets.WIDE_TO]）。 */
    var rangeFrom by mutableStateOf<String?>(null)
    var rangeTo by mutableStateOf<String?>(null)

    /** 抽屉里的搜索词（姓名 / 手机号 / 后 4 位，规则在 `core/UserSearch`）。 */
    var query by mutableStateOf("")

    /** 正在看哪位司机（`d|<id>`）；**空串 = 全部**（页面上是"这一段一共要付多少 + 每人一行"）。 */
    var selectedKey by mutableStateOf("")

    /**
     * 选中那位的名字 —— 与 [selectedKey] 分开存是有原因的：
     * 换到一个**他没有单**的窗口时，`data.groups` 里根本没有他，界面上就只剩一个 key，
     * 于是那句「他在这一段没有单」会变成「他在这一段没有单」但**说不出他是谁**。
     */
    var selectedName by mutableStateOf("")

    /**
     * 运费还没定价的单（`unpriced=true`：**已经派出去了**、运费还是空的，连已送达的也算）。
     *
     * 为什么结算页要知道它（E2E 走查 P19）：这一页只算"已送达且已计价"的单，待定价的单
     * 在这张表里**根本不出现** —— 派单员核「王强这单运费多少」时看到的是一片空，
     * 而钱躺在「运费模板 → 待定价」里，两个页面之间原来连一句话都没有。
     */
    var unpricedRows by mutableStateOf<List<OrderDto>>(emptyList())

    /** 待定价那边还有更多（`X-Truncated`）—— 报数时只能说「N 单以上」，不许说确数。 */
    var unpricedMore by mutableStateOf(false)

    /**
     * 就地展开的那一单（明细行点一下展开、再点一下收起来）。
     *
     * 用户 2026-09-20 说过「他的那个下面明细的订单卡片是可以点击的，点击就是原始的订单信息」——
     * 点一下**先看这一单本身**（就地展开），展开块里那个「打开订单」才是跳去详情页的门。
     */
    var expandedOrderId by mutableStateOf<Long?>(null)
    var expandedOrder by mutableStateOf<OrderDto?>(null)
    var expandedOrderLoading by mutableStateOf(false)

    init {
        // 初值 = 本月：先把这一档翻成区间，再取一次数（只取一次，没有"先画一版空态再换"那一下）
        val r = DatePresets.rangeOf(DatePresets.THIS_MONTH, LocalDate.now())
        rangeFrom = r?.first
        rangeTo = r?.second
        load()
    }

    /**
     * 药丸上的短标签：档位词本身（`本月` / `全部` / …）；自定义时显示那一段日期（`09-01~09-20`）。
     *
     * 自定义时**显示那段日期本身**而不是"自定义"三个字：这一页上必须有**一个地方**
     * 写着"这些数字是哪一段时间的"，否则「共 3 位司机 · 应得 ¥860」没有范围可对。
     */
    val periodLabel: String
        get() {
            if (preset != DatePresets.CUSTOM) return preset
            val from = rangeFrom
            val to = rangeTo
            return if (from != null && to != null) shortDate(from) + "~" + shortDate(to) else DatePresets.ALL
        }

    /**
     * 句子里的口径词：`本月` / `全部时间` / `所选区间`（自定义那两端没选全时按"全部时间"说）。
     *
     * 与 [periodLabel] 分开是因为中文句子要通顺（「所选区间共 3 位司机」），
     * 而药丸上要塞得下具体日期。两个都**只有一个来源**，不会一处说"本月"、另一处说别的。
     */
    val periodWord: String
        get() = when {
            preset == DatePresets.ALL -> "全部时间"
            preset != DatePresets.CUSTOM -> preset
            rangeFrom != null && rangeTo != null -> "所选区间"
            else -> "全部时间"
        }

    /**
     * 抽屉里那一份名单（**只有"人"这一层过滤**）。
     *
     * ⚠️ 抽屉是**选人用的**，所以它筛的只有姓名/手机号；页面上的合计与每人一行
     * **不受它影响**（关掉抽屉之后，屏幕上那些数必须还是所有人的 ——
     * 让搜索结果顶掉合计，用户就会照着筛过的数去对账）。
     */
    fun drawerDrivers(): List<FreightSettlementGroupDto> =
        UserSearch.filter(data?.groups.orEmpty(), query, { it.driverName }, { it.driverPhone })

    /** 选一位司机（`""` = 回到「全部」）。名字一起记下来，见 [selectedName]。 */
    fun selectDriver(key: String) {
        selectedKey = key
        selectedName = data?.groups?.firstOrNull { driverKey(it) == key }?.driverName.orEmpty()
    }

    /** 用户挑了某一档（档位清单点一下）。「自定义」不从这里进（见 [applyCustomRange]）。 */
    fun applyPreset(label: String) {
        preset = label
        val r = DatePresets.rangeOf(label, LocalDate.now())
        applyRange(r?.first, r?.second)
    }

    /**
     * 应用一段自定义时间；两头都是 `null` = 清掉区间（弹层里"两头都没选"就是它 → 回到「全部」）。
     *
     * ⚠️ `DateFilterDialogs` 里选「自定义」时**不调** `onPickPreset`，而是接着开日期弹层，
     *    所以"自定义"这个档位词只在这里落定。
     */
    fun applyCustomRange(from: String?, to: String?) {
        customFrom = from
        customTo = to
        preset = if (from == null && to == null) DatePresets.ALL else DatePresets.CUSTOM
        applyRange(from, to)
    }

    private fun applyRange(from: String?, to: String?) {
        rangeFrom = from
        rangeTo = to
        load()
    }

    fun load() {
        loading = true
        error = null
        // 窗口换了，展开的那一单属于上一个窗口的列表 —— 收起来（否则新列表里可能停着一个不相干的 peek）
        expandedOrderId = null
        expandedOrder = null
        val from = rangeFrom ?: DatePresets.WIDE_FROM
        val to = rangeTo ?: DatePresets.WIDE_TO
        viewModelScope.launch {
            // 顺带问一句"还有多少单没有运费"（与主表**各失败各的**，见 loadUnpriced）
            loadUnpriced()
            try {
                // 起止都按**当地整天**算（结束那天要含进去）：不补 `23:59:59` 的话，
                // 选"到今天"会把今天送达的单整批漏掉 —— 而界面上看不出少了一天，
                // 用户只会觉得"今天的账没进来"。后端会把这两个墙上时间换算成 UTC 再比。
                data = container.repo.freightSettlementRange("$from 00:00:00", "$to 23:59:59")
                // ⚠️ 这里**故意不清 selectedKey**：它是 `d|<司机 id>`，与时间窗口无关
                //    （看着张师傅的九月账切到八月，想看的多半还是张师傅）。
                //    他在新窗口里没有单时，页面会如实说"他在这一段没有单"——见 selectedName 的注释。
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                loading = false
            }
        }
    }

    /**
     * 点一下明细行：展开那一单（再点一下收起来）。
     *
     * 形状与账本页的 `DispatcherLedgerViewModel.toggleOrderDetail` **一致**（同一个交互两处实现，
     * 差别只会在"拉失败时说什么"这类细节上冒出来）——拉失败要**说出来**，
     * 不能显示成"这一单没有内容"（两句是完全不同的结论）。
     */
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

    /**
     * 问一句「还有多少单没有运费」（E2E 走查 P19：待定价那边的路要能回到这一页）。
     *
     * ⛔ 它失败**不能**把整页拖红：这一页的主体是已计价的账，待定价那一行只是**多给一条路**。
     *    失败时按"没有"处理（那一行不显示）—— 页面上其余的东西该显示什么还显示什么。
     */
    private suspend fun loadUnpriced() {
        try {
            val page = container.repo.unpricedOrders()
            unpricedRows = page.rows
            unpricedMore = page.meta.hasMore
        } catch (e: Exception) {
            unpricedRows = emptyList()
            unpricedMore = false
        }
    }

    /** `2026-09-01` → 当年省略年份（`09-01`），跨年时留着年份（否则"01-05"是哪年说不清）。 */
    private fun shortDate(d: String): String =
        if (d.length >= 10 && d.take(4) == LocalDate.now().year.toString()) d.substring(5) else d
}
