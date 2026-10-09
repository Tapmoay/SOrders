package com.tapmoay.sorders.ui.dispatcher

import com.tapmoay.sorders.data.remote.dto.CustomerBalanceRowDto
import com.tapmoay.sorders.util.formatMoney
import com.tapmoay.sorders.util.moneyToDouble

/**
 * 挂账单位卡上那一行「现在欠着多少 / 还能赊多少」。
 *
 * 由来（2026-10-09 财务方向测试的 TB-01）：这一页原来只有「信用额度 ¥X」。
 * 额度是"允许欠多少"，用户真正要知道的是"现在欠着多少" —— 界面上一个字都没有，
 * 只能点开编辑框看额度、再自己去「客户欠款」报表里翻这个单位。
 *
 * ⛔ 这一行里的数**全部来自接口**（客户欠款表的 `credit_used` / `credit_available` /
 * `over_limit`），与「客户欠款」那一页同一份时点账 —— 客户端一个减法都不做：
 * 界面自己再算一遍「超了多少」就是第二份钱算法，改了一处漏了另一处，两个页面迟早对不上。
 *
 * @param text 直接印在卡上的那一句
 * @param warn true = 这句要用警示色画（现在只有"超了"这一种）
 */
internal data class ArrearsBalanceLine(val text: String, val warn: Boolean)

/**
 * 把客户欠款表里的一行折成挂账单位卡上的一句话（纯函数，好单测）。
 *
 * @param row 这个单位在客户欠款表里的那一行；null = 到目前它一分钱都没欠过
 *            （⛔ 不是"欠了 0 元"，所以不许写成 ¥0.00）。
 */
internal fun arrearsBalanceLine(row: CustomerBalanceRowDto?): ArrearsBalanceLine {
    // 名册上有这个单位、账上却找不到它 ⇒ 到现在还没有任何欠款事实。
    if (row == null) return ArrearsBalanceLine("到目前还没有欠款记录", false)
    // credit_used = max(余额, 0)：后端把"欠着"和"预收"分成两个数给，这里照着说，别自己比大小。
    val used = moneyToDouble(row.creditUsed)
    if (used <= 0.0) {
        val prepaid = moneyToDouble(row.prepaid)
        // 预收是"先给了钱、还没抵完"，与欠款是两码事 —— 有就单独说一句，没有就只说没有欠款。
        return ArrearsBalanceLine(
            if (prepaid > 0.0) "没有欠款 · 预收 ¥" + formatMoney(row.prepaid) else "没有欠款",
            false,
        )
    }
    val owed = "已挂账 ¥" + formatMoney(row.creditUsed)
    // 没设过额度 = 不限额（⛔ 不许当成 ¥0：那会把"没管过"说成"一分都不许赊"）。
    if (row.limit == null) return ArrearsBalanceLine(owed + " · 额度：不限额", false)
    if (row.overLimit) {
        // 「超了」用的是后端给的 over_limit 布尔，不在这儿做 credit_used - limit 那个减法。
        return ArrearsBalanceLine(owed + " · 额度 ¥" + formatMoney(row.limit) + "（已超）", true)
    }
    val available = row.creditAvailable
    if (available == null) {
        // 后端说算不出来时只说额度，⛔ 不许当成「还能赊 ¥0.00」。
        return ArrearsBalanceLine(owed + " · 额度 ¥" + formatMoney(row.limit), false)
    }
    return ArrearsBalanceLine(owed + " · 还能赊 ¥" + formatMoney(available), false)
}
