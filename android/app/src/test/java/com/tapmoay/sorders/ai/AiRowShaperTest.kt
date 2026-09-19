package com.tapmoay.sorders.ai

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * [AiRowShaper] 的纯逻辑测试——**这是"回答里不出现内部编号"的第一道闸**。
 *
 * 为什么单独给它一个测试文件：以前这套加工藏在 `AiTools` 的私有方法里，只有那 5 个工具走它。
 * 现在有了"读所有列表"的通用工具（36 个端点、字段五花八门），如果哪次有人图省事绕开它，
 * 编号就会从**某一张没测过的列表**里漏到用户面前——而功能测试发现不了
 * （要等用户截图里出现「user_id 122」才会暴露）。
 */
class AiRowShaperTest {

    private fun obj(json: String): JsonObject = Json.parseToJsonElement(json) as JsonObject

    @Test
    fun internalIdsAreStrippedAtEveryDepth() {
        val row = obj(
            """{"id":7,"order_no":"SO1","shipper_id":12,"nested":{"driver_id":33,"name":"王建国"},
                "items":[{"product_id":9,"qty":2}]}""",
        )
        val text = AiRowShaper.shape(row).toString()
        assertFalse("任何层级的 id/*_id 都不许留下：$text", text.contains("_id"))
        assertFalse(text.contains("\"id\""))
        // 该留的必须留
        assertTrue(text.contains("SO1"))
        assertTrue(text.contains("王建国"))
    }

    @Test
    fun costAndProfitFieldsAreStripped() {
        val row = obj(
            """{"name":"酱油","cost_price":"3.50","cost_total":"35.00","profit":"12","margin":0.3,
                "cost_covered_lines":5,"amount":"100.00","成本价":"3.5"}""",
        )
        val text = AiRowShaper.shape(row).toString()
        assertFalse(text, text.contains("cost"))
        assertFalse(text, text.contains("profit"))
        assertFalse(text, text.contains("margin"))
        assertFalse(text, text.contains("成本"))
        assertTrue("金额本身是业务数据，要留", text.contains("100.00"))
    }

    @Test
    fun hiddenFieldRuleIsExactlyWhatTheGuardrailExpects() {
        assertTrue(AiRowShaper.isHiddenField("id"))
        assertTrue(AiRowShaper.isHiddenField("shipper_id"))
        assertTrue(AiRowShaper.isHiddenField("cost_price"))
        assertTrue(AiRowShaper.isHiddenField("毛利"))
        // 反例：这些是正常业务字段，误杀会让回答缺数据
        assertFalse(AiRowShaper.isHiddenField("order_no"))
        assertFalse(AiRowShaper.isHiddenField("amount"))
        assertFalse(AiRowShaper.isHiddenField("ideal_stock"))
    }

    @Test
    fun namesThatAreActuallyIdsBecomeNeutralWords() {
        assertEquals("未命名", AiRowShaper.safeName("122"))
        assertEquals("未命名", AiRowShaper.safeName("货主#122"))
        assertEquals("未命名", AiRowShaper.safeName("司机 12"))
        assertEquals("未命名", AiRowShaper.safeName("   "))
        assertEquals("王建国", AiRowShaper.safeName("王建国"))
        // ⚠️ 11 位手机号是**有用信息**，不能被当成编号误杀（后端拿手机号兜底当名字是常态）
        assertEquals("13800000001", AiRowShaper.safeName("13800000001"))
        // 正常名字里带数字也不能误杀
        assertEquals("李四2号", AiRowShaper.safeName("李四2号"))
    }

    @Test
    fun namesAreNormalizedInsideRows() {
        val row = obj("""{"shipper_name":"货主#88","driver_name":"王建国","full_name":"122","amount":"10"}""")
        val shaped = AiRowShaper.shape(row)
        assertEquals("\"未命名\"", shaped["shipper_name"].toString())
        assertEquals("\"王建国\"", shaped["driver_name"].toString())
        assertEquals("\"未命名\"", shaped["full_name"].toString())
    }

    @Test
    fun nestedObjectsFlattenButNestedArraysBecomeCounts() {
        // 有意如此：把任意深度的数组摊开会让上下文爆炸（36 个端点的响应里数组一层套一层）。
        // 代价是"某单的商品行"看不到明细——这一点已在文档里写明。
        val row = obj("""{"order_no":"SO1","product":{"name":"酱油","qty":2},"lines":[{"a":1},{"a":2}]}""")
        val shaped = AiRowShaper.shape(row)
        assertEquals("\"酱油\"", shaped["name"].toString())
        assertEquals("2", shaped["lines_count"].toString())
        assertNull(shaped["lines"])
    }

    @Test
    fun rowsAreFoundInWhateverWrapperTheEndpointUses() {
        assertTrue(AiRowShaper.rowsOf(obj("""{"items":[{"a":1}]}""")).size == 1)
        assertTrue(AiRowShaper.rowsOf(obj("""{"data":[{"a":1}]}""")).size == 1)
        assertTrue(AiRowShaper.rowsOf(obj("""{"records":[{"a":1}]}""")).size == 1)
        assertTrue(AiRowShaper.rowsOf(Json.parseToJsonElement("""[{"a":1},{"b":2}]""")).size == 2)
        assertTrue(AiRowShaper.rowsOf(obj("""{"count":3}""")).isEmpty())
    }

    @Test
    fun scalarOnlyResponsesGetAScalarView() {
        // "待派单还有几单"这类聚合值不是列表，硬套行数组会得到空结果，看着像"没有数据"
        val v = AiRowShaper.scalarView(obj("""{"count":23,"pending":23}"""))
        assertTrue(v != null && v.isNotEmpty())
        assertNull("纯数组没有标量视图", AiRowShaper.scalarView(Json.parseToJsonElement("[1,2]")))
    }
}
