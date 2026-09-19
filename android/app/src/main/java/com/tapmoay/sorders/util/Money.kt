package com.tapmoay.sorders.util

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
