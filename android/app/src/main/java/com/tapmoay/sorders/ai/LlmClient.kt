package com.tapmoay.sorders.ai

import com.tapmoay.sorders.core.ApiClient
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.withContext
import kotlinx.serialization.KSerializer
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.descriptors.SerialDescriptor
import kotlinx.serialization.encoding.Decoder
import kotlinx.serialization.encoding.Encoder
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import kotlinx.serialization.json.putJsonObject
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.IOException
import java.net.SocketTimeoutException
import java.util.concurrent.TimeUnit
import kotlin.coroutines.ContinuationInterceptor
import kotlin.coroutines.EmptyCoroutineContext

// ============================================================================
//  协议数据类（字段名严格按 OpenAI Chat Completions 协议，服务端才认）
// ============================================================================

/** LLM 连接参数。apiKey 只在内存里传递，绝不写进任何日志/SharedPreferences 明文。 */
data class LlmConfig(
    val baseUrl: String,
    val apiKey: String,
    val model: String,
    /**
     * 「思考强度」（DeepSeek 兼容端点的 `thinking` + OpenAI 的 `reasoning_effort`，见 [ThinkingLevel]）。
     *
     * 取舍（实测依据）：**开 = 更准**（派单问答要对数字、日期区间、筛选条件更严谨），
     * **关 = 更快更省**（同一问题实测 completion_tokens 24→6，差一倍），且首包更快。
     *
     * 这里的数据类默认值取 **[ThinkingLevel.OFF]**（安静、省钱的保守值，避免某处忘了传参就悄悄多烧 token）；
     * **面向用户的默认值在 [AiKeyStore]（默认「中」）**，最终以那里的说明为准。
     */
    val thinkingLevel: ThinkingLevel = ThinkingLevel.OFF,
    /**
     * 上下文窗口（token 数）。**不是发给服务端的字段**，是本机的预算：
     * 到 [AiContext.COMPACT_AT]（40%）就自动压缩历史，见 [AiContext]。
     *
     * 这个值**由 [AiKeyStore.windowFor] 决定**（按模型名推断 + 撞上限后学到的真实值），
     * 界面上不给用户选（用户口径：不要让用户选那么多，直接给最高的）。
     * 这里的默认值只是"哪都没传"时的兜底（[AiContext.FALLBACK_WINDOW]）。
     */
    val contextWindow: Int = AiContext.FALLBACK_WINDOW,
) {
    /**
     * 归一化后的 chat/completions 端点。
     * 容忍用户手输的各种写法：末尾斜杠、"…/v1"、甚至整条 "…/chat/completions" 粘进来。
     */
    val endpoint: String
        get() {
            var b = baseUrl.trim().trimEnd('/')
            if (b.endsWith("/chat/completions")) b = b.removeSuffix("/chat/completions")
            return b + "/chat/completions"
        }
}

/**
 * 一条对话消息。
 * - system / user：content 必填
 * - assistant：content 可为 null（只调工具时），tool_calls 可空
 * - tool：content = 工具返回值，必须带 tool_call_id（否则服务端 400）
 * - assistant：开思考时服务端会多回一个 `reasoning_content`（思考过程），只用于展示，见下
 *
 * ### 带图片的消息（多模态）
 * [images] 非空时，这条消息在**线上**的 `content` 会从字符串变成
 * `[{"type":"text",...},{"type":"image_url",...}]` 的数组——这是 OpenAI 兼容协议里
 * 传图的标准写法，由 [ChatMessageSerializer] 负责这层转换。
 *
 * **为什么用自定义序列化器而不是把 content 改成 JsonElement**：
 * 后者会让响应解析、工具结果、流式增量等**十几处读 `content` 的代码**全部要改
 * （它们读的都是"文本"），而这里真正需要的只是"发出去的时候换个形状"。
 * 线上格式只在带图时变，不带图时一个字节都不变（老端点、老模型完全不受影响）。
 */
@Serializable(with = ChatMessageSerializer::class)
data class ChatMessage(
    val role: String,
    val content: String? = null,
    @SerialName("tool_calls") val toolCalls: List<ToolCall>? = null,
    @SerialName("tool_call_id") val toolCallId: String? = null,
    /**
     * 模型的思考过程（仅响应里有；开思考模式时服务端才返回）。
     *
     * ⚠️ **只读不回收**：它是**出参**，不是入参。DeepSeek 系端点在输入消息里带上
     * `reasoning_content` 会直接 400（官方文档明确「输入中不要包含该字段」）。
     * 而 [AiAgentLoop] 会把 assistant 消息**原样**塞回 messages（含这个字段），
     * 所以真正下发前由 [LlmClient.buildChatRequest] 统一剥掉——那里是唯一的防线，别删。
     */
    @SerialName("reasoning_content") val reasoningContent: String? = null,
    /**
     * 这一条消息带的图片，格式是 **data URL**（`data:image/jpeg;base64,...`）。
     *
     * 只在**用户那条消息**上出现（模型回复里不会有），而且**只在本次提问的这一轮里存在**：
     * 图片**不进对话历史**（历史里只留一句"这条消息带过一张图"），
     * 因为一张图 base64 之后是几百 KB，写进对话文件会把它撑爆。
     *
     * ⚠️ 它会跟着工具循环的**每一轮请求**一起发出去（多模态协议就是这样：
     * 每次调用都要带上完整上下文）。所以图片在上传前必须先压到"够看清"的大小，
     * 见 [AiAttachmentLoader.readImage]。
     */
    val images: List<String> = emptyList(),
) {
    companion object {
        fun system(text: String) = ChatMessage(role = "system", content = text)
        fun user(text: String) = ChatMessage(role = "user", content = text)

        /** 带图的用户消息（[images] 是 data URL 列表）。 */
        fun userWithImages(text: String, images: List<String>) =
            ChatMessage(role = "user", content = text, images = images)

        fun assistant(text: String) = ChatMessage(role = "assistant", content = text)
        fun tool(callId: String, text: String) = ChatMessage(role = "tool", content = text, toolCallId = callId)
    }
}

/**
 * [ChatMessage] 的线上格式转换器。
 *
 * 规则只有一条：**有图 → content 写成多模态数组；没图 → 原样是字符串**。
 * 反序列化方向要宽容（不同端点回的 content 可能是字符串、也可能是分片数组），
 * 所以数组形态下把 text 分片拼起来。
 */
object ChatMessageSerializer : KSerializer<ChatMessage> {

    /** 中转模型：字段与线上 JSON 一致，只有 `content` 换成 JsonElement（字符串或数组都能装）。 */
    @Serializable
    private data class Wire(
        val role: String,
        val content: JsonElement? = null,
        @SerialName("tool_calls") val toolCalls: List<ToolCall>? = null,
        @SerialName("tool_call_id") val toolCallId: String? = null,
        @SerialName("reasoning_content") val reasoningContent: String? = null,
    )

    private val wire = Wire.serializer()
    private val json = Json { ignoreUnknownKeys = true; explicitNulls = false; encodeDefaults = false }

    override val descriptor: SerialDescriptor = wire.descriptor

    override fun serialize(encoder: Encoder, value: ChatMessage) {
        val content: JsonElement? = if (value.images.isEmpty()) {
            value.content?.let { JsonPrimitive(it) }
        } else {
            buildJsonArray {
                value.content?.takeIf { it.isNotBlank() }?.let {
                    add(buildJsonObject { put("type", "text"); put("text", it) })
                }
                value.images.forEach { url ->
                    add(
                        buildJsonObject {
                            put("type", "image_url")
                            putJsonObject("image_url") { put("url", url) }
                        },
                    )
                }
            }
        }
        encoder.encodeSerializableValue(
            wire,
            Wire(
                role = value.role,
                content = content,
                toolCalls = value.toolCalls,
                toolCallId = value.toolCallId,
                reasoningContent = value.reasoningContent,
            ),
        )
    }

    override fun deserialize(decoder: Decoder): ChatMessage {
        val w = decoder.decodeSerializableValue(wire)
        val text = when (val c = w.content) {
            null -> null
            is JsonPrimitive -> if (c.isString) c.content else c.content
            else -> {
                // 数组形态：把 text 分片拼起来（image_url 分片在**回复**里不会出现）
                val arr = c as? JsonArray ?: return ChatMessage(role = w.role, content = null)
                arr.mapNotNull { el ->
                    (el as? JsonObject)?.get("text")?.let { (it as? JsonPrimitive)?.content }
                }.joinToString("").ifBlank { null }
            }
        }
        return ChatMessage(
            role = w.role,
            content = text,
            toolCalls = w.toolCalls,
            toolCallId = w.toolCallId,
            reasoningContent = w.reasoningContent,
        )
    }
}

/** 模型请求调用工具。arguments 是「JSON 字符串」而不是对象——这是协议规定，别想着改成 JsonObject。 */
@Serializable
data class ToolCall(
    val id: String = "",
    val type: String = "function",
    val function: FunctionCall = FunctionCall(),
)

@Serializable
data class FunctionCall(
    val name: String = "",
    val arguments: String = "",
)

/** 喂给模型的工具定义。 */
@Serializable
data class ToolSpec(
    val type: String = "function",
    val function: FunctionSpec,
)

@Serializable
data class FunctionSpec(
    val name: String,
    val description: String,
    /** JSON Schema（object 型）。 */
    val parameters: JsonObject,
)

/**
 * 「思考模式」开关，对应请求体里的 `thinking` 字段：`{"type":"enabled"}` / `{"type":"disabled"}`。
 *
 * ### 实测结论（目标 DeepSeek 兼容端点，2025-09 实测，别改回别的写法）
 * - `{"type":"enabled"}`  → ✅ 开启思考，响应里出现 `reasoning_content`
 * - `{"type":"disabled"}` → ✅ 真的关掉：`reasoning_content` 消失、completion_tokens 24→6
 * - `reasoning_effort: low/high/minimal` → ❌ **被静默忽略**（返回 200 但思考照样有，最坑的一种：不报错也不生效）
 * - `enable_thinking: false` → ❌ 无效
 * - 带 tools 时开关同样生效，两个模式都能正常返回 tool_calls
 */
@Serializable
data class ThinkingSpec(val type: String) {
    companion object {
        const val ENABLED = "enabled"
        const val DISABLED = "disabled"

        /** 按开关状态构造。取值只允许这两个（见类注释的实测表）。 */
        fun of(enabled: Boolean) = ThinkingSpec(if (enabled) ENABLED else DISABLED)

        fun enabled() = ThinkingSpec(ENABLED)
        fun disabled() = ThinkingSpec(DISABLED)
    }
}

/** `GET {baseUrl}/models` 的返回体（OpenAI 兼容写法：`{"object":"list","data":[{"id":"..."}]}`）。 */
@Serializable
data class ModelListResponse(
    val data: List<ModelItem> = emptyList(),
    /** 兜底：部分端点（Ollama 风格）用 `models[].name` 而不是 `data[].id`。 */
    val models: List<ModelItem> = emptyList(),
)

@Serializable
data class ModelItem(
    val id: String = "",
    val name: String = "",
)

/**
 * `GET {baseUrl}/models` 的结果。与 [ChatResult] 同风格：**不抛异常**，错误转人话。
 * 列模型失败**不能挡住用户**——模型名本来就可以手输，所以每条失败提示都带「可以直接手动输入模型名」。
 */
sealed class ModelListResult {
    data class Success(val models: List<String>) : ModelListResult()
    /** userMessage 可直接展示；raw 是截断后的原始错误体，仅供排障。 */
    data class Failure(val userMessage: String, val raw: String? = null) : ModelListResult()
}

@Serializable
data class ChatRequest(
    val model: String,
    val messages: List<ChatMessage>,
    val tools: List<ToolSpec>? = null,
    @SerialName("tool_choice") val toolChoice: String? = null,
    val temperature: Double = 0.0,
    val stream: Boolean = false,
    /**
     * 流式时用来向服务端**要** `usage`（见 [StreamOptions] 的注释：不要它，40% 自动压缩就退化成瞎猜）。
     *
     * ⚠️ **非流式时必须是 null**：这是个自选字段，端点在不走流式时看到它可能直接 400。
     */
    @SerialName("stream_options") val streamOptions: StreamOptions? = null,
    /** 见 [ThinkingSpec]：开=`enabled`、关=`disabled`；永远显式下发（理由见 [LlmClient.buildChatRequest]）。 */
    val thinking: ThinkingSpec? = null,
    /**
     * 思考强度（OpenAI 的 `reasoning_effort`：`low` / `medium` / `high`）。
     *
     * ⚠️ 部分端点（含本项目实测过的 DeepSeek 兼容端点）会**静默忽略**这个字段：返回 200，
     * 但思考量跟取值无关。所以它只作为"尽力而为"下发，界面措辞也如实标注了这一点
     * （见 [ThinkingLevel] 的类注释）。关思考时**不发**这个字段。
     */
    @SerialName("reasoning_effort") val reasoningEffort: String? = null,
)

@Serializable
data class ChatResponse(
    val choices: List<Choice> = emptyList(),
    val usage: Usage? = null,
    val error: ErrorBody? = null,
)

@Serializable
data class Choice(
    val message: ChatMessage = ChatMessage(role = "assistant"),
    @SerialName("finish_reason") val finishReason: String? = null,
)

@Serializable
data class Usage(
    @SerialName("prompt_tokens") val promptTokens: Int = 0,
    @SerialName("completion_tokens") val completionTokens: Int = 0,
    @SerialName("total_tokens") val totalTokens: Int = 0,
)

@Serializable
data class ErrorBody(
    val message: String? = null,
    val type: String? = null,
    val code: String? = null,
)

/** 调用结果：永远不抛异常给业务层（协程取消除外），错误统一转成人话。 */
sealed class ChatResult {
    data class Success(
        val message: ChatMessage,
        val usage: Usage?,
        /**
         * 这次请求**本来带了图片，但端点不收**，于是自动去掉图片重试了一次。
         *
         * 为什么要一路传到界面：模型看到的是一张**没图的**问题，它的回答会像
         * "你没有发图片给我"或者完全答偏。用户必须知道这一点，否则他会以为
         * "AI 看过我的照片了，它说没问题"。
         */
        val imagesDropped: Boolean = false,
    ) : ChatResult()

    /**
     * userMessage 可直接展示给用户；raw 是截断 300 字以内的原始错误体，仅供排障。
     *
     * [thinkingRejected] = 这次失败**是因为端点不认 `thinking` 参数**。
     * 单独标出来是为了让 [LlmClient] 能自动去掉该参数重试一次——
     * 这是"支持豆包/千问等第三方兼容端点"的关键：它们大多不认这个字段，
     * 而本 App 又刻意总是显式下发它（理由见 [LlmClient.buildChatRequest]）。
     *
     * [contextOverflow] = 这次失败**是因为对话超过了模型能装的长度**。
     * 单独标出来是为了让上层能**自动缩小窗口重试**（见 [AiContext.shrinkOnOverflow]）——
     * 窗口是按模型名猜的，猜大了唯一的补救就是这一次真实报错；不给用户选择就必须能自己修。
     *
     * [contextLimit] = 报错体里**端点自己写明的上限**（如 `maximum context length is 1048576 tokens`）。
     * 拿到它就能把窗口**一次改准**，不用折半逼近；拿不到（各端点写法不一）才退回估算。
     *
     * [streamOptionsRejected] = 这次失败**是因为端点不认 `stream_options` 参数**（同 [thinkingRejected]
     * 的处境：它是我们为了拿 usage 而主动加的自选字段，见 [StreamOptions]）。
     * 标出来是为了让 [LlmClient.completeStreaming] 能去掉它重试一次，并记进能力缓存。
     */
    data class Failure(
        val userMessage: String,
        val raw: String?,
        val thinkingRejected: Boolean = false,
        val contextOverflow: Boolean = false,
        val contextLimit: Int? = null,
        val streamOptionsRejected: Boolean = false,
        /**
         * 这次失败**是因为带了图片**（请求里有图，端点回了 400/415/422）。
         *
         * 标出来是为了让 [LlmClient] 能**去掉图片重试一次**——理由与 [thinkingRejected] 一致：
         * 用户的地址、key、问题都是对的，唯一的问题是"这个模型看不了图"。
         * 让他为此白丢一次提问，不如按纯文字答一遍**并告诉他图没发出去**。
         */
        val imageRejected: Boolean = false,
        /** HTTP 状态码（拿不到时为 null）。排障与"该不该重试"都靠它。 */
        val httpStatus: Int? = null,
    ) : ChatResult()
}

/**
 * LLM 传输层抽象。
 * 抽成 interface 的唯一目的：让 [AiAgentLoop] 能在纯 JVM 单元测试里注入假实现，
 * 不联网就能验证「工具调用循环 + 消息序列 + 8 轮硬上限」。
 */
interface LlmTransport {
    suspend fun complete(cfg: LlmConfig, messages: List<ChatMessage>, tools: List<ToolSpec>): ChatResult

    /**
     * 流式版本：正文增量通过 [onDelta] 实时回调，**返回值与 [complete] 完全同构**
     * （工具调用 / 思考过程 / usage 仍然整轮给全，下游逻辑一行都不用改）。
     *
     * ### 为什么给默认实现，而不是让所有实现都补一个
     * 抽这个接口的唯一目的是单测能注入假传输层（见类注释）。测试替身只关心
     * "第几轮返回什么"，不关心逐字与否——默认实现**退化成非流式**，
     * 于是所有已有的测试替身（[AiAgentLoopTest]、[AiCompactorTest]）一行都不用改。
     *
     * ### 契约（实现者必须遵守）
     * 1. [onDelta] 收到的是**增量片段**，不是全量快照——调用方负责追加；
     * 2. [onDelta] 必须在**调用方所在的协程上下文**里被调用：聊天页会拿它直接写 Compose state
     *    （见 [AiAgentLoop.run] 的注释），从 IO 线程回调会踩到 Compose 的线程约束；
     * 3. 流式失败时**必须能退回非流式**（见 [LlmClient.completeStreaming] 的兜底），
     *    因为"用户点了发送却什么都没发生"比"慢一点但答出来"糟得多。
     */
    suspend fun completeStreaming(
        cfg: LlmConfig,
        messages: List<ChatMessage>,
        tools: List<ToolSpec>,
        onDelta: (String) -> Unit,
    ): ChatResult = complete(cfg, messages, tools)
}

// ============================================================================
//  实现
// ============================================================================

/**
 * 直连 OpenAI 兼容的 `POST {baseUrl}/chat/completions`。
 *
 * ### 设计说明（重要，改之前先读完）
 * 1. **不走 Retrofit**：响应里的 tool_calls 结构是动态的（`arguments` 是「JSON 字符串」而不是对象），
 *    手工用 [ApiClient.json]（ignoreUnknownKeys + coerceInputValues + explicitNulls=false）解析更稳，
 *    不会因为服务端多返回一个字段就整条崩掉。
 * 2. **独立的 OkHttpClient 实例，刻意不挂 HttpLoggingInterceptor**：
 *    请求头带 `Authorization: Bearer <用户自己的 key>`。一旦挂上 BODY 级日志，
 *    key 就会被写进 logcat / 抓包文件——这是本项目的红线。
 *    也**不要**复用 ApiClient 的那个 client（它带 BuildConfig.DEBUG_LOG 控制的 BODY 日志）。
 * 3. **流式（v3.5 起）**：走 `stream:true` + 自己解析 SSE，正文边生成边交给聊天页。
 *    为什么要自己解而不是用 okhttp-sse（官方自述 experimental）：本功能只需要
 *    `data:` 行 + `[DONE]` + 增量 tool_calls 三件事，自己解反而更可控，
 *    而且**解析逻辑被抽成纯类 [ChatStreamAccumulator]，可以脱网单测**——
 *    这正是流式最容易出错、又最难手工覆盖的地方（分片边界）。
 *    非流式的 [complete] 仍然保留：它是流式全部降级路径的最终兜底，也是单测替身的默认实现。
 *
 *    ⚠️ **重试的红线**：已经吐过字就不许重试（会让用户看到同一段回答两遍），
 *    见 [completeStreaming] 的注释。
 * 4. **超时给足**：LLM 首包经常几十秒，OkHttp 默认 10s 读超时会大量误判超时。
 *    这里连接 20s / 读 120s / 写 30s，且不做自动重试（重试会把费用翻倍）。
 */
class LlmClient(
    private val client: OkHttpClient = defaultClient(),
    /**
     * 「这个 Base URL 已知不接受 `thinking` 参数」——生产上由 [AiKeyStore.thinkingUnsupported] 提供。
     * 已知不接受的地址直接**不发**这个字段，省掉一次注定失败的请求。
     */
    private val thinkingUnsupported: (String) -> Boolean = { false },
    /** 第一次发现某地址不接受 `thinking` 时回调（用于持久化这个能力，见 [AiKeyStore.markThinkingUnsupported]）。 */
    private val onThinkingUnsupported: (String) -> Unit = {},
    /**
     * 第一次发现某地址不接受 `stream_options` 时回调
     * （见 [AiKeyStore.markStreamOptionsUnsupported]；与 [onThinkingUnsupported] 完全对称）。
     */
    private val onStreamOptionsUnsupported: (String) -> Unit = {},
    /**
     * 「这个 Base URL 已知不接受 `stream_options`」——生产上由 [AiKeyStore.streamOptionsUnsupported] 提供。
     * 已知不接受的地址直接不发这个字段，省掉一次注定失败的往返（代价是这一次拿不到 usage）。
     */
    private val streamOptionsUnsupported: (String) -> Boolean = { false },
) : LlmTransport {

    override suspend fun complete(
        cfg: LlmConfig,
        messages: List<ChatMessage>,
        tools: List<ToolSpec>,
    ): ChatResult {
        validateConfig(cfg)?.let { return it }
        val url = cfg.endpoint

        // 已知这个地址不认 thinking 参数 → 直接不发，省一次注定失败的往返
        val knownUnsupported = thinkingUnsupported(cfg.baseUrl)
        val first = sendOnce(cfg, url, messages, tools, includeThinking = !knownUnsupported)

        // 带图被拒 → **去掉图片重试一次**（理由见 ChatResult.Failure.imageRejected）
        (first as? ChatResult.Failure)?.takeIf { it.imageRejected }?.let {
            return sendOnce(cfg, url, stripImages(messages), tools, includeThinking = !knownUnsupported).withImagesDropped()
        }

        // 端点不认 thinking（豆包/千问等第三方兼容端点常见）→ **自动去掉该参数重试一次**。
        // 为什么值得多打一次请求：用户点的预设地址是对的、key 是对的，唯一的问题是
        // 我们多发了一个它不认识的字段。让用户为此去理解"思考模式"是不合理的。
        // 只重试一次、且只在「确实发了该参数」时才重试 —— 不会变成无限重试或重复计费。
        if (first is ChatResult.Failure && first.thinkingRejected && !knownUnsupported) {
            val retry = sendOnce(cfg, url, messages, tools, includeThinking = false)
            if (retry is ChatResult.Success) {
                // 记住这个能力：以后不再多发这个字段（也避免每次都白试一次）
                onThinkingUnsupported(cfg.baseUrl)
            }
            return retry
        }
        return first
    }

    /** 去掉所有图片（重试用）。 */
    private fun stripImages(messages: List<ChatMessage>): List<ChatMessage> =
        messages.map { if (it.images.isEmpty()) it else it.copy(images = emptyList()) }

    /** 重试成功时打上"图被丢了"的标记（界面要据此告诉用户）。 */
    private fun ChatResult.withImagesDropped(): ChatResult =
        if (this is ChatResult.Success) copy(imagesDropped = true) else this

    // ========================================================================
    //  流式（SSE）
    // ========================================================================

    /**
     * 流式调用：正文**边生成边交给 [onDelta]**，其余（工具调用 / 思考 / usage）整轮给全。
     *
     * ### 为什么值得做（用户口径：消除与 App 之间的摩擦）
     * 改造前是"转圈等到全部生成完才一次性显示"——一轮带 3 次工具调用的问答要等十几秒，
     * 期间屏幕上只有一个"正在思考…"。对一个没用过这个 App 的人来说，
     * **看不见进展的等待和卡死没有区别**，他会在第 5 秒就切走。
     *
     * ### 为什么敢做（架构早就留好了口子）
     * [AiEvent.TextDelta] 的注释在改造前就写着"以后换成流式时这个事件可以连续触发，
     * 聊天页不用改"；而聊天页的实现确实已经是**追加**语义（`streamed.append(ev.text)`）。
     * 所以这一层换实现，UI 一行都不用动。
     *
     * ### 三条降级路径（"答不出来"绝不可以是流式带来的新失败）
     * 1. **端点不认 `stream_options`** → 去掉它重试（拿不到 usage，但答得出来），并记进能力缓存；
     * 2. **端点不认 `thinking`** → 同上（与非流式共用同一套机制）；
     * 3. **端点无视 `stream:true`**（回了普通 JSON 而非 SSE）→ [ChatStreamAccumulator.sawSseData]
     *    检测到没有 SSE 数据行，把整个响应体按**非流式**解析（见 [finishStream]）。
     *
     * ### 重试的硬约束：**已经吐过字就不许重试**
     * 重试会把内容重新生成一遍，用户会看到同一句话出现两次。所以只有
     * "一个字都还没交出去"（`emittedChars == 0`）时才允许换参数重试——
     * 而参数被拒恰好都发生在 HTTP 阶段（响应体还没开始流），这个条件天然满足。
     */
    override suspend fun completeStreaming(
        cfg: LlmConfig,
        messages: List<ChatMessage>,
        tools: List<ToolSpec>,
        onDelta: (String) -> Unit,
    ): ChatResult {
        validateConfig(cfg)?.let { return it }

        var includeThinking = !thinkingUnsupported(cfg.baseUrl)
        var includeStreamOptions = !streamOptionsUnsupported(cfg.baseUrl)
        // 哪些字段是"因为端点拒绝才丢掉的"——只在这些字段真的丢了、且最终成功时才记进能力缓存
        val dropped = mutableSetOf<String>()
        var attempt = 0

        while (true) {
            attempt++
            val a = sendStreamOnce(
                cfg = cfg,
                messages = messages,
                tools = tools,
                includeThinking = includeThinking,
                includeStreamOptions = includeStreamOptions,
                onDelta = onDelta,
            )
            (a.result as? ChatResult.Success)?.let {
                if (DROPPED_THINKING in dropped) onThinkingUnsupported(cfg.baseUrl)
                if (DROPPED_STREAM_OPTIONS in dropped) onStreamOptionsUnsupported(cfg.baseUrl)
                return it
            }
            val f = a.result as ChatResult.Failure
            // 带图被拒 → 去掉图片重试一次（还没吐过字，重试是安全的）
            if (f.imageRejected && messages.any { it.images.isNotEmpty() } && a.emittedChars == 0) {
                return sendStreamOnce(
                    cfg = cfg,
                    messages = stripImages(messages),
                    tools = tools,
                    includeThinking = includeThinking,
                    includeStreamOptions = includeStreamOptions,
                    onDelta = onDelta,
                ).let { it.result.withImagesDropped() }
            }
            // 已经吐过字：重试会重复内容，宁可把这次失败如实报出来
            if (a.emittedChars > 0 || attempt >= MAX_STREAM_ATTEMPTS) return f

            val retried = when {
                f.thinkingRejected && includeThinking -> {
                    includeThinking = false
                    dropped += DROPPED_THINKING
                    true
                }
                f.streamOptionsRejected && includeStreamOptions -> {
                    includeStreamOptions = false
                    dropped += DROPPED_STREAM_OPTIONS
                    true
                }
                // 兜底：报错体没点名是哪个字段（有的端点只说 "unrecognized request argument"）。
                // 按"先去掉最可能被拒的那个"依次试，保证最多 [MAX_STREAM_ATTEMPTS] 次。
                includeStreamOptions -> {
                    includeStreamOptions = false
                    dropped += DROPPED_STREAM_OPTIONS
                    true
                }
                includeThinking -> {
                    includeThinking = false
                    dropped += DROPPED_THINKING
                    true
                }
                else -> false
            }
            if (!retried) return f
        }
    }

    /** 一次流式尝试的结果 + **已经交给 UI 的字符数**（决定还能不能重试，见 [completeStreaming]）。 */
    private data class StreamAttempt(val result: ChatResult, val emittedChars: Int)

    private suspend fun sendStreamOnce(
        cfg: LlmConfig,
        messages: List<ChatMessage>,
        tools: List<ToolSpec>,
        includeThinking: Boolean,
        includeStreamOptions: Boolean,
        onDelta: (String) -> Unit,
    ): StreamAttempt {
        // 这一批消息里有没有图：决定了"400 是不是因为图"（见 ChatResult.Failure.imageRejected）
        val hadImages = messages.any { it.images.isNotEmpty() }
        val body = buildChatRequest(
            cfg = cfg,
            messages = messages,
            tools = tools,
            includeThinking = includeThinking,
            stream = true,
            includeStreamOptions = includeStreamOptions,
        )
        val jsonText = try {
            ApiClient.json.encodeToString(ChatRequest.serializer(), body)
        } catch (e: Exception) {
            return StreamAttempt(ChatResult.Failure("请求参数构造失败：" + (e.message ?: "序列化异常"), null), 0)
        }

        val request = Request.Builder()
            .url(cfg.endpoint)
            .header("Authorization", "Bearer " + cfg.apiKey.trim())
            .header("Content-Type", "application/json")
            .header("Accept", "text/event-stream")
            .post(jsonText.toRequestBody(JSON_MEDIA))
            .build()

        // 增量必须在**调用方所在的协程上下文**里交付：聊天页会拿它直接写 Compose state
        // （见 [AiAgentLoop.run] 的注释），而读流必须切到 IO。所以先把调用方的调度器记下来。
        val delivery = currentCoroutineContext()[ContinuationInterceptor]

        var emitted = 0
        return withContext(Dispatchers.IO) {
            val call = client.newCall(request)
            val cancelHandle = this.coroutineContext[Job]?.invokeOnCompletion { cause ->
                if (cause != null) call.cancel()
            }
            try {
                call.execute().use { resp ->
                    if (!resp.isSuccessful) {
                        val text = try {
                            resp.body?.string().orEmpty()
                        } catch (e: IOException) {
                            ""
                        }
                        return@use StreamAttempt(
                            ChatResult.Failure(
                                httpMessage(resp.code, text),
                                scrub(truncate(text), cfg.apiKey),
                                thinkingRejected = resp.code == 400 && mentionsThinkingSetting(text),
                                contextOverflow = mentionsContextOverflow(text),
                                contextLimit = AiContext.parseStatedLimit(text),
                                streamOptionsRejected = resp.code == 400 && mentionsStreamOptions(text),
                                imageRejected = hadImages && resp.code in IMAGE_REJECT_CODES,
                                httpStatus = resp.code,
                            ),
                            emitted,
                        )
                    }
                    val source = resp.body?.source()
                        ?: return@use StreamAttempt(ChatResult.Failure("模型服务返回了空响应", null), emitted)

                    val acc = ChatStreamAccumulator()
                    while (true) {
                        val line = source.readUtf8Line() ?: break
                        if (!acc.feed(line)) break
                        val out = acc.pendingForFlush()
                        if (out.isNotEmpty()) {
                            emitted += out.length
                            withContext(delivery ?: EmptyCoroutineContext) { onDelta(out) }
                        }
                    }
                    // 收尾必须无条件提交一次：否则回答的最后几个字会留在缓冲里丢掉
                    val tail = acc.drainAll()
                    if (tail.isNotEmpty()) {
                        emitted += tail.length
                        withContext(delivery ?: EmptyCoroutineContext) { onDelta(tail) }
                    }
                    StreamAttempt(finishStream(acc, cfg.apiKey), emitted)
                }
            } catch (e: SocketTimeoutException) {
                StreamAttempt(
                    ChatResult.Failure("连接模型服务超时（检查网络，或换一个 Base URL / 模型）", scrub(truncate(e.message), cfg.apiKey)),
                    emitted,
                )
            } catch (e: IOException) {
                if (call.isCanceled()) {
                    throw kotlinx.coroutines.CancellationException("LLM 调用已取消")
                }
                StreamAttempt(
                    ChatResult.Failure("无法连接模型服务（检查网络 / Base URL）", scrub(truncate(e.message), cfg.apiKey)),
                    emitted,
                )
            } catch (e: kotlinx.coroutines.CancellationException) {
                throw e
            } catch (e: Exception) {
                StreamAttempt(
                    ChatResult.Failure("调用模型服务出错：" + (e.message ?: e.javaClass.simpleName), scrub(truncate(e.message), cfg.apiKey)),
                    emitted,
                )
            } finally {
                cancelHandle?.dispose()
            }
        }
    }

    /**
     * 把累加器收成 [ChatResult]。
     *
     * 这里承担三个"流式特有的收尾判断"，每一个都对应一种真实存在的端点行为：
     * ① 一个 SSE 数据行都没收到 → 端点无视了 `stream:true`，把整个响应体按**非流式**再解析一次；
     * ② 端点把错误塞在流里（HTTP 200 但分片里带 `error`）→ 有正文就照常给（拿到的东西是有用的），
     *    一个字都没有才算失败——**不能因为一个尾部错误把用户已经看到的回答吃掉**；
     * ③ 正文和工具调用都为空 → 如实报"没有返回内容"，不假装答完了。
     */
    private fun finishStream(acc: ChatStreamAccumulator, apiKey: String): ChatResult {
        if (!acc.sawSseData) {
            val raw = acc.raw.toString()
            if (raw.isBlank()) return ChatResult.Failure("模型服务返回了空响应", null)
            return parseBody(raw, apiKey)
        }
        val msg = acc.toMessage()
        val hasContent = !msg.content.isNullOrBlank() || !msg.toolCalls.isNullOrEmpty()
        acc.streamError?.let { err ->
            if (!hasContent) {
                val code = err.code.orEmpty()
                val hint = when (code) {
                    "401", "invalid_api_key" -> "API key 无效或已过期"
                    "402", "insufficient_quota" -> "余额不足"
                    "429" -> "调用过于频繁或余额不足"
                    else -> err.message.orEmpty().ifBlank { "模型服务返回错误" }
                }
                return ChatResult.Failure(hint, scrub(truncate(acc.raw.toString()), apiKey))
            }
        }
        if (!hasContent) {
            return ChatResult.Failure("模型没有返回任何回复（流式响应为空）", scrub(truncate(acc.raw.toString()), apiKey))
        }
        return ChatResult.Success(msg, acc.usage)
    }

    /** 三个前置校验（非流式与流式共用同一套人话错误，避免两条路径给出不同措辞）。 */
    private fun validateConfig(cfg: LlmConfig): ChatResult.Failure? {
        if (cfg.apiKey.isBlank()) {
            return ChatResult.Failure("API Key 为空，请先到「AI 助手设置」填写。", null)
        }
        if (cfg.model.isBlank()) {
            return ChatResult.Failure("模型名为空，请先到「AI 助手设置」填写。", null)
        }
        val url = cfg.endpoint
        if (!url.startsWith("http://") && !url.startsWith("https://")) {
            return ChatResult.Failure("Base URL 必须以 http:// 或 https:// 开头（当前：${cfg.baseUrl}）", null)
        }
        return null
    }

    /**
     * 报错体里是不是在说「不认 `stream_options` / `include_usage`」。
     *
     * 判据刻意收窄成**只认这两个字段名**：通用的 "unrecognized request argument"
     * 既可能指 `stream_options` 也可能指 `thinking`，认了会把降级路径带偏。
     * 那种只说笼统话的端点由 [completeStreaming] 的兜底分支按顺序试，最多 3 次。
     */
    private fun mentionsStreamOptions(body: String?): Boolean {
        if (body.isNullOrBlank()) return false
        val b = body.lowercase()
        return b.contains("stream_options") || b.contains("include_usage")
    }

    /** 真正发一次请求。抽出来是为了让「带/不带 thinking」两条路径共用同一段网络与解析逻辑。 */
    private suspend fun sendOnce(
        cfg: LlmConfig,
        url: String,
        messages: List<ChatMessage>,
        tools: List<ToolSpec>,
        includeThinking: Boolean,
    ): ChatResult {
        // 这一批消息里有没有图：决定了"400 是不是因为图"（见 ChatResult.Failure.imageRejected）
        val hadImages = messages.any { it.images.isNotEmpty() }
        // 请求体组装统一走 buildChatRequest（单测直接断言它的序列化结果，见 LlmClientRequestTest）
        val body = buildChatRequest(cfg, messages, tools, includeThinking = includeThinking)

        val jsonText = try {
            ApiClient.json.encodeToString(ChatRequest.serializer(), body)
        } catch (e: Exception) {
            return ChatResult.Failure("请求参数构造失败：" + (e.message ?: "序列化异常"), null)
        }

        val request = Request.Builder()
            .url(url)
            .header("Authorization", "Bearer " + cfg.apiKey.trim())
            .header("Content-Type", "application/json")
            .header("Accept", "application/json")
            .post(jsonText.toRequestBody(JSON_MEDIA))
            .build()

        return withContext(Dispatchers.IO) {
            val call = client.newCall(request)
            // 协程被取消（用户退出聊天页）时顺手掐掉 HTTP 调用，避免留下 120s 的僵尸请求。
            // 注意：这里只在「确实被取消」时 cancel，正常完成时 call 已结束，cancel 是空操作。
            val cancelHandle = this.coroutineContext[Job]?.invokeOnCompletion { cause ->
                if (cause != null) call.cancel()
            }
            try {
                call.execute().use { resp ->
                    val text = try {
                        resp.body?.string().orEmpty()
                    } catch (e: IOException) {
                        return@use ChatResult.Failure("读取模型响应失败：" + (e.message ?: "连接中断"), null)
                    }
                    if (!resp.isSuccessful) {
                        return@use ChatResult.Failure(
                            httpMessage(resp.code, text),
                            scrub(truncate(text), cfg.apiKey),
                            thinkingRejected = resp.code == 400 && mentionsThinkingSetting(text),
                            contextOverflow = mentionsContextOverflow(text),
                            contextLimit = AiContext.parseStatedLimit(text),
                            // v3.33：带图被拒（见 [ChatResult.Failure.imageRejected]）
                            imageRejected = hadImages && resp.code in IMAGE_REJECT_CODES,
                            httpStatus = resp.code,
                        )
                    }
                    parseBody(text, cfg.apiKey)
                }
            } catch (e: SocketTimeoutException) {
                // 连接/读超时都落这里
                ChatResult.Failure("连接模型服务超时（检查网络，或换一个 Base URL / 模型）", scrub(truncate(e.message), cfg.apiKey))
            } catch (e: IOException) {
                if (call.isCanceled()) {
                    // 协程取消导致的 IOException：交给上层按取消处理。
                    throw kotlinx.coroutines.CancellationException("LLM 调用已取消")
                }
                ChatResult.Failure("无法连接模型服务（检查网络 / Base URL）", scrub(truncate(e.message), cfg.apiKey))
            } catch (e: kotlinx.coroutines.CancellationException) {
                throw e
            } catch (e: Exception) {
                ChatResult.Failure("调用模型服务出错：" + (e.message ?: e.javaClass.simpleName), scrub(truncate(e.message), cfg.apiKey))
            } finally {
                cancelHandle?.dispose()
            }
        }
    }

    /** 解析 2xx 响应体：兼容「200 但体内是 error」和「choices 为空」两类坑。 */
    private fun parseBody(text: String, apiKey: String): ChatResult {
        if (text.isBlank()) {
            return ChatResult.Failure("模型服务返回了空响应", null)
        }
        val resp = try {
            ApiClient.json.decodeFromString(ChatResponse.serializer(), text)
        } catch (e: Exception) {
            // 常见于 Base URL 指到了网页/网关（返回 HTML），或指到了非 OpenAI 协议的服务
            return ChatResult.Failure(
                "模型返回内容无法解析（确认 Base URL 是 OpenAI 兼容接口，且模型名正确）",
                scrub(truncate(text), apiKey),
            )
        }
        resp.error?.let { err ->
            val code = err.code.orEmpty()
            val msg = err.message.orEmpty().ifBlank { "模型服务返回错误" }
            // 200 但体内是「上下文超长」→ 先标成可自愈的失败（上层会自动缩窗口重试）
            if (mentionsContextOverflow(text)) {
                return ChatResult.Failure(
                    CONTEXT_OVERFLOW_HINT,
                    scrub(truncate(text), apiKey),
                    contextOverflow = true,
                    contextLimit = AiContext.parseStatedLimit(text),
                )
            }
            // 400 且体内提到 thinking / reasoning → 不是「模型名错」，而是端点不接受思考开关（见 httpMessage）
            if (code == "400" && mentionsThinkingSetting(text)) {
                return ChatResult.Failure(THINKING_REJECTED_HINT, scrub(truncate(text), apiKey), thinkingRejected = true)
            }
            val hint = when (code) {
                "401", "invalid_api_key" -> "API key 无效或已过期"
                "402", "insufficient_quota" -> "余额不足"
                "429" -> "调用过于频繁或余额不足"
                else -> msg
            }
            return ChatResult.Failure(hint, scrub(truncate(text), apiKey))
        }
        val msg = resp.choices.firstOrNull()?.message
            ?: return ChatResult.Failure("模型没有返回任何回复（choices 为空）", scrub(truncate(text), apiKey))
        return ChatResult.Success(msg, resp.usage)
    }

    /**
     * HTTP 状态码（+ 错误体）→ 人话。区分「key 错」「没权限」「模型名/地址错」「限流」四类。
     *
     * 为什么要看 [body]：400 有好几种成因——模型名不被支持、工具定义不被接受、
     * **端点不认 `thinking` 参数**。光看状态码分不出来（错误体里通常写着
     * `Unrecognized request argument: thinking` 之类），所以在 400 上多判一次关键词，
     * 否则用户只会看到「请求不合法」而完全不知道该关哪个开关。
     */
    private fun httpMessage(code: Int, body: String? = null): String {
        // 顺序有意为之：先判「超长」。超长的错误体里有时也带 "reasoning"（说 completion 里花了多少），
        // 判成 thinking 被拒会走错重试路径（去掉 thinking 再试一次，照样超长）。
        if (mentionsContextOverflow(body)) return CONTEXT_OVERFLOW_HINT
        if (code == 400 && mentionsThinkingSetting(body)) return THINKING_REJECTED_HINT
        return when (code) {
            400 -> "模型服务认为请求不合法（400）：可能是模型名不被支持，或工具定义不被该模型接受"
            401 -> "API key 无效或已过期"
            402 -> "余额不足，请先充值"
            403 -> "API key 无权访问该模型"
            404 -> "模型名或 Base URL 不对"
            408 -> "模型服务响应超时"
            413 -> "对话内容超过了这个模型能接受的长度（历史消息太长）"
            422 -> "模型名或参数不被支持（422）"
            429 -> "调用过于频繁或余额不足"
            in 500..599 -> "模型服务暂时不可用（$code），稍后重试"
            else -> "模型服务返回错误（$code）"
        }
    }

    companion object {
        private val JSON_MEDIA = "application/json; charset=utf-8".toMediaType()

        /**
         * 流式调用的最大尝试次数（含首次）。
         *
         * 为什么是 3：最多只需要丢掉两个自选字段（`thinking`、`stream_options`），
         * 加上首次正好 3 次。**必须有上限**——否则遇到一个"什么都不认"的端点会一直重试，
         * 而每次重试都是一次计费请求。
         */
        private const val MAX_STREAM_ATTEMPTS = 3

        /** 降级记录用的键（只是内部标记，不是协议字段）。 */
        private const val DROPPED_THINKING = "thinking"
        private const val DROPPED_STREAM_OPTIONS = "stream_options"

        /**
         * 「带图被拒」的状态码集合。
         *
         * 400 = 参数不合法（最常见："content must be a string"）；
         * 415 = 不支持的媒体类型；422 = 结构对但内容不被接受。
         *
         * ⚠️ 三个码都只在**请求里确实带了图**时才算"图被拒"（判断处见 `hadImages`）——
         * 否则一个普通的 400（比如模型名写错）会被误判成图的问题，白白重发一次请求。
         */
        private val IMAGE_REJECT_CODES = setOf(400, 415, 422)

        /**
         * 设置页里对「该地址不支持 stream_options」的解释文案。
         * 与 [THINKING_UNSUPPORTED_NOTE] 同样是**已知能力说明**而非报错：
         * 拿不到 usage 只会让"上下文自动压缩"的触发时机变粗，**不影响能不能答**，
         * 所以措辞不能让用户以为功能坏了。
         */
        const val STREAM_OPTIONS_UNSUPPORTED_NOTE =
            "当前模型地址不接受 `stream_options` 参数，已自动跳过它（不影响回答）。" +
                "代价是拿不到服务端的 token 用量，上下文压缩会改用本机估算。换支持该参数的地址后会自动恢复。"

        /**
         * 端点不接受思考开关时的统一提示。
         *
         * ⚠️ **这句话只在"去掉参数重试之后仍然失败"时才会被用户看到**
         * （见 [LlmClient.complete]：第一次遇到会先自动去掉 `thinking` 重试一次）。
         * 所以措辞不能停在"请关闭思考"——用户会觉得"我明明没开"。
         * 必须说清"已经自动试过不带这个参数了"。
         */
        const val THINKING_REJECTED_HINT =
            "这个模型端点不接受「思考模式」参数，已经自动去掉该参数重试，仍然失败。" +
                "请确认模型名与 Base URL，或换一个模型。"

        /**
         * 设置页里对「该地址不支持思考开关」的解释文案。
         * 与 [THINKING_REJECTED_HINT] 分开写：一个是报错、一个是**已知能力说明**，
         * 前者出现在聊天失败时，后者出现在用户看设置时，语境不同。
         */
        const val THINKING_UNSUPPORTED_NOTE =
            "当前模型地址不接受「思考模式」参数，已自动跳过它（不影响使用）。" +
                "换回支持该参数的地址（如 DeepSeek）后会自动恢复。"

        /**
         * 错误体里是否提到思考相关参数。判断依据：错误体里出现 `thinking` / `reasoning`
         * （覆盖 `thinking`、`reasoning_effort`、`reasoning_content`、`enable_thinking` 等写法）。
         */
        fun mentionsThinkingSetting(body: String?): Boolean {
            if (body.isNullOrBlank()) return false
            val b = body.lowercase()
            return b.contains("thinking") || b.contains("reasoning")
        }

        /**
         * 错误体里是否在说**「上下文/历史太长」**。命中就说明我们猜的窗口比真实上限大。
         *
         * 为什么不能只看状态码：不同端点用不同码和不同措辞报同一件事——
         * `400 invalid_request_error` / `413` / 200 体内 error 都出现过，措辞有
         * `context length`、`maximum context`、`too long`、`reduce the length`……
         * 所以这里按**关键短语**判，而不是按码判。
         *
         * 反过来的风险也要防：普通 400（模型名错）里不该出现这些短语，所以不会误判成超长。
         */
        fun mentionsContextOverflow(body: String?): Boolean {
            if (body.isNullOrBlank()) return false
            val b = body.lowercase()
            return CONTEXT_OVERFLOW_PHRASES.any { b.contains(it) }
        }

        private val CONTEXT_OVERFLOW_PHRASES = listOf(
            "context length",             // This model's maximum context length is 65536 tokens
            "context_length_exceeded",
            "maximum context",
            "max context",
            "context window",
            "reduce the length",          // Please reduce the length of the messages
            "maximum number of tokens",
            "input is too long",
            "prompt is too long",
            // ⚠️ 这里刻意**不收** `exceed` / `token limit` 这类宽词：
            // 「rate limit exceeded」「exceeded your current quota」是**限流/欠费**，
            // 误判成超长会去缩窗口（还会把这个错误的窗口记下来），属于帮倒忙。
            "超过最大长度",
            "上下文长度",
            "请求过长",
        )

        /**
         * 上下文超长的统一提示。
         *
         * ⚠️ 用户看到它时，说明**自动缩窗口重试也没成功**（见 `AiChatViewModel.send`，
         * 会先按实证值收缩窗口重试 1~2 次）。所以措辞不能停在"太长了"——
         * 必须给出下一步动作，否则用户只能干瞪眼。
         */
        const val CONTEXT_OVERFLOW_HINT =
            "这段对话已经超过该模型能接受的长度（模型上限比预想的小）。请点右上角「新对话」继续问，" +
                "或换一个上下文更长的模型。"

        /**
         * 把「配置 + 消息 + 工具」组装成请求体。
         *
         * 单独抽成 public 函数的唯一目的：单测能**不联网、不起 OkHttp** 直接断言序列化出来的 JSON
         * （尤其是 `thinking` 到底发不发、`reasoning_content` 会不会被误发回去）。
         * 生产路径 [complete] 走的就是这个函数 —— 不存在「测试测一份、线上跑另一份」。
         *
         * ### `thinking` 什么时候发（这是刻意的决定，别顺手改成「不思考就不发」）
         * **永远显式下发**：开=`{"type":"enabled"}`、关=`{"type":"disabled"}`，两个取值都在目标端点实测生效。
         *
         * 为什么不选「关的时候省略该字段」：省略 = 把结果交给服务端默认值，而默认值不由我们控制。
         * 万一某模型默认就开思考，用户明明关了开关却照样被收两倍 token（实测 24→6，正好差一倍），
         * 这种「UI 说关了、后台还在思考」的静默失效最难排查。显式下发才能让开关语义与界面一致。
         * 代价：个别第三方 OpenAI 兼容端点不认这个字段会 400 —— 已由 [httpMessage] 单独识别并给人话提示。
         *
         * ### `reasoning_content` 一定剥掉
         * 它是**出参**：DeepSeek 系端点如果在输入消息里带上它，会直接 400。
         * 而 [AiAgentLoop] 会把上一轮的 assistant 消息（含该字段）原样塞回 messages 再发下一轮，
         * 所以这里必须统一剥掉 —— **这是唯一的防线**，删掉就会在多轮工具调用时随机 400。
         *
         * ### [includeThinking] 什么时候是 false（支持第三方端点的关键）
         * `thinking` 是本 App 主动加的字段，**不是 OpenAI 协议的一部分**——豆包、千问等
         * 第三方兼容端点大多不认它，会直接 400。所以：
         * 已知不接受的地址（能力缓存命中）直接不发；第一次遇到时由 [LlmClient.complete]
         * 自动去掉该字段重试一次，并把结果记进能力缓存。
         */
        fun buildChatRequest(
            cfg: LlmConfig,
            messages: List<ChatMessage>,
            tools: List<ToolSpec>,
            includeThinking: Boolean = true,
            /**
             * 是否走流式（`stream:true`）。见 [LlmClient.completeStreaming]。
             * 默认 false = 保持改造前的行为，任何老调用点不传也不会变。
             */
            stream: Boolean = false,
            /**
             * 流式时是否向服务端要 `usage`。只有走流式才轮到它生效。
             * 置 false 的**唯一**场景：「这个地址已被确认不认 `stream_options`」（能力缓存命中）。
             */
            includeStreamOptions: Boolean = true,
        ): ChatRequest {
            // 没有任何工具时不要发 tools / tool_choice：部分兼容服务端会因空数组直接 400。
            val hasTools = tools.isNotEmpty()
            return ChatRequest(
                model = cfg.model.trim(),
                messages = messages.map { m ->
                    if (m.reasoningContent == null) m else m.copy(reasoningContent = null)
                },
                tools = if (hasTools) tools else null,
                toolChoice = if (hasTools) "auto" else null,
                temperature = 0.0, // 派单问答要的是稳定复现，不是创意
                stream = stream,
                // 非流式**绝不**下发它：自选字段多一个就多一分被端点 400 的风险，
                // 而它在非流式下毫无用处（非流式的 usage 本来就在响应体里）。
                streamOptions = if (stream && includeStreamOptions) StreamOptions() else null,
                thinking = if (includeThinking) ThinkingSpec.of(cfg.thinkingLevel.enabled) else null,
                // 关思考时不发 effort（发了也没意义，而且多一个字段多一分被端点拒绝的风险）
                reasoningEffort = if (includeThinking) cfg.thinkingLevel.effort else null,
            )
        }

        /**
         * 拉取可用模型列表：`GET {baseUrl}/models`（OpenAI 兼容端点几乎都有这个探针）。
         *
         * 用途：设置页的「拉取模型列表」按钮——用户不必猜模型名（`deepseek-chat` 这种猜错的默认值
         * 会一路 400/404，实测就是靠这个接口才发现可用的是 `deepseek-flash`）。
         *
         * 与 [LlmClient.complete] 同样的原则：**不抛异常**（协程取消除外）、错误转人话、
         * 走独立 OkHttp 实例、绝不打日志（请求头里有用户的 key）。
         * 而且**任何失败都只是「这一个便利功能不可用」**：模型名本来就能手输，
         * 所以每条失败提示都带上「可以直接手动输入模型名」，页面不会因此崩或卡死。
         */
        suspend fun listModels(
            baseUrl: String,
            apiKey: String,
            client: OkHttpClient = defaultClient(),
        ): ModelListResult {
            if (apiKey.isBlank()) {
                return ModelListResult.Failure("请先填写 API Key，再拉取模型列表")
            }
            val url = modelsEndpoint(baseUrl)
            if (!url.startsWith("http://") && !url.startsWith("https://")) {
                return ModelListResult.Failure("Base URL 要以 http:// 或 https:// 开头（当前：$baseUrl）")
            }
            val request = Request.Builder()
                .url(url)
                .header("Authorization", "Bearer " + apiKey.trim())
                .header("Accept", "application/json")
                .get()
                .build()

            return withContext(Dispatchers.IO) {
                val call = client.newCall(request)
                val cancelHandle = this.coroutineContext[Job]?.invokeOnCompletion { cause ->
                    if (cause != null) call.cancel()
                }
                try {
                    call.execute().use { resp ->
                        val text = try {
                            resp.body?.string().orEmpty()
                        } catch (e: IOException) {
                            return@use ModelListResult.Failure("读取模型列表失败：" + (e.message ?: "连接中断"))
                        }
                        if (!resp.isSuccessful) {
                            return@use ModelListResult.Failure(
                                modelsHttpMessage(resp.code),
                                scrub(truncate(text), apiKey),
                            )
                        }
                        parseModelList(text, apiKey)
                    }
                } catch (e: SocketTimeoutException) {
                    ModelListResult.Failure("拉取模型列表超时（检查网络 / Base URL）；也可以直接手动输入模型名")
                } catch (e: IOException) {
                    if (call.isCanceled()) throw kotlinx.coroutines.CancellationException("拉取模型列表已取消")
                    ModelListResult.Failure(
                        "无法连接模型服务（检查网络 / Base URL）；也可以直接手动输入模型名",
                        scrub(truncate(e.message), apiKey),
                    )
                } catch (e: kotlinx.coroutines.CancellationException) {
                    throw e
                } catch (e: Exception) {
                    ModelListResult.Failure(
                        "拉取模型列表出错：" + (e.message ?: e.javaClass.simpleName) + "；也可以直接手动输入模型名",
                        scrub(truncate(e.message), apiKey),
                    )
                } finally {
                    cancelHandle?.dispose()
                }
            }
        }

        /**
         * `/models` 端点归一化：容忍手输的 `…/v1`、末尾斜杠、甚至把 `…/chat/completions` 整条粘进来。
         * 与 [LlmConfig.endpoint] 同一套容忍策略。
         */
        fun modelsEndpoint(baseUrl: String): String {
            var b = baseUrl.trim().trimEnd('/')
            if (b.endsWith("/chat/completions")) b = b.removeSuffix("/chat/completions").trimEnd('/')
            return b + "/models"
        }

        /** 解析 `/models` 返回体：优先 `data[].id`（OpenAI 标准），退回 `models[].name/id`（Ollama 风格）。 */
        private fun parseModelList(text: String, apiKey: String): ModelListResult {
            if (text.isBlank()) {
                return ModelListResult.Failure("模型列表接口返回了空响应；可以直接手动输入模型名")
            }
            val parsed = try {
                ApiClient.json.decodeFromString(ModelListResponse.serializer(), text)
            } catch (e: Exception) {
                // 常见于 Base URL 指到了网页/网关（返回 HTML），或该端点没有这个接口
                return ModelListResult.Failure(
                    "该端点的 /models 返回内容无法解析（可能不是 OpenAI 兼容接口）；可以直接手动输入模型名",
                    scrub(truncate(text), apiKey),
                )
            }
            val ids = (parsed.data.map { it.id } + parsed.models.map { it.id.ifBlank { it.name } })
                .map { it.trim() }
                .filter { it.isNotEmpty() }
                .distinct()
            if (ids.isEmpty()) {
                return ModelListResult.Failure(
                    "该端点没有返回任何模型（/models 可用但列表为空）；可以直接手动输入模型名",
                    scrub(truncate(text), apiKey),
                )
            }
            return ModelListResult.Success(ids)
        }

        /** `/models` 的失败提示：与 [LlmClient.httpMessage] 同风格，但每条都带「可手动输入」的退路。 */
        private fun modelsHttpMessage(code: Int): String = when (code) {
            401 -> "API Key 无效或已过期，请检查后重试；也可以直接手动输入模型名"
            403 -> "API Key 无权访问该端点；可以直接手动输入模型名"
            404, 405, 501 -> "该端点不支持列模型（HTTP $code）；可以直接手动输入模型名"
            400, 422 -> "该端点不接受列模型请求（HTTP $code）；可以直接手动输入模型名"
            408 -> "模型服务响应超时；也可以直接手动输入模型名"
            429 -> "调用过于频繁或余额不足，稍后再试；也可以直接手动输入模型名"
            in 500..599 -> "模型服务暂时不可用（$code），稍后再试；也可以直接手动输入模型名"
            else -> "拉取模型列表失败（HTTP $code）；可以直接手动输入模型名"
        }

        /** 独立实例：无日志拦截器、无重试、超时给足。 */
        fun defaultClient(): OkHttpClient = OkHttpClient.Builder()
            .connectTimeout(20, TimeUnit.SECONDS)
            .readTimeout(120, TimeUnit.SECONDS)   // LLM 很慢，读超时必须给足
            .writeTimeout(30, TimeUnit.SECONDS)
            .callTimeout(180, TimeUnit.SECONDS)
            .retryOnConnectionFailure(false)      // 失败就失败，不偷偷重发（避免重复计费）
            .build()

        /** 原始错误体截断到 300 字，够排障又不至于刷屏。 */
        fun truncate(s: String?, max: Int = 300): String? {
            val t = s?.trim().orEmpty()
            if (t.isEmpty()) return null
            return if (t.length <= max) t else t.take(max) + "…(已截断)"
        }

        /** 兜底：万一错误体里回显了 key，替换掉再展示。 */
        fun scrub(raw: String?, apiKey: String): String? {
            if (raw.isNullOrBlank()) return null
            val k = apiKey.trim()
            return if (k.length >= 8 && raw.contains(k)) raw.replace(k, "***") else raw
        }
    }
}
