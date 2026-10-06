package com.tapmoay.sorders.ai

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * [AiFieldLabels] 的测试（台账 L-24）。
 *
 * 用户原话（m00812）：「可以啊可以啊……其实**也不需要做的很复杂**，因为它只是**一个信息、
 * 重要信息的展示**而已，也就是**在应用到 AI 的时候才会有，它只展示信息**。」
 *
 * 所以这一份只钉三件事：
 * 1. 认得出来的键换成中文（模型照着念，用户看得懂）；
 * 2. **认不出来的一律原样透传**——猜错标签比露出英文糟得多（模型会照着错标签编业务含义）；
 * 3. 一个中文标签只能对应一个英文键：整体换标签走的是 `mapKeys`，撞了就会**吃掉一个字段**。
 */
class AiFieldLabelsTest {

    private fun obj(json: String): JsonObject = Json.parseToJsonElement(json) as JsonObject

    @Test
    fun 认得出来的键换成中文标签() {
        assertEquals("货主", AiFieldLabels.of("shipper_name"))
        assertEquals("订单号", AiFieldLabels.of("order_no"))
        assertEquals("货款", AiFieldLabels.of("goods_amount"))
        assertEquals("数量", AiFieldLabels.of("quantity"))
        assertEquals("状态", AiFieldLabels.of("status"))
    }

    @Test
    fun 认不出来就原样返回() {
        assertEquals("weird_key", AiFieldLabels.of("weird_key"))
        assertEquals("driver_billing_mode", AiFieldLabels.of("driver_billing_mode"))
        // 司机相关的键在整形那一步就被摘掉了（台账 L-30），这里只是不猜
        assertEquals("arrears_amount", AiFieldLabels.of("arrears_amount"))
    }

    @Test
    fun 一个中文标签只能对应一个英文键() {
        val dup = AiFieldLabels.LABELS.values.groupingBy { it }.eachCount().filterValues { it > 1 }
        assertTrue("同一个中文标签不能对应两个英文键（mapKeys 会吃掉一个字段）：" + dup, dup.isEmpty())
    }

    @Test
    fun 表别被误删成空表() {
        assertTrue("标签表至少 30 条，实际 " + AiFieldLabels.LABELS.size, AiFieldLabels.LABELS.size >= 30)
    }

    @Test
    fun 一行数据整体换标签且顺序不变() {
        val row = obj("""{"order_no":"SO1","shipper_name":"王建国","amount":"100.00"}""")
        val out = AiFieldLabels.apply(row)
        assertEquals(listOf("订单号", "货主", "金额"), out.keys.toList())
        assertEquals("\"SO1\"", out["订单号"].toString())
        assertEquals("\"王建国\"", out["货主"].toString())
    }

    @Test
    fun 整形出来的行就是中文键() {
        val row = obj("""{"order_no":"SO1","goods_amount":"293.20","driver_name":"王建国"}""")
        val shaped = AiRowShaper.shape(row)
        assertEquals("\"SO1\"", shaped["订单号"].toString())
        assertEquals("\"293.20\"", shaped["货款"].toString())
        assertTrue("司机字段仍然不给模型：" + shaped, !shaped.containsKey("司机"))
    }
}
