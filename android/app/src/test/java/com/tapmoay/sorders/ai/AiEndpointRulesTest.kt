package com.tapmoay.sorders.ai

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
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

    /**
     * AI 工具的**默认开关按角色**（2026-09-20 用户：「派单员所有 AI 功能全都是默认开启」）。
     *
     * 这条以前埋在 `AiKeyStore.enabledTools()` 里（要 Context + SharedPreferences，只有真机能验），
     * 抽成纯函数之后这里能把它钉住：派单员一个不漏；其余角色**不含**写工具。
     */
    @Test
    fun `派单员默认全开、其余角色不含写工具`() {
        val all = AiKeyStore.DEFAULT_ENABLED_TOOLS
        assertEquals("派单员应当全部默认开", all, AiKeyStore.defaultEnabledTools(AiRole.DISPATCHER))
        for (role in listOf(AiRole.SHIPPER, null)) {
            val d = AiKeyStore.defaultEnabledTools(role)
            assertTrue("非派单员不该默认开写工具：$role", AiTools.PREVIEW_WRITE !in d)
            assertEquals("除写工具外应当都一样", all - AiKeyStore.OPT_IN_TOOLS, d)
        }
    }

    @Test
    fun `新增工具：派单员不排除、其余角色排除写工具`() {
        assertEquals(
            "派单员对新增工具不该有任何排除",
            emptySet<String>(),
            AiKeyStore.optInExclusion(AiRole.DISPATCHER),
        )
        assertEquals(
            "非派单员要把写工具排除在「新增默认开」之外",
            AiKeyStore.OPT_IN_TOOLS,
            AiKeyStore.optInExclusion(AiRole.SHIPPER),
        )
    }

    /**
     * 「允许 AI 查看成本与毛利」的默认值**按角色**（用户 2026-09-20：
     * 「对那个默认也要开起来」，接着上一句「派单员所有 AI 功能全都是默认开启」）。
     *
     * 这条是**数据外发**开关，所以另外三个方向的判据在别处（`AiWriteTest` 的
     * 「成本开关…」用例：关着必拒、打开才落库）——这里只钉"没设置过时是谁开着的"。
     */
    @Test
    fun `成本开关默认值按角色：派单员开、其余角色关`() {
        assertTrue("派单员默认应当开着", AiKeyStore.defaultCostVisible(AiRole.DISPATCHER))
        assertFalse("货主不该默认把成本价发出去", AiKeyStore.defaultCostVisible(AiRole.SHIPPER))
        assertFalse("认不出角色 = 不开（fail-closed）", AiKeyStore.defaultCostVisible(null))
    }

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
