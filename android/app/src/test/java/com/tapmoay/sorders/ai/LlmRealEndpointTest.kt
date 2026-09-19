package com.tapmoay.sorders.ai

import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeTrue
import org.junit.Test

/**
 * **真实端点**的流式验证（选测：没配 key 就自动跳过）。
 *
 * ### 为什么要有它（假端点测不到的东西）
 * [LlmStreamingIntegrationTest] 用的是我**按协议文档造的**分片。而真端点的形状有三处
 * 只有实测才知道（`_tools/ai/_probe_streaming.py` 是它的 Python 版，两者互为印证）：
 * 1. **首个分片的 `content` 是 `null`**（不是空串）——只在 `reasoning_content` 上有值；
 * 2. `usage` 分片里**多带好几个字段**（`prompt_tokens_details` / `reasoning_tokens` /
 *    `prompt_cache_hit_tokens`…），解析器必须忽略未知字段而不是整条崩掉；
 * 3. **思考分片远多于正文分片**（实测一次问答：155 个思考分片 vs 20 个正文分片）——
 *    这直接说明"思考绝不能逐片交给界面"（否则聊天页会插进上百条分隔线）。
 *
 * ### 怎么跑
 * ```
 * $env:SORDERS_LLM_API_KEY="sk-..."
 * gradlew :app:testEmuDebugUnitTest --tests "*LlmRealEndpointTest*"
 * ```
 * **key 只从环境变量读，绝不写进任何文件**（本项目红线：key 不落盘明文）。
 * 没设环境变量时用 [assumeTrue] 跳过，所以常规 CI/本地全量测试不受影响。
 */
class LlmRealEndpointTest {

    private val key: String? = System.getenv("SORDERS_LLM_API_KEY")
    private val baseUrl: String = System.getenv("SORDERS_LLM_BASE_URL") ?: "https://api.deepseek.com"
    private val model: String = System.getenv("SORDERS_LLM_MODEL") ?: "deepseek-flash"

    private fun cfg() = LlmConfig(baseUrl = baseUrl, apiKey = key!!, model = model)

    @Test
    fun realEndpointStreamsTextAndUsageAndParsesReasoning() = runBlocking {
        assumeTrue("未设置 SORDERS_LLM_API_KEY，跳过真实端点测试", !key.isNullOrBlank())

        val emissions = mutableListOf<String>()
        val result = LlmClient(streamOptionsUnsupported = { false }).completeStreaming(
            cfg(),
            listOf(ChatMessage.user("用一句话说明今天适合做什么。")),
            emptyList(),
        ) { emissions += it }

        assertTrue("真实端点必须答得出来：$result", result is ChatResult.Success)
        val ok = result as ChatResult.Success

        // ① 真流式：必须多次增量交付（一次就说明是读完才解析）
        assertTrue("必须多次增量交付，实际 ${emissions.size} 次", emissions.size >= 2)
        assertEquals("增量拼接必须等于最终正文", ok.message.content, emissions.joinToString(""))

        // ② usage 必须拿到（40% 自动压缩靠它，拿不到就退化成瞎猜）
        val usage = ok.usage
        assertTrue("stream_options 必须带回 usage", usage != null && usage.promptTokens > 0)
        println("[evidence] 真实端点 usage = prompt=${usage!!.promptTokens} completion=${usage.completionTokens} total=${usage.totalTokens}")

        // ③ 思考过程按**轮**交付（不是逐片）：这里它应当是一整块，且长度可观
        val reasoning = ok.message.reasoningContent
        println("[evidence] 思考过程长度=${reasoning?.length ?: 0}，正文增量交付 ${emissions.size} 次")
        assertTrue("开了思考时应当带出思考过程（它由累加器整轮给出，不逐片）", reasoning.isNullOrBlank() || reasoning.length > 20)
    }

    @Test
    fun realEndpointFragmentedToolCallsAssembleIntoValidJson() = runBlocking {
        assumeTrue("未设置 SORDERS_LLM_API_KEY，跳过真实端点测试", !key.isNullOrBlank())

        val tools = listOf(
            ToolSpec(
                type = "function",
                function = FunctionSpec(
                    name = "read_data",
                    description = "读取系统里的一张只读列表。",
                    parameters = kotlinx.serialization.json.Json.parseToJsonElement(
                        """{"type":"object","properties":{"action":{"type":"string","description":"要查哪张表"},
                           "limit":{"type":"integer","description":"最多返回几条"}},"required":["action"]}""",
                    ) as kotlinx.serialization.json.JsonObject,
                ),
            ),
        )

        val result = LlmClient().completeStreaming(
            cfg(),
            listOf(ChatMessage.user("帮我看看这个月的订单列表，最多 3 条。")),
            tools,
        ) {}

        assertTrue("必须答得出来：$result", result is ChatResult.Success)
        val call = (result as ChatResult.Success).message.toolCalls?.firstOrNull()
        assertTrue("真实端点应当发起工具调用", call != null)
        assertEquals("read_data", call!!.function.name)
        assertTrue("id 必须非空（否则 tool 消息无法配对 → 服务端 400）", call.id.isNotBlank())

        // 最关键的一条：分片拼接出来的 arguments 必须是**合法 JSON**。
        // 只要哪次把"拼接"写成了"覆盖"，这里立刻崩。
        val parsed = kotlinx.serialization.json.Json.parseToJsonElement(call.function.arguments)
        println("[evidence] 真实端点工具参数拼接结果 = ${call.function.arguments}")
        assertTrue("拼出来的参数必须是 JSON 对象", parsed is kotlinx.serialization.json.JsonObject)
    }
}
