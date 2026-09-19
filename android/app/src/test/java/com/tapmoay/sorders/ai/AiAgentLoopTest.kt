package com.tapmoay.sorders.ai

import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * [AiAgentLoop] 的纯逻辑单元测试：**不联网、不依赖 Android 框架、不依赖 Retrofit**。
 *
 * 做法：把 [LlmTransport] 与 [AiToolset] 都换成测试替身，
 * 用脚本控制「第一轮返回 tool_call、第二轮返回文本」，然后检查：
 * ① 工具确实被执行（且参数原样透传）
 * ② 送回模型的消息序列正确（assistant 含 tool_calls、tool 消息带 tool_call_id）
 * ③ 超过 8 轮会停下来（不会无限循环烧 key）
 *
 * 运行：`gradlew :app:testDebugUnitTest --tests "*AiAgentLoopTest*"`
 */
class AiAgentLoopTest {

    private val cfg = LlmConfig(
        baseUrl = "https://api.deepseek.com",
        apiKey = "sk-unit-test-key",
        model = "deepseek-chat",
    )

    // ==================================================================
    //  测试替身
    // ==================================================================

    /** 假传输层：按脚本依次返回结果；脚本用完后重复最后一条（用来模拟「永远调工具」）。 */
    private class FakeTransport(private val script: List<ChatResult>) : LlmTransport {
        /** 每次调用时**快照**下来的 messages（必须 toList()，否则会被后续循环改动污染）。 */
        val seen = mutableListOf<List<ChatMessage>>()
        var callCount = 0
            private set

        override suspend fun complete(
            cfg: LlmConfig,
            messages: List<ChatMessage>,
            tools: List<ToolSpec>,
        ): ChatResult {
            seen += messages.toList()
            val idx = callCount.coerceAtMost(script.lastIndex)
            callCount++
            return script[idx]
        }
    }

    /** 假工具集：记录被调用的 (name, args)，返回固定 JSON。 */
    private class FakeTools(
        val result: String = """{"count":1,"items":[{"user_id":7}]}""",
        override val role: AiRole? = AiRole.DISPATCHER,
    ) : AiToolset {
        override val allToolNames = listOf("search_shipper")
        override val enabledReadModules: Set<String> = AiReadCatalog.modules().toSet()
        override val specs = listOf(
            ToolSpec(
                type = "function",
                function = FunctionSpec(
                    name = "search_shipper",
                    description = "测试用工具",
                    parameters = buildJsonObject { put("type", "object") },
                ),
            ),
        )
        val executed = mutableListOf<Pair<String, String>>()

        override suspend fun execute(name: String, argumentsJson: String): String {
            executed += name to argumentsJson
            return result
        }
    }

    private fun toolCallTurn(
        id: String = "call_1",
        name: String = "search_shipper",
        args: String = """{"query":"张"}""",
    ) = ChatResult.Success(
        ChatMessage(
            role = "assistant",
            content = null,
            toolCalls = listOf(
                ToolCall(id = id, type = "function", function = FunctionCall(name = name, arguments = args)),
            ),
        ),
        null,
    )

    private fun textTurn(text: String, usage: Usage? = null) =
        ChatResult.Success(ChatMessage(role = "assistant", content = text), usage)

    private fun expectSuccess(result: AiRunResult): AiRunResult.Success {
        assertTrue("期望 Success，实际：$result", result is AiRunResult.Success)
        return result as AiRunResult.Success
    }

    private fun expectFailure(result: AiRunResult): AiRunResult.Failure {
        assertTrue("期望 Failure，实际：$result", result is AiRunResult.Failure)
        return result as AiRunResult.Failure
    }

    // ==================================================================
    //  ① + ②  第一轮工具调用 → 第二轮文本
    // ==================================================================

    @Test
    fun firstTurnToolCallThenText() = runBlocking {
        val transport = FakeTransport(
            listOf(
                toolCallTurn(),
                // 注意参数顺序：Usage(promptTokens, completionTokens, totalTokens)
                textTurn("张老板这周 3 单，共 1200.00 元。", Usage(promptTokens = 100, completionTokens = 20, totalTokens = 120)),
            ),
        )
        val tools = FakeTools()
        val events = mutableListOf<AiEvent>()
        val loop = AiAgentLoop(transport, tools, { cfg })

        val result = loop.run("张老板这周几单？", emptyList()) { events += it }

        // ---- ① 工具被执行，参数原样透传 ----
        assertEquals(1, tools.executed.size)
        assertEquals("search_shipper", tools.executed[0].first)
        assertEquals("""{"query":"张"}""", tools.executed[0].second)

        // ---- 最终结果 ----
        val success = expectSuccess(result)
        assertEquals("张老板这周 3 单，共 1200.00 元。", success.text)
        assertEquals(2, success.steps)
        assertEquals(120, success.usage?.totalTokens ?: -1)

        // ---- 事件流 ----
        val started = events.filterIsInstance<AiEvent.ToolStarted>()
        assertEquals(1, started.size)
        assertEquals("search_shipper", started[0].name)
        assertTrue("argsSummary 应带上参数", started[0].argsSummary.contains("张"))

        val finished = events.filterIsInstance<AiEvent.ToolFinished>()
        assertEquals(1, finished.size)
        assertTrue("工具正常返回时 ok 应为 true", finished[0].ok)

        // 非流式：TextDelta 一次性给全量、且只给一次
        assertEquals(
            listOf("张老板这周 3 单，共 1200.00 元。"),
            events.filterIsInstance<AiEvent.TextDelta>().map { it.text },
        )

        val usageEvents = events.filterIsInstance<AiEvent.Usage>()
        assertEquals(1, usageEvents.size)
        assertEquals(120, usageEvents[0].tokens)
        assertEquals(100, usageEvents[0].promptTokens)
        assertEquals(20, usageEvents[0].completionTokens)

        // ---- ② 送回模型的消息序列 ----
        assertEquals("应当正好调用模型 2 次", 2, transport.callCount)

        val firstCall = transport.seen[0]
        assertEquals(listOf("system", "user"), firstCall.map { it.role })
        assertTrue("system 提示词要带今天日期", firstCall[0].content.orEmpty().contains("今天"))
        assertTrue(
            "system 提示词必须声明「不得编造数字」",
            firstCall[0].content.orEmpty().contains("严禁编造"),
        )
        assertEquals("张老板这周几单？", firstCall[1].content)

        val secondCall = transport.seen[1]
        assertEquals(listOf("system", "user", "assistant", "tool"), secondCall.map { it.role })

        // assistant 消息必须原样带 tool_calls（否则后面的 tool 消息没有归属，服务端 400）
        val assistant = secondCall[2]
        assertEquals(1, assistant.toolCalls?.size ?: 0)
        assertEquals("call_1", assistant.toolCalls!![0].id)
        assertEquals("search_shipper", assistant.toolCalls!![0].function.name)

        // tool 消息必须带 tool_call_id，并且内容就是工具返回的 JSON
        val toolMsg = secondCall[3]
        assertEquals("tool", toolMsg.role)
        assertEquals("call_1", toolMsg.toolCallId)
        assertEquals(tools.result, toolMsg.content)
    }

    // ==================================================================
    //  ③ 8 轮硬上限
    // ==================================================================

    @Test
    fun stopsAtEightStepsWhenModelNeverStopsCallingTools() = runBlocking {
        // 脚本只有一条：模型每轮都返回工具调用，永远不会给出最终文本
        val transport = FakeTransport(listOf(toolCallTurn()))
        val tools = FakeTools()
        val events = mutableListOf<AiEvent>()
        val loop = AiAgentLoop(transport, tools, { cfg })

        val result = loop.run("无限循环试试", emptyList()) { events += it }

        assertEquals("硬上限 = 最多 8 次模型调用", AiAgentLoop.DEFAULT_MAX_STEPS, transport.callCount)
        assertEquals(8, tools.executed.size)

        val failure = expectFailure(result)
        assertEquals(8, failure.steps)
        assertTrue(
            "必须明确告知已达最大步骤数，实际：${failure.userMessage}",
            failure.userMessage.contains("最大步骤数"),
        )

        // 第 8 次调用发出时，messages 里已经有 7 组 (assistant, tool) 往返：system + user + 7*2
        val lastCall = transport.seen[7]
        assertEquals("system", lastCall[0].role)
        assertEquals("user", lastCall[1].role)
        assertEquals("第 8 次调用时应累积 7 组工具往返", 2 + 7 * 2, lastCall.size)

        // 每一组 assistant→tool 都必须相邻、且 tool_call_id 对得上（否则服务端 400）
        var i = 2
        while (i + 1 < lastCall.size) {
            assertEquals("assistant", lastCall[i].role)
            assertTrue(lastCall[i].toolCalls?.isNotEmpty() == true)
            assertEquals("tool", lastCall[i + 1].role)
            assertEquals(lastCall[i].toolCalls!![0].id, lastCall[i + 1].toolCallId)
            i += 2
        }
        assertEquals("收尾必须是完整的配对，不能落单", lastCall.size, i)
    }

    // ==================================================================
    //  附加：配置缺失、历史清洗、工具报错不打断循环
    // ==================================================================

    @Test
    fun missingConfigFailsFastWithoutCallingModel() = runBlocking {
        val transport = FakeTransport(listOf(textTurn("不该被调用")))
        val tools = FakeTools()

        // 没配置 provider
        val r1 = AiAgentLoop(transport, tools, { null }).run("你好", emptyList()) {}
        val f1 = expectFailure(r1)
        assertTrue(f1.userMessage.contains("还没有配置模型服务"))

        // key 为空
        val r2 = AiAgentLoop(transport, tools, { cfg.copy(apiKey = "   ") }).run("你好", emptyList()) {}
        val f2 = expectFailure(r2)
        assertTrue(f2.userMessage.contains("API Key"))

        assertEquals("配置不全时不该发起任何模型调用", 0, transport.callCount)
        assertEquals(0, tools.executed.size)
    }

    @Test
    fun historyIsSanitizedToAvoidDanglingToolMessages() = runBlocking {
        val transport = FakeTransport(listOf(textTurn("好的")))
        val loop = AiAgentLoop(transport, FakeTools(), { cfg })

        val dirtyHistory = listOf(
            // 调用方塞进来的 system 必须被丢弃（身份提示词由 loop 统一控制）
            ChatMessage.system("调用方的 system"),
            ChatMessage.user("上周呢？"),
            ChatMessage.assistant("上周 5 单"),
            // 悬空的 assistant(tool_calls)：没有配对的 tool 消息
            ChatMessage(
                role = "assistant",
                content = null,
                toolCalls = listOf(ToolCall("c9", "function", FunctionCall("f", "{}"))),
            ),
            // 悬空的 tool 消息：没有配对的 assistant
            ChatMessage(role = "tool", content = "{}", toolCallId = "c9"),
            ChatMessage(role = "user", content = "   "), // 空消息也要丢
        )

        loop.run("这周呢？", dirtyHistory) {}

        val sent = transport.seen[0]
        assertEquals(listOf("system", "user", "assistant", "user"), sent.map { it.role })
        assertEquals("上周呢？", sent[1].content)
        assertEquals("上周 5 单", sent[2].content)
        assertEquals("这周呢？", sent[3].content)
        assertTrue(sent.none { it.role == "tool" })
    }

    @Test
    fun toolErrorIsReportedButLoopContinues() = runBlocking {        val transport = FakeTransport(
            listOf(
                toolCallTurn(),
                textTurn("该能力暂不可用，请稍后再试。"),
            ),
        )
        val tools = FakeTools(result = """{"error":"该能力暂不可用"}""")
        val events = mutableListOf<AiEvent>()
        val loop = AiAgentLoop(transport, tools, { cfg })

        val result = loop.run("帮我查一下", emptyList()) { events += it }

        // 工具报错不能打断循环：模型仍拿到结果并给出最终答复
        val success = expectSuccess(result)
        assertEquals("该能力暂不可用，请稍后再试。", success.text)

        val finished = events.filterIsInstance<AiEvent.ToolFinished>().single()
        assertFalse("工具返回 error 时 ok 应为 false", finished.ok)
        assertTrue(finished.summary.isNotBlank())

        // 错误也必须作为 tool 消息回灌给模型，否则模型不知道失败了
        assertEquals("""{"error":"该能力暂不可用"}""", transport.seen[1][3].content)
    }

    @Test
    fun contextOverflowFailureIsFlaggedForTheCallerToShrinkAndRetry() = runBlocking {
        // 窗口是按模型名猜的，"猜大了"唯一的补救就是这一次真实报错能被上层认出来
        // （AiChatViewModel 靠这个标记去改窗口重试）。标记丢了 = 用户对着超长报错干瞪眼。
        val transport = FakeTransport(
            listOf(
                ChatResult.Failure(
                    "这个模型装不下这么长的对话",
                    null,
                    contextOverflow = true,
                    contextLimit = 1_048_576,
                ),
            ),
        )
        val failure = expectFailure(
            AiAgentLoop(transport, FakeTools(), { cfg }).run("很长的问题", emptyList()) {},
        )
        assertTrue("超长标记必须透传给上层", failure.contextOverflow)
        assertEquals("端点写明的上限也要一起带上去（一次改准，不用折半逼近）", 1_048_576, failure.contextLimit)
        assertTrue(failure.userMessage.isNotBlank())

        // 普通失败不许带这个标记：带上就会白白把窗口缩一半，而且会**记到模型头上**
        val plain = FakeTransport(listOf(ChatResult.Failure("API key 无效", null)))
        val f2 = expectFailure(AiAgentLoop(plain, FakeTools(), { cfg }).run("你好", emptyList()) {})
        assertFalse(f2.contextOverflow)
        assertEquals(null, f2.contextLimit)
    }

    // ==================================================================
    //  ⑨  说了「卡已发」却一张都没发（真机实测出现过两次）
    // ==================================================================

    @Test
    fun claimWithoutCardIsRetriedInsteadOfAccepted() = runBlocking {
        // 真机现场：用户说「新增挂账单位 X，再登记一辆车 Y」，模型只调了两次**只读**工具，
        // 然后回「两张确认卡发给你了……各点一下确认才生效」——屏幕上没有卡，
        // 用户会去找一张不存在的卡然后卡死。提示词拦过两次没拦住，所以这里拦在代码上。
        val transport = FakeTransport(
            listOf(
                textTurn("两张确认卡发给你了，各点一下「确认」才生效。"),          // ← 谎话（这一轮没调任何工具）
                toolCallTurn(name = AiTools.PREVIEW_WRITE, args = """{"action":"x"}"""),
                textTurn("确认卡发给你了，点确认就写好。"),                        // ← 这次是真发了卡
            ),
        )
        val tools = FakeTools(result = """{"ok":true,"status":"awaiting_user_confirmation","summary":"新增挂账单位：X"}""")
        val events = mutableListOf<AiEvent>()
        val loop = AiAgentLoop(transport, tools, { cfg })

        val result = loop.run("新增挂账单位 X。再登记一辆车 Y", emptyList()) { events += it }

        // ① 谎话没有被当成最终答复：模型被要求重做（多调了一次）
        assertEquals("应当重做一次（谎话1 + 工具 + 真话1）", 3, transport.callCount)
        // ② 重做时喂回去的那句话必须点明"你一次 preview_write 都没调用过"
        val nudge = transport.seen[1].last()
        assertEquals("user", nudge.role)
        assertTrue(
            "要把它自己的话记回上下文",
            transport.seen[1].first { it.role == "assistant" }.content!!.contains("两张确认卡"),
        )
        assertTrue("要摆出事实：一次都没调用过", nudge.content!!.contains("一次 preview_write 都没调用过"))
        // ③ 屏幕上先流出去的谎话要被盖掉（不盖用户会先看到"卡已发"）
        assertTrue(
            "要用 replace 盖掉谎话",
            events.any { it is AiEvent.TextDelta && it.replace && it.text == AiCardClaim.CORRECTION },
        )
        // ④ 最终答复是重做之后那一句
        assertEquals("确认卡发给你了，点确认就写好。", expectSuccess(result).text)
    }

    @Test
    fun realCardThenClaimIsAccepted() = runBlocking {
        // 反向：真发了卡就不该重做（否则每一轮都会白烧一次调用）
        val transport = FakeTransport(
            listOf(
                toolCallTurn(name = AiTools.PREVIEW_WRITE, args = """{"action":"x"}"""),
                textTurn("确认卡发给你了，点确认就写好。"),
            ),
        )
        val tools = FakeTools(result = """{"ok":true,"status":"awaiting_user_confirmation","summary":"新增挂账单位：X"}""")
        val loop = AiAgentLoop(transport, tools, { cfg })

        val result = loop.run("新增挂账单位 X", emptyList()) {}

        assertEquals(2, transport.callCount)
        assertEquals("确认卡发给你了，点确认就写好。", expectSuccess(result).text)
    }

    @Test
    fun claimRetryIsBoundedAndEndsWithTheTruth() = runBlocking {
        // 重做次数用尽还在说"卡已发"：不许原样把那句谎话交付给用户，
        // 要换成"我其实没申请任何卡 + 下一步怎么做"——他才有可操作的动作。
        val transport = FakeTransport(listOf(textTurn("确认卡发给你了，点确认就生效。")))
        val loop = AiAgentLoop(transport, FakeTools(), { cfg })

        val result = loop.run("新增挂账单位 X", emptyList()) {}

        assertEquals(
            "重做次数 = 上限 + 首次那一轮",
            1 + AiAgentLoop.MAX_CARD_CLAIM_RETRIES,
            transport.callCount,
        )
        assertEquals(AiCardClaim.EXHAUSTED, expectSuccess(result).text)
        assertTrue("要告诉用户下一步做什么", AiCardClaim.EXHAUSTED.contains("重做一次"))
    }

    @Test
    fun askingWhetherToOfferACardIsNotAClaim() {
        // 只是提问 ≠ 谎话。判成谎话会白重做一轮（代价小，但没必要）。
        assertFalse(AiCardClaim.looksLikeClaim("要不要我发一张确认卡给你？"))
        assertFalse(AiCardClaim.looksLikeClaim("我来申请一张卡，稍等。"))
        assertFalse(AiCardClaim.looksLikeClaim("这单派给谁？你说了我才申请。"))
        // 真的在说"已经发出去了"才拦
        assertTrue(AiCardClaim.looksLikeClaim("两张确认卡发给你了，各点一下「确认」才生效。"))
        assertTrue(AiCardClaim.looksLikeClaim("卡片已生成，请点确认。"))
        assertTrue(AiCardClaim.looksLikeClaim("那张卡就在聊天页上，点击确认即可。"))
    }
}
