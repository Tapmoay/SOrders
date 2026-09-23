package com.tapmoay.sorders.ui.dispatcher

import com.tapmoay.sorders.data.remote.dto.OrderDto
import com.tapmoay.sorders.data.remote.dto.OrderProductDto
import com.tapmoay.sorders.util.lineTotalValue
import java.math.BigDecimal
import java.math.RoundingMode

/**
 * 账本「某个货主 / 某个批发商」那一页的**商品统计**（2026-09-20 用户要求）。
 *
 * 用户原话：「它会统计一下它**哪些货物**下来、**哪些货物欠了多少钱**、**哪些货物对应哪些价**，
 * 然后它欠多少钱」。也就是三列：数量 / 单价 / 金额，外加"其中未收"。
 *
 * ## 口径（唯一一份，改这里就是改全局）
 *
 * · **金额** = 这一时期里这几样货的货款（`line_total` − 退掉的部分）；
 * · **其中未收** = 这些货**还欠着的那部分**：按**每张单的欠款比例**分摊到它的商品行上。
 *
 * 为什么要"按比例分摊"而不是"整单未收就全额计入"：一张单可能只收了一部分
 * （按商品核销 / 部分退款），那时"整单计入"会把 100 元的货算成"欠 100"，
 * 而这张单其实只欠 30 —— 报表上多出来的 70 元没有任何人认领。
 * 比例分摊是**唯一能让每一列加起来等于总数**的口径：
 * `Σ(各商品未收) == Σ(各订单欠款)`（分位取整时余数落在最后一行，见 [productStats]）。
 *
 * ## 与后端的关系
 * 这里的"一行还能收多少"（[lineReceivableCents]）与后端
 * `app/services/order_money.py::line_receivable` 是**同一个公式**：
 * `line_total − 单价 × 已退数量`。后端那份是钱进账时的判据，这一份只用于**显示**；
 * 两边算得不一样时，界面上的合计会与提交后后端算出的数对不上（用户会以为被吞了钱）。
 */
data class ProductStat(
    val name: String,
    val unit: String,
    /** 数量（**不含**已退掉的那些）。 */
    val quantity: Int,
    /** 金额（元）。 */
    val amount: BigDecimal,
    /** 其中还没收到的（元）。 */
    val owed: BigDecimal,
) {
    /** 加权均价（金额 ÷ 数量），两位小数；数量为 0 时给 0。 */
    val unitPrice: BigDecimal
        get() = if (quantity <= 0) BigDecimal.ZERO
        else amount.divide(BigDecimal(quantity), 2, RoundingMode.HALF_UP)
}

/**
 * 这一行**现在还能收多少**（分）＝ 行金额 − 单价 × 已退数量。
 *
 * ⚠️ 退货只改账本红冲、**不改行金额**（那是"当时卖了多少"），所以不能直接用 `lineTotal`：
 *    拿它当应收，退过货的单会被按原价收钱。
 */
fun lineReceivableCents(p: OrderProductDto): Long {
    // ⛔ **先在 Decimal 里相减、最后才取分**（2026-09-24 第 21 轮 E4-1 实测）：
    //    原来两边**各自先取分**再相减 —— `moneyCents(lineTotal)` 与
    //    `moneyCents(unit × returnedQty)`，而后端 `order_money` 是"先相减再取分"。
    //    单价 0.5050 × 2 件 → 行金额 1.01 → 退 1 件：后端算出 **0.51**、这里算出 **0.50**，
    //    于是核销时后端判"收款金额 0.50 与所选订单合计 0.51 不一致" → **这笔款永远收不了**
    //    （0.5~20 元区间有 23400 个"单价×数量×退货数"组合会命中，不是孤立点）。
    //    顺序必须与后端逐字一致：**只有一处口径**（`order_money.line_receivable`）。
    //    行金额那个串也只许在一处 parse（`util/Money.kt::lineTotalValue`）——
    //    它同时喂「订单金额」与这里的行应收，两边各自 parse 就会出现上面那种一分钱的分叉。
    val total = p.lineTotalValue()
    val unit = p.unitPrice?.toBigDecimalOrNull() ?: BigDecimal.ZERO
    val returned = unit.multiply(BigDecimal(p.returnedQuantity))
    return moneyCents((total - returned).toPlainString())
}

/** 金额字符串 → **分**（四舍五入到分，与后端 `q2` 同一个进位方式）。 */
fun moneyCents(raw: String?): Long =
    (raw?.toBigDecimalOrNull() ?: BigDecimal.ZERO)
        .setScale(2, RoundingMode.HALF_UP)
        .movePointRight(2)
        .toLong()

/** 分 → 金额字符串（两位小数）。 */
fun centsToMoney(cents: Long): String =
    BigDecimal(cents).movePointLeft(2).setScale(2, RoundingMode.HALF_UP).toPlainString()

/**
 * 这张单的**应收**（分）＝ 各行应收之和（与后端 `order_money.receivable` 同源）。
 * 欠款的判据**不用** `orderTotal − settled`：退货红冲与退现都不在 settled 里。
 */
fun orderReceivableCents(o: OrderDto): Long = o.orderProducts.sumOf { lineReceivableCents(it) }

/** 这张单**还欠多少**（分）—— 直接取后端算好的 `arrears_amount`，客户端不重算。 */
fun orderArrearsCents(o: OrderDto): Long = moneyCents(o.arrearsAmount)

/**
 * 按商品汇总这一批订单。
 *
 * ⚠️ 退货：已退掉的那部分**既不算数量也不算金额**（货退回来了，不该出现在"卖了哪些货"里），
 *    这一条与页面上「已退 ¥X」那一行是同一个事实的两种展示。
 */
fun productStats(orders: List<OrderDto>): List<ProductStat> {
    class Acc(var qty: Int = 0, var amount: Long = 0L, var owed: Long = 0L, var unit: String = "")

    val map = LinkedHashMap<String, Acc>()
    orders.forEach { o ->
        val lines = o.orderProducts
        val receivable = lines.sumOf { lineReceivableCents(it) }
        val arrears = orderArrearsCents(o)
        var allocated = 0L
        lines.forEachIndexed { i, line ->
            val net = lineReceivableCents(line)
            val netQty = (line.quantity - line.returnedQuantity).coerceAtLeast(0)
            if (netQty <= 0 && net == 0L) return@forEachIndexed
            // 这一行分到的欠款：按它占整单应收的比例。
            // 最后一行吃掉**余数**，所以 Σ(各行) 精确等于这一单的欠款（不多不少一分）。
            val share = when {
                i == lines.lastIndex -> arrears - allocated
                receivable <= 0L -> 0L
                else -> arrears * net / receivable
            }
            allocated += share
            val acc = map.getOrPut(line.productNameSnapshot.ifBlank { "（未命名商品）" }) { Acc() }
            acc.qty += netQty
            acc.amount += net
            acc.owed += share
            if (acc.unit.isBlank()) acc.unit = line.unit
        }
    }
    return map.entries
        .map { (name, a) ->
            ProductStat(
                name = name,
                unit = a.unit,
                quantity = a.qty,
                amount = BigDecimal(a.amount).movePointLeft(2).setScale(2, RoundingMode.HALF_UP),
                owed = BigDecimal(a.owed).movePointLeft(2).setScale(2, RoundingMode.HALF_UP),
            )
        }
        // 金额大的排前面（与账本页别处的"按金额倒序"一致）
        .sortedByDescending { it.amount }
}
