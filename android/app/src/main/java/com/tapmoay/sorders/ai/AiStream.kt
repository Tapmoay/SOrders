package com.tapmoay.sorders.ai

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json

// ============================================================================
//  流式响应（SSE）的协议数据类
//  字段名严格按 OpenAI Chat Completions 的 streaming 协议，服务端才认。
// ============================================================================

/**
 * 流式请求的附加选项：`{"stream_options":{"include_usage":true}}`。
 *
 * ### 为什么必须显式要它（这一条决定了"上下文预算"还能不能work）
 * 开了流以后，**绝大多数端点默认不回 `usage`**（DeepSeek 实测如此）。而本项目的
 * 上下文预算是建立在**服务端真实回报的 `prompt_tokens`** 上的（见 [AiContext] 的类注释：
 * "估偏 20% 就会让『到 40% 触发』变成随机事件"）。拿不到 usage，40% 自动压缩就退化成瞎猜。
 * 所以要显式要。
 *
 * ### 代价与兜底
 * `stream_options` **不是所有兼容端点都认**的自选字段（和 `thinking` 是同一类风险）。
 * 不认的端点会 400，这时由 [LlmClient.completeStreaming] **自动去掉它重试一次**，
 * 并把结果记进能力缓存（[AiKeyStore.markStreamOptionsUnsupported]）——
 * 与 `thinking` 的处理方式完全对称，见 [LlmClient.buildChatRequest] 的注释。
 */
@Serializable
data class StreamOptions(
    @SerialName("include_usage") val includeUsage: Boolean = true,
)

/**
 * 一个 SSE 分片（`data: {...}` 里的那个对象）。
 *
 * 与**非流式**的 [ChatResponse] 是两套结构，别混用：
 * 非流式把整条消息放在 `choices[0].message`，流式放在 `choices[0].delta` 且**每个分片只是一个增量**。
 */
@Serializable
data class ChatStreamChunk(
    val choices: List<StreamChoice> = emptyList(),
    /** 只有在请求里带了 [StreamOptions] 且端点支持时，**最后一个分片**才会带它。 */
    val usage: Usage? = null,
    /** 端点把错误塞在 200 的流里（少见但存在）。 */
    val error: ErrorBody? = null,
)

@Serializable
data class StreamChoice(
    val delta: StreamDelta = StreamDelta(),
    @SerialName("finish_reason") val finishReason: String? = null,
)

/**
 * 增量内容。四个字段都可能缺：
 * - `content`：正文增量（**最常出现的那个**）
 * - `reasoning_content`：思考过程增量（开思考时才有）
 * - `tool_calls`：工具调用的**分片**（见 [StreamToolCall]）
 * - `role`：只在第一个分片出现一次，可以忽略
 */
@Serializable
data class StreamDelta(
    val role: String? = null,
    val content: String? = null,
    @SerialName("reasoning_content") val reasoningContent: String? = null,
    @SerialName("tool_calls") val toolCalls: List<StreamToolCall>? = null,
)

/**
 * 工具调用的一个分片。
 *
 * ### 这是流式里最容易写错的地方
 * 非流式下 `tool_calls` 一次性给全（`id` + `function.name` + `function.arguments` 都是完整的）。
 * 流式下它被**按 `index` 切成很多片**：
 * - `index` 标识"这是第几个工具调用"，**同一个 index 的分片要拼起来**；
 * - `id` / `function.name` 通常只在**该 index 的第一个分片**出现；
 * - `function.arguments` 是**一段一段**来的，必须按顺序**字符串拼接**（不能覆盖）。
 *
 * 漏掉 `index` 归并，多个工具调用会互相覆盖——表现为"模型明明调了 3 个工具，只执行了 1 个"。
 */
@Serializable
data class StreamToolCall(
    /** 第几个工具调用（从 0 开始）。缺省 0 是为了兼容不发 index 的端点。 */
    val index: Int = 0,
    val id: String? = null,
    val type: String? = null,
    val function: StreamFunction? = null,
)

@Serializable
data class StreamFunction(
    val name: String? = null,
    val arguments: String? = null,
)

// ============================================================================
//  流式正文的「净化 + 增量交付」
// ============================================================================

/**
 * 把流式增量**先净化再交付**给聊天页。
 *
 * ### 为什么不能直接"来一片净化一片"
 * [AiAnswerSanitizer] 的判据是**成对**的（`user_id` + 数字、`货主#` + 数字）。
 * 而分片边界是服务端按 token 切的，**正好切在短语中间**是必然会发生的事：
 * ```
 * 分片1 = "（user_id 1"   → 单独净化：无数字紧跟，匹配不上 → 原样吐出去
 * 分片2 = "22）"          → 单独净化：匹配不上 → 原样吐出去
 * 合起来 = "（user_id 122）"  ← 编号就这么漏到屏幕上了
 * ```
 * 所以这里**留一段尾巴不发**（[HOLD_BACK_CHARS]）：只把"确定已经完整"的部分净化后交出去。
 * 短语长度是有界的（`arrears_unit_id 123456` 也就 20 出头），留 24 个字足够把它整个罩住。
 *
 * ### 为什么还要 [Emission.replace]
 * hold-back 只能让"跨边界"变得**极少**，不能让它**不可能**：万一真有一条超长编号
 * 跨越了边界，等它完整时我们才发现前面吐出去的半截是错的。这时唯一正确的做法是
 * **让聊天页把整段换掉**，而不是继续往后追加。
 *
 * ### 它不管"最终保存什么"
 * 最终落盘/展示的文本由 `AiRunResult.Success.text` 负责（聊天页在收到 Success 时
 * **整条覆写**气泡，见 `AiChatViewModel.send` 的注释）。本类只负责"过程里别让不该出现的东西闪现"——
 * 没有它，模型若写了编号，用户会看到它冒出来、几秒后又消失，像是个 bug。
 */
class AiStreamingText(
    /** 留多少字符不发（用来罩住可能跨越分片边界的编号短语）。 */
    private val holdBack: Int = HOLD_BACK_CHARS,
    /** 净化函数（默认真净化器；单测里可以塞一个假的来单独验证交付逻辑）。 */
    private val sanitize: (String) -> String = AiAnswerSanitizer::clean,
) {

    /**
     * 一次交付。
     *
     * @param replace true = 这批内容**取代**聊天页上已有的正文（而不是追加）。
     */
    data class Emission(val text: String, val replace: Boolean)

    private val raw = StringBuilder()

    /** 截至当前**已经交给聊天页**的净化后文本。 */
    private var emitted: String = ""

    /** 追加一个原始增量；返回本次需要交付的内容（null = 本次无需交付）。 */
    fun append(delta: String): Emission? {
        if (delta.isEmpty()) return null
        raw.append(delta)
        return emit(final = false)
    }

    /** 流结束：把留着的尾巴也交出去。返回 null 表示没有新增内容。 */
    fun finish(): Emission? = emit(final = true)

    /** 已经交付出去的净化后全文（供调用方兜底取用）。 */
    fun settledText(): String = emitted

    /** 原始（未净化）全文——**只用于排障计数，不要拿去展示**。 */
    fun rawLength(): Int = raw.length

    private fun emit(final: Boolean): Emission? {
        val safeLen = if (final) raw.length else (raw.length - holdBack).coerceAtLeast(0)
        if (safeLen <= 0) return null

        val sanitized = sanitize(raw.substring(0, safeLen))
        if (sanitized == emitted) return null

        // 正常路径：多出来的部分直接追加
        if (sanitized.startsWith(emitted)) {
            val add = sanitized.substring(emitted.length)
            emitted = sanitized
            return add.takeIf { it.isNotEmpty() }?.let { Emission(it, replace = false) }
        }

        // 异常路径：净化**改动/删除了已经交出去的内容**（短语跨了 hold-back 边界）。
        // 只能整段替换——继续追加会让屏幕上留着那半截编号。
        emitted = sanitized
        return Emission(sanitized, replace = true)
    }

    companion object {
        /**
         * 留尾长度。
         *
         * 取值依据：净化器要罩住的最长短语是「前缀词 + `_id` + 连接符 + 数字」，
         * 前缀词最长的是 `arrears_unit_id`（15）+ 连接符与空格（约 3），
         * 数字再长也不会被当成编号（净化器要求它紧跟关键词）。
         * 24 覆盖得住，而且**对观感几乎无影响**——24 个字在流式下不到一帧的时间。
         */
        const val HOLD_BACK_CHARS = 24
    }
}


// ============================================================================
//  增量累加器（**纯逻辑，无 Android / 网络依赖，可直接 JVM 单测**）
// ============================================================================

/**
 * 把一串 SSE 分片累加成一条完整的 [ChatMessage]。
 *
 * ### 为什么单独抽出来（而不是写在 [LlmClient] 的读循环里）
 * 流式解析是本功能里**最容易错、又最难手工测**的一环：
 * 它只在"用户正好在聊天"时跑，出错的表现是"回答缺字/工具少执行了一个"，
 * 而不是报错——手工测很难覆盖"分片正好切在 JSON 中间"这类情况。
 * 抽成纯类以后，可以拿**构造的分片序列**（含各种切法）直接单测，不用联网。
 *
 * ### 三个必须做对的事
 * 1. **工具调用按 `index` 归并**，`arguments` 按顺序拼接（见 [StreamToolCall] 的注释）；
 * 2. **正文增量要合并**：一个 token 一个分片，逐片刷 UI 会让 Compose 疯狂重组，
 *    所以攒到一定量或过了一定时间才交出去（见 [pendingForFlush]）；
 * 3. **思考过程不逐片交出去**：聊天页把思考按"轮"追加并加分隔线，
 *    逐片发会变成几百条分隔线。所以这里只累加，整轮结束时一次性给（与改造前行为一致）。
 */
class ChatStreamAccumulator(
    /** 两次提交之间至少间隔这么多毫秒（攒一批再刷 UI）。 */
    private val flushIntervalMs: Long = FLUSH_INTERVAL_MS,
    /** 攒够这么多字符就立刻提交（回答很快时不必等时间）。 */
    private val flushChars: Int = FLUSH_CHARS,
) {

    /** 完整正文。 */
    private val content = StringBuilder()

    /** 完整思考过程（**不逐片外发**，见类注释第 3 条）。 */
    private val reasoning = StringBuilder()

    /** 待提交的正文增量。 */
    private val pending = StringBuilder()

    /** 工具调用分片，按 `index` 归并。用有序 Map 保证执行顺序与模型给出的一致。 */
    private val toolCalls = sortedMapOf<Int, ToolCallBuilder>()

    /** 端点若把错误塞在流里，记下来。 */
    var streamError: ErrorBody? = null
        private set

    /** 最后一个分片带的 finish_reason（`stop` / `tool_calls` / `length`）。 */
    var finishReason: String? = null
        private set

    /** 服务端真实回报的用量（只有要了 [StreamOptions.includeUsage] 且端点支持时才有）。 */
    var usage: Usage? = null
        private set

    /** 是否真的收到过 SSE 数据行（用于"端点其实没走流式"的兜底，见 [LlmClient.completeStreaming]）。 */
    var sawSseData: Boolean = false
        private set

    /** 是否已经读到 `[DONE]` 哨兵。 */
    var done: Boolean = false
        private set

    /** 原始响应体（兜底解析用：万一端点无视 `stream:true` 直接回了普通 JSON）。 */
    val raw = StringBuilder()

    private var lastFlushMs = 0L

    /**
     * 喂一行（SSE 是**逐行**的协议，所以按行处理；调用方负责按行切）。
     *
     * 只认 `data:` 行，其余（`event:` / `id:` / `:` 注释 / 空行）一律忽略——
     * 本功能不需要 SSE 的事件类型与重连语义。
     *
     * @return 是否还应继续读（false = 读到 `[DONE]`，可以收工了）
     */
    fun feed(line: String, nowMs: Long = now()): Boolean {
        val trimmed = line.trim()
        raw.append(line).append('\n')
        if (trimmed.isEmpty()) return true
        if (!trimmed.startsWith(DATA_PREFIX)) return true

        val payload = trimmed.removePrefix(DATA_PREFIX).trim()
        if (payload.isEmpty()) return true
        if (payload == DONE_SENTINEL) {
            done = true
            return false
        }

        sawSseData = true
        val chunk = try {
            STREAM_JSON.decodeFromString(ChatStreamChunk.serializer(), payload)
        } catch (e: Exception) {
            // 单个分片解析失败**不能中断整个回答**：丢掉这一片，后面还会来。
            // （整段全是坏的时候，最终 content 为空，由调用方转成"没有返回内容"的失败。）
            return true
        }

        chunk.error?.let { streamError = it }
        chunk.usage?.let { usage = it }

        val choice = chunk.choices.firstOrNull() ?: return true
        choice.finishReason?.let { finishReason = it }

        choice.delta.content?.takeIf { it.isNotEmpty() }?.let {
            content.append(it)
            pending.append(it)
        }
        choice.delta.reasoningContent?.takeIf { it.isNotEmpty() }?.let {
            reasoning.append(it)
        }
        choice.delta.toolCalls?.forEach { frag ->
            toolCalls.getOrPut(frag.index) { ToolCallBuilder() }.merge(frag)
        }

        // 时间到了就标记一次（真正的提交由 pendingForFlush 取走）
        if (pending.isNotEmpty() && pending.length >= flushChars) lastFlushMs = nowMs
        return true
    }

    /**
     * 取走**该提交的**正文增量；没到时候就返回空串。
     *
     * 判据：攒够 [flushChars] 个字符，**或**距上次提交已过 [flushIntervalMs] 毫秒。
     * 两个条件缺一不可——
     * - 只看时间：模型一秒吐 200 字时会刷 25 次，UI 卡；
     * - 只看字符：模型慢慢吐时用户要盯着空白等很久，流式就白做了。
     *
     * 为什么这里返回字符串而不是回调：调用方需要**在它自己的协程上下文里**把增量交给 UI
     * （本 App 的事件回调约定在 Main 线程，见 [AiAgentLoop.run] 的注释），
     * 而本类是纯逻辑、不该知道调度器。
     */
    fun pendingForFlush(nowMs: Long = now()): String {
        if (pending.isEmpty()) return ""
        val due = pending.length >= flushChars || (nowMs - lastFlushMs) >= flushIntervalMs
        if (!due) return ""
        return drainPending(nowMs)
    }

    /** 无条件取走全部待提交增量（流结束时、或要执行工具前必须调一次）。 */
    fun drainAll(nowMs: Long = now()): String = drainPending(nowMs)

    private fun drainPending(nowMs: Long): String {
        if (pending.isEmpty()) return ""
        val out = pending.toString()
        pending.setLength(0)
        lastFlushMs = nowMs
        return out
    }

    /** 完整思考过程（可能为空）。 */
    fun reasoningText(): String = reasoning.toString()

    /** 已累计的完整正文（含尚未提交的部分）。 */
    fun contentText(): String = content.toString()

    /**
     * 拼成一条 assistant 消息。
     *
     * `content` 为空白时给 `null` 而不是空串——只调工具的那一轮本来就没有正文，
     * 而部分端点对"空串 content + tool_calls"会挑剔（协议里 content 应当缺省）。
     */
    fun toMessage(): ChatMessage {
        val calls = toolCalls.values.mapNotNull { it.build() }.takeIf { it.isNotEmpty() }
        return ChatMessage(
            role = "assistant",
            content = content.toString().takeIf { it.isNotBlank() },
            toolCalls = calls,
            // 思考过程**带回去**给聊天页展示（它同时是"这一轮的 reasoning"）。
            // ⚠️ 它绝不会被发回服务端——buildChatRequest 会统一剥掉（那是唯一的防线）。
            reasoningContent = reasoning.toString().takeIf { it.isNotBlank() },
        )
    }

    // ---------------------------------------------------------------- 内部

    /** 工具调用的**拼接中**状态（分片会一片片 merge 进来）。 */
    private class ToolCallBuilder {
        var id: String = ""
        var type: String = "function"
        val name = StringBuilder()
        val args = StringBuilder()

        fun merge(frag: StreamToolCall) {
            frag.id?.takeIf { it.isNotEmpty() }?.let { id = it }
            frag.type?.takeIf { it.isNotEmpty() }?.let { type = it }
            frag.function?.let { f ->
                // 名字按协议只在首个分片出现一次，但确有端点把它切碎发。
                // 判据：已有名字且新片段是它的**后缀**（重复下发）→ 忽略；否则按追加。
                f.name?.takeIf { it.isNotEmpty() }?.let { n ->
                    if (!name.endsWith(n)) name.append(n)
                }
                // arguments 是真正需要一片片拼的东西——**绝不能覆盖**。
                f.arguments?.takeIf { it.isNotEmpty() }?.let { args.append(it) }
            }
        }

        /** 名字和参数都没拿到（纯占位分片）时返回 null，避免往下游传一个空工具调用。 */
        fun build(): ToolCall? {
            if (name.isEmpty() && args.isEmpty() && id.isEmpty()) return null
            return ToolCall(
                // 个别兼容端点不发 id：补一个稳定的，否则后面的 tool 消息无法配对
                // （AiAgentLoop 里还有一层同样的兜底，两处都留着——这是会直接 400 的坑）。
                id = id.ifEmpty { "call_stream_" + name },
                type = type,
                function = FunctionCall(name = name.toString(), arguments = args.toString()),
            )
        }
    }

    internal companion object {
        /** SSE 的字段前缀（**注意冒号后有空格**，但也有端点不发空格，所以比对时 trim）。 */
        private const val DATA_PREFIX = "data:"

        /** 流结束哨兵。 */
        private const val DONE_SENTINEL = "[DONE]"

        /** 攒够这么多字符就提交一次。 */
        internal const val FLUSH_CHARS = 24

        /** 两次提交至少隔这么久。 */
        internal const val FLUSH_INTERVAL_MS = 40L

        /**
         * 本文件自带的 Json 实例，**刻意不用 `ApiClient.json`**：
         * 这样这个类在纯 JVM 单测里能直接用，不必拉起 Android 的运行环境
         * （同 [AiJson] 的做法）。配置对齐 ApiClient：容忍未知字段。
         */
        private val STREAM_JSON = Json {
            ignoreUnknownKeys = true
            isLenient = true
            explicitNulls = false
        }

        private fun now(): Long = System.nanoTime() / 1_000_000L
    }
}
