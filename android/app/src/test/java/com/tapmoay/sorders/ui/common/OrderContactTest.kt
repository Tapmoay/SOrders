package com.tapmoay.sorders.ui.common

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/**
 * 「收货人 / 下单人」这一行怎么显示（`contactWho`）。
 *
 * 为什么值得单测：卡片与**详情页**共用这一个函数，它决定的是一条**信息该不该出现**——
 * 名字或电话少一个时显示哪一个、两个都没有时**不画那一行**（而不是画一条「收货人：-」）。
 * 错在这里的表现是"界面上少了一行，而没有任何报错"。
 */
class OrderContactTest {

    @Test
    fun `名字与电话都有时带上括号`() {
        assertEquals("张三（13800000002）", contactWho("张三", "13800000002"))
    }

    @Test
    fun `只有名字就只显示名字`() {
        assertEquals("张三", contactWho("张三", ""))
        assertEquals("张三", contactWho("张三", null))
    }

    @Test
    fun `只有电话就只显示电话`() {
        // 老单没记过名字（这两列是 2026-09-20 才加的），但电话一直是有的 ——
        // 那种单在卡片上应当只显示电话，而不是整行消失。
        assertEquals("13800000002", contactWho("", "13800000002"))
        assertEquals("13800000002", contactWho(null, "13800000002"))
    }

    @Test
    fun `两边都没有就不画这一行`() {
        assertNull(contactWho("", ""))
        assertNull(contactWho(null, null))
        assertNull(contactWho("   ", "  "))
    }

    @Test
    fun `两侧的空白要去掉`() {
        assertEquals("张三（13800000002）", contactWho("  张三 ", " 13800000002 "))
    }
}
