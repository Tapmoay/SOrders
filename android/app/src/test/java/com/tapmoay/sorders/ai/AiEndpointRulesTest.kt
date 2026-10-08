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
     * AI 工具的**默认开关不分角色、一律全开**（2026-10-09 用户：「非派单的写工具默认开起来……
     * 所有功能的 AI 所有功能默认是开的」；此前 2026-09-20 的口径是"派单员全开、其余角色不含
     * 写工具"，那套 opt-in 概念（`OPT_IN_TOOLS` / `optInExclusion`）当天已删）。
     *
     * 这条以前埋在 `AiKeyStore.enabledTools()` 里（要 Context + SharedPreferences，只有真机能验），
     * 抽成纯函数之后这里能把它钉住。**写工具也在默认集里**是刻意的：它的安全边界不在开关上，
     * 而在确认卡（`preview_write` 只能申请，落库要用户点一下，见 `AiWriteService`）
     * 与角色白名单（货主 `AiWrites.SHIPPER_ACTIONS`，fail-closed）。
     */
    @Test
    fun `默认全开：默认集里连写工具都在，且与角色无关`() {
        val all = AiKeyStore.DEFAULT_ENABLED_TOOLS
        assertTrue("写工具必须在默认集里（2026-10-09：写工具也默认开）", AiTools.PREVIEW_WRITE in all)
        assertEquals("首装默认就是默认集本身", all, AiKeyStore.defaultEnabledTools())
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
