package com.tapmoay.sorders.ui.dispatcher

import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * 车型那一格默认选谁（CHG-0028 / E2E 走查 P11）。
 *
 * 用户的原话是「新增车辆的车型默认是挂车，不注意就会建错车型」。
 * 这里钉的不是"默认值存在"，是**默认值与下拉第一项同源**：
 * 名册里最多的是小货车（本机 vehicles 表 small 11 / large 3 / trailer 1），
 * 所以它排第一，而不动这一格建出来的车也必须是小货车。
 *
 * ⛔ 取值集是三档计费口径（司机计费规则 / 运费模板按它匹配）—— 顺序可以改，档位不许加。
 */
class VehicleManageScreenTest {

    @Test
    fun `小货车排在下拉第一项（名册里最多的是它）`() {
        assertEquals("small", VEHICLE_TYPES.first().first)
        assertEquals("小货车", VEHICLE_TYPES.first().second)
    }

    @Test
    fun `默认车型与下拉第一项同源（换个顺序默认值也跟着换）`() {
        assertEquals(VEHICLE_TYPES.first().first, DEFAULT_VEHICLE_TYPE)
        assertEquals("small", DEFAULT_VEHICLE_TYPE)
    }

    @Test
    fun `取值集仍是计费口径那三档`() {
        assertEquals(listOf("small", "large", "trailer"), VEHICLE_TYPES.map { it.first })
        assertEquals(listOf("小货车", "大货车", "挂车"), VEHICLE_TYPES.map { it.second })
    }

    @Test
    fun `老数据里没填过车型的说「未设置车型」，不许猜一个`() {
        assertEquals("未设置车型", vehicleTypeLabel(""))
        assertEquals("未设置车型", vehicleTypeLabel(null))
        assertEquals("小货车", vehicleTypeLabel("small"))
        assertEquals("大货车", vehicleTypeLabel("large"))
        assertEquals("挂车", vehicleTypeLabel("trailer"))
    }
}
