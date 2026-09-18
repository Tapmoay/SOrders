package com.tapmoay.sorders.ai

/**
 * 上下文预算：**按固定预算收口，窗口只作兜底**（v3.34 改，之前是"到窗口 40% 才压缩"）。
 *
 * ### 两条触发路径，主次不能颠倒
 * 1. **主：固定预算 [HISTORY_BUDGET_TOKENS]**（8k，与模型窗口无关）——见 [overBudget] / [fitToBudget]；
 * 2. **兜底：窗口比例 [COMPACT_AT] / [HARD_LIMIT]**——只在"窗口小得连预算都装不下"时起作用。
 *
 * ⚠️ **曾经只有第 2 条，那是个设计错误**：对 deepseek-flash（窗口 1,048,576）来说 40% 是 419,430 token，
 * 折合四百多轮问答（`_tools/ai/_ctx_budget.py` 算过）——**实际永不触发**，
 * 于是"把整段对话原样发出去"成了唯一会执行的路径。
 * 根因是把「窗口有多大」当成了「该用多少上下文」：前者是模型的能力上限，
 * 后者应该是我们自己的预算。谁要把它改回去，红线 §11c 会红（`_reverse_verify_ctx_budget.py` 证明过）。
 *
 * ### 用量从哪来（这一点决定了整个功能可不可靠）
 * 窗口那条用**服务端真实回报的 `usage.prompt_tokens`**，而不是自己数 token：
 * 本地估偏 20% 会让阈值判断变成随机事件，而服务端**每次调用都白给**这个数。
 * 预算这条对精度不敏感（它是个"该收口了"的阈值，不是悬崖），所以用 [estimateHistoryTokens] 粗估即可。
 *
 * ### 窗口从哪来（整个功能唯一的不可靠点，必须说清楚）
 * OpenAI 兼容的 `/models` **只返回模型名，不返回上下文长度**（DeepSeek / 豆包 / 千问三家实测都是），
 * 所以"模型支持多大"只能**按名字猜**（[inferWindow]）。猜错的方向分轻重：
 * - **猜大 = 危险**：请求超过真实上限 → 服务端直接 400「context length exceeded」；
 * - 猜小 = 只是提前压缩，答得出来，最多丢一点旧信息。
 *
 * 所以 [inferWindow] 只把**名字里写明的**（`-128k` / `-1m`）和**业界公认的**往大写，
 * 其余一律 [FALLBACK_WINDOW]；而"猜大了"由 [shrinkOnOverflow] 在**真实报错时自动纠正并记住**。
 *
 * 这一步是"不给用户选择"能成立的前提：**错了它自己能修**，而不是甩给用户一个旋钮让他自己猜。
 */
object AiContext {

    /**
     * 认不出模型时的兜底窗口。
     *
     * 128k 是主流 OpenAI 兼容端点的共同下限，所以猜它最不容易猜大。
     * 但**猜小是有代价的**（会过早压缩、白白丢掉还能带的上下文），所以另有两条纠偏路径：
     * [growOnEvidence]（成功过的量级证明还能更大）与 [shrinkOnOverflow]（撞上限时按端点说的上限改）。
     */
    const val FALLBACK_WINDOW = 128_000

    /** 收缩窗口时的地板：再小就没法干活了（连历史都装不下，会一直压缩）。 */
    const val MIN_WINDOW = 32_000

    /** 窗口上限（防呆）：端点自己报的上限超过这个数就不采信，按 [MIN_WINDOW] 那套折半逻辑走。 */
    const val MAX_WINDOW = 4_000_000

    /** 用到窗口的这个比例就压缩（用户口径：40%）。 */
    const val COMPACT_AT = 0.40

    /**
     * 历史部分的**固定预算**（token）。**与模型窗口无关**——这是 v3.34 的关键改动。
     *
     * ### 为什么不能用「窗口的百分比」当触发点（原来的写法，已废弃）
     * 原来只在 `contextUsed >= 窗口 × 40%` 时才收口。对 deepseek-flash（窗口 1,048,576）来说
     * 那是 **419,430 token**——折合四百多轮报表问答（实测体量见 `_tools/ai/_ctx_budget.py`）。
     * 也就是说**在实际使用中它永远不会触发**，"把整段对话原样发出去"成了唯一真正会执行的路径。
     * 根因是把「窗口有多大」当成了「该用多少上下文」——前者是模型的能力上限，
     * 后者应该是我们自己的预算。
     *
     * ### 为什么是 8,000
     * 系统提示词 + 工具清单的固定开销实测约 3k 起（`_tools/ai/_sysprompt_size.py`），
     * 历史再给 8k，单次请求大致落在 11~17k——对 128k 的兜底窗口还有足够余量，
     * 对 1M 的窗口更是零压力。用户现在的日常对话只有 1~2k，**这个改动在日常几乎感觉不到**；
     * 它管的是"对话变长之后"：从"无限膨胀到 46 万才收口"变成"到 8k 就收口"。
     *
     * 这个数只此一处，要调就调它（调大 = 记得更全但每轮更贵，调小 = 更省但更容易"忘事"）。
     */
    const val HISTORY_BUDGET_TOKENS = 8_000

    /**
     * 降级时助手回答保留多少字符（取**第一行**——那一行通常就是结论）。
     *
     * 为什么不直接丢掉：结论数字（"本月 128 单 / 3.4 万"）恰恰是后面几轮反复要用的，
     * 丢掉等于逼模型重新查一遍。降级到首行是"最便宜地保住结论"（AFM 那套分级保真的最小实现）。
     */
    const val DEGRADED_ANSWER_CHARS = 120

    /**
     * 降级时**用户消息**保留多少字符。
     *
     * 用户消息一般不降级（它带着筛选条件，是 AFM 里最该保住的那类）——
     * 但这个阈值是给**附件块**留的：`AiAttachment.augment` 把用户那句话放在**最前面**、
     * 附件内容跟在后面，所以从尾巴截断永远保留得住用户真正想问的那句话。
     * 不设这条的话，挂过一次表格的对话此后每一轮都要多付几千 token（实测单个附件块上限约 12k 字符）。
     */
    const val DEGRADED_USER_CHARS = 1_200

    /**
     * 降级留下的痕迹。**不能省**——模型必须知道"这里被省略过"，
     * 否则它会把截断的文字当成完整信息，给出一个"看起来有依据、其实是半截"的结论。
     * 两个不同的后缀是刻意的：助手回答省掉的是明细，用户消息省掉的是附件，恢复方式不一样。
     */
    const val ELIDED_TAIL = "…（明细已省略）"
    const val ELIDED_ATTACHMENT = "\n…（后面还有附件内容，为节省上下文已省略）"

    /** 名字里显式写了窗口大小的（`-128k` / `-1m` / `-32K`）。 */
    private val EXPLICIT_SIZE = Regex("(?<![a-z0-9])(\\d{1,4})\\s*([km])(?![a-z0-9])")

    /**
     * 按模型名认窗口（家族表，从上往下第一个命中的生效）。
     *
     * ⚠️ **`deepseek` 这一行的值是实测的，不是抄文档的**：
     * `_tools/ai/_probe_context_overflow.py` 真的发了一个 1,200,006 token 的请求，
     * 端点回 400 并写明 `This model's maximum context length is 1048576 tokens`。
     * 一开始我按印象写的是 128k——**小了 8 倍**，等于用户说"支持 1M 就用 1M"而我只给 1/8。
     * 所以这张表里凡是能实测的都要实测；实测脚本就在上面那个路径，改表前先跑它。
     */
    private val FAMILY_WINDOWS: List<Pair<String, Int>> = listOf(
        "gemini" to 1_000_000,     // Gemini 1.5 起就是 1M
        "qwen-long" to 1_000_000,  // 千问长文本型号，名字里就写着 long
        "gpt-4.1" to 1_000_000,
        "deepseek" to 1_048_576,   // 实测（见上）；deepseek-flash / v4-pro 都是这个上限
        "claude" to 200_000,       // Claude 3 起 200k
        "doubao" to 256_000,       // 豆包 1.5 / seed 系列
        "seed" to 256_000,
        "kimi" to 256_000,
        "moonshot" to 256_000,
        "qwen" to 128_000,
        "glm" to 128_000,
        "ernie" to 128_000,
        "hunyuan" to 128_000,
        "minimax" to 128_000,
        "spark" to 128_000,
        "gpt-4o" to 128_000,
    )

    /**
     * 按模型名推断上下文窗口（**猜，不是探测**，见类注释）。
     *
     * 顺序：**名字里显式写了大小 → 听名字**（`doubao-1.5-pro-256k` = 256k）；
     * 否则查家族表；再认不出就 [FALLBACK_WINDOW]。
     */
    fun inferWindow(model: String): Int {
        val m = model.trim().lowercase()
        if (m.isEmpty()) return FALLBACK_WINDOW
        EXPLICIT_SIZE.find(m)?.let { hit ->
            val n = hit.groupValues[1].toIntOrNull() ?: return@let
            val v = n * if (hit.groupValues[2] == "m") 1_000_000 else 1000
            // 只认 ≥ [MIN_WINDOW] 的：`-4k` / `-8k` 这种多半是型号里的别的规格（视频、图像），
            // 而且真按 4k 当窗口，系统提示词一进去就过半，会压到没法干活。
            if (v in MIN_WINDOW..8_000_000) return v
        }
        FAMILY_WINDOWS.firstOrNull { m.contains(it.first) }?.let { return it.second }
        return FALLBACK_WINDOW
    }

    /**
     * 从「上下文超长」的报错体里**读出端点自己说的上限**。
     *
     * 为什么值得为此写正则：这是整个自愈链里**唯一不需要猜**的数。DeepSeek 的原始报错就是
     * （实测，见 `_tools/ai/_probe_context_overflow.py`）：
     * ```
     * This model's maximum context length is 1048576 tokens. However, you requested 1200006 tokens
     * (1200005 in the messages, 1 in the completion). Please reduce the length of the messages or completion.
     * ```
     * 有了它，撞一次上限就能把窗口**一次改到准确值**，而不是折半逼近（1M→500k→250k…要撞三次）。
     */
    fun parseStatedLimit(body: String?): Int? {
        if (body.isNullOrBlank()) return null
        val m = STATED_LIMIT.find(body) ?: return null
        val v = m.groupValues[1].toIntOrNull() ?: return null
        return v.takeIf { it in MIN_WINDOW..MAX_WINDOW }
    }

    /** 端点报上限的常见写法（英文为主，个别国产端点用中文）。 */
    private val STATED_LIMIT = Regex(
        "(?:maximum context length is|max(?:imum)? context (?:length|window) (?:is|of)|" +
            "上下文(?:长度)?上限(?:为|是)|最大长度(?:为|是))[^0-9]{0,12}(\\d{3,9})",
        RegexOption.IGNORE_CASE,
    )

    /**
     * 撞到「上下文超长」之后，把窗口收（或改）到一个**能装下**的值。
     *
     * 优先级：
     * 1. **端点自己说的上限**（[parseStatedLimit]）—— 一次到位，不用猜；
     * 2. 本轮**已经成功过**的最大 `prompt_tokens`（[lastGoodTokens]）—— 实证上界，
     *    那个量级确实发得出去，所以按它收一定安全（再乘 90% 硬裁就更稳）；
     * 3. 都没有（第一句就超长）→ 折半。
     *
     * 为什么不干脆一直折半：`1M → 500k → 250k → 125k` 要失败三次才收敛，
     * 每一次都是一声红色报错。
     */
    fun shrinkOnOverflow(window: Int, lastGoodTokens: Int, statedLimit: Int? = null): Int {
        statedLimit?.takeIf { it in MIN_WINDOW..MAX_WINDOW }?.let { return it }
        val half = (window.coerceAtLeast(MIN_WINDOW) / 2).coerceAtLeast(MIN_WINDOW)
        if (lastGoodTokens <= 0) return half
        return lastGoodTokens.coerceIn(MIN_WINDOW, half)
    }

    /**
     * 反向纠偏：**窗口猜小了也要能自己长大**。
     *
     * 判据：这一轮成功发出去了 `lastGoodTokens`，而且它已经贴着我们假设的上限
     * （≥ [HARD_LIMIT] × window）——说明"发不出去更多"是我们自己的闸门造成的，不是模型的极限。
     * 那就把假设翻倍（[MAX_WINDOW] 封顶）。
     *
     * 为什么敢翻倍：一端有成功实证（那个量级确实过得了），另一端翻过头会立刻收到 400，
     * 而 400 里**写着真实上限**，下一次调用就按它改准（[shrinkOnOverflow]）。两个方向都能自纠。
     *
     * @return 新窗口；不需要长大时返回 null
     */
    fun growOnEvidence(window: Int, lastGoodTokens: Int): Int? {
        if (lastGoodTokens <= 0) return null
        if (lastGoodTokens < (window.coerceAtLeast(1) * HARD_LIMIT).toInt()) return null
        val grown = window.coerceAtLeast(MIN_WINDOW) * 2
        return grown.coerceAtMost(MAX_WINDOW).takeIf { it > window }
    }

    /** 触发压缩的 token 数。 */
    fun threshold(window: Int, ratio: Double = COMPACT_AT): Int =
        (window.coerceAtLeast(1) * ratio).toInt()

    /** 是否该压缩了。 */
    fun shouldCompact(usedTokens: Int, window: Int): Boolean =
        usedTokens >= threshold(window)

    /**
     * 粗估一段文本的 token 数（**只在没有服务端用量时用**）。
     *
     * 经验公式：中日韩字符约 1 token/字，其它字符约 4 字符/token。
     * 刻意**不追求精确**——它的唯一用途是"第一轮之前给个量级"，
     * 一旦服务端回了 `prompt_tokens` 就立刻以那个为准。
     */
    fun estimateTokens(text: String): Int {
        if (text.isEmpty()) return 0
        var cjk = 0
        for (ch in text) {
            val c = ch.code
            if (c >= 0x2E80) cjk++ // 中日韩 + 全角标点
        }
        val other = text.length - cjk
        return cjk + (other + 3) / 4
    }

    /** 估算一整轮请求（系统提示词 + 历史）。 */
    fun estimateRequestTokens(systemPrompt: String, history: List<ChatMessage>): Int {
        var n = estimateTokens(systemPrompt) + MESSAGE_OVERHEAD
        history.forEach { m ->
            n += MESSAGE_OVERHEAD + estimateTokens(m.content.orEmpty())
            m.toolCalls?.forEach { n += estimateTokens(it.function.arguments) + 8 }
        }
        return n
    }

    /** 每条消息的角色/分隔符开销（各家都差不多，取 4）。 */
    private const val MESSAGE_OVERHEAD = 4

    /**
     * 硬上限：送出去的请求**无论如何**不许超过窗口的这个比例。
     *
     * 为什么压缩（40%）之外还要一道 90% 的硬闸：压缩**可能失败**（模型摘要调用失败、
     * 用户网络断了、甚至模型自己回一段空话）。压缩失败还继续把全量历史发出去，
     * 服务端就会直接报「context length exceeded」——**用户看到的是红色报错，问他为什么不早说**。
     * 有了这道闸，最坏情况只是"这轮少带点历史"，永远答得出来。
     */
    const val HARD_LIMIT = 0.90

    /**
     * 把历史裁到装得下为止（**从最早的开始丢**，至少留 [minKeep] 条）。
     *
     * 注意它和压缩的分工：压缩是"把旧对话变成摘要保住信息"（优先），
     * 这里是"再装不下就只好丢"（兜底）。两者都要有。
     */
    fun trimToFit(
        systemPrompt: String,
        history: List<ChatMessage>,
        window: Int,
        minKeep: Int = 2,
    ): List<ChatMessage> {
        if (history.size <= minKeep) return history
        val budget = (window.coerceAtLeast(1) * HARD_LIMIT).toInt()
        var kept = history
        while (kept.size > minKeep && estimateRequestTokens(systemPrompt, kept) > budget) {
            kept = kept.drop(1)
        }
        return kept
    }

    /**
     * 只算历史那部分的量（**不含**系统提示词与工具清单）。
     *
     * 为什么需要单独一个：固定预算管的是"历史"，而 `estimateRequestTokens` 把系统提示词也算进去了。
     * 两者差着一个约 3k 的固定开销，混用会让预算的含义漂移。
     */
    fun estimateHistoryTokens(history: List<ChatMessage>): Int {
        var n = 0
        history.forEach { m ->
            n += MESSAGE_OVERHEAD + estimateTokens(m.content.orEmpty())
            m.toolCalls?.forEach { n += estimateTokens(it.function.arguments) + 8 }
        }
        return n
    }

    /**
     * 历史是否已经超过固定预算（[HISTORY_BUDGET_TOKENS]）。
     *
     * ⚠️ 这是**主触发点**。窗口百分比那条（[shouldCompact]）降级为兜底——
     * 它只在"模型窗口小得连预算都装不下"时才该生效（例：窗口被收缩到 32k 时，
     * 预算 8k 仍然安全，但真撞到 28.8k 硬线还是要收）。
     */
    fun overBudget(history: List<ChatMessage>, budget: Int = HISTORY_BUDGET_TOKENS): Boolean =
        estimateHistoryTokens(history) > budget

    /**
     * 把历史压进预算：**先降级、再丢弃**（AFM 那套分级保真的最小实现，规则是内容驱动的，不靠分类器）。
     *
     * 三级保真，按"离现在多远"分配：
     * 1. **最近 [keepRecent] 条 = FULL**：一个字不动。用户正在聊的就是这些。
     * 2. **更早的助手回答 = COMPRESSED**：压成首行（[DEGRADED_ANSWER_CHARS]）。
     *    结论数字留在里面，明细（尤其整张 Markdown 表格）丢掉——那正是"大部分内容没用"的那部分。
     * 3. **更早的用户消息 = 保留**，除非它带着附件块（超过 [DEGRADED_USER_CHARS]）→ 同样降级。
     *    用户原话是筛选条件的载体，比助手的长篇回答更该留。
     * 4. 降级完还是超预算 → 从**最早**的开始丢（这部分信息由滚动摘要承担）。
     *
     * ### 为什么必须先降级再丢
     * 直接丢最早的几条，丢掉的是"结论"；先降级丢掉的是"明细"。
     * 前者的代价是模型重新查一遍（用户看到的是"它怎么又忘了"），后者几乎无代价。
     * 同样的预算下，先降级能多留下好几轮的结论。
     *
     * 纯函数，不联网、不改任何状态——**压缩失败也照样能用它兜住**，这正是它和 [AiCompactor] 的分工。
     */
    fun fitToBudget(
        history: List<ChatMessage>,
        budget: Int = HISTORY_BUDGET_TOKENS,
        keepRecent: Int = KEEP_RECENT_MESSAGES,
    ): List<ChatMessage> {
        if (history.size <= keepRecent) return history

        val older = history.dropLast(keepRecent)
        val recent = history.takeLast(keepRecent)
        var kept = ArrayDeque(older.map { degrade(it) })

        // 先降级、再丢弃：每丢一条都要重新量，不能一把丢过头
        var used = estimateHistoryTokens(kept + recent)
        while (kept.isNotEmpty() && used > budget) {
            kept.removeFirst()
            used = estimateHistoryTokens(kept + recent)
        }
        return kept + recent
    }

    /**
     * 单条消息的降级。助手回答取首行，用户消息只在明显是"附件块"时截断。
     *
     * 截断处**必须留下痕迹**：模型得知道"这里被省略过"，
     * 否则它会把一段截断的文字当成完整信息，答出一个看起来有依据其实是半截的结论。
     */
    private fun degrade(m: ChatMessage): ChatMessage {
        val text = m.content.orEmpty()
        return when {
            m.role == "assistant" && text.length > DEGRADED_ANSWER_CHARS -> {
                val head = text.lineSequence().firstOrNull { it.isNotBlank() }.orEmpty()
                m.copy(content = clip(head, DEGRADED_ANSWER_CHARS) + ELIDED_TAIL)
            }
            // 用户消息：短的原样留（那是筛选条件），长的按"附件块"处理（问题在最前面，尾巴是附件）
            m.role == "user" && text.length > DEGRADED_USER_CHARS ->
                m.copy(content = clip(text, DEGRADED_USER_CHARS) + ELIDED_ATTACHMENT)
            else -> m
        }
    }

    /** 截断（不切断代理对，避免半个 emoji 变乱码）。 */
    private fun clip(s: String, max: Int): String {
        if (s.length <= max) return s
        var end = max
        if (end > 0 && Character.isHighSurrogate(s[end - 1])) end -= 1
        return s.substring(0, end)
    }

    /** 窗口人话：`128k` / `1M`。 */
    fun windowLabel(window: Int): String = when {
        window >= 1_000_000 -> "${window / 1_000_000}M"
        window >= 1000 -> "${window / 1000}k"
        else -> window.toString()
    }

    // 这里曾经有一个 usageLabel(已用/窗口/百分比)：用户明确说**不要看这些数字**，
    // 「他只需要知道我这个模型是什么以及思考强度是怎样」，所以界面上不再有它，
    // 函数也一并删掉——留着就是等着下次有人又把它画回界面上。

    /**
     * 压缩时保留多少条最近消息。
     *
     * 为什么不是"保留到刚好装下"：工具往返（assistant 带 tool_calls + tool 结果）
     * 是**成对**的，从中间切开会让服务端 400（见 `AiAgentLoop.sanitizeHistory`）。
     * 所以这里按"条数"保留，且**压缩后的历史只留 user / 纯文本 assistant**——
     * 工具往返本来就会被 sanitizeHistory 丢掉，压缩时一并丢掉最省事也最安全。
     */
    const val KEEP_RECENT_MESSAGES = 6
}
