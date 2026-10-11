package com.tapmoay.sorders.ui.common

import com.tapmoay.sorders.data.remote.dto.ContactDto
import com.tapmoay.sorders.data.remote.dto.UserDto
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 「我自己」那一行（`SelfContact.kt`，CHG-0117）的单测 —— 纯 JVM，不需要模拟器。
 *
 * 为什么值得单测（用户 2026-10-11 逐字：「**收货联系人**……这个联系人**可以选择派单员本人**啊」）：
 * 这一行是**凭空造出来的**联系人（后端根本没有这条记录），所以它只有两条硬规矩，而两条错了
 * 都不会报错、界面上也看不出来：
 * · **拿不到姓名或电话就不许出现** —— 否则用户会挑中一条空姓名/空电话的收货人，
 *   司机照着拨号才发现号码是空的（那是"填一个打不通的号比空着更糟"的翻版）；
 * · **它必须排在最前、且不去重** —— 排后面等于藏在名册尾巴里；去重会把用户自己存过的那条
 *   （可能叫别的名字）悄悄吞掉，让人以为名册里那条不见了。
 */
class SelfContactTest {

    private fun me(fullName: String = "王老板", phone: String = "13800000001") =
        UserDto(id = 7L, username = "wang", phone = phone, fullName = fullName, role = "dispatcher")

    private fun c(id: Long, name: String, phone: String) =
        ContactDto(id = id, phone = phone, displayName = name)

    // ---- 构造：两样都要有 ----

    @Test
    fun `姓名和电话都有 → 造出「我自己」那一行（负数哨兵 id）`() {
        val self = SelfContact.of("王老板", "13800000001")
        assertEquals(SelfContact.SELF_ID, self?.id)
        assertEquals(-1L, self?.id)
        assertEquals("王老板", self?.displayName)
        assertEquals("13800000001", self?.phone)
    }

    @Test
    fun `姓名拿不到 → 不显示这一项（null、空串、纯空白都算拿不到）`() {
        assertNull(SelfContact.of(null, "13800000001"))
        assertNull(SelfContact.of("", "13800000001"))
        assertNull(SelfContact.of("   ", "13800000001"))
    }

    @Test
    fun `电话拿不到 → 不显示这一项（某些测试号就是这样）`() {
        assertNull(SelfContact.of("王老板", null))
        assertNull(SelfContact.of("王老板", ""))
        assertNull(SelfContact.of("王老板", "   "))
    }

    @Test
    fun `两样都拿不到 → 不显示`() {
        assertNull(SelfContact.of(null, null))
        assertNull(SelfContact.of("", ""))
    }

    @Test
    fun `姓名与电话都去掉首尾空白（名字里带空格不该把号码也带进来）`() {
        val self = SelfContact.of("  王老板 ", " 13800000001 ")
        assertEquals("王老板", self?.displayName)
        assertEquals("13800000001", self?.phone)
    }

    @Test
    fun `从「我的资料」接口的返回造；fullName 是空的 → 不显示`() {
        val self = SelfContact.of(me())
        assertEquals(SelfContact.SELF_ID, self?.id)
        assertEquals("王老板", self?.displayName)
        assertEquals("13800000001", self?.phone)
        assertNull(SelfContact.of(me(fullName = "   ")))
        assertNull(SelfContact.of(me(phone = "")))
        assertNull(SelfContact.of(null as UserDto?))
    }

    // ---- 排位：固定最前、不去重 ----

    @Test
    fun `「我自己」固定排在最前，名册原有顺序一行不动`() {
        val a = c(1L, "甲", "13800000001")
        val b = c(2L, "乙", "13800000002")
        val self = SelfContact.of("王老板", "13800000003")!!
        val rows = SelfContact.withSelf(listOf(a, b), self)
        assertEquals(listOf(self, a, b), rows)
    }

    @Test
    fun `self 为 null（拿不到资料）→ 名册原样返回，一行都不多`() {
        val a = c(1L, "甲", "13800000001")
        val b = c(2L, "乙", "13800000002")
        val list = listOf(a, b)
        assertEquals(list, SelfContact.withSelf(list, null))
        assertSame(list, SelfContact.withSelf(list, null))
    }

    @Test
    fun `不去重：名册里也有同号那一条时，两行都留着`() {
        val mine = c(9L, "我自己（存过的那条）", "13800000003")
        val self = SelfContact.of("王老板", "13800000003")!!
        val rows = SelfContact.withSelf(listOf(mine), self)
        assertEquals(2, rows.size)
        assertEquals(SelfContact.SELF_ID, rows[0].id)
        assertEquals(9L, rows[1].id)
    }

    @Test
    fun `名册为空时也能只显示「我自己」`() {
        val self = SelfContact.of("王老板", "13800000001")!!
        assertEquals(listOf(self), SelfContact.withSelf(emptyList(), self))
    }

    // ---- 判别：那一枚负哨兵 ----

    @Test
    fun `isSelf 只认那一枚负哨兵`() {
        val self = SelfContact.of("王老板", "13800000001")!!
        assertTrue(SelfContact.isSelf(self))
        assertFalse(SelfContact.isSelf(c(1L, "甲", "13800000001")))
        // 0 与正数都不是"我自己"（真实主键恒为正；负数只可能是这里造的那一行）。
        assertFalse(SelfContact.isSelf(c(0L, "甲", "13800000001")))
        assertFalse(SelfContact.isSelf(c(99L, "甲", "13800000001")))
    }
}
