package com.tapmoay.sorders.ui.common

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 单位换算**预取角色门**（`UnitConv.canRead` / `READ_ROLE_KEYS`）的单测 —— 纯 JVM。
 *
 * 为什么值得单测：这张表只有货主与派单员能读（后端 `require_roles(SHIPPER, DISPATCHER)`），
 * 而 App 原来**不看角色**，会话一建立就无条件拉一次 —— 司机每次登录/恢复都在后端留下一条 403。
 * 失败还是静默的（`refresh` 吞掉异常、界面照旧只显示原单位），所以这件事**在页面上永远看不出来**，
 * 只有后端日志一直在响（走查报告 §5.3）。
 *
 * ⛔ `wholesaler` 那一格是**故意**列出来的：`Role.fromKey` 把不认识的 key 折成 SHIPPER，
 *    若拿折过的枚举去判，后端确实存在的批发商账号会照发不误（后端照样 403）。
 */
class UnitConvAccessTest {

    @Test
    fun `能读的只有货主与派单员`() {
        assertTrue(UnitConv.canRead("shipper"))
        assertTrue(UnitConv.canRead("dispatcher"))
    }

    @Test
    fun `司机与批发商都不该发那次请求`() {
        assertFalse(UnitConv.canRead("driver"))
        assertFalse(UnitConv.canRead("wholesaler"))
        assertFalse(UnitConv.canRead(null))
        assertFalse(UnitConv.canRead(""))
    }

    @Test
    fun `角色清单就是后端那一份`() {
        assertEquals(setOf("shipper", "dispatcher"), UnitConv.READ_ROLE_KEYS)
    }
}
