package com.tapmoay.sorders.ui.dispatcher

import com.tapmoay.sorders.ui.common.DatePresets
import java.time.LocalDate

/**
 * 报表中心里那些**纯映射**：页签 → 导出 kind、后端枚举 → 中文、资金方向 → 收/支。
 *
 * ### 为什么单独一个文件（而不是留在 Composable 里）
 * 这三个映射各自都曾经**悄悄错过**，而它们的错法都一样：**界面上看不出来**。
 * - 页签 → 导出 kind 错位：用户拿到一个名字叫「客户经营」、内容是异常审计的 xlsx，导出还提示"成功"；
 * - 资金方向比大小写：`"IN" != "in"` → 资金流入恒 ¥0.00，而每一笔收款都被显示成"支出 −¥500"；
 * - biz_type 词表认的是猜的取值（`"payment"`）而后端存的是枚举名（`PAYMENT_DRIVER`）→ 整页显示原始码。
 *
 * 三者的共同点是"没有一处会报错"。所以它们必须是**纯函数 + 单测**，
 * 而不是散在某个 Composable 里的 `when`（那些写错了没有任何东西会响）。
 */
internal object ReportFinance {

    /**
     * 报表接口那两个**历史参数**（`mode` + `date`）在 App 里固定送的值。
     *
     * ⚠️ 2026-09-22 起页面上的窗口是**一段明确区间**（`date_from`/`date_to`），后端两个都给时
     * **区间优先**（`reports.py::_span` 一处判）。但这两个参数在签名里仍是必填（还有别的调用方、
     * 还有既有测试走 `mode`+`anchor`），所以这里送一对**不起作用**的值，
     * 而不是让每个调用点各写一遍字面量。
     */
    const val LEGACY_MODE = "day"

    /**
     * 「全部」在这一页落成的区间起点（见 VM 的 `windowOf`）。
     *
     * 报表两个端点必须给一段窗口（给不出"不带日期条件"那种），而档位表里的「全部」
     * 就是"看所有数据" —— 用 `2000-01-01 ~ 今天` 落它：库里的数据都在这段里，
     * 所以药丸上写「全部」与画出来的数字**是同一件事**。
     * ⛔ 不许悄悄换成"近一年"那种更窄的窗口 —— 那就是口径词与窗口不一致。
     */
    const val ALL_FROM = "2000-01-01"

    /**
     * 档位 → 这一次要看的 `(from, to)` —— **报表六个页签共用这一处**（页面、导出、探测都用它）。
     *
     * 三条规矩：
     * 1. **自定义**两头都给了才用那一段（只给一头是弹层的半成品状态，见下）；
     * 2. 其余档位一律问 `DatePresets.rangeOf`（**档位与区间的唯一实现** —— 报表这边不另算一遍，
     *    否则「本月」在报表是整月、在账本是 1 日到今天，两个页面两个口径）；
     * 3. 「全部」这种**不带日期条件的档位**（`rangeOf` 返回 null）落成 [ALL_FROM] ~ 今天：
     *    报表两个端点必须给一段窗口，而这一段覆盖了库里所有数据 —— 药丸上写「全部」
     *    与画出来的数字仍然是同一件事。
     *
     * ⚠️ 半截自定义（只选了一头）**不该发生**（弹层只在两头都有时才回调）。真发生了就按
     *    **最宽**的窗口看：报表宁可多算，也⛔不许悄悄少算一段 —— 少算的那几天页面上看不出来。
     */
    fun windowOf(preset: String, customFrom: String?, customTo: String?, today: LocalDate): Pair<String, String> {
        if (preset == DatePresets.CUSTOM && customFrom != null && customTo != null) {
            return customFrom to customTo
        }
        return DatePresets.rangeOf(preset, today) ?: (ALL_FROM to today.toString())
    }

    /**
     * 这一段**有没有数**（自动挡的判据）。
     *
     * ⚠️ 判据必须与页面自己的取数**同源**：报表这一页的窗口是**页面级**的（六个页签共用一段），
     * 所以"这段有没有业务"由「营业纵览」那份营业额来说 —— 探测打的就是
     * `GET /reports/turnover`（页面第一屏自己要打的那个接口）、用的就是**同一段区间**
     * （`date_from`/`date_to`），不是另找一个便宜的近似接口
     * （那会变成"探到了、进去还是空"，正是 2026-09-22 那个 bug 的翻版）。
     *
     * 两个数任一非零就算有数：`total_orders` 是窗口内已送达单数，`total_amount` 是营业额。
     * 只认单数会在"有营业额但单数统计口径变了"时误判，只认金额会在"0 元单"上误判。
     */
    fun hasData(totalOrders: Int, totalAmount: String): Boolean =
        totalOrders > 0 || (totalAmount.toDoubleOrNull() ?: 0.0) != 0.0


    /**
     * 报表页签 → 后端导出的 `kind`。
     *
     * ⚠️ 页签顺序的唯一真相是 `ReportHomeScreen` 里那份入口清单（0 营业纵览 / 1 商品经营 /
     * 2 司机绩效 / 3 客户经营 / 4 资金收支 / 5 异常与审计）。这一版之前是**错位**的
     * （3→audit、4→customers、else→finance），而后端的 kind 白名单恰好接受这三个词，
     * 所以不会 400——导出"成功"，只是内容是别人的。
     */
    fun exportKind(tab: Int): String = when (tab) {
        0 -> "turnover"
        1 -> "products"
        2 -> "drivers"
        3 -> "customers"
        4 -> "finance"
        else -> "audit"
    }

    /**
     * 资金方向是不是"收"。
     *
     * 后端 `CashFlowDirection` 的真实取值是**小写** `in` / `out`
     * （`backend/app/models/enums.py`）。这里刻意用 `equals(ignoreCase = true)`：
     * 哪天后端改成大写也不会重演"整页金额恒为零"。
     */
    fun isIncome(direction: String?): Boolean = direction?.trim()?.equals("in", ignoreCase = true) == true

    /**
     * 资金流水业务类型 → 中文。
     *
     * 取值是**枚举名**（`CashFlowBizType`），不是小写短语。旧的词表写的是
     * `"payment" / "driver_payment" / "damage"` 这一类猜出来的词——一个都对不上，
     * 于是整页显示 `PAYMENT_DRIVER` 这样的原始码。
     */
    fun bizLabel(biz: String?): String = when (biz?.trim()?.uppercase()) {
        "RECEIPT_CASH" -> "客户收款（现金）"
        "RECEIPT_TRANSFER" -> "客户收款（转账）"
        "RECEIPT_ARREARS" -> "挂账结清"
        "RECEIPT_PREPAID" -> "预收款"
        "PAYMENT_DRIVER" -> "司机运费"
        "PAYMENT_SALARY" -> "司机工资"
        "PAYMENT_DRIVER_ADVANCE" -> "司机借支"
        "PAYMENT_SUPPLIER" -> "付供应商"
        "PAYMENT_TAX" -> "税费"
        "EXPENSE_FUEL" -> "油费"
        "EXPENSE_REPAIR" -> "维修"
        "EXPENSE_TOLL" -> "过路费"
        "EXPENSE_PARKING" -> "停车费"
        "EXPENSE_FINE" -> "罚款"
        "EXPENSE_INSURANCE" -> "保险"
        "EXPENSE_LOSS" -> "货损"
        "EXPENSE_OTHER" -> "其他开销"
        "REFUND_CUSTOMER" -> "退客户"
        "REFUND_DRIVER" -> "退司机"
        "ADJUST" -> "调账"
        // 认不出来就**原样显示**（含空）：编一个"其他"会把未知类型藏起来，
        // 而这个页面恰恰是用来发现"账上出现了我没见过的东西"的。
        else -> biz?.trim().orEmpty()
    }

    /**
     * 开销分类 → 中文。
     *
     * 真实取值见 `ExpenseCategory`：`fuel/repair/toll/parking/fine/insurance/loss/other`。
     * ⚠️ 旧的词表把货损写成了 `"damage"`——后端从来没有这个值，于是货损那一类
     * 在页面上显示成英文字面 `loss`。
     */
    fun expenseCategoryLabel(c: String?): String = when (c?.trim()?.lowercase()) {
        "fuel" -> "油费"
        "repair" -> "维修"
        "toll" -> "过路费"
        "parking" -> "停车费"
        "fine" -> "罚款"
        "insurance" -> "保险"
        "loss" -> "货损"
        "other" -> "其他"
        else -> c?.trim().orEmpty()
    }
}
