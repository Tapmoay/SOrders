package com.tapmoay.sorders.ui.shipper

import com.tapmoay.sorders.data.remote.api.ShipperSettlementDto
import com.tapmoay.sorders.data.remote.dto.OrderDto
import com.tapmoay.sorders.data.remote.dto.OrderProductDto
import com.tapmoay.sorders.ui.dispatcher.lineReceivableCents
import com.tapmoay.sorders.ui.dispatcher.moneyCents

/**
 * 货主账本（**以订单为基础**）的分组与合计 —— 纯函数，有单测。
 *
 * ## 两本账，别混（用户 2026-09-20 原话）
 * 「真正的批发商核销是派单员，他是另外一回事」「他这个核销是他另外的、独立的，他自己管自己的」。
 *
 * | 数 | 谁欠谁 | 从哪来 |
 * | --- | --- | --- |
 * | [LedgerTotals.dispatcherArrearsCents] | **我欠总分销商** | 后端算好的 `arrears_amount` 逐单相加（[orderArrearsCents]），**客户端不重算** |
 * | [LedgerCustomer.owedCents] | **我的货主欠我** | 各行「货款 − 我已核销」之和（[lineRemainingCents]） |
 *
 * ## 归属谁（哪个货主）
 * 用户原话：「他下单，有时候他会填**下单人**是谁……或者**收货人**也是货主（他批发商的货主）」。
 * 真实数据给出了答案：本机 108 张批发商订单里，**下单人恒为批发商自己**、**收货人才是各不相同的客户**，
 * 所以归属取**收货人**（空则退到下单人，再空进「未指定」那一档 —— 不编名字）。
 *
 * ## 钱的口径只有一处
 * 「这一行还能收多少」= `ui/dispatcher/LedgerPersonStats.kt::lineReceivableCents`
 * （与后端 `order_money.line_receivable` 同一个公式）。**这里不另写一份**：
 * 两边算得不一样时，界面上的合计会和提交后后端算出的数对不上，用户只会以为被吞了钱。
 */

/** 归属人为空时的那一档（**不编名字**：编一个会让用户以为这单真的记了人）。 */
const val UNSET_CUSTOMER = "未指定货主"

/** 收货人名（空则下单人名，空则 [UNSET_CUSTOMER]）。 */
fun customerNameOf(o: OrderDto): String {
    val dongjia = o.contactDongjiaName.trim()
    if (dongjia.isNotEmpty()) return dongjia
    val boss = o.contactBossName.trim()
    if (boss.isNotEmpty()) return boss
    return UNSET_CUSTOMER
}

/** 归属人的电话（与名字同源：收货人优先）。 */
fun customerPhoneOf(o: OrderDto): String {
    val a = o.contactDongjiaPhone.trim()
    if (a.isNotEmpty()) return a
    return o.contactBossPhone.trim()
}

/**
 * 分组键 = 名字 + 电话。
 *
 * ⚠️ 只用名字会把**两个同名客户并成一个**（"张老板"在这个行业里遍地都是），
 *    而合并的后果是"他的欠款翻倍、另一个人的欠款不见了" —— 两边都不报错。
 * 电话为空时（老单没记）用名字兜底。
 */
fun customerKeyOf(o: OrderDto): String = customerNameOf(o) + "|" + customerPhoneOf(o)

/** 每一行**已经核销了多少**（分）。只算没撤销的核销记录。 */
fun settledByLineCents(settlements: List<ShipperSettlementDto>): Map<Long, Long> {
    val out = HashMap<Long, Long>()
    settlements.forEach { s ->
        if (s.isDeleted) return@forEach
        s.lines.forEach { ln ->
            out[ln.orderProductId] = (out[ln.orderProductId] ?: 0L) + moneyCents(ln.amount)
        }
    }
    return out
}

/** 每一单**已经核销了多少**（分）。 */
fun settledByOrderCents(settlements: List<ShipperSettlementDto>): Map<Long, Long> {
    val out = HashMap<Long, Long>()
    settlements.forEach { s ->
        if (s.isDeleted) return@forEach
        out[s.orderId] = (out[s.orderId] ?: 0L) + moneyCents(s.amount)
    }
    return out
}

/**
 * 这一行**现在还能核销多少**（分）＝ 行应收 − 已核销（不小于 0）。
 *
 * 与后端 `services/shipper_settle.py::line_remaining` 是同一个式子；界面拿它显示、
 * 后端拿它校验上限，**两边必须一致**（不一致时用户按界面上的数点核销会被 400 拦下）。
 */
fun lineRemainingCents(line: OrderProductDto, settled: Map<Long, Long>): Long {
    val left = lineReceivableCents(line) - (settled[line.id] ?: 0L)
    return if (left > 0L) left else 0L
}

/** 这一单**现在还能核销多少**（分）＝ 各行还可核销之和。 */
fun orderRemainingCents(o: OrderDto, settled: Map<Long, Long>): Long =
    o.orderProducts.sumOf { lineRemainingCents(it, settled) }

/** 这一单的货款（分）＝ 各行应收之和（退掉的那部分已经扣掉）。 */
fun orderGoodsCents(o: OrderDto): Long = o.orderProducts.sumOf { lineReceivableCents(it) }

/** 他欠总分销商多少（分）——**后端算好的数**，客户端不加不减。 */
fun orderArrearsCents(o: OrderDto): Long = moneyCents(o.arrearsAmount)

/**
 * 一个货主（联系人）在这一段里的一本小账。
 *
 * `orders` 按传入顺序（后端是按 id 倒序，即新单在前）。
 */
data class LedgerCustomer(
    val key: String,
    val name: String,
    val phone: String,
    val orders: List<OrderDto>,
    /** 这些单的货款合计（我卖给他的货值）。 */
    val goodsCents: Long,
    /** 其中**他已经给我的**（我核销掉的）。 */
    val settledCents: Long,
    /** 其中**他还欠我的**。 */
    val owedCents: Long,
    /** 还没结清的单数（这一单还收得动钱）。 */
    val unsettledOrders: Int,
)

/**
 * 按货主（联系人）分组：**先总计、再订单明细**（用户原话的排列顺序）。
 *
 * 排序：**欠得多的在前** —— 账本要回答的第一个问题是"谁还欠我钱"，
 * 欠 0 的人排最前面会把这个答案埋掉（与派单员账本"按金额倒序"同一条约定）。
 */
fun groupByCustomer(
    orders: List<OrderDto>,
    settlements: List<ShipperSettlementDto>,
): List<LedgerCustomer> {
    val settled = settledByLineCents(settlements)
    val buckets = LinkedHashMap<String, MutableList<OrderDto>>()
    orders.forEach { o -> buckets.getOrPut(customerKeyOf(o)) { mutableListOf() }.add(o) }
    return buckets.entries
        .map { (key, list) ->
            val first = list.first()
            val goodsCents = list.sumOf { orderGoodsCents(it) }
            val settledCents = list.sumOf { orderGoodsCents(it) - orderRemainingCents(it, settled) }
            val owedCents = list.sumOf { orderRemainingCents(it, settled) }
            LedgerCustomer(
                key = key,
                name = customerNameOf(first),
                phone = customerPhoneOf(first),
                orders = list,
                goodsCents = goodsCents,
                settledCents = settledCents,
                owedCents = owedCents,
                unsettledOrders = list.count { orderRemainingCents(it, settled) > 0L },
            )
        }
        .sortedWith(compareByDescending<LedgerCustomer> { it.owedCents }.thenBy { it.name })
}

/** 顶部那张卡上的四个数（**当前筛选下**的，不是历史总额）。 */
data class LedgerTotals(
    val orders: Int,
    /** 我欠总分销商（后端 `arrears_amount` 逐单相加）。 */
    val dispatcherArrearsCents: Long,
    /** 货款合计（我该向下游收的）。 */
    val goodsCents: Long,
    /** 其中已经收回来多少。 */
    val settledCents: Long,
    /** 其中还欠我多少。 */
    val owedCents: Long,
    /** 其中已经结清的单数（欠款 ≤ 0）。 */
    val clearedOrders: Int,
)

/** 当前筛选下的合计。 */
fun ledgerTotals(orders: List<OrderDto>, settlements: List<ShipperSettlementDto>): LedgerTotals {
    val settled = settledByLineCents(settlements)
    val goods = orders.sumOf { orderGoodsCents(it) }
    val owed = orders.sumOf { orderRemainingCents(it, settled) }
    return LedgerTotals(
        orders = orders.size,
        dispatcherArrearsCents = orders.sumOf { orderArrearsCents(it) },
        goodsCents = goods,
        settledCents = goods - owed,
        owedCents = owed,
        clearedOrders = orders.count { orderRemainingCents(it, settled) <= 0L },
    )
}

/**
 * 本地的兜底筛选（**联系人搜索**）。
 *
 * 为什么服务端已经按 `q` 筛过了还要有这一份：**批发商搜的是联系人（客户）**，
 * 而服务端的 `q` 是"单号/地址/电话/名字"的全字段模糊匹配 —— 用户输入一个客户名时，
 * 命中集合里可能混进"地址里正好含这几个字"的单（另一家的单）。本地这一道只按
 * **归属人**过滤，保证"搜谁就只看谁"，且他的**合计**与列表是同一个集合。
 *
 * 判据与全项目一致：子串匹配、大小写不敏感（不写"取后四位"这类额外分支）。
 */
fun filterByCustomer(
    customers: List<LedgerCustomer>,
    keyword: String,
): List<LedgerCustomer> {
    val kw = keyword.trim()
    if (kw.isEmpty()) return customers
    return customers.filter { c ->
        c.name.contains(kw, ignoreCase = true) || c.phone.contains(kw, ignoreCase = true)
    }
}
