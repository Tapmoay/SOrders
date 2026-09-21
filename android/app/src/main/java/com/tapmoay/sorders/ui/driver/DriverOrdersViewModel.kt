package com.tapmoay.sorders.ui.driver

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.core.OrderStatusModel
import com.tapmoay.sorders.data.remote.dto.OrderDto
import com.tapmoay.sorders.data.repo.toApiException
import com.tapmoay.sorders.ui.common.DatePresets
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch
import java.time.LocalDate

class DriverOrdersViewModel(private val container: AppContainer) : ViewModel() {

    var tab by mutableStateOf(0) // 0=进行中 1=已完成
    var orders by mutableStateOf<List<OrderDto>>(emptyList())
    var loading by mutableStateOf(false)
    var error by mutableStateOf<String?>(null)
    var refreshing by mutableStateOf(false)

    /** 当前生效的日期窗口（只在「已完成」用得着；`null` = 不限）。 */
    var dateFrom by mutableStateOf<String?>(null)
        private set
    var dateTo by mutableStateOf<String?>(null)
        private set

    // ⚠️ 下面这几个**必须声明在 `init` 之前**：Kotlin 的属性初始化与 init 块按**书写顺序**执行，
    //    写在 init 之后的话，init 里那句赋值会抛
    //    `MutableState.setValue … on a null object reference` —— **打开这一页直接崩**
    //    （账本页 2026-09-20 真机栽过一次）。判据：`_tools/qa/_check_vm_state_before_init.py`。

    /**
     * 当前选中的日期档位（[DatePresets.ROW] 里的一档，或「自定义」）。
     *
     * ⚠️ 初值 = **今天**（用户 2026-09-20：「默认是今天的默认值查看今天的订单」）。
     *    今天没单时不会把人按在空列表上：第一次进「已完成」会 [pickDefaultPreset] 自动往后退档。
     */
    var preset by mutableStateOf(DatePresets.TODAY)
        private set

    /** 「自定义」那一档的两端（用户在日期弹层里选的）。 */
    var customFrom by mutableStateOf<String?>(null)
        private set
    var customTo by mutableStateOf<String?>(null)
        private set

    private var loadJob: Job? = null

    /**
     * **「已完成」那一段的窗口定下来了没有**（2026-09-21）。
     *
     * 这一页与账本页**不完全一样**：它没有"先按今天拉一次"那一步（盘点发生在切到「已完成」
     * 那一栏的时候），所以不会闪"两个窗口"。但它**缺一个门**：切过去的那一瞬间，
     * 屏幕上还挂着**上一栏（进行中）的那批单**，直到盘点完 + 拉完才换成已完成的 ——
     * 用户看到的是"先显示了几张进行中的单、再跳成已完成"，与账本页那个"闪两下"是同族毛病。
     *
     * 所以：切进「已完成」时先关闸（[selectTab]），盘点定下来、数也拉回来之后再开闸。
     * ⚠️ 初值 `true`：第 0 栏（进行中）不涉及日期窗口，一进来就该画。
     */
    var windowSettled by mutableStateOf(true)
        private set

    /** 用户**手动**挑过档位没有 —— 挑过就永不自动改（见 `selectTab` 里那次 `pickWindow`）。 */
    private var userPickedPreset = false

    /** 首次进「已完成」时挑过一次默认档位没有（只跑一次，之后切 tab 都按用户当前的档位）。 */
    private var autoPickedPreset = false

    init {
        // 默认档位是「今天」：先把区间算好再拉第一次 —— 否则会出现"药丸上写着今天、请求却没带日期"。
        DatePresets.rangeOf(preset, LocalDate.now())?.let {
            dateFrom = it.first
            dateTo = it.second
        }
        load()
        // Socket 实时事件驱动刷新（新单/撤回/完成等），新单由 RealtimeHub 语音播报
        viewModelScope.launch {
            container.realtimeHub.refreshOrders.collect { load() }
        }
    }

    fun selectTab(index: Int) {
        if (tab != index) {
            tab = index
            // 第一次进「已完成」：挑一个**真有单**的档位（今天→昨天→前天→这周→上周…）。
            // ⚠️ 只挑这一次：以后切回来按用户当前选的档位，不能每次都把他的选择顶掉。
            if (tab == 1 && !autoPickedPreset) {
                autoPickedPreset = true
                // ⚠️ **先关闸**：盘点 + 取数跑完之前不画（否则屏幕上先是一批"进行中"的单，
                //    再跳成已完成 —— 与账本页那个"闪两下"同族，用户 2026-09-21 报的就是这一类）。
                windowSettled = false
                viewModelScope.launch {
                    // ⚠️ **用户可能在探测期间自己挑了档位**（探测是网络请求）：那时再按阶梯结果
                    //    换档就是**抢方向盘** —— 与账本页同一条规矩。
                    if (!userPickedPreset) {
                        switchPreset(DatePresets.pickWindow(DatePresets.ORDER_PRESET_LADDER) { periodHasData(it) })
                    } else {
                        load()
                    }
                    windowSettled = true
                }
            } else {
                load()
            }
        }
    }

    /** 用户自己挑的档位（右上角那个药丸 → 档位清单）。**手动**：从此不再自动退档。 */
    fun applyPreset(label: String) {
        userPickedPreset = true
        // 用户已经表态 = 窗口就算是定下来了（不必再等那次盘点跑完才开闸）
        windowSettled = true
        switchPreset(label)
    }

    /**
     * 自定义区间（日期弹层回来的）。两头都没选 = 清掉区间，退回「全部」。
     * 手输的窗口同样是**手动**：不再自动退档。
     *
     * ⚠️ 日期换算**不在这里做**：档位与它们的区间只有 `ui/common/DatePresets` 一份实现，
     *    本页只把选中的那一档翻成 from/to。自己再写一遍 `when(档位)`，就会出现
     *    "这一页的今天和账本页的今天差一天"，而两边都看着对。
     */
    fun applyCustomRange(from: String?, to: String?) {
        userPickedPreset = true
        windowSettled = true // 同上：手输的窗口也算"用户已经表态"
        customFrom = from
        customTo = to
        preset = if (from == null && to == null) DatePresets.ALL else DatePresets.CUSTOM
        dateFrom = from
        dateTo = to
        load()
    }

    /** 真正的换档（自动退档与手动换档都走这一条路，**不许各写一份**）。 */
    private fun switchPreset(label: String) {
        preset = label
        val r = DatePresets.rangeOf(label, LocalDate.now())
        dateFrom = r?.first
        dateTo = r?.second
        load()
    }

    /**
     * 这一档有没有单（**只探测、不动页面状态**）。
     *
     * 判据与页面自己的取数**同源**（同一个状态 `DELIVERED`、同一套日期参数）—— 换个接口去猜
     * "有没有单"，就会出现"退档到的那一档页面还是空的"。
     * ⚠️ 探测失败（网络/权限）当"没单"处理：不能因为探测不通就把用户按在一个看不见的窗口上。
     */
    private suspend fun periodHasData(label: String): Boolean {
        val r = DatePresets.rangeOf(label, LocalDate.now()) ?: return true
        return try {
            container.repo.orders(status = "DELIVERED", dateFrom = r.first, dateTo = r.second).isNotEmpty()
        } catch (e: Exception) {
            false
        }
    }

    /**
     * 药丸上写的那几个字 —— **跟着实际窗口走**（设计规范 §4.9）：选着「今天」却在药丸上写「本月」，
     * 就是"以为看的是今天的单、其实看的是本月"的第一步。
     */
    val periodWord: String
        get() = when {
            // 还没盘点完 → 先写「…」（这时写任何档位都是假话，窗口还没定）
            tab == 1 && !windowSettled -> "…"
            preset != DatePresets.CUSTOM -> preset
            dateFrom == null || dateTo == null -> DatePresets.ALL
            else -> dateFrom!!.take(10).substring(5) + "~" + dateTo!!.take(10).substring(5)
        }

    fun load() {
        loadJob?.cancel()
        loadJob = viewModelScope.launch {
            loading = orders.isEmpty()
            error = null
            try {
                // 进行中 = 已派单（还没接）+ 已接单。状态取自 `OrderStatusModel.DRIVER_OPEN`
                // （原来这里硬写两个字面量；只查 ACCEPTED 时新派来的单在司机端**根本不出现**）。
                val statuses = if (tab == 0) OrderStatusModel.DRIVER_OPEN else listOf("DELIVERED")
                orders = statuses
                    .flatMap { container.repo.orders(status = it, dateFrom = if (tab == 1) dateFrom else null, dateTo = if (tab == 1) dateTo else null) }
                    .sortedByDescending { it.createdAt }
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                loading = false
                refreshing = false
            }
        }
    }

    fun refresh() {
        refreshing = true
        load()
    }

}

/**
 * 司机端自动退档的阶梯 —— **家已经搬到 `ui/common/DatePresets.kt::ORDER_PRESET_LADDER`**
 * （2026-09-22：派单员「订单管理」与货主「我的订单」也要"找订单的自动挡"，阶梯一旦有第二个
 * 使用者，"谁抄了谁"就没人说得清。原来那份 `DRIVER_PRESET_LADDER` 已删除，直接引用共享的那条）。
 */
