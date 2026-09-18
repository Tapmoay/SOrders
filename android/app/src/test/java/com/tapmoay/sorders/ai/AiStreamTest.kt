package com.tapmoay.sorders.ai

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 流式解析（[ChatStreamAccumulator]）与流式净化（[AiStreamingText]）的纯逻辑测试。
 *
 * ### 为什么这两个类值得单独一个测试文件
 * 它们是**平时不跑、一出事才跑**的那类代码：只在用户正好在聊天、而且服务端的
 * 分片**恰好切在某个位置**时才出问题。手工测覆盖不到——你没法命令服务端
 * "把 `user_id 122` 从中间切开发"。而一旦真的出问题，表现是：
 * - 回答缺字（`arguments` 被覆盖）→ 工具少执行一个，用户拿到半截结论；
 * - 编号漏到屏幕上（净化被分片绕过）→ 踩到本项目最硬的那条红线。
 *
 * 所以这里全部用**构造的分片序列**驱动，不联网、不依赖模拟器。
 */
class AiStreamTest {

    // ------------------------------------------------------------------ 工具

    private fun chunk(json: String) = "data: $json"

    /** 正文分片。 */
    private fun textChunk(text: String) =
        chunk("""{"choices":[{"index":0,"delta":{"content":${quote(text)}},"finish_reason":null}]}""")

    /** 工具调用分片（arguments 是这一片的内容）。 */
    private fun toolChunk(index: Int, id: String?, name: String?, args: String?) = chunk(
        buildString {
            append("""{"choices":[{"index":0,"delta":{"tool_calls":[{"index":$index""")
            if (id != null) append(""","id":${quote(id)}""")
            if (name != null || args != null) {
                append(""","function":{""")
                if (name != null) append(""""name":${quote(name)}""")
                if (name != null && args != null) append(",")
                if (args != null) append(""""arguments":${quote(args)}""")
                append("}")
            }
            append(""","type":"function"}]},"finish_reason":null}]}""")
        },
    )

    private fun quote(s: String) = "\"" + s.replace("\\", "\\\\").replace("\"", "\\\"").replace("\n", "\\n") + "\""

    /** 喂一批行，返回累加器。 */
    private fun feed(vararg lines: String): ChatStreamAccumulator {
        val acc = ChatStreamAccumulator()
        lines.forEach { acc.feed(it, nowMs = 0L) }
        return acc
    }

    // ======================================================== 正文累加

    @Test
    fun contentDeltasAccumulateIntoOneMessage() {
        val acc = feed(
            textChunk("本月"),
            textChunk("下单最多的是"),
            textChunk("城东水果批发。"),
        )
        assertEquals("本月下单最多的是城东水果批发。", acc.contentText())
        assertEquals("本月下单最多的是城东水果批发。", acc.toMessage().content)
    }

    @Test
    fun emptyTextDeltasAreIgnoredNotTreatedAsContent() {
        // 很多端点在工具轮会发 content:"" 的占位分片。若把它当成"有正文"，
        // 就会出现 content=null 与 content="" 的摇摆，某些端点会因此 400。
        val acc = feed(textChunk(""), textChunk("好的"))
        assertEquals("好的", acc.contentText())
        assertTrue(acc.toMessage().reasoningContent == null)
    }

    @Test
    fun messageContentIsNullWhenOnlyToolCallsArrived() {
        // 只调工具的那一轮本来就没有正文；给 null 而不是空串（协议里 content 应当缺省）
        val acc = feed(toolChunk(0, "call_1", "read_data", """{"action":"orders.list_orders"}"""), chunk("[DONE]"))
        val msg = acc.toMessage()
        assertNull("没有正文时 content 必须是 null", msg.content)
        assertEquals(1, msg.toolCalls?.size)
    }

    // ======================================================== 工具调用归并

    @Test
    fun toolCallArgumentsSplitAcrossChunksAreConcatenated() {
        // ⚠️ 本文件最重要的一条：arguments 是**一片片拼**出来的，绝不能覆盖。
        // 覆盖的表现是"模型明明要查订单，参数却只拿到半截 JSON" → 工具报参数错误。
        val acc = feed(
            toolChunk(0, "call_1", "read_data", """{"act"""),
            toolChunk(0, null, null, """ion":"or"""),
            toolChunk(0, null, null, """ders.list_orders"}"""),
        )
        val call = acc.toMessage().toolCalls!!.single()
        assertEquals("read_data", call.function.name)
        assertEquals("""{"action":"orders.list_orders"}""", call.function.arguments)
        assertEquals("call_1", call.id)
    }

    @Test
    fun multipleToolCallsAreKeptSeparateByIndex() {
        // 漏掉 index 归并 → 两个工具会互相覆盖，表现成"只执行了一个"
        val acc = feed(
            toolChunk(0, "call_a", "read_data", """{"action":"a"""),
            toolChunk(1, "call_b", "inventory_alerts", """{"limit":5}"""),
            toolChunk(0, null, null, """.list"}"""),
        )
        val calls = acc.toMessage().toolCalls!!
        assertEquals("两个工具调用都要在", 2, calls.size)
        assertEquals("call_a", calls[0].id)
        assertEquals("""{"action":"a.list"}""", calls[0].function.arguments)
        assertEquals("call_b", calls[1].id)
        assertEquals("""{"limit":5}""", calls[1].function.arguments)
    }

    @Test
    fun toolCallWithoutIdGetsASynthesizedOne() {
        // 个别兼容端点不发 id。没有它，后面的 role="tool" 消息无法配对 → 服务端 400
        val acc = feed(toolChunk(0, null, "calculate", """{"expr":"1+1"}"""))
        val call = acc.toMessage().toolCalls!!.single()
        assertTrue("必须补一个非空 id，实际=${call.id}", call.id.isNotEmpty())
    }

    @Test
    fun nameArrivingTwiceIsNotDuplicated() {
        // 名字按协议只在首个分片出现，但确有端点重复下发。重复拼会变成 "read_dataread_data"
        val acc = feed(
            toolChunk(0, "call_1", "read_data", null),
            toolChunk(0, null, "read_data", """{"action":"x"}"""),
        )
        assertEquals("read_data", acc.toMessage().toolCalls!!.single().function.name)
    }

    // ======================================================== 思考 / 用量 / 收尾

    @Test
    fun reasoningIsAccumulatedAndNeverMixedIntoContent() {
        // 思考过程必须与正文**分开**：混进去会污染回答，而且它不能被回传给服务端
        val acc = ChatStreamAccumulator()
        acc.feed(
            chunk("""{"choices":[{"index":0,"delta":{"reasoning_content":"先看日期…"},"finish_reason":null}]}"""),
            nowMs = 0L,
        )
        acc.feed(
            chunk("""{"choices":[{"index":0,"delta":{"reasoning_content":"再查订单。"},"finish_reason":null}]}"""),
            nowMs = 0L,
        )
        acc.feed(textChunk("结论：9 单"), nowMs = 0L)

        assertEquals("先看日期…再查订单。", acc.reasoningText())
        assertEquals("结论：9 单", acc.contentText())
        assertEquals("先看日期…再查订单。", acc.toMessage().reasoningContent)
    }

    @Test
    fun usageAndFinishReasonAreCapturedFromTheTailChunk() {
        val acc = feed(
            textChunk("答"),
            chunk("""{"choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}"""),
            // 要了 stream_options 时，usage 在**最后**一个分片里，且该分片 choices 为空
            chunk("""{"choices":[],"usage":{"prompt_tokens":1234,"completion_tokens":56,"total_tokens":1290}}"""),
        )
        assertEquals("stop", acc.finishReason)
        assertEquals(1234, acc.usage?.promptTokens)
        assertEquals(1290, acc.usage?.totalTokens)
    }

    @Test
    fun doneSentinelStopsTheLoop() {
        val acc = ChatStreamAccumulator()
        assertTrue(acc.feed(textChunk("第一段"), nowMs = 0L))
        assertFalse("读到 [DONE] 应当让调用方停止读流", acc.feed(chunk("[DONE]"), nowMs = 0L))
        assertTrue(acc.done)
    }

    @Test
    fun nonDataLinesAreIgnored() {
        // SSE 里还会有 event: / id: / 注释行 / 空行；本功能不需要它们
        val acc = ChatStreamAccumulator()
        acc.feed("", nowMs = 0L)
        acc.feed(": keep-alive", nowMs = 0L)
        acc.feed("event: message", nowMs = 0L)
        acc.feed("id: 3", nowMs = 0L)
        acc.feed(textChunk("正文"), nowMs = 0L)
        assertEquals("正文", acc.contentText())
        assertFalse("只有 data: 行才算 SSE 数据", acc.sawSseData && acc.raw.isEmpty())
    }

    @Test
    fun brokenChunkDoesNotKillTheWholeStream() {
        // 单个分片解析失败（网络截断、端点多发怪东西）不能中断整个回答，后面的分片还要收
        val acc = ChatStreamAccumulator()
        acc.feed(textChunk("前半"), nowMs = 0L)
        acc.feed("data: {\"choices\":[{\"index\":0,", nowMs = 0L) // 半截 JSON
        acc.feed(textChunk("后半"), nowMs = 0L)
        assertEquals("前半后半", acc.contentText())
    }

    @Test
    fun sawSseDataIsFalseWhenEndpointIgnoredStreamFlag() {
        // 端点无视 stream:true、直接回了普通 JSON —— 上层据此回退到非流式解析
        val acc = ChatStreamAccumulator()
        acc.feed("""{"choices":[{"message":{"role":"assistant","content":"你好"}}]}""", nowMs = 0L)
        assertFalse(acc.sawSseData)
        assertTrue("原始响应体要留着，供非流式兜底解析", acc.raw.toString().contains("你好"))
    }

    // ======================================================== 提交节流

    @Test
    fun smallDeltasAreHeldUntilTheTimeThreshold() {
        // 模型慢慢吐字时，不能每个字都刷一次 UI（Compose 会疯狂重组）
        val acc = ChatStreamAccumulator()
        acc.feed(textChunk("单"), nowMs = 0L)
        assertEquals("刚过一个字，不该提交", "", acc.pendingForFlush(nowMs = 10L))
        val out = acc.pendingForFlush(nowMs = ChatStreamAccumulator.FLUSH_INTERVAL_MS + 1)
        assertEquals("单", out)
    }

    @Test
    fun enoughCharactersFlushImmediately() {
        val acc = ChatStreamAccumulator()
        val long = "一".repeat(ChatStreamAccumulator.FLUSH_CHARS)
        acc.feed(textChunk(long), nowMs = 0L)
        assertEquals("攒够字数应当立刻提交，不必等时间", long, acc.pendingForFlush(nowMs = 1L))
    }

    @Test
    fun drainAllReturnsWhateverIsLeft() {
        val acc = ChatStreamAccumulator()
        acc.feed(textChunk("尾"), nowMs = 0L)
        assertEquals("强制提交必须把待发的都取走", "尾", acc.drainAll(nowMs = 0L))
        assertEquals("取过之后不该再重复给", "", acc.drainAll(nowMs = 0L))
    }

    // ======================================================== 流式净化

    @Test
    fun splitIdPhraseNeverLeaksToTheScreen() {
        // ⚠️ 这条钉的是「分片边界正好切开编号短语」这个必然会发生的情况。
        // 逐片净化是不安全的：单独看 "（user_id 1" 匹配不上，"22）" 也匹配不上，
        // 但那两段拼起来就是一个编号。留尾机制必须把它整个罩住。
        val emitter = AiStreamingText()
        val seen = StringBuilder()

        emitter.append("（user_id 1")?.let { seen.append(it.text) }
        emitter.append("22）")?.let { seen.append(it.text) }
        emitter.finish()?.let {
            if (it.replace) {
                seen.setLength(0)
            }
            seen.append(it.text)
        }

        val shown = seen.toString()
        assertFalse("编号绝不许出现在屏幕上，实际=$shown", shown.contains("user_id"))
        assertFalse("编号数字也不许出现，实际=$shown", shown.contains("122"))
    }

    @Test
    fun normalIdPhraseInsideOneChunkIsRemoved() {
        val emitter = AiStreamingText()
        val out = StringBuilder()
        emitter.append("这单是（user_id 122）的，金额 1584.00 元")
        emitter.finish()?.let { out.append(it.text) }
        val shown = out.toString() + emitter.settledText()
        assertFalse("编号要抹掉", shown.contains("user_id"))
        assertTrue("金额必须原样保留（净化器刻意不碰它）", shown.contains("1584.00"))
    }

    @Test
    fun plainTextPassesThroughUnchanged() {
        val emitter = AiStreamingText()
        val text = "本月下单最多的货主是城东水果批发，共 5 单、2806.00 元。"
        emitter.append(text)
        emitter.finish()
        assertEquals("干净文本一个字符都不该被改动", text, emitter.settledText())
    }

    @Test
    fun sanitizerRewritingAlreadyEmittedTextProducesReplace() {
        // holdBack 调小以构造"短语跨过留尾边界"的场景：
        // 先按旧前缀吐了一截，随后发现整段其实是一个编号短语 → 必须整段替换，
        // 否则屏幕上会留着 "user_" 这种半截垃圾。
        val emitter = AiStreamingText(holdBack = 4)
        val first = emitter.append("user_id 1")
        assertEquals("user_", first?.text)
        assertEquals(false, first?.replace)

        val second = emitter.append("22 元")
        assertTrue("净化改写了已发出的内容时必须整段替换", second?.replace == true)
        assertEquals("替换后的内容里不能有编号残留", "", second?.text)
    }

    @Test
    fun finishFlushesTheHeldBackTail() {
        // 留尾必须在流结束时交出去，否则回答的结尾会缺二十几个字
        val emitter = AiStreamingText()
        val tail = "城东水果批发"
        emitter.append(tail)
        assertNull("还没到留尾长度，先攒着", emitter.append(""))
        val last = emitter.finish()
        assertTrue("收尾必须把尾巴交出来，实际=$last", last != null && last.text.isNotEmpty())
        assertEquals(tail, emitter.settledText())
    }

    @Test
    fun settledTextTracksEmittedContentExactly() {
        val emitter = AiStreamingText()
        val text = "第一句。" + "第二句写得长一些，用来凑过留尾的二十四个字。" + "第三句。"
        emitter.append(text)
        emitter.finish()
        assertEquals("最终交付的文本必须与原始文本逐字一致", text, emitter.settledText())
    }
}
