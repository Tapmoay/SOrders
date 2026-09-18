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
}
