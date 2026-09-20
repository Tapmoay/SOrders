package com.tapmoay.sorders.core

import com.tapmoay.sorders.data.remote.dto.ExpenseDto
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/**
 * 开销卡片"突出哪一项"的规则（[ExpenseLink]）。
 *
 * 用户 2026-09-20 的原话：「这个关联跟**对应的分类**是有关系的 —— 燃油/维修这些主要是车辆，
 * 首要突出的是车辆；如果是其他的成本，可能关联的就是其他的……**要具体问题具体判断，不能一刀切**」。
 * 所以这里钉死两件事：**按分类走**、以及**分类说的那一项没填时的兜底顺序**。
 */
class ExpenseLinkTest {

    private fun e(
        category: String = "加油",
        linkKind: String = ExpenseLink.VEHICLE,
        vehicle: String? = null,
        driver: String? = null,
        orderNo: String? = null,
    ) = ExpenseDto(
        id = 1,
        category = category,
        amount = "100.00",
        driverName = driver,
        vehicleName = vehicle,
        orderNo = orderNo,
        linkKind = linkKind,
    )

    @Test
    fun `燃油类突出车牌`() {
        val p = ExpenseLink.primary(e(vehicle = "粤L12345", driver = "王建国"))
        assertEquals(ExpenseLink.VEHICLE, p?.kind)
        assertEquals("粤L12345", p?.text)
        // 突出的是车辆，司机降到次要那一行（不是消失）
        assertEquals(
            listOf(ExpenseLink.DRIVER),
            ExpenseLink.secondary(e(vehicle = "粤L12345", driver = "王建国")).map { it.kind },
        )
    }

    @Test
    fun `分类说车辆但没填车_退到司机再退到订单`() {
        assertEquals(ExpenseLink.DRIVER, ExpenseLink.primary(e(vehicle = null, driver = "王建国"))?.kind)
        assertEquals(ExpenseLink.ORDER, ExpenseLink.primary(e(vehicle = null, driver = null, orderNo = "SO1"))?.kind)
    }

    @Test
    fun `货损类突出订单_没单时退到车`() {
        val withOrder = e(category = "货损", linkKind = ExpenseLink.ORDER, orderNo = "SO2026", vehicle = "粤L1")
        assertEquals(ExpenseLink.ORDER, ExpenseLink.primary(withOrder)?.kind)
        val noOrder = e(category = "货损", linkKind = ExpenseLink.ORDER, orderNo = null, vehicle = "粤L1")
        assertEquals(ExpenseLink.VEHICLE, ExpenseLink.primary(noOrder)?.kind)
    }

    @Test
    fun `不关联的分类不突出任何东西`() {
        assertNull(ExpenseLink.primary(e(category = "其他", linkKind = ExpenseLink.NONE, vehicle = "粤L1", driver = "张三")))
        // 认不出的 link_kind（后端加了新值而客户端还没跟上）也当"不关联"，不许乱挑一个
        assertNull(ExpenseLink.primary(e(linkKind = "something-new", vehicle = "粤L1")))
    }

    @Test
    fun `三项都没填就不显示那一行`() {
        assertNull(ExpenseLink.primary(e(vehicle = null, driver = null, orderNo = null)))
        assertEquals(emptyList<String>(), ExpenseLink.secondary(e()).map { it.kind })
    }

    @Test
    fun `中文名表是唯一一份`() {
        assertEquals("车辆", ExpenseLink.label(ExpenseLink.VEHICLE))
        assertEquals("不关联", ExpenseLink.label(ExpenseLink.NONE))
        assertEquals("不关联", ExpenseLink.label("认不出的值"))
        assertEquals(4, ExpenseLink.CHOICES.size)
    }
}
