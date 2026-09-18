package com.tapmoay.sorders.ui.dispatcher

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
     * 这个页签导出时要不要用**日期区间**（而不是 mode+anchor）。
     *
     * 与页面上的取数口径一致：
     * - 营业纵览 / 商品经营：按 `mode`（日/周/月）+ `anchor` 看窗口，页面上就是那个时间段；
     * - 司机绩效 / 客户经营 / 资金收支：页面上用的是 dateRange（那个时间段）；
     * - 异常与审计：页面上**固定近 30 天**（没有时间导航），导出也必须是同一段，
     *   否则"我看到的"和"我导出的"是两个区间。
     */
    fun usesDateRange(tab: Int): Boolean = tab in 2..5

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
