package com.tapmoay.sorders.ai

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * [AiContext] 的单元测试。
 *
 * 这里守的是**钱包和稳定性**两件事：
 * - 阈值算错 → 该压缩时不压缩，用户会撞上「context length exceeded」的红色报错；
 * - 硬裁算错 → 压缩失败时把整段历史发出去，同样报错。
 * 两者都是"平时没事、上下文一长就炸"的类型，必须钉住。
 *
 * v3.4 起还多守两件事（用户口径变了：**不给用户选窗口**）：
 * - [AiContext.inferWindow] 猜窗口：猜大 = 用户吃红色报错，猜小 = 白白丢历史；
 * - [AiContext.shrinkOnOverflow] 撞上限后的自动收缩：**这是"不给用户选择"能成立的前提**，
 *   算错就等于把用户卡死在"每次都超长"的死循环里。
 */
class AiContextTest {

    @Test
    fun thresholdIsFortyPercentOfWindow() {
        assertEquals(51_200, AiContext.threshold(128_000))
        assertEquals(400_000, AiContext.threshold(1_000_000))
        assertEquals(12_800, AiContext.threshold(32_000))
    }

    @Test
    fun shouldCompactAtTheBoundary() {
        assertFalse(AiContext.shouldCompact(51_199, 128_000))
        assertTrue("到 40% 就该压了（含等于）", AiContext.shouldCompact(51_200, 128_000))
        assertTrue(AiContext.shouldCompact(200_000, 128_000))
    }

    @Test
    fun windowLabelIsHumanReadable() {
        assertEquals("128k", AiContext.windowLabel(128_000))
        assertEquals("1M", AiContext.windowLabel(1_000_000))
        assertEquals("32k", AiContext.windowLabel(32_000))
    }

    @Test
    fun estimateCountsHanAsOneTokenAndOthersAsQuarter() {
        assertEquals(4, AiContext.estimateTokens("本月单量"))   // 4 个汉字 ≈ 4 token
        assertEquals(1, AiContext.estimateTokens("abcd"))       // 4 个 ASCII ≈ 1 token
        assertEquals(0, AiContext.estimateTokens(""))
        // 混排：2 汉字 + 4 ASCII ≈ 2 + 1 = 3
        assertEquals(3, AiContext.estimateTokens("货主abcd"))
    }

    @Test
    fun trimToFitDropsOldestUntilItFits() {
        val big = "字".repeat(4000) // 约 4000 token
        val history = (1..20).map { ChatMessage.user("第 $it 条 $big") }
        val kept = AiContext.trimToFit("", history, window = 10_000)
        assertTrue("必须裁到装得下", kept.size < history.size)
        assertTrue("至少留几条", kept.size >= 2)
        // 丢的必须是最早的（最新的一轮永远要留住）
        assertEquals(history.last().content, kept.last().content)
    }

    @Test
    fun trimToFitKeepsMinimumEvenWhenNothingFits() {
        val huge = ChatMessage.user("字".repeat(100_000))
        val kept = AiContext.trimToFit("", listOf(huge, huge, huge), window = 1000, minKeep = 2)
        assertEquals("宁可超一点也不能把历史裁成空", 2, kept.size)
    }

    @Test
    fun trimToFitLeavesShortHistoryAlone() {
        val history = listOf(ChatMessage.user("一"), ChatMessage.assistant("二"))
        assertEquals(history, AiContext.trimToFit("", history, window = 1_000_000))
    }

    @Test
    fun compactRatioIsFortyPercent() {
        // 用户口径写死在常量里：改这个数会同时改掉界面文案和触发点，所以单独钉一条
        // （v3.1 是 60%，v3.4 用户改成「整个会话记录的 40%」）
        assertEquals(0.40, AiContext.COMPACT_AT, 0.0001)
    }

    // ------------------------------------------------- 固定历史预算（v3.34 的主触发点）

    @Test
    fun budgetIsDecoupledFromTheWindow() {
        // ⚠️ 这条是**反回归**用的，改触发点前先读它。
        // 旧口径「窗口 × 40%」在 deepseek-flash（1M）上等于 419,430 token——
        // 折合四百多轮报表问答，**实际永不触发**（`_tools/ai/_ctx_budget.py` 算过）。
        // 表现是"把整段对话原样发出去"成了唯一会执行的路径。
        val history = List(40) { ChatMessage.assistant("字".repeat(300)) }   // ≈ 12k token
        assertTrue("12k 的历史：按预算就该收口了", AiContext.overBudget(history))
        assertFalse(
            "而旧触发点这时还差得远 —— 这正是它坏在哪（它永远不会到）",
            AiContext.shouldCompact(AiContext.estimateHistoryTokens(history), 1_048_576),
        )
        // 预算是个常数，不随窗口变：换多大的模型都是这个数
        assertTrue(AiContext.HISTORY_BUDGET_TOKENS < AiContext.FALLBACK_WINDOW / 4)
    }

    @Test
    fun budgetBoundaryIsInclusiveOnTheExceedingSide() {
        // 恰好等于预算 = 还没超（差一点才收口，避免刚好卡在边界上反复触发）
        assertFalse(AiContext.overBudget(listOf(ChatMessage.user("字".repeat(96))), budget = 100))
        assertTrue(AiContext.overBudget(listOf(ChatMessage.user("字".repeat(97))), budget = 100))
    }

    @Test
    fun historyTokensExcludeTheSystemPrompt() {
        // 预算管的是"历史"，不能把系统提示词算进来（两者差着一个约 3k 的固定开销）
        val history = listOf(ChatMessage.user("本月单量"), ChatMessage.assistant("128 单"))
        assertTrue(AiContext.estimateHistoryTokens(history) > 0)
        assertTrue(
            AiContext.estimateRequestTokens("字".repeat(500), history) >
                AiContext.estimateHistoryTokens(history) + 400,
        )
    }

    @Test
    fun fitToBudgetDegradesOlderAnswersInsteadOfDroppingThem() {
        // 先降级、再丢弃：预算够装"摘要化"的旧回答时，一条都不许丢
        val older = List(4) {
            ChatMessage.assistant("本月 128 单\n" + "明细行 ".repeat(200))
        }
        val recent = listOf(ChatMessage.user("那上周呢"), ChatMessage.assistant("上周 96 单"))
        val out = AiContext.fitToBudget(older + recent, budget = 1_000, keepRecent = 2)

        assertEquals("降级够用就不该丢任何一轮", 6, out.size)
        assertTrue("旧回答必须被压成首行", out[0].content!!.startsWith("本月 128 单"))
        assertTrue("截断必须留下痕迹，否则模型会把半截当全部", out[0].content!!.endsWith(AiContext.ELIDED_TAIL))
        assertTrue("整张明细必须被丢掉（那才是「没用的那部分」）", out[0].content!!.length < 200)
        assertEquals("最近两条一个字都不能动", "那上周呢", out[4].content)
        assertEquals("上周 96 单", out[5].content)
    }

    @Test
    fun fitToBudgetKeepsShortUserMessagesBecauseTheyCarryTheConstraints() {
        // 用户原话带着筛选条件，是 AFM 里最该保住的那类：短的原样留，不降级
        val ask = ChatMessage.user("只看城东水果批发这个月的")
        val older = listOf(ask, ChatMessage.assistant("好\n" + "明细 ".repeat(300)))
        val out = AiContext.fitToBudget(older + listOf(ChatMessage.user("继续")), budget = 5_000, keepRecent = 1)
        assertEquals("短的用户消息一个字都不能改", "只看城东水果批发这个月的", out[0].content)
    }

    @Test
    fun fitToBudgetTruncatesHugeAttachmentBlockButKeepsTheQuestion() {
        // 附件块是最容易吃掉预算的东西（实测单个上限约 12k 字符，且此后**每一轮**都要重发）。
        // augment() 把用户那句话放在最前面，所以从尾巴截断永远保得住他真正想问的那句。
        val question = "帮我按这个表创建商品"
        val withAttachment = ChatMessage.user(question + "\n【附件】以下是用户上传的文件内容：\n" + "行数据 ".repeat(1500))
        val out = AiContext.fitToBudget(
            listOf(withAttachment) + List(2) { ChatMessage.user("继续") },
            budget = 5_000,
            keepRecent = 1,
        )
        assertTrue("用户那句话必须留住", out[0].content!!.startsWith(question))
        assertTrue("附件必须被截断", out[0].content!!.contains(AiContext.ELIDED_ATTACHMENT))
        assertTrue("截断后要明显短于原来", out[0].content!!.length < withAttachment.content!!.length / 2)
    }

    @Test
    fun fitToBudgetDropsOldestOnlyAfterDegradingIsNotEnough() {
        val older = List(6) { ChatMessage.assistant("结论 $it\n" + "明细 ".repeat(300)) }
        val recent = listOf(ChatMessage.user("问"), ChatMessage.assistant("答"))
        // 预算小于"最近两条"本身 → 降级救不了，只能把旧的丢光
        val out = AiContext.fitToBudget(older + recent, budget = 1, keepRecent = 2)
        assertEquals("最近窗口永远不动，剩下的一律丢", 2, out.size)
        assertEquals("问", out[0].content)
    }

    @Test
    fun fitToBudgetLeavesShortHistoryAlone() {
        val history = listOf(ChatMessage.user("一"), ChatMessage.assistant("二"))
        assertEquals(history, AiContext.fitToBudget(history, budget = 1, keepRecent = 6))
    }

    // ------------------------------------------------------------ 窗口推断

    @Test
    fun inferWindowHonoursExplicitSizeInModelName() {
        // 名字里写了大小就听名字的（这类型号名到处都有，是最可靠的一路信号）
        assertEquals(256_000, AiContext.inferWindow("doubao-1.5-pro-256k"))
        assertEquals(1_000_000, AiContext.inferWindow("qwen-plus-1m"))
        assertEquals(32_000, AiContext.inferWindow("some-model-32K"))
        // 大小写、连字符写法都要认
        assertEquals(128_000, AiContext.inferWindow("Foo-Bar-128k-preview"))
    }

    @Test
    fun inferWindowFallsBackToFamilyTable() {
        assertEquals(128_000, AiContext.inferWindow("acme-unknown"))
        assertEquals(256_000, AiContext.inferWindow("doubao-seed-1-6"))
        assertEquals(1_000_000, AiContext.inferWindow("gemini-2.5-pro"))
        assertEquals(200_000, AiContext.inferWindow("claude-sonnet-4"))
    }

    @Test
    fun inferWindowKnowsTheMeasuredDeepSeekLimit() {
        // ⚠️ 这个数是**实测**的，不是抄文档的：`_tools/ai/_probe_context_overflow.py` 真发了一个
        // 1,200,006 token 的请求，端点回 400 并写明 `maximum context length is 1048576 tokens`。
        // 我一开始按印象写 128k——**小了 8 倍**，直接违背用户"支持 1M 就用 1M"的要求。
        // 谁要是觉得这个数不对，请先跑那个探针，别再按印象改。
        assertEquals(1_048_576, AiContext.inferWindow("deepseek-flash"))
        assertEquals(1_048_576, AiContext.inferWindow("deepseek-v4-pro"))
        assertEquals(1_048_576, AiContext.inferWindow("deepseek-chat"))
    }

    @Test
    fun inferWindowPrefersConservativeFallbackForUnknownNames() {
        // 认不出来时**宁可猜小**：猜大 = 用户吃 400，猜小 = 只是早点压缩
        assertEquals(AiContext.FALLBACK_WINDOW, AiContext.inferWindow("some-inhouse-llm"))
        assertEquals(AiContext.FALLBACK_WINDOW, AiContext.inferWindow(""))
        // 型号里的数字不能被当成窗口（`72b` 是参数量不是上下文）
        assertEquals(AiContext.FALLBACK_WINDOW, AiContext.inferWindow("acme-72b-instruct"))
    }

    @Test
    fun inferWindowIgnoresAbsurdSmallSizes() {
        // `4k` 这种多半是视频/图片规格而不是上下文；4k 以下不当窗口用 → 走兜底
        assertEquals(AiContext.FALLBACK_WINDOW, AiContext.inferWindow("vision-model-4k"))
    }

    // ------------------------------------------------------ 撞上限后的自动收缩

    @Test
    fun shrinkOnOverflowUsesEvidenceFromLastSuccessfulCall() {
        // 猜 1M、实际 128k，而上一轮 120k 的请求明明成功了 → 一次就收到 120k（不用连撞三次）
        assertEquals(120_000, AiContext.shrinkOnOverflow(window = 1_000_000, lastGoodTokens = 120_000))
    }

    @Test
    fun shrinkOnOverflowPrefersTheLimitTheEndpointItselfStated() {
        // 端点自己报的上限是**唯一不用猜的数**，优先级必须高于一切推算
        assertEquals(
            1_048_576,
            AiContext.shrinkOnOverflow(window = 2_000_000, lastGoodTokens = 1_100_000, statedLimit = 1_048_576),
        )
        // 荒谬的"上限"不采信（有的端点会把别的数塞在同一句话里）
        assertEquals(500_000, AiContext.shrinkOnOverflow(window = 1_000_000, lastGoodTokens = 0, statedLimit = 3))
        assertEquals(500_000, AiContext.shrinkOnOverflow(window = 1_000_000, lastGoodTokens = 0, statedLimit = 99_999_999))
    }

    @Test
    fun parseStatedLimitReadsTheRealDeepSeekErrorBody() {
        // 真实报错原文（`_probe_context_overflow.py` 打出来的，一个字没改）
        val body = """{"error":{"message":"This model's maximum context length is 1048576 tokens. """ +
            """However, you requested 1200006 tokens (1200005 in the messages, 1 in the completion). """ +
            """Please reduce the length of the messages or completion.","type":"invalid_request_error",""" +
            """"param":null,"code":"invalid_request_error"}}"""
        assertEquals(1_048_576, AiContext.parseStatedLimit(body))
        // 没有这个数就说没有（别硬凑一个出来）
        assertEquals(null, AiContext.parseStatedLimit("""{"error":{"message":"Model Not Exist"}}"""))
        assertEquals(null, AiContext.parseStatedLimit(""))
        assertEquals(null, AiContext.parseStatedLimit(null))
    }

    @Test
    fun shrinkOnOverflowNeverGrowsAndNeverGoesBelowFloor() {
        // 实证值比现有窗口还大（换过模型/统计口径不一致）→ 也不许变大，最多折半
        assertEquals(64_000, AiContext.shrinkOnOverflow(window = 128_000, lastGoodTokens = 999_999))
        // 实证值很小（如 2k）→ 不能一路收到 2k，否则每次提问都得压缩，压到没法干活
        assertEquals(AiContext.MIN_WINDOW, AiContext.shrinkOnOverflow(window = 1_000_000, lastGoodTokens = 2_000))
    }

    @Test
    fun shrinkOnOverflowHalvesWhenNoEvidenceYet() {
        // 本轮一次都没成功过（第一句就超长）→ 退化成折半
        assertEquals(500_000, AiContext.shrinkOnOverflow(window = 1_000_000, lastGoodTokens = 0))
        assertEquals(AiContext.MIN_WINDOW, AiContext.shrinkOnOverflow(window = 32_000, lastGoodTokens = 0))
    }

    @Test
    fun growOnEvidenceOnlyFiresWhenOurOwnCapWasTheBindingConstraint() {
        // 成功发出去 0.9×窗口的量 → 拦住我们的是自己的闸门，不是模型极限 → 翻倍
        assertEquals(256_000, AiContext.growOnEvidence(window = 128_000, lastGoodTokens = 115_200))
        // 普通小请求说明不了上限在哪 → 不许长大（否则会一路虚涨到不可能的值）
        assertEquals(null, AiContext.growOnEvidence(window = 128_000, lastGoodTokens = 5_000))
        assertEquals(null, AiContext.growOnEvidence(window = 128_000, lastGoodTokens = 0))
        // 封顶
        assertEquals(null, AiContext.growOnEvidence(window = AiContext.MAX_WINDOW, lastGoodTokens = AiContext.MAX_WINDOW))
    }

    @Test
    fun shrinkChainConvergesWithinMaxRetries() {
        // 这条钉的是"最坏情况能在 2 次重试内收敛"：猜的 128k、实际 32k（4 倍）
        var w = AiContext.inferWindow("acme-unknown")
        assertEquals(128_000, w)
        w = AiContext.shrinkOnOverflow(w, 0)
        assertEquals(64_000, w)
        w = AiContext.shrinkOnOverflow(w, 0)
        assertEquals("两次重试后必须落到 32k，正好是真实上限", 32_000, w)
    }

    @Test
    fun windowSelfHealsBothWaysWithoutTheUserChoosingAnything() {
        // 「不给用户选窗口」能成立的完整论证：一个来回里两个方向都被真实往返纠正
        // ① 猜小了（认不出的模型按 128k 兜底）→ 贴着上限成功一次 → 翻倍
        var w = AiContext.inferWindow("acme-new-llm")
        assertEquals(128_000, w)
        w = AiContext.growOnEvidence(w, 115_200)!!
        assertEquals(256_000, w)
        // ② 翻过头了 → 端点回 400 并写明真实上限 → 一次改准
        w = AiContext.shrinkOnOverflow(w, lastGoodTokens = 200_000, statedLimit = 204_800)
        assertEquals(204_800, w)
    }
}
