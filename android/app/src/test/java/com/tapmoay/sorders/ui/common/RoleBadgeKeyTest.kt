package com.tapmoay.sorders.ui.common

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 工作台右边那颗胶囊上的字：**货主 / 批发商按实际身份说**（CHG-0033）。
 *
 * ## 由来（用户 2026-10-04 第 2 件，对着工作台头部那张截图）
 * > 「他那个右边的那个**货主**啊，他是**根据实际情况**来定的：如果**对面是货主**的话，
 * >   他就**货主**，如果**对面是批发商**的话，则就是**批发商**」
 *
 * 批发商在库里 `role` 仍然是 `"shipper"`（`is_member=1`）—— 只看角色的话，
 * 那 14 个批发商的手机上那颗胶囊一直写着「货主」（他们的账本、核销能力与普通货主都不一样）。
 *
 * 这一组断言守四件事：**两种身份各自的字**、**只对货主生效**（派单员/司机标了也不算）、
 * **问不出来时按普通货主算**（fail-closed）、以及**批发商与货主同一族色**（他本来就是货主那一族）。
 */
class RoleBadgeKeyTest {

    @Test
    fun `货主不是批发商时胶囊上写「货主」（老行为一个字都不许变）`() {
        assertEquals("shipper", roleBadgeKey("shipper", memberShipper = false))
        assertEquals("货主", rolePaletteOf(roleBadgeKey("shipper", memberShipper = false)).label)
    }

    @Test
    fun `货主是批发商时胶囊上写「批发商」`() {
        assertEquals("shipper_member", roleBadgeKey("shipper", memberShipper = true))
        assertEquals("批发商", rolePaletteOf(roleBadgeKey("shipper", memberShipper = true)).label)
    }

    @Test
    fun `这一维只对货主生效——派单员与司机被标成批发商也不改标签`() {
        listOf("dispatcher" to "派单员", "driver" to "司机").forEach { (key, label) ->
            assertEquals(key, roleBadgeKey(key, memberShipper = true))
            assertEquals(label, rolePaletteOf(roleBadgeKey(key, memberShipper = true)).label)
        }
    }

    @Test
    fun `问不出来（false）时按普通货主算——fail-closed`() {
        listOf("shipper", "driver", "dispatcher").forEach { key ->
            assertEquals(key, roleBadgeKey(key, memberShipper = false))
        }
        // 兜底：不认识的键原样传出去（宁可显示一个怪名字，也不许冒充「批发商」）
        assertEquals("mystery", roleBadgeKey("mystery", memberShipper = true))
        assertEquals("mystery", rolePaletteOf(roleBadgeKey("mystery", memberShipper = true)).label)
    }

    @Test
    fun `批发商与货主是同一族色（变的只是标签上那个字）`() {
        val shipper = rolePaletteOf("shipper")
        val member = rolePaletteOf("shipper_member")
        assertEquals(shipper.light, member.light)
        assertEquals(shipper.dark, member.dark)
        assertTrue("两种身份的字必须是两个不同的词", shipper.label != member.label)
    }

    @Test
    fun `三个角色的标签不许走样（加了批发商那一支之后也得是这三句）`() {
        assertEquals("货主", rolePaletteOf("shipper").label)
        assertEquals("司机", rolePaletteOf("driver").label)
        assertEquals("派单员", rolePaletteOf("dispatcher").label)
    }
}
