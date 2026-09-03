package com.tapmoay.sorders.util

/** 金额格式化：统一两位小数（¥23.50 / ¥859.90），长度一致更美观 */
fun formatMoney(raw: String?): String {
    val v = raw?.toDoubleOrNull() ?: return "0.00"
    return "%.2f".format(v)
}

fun moneyToDouble(raw: String?): Double = raw?.toDoubleOrNull() ?: 0.0
