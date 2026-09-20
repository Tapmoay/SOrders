package com.tapmoay.sorders.util

import com.tapmoay.sorders.data.remote.dto.OrderDto
import java.math.BigDecimal
import java.math.RoundingMode

/** 金额格式化：统一两位小数（¥23.50 / ¥859.90），长度一致更美观 */
fun formatMoney(raw: String?): String {
    val v = raw?.toDoubleOrNull() ?: return "0.00"
    return "%.2f".format(v)
}

fun moneyToDouble(raw: String?): Double = raw?.toDoubleOrNull() ?: 0.0

/**
 * **可编辑的价框**里显示用：去掉末尾多余的 0，**但不丢精度**。
 *
 * - `"12.5000"` → `"12.5"`（后端单价列是 `Numeric(14,4)`，序列化出来一律 4 位小数）
 * - `"12.3456"` → `"12.3456"`（**四位真的有用时一位都不能少**）
 * - `"10.0000"` → `"10"`
 *
 * ⛔ 这里**不能**用 [formatMoney]：它是"显示成两位小数"，把 `12.3456` 显示成 `12.35` ——
 * 在一个**可以编辑**的价框里，那等于骗人（用户不改直接保存，价就真的变了）。
 * 显示用两位、编辑用本函数，两者的区别就在这里。
 *
 * 不是数字的原样返回（界面层不该在这里做校验，校验是 `core/InputRules.kt` 的事）。
 */
fun trimMoneyZeros(raw: String?): String {
    val s = raw?.trim().orEmpty()
    if (s.isEmpty() || s.toDoubleOrNull() == null) return s
    return if (s.contains('.')) s.trimEnd('0').trimEnd('.') else s
}

/**
 * 一张订单的**商品行合计**（定点）—— **全 App 只有这一处**（2026-09-21 精简轮）。
 *
 * ### 为什么必须定点、且只有一处
 * 这个数出现在三个地方，而它们必须给出**同一个数**：
 * ① AI 确认卡上的「订单金额」（`AiOrderRef.amount`）；
 * ② 收款页明细行的 `¥` 与「合计 `¥`」；
 * ③ 收款页的**判据** —— 用户照抄填进去的金额必须与后端用 `Decimal` 算出的那个数**完全相等**，
 *    差一分就 400，而表现是**多行/多单时永久收不了款**（2026-09-19 全项目报告 P0-4：
 *    原来判据用 `Double` 顺序累加，守护者 20 万次随机试验的失配率 2 行 22.72% / 5 行 37.68%）。
 * 三处各写一遍时，任何一处"顺手用 `Double`"或"忘了进位"都会让两边差一分钱，
 * 而**两个数看起来都对** —— 这正是最难查的一类。
 *
 * ⛔ 不要拿 [formatMoney] 来做这件事：那是**显示**口径（`Double` + `%.2f`，
 * 会把 `12.3456` 印成 `12.35`），而这里是在**算钱**。返回 [BigDecimal]，
 * 要下发给模型/写进卡片时用 [goodsTotalText]（两位小数）。
 */
fun OrderDto.goodsTotal(): BigDecimal =
    orderProducts.fold(BigDecimal.ZERO) { acc, p ->
        acc.add(p.lineTotal?.toBigDecimalOrNull() ?: BigDecimal.ZERO)
    }

/**
 * [goodsTotal] 的**两位小数字符串**形态：AI 卡片那些"要一个字面量"的地方用它。
 *
 * 进位规则（`HALF_UP`）只有这一处 —— 与后端 `order_money` 的口径一致。
 */
fun OrderDto.goodsTotalText(): String =
    goodsTotal().setScale(2, RoundingMode.HALF_UP).toPlainString()
