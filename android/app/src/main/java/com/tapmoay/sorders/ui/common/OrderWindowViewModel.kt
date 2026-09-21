package com.tapmoay.sorders.ui.common

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.tapmoay.sorders.core.AppContainer
import kotlinx.coroutines.launch
import java.time.LocalDate

/**
 * 订单列表（派单员「订单管理」/ 货主「我的订单」）共用的
 * **档位选择 + 右上角时间药丸 + 找订单的自动挡**。
 *
 * ## 为什么收在一处（2026-09-22）
 *
 * 这两页的档位语义本来就一样（全部 / 派单中 / 已接单 / 已送达 / 已撤销 / 已退货），而时间窗口
 * 那一套（`preset` / `customFrom` / `customTo` / `windowSettled` / `userPickedPreset` /
 * `datedTab` / `periodWord` / `windowRange` / `applyPreset` / `applyCustomRange` / 自动退档）
 * 第一版是**一字不差抄了两遍** —— 仓库自己的 `_tools/qa/_scan_dup.py` 当场报出 5 组跨文件重复。
 *
 * 比行数更要紧的是**行为**：这两个页面必须永远一致，而抄两份意味着"下一次修 bug 只修一页"。
 * 本轮真机上抓到的那个坑正是证据（见 [selectTab] 的注释）：它只需要改一处，
 * 但如果代码有两份，另一份就会把同一个坑留着。
 *
 * ## 子类只需要给三件（都与"怎么取数"有关，基类猜不出来）
 * · [tabs] / [defaultTabKey]：本角色的档位表与缺省档（按**状态名**找，⛔ 不写下标）；
 * · [reload]：取一次数（日期窗口由基类经 [windowRange] 给出）；
 * · [probeHasData]：这一档 + 这一窗口**有没有单**（自动挡的探测，**必须与 [reload] 同源**）。
 */
abstract class OrderWindowViewModel(
    protected val container: AppContainer,
    private val tabs: List<OrderTab>,
    defaultTabKey: String,
) : ViewModel() {

    /** 当前选中的档位下标（缺省档按**状态名**现算，见 `OrderTab` 的注释）。 */
    var tab by mutableStateOf(tabs.indexOfFirst { it.key == defaultTabKey })
        protected set

    /** 当前选中的日期档位（`DatePresets.ROW` 里的一档，或「自定义」）。**初值 = 今天**。 */
    var preset by mutableStateOf(DatePresets.TODAY)
        private set
    var customFrom by mutableStateOf<String?>(null)
        private set
    var customTo by mutableStateOf<String?>(null)
        private set

    /** 药丸弹层（档位清单）的开关 —— 页面 `remember` 也行，放这里省一层。 */
    var showDatePresets by mutableStateOf(false)

    /**
     * **这一段窗口定下来了没有**（用户要的"找订单的自动挡"）。
     *
     * 做法与账本/司机端**同一套**（那些页面早就这么做，见 `DatePresets.pickWindow` 的说明）：
     * 先只**探测**哪一档有单（今天 → 昨天 → … → 上月），定下来之后**只取一次数** ——
     * 不是"先按今天拉一次、空了再退档"（那样最坏要画三帧，就是用户 2026-09-21 报的"闪两下"）。
     *
     * ⚠️ 初值 `true`：缺省档是「派单中」/「已接单」（进行中，没有窗口），一进来就该画；
     *    只有切进**带窗口的档位**时才关闸（见 [selectTab]）。
     */
    var windowSettled by mutableStateOf(true)
        private set

    /** 用户**手动**挑过档位没有 —— 挑过就永不自动改（"默认"只在他还没表态时生效）。 */
    private var userPickedPreset = false

    /** 本角色的档位表（页面画顶栏、拼空态文案要用）。 */
    val allTabs: List<OrderTab> get() = tabs

    /** 当前这一档。 */
    val currentTab: OrderTab get() = tabs[tab]

    /** 这一档要不要日期窗口 —— 按**档位自己**的标记判（⛔ 不写下标：档位顺序一动就静默错位）。 */
    val datedTab: Boolean get() = currentTab.dated

    /**
     * 药丸上写的那几个字 —— **跟着实际窗口走**（设计规范 §4.9）：选着「今天」却在药丸上写
     * 「本月」，就是"以为看的是今天的单、其实看的是本月"的第一步。
     * ⚠️ 还没盘点完 → 写「…」：这时写任何档位都是假话（窗口还没定下来）。
     */
    val periodWord: String
        get() = when {
            datedTab && !windowSettled -> "…"
            preset == DatePresets.CUSTOM -> DatePresets.customLabel(customFrom, customTo)
            else -> preset
        }

    /**
     * 这一档这次实际要带的日期区间（两端 null = 不带日期条件）。
     *
     * ⚠️ **每次查询现算**（不在 init 里算一次存起来）：跨过零点之后「今天」还应该是真的今天，
     *    存起来的那一份会变成昨天那一格（而界面上写着"今天"，谁也看不出来）。
     * ⚠️ 档位 → 区间的换算只有 `ui/common/DatePresets` 一份实现，这里**不重写** `when(档位)`。
     */
    protected fun windowRange(): Pair<String?, String?> {
        if (!datedTab) return null to null
        if (preset == DatePresets.CUSTOM) return customFrom to customTo
        val r = DatePresets.rangeOf(preset, LocalDate.now()) ?: return null to null
        return r.first to r.second
    }

    /** 用户自己挑的档位（右上角药丸 → 档位清单）。**手动**：从此不再自动退档。 */
    fun applyPreset(label: String) {
        userPickedPreset = true
        windowSettled = true // 用户已经表态 = 窗口就算定下来了
        switchPreset(label)
    }

    /** 自定义区间（日期弹层回来的）。两头都没选 = 退回「全部」（不带日期条件）。 */
    fun applyCustomRange(from: String?, to: String?) {
        userPickedPreset = true
        windowSettled = true // 同上：手输的窗口也算"用户已经表态"
        customFrom = from
        customTo = to
        preset = if (from == null && to == null) DatePresets.ALL else DatePresets.CUSTOM
        reload()
    }

    /**
     * 真正的换档（自动退档与手动换档都走这一条，**不许各写一份**）。
     * ⚠️ 档位 → 区间的换算不在这里做：那是 `DatePresets.rangeOf` 的唯一职责（见 [windowRange]）。
     */
    private fun switchPreset(label: String) {
        preset = label
        reload()
    }

    /**
     * 切档位。
     *
     * 切进**带日期窗口的档位**时先挑一个**真有单**的档位（今天→昨天→…→上月）——
     * 这就是用户 2026-09-22 要的「找订单的规则，也就是**自动挡**」。
     *
     * ⚠️ **每次进带窗口的档位都重新找**（不是"整个页面只挑一次"）：第一版照司机端抄了
     *    "只挑一次"，真机上当场抓到 —— 先点「全部」（挑到「今天」）、再点「已送达」就
     *    **不再挑了**，于是「已送达 + 今天没单」停在空列表上，正是用户要避免的那个画面。
     *    （司机端那页能"只挑一次"是因为它**只有一个**带窗口的档；这两个页面各有 4 个。）
     * ⚠️ 但**用户手动挑过之后永不再自动改**（见 [applyPreset]）—— 那才是抢方向盘。
     */
    fun selectTab(i: Int) {
        if (tab == i) return
        tab = i
        if (currentTab.dated && !userPickedPreset) {
            // ⚠️ **先关闸**：盘点 + 取数跑完之前不画（否则屏幕上先是一批上一档的单、
            //    再跳成这一档的 —— 与账本页那个"闪两下"同族毛病）。
            windowSettled = false
            viewModelScope.launch {
                // ⚠️ **用户可能在探测期间自己挑了档位**（探测是网络请求）：那时再按阶梯结果换档
                //    就是**抢方向盘** —— 与账本页/司机端同一条规矩。
                if (!userPickedPreset) {
                    switchPreset(
                        DatePresets.pickWindow(DatePresets.ORDER_PRESET_LADDER) { label ->
                            val r = DatePresets.rangeOf(label, LocalDate.now()) ?: return@pickWindow true
                            probeHasData(currentTab.key, r.first, r.second)
                        },
                    )
                } else {
                    reload()
                }
                windowSettled = true
            }
        } else {
            reload()
        }
    }

    /** 取一次数（日期窗口用 [windowRange]）。 */
    protected abstract fun reload()

    /**
     * 这一档 + 这一窗口**有没有单**（自动挡的探测）。
     *
     * **判据必须与 [reload] 同源**（同一个端点、同一套参数）：换个接口去猜"有没有单"，
     * 就会出现"退档到的那一档页面还是空的"。
     * ⚠️ 探测失败（网络/权限）由实现方当"没单"处理：不能因为探测不通就把用户按在一个
     *    看不见的窗口上。
     */
    protected abstract suspend fun probeHasData(status: String?, from: String, to: String): Boolean
}
