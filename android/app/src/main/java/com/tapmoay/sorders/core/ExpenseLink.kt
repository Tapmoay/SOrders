package com.tapmoay.sorders.core

import com.tapmoay.sorders.data.remote.dto.ExpenseDto

/**
 * 开销卡片上「**突出哪一项**」的规则 —— 纯函数，有单测。
 *
 * ## 为什么要有这一份（用户 2026-09-20）
 *
 * 原话：「这个关联啊，其实跟对应的分类是有关系的 —— 比如说燃油或者说维修这些主要是车辆，
 * 所以关联的是车辆，**首要突出的是车辆**；如果是其他的成本的话，可能关联的就是其他的……
 * 要**具体问题具体判断，不能一刀切**」。
 *
 * 所以"突出什么"**不是代码里写死的**，而是每个分类自己带的一列（`expense_categories.link_kind`，
 * 在「开销分类管理」里能改）。这里只负责把那一列翻成"卡片上突出显示哪一项"：
 *
 * | link_kind | 突出 | 兜底顺序 |
 * |---|---|---|
 * | `vehicle` | 车辆 | 车辆 → 司机 → 订单 |
 * | `driver` | 司机 | 司机 → 车辆 → 订单 |
 * | `order` | 订单 | 订单 → 车辆 → 司机 |
 * | `none` / 认不出 | 不突出（只显示分类 + 金额 + 日期） | —— |
 *
 * ⚠️ **兜底一定要有**：分类说"突出车辆"、可这一笔忘了填车，卡片上就空着的话，
 *    用户会以为记漏了 —— 退到"实际填了的那一项"才诚实。
 * ⚠️ **三项都没填就不显示这一行**（不临时挑一个：那是替用户编事实）。
 */
object ExpenseLink {

    const val VEHICLE = "vehicle"
    const val DRIVER = "driver"
    const val ORDER = "order"
    const val NONE = "none"

    /** 「开销分类管理」里那个下拉的选项（顺序 = 界面顺序）。 */
    val CHOICES: List<Pair<String, String>> = listOf(
        VEHICLE to "车辆",
        DRIVER to "司机",
        ORDER to "订单",
        NONE to "不关联",
    )

    /** 一个关联项：`kind` 用于去重（同一项不要在卡片上出现两次），`label` 是"车辆/司机/订单"。 */
    data class Linked(val kind: String, val label: String, val text: String)

    /** 分类管理页与详情里显示的中文名。 */
    fun label(kind: String): String = CHOICES.firstOrNull { it.first == kind }?.second ?: "不关联"

    /** 这一笔实际填了哪几项关联（按"车辆 → 司机 → 订单"的固定顺序）。 */
    private fun present(e: ExpenseDto): List<Linked> = listOfNotNull(
        e.vehicleName?.takeIf { it.isNotBlank() }?.let { Linked(VEHICLE, "车辆", it) },
        e.driverName?.takeIf { it.isNotBlank() }?.let { Linked(DRIVER, "司机", it) },
        e.orderNo?.takeIf { it.isNotBlank() }?.let { Linked(ORDER, "订单", it) },
    )

    /**
     * 卡片上**突出**的那一项（分类说的那一项优先，没填就按兜底顺序退）。
     * 三项都没填 / 分类是「不关联」→ null。
     */
    fun primary(e: ExpenseDto): Linked? {
        val items = present(e)
        val order = when (e.linkKind) {
            VEHICLE -> listOf(VEHICLE, DRIVER, ORDER)
            DRIVER -> listOf(DRIVER, VEHICLE, ORDER)
            ORDER -> listOf(ORDER, VEHICLE, DRIVER)
            else -> return null
        }
        for (kind in order) {
            items.firstOrNull { it.kind == kind }?.let { return it }
        }
        return null
    }

    /**
     * 卡片的**次要**那一行：突出项之外**还填了**的关联（弱化显示）。
     *
     * 为什么留着：突出的是"这一类开销最该看的那一项"，但"这一笔还挂了谁/哪一单"同样是事实 ——
     * 全藏起来的话用户只能点进详情才看得到（而那是他自己录的）。
     */
    fun secondary(e: ExpenseDto): List<Linked> {
        val top = primary(e)?.kind
        return present(e).filter { it.kind != top }
    }
}
