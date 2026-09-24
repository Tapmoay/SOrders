package com.tapmoay.sorders.ui.common

import com.tapmoay.sorders.data.remote.api.UnitConversionDto
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/**
 * 单位换算**显示**判据（`Units.kt::convertedQty` / [qtyWithUnitConverted]）的单测 —— 纯 JVM。
 *
 * 为什么值得单测：用户要的是"我下的十车，会有 **2 个数据**：第一个是 10 车，第 2 个则是 80 方"。
 * 这个数会印在**订单卡片**上，而它的算法一旦走偏（浮点、方向反了、没换算也硬编一个数），
 * **谁都不会报错** —— 只是每一张卡上都写着一个错的数。
 *
 * 三条边界各有用例：
 * ① `10 车 ≈ 80 方` 这种正常情况；
 * ② **没有换算时逐字退回原样**（`10 车`，不是 `10 车 ≈ null`、也不是 `10 件`）；
 * ③ 换算率是脏数据（0 / 空 / 非数字）时**宁可不显示**，不显示成 `0 方`。
 */
class UnitConversionDisplayTest {

    private fun conv(from: String, to: String, factor: String) =
        UnitConversionDto(id = 1, fromUnit = from, toUnit = to, factor = factor)

    @Test
    fun `用户举的例子：十车等于八十方`() {
        val rows = listOf(conv("车", "方", "8"))
        assertEquals("80 方", convertedQty(10, "车", rows))
        assertEquals("10 车 ≈ 80 方", qtyWithUnitConverted(10, "车", rows))
    }

    @Test
    fun `换算率可以是小数（一斤等于半公斤）`() {
        val rows = listOf(conv("斤", "公斤", "0.5"))
        assertEquals("1.5 公斤", convertedQty(3, "斤", rows))
    }

    @Test
    fun `浮点会印出 79-99999999999999 这种数，这里不会`() {
        // 0.1 × 3 用 Double 得到 0.30000000000000004
        val rows = listOf(conv("斤", "公斤", "0.1"))
        assertEquals("0.3 公斤", convertedQty(3, "斤", rows))
    }

    @Test
    fun `换算率末尾多余的零要去掉（8-0000 显示成 8）`() {
        val rows = listOf(conv("车", "方", "8.0000"))
        assertEquals("80 方", convertedQty(10, "车", rows))
    }

    @Test
    fun `没有这个单位的换算时逐字退回原样`() {
        val rows = listOf(conv("车", "方", "8"))
        assertNull(convertedQty(3, "桶", rows))
        assertEquals("3 桶", qtyWithUnitConverted(3, "桶", rows))
        // 换算表为空（还没拉到 / 没设过）时也一样
        assertEquals("3 车", qtyWithUnitConverted(3, "车", emptyList()))
    }

    @Test
    fun `空单位不编单位也不换算`() {
        val rows = listOf(conv("车", "方", "8"))
        assertNull(convertedQty(3, "", rows))
        assertNull(convertedQty(3, null, rows))
        // 老单没填过单位 → 只给数字（与 qtyWithUnit 同一条规矩）
        assertEquals("3", qtyWithUnitConverted(3, null, rows))
    }

    @Test
    fun `换算率是脏数据时宁可不显示`() {
        for (bad in listOf("", "  ", "abc", "0", "-8")) {
            val rows = listOf(conv("车", "方", bad))
            assertNull("factor=$bad 不该算出数来", convertedQty(10, "车", rows))
            assertEquals("10 车", qtyWithUnitConverted(10, "车", rows))
        }
    }

    @Test
    fun `目标单位是空串时也不显示`() {
        val rows = listOf(conv("车", "", "8"))
        assertNull(convertedQty(10, "车", rows))
    }

    @Test
    fun `单位匹配忽略大小写与首尾空格`() {
        val rows = listOf(conv(" kg ", "斤", "2"))
        assertEquals("4 斤", convertedQty(2, "KG", rows))
        assertEquals("4 斤", convertedQty(2, " kg", rows))
    }

    @Test
    fun `同源单位有多条时取第一条（历史数据不崩）`() {
        // 判据（一个源单位只能一条）在后端；这里保证显示层遇到脏历史时不会崩、也不会显示成空
        val rows = listOf(conv("车", "方", "8"), conv("车", "袋", "50"))
        assertEquals("80 方", convertedQty(10, "车", rows))
    }

    @Test
    fun `用的是约等号不是等号`() {
        // 换算率是用户自己填的（"大概是八方"）—— 写成等号等于替用户担保那个数
        val rows = listOf(conv("车", "方", "8"))
        assertEquals(true, qtyWithUnitConverted(10, "车", rows).contains("≈"))
    }
}
