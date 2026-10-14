package com.tapmoay.sorders.ui.driver

import com.tapmoay.sorders.data.remote.dto.DriverBillDto
import com.tapmoay.sorders.util.moneyToDouble

/**
 * 固定工资司机的「工资」那一半账（2026-10-15，CHG-0127）。
 *
 * 用户口径（m43131）：「我们的大车司机也就是固定工资的司机不是没有我的账本吗，我们加一个
 * 我的账本啊，这个我的账本就是**统计他的工资**的……如果在任职期间他的固定工资发生了改变，
 * 我们也同样也是有记录的，也会有个统计；当然如果**已经核销了**……表示已核销，就是重新计算
 * 那个**没有核销**的工资」。
 *
 * ⛔ 这里**只算数、不画钱**：`ui/driver/` 下允许出现金额渲染的文件只有 `DriverFreightScreen.kt`
 *    一个（判据 `_tools/qa/_check_driver_money.py` 第 8 节按目录自己算），所以本文件里一个字都
 *    不许出现金额格式化 —— 金额只以 `Double` 的形式出去，由界面统一渲染。
 * ⚠️ 两个 `data class` 故意**不加 `internal`**：`DriverFreightViewModel` 的属性是公开的，
 *    公开属性暴露 internal 类型编译不过（Kotlin: 'public' property exposes its 'internal' type
 *    argument）。先例：`ui/messages/MessageGrading.kt` 那两个跨页类型也是公开的。
 * ⛔ 取数口径**不在这里**：本层只把后端发下来的工资单（`GET /driver-bills`，司机自读由后端强制
 *    成"只有他自己的"）分账、求和、比月份。金额一律来自 `services/driver_pay.py`，界面不许自己
 *    按规则/车型猜（猜了必然和账单对不上）。
 */

/** 这张单是不是**月薪单**（`bill_type = salary`）；大小写都认（后端枚举值是小写 `salary`）。 */
internal fun isSalaryBill(b: DriverBillDto): Boolean = b.billType.equals("salary", ignoreCase = true)

/**
 * 这笔工资**核销了没有**。
 *
 * 已核销 = 那张结算单已经把它锁住（`settled_doc_id`），或状态已经变成 `settled`。
 * 两个判据**取或**：只认状态会漏掉"已被草稿结算单点名"的单（后端 `driver_bills._is_open_unlocked`
 * 是同口径的另一半）；只认 `settled_doc_id` 会漏掉老数据里状态已改、单据又被删掉的单。
 */
internal fun isSettledBill(b: DriverBillDto): Boolean =
    b.status.equals("settled", ignoreCase = true) || b.settledDocId != null

/** 只留月薪单，**按月份倒序**（新的在最上面）—— 界面上"这个月、上个月"就是这么念的。 */
internal fun salaryBillsOf(bills: List<DriverBillDto>): List<DriverBillDto> =
    bills.filter { isSalaryBill(it) }.sortedByDescending { it.month }

/**
 * 已核销 / 未核销两本小账（用户：「表示已核销……那个没有核销的工资」）。
 *
 * ⚠️ 两个数**分开给**，不给"合计"了事：已核销的是**已经拍过板的凭据**（不再变），
 *    未核销的会随固定工资改变被重算（[com.tapmoay.sorders.data.remote.dto.DriverBillGenerateRequest.refreshUnsettled]）
 *    —— 混成一个数，"这个月到底结了多少"就答不上来了。
 */
data class SalaryTotals(
    val settledCount: Int,
    val settled: Double,
    val openCount: Int,
    val open: Double,
) {
    val count: Int get() = settledCount + openCount
    val all: Double get() = settled + open
}

internal fun salaryTotalsOf(bills: List<DriverBillDto>): SalaryTotals {
    val rows = salaryBillsOf(bills)
    val settled = rows.filter { isSettledBill(it) }
    val open = rows.filter { !isSettledBill(it) }
    return SalaryTotals(
        settledCount = settled.size,
        settled = settled.sumOf { moneyToDouble(it.amount) },
        openCount = open.size,
        open = open.sumOf { moneyToDouble(it.amount) },
    )
}

/**
 * 一次**工资变更**。
 *
 * 判据：相邻两张月薪单的金额不一样 —— 工资单是按"当月的固定工资"生成的，所以账单本身
 * 就是他任职期间那张工资表的时间线（改规则**不会**改历史账单，快照在生成那一刻就定死了）。
 * `month` = 变更后那张单的月份（"从哪个月起是这个数"）。
 */
data class SalaryChange(val month: String, val from: Double, val to: Double, val ruleName: String)

internal fun salaryChangesOf(bills: List<DriverBillDto>): List<SalaryChange> {
    val rows = salaryBillsOf(bills).sortedBy { it.month } // 旧 → 新
    val out = mutableListOf<SalaryChange>()
    for (i in 1 until rows.size) {
        val prev = moneyToDouble(rows[i - 1].amount)
        val cur = moneyToDouble(rows[i].amount)
        if (prev != cur) out += SalaryChange(rows[i].month, prev, cur, rows[i].ruleName)
    }
    return out.asReversed() // 新的在前
}

/**
 * 「2026-10」→「2026 年 10 月」。
 *
 * 长度/形状不对就**原样回**：老后端或脏数据不该把这一行变成空白（宁可丑，不可无）。
 */
internal fun salaryMonthWord(month: String): String {
    val m = month.trim()
    if (m.length < 7) return m
    val y = m.substring(0, 4)
    val mm = m.substring(5, 7).trimStart('0')
    val ok = y.all { it.isDigit() } && mm.isNotEmpty() && mm.all { it.isDigit() }
    return if (ok) y + " 年 " + mm + " 月" else m
}
