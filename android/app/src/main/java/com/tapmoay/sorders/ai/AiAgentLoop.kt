package com.tapmoay.sorders.ai

import com.tapmoay.sorders.core.ApiClient
import kotlinx.coroutines.CancellationException
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import java.time.LocalDate

/**
 * agent 循环对外抛的事件。
 *
 * [TextDelta] **从 v3.5 起是连续的增量**（见其自身注释）：回答边生成边显示，
 * 而不是等整轮生成完再一次性给出。聊天页对这个变化**无需改动**——
 * 它一直是按「追加」实现的，当初就是为流式留的口子。
 */
sealed interface AiEvent {
    /** 开始执行某个工具。argsSummary 是给界面看的一行摘要（已截断）。 */
    data class ToolStarted(val name: String, val argsSummary: String) : AiEvent

    /** 工具执行结束。ok=false 表示工具返回了 {"error": ...}。 */
    data class ToolFinished(val name: String, val ok: Boolean, val summary: String) : AiEvent

    /**
     * 模型给出的正文。
     *
     * ### 从「一次性全量」改成「可连续追加」（v3.5 流式）
     * 改造前这个事件**每一轮最多来一次**，且带的是全量文本；现在它会**连续触发**，
     * 每次带一小段增量，聊天页负责追加。这个改动聊天页**一行都不用改**——
     * 它本来就是按追加实现的（见 `AiChatViewModel.onAiEvent`），当初就是为流式留的口子。
     *
     * @param replace true = 这批内容**取代**聊天页上已有的正文，而不是追加。
     *   两个地方会用到它：
     *   ① 流式过程中净化器发现先前吐出去的半截内容里含编号短语（短语跨了分片边界），
     *      必须整段换掉（见 [AiStreamingText]）；
     *   ② 最终答复落定时，用**净化后的权威文本**覆盖掉过程里累积的预览，
     *      保证「屏幕上看到的」和「存进历史的」是同一份。
     */
    data class TextDelta(val text: String, val replace: Boolean = false) : AiEvent

    /**
     * 模型的思考过程（`reasoning_content`）。
     *
     * 只有开启思考模式时服务端才会返回它；关闭时该字段为空、本事件也就不会发出。
     * 界面应当把它**折叠展示**（默认收起）——它是过程不是结论，摊开会淹没答案。
     */
    data class Reasoning(val text: String) : AiEvent

    /** 本次调用的 token 消耗（有的服务端不返回 usage，此时不会发这个事件）。 */
    data class Usage(
        val tokens: Int,
        val promptTokens: Int = 0,
        val completionTokens: Int = 0,
    ) : AiEvent
}

/** 实际发生过的一次工具调用（工具名 + 原始参数 JSON）。用于使用习惯统计与排障。 */
data class ToolCallRecord(val name: String, val arguments: String)

/** agent 循环的最终结果。 */
sealed interface AiRunResult {
    /** 拿到最终答复。[usage] 是**最后一次**调用的用量（多轮时前面几轮的用量通过 AiEvent.Usage 上报）。 */
    data class Success(
        val text: String,
        val steps: Int,
        val usage: Usage?,
        /** 本轮真实调过的工具（用于使用习惯统计）。 */
        val toolCalls: List<ToolCallRecord> = emptyList(),
        /**
         * 这次提问带的图片**没有发出去**（端点不收），已自动按纯文字重试。
         *
         * 界面必须把这件事说出来：模型看到的是一张没图的问题，
         * 它的回答可能像"你没有发图片给我"或者完全答偏——不说的话，
         * 用户会以为"AI 看过我的照片了"。
         */
        val imagesDropped: Boolean = false,
    ) : AiRunResult

    /** 没拿到最终答复：配置缺失 / 模型报错 / 达到步骤上限。userMessage 可直接展示。 */
    data class Failure(
        val userMessage: String,
        val steps: Int,
        val toolCalls: List<ToolCallRecord> = emptyList(),
        /**
         * 失败原因是**对话超过模型能装的长度**。
         * 上层据此**自动缩小窗口重试**（见 `AiChatViewModel.send` 与 [AiContext.shrinkOnOverflow]）——
         * 窗口是按模型名猜的，只有这一次真实报错能纠正它。
         */
        val contextOverflow: Boolean = false,
        /** 报错体里端点**自己写明的上限**（拿得到就把窗口一次改准，见 [AiContext.parseStatedLimit]）。 */
        val contextLimit: Int? = null,
    ) : AiRunResult
}

/**
 * 「派单员 AI 助手」的工具调用循环（function calling agent loop）。
 *
 * 调用方式（聊天页只需要这一句）：
 * ```
 * val loop = aiContainer.agentLoop
 * val job = viewModelScope.launch {
 *     val r = loop.run(userText, history) { ev -> /* 更新 UI 状态 */ }
 * }
 * ```
 * 循环跑在调用方所在的调度器上（内部只有网络那一跳会切到 IO），
 * 所以从 `viewModelScope`（Main）调用时，[AiEvent] 回调也在 Main 线程，可直接写 Compose state。
 *
 * ### 循环逻辑（逐条对应实现，改之前请先读完）
 * 1. 组装 `messages = [system] + 清洗过的 history + [user]`。
 * 2. 调 [LlmTransport.complete]。
 * 3. `message.tool_calls` 为空 → 结束，content 就是最终答复。
 * 4. 否则：**先把 assistant 消息（含 tool_calls）原样加进 messages**（漏掉这步，后面的 tool 消息
 *    就没有归属，服务端一定 400），再逐个执行工具，**每个结果作为 `role="tool"` + `tool_call_id`
 *    的消息加入 messages**，回到第 2 步。
 * 5. **硬上限 [DEFAULT_MAX_STEPS] = 8 轮**。到顶就停，并明确告知用户「已达最大步骤数，未得到最终答复」
 *    ——绝不能假装答完了，也绝不能无限循环烧 key。
 * 6. 每步通过 [onEvent] 上报，聊天页据此显示「正在查 XX…」和工具结果摘要。
 * 7. **取消安全**：全程不吞 [CancellationException]（工具执行与模型调用两处都显式重抛），
 *    用户退出页面 → 协程取消 → HTTP 调用被掐断（见 [LlmClient]）→ 上层 catch 到取消即可。
 *
 * @param transport 模型传输层（生产 = [LlmClient]，测试 = 假实现）。
 * @param tools 可调用的工具集（生产 = [AiTools]）。
 * @param configProvider 每次 run 时读取最新配置（用户在设置页改了 key 立刻生效）。
 * @param maxSteps 最大步骤数（=最多几次模型调用），默认 8。
 */
class AiAgentLoop(
    private val transport: LlmTransport,
    private val tools: AiToolset,
    private val configProvider: () -> LlmConfig?,
    private val maxSteps: Int = DEFAULT_MAX_STEPS,
) {

    suspend fun run(
        userText: String,
        history: List<ChatMessage>,
        /**
         * 追加到 system prompt 后面的额外上下文（**使用习惯**、**早前对话摘要** 等）。
         *
         * 为什么走这个参数而不是塞进 `history`：`history` 里的 `system` 消息会被
         * [sanitizeHistory] 丢掉（身份提示词由本类统一控制），塞进去会静默消失。
         * 传 null 表示什么都不加（老调用方不受影响）。
         */
        systemExtra: String? = null,
        /**
         * 这一轮提问附带的图片（data URL 列表，来自用户挂载的图片）。
         *
         * 只有**用户那条消息**带得上图；工具循环的后续轮次会把这条消息原样重发
         * （多模态协议就是这样），所以图片必须在上传前压到"够看清"的大小。
         */
        images: List<String> = emptyList(),
        onEvent: (AiEvent) -> Unit,
    ): AiRunResult {
        // ---- 0. 配置校验：三种缺失分别给不同提示，让用户知道该去设置页补什么 ----
        val cfg = configProvider()
            ?: return AiRunResult.Failure("还没有配置模型服务，请先到「AI 助手设置」填写 API Key。", 0)
        if (cfg.apiKey.isBlank()) {
            return AiRunResult.Failure("还没有填写 API Key，请先到「AI 助手设置」填写。", 0)
        }
        if (cfg.baseUrl.isBlank() || cfg.model.isBlank()) {
            return AiRunResult.Failure("模型配置不完整（Base URL / 模型名），请到「AI 助手设置」补全。", 0)
        }

        val specs = tools.specs  // 用户关掉的工具不会出现在这里，模型自然就调不到

        // ---- 1. 组装 messages ----
        val messages = ArrayList<ChatMessage>(history.size + 2)
        messages += ChatMessage.system(systemPrompt(specs.map { it.function.name }, systemExtra))
        messages += sanitizeHistory(history)
        messages += ChatMessage.user(userText)
        // 有图时把最后那条用户消息换成"带图版"（content 会在线上变成多模态数组）
        if (images.isNotEmpty()) {
            messages[messages.lastIndex] = ChatMessage.userWithImages(userText, images)
        }

        var steps = 0
        var lastUsage: Usage? = null
        val usedTools = ArrayList<ToolCallRecord>()
        /** 这次提问带的图被端点拒收过（见 [AiRunResult.Success.imagesDropped]）。 */
        var imagesDropped = false
        /**
         * 这一轮里**真的**发出去几张确认卡。只认工具返回里的结构化标记
         * （`status == "awaiting_user_confirmation"`），不认模型说的话——
         * 它说"卡已发"而实际一张没发，真机上已经发生过两次（见 [AiCardClaim]）。
         */
        var cardsOffered = 0
        /** 因为"说了卡却没有卡"而重做的次数（有上限，防止死循环）。 */
        var claimRetries = 0

        while (true) {
            // ---- 5. 硬上限：在发起调用**之前**判断，保证最多 maxSteps 次模型调用 ----
            if (steps >= maxSteps) {
                val msg = "已达到最大步骤数（$maxSteps 步），没有得出最终答复。" +
                    "可以把问题拆小一点再问，或者换个更具体的说法。"
                onEvent(AiEvent.TextDelta(msg))
                return AiRunResult.Failure(msg, steps, usedTools)
            }
            steps++

            // ---- 2. 调模型（流式：正文边生成边交给聊天页）----
            // 每一轮一个净化交付器：一轮 = 一条 assistant 消息，轮与轮之间正文是独立生成的，
            // 净化状态不能串（否则上一轮的留尾会跟这一轮的正文接在一起）。
            val streaming = AiStreamingText()
            // 只在这里出现 try：CancellationException 必须原样抛出，其它异常转成可展示失败，避免崩掉聊天页
            val result = try {
                transport.completeStreaming(cfg, messages, specs) { delta ->
                    streaming.append(delta)?.let { onEvent(AiEvent.TextDelta(it.text, it.replace)) }
                }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                return AiRunResult.Failure("调用模型服务出错：" + (e.message ?: e.javaClass.simpleName), steps, usedTools)
            }
            // 无论成败都先把留尾交出去：否则回答的最后几个字会卡在净化器里，
            // 表现成「话说到一半就断了」。失败时也要交——用户已经看到的半句不该被吞掉。
            streaming.finish()?.let { onEvent(AiEvent.TextDelta(it.text, it.replace)) }

            when (result) {
                is ChatResult.Failure -> return AiRunResult.Failure(
                    result.userMessage,
                    steps,
                    usedTools,
                    contextOverflow = result.contextOverflow,
                    contextLimit = result.contextLimit,
                )

                is ChatResult.Success -> {
                    result.usage?.let { u ->
                        lastUsage = u
                        onEvent(AiEvent.Usage(u.totalTokens, u.promptTokens, u.completionTokens))
                    }
                    // 端点不收图、已经自动去掉图重试过 → 记下来，最终结果里要告诉用户
                    if (result.imagesDropped) imagesDropped = true
                    val message = result.message

                    // ---- 2b. 思考过程：只在服务端返回时上报（关思考时为 null，不会有这个事件）----
                    // 每一轮都可能有：工具轮里的推理对排障有用，所以不只在最终答复时发。
                    // 思考过程也会显示给用户看，所以和答案同样要净化掉内部编号。
                    message.reasoningContent?.trim()?.takeIf { it.isNotEmpty() }?.let {
                        onEvent(AiEvent.Reasoning(AiAnswerSanitizer.clean(it)))
                    }

                    // ---- 3. 没有工具调用 → 这就是最终答复 ----
                    val calls = message.toolCalls.orEmpty()
                    if (calls.isEmpty()) {
                        val raw = message.content?.trim().orEmpty()

                        // ---- 3a. ⛔ 说了「卡已发」却一张都没发 → 不接受这句答复，让它当场重做 ----
                        // 判据是**事实**（cardsOffered），不是话术——提示词已经拦过两次没拦住
                        // （见 [AiCardClaim] 的类注释）。少了这一段，用户会去找一张不存在的卡，
                        // 然后卡死在那里：他不知道该说什么，也不知道其实什么都没发生。
                        if (cardsOffered == 0 &&
                            claimRetries < MAX_CARD_CLAIM_RETRIES &&
                            AiCardClaim.looksLikeClaim(raw)
                        ) {
                            claimRetries++
                            // 先把屏幕上刚流出去的谎话盖掉：不盖的话他会先看到"卡已发"。
                            onEvent(AiEvent.TextDelta(AiCardClaim.CORRECTION, replace = true))
                            messages += ChatMessage.assistant(raw)
                            messages += ChatMessage.user(AiCardClaim.NUDGE)
                            continue
                        }

                        var finalText = AiAnswerSanitizer.clean(
                            raw.ifBlank { "模型没有返回文字内容，请再问一次。" },
                        )
                        // 重做次数用尽还是只有一句"卡已发"：至少别让他干等（如实说明 + 给出下一步）。
                        if (cardsOffered == 0 && AiCardClaim.looksLikeClaim(raw)) {
                            finalText = AiCardClaim.EXHAUSTED
                        }
                        // `replace = true`：用**净化后的权威文本**盖掉过程里累积的预览。
                        // 流式下正文已经一段段显示过了，这里若按追加发，屏幕上会出现
                        // "同一段回答来两遍「。替换还顺带保证了一件事：
                        // 屏幕上的字 = `Success.text` = 落进历史的字，三者永远一致。
                        //
                        // 代价（已知并接受）：中间轮次模型若说过「我先查一下…"这类过渡话，
                        // 会在最终答复落定时被一起盖掉。这些过渡话本就是过程性内容，
                        // 而且旁边的工具痕迹（toolTrace）会完整保留，不影响用户回看发生了什么。
                        onEvent(AiEvent.TextDelta(finalText, replace = true))
                        return AiRunResult.Success(
                            text = finalText,
                            steps = steps,
                            usage = lastUsage,
                            toolCalls = usedTools,
                            // 图片被端点拒收、自动按纯文字重试过 → 界面要如实告诉用户
                            imagesDropped = imagesDropped,
                        )
                    }

                    // ---- 4a. assistant 消息（含 tool_calls）原样加入 ----
                    // 兜底：极少数兼容服务端不带 tool_call.id，这里补一个，否则 tool 消息无法配对
                    val normalized = calls.mapIndexed { i, c ->
                        if (c.id.isBlank()) c.copy(id = "call_" + steps + "_" + i) else c
                    }
                    messages += message.copy(toolCalls = normalized)

                    // ---- 4b. 逐个执行工具，结果作为 role="tool" 加入 ----
                    for (call in normalized) {
                        val fnName = call.function.name.ifBlank { "(未命名工具)" }
                        val argsJson = call.function.arguments
                        usedTools += ToolCallRecord(fnName, argsJson)

                        // ⚠️ 这两行会进聊天页、进无障碍树、还会被存进对话文件：
                        //    控制字符（模型给的参数里带 NUL 是最难查的一种）先在这里剥掉。
                        //    见 [AiAnswerSanitizer.stripControl] 里那段实测记录。
                        onEvent(AiEvent.ToolStarted(fnName, AiAnswerSanitizer.stripControl(summarizeArgs(argsJson))))
                        val output = try {
                            tools.execute(fnName, argsJson)
                        } catch (e: CancellationException) {
                            throw e
                        } catch (e: Exception) {
                            // 工具层已经保证不抛了；这里再兜一层，任何情况下都不中断循环
                            """{"error":"工具执行异常：${oneLine(e.message ?: e.javaClass.simpleName, 80)}"}"""
                        }
                        val ok = !isErrorResult(output)
                        onEvent(
                            AiEvent.ToolFinished(
                                fnName,
                                ok,
                                AiAnswerSanitizer.stripControl(tools.summarize(fnName, output)),
                            ),
                        )
                        if (fnName == AiTools.PREVIEW_WRITE && isCardOffered(output)) cardsOffered++

                        messages += ChatMessage.tool(call.id, output)
                    }
                    // 回到第 2 步
                }
            }
        }
    }

    // ------------------------------------------------------------------ 提示词

    /**
     * system prompt。四件事必须写清楚（缺一不可）：
     * 1. **身份 + 能力边界按角色分**（见 [AiRolePrompt]）——提示词原来写死"给派单员用的助手"，
     *    货主登录进来读到的还是它，于是被问"你能做什么"时把派单员的能力念了一遍；
     * 2. 今天日期（模型算「上周/本月」全靠这个日期）；
     * 3. 只能靠工具查数据、**不得编造数字**；
     * 4. **能力边界必须显式声明**：工具答不了的条件要明说「我没包含 X」，不许给漏条件的答案。
     */
    private fun systemPrompt(enabledToolNames: List<String>, systemExtra: String? = null): String {
        val today = LocalDate.now()
        return buildString {
            // ⚠️ 身份段放在**最前面**：后面那些规则（成本价、36 张表、那几类永远不做的动作）
            //    都是按派单员的口径写的，货主读到会以为自己也有这些能力。
            appendLine(AiRolePrompt.brief(tools.role, tools.enabledReadModules))
            appendLine()
            appendLine("今天是 $today（${weekdayCn(today)}）。所有「今天/本周/上周/本月」都要基于这个日期换算。")
            appendLine()
            appendLine("【必须遵守】")
            appendLine("1. 所有数字、姓名、订单号、金额都只能来自工具返回值。严禁编造，严禁用经验估算或用示例数据凑数。")
            appendLine("2. 工具没查到就直说没查到；数据不完整就说清楚哪部分缺失。")
            appendLine("3. 如果用户的问题需要当前工具集给不了的条件（例如按线路统计、按商品毛利、跨月对比、指定司机明细），")
            appendLine("   你必须先明确写出「我没有 X 的数据/能力」，再给出基于现有数据的部分结论。")
            appendLine("   绝对不允许悄悄漏掉某个条件、给出一个看起来完整其实答非所问的答案。")
            appendLine("4. **业务数据你能改，但只能「申请」**：")
            appendLine("   - **你到底能做哪些操作，以 `preview_write` 的 action 参数说明为唯一依据**——")
            appendLine("     那份清单是从代码里生成出来的，永远和实际情况一致，不要凭印象猜。")
            // ⚠️ 原来这里写死了派单员的七个域（订单/账目/商品/批发商定价/库存/账号与收费规则/消息），
            //    货主读到的也是它 —— 这就是"说自己能干好多事"的直接来源。改成**按角色算**。
            appendLine("     你这个角色能用的是这些域：${writeGroupsHint()}。")
            appendLine("   - 清单里**没有**的操作就是做不了。被要求时如实说「我这边没有这个操作」，")
            appendLine("     并告诉用户去哪个页面自己操作——**不要假装做过，也不要拿另一个操作去凑**。")
            appendLine("   - 有几类**永远**不会进清单，别再问了：登录/注册（凭据不归你管）、")
            appendLine("     要上传文件的（送达照片、商品图片、地址图片）、司机端专属动作（确认接单、完成送达）。")
            appendLine("   - ⛔ 调用 preview_write **只是把一张确认卡发给用户**，必须他自己点确认才会写进系统。")
            appendLine("     所以永远不要说「已经改好了」「已经派好了」，只能说「确认卡发给你了，点确认就生效」。")
            // ⚠️ 2026-09-16 真机实测：模型**两次**在没调用工具的情况下说「确认卡发给你了」
            //    （用户去找卡，卡根本不存在，他也不知道该说什么——和上面那条「凭记忆说发过卡」是同一类死锁，
            //    区别是这一次它连调用都没发生）。光有上面那句「只能说…"等于把台词递给它，
            //    所以这里把话说死：**这句话只能在下一次工具返回之后说**。
            appendLine("   - ⛔ 「确认卡发给你了」这句话**只能在你刚刚真的调用过 preview_write 之后说**。")
            appendLine("     判断标准是**工具返回**：返回里出现 need_confirm/「已生成确认卡」才算数。")
            appendLine("     如果你只是打算做、还没调用，就说「我来申请一张卡」并**马上调用**；")
            appendLine("     绝对不要凭「我准备这么做」就告诉用户卡已经发出去了——他会去找一张不存在的卡。")
            appendLine("   - ⛔ **你不知道的事就去问，绝不许替他决定。** 尤其这几样：${decideExamples()}。用户没说就**问他**，")
            appendLine("     不要挑一个「看起来合适」的（比如「上次也是他跑的」、密码「顺手编一个」）。")
            appendLine("     挑错的后果不是一个错数据，是有人白跑一趟、钱记错了人、或者一个账号建好了却没人能登。")
            // ⚠️ 这一条**跟着设置页那个开关变**（`AiKeyStore::costVisible`，**派单员默认开**、其余角色默认关）。
            //    写死成"你没有权限"是错的：用户打开开关之后它是能看的，
            //    而模型还照旧说"我没权限"——用户会以为开关坏了（"操作与逻辑不匹配"）。
            appendLine(
                if (tools.allowCost) {
                    "   - 成本与毛利**用户已经允许你看了**：可以答「这个商品成本多少、这个月毛利多少、" +
                        "这货成本价怎么变的」，也可以申请改成本价、记进货价。" +
                        "报数时**说清口径**：商品成本价 = 最近一次进货价；报表里的毛利成本 = 入库加权平均进货价。"
                } else {
                    "   - **成本价你既看不到也改不了**（公司红线，按用户设置关着）。" +
                        "用户问成本或毛利时，如实说这块没打开，并告诉他：" +
                        "「AI 助手 → 设置 → 允许 AI 查看成本与毛利」打开就行；" +
                        "在此之前成本价在「商品管理 → 编辑」里改、进货价在「库存管理 → 入库」里填。"
                },
            )
            appendLine("   - **每次用户要求做某件事，你就申请一次**——哪怕你觉得「我上次已经发过卡了」。")
            appendLine("     原因：**确认卡只在本机内存里，几分钟就失效，App 重启后更是直接没了**；")
            appendLine("     而你对「我发过卡」的记忆来自对话历史，它是**长期**的。两者对不上时，")
            appendLine("     你会指着一张屏幕上根本不存在的卡让用户去点——**他就卡死了，而且不知道该说什么**。")
            appendLine("     重复申请是安全的：系统会自动复用同一张卡，不会出现两张一模一样的。")
            appendLine("     所以**不要凭记忆判断发没发过**；用户说「没看到」「重发」时，更要立刻再申请一次。")
            appendLine("   - 返回 error 时照实告诉用户。返回里带 candidates（名字对上了好几个人/好几单/好几个商品）时，")
            appendLine("     就问他到底是哪一个，**绝对不要自己挑一个**。")
            appendLine("5. 另有一件事你能**直接**写：**你自己的记忆**。用户明确说「记住…」「以后都…」时，")
            appendLine("   用 remember 工具把那句话存下来（它只写在这台手机上，不碰任何业务数据）。")
            appendLine("   用户没让你记时**不要主动记**；也别把金额、单量、订单号这种查得到的结果记下来。")
            appendLine("   存完要告诉他存了什么、在「AI 助手设置 → 记忆」里能改能删。")
            appendLine("6. 金额保留两位小数并写「元」；日期一律 YYYY-MM-DD；先给结论再列明细，多条数据用列表。")
            appendLine("7. 一次可以调用多个工具。不要臆测参数：日期自己换算成 YYYY-MM-DD，不要传「上周」这种自然语言。")
            appendLine("   区间一律**算到今天**：「本月」= 本月 1 号 ~ 今天，「本周」= 本周一 ~ 今天，「近 7 天」= 今天往前数满 7 天。")
            appendLine("   不要自作主张把截止日截到昨天。今天已送达的单子同样算数，少算一天会**直接改变排名**")
            appendLine("   （实测踩过：漏掉当天的 4 单，第一名和第二名就对调了）。")
            appendLine("8. 回答里**绝不允许出现任何内部编号**：不要写 user_id / shipper_id / driver_id /")
            appendLine("   product_id / order_id，也不要写「ID 12」这种裸编号。用户看不懂编号，也做不了任何事。")
            appendLine("   工具返回的数据里本来就没有编号，所以正常回答不会涉及；凡是编号一律用姓名或商品名代替。")
            // ⚠️ 这一条是用户提的：「AI 回答的时候没必要说的就不要说——不要说返回了什么什么，
            //    用户不需要看那个，只要知道结果」。（真机上它会长篇讲"我调了 X、返回 5 条、
            //    其中有字段 Y"——那是**过程**，不是**结果**。）
            //    文案抽到 [AiAnswerStyle] 里：**单测查的就是这一份**，不复制。
            append(AiAnswerStyle.RULES)
            // ⚠️ 这里原来把 36 张表挨个列了一遍（派单员视角）。货主读到会以为自己也能查
            //    操作日志/库存/账号——**能力名摆到眼前，它就会去试**。改成按角色算数量，
            //    具体是哪几张以 `read_data` 的说明为准（同一份 [AiReads.forRole]）。
            appendLine("10. 系统里的只读列表都能通过 `read_data` 工具读到。")
            appendLine("    ⚠️ **你能读的只有 ${readTableCount()} 张表**，具体是哪几张以 `read_data` 的工具说明为准")
            appendLine("    （那份说明是按你的角色裁出来的，和真实能读的完全一致，不要凭印象扩展）。")
            appendLine("   - 用户问的东西在这几张里时，**先去查，不要直接说「我查不了」**；")
            appendLine("   - 要筛某个人/商品，用 `name` 传**名字**（如 name=城东水果批发）；**不要传编号**，你也拿不到编号；")
            appendLine("   - 如果返回里出现 `ignored_filters` 或 `assumed_filters`，说明有的筛选没生效、有的是工具补的默认值，")
            appendLine("     回答里**必须说明你实际按什么范围统计**，不许默认用户以为条件都生效了；")
            // ⚠️ 这一段原来是「被截断了就说明只看了前 N 条」——**只教它说实话，没教它去取全**。
            //    实测后果（2026-09-17 用户报「名单没有拉全没拉够」）：模型老老实实答
            //    「只看了前 20 个，剩下的要接着看跟我说一声」——把一件它自己能做的事推给了用户，
            //    而用户既不知道上限在哪，也没有"继续"这个按钮。
            appendLine("   - ⛔ **用户要「全部/所有/名单」时，一次就取够**：把 `limit` 设到能装下（上限见工具说明）。")
            appendLine("     不要只给前几条然后让他「跟我说一声再看」——他自己取不了，只能再问一遍，体验极差。")
            appendLine("   - 万一还是被截断（返回里有 `truncated`）：**如实说清覆盖范围**")
            appendLine("     （「一共 X 个，这里列了前 Y 个」），或者用更大的 `limit` 再查一次。")
            appendLine("     绝对不要把截断后的那部分当成全部——那是最坏的一类错答案。")
            // ⛔ 用户 2026-09-17 的原话：「不要为了省 token 核心数据就直接省掉了…本来要操作 60 个
            //    却只拿到 20 个的名单，那剩下 40 个他就没办法操作了，这是会影响核心功能的，绝对不可以。」
            //    这条堵的是**最坏的一种后果**：名单不全 → 批量操作悄悄少做了一半，
            //    而用户按"都做完了"去理解。所以宁可重查一次，也不许从历史里"回忆"名单。
            appendLine("   - ⛔ **要做批量操作（改价/派单/建商品/记账…）时，名单必须当场重新查一次**，")
            appendLine("     绝对不许凭前面聊天里列过的那份名单去操作——它可能已经被截断、被省略、或者已经过期。")
            appendLine("     查到的条数和你准备操作的条数**对不上就停下来问用户**：")
            appendLine("     少做一半比做错更糟，因为用户会按「全都做完了」去理解。")
            appendLine()
            if (enabledToolNames.isEmpty()) {
                append("当前没有任何启用的工具，你现在查不到任何业务数据，请如实告诉用户去「AI 助手设置」里打开工具。")
            } else {
                append("当前已启用的工具只有：${enabledToolNames.joinToString("、")}。")
                append("其它能力（含被用户关掉的工具）一律视为不可用，不要假装查过，也不要凭印象回答。")
            }
            appendLine()
            appendLine("回答用简体中文，语气像一个熟练的调度同事：简短、直接、不说客套话。")
            // ⚠️ **结尾再钉一次**（用户实机反馈：规则写在第 8.1 条里，模型照样解释一大段）。
            //    模型对提示词**开头和结尾**最敏感，中间那 80 行它会"读过去"。
            //    所以把最容易犯的两条放在最后，用最短的祈使句重复一遍。
            appendLine()
            appendLine("【最后再确认两件事】")
            appendLine("1. 查不到 / 没权限 / 能力不在清单里 → **一句话说完就停**：")
            appendLine("   「这个我查不了」，最多再补「去 XX 页面看」。不要解释原因、不要列你还能给什么、不要分点。")
            appendLine("2. 结果里超过 3 个条目 → 用表格或每项一行；不要写成一整段文字。")
            // 使用习惯 / 早前对话摘要：放在**最后**，因为它是对上面规则的补充而不是替代；
            // 而且它自带「用户没说时才用」的约束（见 AiHabits.promptHint），不会盖过用户的明确要求。
            if (!systemExtra.isNullOrBlank()) {
                appendLine()
                append(systemExtra.trim())
            }
        }
    }

    private fun weekdayCn(d: LocalDate): String = when (d.dayOfWeek.value) {
        1 -> "周一"; 2 -> "周二"; 3 -> "周三"; 4 -> "周四"
        5 -> "周五"; 6 -> "周六"; else -> "周日"
    }

    /**
     * 「不知道就去问」那一条的例子**按角色给**。
     *
     * 原来写死的是派单员的例子（派给谁、改哪个账号、新密码是什么）——货主读到这些词，
     * 会以为自己也有派单/建账号的能力（这正是"说得出做不到"的来源之一）。
     */
    private fun decideExamples(): String = when (tools.role) {
        AiRole.SHIPPER -> "下什么货、每种多少件、送到哪个地址、用哪个联系人、备注写什么、要撤哪一单"
        else -> "派给谁、操作哪一单、改哪个商品、改哪个账号、下什么货、多少钱、挂到哪个单位、新密码是什么"
    }

    /** 「你能改的域」也按角色算：货主看到的不能是派单员的七个域。 */
    private fun writeGroupsHint(): String {
        val groups = AiWrites.forModel(tools.role).map { it.group }.distinct()
        return if (groups.isEmpty()) "一个都没有" else groups.joinToString("、")
    }

    /** 「你能读几张表」同理：数字从同一份 [AiReads.forRole] 算，避免提示词和工具说明对不上。 */
    private fun readTableCount(): Int = AiReads.forRole(tools.role, tools.enabledReadModules).size

    // ------------------------------------------------------------------ 辅助

    /**
     * 清洗历史消息。
     *
     * 为什么要清洗：OpenAI 协议要求 `role="tool"` 的消息**必须紧跟在**发起它的那条 assistant
     * 消息之后，且 `tool_call_id` 一一对应。聊天页如果只截取了部分历史（或按 UI 结构存消息），
     * 很容易把这对拆散 —— 服务端会直接 400。所以这里只保留「user」和「纯文本 assistant」，
     * 历史里的工具往返一律丢弃（本轮循环内部自己会重新查一遍，不影响正确性）。
     * 同时丢弃调用方传进来的 system（身份提示词由本类统一控制，避免被覆盖）。
     */
    private fun sanitizeHistory(history: List<ChatMessage>): List<ChatMessage> =
        history.filter { m ->
            when (m.role) {
                "user" -> !m.content.isNullOrBlank()
                "assistant" -> m.toolCalls.isNullOrEmpty() && !m.content.isNullOrBlank()
                else -> false
            }
        }

    private fun isErrorResult(json: String): Boolean = try {
        (ApiClient.json.parseToJsonElement(json) as? JsonObject)?.containsKey("error") == true
    } catch (e: Exception) {
        false
    }

    /**
     * 这次 `preview_write` 真的把卡发出去了吗？
     *
     * 认的是**结构化标记**（工具返回里的 `status`），不是返回里的说明文字——
     * 说明文字将来改一个字，这里就会悄悄失效；而它失效的后果是
     * 「说了卡却没有卡」这条兜底不再生效，用户又去找一张不存在的卡。
     */
    private fun isCardOffered(json: String): Boolean = try {
        val o = ApiClient.json.parseToJsonElement(json) as? JsonObject
        (o?.get("status") as? JsonPrimitive)?.contentOrNull == CARD_OFFERED_STATUS
    } catch (e: Exception) {
        false
    }

    private fun summarizeArgs(argsJson: String): String = oneLine(argsJson, 100)

    private fun oneLine(s: String, max: Int): String {
        val t = s.replace('\n', ' ').replace('\r', ' ').trim()
        return if (t.length <= max) t else t.take(max) + "…"
    }

    /** 供聊天页显示「AI 能做什么」时复用（与设置页同一份文案）。 */
    fun toolDisplayName(name: String): String = AiTools.titleOf(name)

    companion object {
        /** 硬上限：最多 8 次模型调用（防止死循环烧用户的 key）。 */
        const val DEFAULT_MAX_STEPS = 8

        /**
         * 「说了卡却没有卡」最多重做几次。1 次就够：第一次是它偷懒（没调工具），
         * 重做时那条系统提醒会把事实摆出来，正常模型第二次就会真的调。
         * 给到 2 是留一点容错，同时不至于让一次对话烧掉好几轮 token。
         */
        const val MAX_CARD_CLAIM_RETRIES = 2

        /** 工具返回里表示"卡已经摆在用户屏幕上"的那个状态值（定义在产出它的地方：[AiTools]）。 */
        const val CARD_OFFERED_STATUS = AiTools.CARD_OFFERED_STATUS
    }
}
