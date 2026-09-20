package com.tapmoay.sorders.core

/**
 * 「这一行**还能退几件**」——客户端唯一一份规则。
 *
 * 公式：`数量 − 货损 − 已退`（下限 0）。
 *
 * ## 为什么只有这一份
 * 它有三个消费点：派单员「订单管理」的退货弹窗（加减号的上限）、AI 确认卡（卡片上写"还能退 N"）、
 * 以及账本页的退货入口。三处各写一遍 `quantity - damage - returned` 的后果不是崩，
 * 而是**界面让填 3、后端只认 2**（后端 `services/order_return.py::max_returnable` 是判据）——
 * 用户填完点确认被拒，而他不知道该信哪个数。
 *
 * ## 两条口径（与后端逐字对应，改这里必须同时看后端）
 * · **货损那几件不能退**：那部分已经在送达时按成本计进损失账了，客户手里根本没有那几件；
 * · **已退的不能再退**：同一行分几次退是真实场景（先退 2 件、过两天再退 3 件），
 *   每一次的上限都要扣掉之前退过的。
 */
object ReturnRules {

    fun maxReturnable(quantity: Int, damageQuantity: Int, returnedQuantity: Int): Int =
        (quantity - damageQuantity - returnedQuantity).coerceAtLeast(0)
}
