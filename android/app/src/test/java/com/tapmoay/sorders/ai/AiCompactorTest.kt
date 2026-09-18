package com.tapmoay.sorders.ai

import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * [AiCompactor] 的单元测试（假传输层，不联网）。
 *
 * 为什么压缩值得单独测：它是**"平时不跑、一到上下文快满才跑"**的代码路径。
 * 这种路径最危险——上线前手工测不到（要把上下文撑到 60%），真跑起来又是在用户
 * 已经聊了很久、最不能出错的时候。所以把它的行为在单测里钉死。
 */
class AiCompactorTest {

    private val cfg = LlmConfig(
        baseUrl = "https://api.deepseek.com",
        apiKey = "sk-unit-test-key",
        model = "deepseek-flash",
    )

    private class FakeTransport(
        private val reply: ChatResult,
        /** 记录收到的请求，供断言"到底把什么送去压缩了"。 */
        val seen: MutableList<List<ChatMessage>> = mutableListOf(),
    ) : LlmTransport {
        override suspend fun complete(
            cfg: LlmConfig,
            messages: List<ChatMessage>,
            tools: List<ToolSpec>,
        ): ChatResult {
            seen += messages
            return reply
        }
    }

    private fun okSummary(text: String) =
        ChatResult.Success(ChatMessage.assistant(text), null)

    private fun history(n: Int) = (1..n).map { i ->
        if (i % 2 == 1) ChatMessage.user("问题 $i") else ChatMessage.assistant("答案 $i")
    }

    @Test
    fun compactsOlderMessagesAndKeepsRecentOnes() = runBlocking {
        val transport = FakeTransport(okSummary("要点：问过单量；本月；尚无结论"))
        val c = AiCompactor(transport)

        val r = c.compact(cfg, history(20), keepRecent = 6)

        assertTrue(r != null)
        assertEquals("要点：问过单量；本月；尚无结论", r!!.summary)
        assertFalse(r.degraded)
        assertEquals("被压缩的是前面 14 条", 14, r.compactedCount)

        // 送进去压缩的内容必须包含**最早的**那几条（否则等于没压）
        val sent = transport.seen.single().joinToString("") { it.content.orEmpty() }
        assertTrue(sent.contains("问题 1"))
        assertTrue("最近的几条不该被送去压缩（它们要原样保留）", !sent.contains("问题 20"))
    }

    @Test
    fun returnsNullWhenNothingToCompact() = runBlocking {
        val transport = FakeTransport(okSummary("不该被调用"))
        val c = AiCompactor(transport)
        assertNull("历史本来就很短 → 不压，也不该白花一次调用", c.compact(cfg, history(4), keepRecent = 6))
        assertTrue("不该发起任何请求", transport.seen.isEmpty())
        assertNull(c.compact(cfg, emptyList()))
    }

    @Test
    fun summarizationFailsDegradesHonestly() = runBlocking {
        val transport = FakeTransport(ChatResult.Failure("模型服务暂时不可用", null))
        val c = AiCompactor(transport)

        val r = c.compact(cfg, history(20), keepRecent = 6)

        assertTrue(r != null)
        assertTrue("必须标成降级，界面要如实告诉用户", r!!.degraded)
        assertEquals(AiCompactor.FALLBACK_NOTE, r.summary)
        // 兜底文案必须说清"更早的内容不可用"，否则用户以为上下文还在，会基于错误前提继续问
        assertTrue(r.summary.contains("省略"))
    }

    @Test
    fun emptySummaryIsTreatedAsFailure() = runBlocking {
        // 模型回了个空串（真实会发生：被安全策略拦、或只回了空白）→ 当作失败，走降级
        val transport = FakeTransport(okSummary("   "))
        val r = AiCompactor(transport).compact(cfg, history(20), keepRecent = 6)
        assertTrue(r!!.degraded)
    }

    @Test
    fun onlySafeMessagesAreSummarized() = runBlocking {
        // 工具往返（assistant 带 tool_calls + tool 结果）不能进摘要请求：
        // 它们成对出现，且下一轮本来就会重查，带进去只是白烧 token
        val messy = listOf(
            ChatMessage.system("不该出现"),
            ChatMessage.user("问题 A"),
            ChatMessage(
                role = "assistant",
                content = null,
                toolCalls = listOf(ToolCall("c1", "function", FunctionCall("f", "{}"))),
            ),
            ChatMessage(role = "tool", content = "工具结果", toolCallId = "c1"),
        ) + history(14)

        val transport = FakeTransport(okSummary("要点"))
        AiCompactor(transport).compact(cfg, messy, keepRecent = 6)

        val sent = transport.seen.single().joinToString("") { it.content.orEmpty() }
        assertTrue(sent.contains("问题 A"))
        assertFalse("system 不该被送去压缩", sent.contains("不该出现"))
        assertFalse("工具结果不该被送去压缩", sent.contains("工具结果"))
    }

    @Test
    fun summarizationRequestDisablesThinking() = runBlocking {
        // 压缩的初衷就是省 token；用最高思考强度去压缩是自相矛盾的
        var seenCfg: LlmConfig? = null
        val transport = object : LlmTransport {
            override suspend fun complete(
                cfg: LlmConfig,
                messages: List<ChatMessage>,
                tools: List<ToolSpec>,
            ): ChatResult {
                seenCfg = cfg
                return okSummary("要点")
            }
        }
        AiCompactor(transport).compact(cfg.copy(thinkingLevel = ThinkingLevel.HIGH), history(20), 6)
        assertEquals(ThinkingLevel.OFF, seenCfg?.thinkingLevel)
    }
}
