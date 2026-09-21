package com.tapmoay.sorders.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 422 的英文校验信息 → 人话（[ApiClient.humanizeValidation]）。
 *
 * ### 为什么这条值得钉住
 * 用户报过的原话是"报错是英文我看不懂"。而这类 422 **全都是用户自己就能改好的**
 * （选太多了、手机号格式、拆单份数），给一句英文等于让他卡在那里重试同一件事。
 */
class ApiClientValidationMessageTest {

    @Test
    fun `列表超上限 → 说清最多几项`() {
        val s = ApiClient.humanizeValidation("List should have at most 100 items")!!
        assertTrue(s, s.contains("100"))
        assertFalse(s, s.contains("List"))
    }

    @Test
    fun `后端自己写的中文原样透出`() {
        assertEquals("逐单核销需绑定订单", ApiClient.humanizeValidation("逐单核销需绑定订单"))
        assertEquals("该电话已存在已有联系人", ApiClient.humanizeValidation("该电话已存在已有联系人"))
    }

    @Test
    fun `手机号格式与拆单份数都有中文说法`() {
        assertFalse(ApiClient.humanizeValidation("String should match pattern '^1\\d{10}$'")!!.contains("pattern"))
        assertTrue(ApiClient.humanizeValidation("List should have at least 2 items")!!.contains("2"))
    }

    @Test
    fun `认不出来的英文也给一句中文，绝不留英文原文`() {
        val s = ApiClient.humanizeValidation("some brand new pydantic message")!!
        assertTrue(s, s.contains("不符合要求"))
        assertFalse(s, s.contains("pydantic"))
    }

    @Test
    fun `空消息也有兜底`() {
        assertEquals("提交的内容不符合要求，请检查后重试", ApiClient.humanizeValidation(null))
        assertEquals("提交的内容不符合要求，请检查后重试", ApiClient.humanizeValidation("   "))
    }

    // ---- HTTP 错误码 → 中文（[ApiClient.httpMessage]，2026-09-21 加）----

    /**
     * ⛔ 这一条是真事钉出来的：手机上派单员「退货申请」显示红字 **`Not Found`**，
     * 用户读成"连接失败/没找到"，而真相是"服务端还没发版"。英文原文绝不能上屏。
     */
    @Test
    fun `404 的英文 Not Found 要变中文且不能提网络`() {
        val s = ApiClient.httpMessage(404, "Not Found")
        assertFalse(s, s.contains("Not Found"))
        assertTrue(s, s.contains("404"))
        assertTrue("必须指向「服务端没发版」这个最可能的原因：$s", s.contains("服务端"))
    }

    /** 500 也**不能**说成"网络连接失败"——那是另一类问题（IOException 那条），排查方向完全不同。 */
    @Test
    fun `500 说服务器出错且明确不是网络问题`() {
        val s = ApiClient.httpMessage(500, null)
        assertTrue(s, s.contains("500"))
        assertTrue("要说清不是网络问题：$s", s.contains("不是网络"))
    }

    /** 后端自己写的中文（业务拒绝）永远原样透出 —— 那是用户唯一能照着改的话。 */
    @Test
    fun `后端的中文 detail 原样透出（含 404 与 500）`() {
        assertEquals("这张退货申请已经办完了，不能办理", ApiClient.httpMessage(400, "这张退货申请已经办完了，不能办理"))
        assertEquals("未找到对应记录", ApiClient.httpMessage(404, "未找到对应记录"))
        assertEquals("服务器开小差了", ApiClient.httpMessage(500, "服务器开小差了"))
    }

    /** 认不出来的英文 detail 也不裸奔，但仍然带上原码，便于对日志。 */
    @Test
    fun `认不出的英文 detail 裹上中文外壳并保留错误码`() {
        val s = ApiClient.httpMessage(418, "I am a teapot")
        assertTrue(s, s.contains("418"))
        assertFalse("英文原文不许单独上屏（这里只作为附注保留）", s.startsWith("I am"))
    }
}
