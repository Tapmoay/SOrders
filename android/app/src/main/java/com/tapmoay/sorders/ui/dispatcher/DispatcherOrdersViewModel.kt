package com.tapmoay.sorders.ui.dispatcher

import androidx.compose.runtime.*
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.core.InputRules
import com.tapmoay.sorders.data.remote.dto.OrderDto
import com.tapmoay.sorders.data.remote.dto.OrderUpdateRequest
import com.tapmoay.sorders.data.repo.toApiException
import com.tapmoay.sorders.ui.common.DatePresets
import com.tapmoay.sorders.ui.common.ORDER_LIST_LIMIT
import com.tapmoay.sorders.ui.common.OrderTab
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch
import java.time.LocalDate

/**
 * 派单员「订单管理」顶栏那一排档位。
 *
 * ⚠️ 缺省档 = **「派单中」**（用户 2026-09-22 原话：「如果是进来的话，**默认是不会进入「全部」**的，
 *    默认是进入**「派单中」**」）。下标用**状态名**现算，不写 `0/1` —— 档位顺序改过
 *    （货主那列的「已接单」这一轮就挪了一格），写死的下标会把默认档悄悄指到别的档上。
 * ⚠️ `dated = true` 的档才有右上角那个时间药丸：**「全部」也有**（用户：「对，**全部我们也要有
 *    时间的筛选**」）——终态档（已送达/已撤销/已退货）都有；**「派单中」「已接单」没有**
 *    （用户：「他属于**正在进行**啊，所以他是不会有选择时间」）。
 */
val DISPATCH_TABS = listOf(
    OrderTab(null, "全部", dated = true),
    OrderTab("PENDING_DISPATCH", "派单中"),
    OrderTab("ACCEPTED", "已接单"),
    OrderTab("DELIVERED", "已送达", dated = true),
    OrderTab("CANCELLED", "已撤销", dated = true),
    // 已退货（2026-09-20）：与「已撤销」**不是一回事**（撤销＝单没发生过，
    // 退货＝送了、入了账、事后货退回来了）。两者都有各自的页签，别合并成一档。
    OrderTab("RETURNED", "已退货", dated = true),
)

/** 进页面时选中哪一档：**「派单中」**（按状态名算下标，见上面那条注释）。 */
private val DEFAULT_TAB = DISPATCH_TABS.indexOfFirst { it.key == "PENDING_DISPATCH" }

class DispatcherOrdersViewModel(private val container: AppContainer) : ViewModel() {

    var orders by mutableStateOf<List<OrderDto>>(emptyList())
    var loading by mutableStateOf(false)
    var error by mutableStateOf<String?>(null)
    var acting by mutableStateOf(false)
    var actionResult by mutableStateOf<String?>(null)

    var tab by mutableStateOf(DEFAULT_TAB)
    var search by mutableStateOf("")

    // ---- 右上角的时间药丸 + 「找订单的自动挡」（2026-09-22）----
    // 只服务带日期窗口的档（`OrderTab.dated`：全部 / 已送达 / 已撤销 / 已退货），**默认档 = 今天**
    // （用户原话：「而且**时间默认的是今天**」）。
    // ⚠️ 下面这几项必须声明在 `init` **之前**（Kotlin 的属性初始化与 init 块按书写顺序执行，
    //    写在 init 之后的话 init 里那句赋值会抛 NPE —— 账本页 2026-09-20 真机栽过一次）。
    //    判据：`_tools/qa/_check_vm_state_before_init.py`。
    var preset by mutableStateOf(DatePresets.TODAY)
        private set
    var customFrom by mutableStateOf<String?>(null)
        private set
    var customTo by mutableStateOf<String?>(null)
        private set
    var showDatePresets by mutableStateOf(false)

    /**
     * **这一段窗口定下来了没有**（用户要的"找订单的自动挡"）。
     *
     * 用户原话：「他们是有那个**找订单的规则**，也就是**自动挡**，他需要做」。
     * 做法与账本/司机端**同一套**（那 5 个页面早就这么做，见 `DatePresets.pickWindow` 的说明）：
     * 先只**探测**哪一档有单（今天 → 昨天 → … → 上月），定下来之后**只取一次数** ——
     * 不是"先按今天拉一次、空了再退档"（那样最坏要画三帧，用户 2026-09-21 报的"闪两下"）。
     *
     * ⚠️ 初值 `true`：默认档是「派单中」（进行中，没有日期窗口），一进来就该画；
     *    只有切进**带窗口的档位**时才关闸（见 [selectTab]）。
     */
    var windowSettled by mutableStateOf(true)
        private set

    /** 用户**手动**挑过档位没有 —— 挑过就永不自动改（"默认"只在他还没表态时生效）。 */
    private var userPickedPreset = false

    // 编辑弹窗
    var showEditDialog by mutableStateOf(false)
    var editingOrder by mutableStateOf<OrderDto?>(null)
    var editAddress by mutableStateOf("")
    var editDongjia by mutableStateOf("")
    var editBoss by mutableStateOf("")
    // 与两个电话一一对应的名称（2026-09-20 加）：dongjia=收货人、boss=下单人
    var editDongjiaName by mutableStateOf("")
    var editBossName by mutableStateOf("")
    var editRemark by mutableStateOf("")
    var editInternal by mutableStateOf("")

    // 撤回派单
    var showRecallDialog by mutableStateOf(false)
    var recallOrderId by mutableStateOf<Long?>(null)
    var recallReason by mutableStateOf("")

    // 异常标记
    var showExceptionDialog by mutableStateOf(false)
    var exceptionOrderId by mutableStateOf<Long?>(null)
    var exceptionReason by mutableStateOf("")
    var exceptionResolution by mutableStateOf("")
    var expectedBefore by mutableStateOf("")

    private var loadJob: Job? = null

    init {
        load()
        viewModelScope.launch {
            container.realtimeHub.refreshOrders.collect { load() }
        }
    }

    /** 这一档要不要日期窗口 —— 按**档位自己**的标记判（不写下标，见 `OrderTab`）。 */
    val datedTab: Boolean get() = DISPATCH_TABS[tab].dated

    /**
     * 药丸上写的那几个字 —— **跟着实际窗口走**（设计规范 §4.9）：
     * 选着「今天」却在药丸上写「本月」，就是"以为看的是今天的单、其实看的是本月"的第一步。
     * ⚠️ 还没盘点完 → 先写「…」：这时写任何档位都是假话（窗口还没定）。
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
     * ⚠️ **每次查询现算**，不在 init 里算一次存起来：跨过零点之后「今天」还应该是真的今天，
     *    存起来的那一份会变成昨天那一格（而且界面上写着"今天"，谁也看不出来）。
     * ⚠️ 档位 → 区间的换算只有 `ui/common/DatePresets` 一份实现，这里**不重写** `when(档位)`。
     */
    private fun windowRange(): Pair<String?, String?> {
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
        load()
    }

    /**
     * 真正的换档（自动退档与手动换档都走这一条，**不许各写一份**）。
     * ⚠️ 档位 → 区间的换算不在这里做：那是 `DatePresets.rangeOf` 的唯一职责（见 [windowRange]）。
     */
    private fun switchPreset(label: String) {
        preset = label
        load()
    }

    /**
     * 这一档有没有单（**只探测、不动页面状态**）。
     *
     * 判据必须与页面自己的取数**同源**：同一个状态（`DISPATCH_TABS[tab].key`，可能是 null）+
     * 同一套日期参数（都走 `DatePresets.rangeOf`）—— 换个接口去猜"有没有单"，
     * 就会出现"退档到的那一档页面还是空的"。
     * ⚠️ 探测失败（网络/权限）当"没单"处理：不能因为探测不通就把用户按在一个看不见的窗口上。
     */
    private suspend fun periodHasData(label: String): Boolean {
        val r = DatePresets.rangeOf(label, LocalDate.now()) ?: return true
        return try {
            container.repo.orders(
                status = DISPATCH_TABS[tab].key,
                q = search.trim().ifBlank { null },
                dateFrom = r.first,
                dateTo = r.second,
            ).isNotEmpty()
        } catch (e: Exception) {
            false
        }
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
                orders = container.repo.orders(
                    status = DISPATCH_TABS[tab].key,
                    q = search.trim().ifBlank { null },
                    dateFrom = from,
                    dateTo = to,
                )
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                loading = false
            }
        }
    }

    fun selectTab(i: Int) {
        if (tab == i) return
        tab = i
        // 切进**带日期窗口的档位**：先挑一个**真有单**的档位（今天→昨天→…→上月）。
        // 这就是用户 2026-09-22 要的「找订单的规则，也就是**自动挡**」。
        //
        // ⚠️ **每次进带窗口的档位都要重新挑**（不是"整个页面只挑一次"）：第一版照司机端抄了
        //    "只挑一次"，真机上当场抓到 —— 先点「全部」（挑到「今天」）、再点「已送达」就
        //    **不再挑了**，于是「已送达 + 今天没单」停在空列表上，正是用户要避免的那个画面。
        //    （司机端那页能"只挑一次"是因为它只有一个带窗口的档。）
        // ⚠️ 但**用户手动挑过之后永不再自动改**（见 [applyPreset]）—— 那才是抢方向盘。
        if (DISPATCH_TABS[i].dated && !userPickedPreset) {
            // ⚠️ **先关闸**：盘点 + 取数跑完之前不画（否则屏幕上先是一批上一档的单、
            //    再跳成这一档的 —— 与账本页那个"闪两下"同族毛病）。
            windowSettled = false
            viewModelScope.launch {
                // ⚠️ **用户可能在探测期间自己挑了档位**（探测是网络请求）：那时再按阶梯结果换档
                //    就是**抢方向盘** —— 与账本页/司机端同一条规矩。
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

    fun searchNow() = load()

    // ---- 编辑 ----
    fun openEdit(o: OrderDto) {
        editingOrder = o
        editAddress = o.addressDetail
        editDongjia = o.contactDongjiaPhone
        editBoss = o.contactBossPhone
        editDongjiaName = o.contactDongjiaName
        editBossName = o.contactBossName
        editRemark = o.remark
        editInternal = o.internalNotes
        showEditDialog = true
    }

    fun saveEdit() {
        val o = editingOrder ?: return
        // 电话格式先在这一侧挡一道（与后端同一条规则）。老单里可能是"嘿嘿"这种旧数据，
        // 它不会被静默清空 —— 而是明确告诉用户"这一单的电话要改一下才能存"。
        InputRules.phoneError(editDongjia.trim())?.let {
            error = it
            return
        }
        InputRules.phoneError(editBoss.trim())?.let {
            error = it
            return
        }
        acting = true
        viewModelScope.launch {
            try {
                val updated = container.repo.updateOrder(
                    o.id,
                    OrderUpdateRequest(
                        addressDetail = editAddress.trim(),
                        contactDongjiaPhone = editDongjia.trim(),
                        contactBossPhone = editBoss.trim(),
                        contactDongjiaName = editDongjiaName.trim(),
                        contactBossName = editBossName.trim(),
                        remark = editRemark.trim(),
                        internalNotes = editInternal.trim(),
                    ),
                )
                actionResult = "订单已更新"
                showEditDialog = false
                load()
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                acting = false
            }
        }
    }

    // ---- 撤回派单 ----
    fun openRecall(o: OrderDto) {
        recallOrderId = o.id
        recallReason = ""
        showRecallDialog = true
    }

    fun confirmRecall() {
        val oid = recallOrderId ?: return
        if (recallReason.isBlank()) {
            error = "请填写撤回原因"
            return
        }
        acting = true
        viewModelScope.launch {
            try {
                container.repo.recallOrder(oid, recallReason.trim())
                actionResult = "已撤回派单，订单回到派单中"
                showRecallDialog = false
                load()
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                acting = false
            }
        }
    }

    // ---- 异常 ----
    fun openException(o: OrderDto) {
        exceptionOrderId = o.id
        exceptionReason = o.exceptionReason
        exceptionResolution = o.exceptionResolution
        expectedBefore = o.expectedDeliverBefore?.take(16) ?: ""
        showExceptionDialog = true
    }

    fun confirmException() {
        val oid = exceptionOrderId ?: return
        acting = true
        viewModelScope.launch {
            try {
                val body = com.tapmoay.sorders.data.remote.dto.OrderExceptionBody(
                    isException = true,
                    exceptionReason = exceptionReason.trim(),
                    exceptionResolution = exceptionResolution.trim(),
                    expectedDeliverBefore = expectedBefore.trim().ifBlank { null },
                )
                container.repo.markException(oid, body)
                actionResult = "异常已登记"
                showExceptionDialog = false
                load()
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                acting = false
            }
        }
    }

    // 退出/作废弹窗
    // 退货（2026-09-20 用户要求）：「订单管理……我们可以进行一个退货」，
    // 「可以整单退货，也可以只退其中的某几个商品或者是一个商品，他自己勾选」。
    var showReturnDialog by mutableStateOf(false)
    var returnTarget by mutableStateOf<OrderDto?>(null)
    /** 每行退几件（`order_products.id` → 数量）。**只有 > 0 的行才会提交**。 */
    var returnQty by mutableStateOf<Map<Long, Int>>(emptyMap())
    var returnNote by mutableStateOf("")
    var returnSubmitting by mutableStateOf(false)

    /** 这一行**最多还能退几件**（规则只有一份：`core/ReturnRules`，与后端 `max_returnable` 同源）。 */
    fun maxReturnable(line: com.tapmoay.sorders.data.remote.dto.OrderProductDto): Int =
        com.tapmoay.sorders.core.ReturnRules.maxReturnable(
            line.quantity,
            line.damageQuantity,
            line.returnedQuantity,
        )

    fun hasReturnable(o: OrderDto): Boolean = o.orderProducts.any { maxReturnable(it) > 0 }

    /** 打开发货单：默认**全部退满**（用户最常见的就是整单退，再自己往下减）。 */
    fun openReturn(o: OrderDto) {
        returnTarget = o
        returnQty = o.orderProducts.associate { it.id to maxReturnable(it) }
        returnNote = ""
        showReturnDialog = true
    }

    fun setReturnQty(lineId: Long, qty: Int) {
        val o = returnTarget ?: return
        val line = o.orderProducts.firstOrNull { it.id == lineId } ?: return
        // 上限夹在这一处：手输、加减号、整单三条路都走它，所以不可能有"填了 5 却只退 3"的鬼状态
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

    /** 这次要退的金额（元）—— 与后端红冲公式同一份：单价 × 数量。 */
    fun returnAmount(): String {
        val o = returnTarget ?: return "0.00"
        val total = o.orderProducts.fold(java.math.BigDecimal.ZERO) { acc, line ->
            val q = returnQty[line.id] ?: 0
            acc.add(
                (line.unitPrice?.toBigDecimalOrNull() ?: java.math.BigDecimal.ZERO)
                    .multiply(java.math.BigDecimal(q)),
            )
        }.setScale(2, java.math.RoundingMode.HALF_UP)
        return total.toPlainString()
    }

    fun confirmReturn() {
        val o = returnTarget ?: return
        val items = o.orderProducts
            .mapNotNull { line -> (returnQty[line.id] ?: 0).takeIf { it > 0 }?.let { line.id to it } }
        if (items.isEmpty()) {
            error = "请至少勾一个要退的商品（数量大于 0）"
            return
        }
        returnSubmitting = true
        error = null
        viewModelScope.launch {
            try {
                val r = container.repo.returnOrder(
                    o.id,
                    items.map { com.tapmoay.sorders.data.remote.dto.OrderReturnItem(it.first, it.second) },
                    returnNote.trim(),
                )
                actionResult = buildString {
                    append("已退货 ¥").append(r.returnedAmount)
                    if ((r.refundAmount.toDoubleOrNull() ?: 0.0) > 0.0) {
                        append("，并退给客户 ¥").append(r.refundAmount)
                    }
                    if (r.fullyReturned) append("（整单退完，订单已变为「已退货」）")
                    r.warnings.forEach { append("；").append(it) }
                }
                showReturnDialog = false
                returnTarget = null
                load()
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                returnSubmitting = false
            }
        }
    }

    // 复用：编辑/撤回/异常用
    fun dismissDialogs() {
        showEditDialog = false
        showRecallDialog = false
        showExceptionDialog = false
        showReturnDialog = false
    }
}
