package com.tapmoay.sorders.ui.dispatcher

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.data.remote.dto.FreightSettlementDto
import com.tapmoay.sorders.data.repo.toApiException
import kotlinx.coroutines.launch
import java.time.LocalDate
import java.time.format.DateTimeFormatter

/**
 * 司机运费结算（两栏：左篮子 / 右详情）。
 *
 * 选中态存的是**字符串 key**（`d|<司机 id>`）而不是 `FreightSettlementGroupDto`：
 * 换月份会整批换掉 `data`，存对象的话选中的那位会指向一个已经被替换掉的旧实例
 * （界面照样亮着，但读出来的单数/金额是上个月的）。
 *
 * ## 时间口径（2026-09-20 用户要求）
 * > 司机运费结账的那个工作台，他除了上个月上上个月，他还可以选择时间进行查看的。
 *
 * 三档月份药丸之外还能自己选一段起止日期。两条路径打的是**同一个后端接口**
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

    /** 自定义区间（**两头都非空**才生效）；`null` = 走月份药丸那条路。 */
    var rangeFrom by mutableStateOf<String?>(null)
    var rangeTo by mutableStateOf<String?>(null)

    /** 左栏的搜索词（姓名 / 手机号 / 后 4 位，规则在 `core/UserSearch`）。 */
    var query by mutableStateOf("")

    /** 右栏正在看哪位司机（`d|<id>`）；空 = 还没点，界面回落到第一位。 */
    var selectedKey by mutableStateOf("")

    init {
        load()
    }

    val isCustomRange: Boolean get() = rangeFrom != null && rangeTo != null

    /**
     * 标题与药丸上的短标签：`本月` / `上月` / `上上月` / `09-01~09-20`。
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

    /** 换月份 = 回到药丸那条路（自定义区间就此清掉，否则界面会同时亮着两个"选中"）。 */
    fun shiftMonth(delta: Int) {
        rangeFrom = null
        rangeTo = null
        month = LocalDate.now().plusMonths(delta.toLong()).format(MONTH_FMT)
        load()
    }

    /** 应用一段自定义时间；两头都是 `null` = 清掉区间（弹层里"两头都没选"就是它）。 */
    fun applyRange(from: String?, to: String?) {
        rangeFrom = from
        rangeTo = to
        load()
    }

    fun selectDriver(key: String) {
        selectedKey = key
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
                // 换时间窗口后把选中清掉：那个 key 在新窗口里可能根本不存在，
                // 而界面会"回落到第一位"—— 留着旧 key 会让左栏高亮和右栏内容对不上。
                selectedKey = ""
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
