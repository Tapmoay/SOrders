package com.tapmoay.sorders.ui.common

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 「收货人两栏怎么被带出来」判据（`ContactFill.kt::fillReceiver`）的单测 —— 纯 JVM，不需要模拟器。
 *
 * 为什么值得单测：这两栏是**司机照着拨号**的那两个字段，而四条来源（手打 / 选联系人 / 选线路 /
 * 选地点）里任何一条把覆盖规矩写错，**都不会报错** —— 表现只是"名字还在、电话换成上一个人的"
 * 或者"刚填好的名字被一次选点清掉"，界面上完全看不出来。
 *
 * 两条规矩**故意不同**（见 `ContactFill.kt` 文件头）：
 * · BROUGHT（选地点/线路顺带带出）= 有值才覆盖、空值不清空；
 * · PICKED（明确挑了一个人）= 整对替换，含清空。
 */
class ContactFillTest {

    // ---- BROUGHT：带出 ----

    @Test
    fun `带出时两边都有值就都覆盖`() {
        val r = fillReceiver(ReceiverContact("旧名字", "13800000000"), "王老板", "13800001111", ContactFillMode.BROUGHT)
        assertEquals(ReceiverContact("王老板", "13800001111"), r)
    }

    @Test
    fun `带出时来源空着的那一栏不许清掉用户填的`() {
        // 这个地点只绑了名字、没绑电话 → 电话保持用户已经填的那个
        val r = fillReceiver(ReceiverContact("手打的名字", "13800000000"), "王老板", "", ContactFillMode.BROUGHT)
        assertEquals(ReceiverContact("王老板", "13800000000"), r)
    }

    @Test
    fun `带出时来源什么都没给就原样不动`() {
        val cur = ReceiverContact("手打的名字", "13800000000")
        assertEquals(cur, fillReceiver(cur, "", "", ContactFillMode.BROUGHT))
        assertEquals(cur, fillReceiver(cur, null, null, ContactFillMode.BROUGHT))
        assertEquals(cur, fillReceiver(cur, "   ", "  ", ContactFillMode.BROUGHT))
    }

    @Test
    fun `带出时来源带首尾空格要修掉`() {
        val r = fillReceiver(ReceiverContact(), " 王老板 ", " 13800001111 ", ContactFillMode.BROUGHT)
        assertEquals(ReceiverContact("王老板", "13800001111"), r)
    }

    // ---- PICKED：挑了一个人 ----

    @Test
    fun `挑人时整对替换（含把旧值清空）`() {
        // 名册里那个人只存了号码、没写名字（display_name 缺省是空串）——
        // 这时名字必须是空，**不许**留着上一位的名字：那会拼出一个不存在的人，
        // 而司机照着这个名字找到的是另一个人。
        val r = fillReceiver(ReceiverContact("上一位的名字", "13800000000"), "", "13900002222", ContactFillMode.PICKED)
        assertEquals(ReceiverContact("", "13900002222"), r)
    }

    @Test
    fun `挑人时清空也是允许的结果（那个人姓名电话都空）`() {
        val r = fillReceiver(ReceiverContact("上一位", "13800000000"), "", "", ContactFillMode.PICKED)
        assertTrue(r.isBlank)
    }

    @Test
    fun `挑人时不看当前值（与带出是两条路）`() {
        val a = fillReceiver(ReceiverContact("甲", "1"), "王老板", "138", ContactFillMode.PICKED)
        val b = fillReceiver(ReceiverContact("乙", "2"), "王老板", "138", ContactFillMode.PICKED)
        assertEquals(a, b)
    }

    // ---- 显示与判空 ----

    @Test
    fun `有没有绑人：空串与纯空格都算没绑`() {
        assertFalse(hasBoundContact("", ""))
        assertFalse(hasBoundContact("   ", null))
        assertFalse(hasBoundContact(null, null))
        assertTrue(hasBoundContact("王老板", ""))
        assertTrue(hasBoundContact("", "13800001111"))
    }

    @Test
    fun `一行摘要：有名字写名字、两个都有就连起来、只有电话就写电话`() {
        assertEquals("王老板 · 13800001111", boundContactLabel("王老板", "13800001111"))
        assertEquals("王老板", boundContactLabel("王老板", ""))
        assertEquals("王老板", boundContactLabel(" 王老板 ", null))
        assertEquals("13800001111", boundContactLabel("", "13800001111"))
        assertEquals("", boundContactLabel("", ""))
    }

    @Test
    fun `两栏都空才算这一单没有收货人`() {
        assertTrue(ReceiverContact("", "").isBlank)
        assertFalse(ReceiverContact("王老板", "").isBlank)
        assertFalse(ReceiverContact("", "138").isBlank)
    }
}
