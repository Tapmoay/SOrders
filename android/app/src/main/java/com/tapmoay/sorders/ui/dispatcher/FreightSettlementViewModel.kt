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
import com.tapmoay.sorders.data.repo.toApiException
import kotlinx.coroutines.launch
import java.time.LocalDate
import java.time.format.DateTimeFormatter

/** 一位司机在这份结算里的 key（抽屉选中态、`selectDriver` 收到的都是它，**不许两处各拼一份**）。 */
internal fun driverKey(g: FreightSettlementGroupDto): String = "d|" + g.driverId

/**
 * 司机运费结算（**侧边抽屉选人 + 顶栏右上角月份**，2026-09-22 用户第二轮定稿）。
 *
 * | 谁 | 用什么形态 | 为什么 |
 * |---|---|---|
 * | **时间** | 顶栏右上角一个**药丸**，点开是**年月网格**（年份左右翻 + 12 个月格子） | 用户：「也可以按照**右上角一个时间**（栏），但是**月份的选择形式跟我们平常的不一样**」——位置与账本页一致，**选择形式**是月历式的（不是那列档位清单） |
 * | **人员** | 页面上**一行入口** → 打开**侧边抽屉**（抽屉里带搜索） | 用户 2026-09-22：「不要按照这样子的**商品的管理**啊……直接换那个**类似于货主的账本管理**的那种形式，是那个**左侧的抽屉栏**在那里选择人物，**也可以在那里搜索**」 |
 *
 * ## 选中态存的是**字符串 key**（`d|<司机 id>`），不是 DTO
 *
 * 换月份会整批换掉 `data`，存对象的话选中的那位会指向一个已经被替换掉的旧实例
 * （界面照样亮着，但读出来的单数/金额是上个月的）。
 *
 * ## ⚠️ 换窗口**不再把选中清掉**（与上一版的行为差别的唯一一处）
 *
 * key 是 `d|<司机 id>`，**与时间窗口无关**：看着张师傅的九月账切到八月，想看的多半还是张师傅。
 * 上一版换窗口会清掉选中、界面回落到第一位司机 —— 那等于"我明明在看的人被换掉了，还没提示"。
 * 现在窗口里没有他时页面**如实说**「张师傅在八月没有已计价的单」（见 [selectedName]）。
 *
 * ## 时间口径（2026-09-20 用户要求）
 * > 司机运费结账的那个工作台，他除了上个月上上个月，他还可以选择时间进行查看的。
 *
 * 月份与自定义区间两条路径打的是**同一个后端接口**
 * （`GET /freight-settlement`：`month=` 与 `from=/to=`），口径也**必须**是同一个
 * （已送达、已计价、按送达时间落在这个窗口里，隔离区的单不算）。
 * 所以一换窗口，页面上那几句话也得跟着换（[periodWord]）——
 * 自定义区间时还写"本月…"就是在说假话，而数字本身又没法自证是哪一段的。
 */
class FreightSettlementViewModel(private val container: AppContainer) : ViewModel() {

    var data by mutableStateOf<FreightSettlementDto?>(null)
    var loading by mutableStateOf(false)
    var error by mutableStateOf<String?>(null)
    var month by mutableStateOf(currentMonth())

    /** 自定义区间（**两头都非空**才生效）；`null` = 走月份那条路。 */
    var rangeFrom by mutableStateOf<String?>(null)
    var rangeTo by mutableStateOf<String?>(null)

    /** 抽屉里的搜索词（姓名 / 手机号 / 后 4 位，规则在 `core/UserSearch`）。 */
    var query by mutableStateOf("")

    /** 正在看哪位司机（`d|<id>`）；**空串 = 全部**（页面上是"这个月一共要付多少 + 每人一行"）。 */
    var selectedKey by mutableStateOf("")

    /**
     * 选中那位的名字 —— 与 [selectedKey] 分开存是有原因的：
     * 换到一个**他没有单**的月份时，`data.groups` 里根本没有他，界面上就只剩一个 key，
     * 于是那句「他在这个月没有单」会变成「他在这个月没有单」但**说不出他是谁**。
     */
    var selectedName by mutableStateOf("")

    init {
        load()
    }

    val isCustomRange: Boolean get() = rangeFrom != null && rangeTo != null

    /**
     * 标题与药丸上的短标签：`本月` / `上月` / `上上月` / `2025年12月` / `09-01~09-20`。
     *
     * 自定义时**显示那段日期本身**而不是"自定义"三个字：这一页上必须有**一个地方**
     * 写着"这些数字是哪一段时间的"，否则「共 3 位司机 · 应得 ¥860」没有范围可对。
     */
    val periodLabel: String
        get() {
            val from = rangeFrom
            val to = rangeTo
            return if (from != null && to != null) shortDate(from) + "~" + shortDate(to)
            else monthWord(month)
        }

    /**
     * 句子里的口径词：`本月` / `上月` / `上上月` / `所选区间`。
     *
     * 与 [periodLabel] 分开是因为中文句子要通顺（「所选区间共 3 位司机」），
     * 而标题上要塞得下日期。两个都**只有一个来源**，不会一处说"本月"、另一处说别的。
     */
    val periodWord: String get() = if (isCustomRange) "所选区间" else monthWord(month)

    fun currentMonth(): String = LocalDate.now().format(MONTH_FMT)

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

    /**
     * 换一个月 = 回到月份那条路（自定义区间就此清掉，否则界面会同时亮着两个"选中"）。
     *
     * ⚠️ 名字**不能**叫 `setMonth`：`var month` 的属性 setter 在 JVM 上就是 `setMonth(String)`，
     *    两者签名撞车（编译期 `Platform declaration clash`）。
     */
    fun pickMonth(target: String) {
        rangeFrom = null
        rangeTo = null
        month = target
        load()
    }

    /** 应用一段自定义时间；两头都是 `null` = 清掉区间（弹层里"两头都没选"就是它）。 */
    fun applyRange(from: String?, to: String?) {
        rangeFrom = from
        rangeTo = to
        load()
    }

    fun load() {
        loading = true
        error = null
        val from = rangeFrom
        val to = rangeTo
        viewModelScope.launch {
            try {
                data = if (from != null && to != null) {
                    // 起止都按**当地整天**算（结束那天要含进去）：不补 `23:59:59` 的话，
                    // 选"到今天"会把今天送达的单整批漏掉 —— 而界面上看不出少了一天，
                    // 用户只会觉得"今天的账没进来"。后端会把这两个墙上时间换算成 UTC 再比。
                    container.repo.freightSettlementRange("$from 00:00:00", "$to 23:59:59")
                } else {
                    container.repo.freightSettlement(month)
                }
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

    private fun monthWord(m: String): String {
        val now = LocalDate.now()
        return when (m) {
            now.format(MONTH_FMT) -> "本月"
            now.minusMonths(1).format(MONTH_FMT) -> "上月"
            now.minusMonths(2).format(MONTH_FMT) -> "上上月"
            // 更早的月份直接写出来（"前年"这种词没有信息量，用户要的是"哪一段"）
            else -> m.replace("-", "年") + "月"
        }
    }

    /** `2026-09-01` → 当年省略年份（`09-01`），跨年时留着年份（否则"01-05"是哪年说不清）。 */
    private fun shortDate(d: String): String =
        if (d.length >= 10 && d.take(4) == LocalDate.now().year.toString()) d.substring(5) else d

    private companion object {
        val MONTH_FMT: DateTimeFormatter = DateTimeFormatter.ofPattern("yyyy-MM")
    }
}
