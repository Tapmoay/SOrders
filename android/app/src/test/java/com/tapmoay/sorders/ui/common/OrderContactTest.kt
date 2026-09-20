package com.tapmoay.sorders.ui.common

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
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

    // ---- 下单人 = 货主 时不重复说一遍（用户 2026-09-20）----

    @Test
    fun `下单人与货主同名时不画货主那一行`() {
        // 用户原话：「那个下单人和货主是一样的，不需要重新说一遍…你只要出现下单人就可以了」
        assertTrue(ordererIsShipper("永盛食品", "永盛食品"))
        // 空格与大小写不算两个人（同一个人被写成"永盛 食品"不该变成两行）
        assertTrue(ordererIsShipper("永盛 食品", "永盛食品"))
        assertTrue(ordererIsShipper("YongSheng", "yongsheng"))
    }

    @Test
    fun `真的是两个人时货主那一行还要画`() {
        assertFalse(ordererIsShipper("陈国强", "永盛食品"))
        // 派单员代下单：下单人是派单员，货主是别人 —— 这正是"两行都要有"的场景
        assertFalse(ordererIsShipper("陈国强", "李伟明"))
    }

    @Test
    fun `有一边是空的就不算同一个人`() {
        // ⚠️ 老单没记过下单人（这两列 2026-09-20 才加）→ **不能**因此把货主那行也抹掉，
        //    否则升级之后所有老单的卡片上都看不到"这单是谁的"。
        assertFalse(ordererIsShipper("", "永盛食品"))
        assertFalse(ordererIsShipper(null, "永盛食品"))
        assertFalse(ordererIsShipper("永盛食品", null))
        assertFalse(ordererIsShipper(null, null))
    }
}
