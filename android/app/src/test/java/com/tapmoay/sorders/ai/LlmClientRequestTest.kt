package com.tapmoay.sorders.ai

import com.tapmoay.sorders.core.ApiClient
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * [LlmClient] 请求体组装的纯逻辑单测：**不联网、不起 OkHttp、不发一个 token**。
 *
 * 为什么要有它：思考模式（`thinking`）和思考过程（`reasoning_content`）这两件事
 * **错了不会报错，只会静默失效或静默多花钱** ——
 * - `thinking` 没发出去 → 开关形同虚设（用户以为关了，其实每问一次都多花一倍 token）；
 * - `reasoning_content` 被当成入参发回去 → DeepSeek 系端点直接 400，而且是**第二轮工具调用才炸**，
 *   现象是「简单问题能答、一调工具就报错」，最难排查；
 * - 两个字段名一旦被拼错（`reasoning` / `enable_thinking` / `reasoning_effort`），
 *   实测都会**静默忽略**（返回 200 但不生效）。
 *
 * 所以这里逐条钉死序列化结果，用生产同一份 Json 配置（[ApiClient.json]，`explicitNulls=false`）。
 *
 * 运行：`gradlew :app:testDebugUnitTest --tests "*LlmClientRequestTest*"`
 */
class LlmClientRequestTest {

    private val cfg = LlmConfig(
        baseUrl = "https://api.deepseek.com",
        apiKey = "sk-unit-test-key",
        model = "deepseek-flash",
    )

    private val toolSpec = ToolSpec(
        type = "function",
        function = FunctionSpec(
            name = "search_shipper",
            description = "测试用工具",
            parameters = buildJsonObject { put("type", "object") },
        ),
    )

    /** 走生产路径组装 + 用生产 Json 配置序列化，返回可断言的 JSON 对象。 */
    private fun encode(
        cfg: LlmConfig,
        messages: List<ChatMessage>,
        tools: List<ToolSpec> = emptyList(),
    ): JsonObject = ApiClient.json
        .encodeToJsonElement(ChatRequest.serializer(), LlmClient.buildChatRequest(cfg, messages, tools))
        .jsonObject

    /** 从请求体里取 `thinking.type`（没有这个字段时返回 null）。 */
    private fun thinkingType(json: JsonObject): String? =
        json["thinking"]?.jsonObject?.get("type")?.jsonPrimitive?.content

    // ==================================================================
    //  ① 思考模式开关 → thinking 字段
    // ==================================================================

    @Test
    fun thinkingOnSendsTypeEnabled() {
        val json = encode(cfg.copy(thinkingLevel = ThinkingLevel.MEDIUM), listOf(ChatMessage.user("张老板这周几单？")))

        assertEquals(
            "开了思考模式就必须下发 thinking={\"type\":\"enabled\"}（漏发 = 开关不生效，白开关一场）",
            "enabled",
            thinkingType(json),
        )
    }

    @Test
    fun thinkingOffSendsTypeDisabled() {
        val json = encode(cfg.copy(thinkingLevel = ThinkingLevel.OFF), listOf(ChatMessage.user("张老板这周几单？")))

        // 刻意选择「显式下发 disabled」而不是「省略字段」：
        // 省略 = 交给服务端默认值，若某模型默认就开思考，用户关了开关照样多花一倍 token。
        assertEquals(
            "关了思考模式要显式下发 thinking={\"type\":\"disabled\"}（不能只是省略字段）",
            "disabled",
            thinkingType(json),
        )
    }

    @Test
    fun thinkingAndEffortAreTheOnlyAcceptedSpellings() {
        // 字段名必须精确：实测 `enable_thinking` / `reasoning` 这类写法会被静默忽略（200 但不生效）
        val raw = ApiClient.json.encodeToString(
            ChatRequest.serializer(),
            LlmClient.buildChatRequest(
                cfg.copy(thinkingLevel = ThinkingLevel.MEDIUM),
                listOf(ChatMessage.user("你好")),
                emptyList(),
            ),
        )
        assertFalse("不要出现 enable_thinking（实测无效）", raw.contains("enable_thinking"))
        assertTrue("thinking 字段必须在请求体里", raw.contains("\"thinking\""))
        assertTrue("thinking 的取值必须是 {type:enabled}", raw.contains("{\"type\":\"enabled\"}"))
        // 强度分档：中 → reasoning_effort=medium。
        // ⚠️ 这个字段在部分端点上会被**静默忽略**（本项目实测过 DeepSeek 兼容端点），
        // 所以它是"尽力而为"地下发，界面措辞也如实标注了这一点（见 ThinkingLevel 类注释）。
        assertTrue("思考强度要下发 reasoning_effort", raw.contains("\"reasoning_effort\":\"medium\""))

        // 打印真实请求体：单测报告（build/test-results/…xml 的 <system-out>）里能直接看到发出去的字节，
        // 方便人工核对协议形状，不必为了看一眼 JSON 去搭模拟器。
        println("[evidence] ChatRequest(thinkingLevel=MEDIUM) 实际序列化结果 = $raw")
    }

    @Test
    fun thinkingOffOmitsEffortButStillSendsDisabled() {
        val raw = ApiClient.json.encodeToString(
            ChatRequest.serializer(),
            LlmClient.buildChatRequest(
                cfg.copy(thinkingLevel = ThinkingLevel.OFF),
                listOf(ChatMessage.user("你好")),
                emptyList(),
            ),
        )
        assertTrue("关了也要显式下发 disabled", raw.contains("{\"type\":\"disabled\"}"))
        assertFalse("关了就不该再发 reasoning_effort", raw.contains("reasoning_effort"))
    }

    @Test
    fun everyThinkingLevelMapsToTheRightEffort() {
        // 这一条钉的是"强度 → 请求体"的映射表，改枚举时它立刻会红
        assertEquals(null, ThinkingLevel.OFF.effort)
        assertEquals("low", ThinkingLevel.LOW.effort)
        assertEquals("medium", ThinkingLevel.MEDIUM.effort)
        assertEquals("high", ThinkingLevel.HIGH.effort)
        assertFalse(ThinkingLevel.OFF.enabled)
        assertTrue(ThinkingLevel.LOW.enabled && ThinkingLevel.MEDIUM.enabled && ThinkingLevel.HIGH.enabled)
        // 老版本的布尔开关要能迁移（true→中 / false→关），否则升级等于悄悄把花费翻倍
        assertEquals(ThinkingLevel.OFF, ThinkingLevel.migrate(false))
        assertEquals(ThinkingLevel.MEDIUM, ThinkingLevel.migrate(true))
        assertEquals(ThinkingLevel.DEFAULT, ThinkingLevel.migrate(null))
    }

    // ==================================================================
    //  ② reasoning_content：只读出、不回收
    // ==================================================================

    @Test
    fun reasoningContentIsParsedFromResponse() {
        // 真实形状的响应体（含 reasoning_content 与 usage）
        val body = """
            {"id":"chatcmpl-1","object":"chat.completion","model":"deepseek-flash",
             "choices":[{"index":0,"finish_reason":"stop","message":{
                "role":"assistant","content":"张老板这周 3 单，共 1200.00 元。",
                "reasoning_content":"先按 shipper 查订单，再按 created_at 过滤本周…"}}],
             "usage":{"prompt_tokens":120,"completion_tokens":24,"total_tokens":144}}
        """.trimIndent()

        val resp = ApiClient.json.decodeFromString(ChatResponse.serializer(), body)
        val msg = resp.choices.firstOrNull()?.message ?: error("choices 应至少有一条")

        assertEquals("张老板这周 3 单，共 1200.00 元。", msg.content)
        assertEquals(
            "reasoning_content 必须被读出来（展示思考过程全靠它；丢了就永远看不到思考）",
            "先按 shipper 查订单，再按 created_at 过滤本周…",
            msg.reasoningContent,
        )
        assertEquals(24, resp.usage?.completionTokens ?: -1)
    }

    @Test
    fun reasoningContentIsAbsentWhenThinkingIsOff() {
        // 关闭思考时服务端不返回该字段：必须解成 null（而不是抛异常、也不是空串）
        val body = """
            {"choices":[{"index":0,"finish_reason":"stop","message":{
               "role":"assistant","content":"3 单。"}}]}
        """.trimIndent()

        val resp = ApiClient.json.decodeFromString(ChatResponse.serializer(), body)
        assertNull(resp.choices[0].message.reasoningContent)
    }

    @Test
    fun reasoningContentIsStrippedFromOutgoingMessages() {
        // AiAgentLoop 会把上一轮 assistant 消息（含 reasoning_content）原样塞回 messages 再发下一轮，
        // 而 DeepSeek 系端点「输入里带 reasoning_content」= 直接 400（且只在多轮工具调用时才炸）。
        // 所以下发前必须剥掉——这是唯一的防线。
        val withReasoning = ChatMessage(
            role = "assistant",
            content = null,
            toolCalls = listOf(ToolCall(id = "call_1", function = FunctionCall("search_shipper", "{}"))),
            reasoningContent = "上一轮的思考过程，不能回灌给服务端",
        )
        val json = encode(
            cfg,
            listOf(ChatMessage.system("系统提示"), ChatMessage.user("查一下"), withReasoning, ChatMessage.tool("call_1", "{}")),
        )

        val messages = json["messages"]!!.jsonArray
        assertEquals(4, messages.size)
        messages.forEachIndexed { i, m ->
            assertFalse(
                "第 $i 条消息不该带 reasoning_content（会把 400 引到第二轮）",
                m.jsonObject.containsKey("reasoning_content"),
            )
        }

        // 剥字段不能连累同一条消息的其它内容：tool_calls 与 role 必须原样保留
        val assistant = messages[2].jsonObject
        assertEquals("assistant", assistant["role"]?.jsonPrimitive?.content)
        assertEquals("call_1", assistant["tool_calls"]!!.jsonArray[0].jsonObject["id"]?.jsonPrimitive?.content)
        assertEquals("tool", messages[3].jsonObject["role"]?.jsonPrimitive?.content)
        assertEquals("call_1", messages[3].jsonObject["tool_call_id"]?.jsonPrimitive?.content)
    }

    @Test
    fun reasoningContentFieldNameIsReasoningContent() {
        // 直接序列化一条带思考的消息：字段名必须是协议里的 reasoning_content（拼错 = 永远读不到）
        val raw = ApiClient.json.encodeToString(
            ChatMessage.serializer(),
            ChatMessage(role = "assistant", content = "3 单", reasoningContent = "想一下"),
        )
        assertTrue("字段名必须是 reasoning_content，实际：$raw", raw.contains("\"reasoning_content\":\"想一下\""))
    }

    // ==================================================================
    //  ③ 其它请求体约定（改动时别顺手弄坏）
    // ==================================================================

    @Test
    fun emptyToolsAreOmitted() {
        val json = encode(cfg, listOf(ChatMessage.user("你好")))
        assertFalse("没有工具时不要发 tools（部分兼容服务端对空数组直接 400）", json.containsKey("tools"))
        assertFalse("没有工具时不要发 tool_choice", json.containsKey("tool_choice"))
    }

    @Test
    fun toolsAreSentWithAutoChoice() {
        val json = encode(cfg, listOf(ChatMessage.user("你好")), listOf(toolSpec))
        assertEquals(1, json["tools"]!!.jsonArray.size)
        assertEquals("auto", json["tool_choice"]?.jsonPrimitive?.content)
    }

    @Test
    fun modelNameIsTrimmed() {
        // 用户手输模型名极易带上空格（从别处复制粘贴），带空格 = 服务端 404
        val json = encode(cfg.copy(model = "  deepseek-flash "), listOf(ChatMessage.user("你好")))
        assertEquals("deepseek-flash", json["model"]?.jsonPrimitive?.content)
    }

    // ==================================================================
    //  ④ /models 端点与思考相关的错误识别
    // ==================================================================

    @Test
    fun modelsEndpointToleratesHandTypedBaseUrls() {
        assertEquals("https://api.deepseek.com/models", LlmClient.modelsEndpoint("https://api.deepseek.com"))
        assertEquals("https://api.deepseek.com/models", LlmClient.modelsEndpoint("https://api.deepseek.com/"))
        assertEquals("https://api.deepseek.com/v1/models", LlmClient.modelsEndpoint("https://api.deepseek.com/v1"))
        // 用户把整条 chat/completions 粘进来也要能纠正
        assertEquals(
            "https://api.deepseek.com/v1/models",
            LlmClient.modelsEndpoint("https://api.deepseek.com/v1/chat/completions"),
        )
        assertEquals("https://api.deepseek.com/models", LlmClient.modelsEndpoint("  https://api.deepseek.com/chat/completions/ "))
    }

    @Test
    fun modelListResponseParsesDataIds() {
        // 实测该端点就是这种形状：{"object":"list","data":[{"id":"deepseek-flash"},…]}
        val body = """{"object":"list","data":[{"id":"deepseek-flash"},{"id":"deepseek-v4-pro"},{"id":"deepseek-chat"}]}"""
        val parsed = ApiClient.json.decodeFromString(ModelListResponse.serializer(), body)
        assertEquals(listOf("deepseek-flash", "deepseek-v4-pro", "deepseek-chat"), parsed.data.map { it.id })
    }

    @Test
    fun modelListResponseToleratesOllamaStyle() {
        val body = """{"models":[{"name":"qwen2.5:7b"},{"name":"llama3:8b"}]}"""
        val parsed = ApiClient.json.decodeFromString(ModelListResponse.serializer(), body)
        assertEquals(listOf("qwen2.5:7b", "llama3:8b"), parsed.models.map { it.name })
    }

    @Test
    fun thinkingRejectionIsRecognizedFrom400Body() {
        // 400 有好几种成因，靠错误体里的关键词才能区分「模型名错」和「端点不认 thinking」
        assertTrue(LlmClient.mentionsThinkingSetting("""{"error":{"message":"Unrecognized request argument supplied: thinking"}}"""))
        assertTrue(LlmClient.mentionsThinkingSetting("""{"error":{"message":"reasoning_content is not allowed in input"}}"""))
        assertTrue(LlmClient.mentionsThinkingSetting("""{"detail":"unknown field reasoning_effort"}"""))
        assertFalse(LlmClient.mentionsThinkingSetting("""{"error":{"message":"Model Not Exist"}}"""))
        assertFalse(LlmClient.mentionsThinkingSetting(""))
        assertFalse(LlmClient.mentionsThinkingSetting(null))

        // 提示文案必须说清「已经自动去掉该参数重试过」。
        // 为什么这个词这么重要：第一次遇到不认 thinking 的端点时，LlmClient 会**先自动去掉参数重试一次**
        // （见 LlmClient.complete），所以用户看到这条提示时，事情已经不止是"请关开关"了——
        // 老文案「请在设置里关闭思考」会让人困惑："我已经按你说的关了，怎么还报同一个错？"
        assertTrue(LlmClient.THINKING_REJECTED_HINT.contains("自动去掉"))
        assertTrue(LlmClient.THINKING_REJECTED_HINT.contains("仍然失败"))
    }

    @Test
    fun contextOverflowIsRecognizedFromErrorBody() {
        // 各家报「太长」的措辞和状态码都不一样，只能按关键短语判（这就是自动缩窗口的依据）
        assertTrue(LlmClient.mentionsContextOverflow(
            """{"error":{"message":"This model's maximum context length is 65536 tokens. However, you requested 70000 tokens"}}""",
        ))
        assertTrue(LlmClient.mentionsContextOverflow("""{"error":{"code":"context_length_exceeded"}}"""))
        assertTrue(LlmClient.mentionsContextOverflow("""{"error":{"message":"Please reduce the length of the messages"}}"""))
        assertTrue(LlmClient.mentionsContextOverflow("""{"detail":"输入的上下文长度超过最大长度"}"""))
        assertFalse(LlmClient.mentionsContextOverflow("""{"error":{"message":"Model Not Exist"}}"""))
        assertFalse(LlmClient.mentionsContextOverflow(""))
        assertFalse(LlmClient.mentionsContextOverflow(null))
    }

    @Test
    fun contextOverflowDoesNotSwallowRateLimitOrQuotaErrors() {
        // ⚠️ 这条是防"帮倒忙"：限流/欠费的错误体里也有 "exceeded"，
        // 一旦误判成超长，就会去缩窗口——还会把那个错误的窗口**记到模型头上**，
        // 从此这个模型的上下文被永久压小。
        assertFalse(LlmClient.mentionsContextOverflow(
            """{"error":{"message":"You exceeded your current quota, please check your plan and billing details"}}""",
        ))
        assertFalse(LlmClient.mentionsContextOverflow(
            """{"error":{"message":"Rate limit reached: 500000 tokens per minute"}}""",
        ))
        assertFalse(LlmClient.mentionsContextOverflow(
            """{"error":{"code":"insufficient_quota","message":"Account balance exceeded"}}""",
        ))
    }

    @Test
    fun contextOverflowHintTellsUserWhatToDoNext() {
        // 用户看到这条时，说明**自动缩窗口重试也没成功**，所以必须给出下一步动作，
        // 不能只说"太长了"（那等于把问题丢回给用户）
        assertTrue(LlmClient.CONTEXT_OVERFLOW_HINT.contains("新对话"))
    }

    @Test
    fun theRealDeepSeekOverflowBodyIsRecognizedAndItsLimitIsReadable() {
        // 真实报错原文（`_tools/ai/_probe_context_overflow.py` 用真 key 打出来的，一个字没改）。
        // 这条测试的意义：**自愈链的判断依据是实测过的，不是猜的**。
        val body = """{"error":{"message":"This model's maximum context length is 1048576 tokens. """ +
            """However, you requested 1200006 tokens (1200005 in the messages, 1 in the completion). """ +
            """Please reduce the length of the messages or completion.","type":"invalid_request_error",""" +
            """"param":null,"code":"invalid_request_error"}}"""
        assertTrue("超长必须能被认出来", LlmClient.mentionsContextOverflow(body))
        assertEquals("端点写的上限必须能读出来", 1_048_576, AiContext.parseStatedLimit(body))
        // 而且不许被当成「端点不认 thinking」——那会走错重试路径（去掉参数再试一次，照样超长）
        assertFalse("不许误判成 thinking 被拒", LlmClient.mentionsThinkingSetting(body))
    }

    @Test
    fun thinkingParamIsOmittedWhenEndpointRejectsIt() {
        // includeThinking=false 是「端点不认这个字段」时的降级路径（豆包/千问等第三方兼容端点）。
        // 关键点：**必须一点都不发**——发个空对象或 "disabled" 同样会被 400。
        val cfgDoubao = LlmConfig(
            baseUrl = "https://ark.cn-beijing.volces.com/api/v3",
            apiKey = "sk-unit-test-key",
            model = "doubao-xxx",
            thinkingLevel = ThinkingLevel.MEDIUM,
        )
        val downgraded = LlmClient.buildChatRequest(
            cfgDoubao, listOf(ChatMessage.user("你好")), emptyList(), includeThinking = false,
        )
        assertNull("端点不认 thinking 时不能下发该字段", downgraded.thinking)

        val normal = LlmClient.buildChatRequest(
            cfgDoubao, listOf(ChatMessage.user("你好")), emptyList(), includeThinking = true,
        )
        assertEquals(ThinkingSpec.ENABLED, normal.thinking?.type)
    }

    @Test
    fun thinkingSpecOfMapsBothDirections() {
        assertEquals(ThinkingSpec.ENABLED, ThinkingSpec.of(true).type)
        assertEquals(ThinkingSpec.DISABLED, ThinkingSpec.of(false).type)
        assertEquals("""{"type":"enabled"}""", ApiClient.json.encodeToString(ThinkingSpec.serializer(), ThinkingSpec.enabled()))
    }
}
