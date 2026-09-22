package com.tapmoay.sorders.ui.common

import com.tapmoay.sorders.ui.nav.Role
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 「拨打司机电话」给谁（`canDialDriver`）。
 *
 * 用户 2026-09-22 两轮口述：先是「**只会在派单端里**，其他人是没有的」，本轮放宽成
 * 「派单员……或者**批发商**也是可以拨打司机电话的……**只有这两个人**能看得到，
 * **司机是没有这个的**」。
 *
 * 单测钉的是**边界**：普通货主不能因为"他也是货主"就被顺带放开，司机更不能。
 */
class DriverCallTest {

    @Test
    fun `派单员能拨（这一行本来就是为他做的）`() {
        assertTrue(canDialDriver(Role.DISPATCHER, memberShipper = false))
        assertTrue(canDialDriver(Role.DISPATCHER, memberShipper = true))
    }

    @Test
    fun `批发商能拨（本轮新放开的那一档）`() {
        assertTrue(canDialDriver(Role.SHIPPER, memberShipper = true))
    }

    @Test
    fun `普通货主不给 —— 别顺手放宽成「所有货主」`() {
        assertFalse(canDialDriver(Role.SHIPPER, memberShipper = false))
    }

    @Test
    fun `司机不给 —— 他不需要打给自己`() {
        assertFalse(canDialDriver(Role.DRIVER, memberShipper = false))
        assertFalse(canDialDriver(Role.DRIVER, memberShipper = true))
    }

    @Test
    fun `三种角色 × 是否批发商 共 6 种组合逐条断言（防止判据被写成恒真或恒假）`() {
        val expected = mapOf(
            (Role.DISPATCHER to false) to true,
            (Role.DISPATCHER to true) to true,
            (Role.SHIPPER to true) to true,
            (Role.SHIPPER to false) to false,
            (Role.DRIVER to false) to false,
            (Role.DRIVER to true) to false,
        )
        Role.entries.forEach { r ->
            listOf(false, true).forEach { m ->
                assertTrue(
                    "组合 ($r, is_member=$m) 与口径不一致",
                    canDialDriver(r, m) == expected.getValue(r to m),
                )
            }
        }
    }
}
