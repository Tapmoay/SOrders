package com.tapmoay.sorders.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 订单状态模型的单测（2026-09-19 审计 H1）。
 *
 * ### 为什么这个纯数据对象也要测
 * 它承载的是"**这一档能不能做那件事**"，而错了不会报错、只会少一个按钮或多一个必然失败的按钮：
 * - App 派单员撤回按钮原来只认 `ACCEPTED` → **派错司机的第一时间撤不回来**；
 * - 司机的"进行中"只查 `ACCEPTED` → 新派来的单**在司机端根本不出现**。
 *
 * 静态红线 `_tools/qa/_check_client_contract.py` 负责"与后端逐值对账"（那需要跑脚本），
 * 这里负责"**模型自身的自洽**"：能离线、毫秒级地拦住"有人手滑改掉一档"。
 */
class OrderStatusModelTest {

    @Test
    fun `六个状态一个不少（少一档就等于那一档订单在客户端查无此单）`() {
        // 2026-09-20 加了 RETURNED（已退货）：**与 CANCELLED 不是一回事** ——
        // 撤销＝这单没发生过；退货＝送了、入了账、事后货退回来了。
        assertEquals(6, OrderStatusModel.ALL.size)
        assertEquals(
            listOf("PENDING_DISPATCH", "DISPATCHED", "ACCEPTED", "DELIVERED", "CANCELLED", "RETURNED"),
            OrderStatusModel.ALL,
        )
    }

    @Test
    fun `可退货只有已送达一档（与后端 order_return 的状态门一致）`() {
        assertEquals(setOf("DELIVERED"), OrderStatusModel.RETURNABLE)
    }

    @Test
    fun `每个集合里的取值都在全集里（写错一个字母就是个永不成立的门）`() {
        val sets = mapOf(
            "CANCELLABLE" to OrderStatusModel.CANCELLABLE,
            "RECALLABLE" to OrderStatusModel.RECALLABLE,
            "ASSIGNABLE" to OrderStatusModel.ASSIGNABLE,
            "LINE_EDITABLE" to OrderStatusModel.LINE_EDITABLE,
            "ACKABLE" to OrderStatusModel.ACKABLE,
            "COMPLETABLE" to OrderStatusModel.COMPLETABLE,
            "EDITABLE" to OrderStatusModel.EDITABLE,
            "FREIGHT_EDITABLE" to OrderStatusModel.FREIGHT_EDITABLE,
            "NOT_CANCELLED" to OrderStatusModel.NOT_CANCELLED,
            "RETURNABLE" to OrderStatusModel.RETURNABLE,
            "DRIVER_OPEN" to OrderStatusModel.DRIVER_OPEN.toSet(),
        )
        for ((name, values) in sets) {
            assertTrue("$name 是空的", values.isNotEmpty())
            assertEquals("$name 里有全集之外的取值", emptySet<String>(), values - OrderStatusModel.ALL.toSet())
        }
    }

    @Test
    fun `司机端进行中必须覆盖接单与送达两帧`() {
        val open = OrderStatusModel.DRIVER_OPEN.toSet()
        assertTrue("缺接单档，司机看不到新单", open.containsAll(OrderStatusModel.ACKABLE))
        assertTrue("缺送达档，司机接了单就找不到这一单", open.containsAll(OrderStatusModel.COMPLETABLE))
    }

    @Test
    fun `已送达与已撤销不再可操作（撤单、改单、撤回、改运费都关上）`() {
        val terminal = setOf("DELIVERED", "CANCELLED")
        for (name in listOf(
            "CANCELLABLE", "RECALLABLE", "ASSIGNABLE", "LINE_EDITABLE", "EDITABLE", "FREIGHT_EDITABLE",
        )) {
            val values = when (name) {
                "CANCELLABLE" -> OrderStatusModel.CANCELLABLE
                "RECALLABLE" -> OrderStatusModel.RECALLABLE
                "ASSIGNABLE" -> OrderStatusModel.ASSIGNABLE
                "LINE_EDITABLE" -> OrderStatusModel.LINE_EDITABLE
                "EDITABLE" -> OrderStatusModel.EDITABLE
                else -> OrderStatusModel.FREIGHT_EDITABLE
            }
            assertEquals("$name 不该含终态", emptySet<String>(), values intersect terminal)
        }
    }

    @Test
    fun `接单与送达是两档不同的状态（同一次点击不可能既是又非）`() {
        assertEquals(setOf("DISPATCHED"), OrderStatusModel.ACKABLE)
        assertEquals(setOf("ACCEPTED"), OrderStatusModel.COMPLETABLE)
        assertEquals(emptySet<String>(), OrderStatusModel.ACKABLE intersect OrderStatusModel.COMPLETABLE)
    }
}
