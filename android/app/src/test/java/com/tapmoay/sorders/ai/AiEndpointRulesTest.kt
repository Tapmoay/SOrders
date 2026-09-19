package com.tapmoay.sorders.ai

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * AI 接口地址（Base URL）的校验 —— 2026-09-19 全项目报告 C-1/P1-6。
 *
 * 这几条判据护的是**钱与凭据**：用户在这里填的是"把 API Key 发到哪里"，
 * 明文 http 会让同网段的人读走 Key、甚至把请求改发到别的主机。
 */
class AiEndpointRulesTest {

    @Test
    fun `发布包必须 https`() {
        assertNull(AiEndpointRules.error("https://api.deepseek.com/v1", debug = false))
        assertNotNull(AiEndpointRules.error("http://api.deepseek.com/v1", debug = false))
        assertNotNull(AiEndpointRules.error("http://192.168.1.9:11434/v1", debug = false))
    }

    @Test
    fun `拒绝明文时的提示要能照着做`() {
        val msg = AiEndpointRules.error("http://x.com/v1", debug = false)!!
        assertTrue("要说清为什么：$msg", msg.contains("API Key"))
        assertTrue("要给出办法：$msg", msg.contains("debug"))
    }

    @Test
    fun `debug 包允许明文（本地联调与局域网自建服务）`() {
        assertNull(AiEndpointRules.error("http://10.0.2.2:8000/v1", debug = true))
        assertNull(AiEndpointRules.error("http://192.168.1.9:11434/v1", debug = true))
    }

    @Test
    fun `空与非法协议都要给中文`() {
        assertEquals("请填写 Base URL", AiEndpointRules.error("   ", debug = false))
        val bad = AiEndpointRules.error("api.deepseek.com", debug = false)
        assertNotNull("没写协议名也要拒绝（否则 Retrofit 会抛英文异常）", bad)
        assertTrue(bad!!.contains("https://"))
    }
}
