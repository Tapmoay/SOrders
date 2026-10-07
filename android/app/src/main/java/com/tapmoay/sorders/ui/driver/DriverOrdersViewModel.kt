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

/**
 * 「已完成」这一档包含的状态：**已送达 + 已退货**。
 *
 * ⚠️ 2026-10-03（E2E 走查 P27）：这里原来只查 `DELIVERED` —— 整单退完的单状态变成 `RETURNED`，
 * 于是它从司机的「已完成」列表里**凭空消失**（他翻遍列表也找不到那张单，与"退货一条消息都没有"
 * 是同一件事的两面）。取数与 [DriverOrdersViewModel.periodHasData] 的探测**必须同源**，
 * 否则会出现"退档到的那一档页面还是空的"。
 */
private val FINISHED_STATUSES: List<String> = listOf("DELIVERED", "RETURNED")

class DriverOrdersViewModel(private val container: AppContainer) : ViewModel() {

    var tab by mutableStateOf(0) // 0=进行中 1=已完成
    var orders by mutableStateOf<List<OrderDto>>(emptyList())

    /**
     * **`orders` 里这批单属于哪一栏**（0=进行中 1=已完成）—— 2026-10-06，BUG-0014。
     *
     * ⚠️ 与 [tab] 是**两件事**，切换的那一瞬间必然不同：
     *   `tab`      = 用户**想看**哪一栏（点下去就变了）；
     *   `ordersTab` = 屏幕上**画的**是哪一栏（要等网络回来才变）。
     * 从前卡片拿 [tab] 算高亮（`highlight = vm.tab == 0`），于是点「已完成」的一瞬间，
     * 那批**属于「进行中」的单**被画成已完成的样式（件数由红变紫、字号 titleLarge→titleMedium），
     * 一个往返之后才连数据一起换掉 —— 用户看到的就是"先闪一下错的样式"。
     *
     * ⛔ 别把这两个状态拆开写：见 [load] 里那句"必须相邻"。
     */
    var ordersTab by mutableStateOf(0)
        private set

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
     * **正在确认接单的那一张单**（`null` = 没有请求在飞）—— 2026-10-08，CHG-0081。
     *
     * 用户要的是"在卡片上直接接单"（原话：「直接在订单卡片里面的最底下…按钮…
     * 直接在那里点击确认…他就不需要直接的点进去…进行确认就可以了」）。卡片上多了一颗
     * 一点就改状态的按钮，就必须回答"点下去到服务器回话之间这一格画什么"：
     *  · 按下的那颗 → 转圈 + 置灰（不然司机会连点，第二次必然被后端 CAS 判成 400
     *    「这张单刚刚被改过…」—— 那是一条**看起来像系统坏了**的错）；
     *  · 同一时刻**别的**卡片那颗也一起置灰（[ackingOrderId] 是个单值）：一次只接一张，
     *    两个请求同时在飞的时候界面说不清"哪一张成了、哪一张没成"。
     *
     * ⚠️ 必须声明在 `init { }` **之前**（属性初始化按书写顺序执行，写在后面这一页打开就崩）
     *    —— 判据 `_tools/qa/_check_vm_state_before_init.py`。
     */
    var ackingOrderId by mutableStateOf<Long?>(null)
        private set

    /**
     * 确认接单**失败**的原因（成功即清空）。
     *
     * ⛔ 它**不进**页面级 [error]：那个 error 是"这一页没加载出来"（渲染门会拿它顶掉整个列表，
     *    司机连那张单都看不见了）。接单失败是**这一张卡**的事 —— 卡片还在、按钮还在，
     *    他看完那句话就能再点一次（与设计规范 §4.8「错误的落点」同一条）。
     */
    var ackError by mutableStateOf<String?>(null)
        private set

    /**
     * [ackError] 那句话是**哪一张单**的（`null` = 没有）。
     *
     * ⚠️ 没有它就出大问题：`ackError` 是个单值，而列表上**每一张卡都读同一个字段**
     *    → 一张单接单失败，屏幕上**所有**卡片底下同时冒出同一句红字（司机看到的是
     *    "这些单全都出问题了"）。错误的落点必须精确到那一张卡。
     */
    var ackErrorOrderId by mutableStateOf<Long?>(null)
        private set

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

    /**
     * **确认接单**（2026-10-08，CHG-0081）—— 司机在**卡片上**直接接单，不必先进详情页。
     *
     * 为什么把接单搬到列表上：用户原话「这个确认订单，他的按钮是进入订单详情面才能确认，
     * 这个就太麻烦了…直接在订单卡片里面的最底下…有一个按钮…他就不需要直接的点进去…
     * 进行确认就可以了」。接单是司机最高频、最该"一下就能做完"的动作，而它此前**只有**
     * 详情页那一个入口（`ui/order/OrderDetailScreen.kt` 那颗整宽按钮）。
     *
     * 三件事与详情页**必须同源**（少一件就是"列表上接的单和详情页接的单不一样"）：
     *  ① 状态门 = [OrderStatusModel.ACKABLE]（不是硬写 `"DISPATCHED"`）：卡片上画不画那颗按钮、
     *     点下去之前再判一次，用的是同一个集合；
     *  ② 成功即 [AppContainer.newOrderPlayer].stop()：接完还在喊「来单了」，司机会怀疑到底接上没有；
     *  ③ 成功后 `realtimeHub.notifyOrdersChanged()`：这一页自己刷新，**也让别的页面（详情页/角标）
     *     跟着知道状态变了**。
     *
     * 三种收场，各有各的道理：
     *  · 成功 → 用响应回来的那张单**原地换掉列表里那一条**（`OrderOut` 是整单，不用再拉一次列表）；
     *  · 被后端 CAS 拒（"这张单刚刚被改过…"）→ [ackError] + **再拉一次列表**：那句话说的是
     *    "你手上这张单已经不是这样了"，只弹错误却把过期状态留在屏幕上，他只会再点一次；
     *  · 网络失败 → 只写 [ackError]（列表还准，重连重试即可）。
     *
     * ⚠️ 它**不是** [load] 的替代：`load()` 里有"orders 与 ordersTab 必须相邻"那条规矩，
     *    这里只动 `orders` 里的**一条**，不碰 `ordersTab`（那一栏没变）。
     */
    fun ack(order: OrderDto) {
        // 已经有请求在飞 → 直接不管（按钮那边也置灰了）。后端对重复接单是**硬拒**：
        // `services/order_flow.accept_order` 的条件 UPDATE 撞不上就 400「这张单刚刚被改过…」，
        // 那条错看起来像系统坏了，而它其实只是"你点了两下"。
        if (ackingOrderId != null) return
        ackingOrderId = order.id
        ackError = null
        ackErrorOrderId = null
        viewModelScope.launch {
            try {
                val updated = container.repo.driverAck(order.id)
                // ⚠️ 按 **id** 换那一条（不是按下标）：`load()`/实时推送期间列表可能已经变了
                //    （新单进来、旧的被撤回），按下标换会把结果写到别人头上。
                //    ⚠️ `List` 没有 `replace`（那是 `MutableList` 的）—— 这里要的是**换成一个新列表**。
                orders = orders.map { if (it.id == updated.id) updated else it }
                container.newOrderPlayer.stop()
                container.realtimeHub.notifyOrdersChanged()
            } catch (e: Exception) {
                ackError = toApiException(e).message
                ackErrorOrderId = order.id
                // 失败就把列表拉回真相：这条错多半是"状态已经变了"，而屏幕上那份还是点之前的样子。
                // 拉回来的结果由 `load()` 写进 `orders`；那两个 ack 错误状态不会被它清掉
                // （互不干扰），所以他还能看见"为什么没接上"。
                load()
            } finally {
                ackingOrderId = null
            }
        }
    }

    /** 确认接单失败的那句话由用户手动收起（换一栏/手动刷新也该清掉）。 */
    fun clearAckError() {
        ackError = null
        ackErrorOrderId = null
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
            // 与 `load()` 同一份状态清单（[FINISHED_STATUSES]）：探测漏了 RETURNED 的话，
            // 一档里明明有已退货的单却被判成"没单"，自动退档会把用户越推越远。
            FINISHED_STATUSES.any { st ->
                container.repo.orders(status = st, dateFrom = r.first, dateTo = r.second).isNotEmpty()
            }
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
        // ⚠️ **在挂起点之前**把"这一趟是给哪一栏取的"钉死：取数期间用户又切了一次 tab 的话，
        //    拿回来的是**旧那一栏**的数据 —— 那时若按新 tab 记 [ordersTab]，就又把两件事混成一件。
        val wanted = tab
        loadJob = viewModelScope.launch {
            loading = orders.isEmpty()
            error = null
            try {
                // 进行中 = 已派单（还没接）+ 已接单。状态取自 `OrderStatusModel.DRIVER_OPEN`
                // （原来这里硬写两个字面量；只查 ACCEPTED 时新派来的单在司机端**根本不出现**）。
                // 已完成档 = 已送达 + 已退货（[FINISHED_STATUSES]）—— 整单退货的单**不许**从
                // 司机列表里消失（2026-10-03，E2E 走查 P27）。
                val statuses = if (wanted == 0) OrderStatusModel.DRIVER_OPEN else FINISHED_STATUSES
                val fetched = statuses
                    .flatMap { container.repo.orders(status = it, dateFrom = if (wanted == 1) dateFrom else null, dateTo = if (wanted == 1) dateTo else null) }
                    .sortedByDescending { it.createdAt }
                // ⚠️ 这两句**必须相邻**（中间不许出现任何挂起点）：`orders` 与 [ordersTab] 是同一个事实的两半，
                //    要么一起换、要么都不换。拆开写就会出现"数据是新的、栏位还是旧的"（或反过来），
                //    而这两种错都不会报错、只在屏幕上闪一下。
                orders = fetched
                ordersTab = wanted
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
