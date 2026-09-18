package com.tapmoay.sorders.ai

/**
 * 上下文压缩：把**较早的对话**压成一段摘要，腾出窗口给新的对话。
 *
 * ### 为什么用"模型自己摘要"而不是"直接丢掉最早的几条"
 * 多轮对话里，用户前面说过的**筛选条件**（哪个货主、哪个时间段、排除了什么）
 * 恰恰是最需要留住的东西——直接丢掉，模型就会在后面几轮里"忘掉条件"重新问一遍，
 * 用户会觉得"它怎么又忘了"。
 *
 * 摘要保留的正是这类信息。丢掉只在**摘要本身失败**时才作为兜底（见 [AiCompactor.compact]）。
 *
 * ### 为什么压缩是"安全"的
 * 压缩后的历史只保留 user / 纯文本 assistant（见 [AiContext.KEEP_RECENT_MESSAGES] 的说明）：
 * 工具往返（`assistant(tool_calls)` + `tool`）必须成对出现，从中间切开会让服务端 400，
 * 而它们在下一轮本来就会被重新查一遍，丢掉不影响正确性。
 */
class AiCompactor(private val transport: LlmTransport) {

    /** 压缩结果：摘要 + 保留的最近消息。 */
    data class Result(
        val summary: String,
        /** true = 模型摘要失败，退化成"丢弃最早的"（界面要如实告诉用户）。 */
        val degraded: Boolean,
        /** 参与压缩的历史条数。 */
        val compactedCount: Int,
    )

    /**
     * 压缩 [history]：较早的部分交给模型摘要，最近的 [keepRecent] 条原样保留。
     *
     * 全程不抛异常（协程取消除外）：压缩失败也必须让用户能继续问，
     * 大不了这一次少带点上下文。
     */
    suspend fun compact(
        cfg: LlmConfig,
        history: List<ChatMessage>,
        keepRecent: Int = AiContext.KEEP_RECENT_MESSAGES,
    ): Result? {
        // 只保留能安全送回去的两类消息（见类注释）
        val safe = history.filter { m ->
            when (m.role) {
                "user" -> !m.content.isNullOrBlank()
                "assistant" -> m.toolCalls.isNullOrEmpty() && !m.content.isNullOrBlank()
                else -> false
            }
        }
        if (safe.size <= keepRecent + 1) return null // 本来就没什么可压的

        val older = safe.dropLast(keepRecent)
        val recent = safe.takeLast(keepRecent)
        val summary = try {
            summarize(cfg, older)
        } catch (e: kotlinx.coroutines.CancellationException) {
            throw e
        } catch (e: Exception) {
            null
        }
        if (summary.isNullOrBlank()) {
            // 兜底：摘要不了就只留最近几条，并**如实标注**（界面据此提示用户）
            return Result(summary = FALLBACK_NOTE, degraded = true, compactedCount = older.size)
        }
        return Result(summary = summary.trim(), degraded = false, compactedCount = older.size)
    }

    /**
     * 让模型把这几条消息压成要点。
     *
     * 提示词里三条硬约束：
     * 1. **不许编造**——摘要被当成事实喂回给模型，编造会被二次放大；
     * 2. **必须留住筛选条件**（货主/司机/时间范围/口径）——这正是压缩要保住的东西；
     * 3. **不要评论、不要客套**——省 token 是压缩的初衷。
     */
    private suspend fun summarize(cfg: LlmConfig, older: List<ChatMessage>): String? {
        val body = older.joinToString("\n") { m ->
            val who = if (m.role == "user") "用户" else "助手"
            "$who：${m.content.orEmpty().trim()}"
        }
        val request = listOf(
            ChatMessage.system(
                "你是对话压缩器。把给定对话压缩成要点，供后续轮次继续使用。",
            ),
            ChatMessage.user(
                buildString {
                    appendLine("把下面这段对话压缩成不超过 150 字的要点。必须做到：")
                    appendLine("1. 只写对话里**确实出现过**的信息，一个数字都不要编；")
                    appendLine("2. **必须原样留住**这几类（有就写，没有就跳过）：")
                    appendLine("   - 筛选条件：涉及的货主/司机/商品名、时间范围、统计口径、排除项；")
                    appendLine("   - 用户的偏好与长期要求（例如「以后都按这个口径」「不要写客套话」）——")
                    appendLine("     这类要求一旦丢掉，后面每一轮都会违背它，而用户不会每次都重申；")
                    appendLine("   - 关键实体：出现过的店名/人名/商品名/单号，**照抄原名**，不要改写也不要简称；")
                    appendLine("3. 保留已经得出的结论数字；没得出结论就写「尚无结论」；")
                    appendLine("4. 不要客套、不要评价、不要 Markdown 表格，直接给要点，可以用「；」分隔。")
                    appendLine()
                    appendLine("对话：")
                    append(body)
                },
            ),
        )
        return when (
            // 摘要不需要思考：给它关掉，省一轮 token、也快一点。
            // 压缩本身就是"为了省 token"，用最高强度去压缩是自相矛盾的。
            val r = transport.complete(cfg.copy(thinkingLevel = ThinkingLevel.OFF), request, emptyList())
        ) {
            is ChatResult.Success -> r.message.content?.trim()
            is ChatResult.Failure -> null
        }
    }

    companion object {
        /** 摘要失败时的占位说明。**必须如实说明"更早的内容已不可用"**，不能让用户以为上下文还在。 */
        const val FALLBACK_NOTE =
            "（更早的对话因过长已被省略，且本次未能生成摘要；如需旧信息请重新说明一次。）"

        /** 摘要注入 system prompt 时的标题。 */
        const val SUMMARY_TITLE = "【早前对话摘要】"
    }
}
