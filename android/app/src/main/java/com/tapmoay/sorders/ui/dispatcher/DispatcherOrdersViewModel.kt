package com.tapmoay.sorders.ui.dispatcher

import androidx.compose.runtime.*
import androidx.lifecycle.viewModelScope
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.core.InputRules
import com.tapmoay.sorders.data.remote.dto.OrderDto
import com.tapmoay.sorders.data.remote.dto.OrderUpdateRequest
import com.tapmoay.sorders.data.repo.toApiException
import com.tapmoay.sorders.ui.common.ORDER_LIST_LIMIT
import com.tapmoay.sorders.ui.common.ORDER_WINDOW_NO_LIMIT_WORD
import com.tapmoay.sorders.ui.common.OrderTab
import com.tapmoay.sorders.ui.common.OrderWindowViewModel
import com.tapmoay.sorders.util.formatMoney
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch

/**
 * 派单员「订单管理」顶栏那一排档位。
 *
 * ⚠️ 缺省档 = **「派单中」**（用户 2026-09-22 原话：「如果是进来的话，**默认是不会进入「全部」**的，
 *    默认是进入**「派单中」**」）。下标用**状态名**现算，不写 `0/1` —— 档位顺序改过
 *    （货主那列的「已接单」这一轮就挪了一格），写死的下标会把默认档悄悄指到别的档上。
 * ⚠️ `dated = true` 的档才是**可按日期筛**的（药丸可点）：**「全部」也有**（用户：「对，**全部我们也要有
 *    时间的筛选**」）——终态档（已送达/已撤销/已退货）都有；**「派单中」「已接单」不按日期筛**
 *    （用户：「他属于**正在进行**啊，所以他是不会有选择时间」），但它们也有药丸 ——
 *    只是**不可点**、上面写「不限时间」（用户第三轮：「为了美观而统一…那个图标**无法选择**，
 *    他不会有列表，就是只有显示」）。⛔ 那两档**不许写「今天」**，理由见 `ORDER_WINDOW_NO_LIMIT_WORD`。
 * ⚠️ **缺省档与窗口那一套逻辑不在这里**：`tab` / `preset` / `selectTab` / 自动退档都在共用的
 *    `ui/common/OrderWindowViewModel`（构造时把这个表和缺省档的**状态名**交给它）。
 */
val DISPATCH_TABS = listOf(
    OrderTab(null, "全部", dated = true),
    OrderTab("PENDING_DISPATCH", "派单中", windowWord = ORDER_WINDOW_NO_LIMIT_WORD),
    OrderTab("ACCEPTED", "已接单", windowWord = ORDER_WINDOW_NO_LIMIT_WORD),
    OrderTab("DELIVERED", "已送达", dated = true),
    OrderTab("CANCELLED", "已撤销", dated = true),
    // 已退货（2026-09-20）：与「已撤销」**不是一回事**（撤销＝单没发生过，
    // 退货＝送了、入了账、事后货退回来了）。两者都有各自的页签，别合并成一档。
    OrderTab("RETURNED", "已退货", dated = true),
    // 已派单（**DISPATCHED**，2026-09-24 第 19 轮补）：这一档原来**一个档位都没有** ——
    // 而本项目的领域文档（`docs/DOMAIN_MODEL.md:22-23`）写着「`DISPATCHED` 不是过渡态，
    // 它会停留……每个客户端都必须有入口列出它，否则『派错司机』这件事既看不见也撤不回」。
    // 实测代价（本机库只读）：7 张「已派单、司机未接单」的单在**任何具名档位里都查不到**
    // （最老那张卡了 12 天），唯一落点「全部」被自动挡钉在"今天"→ 真正看不见。
    // ⚠️ 它和「派单中」（PENDING_DISPATCH，还没司机）是**两个状态**，不能合并。
    // ⚠️ `dated = false`：它是"正在进行"的一档（与「派单中」「已接单」同类）——
    //    列表不按日期筛，药丸写「不限时间」（⛔ 不许写「今天」，理由见 `OrderTab.windowWord`）。
    OrderTab("DISPATCHED", "已派单", windowWord = ORDER_WINDOW_NO_LIMIT_WORD),
)

class DispatcherOrdersViewModel(container: AppContainer) :
    OrderWindowViewModel(container, DISPATCH_TABS, "PENDING_DISPATCH") {

    var orders by mutableStateOf<List<OrderDto>>(emptyList())
    var loading by mutableStateOf(false)
    var error by mutableStateOf<String?>(null)
    var acting by mutableStateOf(false)
    var actionResult by mutableStateOf<String?>(null)

    /**
     * **弹层里**的失败原因（2026-09-23 真机抓到）。
     *
     * ⛔ 这四个弹层（编辑/撤回/异常/退货）原来把失败写成页面级 [error]，而页面级错误在
     * `DispatcherOrdersScreen` 里被渲染成**整页 ErrorView**、并且被弹层**盖在下面** ——
     * 用户的感受是"点了保存没反应，一关弹层发现整个列表变成了错误页"。
     * 后端那句中文（例如"仅「待派单」状态可编辑明细"）必须画在弹层**里面**。
     * 页面级 [error] 只留给"这一页的数据没加载出来"。
     */
    var dialogError by mutableStateOf<String?>(null)

    /** 打开任一弹层前清掉上一次的失败原因（弹层与它的错误同生共死）。 */
    private fun clearDialogError() {
        dialogError = null
    }

    var search by mutableStateOf("")

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

    // ── 档位选择 + 右上角时间药丸 + 找订单的自动挡 ──
    // **全在共用的 `ui/common/OrderWindowViewModel` 里**（`tab` / `preset` / `customFrom` /
    //  `customTo` / `showDatePresets` / `windowSettled` / `datedTab` / `periodWord` / `windowRange`
    //  / `applyPreset` / `applyCustomRange` / `selectTab`）。
    // 为什么收在一处：这一套原来在派单员与货主两页**一字不差抄了两遍**
    //（`_tools/qa/_scan_dup.py` 当场报出 5 组跨文件重复），而"抄两份"意味着
    // 下一次修 bug 只修一页 —— 本轮真机上抓到的那个坑正好是这一类的证据。
    // 本页只需要提供"怎么取数"：见下面的 [load] 与 [probeHasData]。

    /**
     * 这一档有没有单（自动挡的探测，**只探测、不动页面状态**）。
     *
     * 判据必须与 [load] **同源**：同一个状态（`currentTab.key`，可能是 null）+ 同一套日期窗口 +
     * 同一个关键词 —— 换个接口去猜"有没有单"，就会出现"退档到的那一档页面还是空的"。
     * ⚠️ 探测失败（网络/权限）当"没单"处理：不能因为探测不通就把用户按在一个看不见的窗口上。
     */
    override suspend fun probeHasData(status: String?, from: String, to: String): Boolean = try {
        container.repo.orders(
            status = status,
            q = search.trim().ifBlank { null },
            dateFrom = from,
            dateTo = to,
        ).isNotEmpty()
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
                orders = container.repo.orders(
                    status = currentTab.key,
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

    override fun reload() = load()

    fun searchNow() = load()

    // `selectTab` / `applyPreset` / `applyCustomRange` 都在共用内核里
    // （`ui/common/OrderWindowViewModel`）—— 两页共用同一套"找订单的自动挡"。

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
        clearDialogError()
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
                dialogError = toApiException(e).message
            } finally {
                acting = false
            }
        }
    }

    // ---- 撤回派单 ----
    fun openRecall(o: OrderDto) {
        recallOrderId = o.id
        recallReason = ""
        clearDialogError()
        showRecallDialog = true
    }

    fun confirmRecall() {
        val oid = recallOrderId ?: return
        if (recallReason.isBlank()) {
            dialogError = "请填写撤回原因"
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
                dialogError = toApiException(e).message
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
        clearDialogError()
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
                dialogError = toApiException(e).message
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
        clearDialogError()
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
            dialogError = "请至少勾一个要退的商品（数量大于 0）"
            return
        }
        returnSubmitting = true
        dialogError = null
        viewModelScope.launch {
            try {
                val r = container.repo.returnOrder(
                    o.id,
                    items.map { com.tapmoay.sorders.data.remote.dto.OrderReturnItem(it.first, it.second) },
                    returnNote.trim(),
                )
                actionResult = buildString {
                    append("已退货 ¥").append(formatMoney(r.returnedAmount))
                    if ((r.refundAmount.toDoubleOrNull() ?: 0.0) > 0.0) {
                        append("，并退给客户 ¥").append(formatMoney(r.refundAmount))
                    }
                    if (r.fullyReturned) append("（整单退完，订单已变为「已退货」）")
                    r.warnings.forEach { append("；").append(it) }
                }
                showReturnDialog = false
                returnTarget = null
                load()
            } catch (e: Exception) {
                dialogError = toApiException(e).message
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
        clearDialogError()
    }
}
