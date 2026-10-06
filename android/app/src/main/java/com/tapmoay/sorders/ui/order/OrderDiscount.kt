package com.tapmoay.sorders.ui.order

import com.tapmoay.sorders.data.remote.dto.OrderDto
import com.tapmoay.sorders.util.formatMoney
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import java.math.BigDecimal

/**
 * 订单打折（CHG-0071 / 台账 L-34）：**这一页只做「值填得对不对」与「给用户看的那几行字」**。
 *
 * ⛔ 折扣算法只有一份：后端 `backend/app/services/order_discount.py`。
 *    这里一个乘法都不做 —— 摊到每行的钱、实际优惠了多少，全部由服务端算好返回
 *    （`discountAmount` / 折后的 `orderProducts[].lineTotal`）。客户端自己算一遍，
 *    迟早与账上的数差几毛，而账单上差一毛就是两本账。
 *
 * ⛔ 不做「打几折 = 原价 × (1 − 10%)」这种预演：抹零会被"最后一行没那么多钱"改小，
 *    预演出来的数与服务端不一样，用户会以为界面在骗他。
 */

/** `percent` = 减百分比；`amount` = 抹零（减一个金额）。后端 `order_discount.py` 的口径。 */
const val DISCOUNT_KIND_PERCENT = "percent"
const val DISCOUNT_KIND_AMOUNT = "amount"

/**
 * 能打折的状态：与后端 `api/v1/order_products.py::LINE_EDITABLE_STATUSES` 同一组值
 * （已送达 / 已撤销 / 已退货的单不能再动钱 —— 钱已经进账本了）。
 *
 * ⚠️ 与 `core/OrderStatusModel.EDITABLE` 今天是同一组值，但**不是同一件事**：那个管"改信息"，
 *    这个管"改钱"。所以另立一个名字，判据会核对三者是同一组值（改一处忘一处就红）。
 */
val DISCOUNT_STATUSES: Set<String> = setOf("PENDING_DISPATCH", "DISPATCHED", "ACCEPTED")

fun canDiscount(status: String): Boolean = status.uppercase() in DISCOUNT_STATUSES

/** 两种方式在界面上的名字（真机截图与 Hint 都用它，免得三处各写一个词）。 */
fun discountKindLabel(kind: String): String =
    if (kind == DISCOUNT_KIND_AMOUNT) "抹零" else "减百分比"

/**
 * 值框的校验：null = 可以发；非 null = 给用户看的那句话。
 *
 * 拦在这里的是"一定发不出去"的数（空 / 不是数 / ≤0 / 百分比 ≥100 / 超过四位小数）；
 * 业务规则（抹零比整单还多、勾到了「不参与打折」的行）留在服务端 —— 那些要看这一单现在
 * 到底有多少钱、商品档案上勾没勾，客户端看不到全部。
 */
fun discountValueError(kind: String, raw: String): String? {
    val s = raw.trim()
    if (s.isEmpty()) return "先填一个数"
    val v = s.toBigDecimalOrNull() ?: return "只能填数字（比如 10 或 12.5）"
    if (v <= BigDecimal.ZERO) return "要大于 0"
    if (kind == DISCOUNT_KIND_PERCENT && v >= BigDecimal("100")) {
        return "百分比要小于 100%（那等于白送，请改用「抹零」）"
    }
    if (v.scale() > 4) return "最多四位小数"
    return null
}

/** 发出去的值：原样的数字串（⛔ 不做任何格式化 —— 去掉尾零再解析，精度就变了）。 */
fun discountValueToSend(raw: String): String = raw.trim()

/** 「减 10%」/「抹零 ¥20」—— 订单详情与操作日志里都是这一句话。 */
fun discountSummary(kind: String, value: String?): String =
    // ⚠️ `¥` 与 `formatMoney(` 必须**同一行**：`_check_money_display.py` §3 是按行判的，
    //    把值先存进 `val v` 再拼，那一行就只剩一个裸变量 ⇒ 判据认不出它过了漏斗。
    if (kind == DISCOUNT_KIND_AMOUNT) "抹零 ¥${formatMoney(value)}" else "减 ${formatMoney(value)}%"

/** 「已优惠 ¥12.5」；没打折 / 优惠是 0 时返回 null（界面据此整行不画）。 */
fun discountHeadline(order: OrderDto): String? {
    val amount = order.discountAmount?.toBigDecimalOrNull() ?: return null
    if (amount <= BigDecimal.ZERO) return null
    return "已优惠 ¥" + formatMoney(order.discountAmount)
}

/**
 * 折扣的来龙去脉：「减 10% · 张三 · 理由：老客户」。
 *
 * ⛔ 时刻不在这里拼（那是界面层的事，`util/TimeFmt.kt`）；理由为空就不印「理由：」这一截。
 */
fun discountTrace(order: OrderDto): String? {
    val kind = order.discountKind
    if (kind.isNullOrBlank()) return null
    val parts = mutableListOf(discountSummary(kind, order.discountValue))
    order.discountByName?.takeIf { it.isNotBlank() }?.let { parts += it }
    order.discountReason?.takeIf { it.isNotBlank() }?.let { parts += "理由：" + it }
    return parts.joinToString(" · ")
}

/**
 * 这一单已经参与过折扣的行 id（「改折扣」时把勾预先打上）。
 *
 * 空集 = 老数据没有逐行快照 ⇒ 界面按"整单"处理（与后端 `plan_discount` 同一条退路）。
 */
fun discountLineIds(order: OrderDto): Set<Long> {
    val out = mutableSetOf<Long>()
    order.discountLines?.forEach { row ->
        val raw = (row["line_id"] as? JsonPrimitive)?.contentOrNull ?: return@forEach
        raw.toLongOrNull()?.let { out += it }
    }
    return out
}
