package com.tapmoay.sorders.ui.common

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 台账 L-32：下单时四个联系字段**不能全空**（名字或电话，任选其一就够）。
 *
 * 为什么值得单测：这条判据决定的是"这一单能不能下出去"，而它错在两边的代价完全不同 ——
 * 判宽了 = 又下出一批无主的单（账上认不出人，事后只能靠异常单去补）；
 * 判严了 = 用户明明填了收货人却点不动提交，且**看不出为什么**。
 */
class ContactRequirementTest {

    @Test
    fun `四个都空才拦（名字或电话任选其一就够）`() {
        assertTrue(contactInfoMissing("", "", "", ""))
        assertTrue(contactInfoMissing(null, null, null, null))
        // 只填任意一个都算合格 —— 四条各测一遍（少测一条，日后改坏一处也发现不了）
        assertFalse(contactInfoMissing("收货人甲", "", "", ""))
        assertFalse(contactInfoMissing("", "13800000001", "", ""))
        assertFalse(contactInfoMissing("", "", "下单人乙", ""))
        assertFalse(contactInfoMissing("", "", "", "13900000002"))
    }

    @Test
    fun `纯空格算空（与后端 strip 同一口径）`() {
        assertTrue(contactInfoMissing("   ", " ", "\t", "  "))
        assertFalse(contactInfoMissing("  收货人甲 ", "", "", ""))
    }

    @Test
    fun `提示文案与后端那条逐字一致`() {
        // 两边字不一样时用户会以为是两回事（后端拒单的话与页面上那句对不上）。
        // 后端那份在 backend/app/services/order_contact.py::CONTACT_INFO_REQUIRED。
        assertEquals("请填写收货人或下单人（名字或电话，至少一个）", CONTACT_REQUIRED_MESSAGE)
    }
}
