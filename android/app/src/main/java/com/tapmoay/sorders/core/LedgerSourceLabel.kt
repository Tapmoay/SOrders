package com.tapmoay.sorders.core

/**
 * 账本流水的「来源」（`ledgers.source`：`order` / `manual` / `refund`）→ 中文 —— **唯一一份实现**。
 *
 * 两个消费点：AI 记账/改账卡片上的「来源：…」，与派单员账本顶部那张**扇形图**的图例。
 * 各写一份 `when` 的后果不是崩，而是**同一个东西在两张界面上叫两个名字**——
 * 用户没法判断"退款红冲"和"退款"是不是同一类账，只能当成两个科目。
 *
 * ⚠️ 认不出的来源**原样显示**（不猜成"其他"）：后端将来加了新来源，
 *    界面上至少还能看出那一格是什么，而不是被并进一个错误的类里。
 */
fun ledgerSourceLabel(raw: String): String = when (raw.lowercase()) {
    "order" -> "订单入账"
    "manual" -> "手工记账"
    "refund" -> "货损红冲"
    else -> raw.ifBlank { "未知来源" }
}
