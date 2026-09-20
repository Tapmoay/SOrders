package com.tapmoay.sorders.ui.driver

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.data.repo.toApiException
import com.tapmoay.sorders.ui.common.DatePresets
import com.tapmoay.sorders.util.formatDateTime
import com.tapmoay.sorders.util.moneyToDouble
import kotlinx.coroutines.launch
import java.time.LocalDate

/**
 * 司机「我的账本」：**时间档位（药丸）+ 趋势图 + 合计 + 明细**。
 *
 * 2026-09-20 用户点名把时间控件换成与司机任务页一样的形态：
 * 「时间也按那个（药丸）进行，预设默认是今天的，如果今天没有单则也按老规则一直推到有单为止」。
 * ⛔ 取数口径**一个字没动**：仍走 `repo.freightSettlementRange`（司机应得只有 `services/driver_pay.py` 一处算）。
 */
class DriverFreightViewModel(private val container: AppContainer) : ViewModel() {

    /** 明细行（订单维度） */
    data class FreightRow(
        val orderId: Long,
        val orderNo: String,
        val deliveredAt: String?,
        /** **司机应得**（后端 `driver_pay.pay_for_order` 算的，与司机账单同源）。 */
        val payTotal: String,
        /** 货主那头的运费（提成基数）；null = 还没定价。**不等于司机应得**。 */
        val freightFee: String?,
        /** 这一单的**计件**部分（司机应得 = 计件 + 提成）。 */
        val payPiece: String,
        /** 这一单的**提成**部分（用户 2026-09-20：「每个订单会显示他每个单抽成多少」）。 */
        val payCommission: String,
        val desc: String,
        val address: String,
        /**
         * 起点地址（线路上的"从这出发"）。
         * ⚠️ **后端目前不出** → 恒为 null（订单表没有起点列），所以现在卡片只显示终点。
         *    用户 2026-09-20：「有起点和终点（路线）的时候就自动显示，没有路线就显示终点」。
         */
        val origin: String? = null,
    )

    var rows by mutableStateOf<List<FreightRow>>(emptyList())
    var loading by mutableStateOf(false)
    var error by mutableStateOf<String?>(null)

    /** 趋势图类型：line / bar */
    var chartType by mutableStateOf("line")

    // ⚠️ 下面这几个**必须声明在 `init` 之前**：Kotlin 的属性初始化与 init 块按**书写顺序**执行，
    //    写在 init 之后的话，init 里那句赋值会抛
    //    `MutableState.setValue … on a null object reference` —— **打开这一页直接崩**
    //    （账本页 2026-09-20 真机栽过一次）。判据：`_tools/qa/_check_vm_state_before_init.py`。

    /** 当前档位（默认**今天**；今天没单时 `init` 那次盘点会往后退到有单的那一档）。 */
    var preset by mutableStateOf(DatePresets.TODAY)
        private set

    /** 「自定义」那一档的两端（用户在日期弹层里选的）。 */
    var customFrom by mutableStateOf<String?>(null)
        private set
    var customTo by mutableStateOf<String?>(null)
        private set

    /**
     * **窗口定下来了没有**（2026-09-21）。
     *
     * 用户报的毛病是"点进去闪两下才跳到有数的那一段"——根子是**先按今天拉了一次**、
     * 再异步退档，于是最坏画三帧。现在先探测、定下来只取一次数；这一位为假时整页 loading。
     * ⚠️ 必须声明在 `init` **之前**（`init` 会写它，写在后面就是"打开这一页必崩"）。
     */
    var windowSettled by mutableStateOf(false)
        private set

    /** 用户**手动**挑过档位没有 —— 挑过就永不自动改（见 `init` 里那次 `pickWindow`）。 */
    private var userPickedPreset = false

    init {
        viewModelScope.launch {
            container.realtimeHub.refreshLedger.collect { load() }
        }
        // 默认档位 = 今天；今天没单就往后退到有单的那一档。
        // ⚠️ **先盘点、再取数**（2026-09-21 用户报的"闪两下"）：原来是先 `load()` 拉今天
        //    （多半是空的）再异步退档 —— 最坏画三帧（今天·加载 → 今天·空态 → 有数那一档）。
        //    现在只做**探测**（每档 limit=1），定下来之后**只取一次数**；
        //    页面那边用 [windowSettled] 把"还没定下来"那一帧挡成 loading。
        viewModelScope.launch {
            if (!userPickedPreset) {
                switchPreset(DatePresets.pickWindow(DRIVER_PRESET_LADDER) { periodHasData(it) })
            } else {
                load()
            }
            windowSettled = true
        }
    }

    // ⚠️ 合计与趋势图都必须用 **payTotal（司机应得）**，不能用 freightFee（货主运费）：
    //    司机挂了"每单 300 + 运费 5%"这类规则时两者差得很远（账单 675 / 旧算法 1500），
    //    而页面标题写的是"当前范围内合计"——用运费求和就等于司机拿一个公司不认的数来对账。
    fun total(): Double = rows.sumOf { moneyToDouble(it.payTotal) }

    val periodStart: String get() = windowOf(preset).first
    val periodEnd: String get() = windowOf(preset).second

    /**
     * 某一档对应的窗口（`YYYY-MM-DD`）。
     *
     * ⚠️ **「自定义」必须在这里接上 `customFrom/customTo`**：[DatePresets.rangeOf] 对它返回 null
     *    （它说得很清楚：「自定义」的区间由调用方给）。2026-09-20 实测漏了这一支的后果：
     *    药丸上写着 `09-15~09-15`、请求却发的是"全部"（`2000-01-01`~今天），
     *    列表把半年多的单全列出来 —— **口径词和实际窗口对不上**，而两边都不报错。
     * 「全部」在 [DatePresets.rangeOf] 里也返回 null（它本来就不是日期条件）—— 这条接口 from/to 必填，
     * 所以给它一个足够宽的起点（见 [ALL_FROM]）。
     */
    private fun windowOf(label: String): Pair<String, String> = when (label) {
        DatePresets.CUSTOM -> (customFrom ?: ALL_FROM) to (customTo ?: LocalDate.now().toString())
        else -> DatePresets.rangeOf(label, LocalDate.now()) ?: (ALL_FROM to LocalDate.now().toString())
    }

    /** 用户自己挑的档位（右上角那个药丸 → 档位清单）。**手动**：从此不再自动退档。 */
    fun applyPreset(label: String) {
        userPickedPreset = true
        // 用户已经表态 = 窗口就算是定下来了（不必再等 init 那次探测跑完才开闸）
        windowSettled = true
        switchPreset(label)
    }

    /**
     * 自定义区间（日期弹层回来的）。两头都没选 = 清掉区间，退回「全部」。
     * 手输的窗口同样是**手动**：不再自动退档。
     *
     * ⚠️ 日期换算**不在这里做**：档位与它们的区间只有 `ui/common/DatePresets` 一份实现。
     */
    fun applyCustomRange(from: String?, to: String?) {
        userPickedPreset = true
        windowSettled = true // 同上：手输的窗口也算"用户已经表态"
        customFrom = from
        customTo = to
        preset = if (from == null && to == null) DatePresets.ALL else DatePresets.CUSTOM
        load()
    }

    /** 真正的换档（自动退档与手动换档都走这一条路，**不许各写一份**）。 */
    private fun switchPreset(label: String) {
        preset = label
        load()
    }

    /**
     * 这一档有没有单（**只探测、不动页面状态**）。
     *
     * 判据与页面自己的取数**同源**（同一个接口、同一套 from/to）—— 换个接口去猜"有没有单"，
     * 就会出现"退档到的那一档页面还是空的"。
     * ⚠️ 探测失败（网络/权限）当"没单"处理：不能因为探测不通就把用户按在一个看不见的窗口上。
     */
    private suspend fun periodHasData(label: String): Boolean {
        val (f, t) = windowOf(label)
        return try {
            container.repo.freightSettlementRange(f + " 00:00:00", t + " 23:59:59")
                .groups.firstOrNull()?.orders?.isNotEmpty() == true
        } catch (e: Exception) {
            false
        }
    }

    /**
     * 药丸上写的那几个字 —— **跟着实际窗口走**（设计规范 §4.9）：选着「今天」却在药丸上写「本月」，
     * 就是"以为看的是今天、其实看的是本月"的第一步。
     */
    val periodWord: String
        get() = when {
            // 还没盘点完 → 先写「…」（这时写任何档位都是假话）
            !windowSettled -> "…"
            preset != DatePresets.CUSTOM -> preset
            customFrom == null || customTo == null -> DatePresets.ALL
            else -> customFrom!!.take(10).substring(5) + "~" + customTo!!.take(10).substring(5)
        }

    /**
     * 趋势图的点：`(x 轴标签, 金额)`。
     *
     * **粒度跟着窗口走**（用户 2026-09-20：「如果是今天的话，X 轴就是按**时段**；昨天也是按时段；
     * 这周 / 上周这种一周的，X 轴就变成为**这一周的天**」）：
     * · 单日档（今天 / 昨天 / 前天 / 自定义选的同一天）→ 按**小时**分桶，标签 `18时`
     *   —— 一直按日期分桶的话，选「今天」整张图只有**一个点**，趋势图等于没用；
     * · 跨日档（这周 / 上周 / 近 7 天 / 本月 / 上月）→ 按**天**分桶，标签 `09/15`。
     *
     * ⚠️ 按 key **排序**后再给出去：分桶用的是 `LinkedHashMap`，不排序就跟着后端返回顺序走
     *    （后端倒序时整张图就是倒的），而"图反了"很难被一眼看出来。
     */
    val chartSeries: List<Pair<String, Double>> get() {
        val singleDay = periodStart == periodEnd
        val map = LinkedHashMap<String, Double>()
        rows.forEach { e ->
            // `deliveredAt` 已经是**设备时区**的 `MM-dd HH:mm`（见 load 里的 formatDateTime）
            val raw = e.deliveredAt ?: ""
            if (raw.length < 11) return@forEach
            // 单日：到小时（"09-15 20"）；跨日：到天（"09-15"）
            val key = if (singleDay) raw.take(8) else raw.take(5)
            map[key] = (map[key] ?: 0.0) + moneyToDouble(e.payTotal)
        }
        return map.entries
            .sortedBy { it.key }
            .map { (k, v) ->
                (if (singleDay) k.substring(6, 8) + "时" else k.replace("-", "/")) to v
            }
    }

    fun load() {
        loading = rows.isEmpty()
        error = null
        viewModelScope.launch {
            try {
                val dto = container.repo.freightSettlementRange(periodStart + " 00:00:00", periodEnd + " 23:59:59")
                val me = dto.groups.firstOrNull()
                rows = me?.orders?.map {
                    FreightRow(
                        orderId = it.orderId,
                        orderNo = it.orderNo,
                        // ⚠️ 必须走 `formatDateTime`（naive 串按 UTC 解释、再换算到**设备时区**）：
                        //    直接 `take(16)` 印出来的是 **UTC**，而这条接口的窗口是按**当地日**算的 ——
                        //    于是"明细写着 09-15 18:18、筛 09-15 却查不到它"（它当地其实是 09-16 02:18），
                        //    两边都不报错。模拟器时区恰好是 UTC，所以这个错**只在真机上看得见**。
                        deliveredAt = formatDateTime(it.deliveredAt),
                        payTotal = it.payTotal,
                        freightFee = it.freightFee,
                        payPiece = it.payPiece,
                        payCommission = it.payCommission,
                        desc = it.deliveryDescription,
                        address = it.addressDetail,
                        origin = it.originAddress,
                    )
                } ?: emptyList()
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                loading = false
            }
        }
    }

    companion object {
        /**
         * 「全部」档的起点：司机不可能有 2000 年的单，拿它当"不限"用
         * （这条接口的 from/to 都是必填的日期时刻）。
         */
        private const val ALL_FROM = "2000-01-01"
    }
}
