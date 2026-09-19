package com.tapmoay.sorders.ai

import kotlinx.coroutines.asCoroutineDispatcher
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.InputStream
import java.io.OutputStream
import java.net.InetAddress
import java.net.ServerSocket
import java.net.Socket
import java.util.Collections
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicInteger
import kotlin.concurrent.thread

/**
 * [LlmClient] 流式链路的**集成测试**：真起一个 HTTP 服务端、真走 OkHttp、真解析 SSE。
 *
 * ### 为什么不能只靠 [AiStreamTest]
 * [AiStreamTest] 测的是"给我一串分片行，累加器算得对不对"——它验不到：
 * - `stream:true` 与 `stream_options` 到底有没有**真的发出去**；
 * - 响应体是不是**边到边解**（而不是等整段读完才解，那流式就白做了）；
 * - 两条降级路径（端点不认 `stream_options` / 端点无视 `stream:true`）通不通；
 * - 增量是不是在**调用方的协程上下文**里回调（聊天页要直接写 Compose state）。
 *
 * 这四件事全在 `LlmClient` 里，而它们**不需要真 key 也能验**——起个本机假端点就够了。
 * 这正是把协议形状钉进测试的价值：以后谁把 `stream_options` 挪走、或把 `withContext(delivery)`
 * 删了，这里立刻红。
 *
 * ### 为什么手写 HTTP 服务端
 * `com.sun.net.httpserver` **不在 Android 单测的编译类路径里**（编译期报 Unresolved reference
 * 'sun'），而引入 MockWebServer 要加依赖（本项目当前只有 junit）。
 * 这里只要"按行写、每行 flush、最后关连接"，`ServerSocket` 足够，而且能精确控制逐片时序——
 * 那恰恰是"证明这是真流式"所必需的。
 */
class LlmStreamingIntegrationTest {

    private var fake: FakeHttpServer? = null

    @After
    fun tearDown() {
        fake?.stop()
    }

    private fun cfg(port: Int) = LlmConfig(
        baseUrl = "http://127.0.0.1:$port/v1",
        apiKey = "sk-unit-test-key",
        model = "deepseek-flash",
    )

    private val port: Int get() = fake!!.port

    // ==================================================================
    //  假服务端
    // ==================================================================

    /** 服务端的一种应答。 */
    private sealed interface Reply {
        /** 逐行写 SSE；每写一行就 flush 一次，并回调 [onChunk]。 */
        class Sse(val lines: List<String>, val onChunk: (Int) -> Unit) : Reply

        /** 一次性回一个完整响应（用于 400 / 非流式兜底两个场景）。 */
        class Whole(val status: Int, val contentType: String, val body: String) : Reply
    }

    private class FakeHttpServer(private val route: (String) -> Reply) {
        /** 收到过的请求体（断言"到底发了什么字段"用）。 */
        val bodies: MutableList<String> = Collections.synchronizedList(mutableListOf())

        private val socket = ServerSocket(0, 16, InetAddress.getByName("127.0.0.1"))
        val port: Int get() = socket.localPort

        fun start() {
            thread(isDaemon = true, name = "fake-llm-server") {
                while (!socket.isClosed) {
                    val conn = try {
                        socket.accept()
                    } catch (e: Exception) {
                        return@thread // stop() 关掉了 socket
                    }
                    thread(isDaemon = true) { serve(conn) }
                }
            }
        }

        fun stop() {
            try {
                socket.close()
            } catch (_: Exception) {
            }
        }

        private fun serve(conn: Socket) {
            conn.use { s ->
                val input = s.getInputStream().buffered()
                val requestLine = readHeaderLine(input) ?: return
                var contentLength = 0
                while (true) {
                    val h = readHeaderLine(input) ?: break
                    if (h.isEmpty()) break
                    if (h.lowercase().startsWith("content-length:")) {
                        contentLength = h.substringAfter(':').trim().toIntOrNull() ?: 0
                    }
                }
                val body = if (contentLength > 0) String(input.readNBytes(contentLength)) else ""
                bodies += body

                val out = s.getOutputStream()
                when (val r = route(body)) {
                    is Reply.Whole -> {
                        val bytes = r.body.toByteArray()
                        out.write(
                            (
                                "HTTP/1.1 ${r.status} X\r\n" +
                                    "Content-Type: ${r.contentType}\r\n" +
                                    "Content-Length: ${bytes.size}\r\n" +
                                    "Connection: close\r\n\r\n"
                                ).toByteArray(),
                        )
                        out.write(bytes)
                        out.flush()
                    }

                    is Reply.Sse -> {
                        // 无 Content-Length + Connection: close：响应体到连接关闭为止。
                        // 每行 flush 一次，客户端才能"边到边解"——这正是要验的东西。
                        out.write(
                            (
                                "HTTP/1.1 200 OK\r\n" +
                                    "Content-Type: text/event-stream\r\n" +
                                    "Connection: close\r\n\r\n"
                                ).toByteArray(),
                        )
                        out.flush()
                        r.lines.forEachIndexed { i, line ->
                            out.write(("data: " + line + "\n\n").toByteArray())
                            out.flush()
                            r.onChunk(i + 1)
                        }
                    }
                }
            }
        }

        /** 读一行（以 `\n` 结束），去掉尾部 `\r`。EOF 返回 null。 */
        private fun readHeaderLine(input: InputStream): String? {
            val sb = StringBuilder()
            while (true) {
                val b = input.read()
                if (b < 0) return sb.takeIf { it.isNotEmpty() }?.toString()
                if (b == '\n'.code) return sb.toString().removeSuffix("\r")
                sb.append(b.toChar())
            }
        }
    }

    // ==================================================================
    //  分片构造
    // ==================================================================

    private fun textDelta(text: String) =
        """{"choices":[{"index":0,"delta":{"content":"$text"},"finish_reason":null}]}"""

    /** JSON 字符串转义。**必须做**：工具参数本身就是 JSON（`{"act`），原样塞进去会破坏外层 JSON。 */
    private fun esc(s: String) = s.replace("\\", "\\\\").replace("\"", "\\\"")

    private fun toolChunk(index: Int, id: String?, name: String?, args: String?) = buildString {
        append("""{"choices":[{"index":0,"delta":{"tool_calls":[{"index":$index""")
        id?.let { append(""","id":"${esc(it)}"""") }
        if (name != null || args != null) {
            append(""","function":{""")
            name?.let { append(""""name":"${esc(it)}"""") }
            if (name != null && args != null) append(",")
            args?.let { append(""""arguments":"${esc(it)}"""") }
            append("}")
        }
        append(""","type":"function"}]},"finish_reason":null}]}""")
    }

    /**
     * "第一片是否在服务端继续往下写之前就被客户端消费掉了"的探针。
     *
     * 这是**不靠计时**地证明"真流式"的办法：服务端写完第一片就停住等它。
     * - 真流式 → 客户端解析出增量 → 回调 → [clientConsumed] → 服务端放行 → [ackedBeforeTimeout] = true；
     * - 假流式（读完整段响应体才解析）→ 没人 countDown → 服务端等超时 → false。
     *
     * 用超时而不是永久等待，是为了让"实现退化成非流式"表现为**断言失败**，
     * 而不是把整个测试挂死。
     */
    private class FirstChunkGate {
        private val latch = java.util.concurrent.CountDownLatch(1)
        val ackedBeforeTimeout = java.util.concurrent.atomic.AtomicBoolean(false)

        fun clientConsumed() = latch.countDown()

        fun serverWaitsForClient() {
            ackedBeforeTimeout.set(latch.await(10, java.util.concurrent.TimeUnit.SECONDS))
        }
    }

    /**
     * 安排一个按分片回 SSE 的假端点。
     *
     * @param firstChunkGate 非 null 时启用"第一片停住等客户端"的流式探针（见 [FirstChunkGate]）。
     */
    private fun serveSse(
        chunks: List<String> = emptyList(),
        toolChunks: List<String> = emptyList(),
        usageLine: String? = null,
        rejectStreamOptionsTimes: Int = 0,
        plainJsonInsteadOfSse: Boolean = false,
        firstChunkGate: FirstChunkGate? = null,
    ): AtomicInteger {
        val chunkCounter = AtomicInteger(0)
        val rejectSeen = AtomicInteger(0)
        fake = FakeHttpServer { body ->
            // 降级路径 ①：端点不认 stream_options → 400 且点名它
            if (rejectStreamOptionsTimes > 0 &&
                body.contains("stream_options") &&
                rejectSeen.incrementAndGet() <= rejectStreamOptionsTimes
            ) {
                return@FakeHttpServer Reply.Whole(
                    400,
                    "application/json",
                    """{"error":{"message":"Unrecognized request argument supplied: stream_options","code":"400"}}""",
                )
            }
            // 降级路径 ②：端点无视 stream:true，回了个普通的非流式响应
            if (plainJsonInsteadOfSse) {
                return@FakeHttpServer Reply.Whole(
                    200,
                    "application/json",
                    """{"choices":[{"message":{"role":"assistant","content":"这是非流式的回答"}}],""" +
                        """"usage":{"prompt_tokens":11,"completion_tokens":7,"total_tokens":18}}""",
                )
            }
            val lines = buildList {
                chunks.forEach { add(textDelta(it)) }
                addAll(toolChunks)
                usageLine?.let { add(it) }
                add("[DONE]")
            }
            Reply.Sse(lines) { n ->
                chunkCounter.set(n)
                if (n == 1) firstChunkGate?.serverWaitsForClient()
            }
        }
        fake!!.start()
        return chunkCounter
    }

    private fun bodyOf(index: Int): String = fake!!.bodies[index]

    // ==================================================================
    //  1. 基本流式
    // ==================================================================

    @Test
    fun streamingDeliversIncrementallyAndReturnsFullMessage() = runBlocking {
        // 每片都超过 FLUSH_CHARS，保证「攒够就提交」这条路被走到
        val a = "一".repeat(ChatStreamAccumulator.FLUSH_CHARS)
        val b = "二".repeat(ChatStreamAccumulator.FLUSH_CHARS)
        val c = "三".repeat(ChatStreamAccumulator.FLUSH_CHARS)
        serveSse(chunks = listOf(a, b, c))

        val emissions = mutableListOf<String>()
        val result = LlmClient().completeStreaming(cfg(port), listOf(ChatMessage.user("问")), emptyList()) {
            emissions += it
        }

        assertTrue("必须是成功", result is ChatResult.Success)
        assertEquals("最终正文必须是三片之和", a + b + c, (result as ChatResult.Success).message.content)
        assertEquals("必须多次增量交付（一次性给全量就说明没在流）", 3, emissions.size)
        assertEquals("增量拼起来必须等于全文", a + b + c, emissions.joinToString(""))
    }

    @Test
    fun textIsDeliveredWhileTheStreamIsStillOpen() = runBlocking {
        // 这一条是"真流式"的**确定性**证明（不靠计时）：服务端写完第一片就停住，
        // 等客户端把这一片的增量交出来才继续写剩下的。
        // 若实现是"读完整个响应体再解析"，第一个增量永远不会来 → 闩锁超时 → 断言失败。
        val big = "字".repeat(ChatStreamAccumulator.FLUSH_CHARS)
        val gate = FirstChunkGate()
        serveSse(chunks = listOf(big, big, big), firstChunkGate = gate)

        val emissions = mutableListOf<String>()
        val r = LlmClient().completeStreaming(cfg(port), listOf(ChatMessage.user("问")), emptyList()) {
            emissions += it
            gate.clientConsumed()
        }

        assertTrue(r is ChatResult.Success)
        assertEquals("三片都要收到", big + big + big, (r as ChatResult.Success).message.content)
        assertTrue(
            "第一片必须在服务端继续往下写之前就交付——否则说明是读完整段响应体才开始解析的",
            gate.ackedBeforeTimeout.get(),
        )
        assertEquals("第一段交付的就是第一片", big, emissions.first())
    }

    @Test
    fun requestAsksForUsageAndEnablesStreaming() = runBlocking {
        serveSse(chunks = listOf("答".repeat(ChatStreamAccumulator.FLUSH_CHARS)))
        LlmClient().completeStreaming(cfg(port), listOf(ChatMessage.user("问")), emptyList()) {}

        val body = bodyOf(0)
        assertTrue("必须开流：$body", body.contains("\"stream\":true"))
        assertTrue("必须向服务端要 usage（否则上下文预算退化成瞎猜）：$body", body.contains("stream_options"))
        assertTrue(body.contains("\"include_usage\":true"))
    }

    @Test
    fun usageFromTailChunkIsSurfaced() = runBlocking {
        serveSse(
            chunks = listOf("答".repeat(ChatStreamAccumulator.FLUSH_CHARS)),
            usageLine = """{"choices":[],"usage":{"prompt_tokens":4321,"completion_tokens":12,"total_tokens":4333}}""",
        )
        val r = LlmClient().completeStreaming(cfg(port), listOf(ChatMessage.user("问")), emptyList()) {}
        assertEquals("usage 必须透出来（40% 压缩阈值靠它）", 4321, (r as ChatResult.Success).usage?.promptTokens)
    }

    // ==================================================================
    //  2. 工具调用（分片归并）
    // ==================================================================

    @Test
    fun fragmentedToolCallsSurviveTheRoundTrip() = runBlocking {
        serveSse(
            chunks = listOf("先查一下。".repeat(5)),
            toolChunks = listOf(
                toolChunk(0, "call_1", "read_data", """{"act"""),
                toolChunk(0, null, null, """ion":"orders.list_orders"}"""),
                toolChunk(1, "call_2", "inventory_alerts", """{"limit":3}"""),
            ),
        )
        val r = LlmClient().completeStreaming(cfg(port), listOf(ChatMessage.user("问")), emptyList()) {}
        val calls = (r as ChatResult.Success).message.toolCalls!!
        assertEquals("两个工具调用都要活下来", 2, calls.size)
        assertEquals("""{"action":"orders.list_orders"}""", calls[0].function.arguments)
        assertEquals("inventory_alerts", calls[1].function.name)
    }

    // ==================================================================
    //  3. 两条降级路径（"答不出来"不能是流式带来的新失败）
    // ==================================================================

    @Test
    fun streamOptionsRejectionFallsBackAndIsRemembered() = runBlocking {
        serveSse(
            chunks = listOf("答".repeat(ChatStreamAccumulator.FLUSH_CHARS)),
            rejectStreamOptionsTimes = 1,
        )
        var remembered: String? = null
        val client = LlmClient(onStreamOptionsUnsupported = { remembered = it })

        val r = client.completeStreaming(cfg(port), listOf(ChatMessage.user("问")), emptyList()) {}

        assertTrue("去掉 stream_options 重试后必须成功", r is ChatResult.Success)
        assertNotNull("必须把「这个地址不认它」记下来（否则每次提问都白打一次）", remembered)
        assertEquals("应当恰好打两次：一次被拒 + 一次降级", 2, fake!!.bodies.size)
        assertFalse("第二次不能再发 stream_options", bodyOf(1).contains("stream_options"))
        assertTrue("但流式本身要保留", bodyOf(1).contains("\"stream\":true"))
    }

    @Test
    fun knownUnsupportedHostSkipsTheFieldUpFront() = runBlocking {
        // 能力缓存命中时**不该**再白发一次注定 400 的请求
        serveSse(chunks = listOf("答".repeat(ChatStreamAccumulator.FLUSH_CHARS)))
        val client = LlmClient(streamOptionsUnsupported = { true })
        val r = client.completeStreaming(cfg(port), listOf(ChatMessage.user("问")), emptyList()) {}

        assertTrue(r is ChatResult.Success)
        assertEquals("已知不认 → 只打一次", 1, fake!!.bodies.size)
        assertFalse(bodyOf(0).contains("stream_options"))
    }

    @Test
    fun endpointIgnoringStreamFlagFallsBackToPlainJson() = runBlocking {
        serveSse(plainJsonInsteadOfSse = true)
        val emissions = mutableListOf<String>()
        val r = LlmClient().completeStreaming(cfg(port), listOf(ChatMessage.user("问")), emptyList()) {
            emissions += it
        }
        assertTrue("端点无视 stream 也必须答得出来", r is ChatResult.Success)
        assertEquals("这是非流式的回答", (r as ChatResult.Success).message.content)
        assertEquals("非流式兜底拿不到增量，不该硬凑", 0, emissions.size)
        assertEquals("usage 也要从非流式响应里读出来", 11, r.usage?.promptTokens)
    }

    // ==================================================================
    //  4. 交付线程契约（聊天页会直接写 Compose state）
    // ==================================================================

    @Test
    fun deltasAreDeliveredOnTheCallersDispatcher() = runBlocking {
        val big = "字".repeat(ChatStreamAccumulator.FLUSH_CHARS)
        serveSse(chunks = listOf(big, big))

        val executor = Executors.newSingleThreadExecutor { r -> Thread(r, "caller-thread") }
        val callerCtx = executor.asCoroutineDispatcher()
        val threads = Collections.synchronizedList(mutableListOf<String>())
        try {
            val r = runBlocking(callerCtx) {
                LlmClient().completeStreaming(cfg(port), listOf(ChatMessage.user("问")), emptyList()) {
                    threads += Thread.currentThread().name
                }
            }
            assertTrue(r is ChatResult.Success)
            assertTrue("必须收到过增量", threads.isNotEmpty())
            assertTrue(
                "增量必须在调用方上下文的线程上回调，实际=$threads（从 IO 线程回调会踩 Compose 的线程约束）",
                // 线程名带上 @coroutine#N 后缀（Kotlin 协程调试信息），所以用前缀比对
                threads.all { it.startsWith("caller-thread") },
            )
        } finally {
            executor.shutdown()
        }
    }

    // ==================================================================
    //  5. 非流式路径不许被改坏（它仍是降级兜底 + 压缩器在用的那条）
    // ==================================================================

    @Test
    fun plainCompleteStillWorksAndNeverSendsStreamOptions() = runBlocking {
        serveSse(plainJsonInsteadOfSse = true)
        val r = LlmClient().complete(cfg(port), listOf(ChatMessage.user("问")), emptyList())
        assertTrue(r is ChatResult.Success)
        val body = bodyOf(0)
        assertFalse("非流式不许下发 stream_options（自选字段多一个多一分被拒风险）", body.contains("stream_options"))
        assertFalse(body.contains("\"stream\":true"))
    }
}
