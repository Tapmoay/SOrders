package com.tapmoay.sorders.util

import com.tapmoay.sorders.data.remote.dto.OrderDto
import com.tapmoay.sorders.data.remote.dto.OrderProductDto
import java.math.BigDecimal
import java.math.RoundingMode
import java.util.Locale

/**
 * 金额**显示**（`¥` 后面那一串）：先按分四舍五入，**再去掉末尾多余的 0**。
 *
 * - `"56.70"` → `"56.7"`、`"87.00"` → `"87"`（用户 2026-09-22：「有零的全省」）
 * - `"56.77"` → `"56.77"` —— **有零以外的位一位都不能少**。"去掉多余的 0" 与 "把 7 约掉" 是
 *   两件事，这条就是分界：只动**末尾的 0**，不做任何近似。
 * - `"12.3456"` → `"12.35"`（显示只留两位：这不是精度口径，精度口径见 [trimMoneyZeros]）
 *
 * ### ⛔ 显示 vs 值：两件事，别混（混一次就是"没改价、价却变了"）
 * 这里是**给人看的字**，所以末尾的 0 是噪音。而这些地方**一位都不许动**：
 * ① 进出接口的金额（后端 `Decimal` 出参、写回 payload 的字段）；
 * ② **判据**（[goodsTotalText] 是收款页的判据，差一分就永久收不了款）；
 * ③ 用户**自己打的**金额输入框（`core/InputRules.moneyInput`）；
 * ④ 可编辑价框的预填（那是 [trimMoneyZeros]：去零**但保四位精度**，免得 `12.3456` 被显示成 `12.35`）。
 *
 * 进位算法**没换**（仍是 `Double` + `%.2f`，与 2026-09-22 之前逐位一致），本轮只少印几个 0 ——
 * 所以任何一笔钱的数字都不会变。`Locale.US` 是防某些语言把小数点印成逗号（`56,7`）。
 */
fun formatMoney(raw: String?): String {
    val v = raw?.toDoubleOrNull() ?: return "0"
    // `%.2f` 一定带小数点，所以先删 '0' 再删那个小数点不会误伤 `100` 这种整数。
    val s = "%.2f".format(Locale.US, v).trimEnd('0').trimEnd('.')
    // `-0.001` 会印成 `-0`：负零不是钱，摆正（否则界面上出现「¥-0」）。
    return if (s == "-0") "0" else s
}

fun moneyToDouble(raw: String?): Double = raw?.toDoubleOrNull() ?: 0.0

/**
 * **可编辑的价框**里显示用：去掉末尾多余的 0，**但不丢精度**。
 *
 * - `"12.5000"` → `"12.5"`（后端单价列是 `Numeric(14,4)`，序列化出来一律 4 位小数）
 * - `"12.3456"` → `"12.3456"`（**四位真的有用时一位都不能少**）
 * - `"10.0000"` → `"10"`
 *
 * ⛔ 这里**不能**用 [formatMoney]：它是"显示成两位小数（再去尾零）"，把 `12.3456` 显示成 `12.35` ——
 * 在一个**可以编辑**的价框里，那等于骗人（用户不改直接保存，价就真的变了）。
 * 显示只留两位、编辑一位不少，两者的区别就在这里。
 * ⛔ 反过来也不行：显示不能改用本函数 —— 后端单价是 `Numeric(14,4)`，那会把 `12.3400` 印成 `12.34` 的
 * 同时把 `12.3456` 原样印出来，卡片上出现四位小数（显示口径就是"到分为止"）。
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
    orderProducts.fold(BigDecimal.ZERO) { acc, p -> acc.add(p.lineTotalValue()) }

/**
 * 一行商品的**行金额**（定点）—— `line_total` 那个字符串 → [BigDecimal] 的**唯一一处**。
 *
 * 为什么单独抽出来（2026-09-24 第 22 轮）：这两个消费者必须从同一个串里读出**同一个数**，
 * 而它们各自去 parse 一次字符串时，任何一边"顺手换个进位方式"就会让两边差一分：
 * ① [goodsTotal]（Σ 各行 ＝ 界面上的「订单金额」，同时是收款页的判据）；
 * ② 账本页的行应收（`ui/dispatcher/LedgerPersonStats.kt::lineReceivableCents`：
 *    `行金额 − 单价 × 已退数量`，与后端 `order_money.line_receivable` 同一个式子）。
 *
 * 空串 / 不是数字 → 0（`null` 在这里的含义是"没有行金额"，不是"金额未知"）。
 */
fun OrderProductDto.lineTotalValue(): BigDecimal =
    lineTotal?.toBigDecimalOrNull() ?: BigDecimal.ZERO

/**
 * [goodsTotal] 的**两位小数字符串**形态：AI 卡片那些"要一个字面量"的地方用它。
 *
 * 进位规则（`HALF_UP`）只有这一处 —— 与后端 `order_money` 的口径一致。
 *
 * ⛔ **这是"值"，不是"显示"**：它同时是收款页的判据（要与后端 `Decimal` 完全相等）和写进
 * AI 卡片的字面量，所以**故意留两位**、不许过 [formatMoney] 去尾零 ——
 * 那个 `56.70 → 56.7` 的显示规则（用户 2026-09-22 定的）只作用于**给人看的字**。
 */
fun OrderDto.goodsTotalText(): String =
    goodsTotal().setScale(2, RoundingMode.HALF_UP).toPlainString()
