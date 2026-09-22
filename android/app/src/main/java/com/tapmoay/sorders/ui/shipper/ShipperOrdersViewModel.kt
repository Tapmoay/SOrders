package com.tapmoay.sorders.ui.shipper

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.viewModelScope
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.core.ReturnRules
import com.tapmoay.sorders.data.remote.dto.OrderDto
import com.tapmoay.sorders.data.remote.dto.OrderProductDto
import com.tapmoay.sorders.data.remote.dto.OrderReturnItem
import com.tapmoay.sorders.data.remote.dto.ReturnRequestDto
import com.tapmoay.sorders.data.repo.toApiException
import com.tapmoay.sorders.ui.common.ORDER_LIST_LIMIT
import com.tapmoay.sorders.ui.common.ORDER_WINDOW_NO_LIMIT_WORD
import com.tapmoay.sorders.ui.common.OrderTab
import com.tapmoay.sorders.ui.common.OrderWindowViewModel
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch

/**
 * 货主 / 批发商「我的订单」顶栏那一排档位。
 *
 * ⚠️ 缺省档 = **「已接单」**（用户 2026-09-22：「**货主就是已接单的**，货主他是**默认已接单**的，
 *    并且将那个**已接单往前一格排第 2 位置**」）。
 * ⚠️ 下表**就是**那个"往前一格"的结果：默认档紧挨着「全部」，一进来视线就落在它上面。
 *    下标一律按**状态名**现算，别写 `1` —— 再挪一格就又错位了。
 * ⚠️ `dated = true` 的档才是**可按日期筛**的（药丸可点）：**「全部」也有**（用户 2026-09-22：
 *    「对，**全部我们也要有时间的筛选**」）—— 终态档（已送达/已撤销/已退货）都有；
 *    **「已接单」「派单中」不按日期筛**（用户：「他属于**正在进行**啊，所以他是不会有选择时间」），
 *    但它们也有药丸 —— 只是**不可点**、上面写「不限时间」（用户第三轮：「为了美观而统一…
 *    那个图标**无法选择**，他不会有列表，就是只有显示」）。⛔ 那两档**不许写「今天」**。
 * ⚠️ 缺省档与窗口那一套（`tab` / `preset` / `selectTab` / 自动退档）在共用的
 *    `ui/common/OrderWindowViewModel` —— 与派单员「订单管理」是**同一份**。
 */
val SHIPPER_TABS = listOf(
    OrderTab(null, "全部", dated = true),
    OrderTab("ACCEPTED", "已接单", windowWord = ORDER_WINDOW_NO_LIMIT_WORD),
    OrderTab("PENDING_DISPATCH", "派单中", windowWord = ORDER_WINDOW_NO_LIMIT_WORD),
    OrderTab("DELIVERED", "已送达", dated = true),
    OrderTab("CANCELLED", "已撤销", dated = true),
    // 已退货（2026-09-20）：货主必须看得到这一档 —— 否则"送过的单被退掉了"只会从他的
    // 「已送达」里消失（筛选按状态走），而界面上一个字都不提这件事。
    OrderTab("RETURNED", "已退货", dated = true),
)

class ShipperOrdersViewModel(container: AppContainer) :
    OrderWindowViewModel(container, SHIPPER_TABS, "ACCEPTED") {

    var orders by mutableStateOf<List<OrderDto>>(emptyList())
    var loading by mutableStateOf(false)
    var error by mutableStateOf<String?>(null)
    var refreshing by mutableStateOf(false)
    var acting by mutableStateOf(false)
    var actionResult by mutableStateOf<String?>(null)
    var cancelTarget by mutableStateOf<OrderDto?>(null)

    // 档位（`tab`）、时间药丸（`preset` / `customFrom` / `customTo` / `showDatePresets`）、
    // 自动挡（`windowSettled` / `selectTab` / `applyPreset` / `applyCustomRange`）**全在基类**：
    // 这一套原来在派单员与货主两页一字不差抄了两遍（`_tools/qa/_scan_dup.py` 报出 5 组跨文件
    // 重复），而"抄两份"意味着下一次修 bug 只修一页 —— 本轮真机上抓到的坑正是这一类的证据。

    // ---- 退货申请（2026-09-21）：货主**只能申请**，派单员办理完库存与账本才变 ----
    /** 这一单**待处理**的退货申请（`orderId` → 申请）。有它就说明这张单不能再申请一次。 */
    var pendingReturns by mutableStateOf<Map<Long, ReturnRequestDto>>(emptyMap())

    /**
     * 「待处理申请」这一份**到底有没有拉到手**。
     *
     * ⛔ 为什么要有这个门：`myReturnRequests` 万一失败（老后端没这个端点 / 网络抖），
     *    `pendingReturns` 会是**空表**，而空表与"确实没有待处理申请"在界面上长得一模一样 ——
     *    于是「申请退货」又会冒出来，点下去必然被后端拒（这正是要避免的那种按钮）。
     *    所以拉不到就 `false`，**宁可不显示那个按钮**（宁可少一个入口，也不给一个必然失败的）。
     */
    var pendingKnown by mutableStateOf(false)
        private set

    // 申请弹层（与派单员那个退货弹窗同形：逐行勾数量 + 备注）
    var showReturnDialog by mutableStateOf(false)
    var returnTarget by mutableStateOf<OrderDto?>(null)
    /** 每行申请退几件（`order_products.id` → 数量）。**只有 > 0 的行才会提交**。 */
    var returnQty by mutableStateOf<Map<Long, Int>>(emptyMap())
    var returnNote by mutableStateOf("")
    var returnSubmitting by mutableStateOf(false)

    /**
     * 申请弹层**自己**的错误（表单级，不是页面级）。
     *
     * ⚠️ 本仓库的规矩（`Components.kt::FormErrorLine` 那段注释讲的就是这个踩过的坑）：
     *    **表单的错误必须和表单同生共死** —— 否则表现是"点提交没有任何反应"
     *    （错误被 AlertDialog 的遮罩盖在背后），关掉弹层又整页被 `ErrorView` 顶掉。
     *    页面级 [error] 只留给"这一页的数据没加载出来"。
     */
    var returnFormError by mutableStateOf<String?>(null)

    /** 撤回申请（二次确认） */
    var withdrawTarget by mutableStateOf<ReturnRequestDto?>(null)
    var withdrawFormError by mutableStateOf<String?>(null)

    private var loadJob: Job? = null

    init {
        load()
        // Socket 实时事件驱动刷新（派单/送达/撤销等）
        viewModelScope.launch {
            container.realtimeHub.refreshOrders.collect { load() }
        }
    }

    // `selectTab` / `datedTab` / `periodWord` / `windowRange` / `applyPreset` / `applyCustomRange`
    // 都在共用内核 `ui/common/OrderWindowViewModel` 里（与派单员「订单管理」是同一份）。
    // 本页只需要提供"怎么取数"：见下面的 [load] 与 [probeHasData]。

    /**
     * 这一档有没有单（自动挡的探测，**只探测、不动页面状态**）。
     *
     * 判据必须与 [load] **同源**：同一个状态（`currentTab.key`，可能是 null）+ 同一套日期窗口
     * —— 换个接口去猜"有没有单"，就会出现"退档到的那一档页面还是空的"。
     * ⚠️ 探测失败（网络/权限）当"没单"处理：不能因为探测不通就把用户按在一个看不见的窗口上。
     */
    override suspend fun probeHasData(status: String?, from: String, to: String): Boolean = try {
        container.repo.orders(status = status, dateFrom = from, dateTo = to).isNotEmpty()
    } catch (e: Exception) {
        false
    }


    /**
     * 这次列表**可能被服务端截断**（2026-09-19 审计）。
     *
     * `GET /orders` 现在对所有角色都有缺省上限 300（以前除"派单员+待派单"外是全量下发，
     * 3 年数据后就是几万单十几 MB）。判据只用"返回条数 == 上限"——少于上限就一定没有更多，
     * 等于上限则**可能**还有，所以文案说"可能"，不撒谎也不吓人。
     */
    val maybeTruncated: Boolean get() = orders.size >= ORDER_LIST_LIMIT

    fun load() {
        loadJob?.cancel()
        loadJob = viewModelScope.launch {
            loading = orders.isEmpty()
            error = null
            // 日期窗口只在带窗口的档位上生效（见 OrderTab.dated）：不带窗口的档位
            // 连参数都不传，免得"看着是全部、其实是今天"。
            val (from, to) = windowRange()
            try {
                val list = container.repo.orders(
                    status = currentTab.key,
                    dateFrom = from,
                    dateTo = to,
                )
                orders = list
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                loading = false
                refreshing = false
            }
            loadPendingReturns()
        }
    }

    override fun reload() = load()

    /**
     * 拉「我这一单有没有待处理的退货申请」——**一次拉全部待处理**，按 `orderId` 建表。
     *
     * 为什么不是每张单各问一次：列表里有几十张单，逐单问就是几十个请求。
     * 为什么失败**不**把整页变成错误页：那样等于"退货申请这个新功能把订单列表弄挂了"，
     *   而这只是一次附带查询 —— 失败的后果收敛成上面 [pendingKnown] 那一个开关。
     */
    private suspend fun loadPendingReturns() {
        pendingReturns = try {
            val items = container.repo.myReturnRequests(status = "pending").items
            pendingKnown = true
            items.filter { it.isPending }.associateBy { it.orderId }
        } catch (e: kotlinx.coroutines.CancellationException) {
            // 换档/下拉重拉会取消上一个 job —— 那不是"拉失败"，别把它记成 pendingKnown=false
            // （本项目栽过一次同类坑：把 CancellationException 当成业务失败）。
            throw e
        } catch (e: Exception) {
            pendingKnown = false
            emptyMap()
        }
    }

    // ---- 退货申请 ----

    /** 这一行**最多还能申请退几件**。规则只有一份：`core/ReturnRules`（与后端 `max_returnable` 同源）。 */
    fun maxReturnable(line: OrderProductDto): Int =
        ReturnRules.maxReturnable(line.quantity, line.damageQuantity, line.returnedQuantity)

    fun hasReturnable(o: OrderDto): Boolean = o.orderProducts.any { maxReturnable(it) > 0 }

    /**
     * 这一单现在能不能提申请。
     *
     * 三个条件缺一不可（**全都是"先判再显示"，不许出现点了必然失败的按钮**）：
     * ① 已送达（后端 `order_return_request.submit` 只认 `DELIVERED`）；
     * ② 还有可退量（全退完 / 剩下的都是货损 → 后端会拒）；
     * ③ 没有待处理的申请（一张单同时只允许一条，要改数量得先撤回）。
     */
    fun canApplyReturn(o: OrderDto): Boolean =
        pendingKnown &&
            pendingReturns[o.id] == null &&
            o.status in com.tapmoay.sorders.core.OrderStatusModel.RETURNABLE &&
            hasReturnable(o)

    /** 这张单上待处理的申请（没有则 null）。 */
    fun pendingFor(o: OrderDto): ReturnRequestDto? = pendingReturns[o.id]

    /** 打开申请弹层：默认**全部勾满**（最常见的就是整单退，再自己往下减），与派单员那个弹窗同一手感。 */
    fun openReturn(o: OrderDto) {
        returnTarget = o
        returnQty = o.orderProducts.associate { it.id to maxReturnable(it) }
        returnNote = ""
        returnFormError = null
        showReturnDialog = true
    }

    /** 关掉申请弹层：**顺手把它自己的错误清掉**（表单的错误与表单同生共死）。 */
    fun dismissReturnDialog() {
        if (returnSubmitting) return
        showReturnDialog = false
        returnFormError = null
    }

    fun setReturnQty(lineId: Long, qty: Int) {
        val o = returnTarget ?: return
        val line = o.orderProducts.firstOrNull { it.id == lineId } ?: return
        // 上限夹在这一处：加减号、整单全勾、全清零三条路都走它，
        // 所以不可能出现"填了 5 却只退 3"这种鬼状态（与派单员那一份同一写法）
        returnQty = returnQty + (lineId to qty.coerceIn(0, maxReturnable(line)))
    }

    fun returnAll() {
        val o = returnTarget ?: return
        returnQty = o.orderProducts.associate { it.id to maxReturnable(it) }
    }

    fun returnNone() {
        val o = returnTarget ?: return
        returnQty = o.orderProducts.associate { it.id to 0 }
    }

    /** 这次一共申请退几件（只用于弹层上的一行提示；**不显示金额** —— 那要派单员办理时才算得出来）。 */
    fun returnTotalQty(): Int = returnQty.values.sum()

    fun confirmApplyReturn() {
        val o = returnTarget ?: return
        val items = o.orderProducts
            .mapNotNull { line -> (returnQty[line.id] ?: 0).takeIf { it > 0 }?.let { line.id to it } }
        if (items.isEmpty()) {
            // 这是**表单**的错误：画在弹层里（画在页面上会被遮罩盖住 = "点了没反应"）
            returnFormError = "请至少勾一个要退的商品（数量大于 0）"
            return
        }
        returnSubmitting = true
        returnFormError = null
        viewModelScope.launch {
            try {
                container.repo.applyReturnRequest(
                    o.id,
                    items.map { OrderReturnItem(it.first, it.second) },
                    returnNote.trim(),
                )
                // 这句话必须写清"这只是申请"：界面上一个数字都没变，用户很容易以为货已经退了。
                // 提交后**库存与账本一分没动**是这个功能的全部意义（见后端 order_return_request.py 头）。
                actionResult = "已提交退货申请，派单员会收到通知并办理；现在库存和账本还没有变化"
                showReturnDialog = false
                returnFormError = null
                returnTarget = null
                load()
            } catch (e: Exception) {
                // 后端的 detail 是能照着改的中文（"这一单已经有一张待处理的退货申请了（…），
                // 要改就先把那一张撤回，再重新申请"）——原样显示在弹层里，别自己翻译
                returnFormError = toApiException(e).message
            } finally {
                returnSubmitting = false
            }
        }
    }

    fun askWithdraw(req: ReturnRequestDto) {
        withdrawTarget = req
        withdrawFormError = null
    }

    fun cancelWithdraw() {
        withdrawTarget = null
        withdrawFormError = null
    }

    fun confirmWithdraw() {
        val req = withdrawTarget ?: return
        acting = true
        withdrawFormError = null
        viewModelScope.launch {
            try {
                container.repo.withdrawReturnRequest(req.id)
                actionResult = "已撤回退货申请（申请记录留着，派单员看得到你提过又撤了）"
                withdrawTarget = null
                load()
            } catch (e: Exception) {
                withdrawFormError = toApiException(e).message
            } finally {
                acting = false
            }
        }
    }

    /** 卡片直撤：确认后调取消接口 */
    fun confirmCancel() {
        val target = cancelTarget ?: return
        acting = true
        error = null
        viewModelScope.launch {
            try {
                container.repo.cancelOrder(target.id)
                actionResult = "订单已撤销"
                cancelTarget = null
                load()
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                acting = false
            }
        }
    }

    fun refresh() {
        refreshing = true
        load()
    }
}
