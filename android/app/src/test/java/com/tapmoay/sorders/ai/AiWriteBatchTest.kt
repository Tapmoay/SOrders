package com.tapmoay.sorders.ai

import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.put
import kotlinx.serialization.json.putJsonArray
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * **批量捷径**（[BatchWriteHandler]，用户 2026-09-21 要求）的纯逻辑测试。
 *
 * ### 为什么它值得单独一个文件
 * 用户要的是"既能量大地改、也别一个一条地调（费 token）"，所以这一层把 N 次写操作
 * **合成一张卡**。合成带来的每一个风险都是"不报错"的那一类：
 * - 少做一条（用户按"全做完了"理解）→ 逐行列出 + 逐条执行 + 逐条汇报；
 * - 把用户手里那张单条卡偷走（内层也会登记卡，取走时误伤）→ 只取"这一次新产生的"；
 * - 卡片答应了一件做不到的事（"会出现撤回"而批量没有撤回）→ 最后一行单独写；
 * - 校验一松就整批发出去（20 行里错 1 行）→ **任何一条不合法就整批不发**，并报第几条。
 *
 * 这里用的是**假处理器**（不碰后端、不碰仓库）：批量层唯一依赖的是
 * [AiWriteHandler] 这个接口 + [AiWritePreviewStore]，所以它可以在纯 JVM 里被钉死。
 */
class AiWriteBatchTest {

    // ============================================================ 测试替身

    /** 动作 id 用**真实**的 `products.update`：卡片最后一行要拿它去问 [AiRevert]。 */
    private val actionId = AiWrites.PRODUCTS_UPDATE

    private fun action(risk: AiWriteRisk = AiWriteRisk.MEDIUM) = AiWriteAction(
        id = actionId,
        title = "改商品",
        risk = risk,
        group = "商品",
        blurb = "改一个商品的字段",
        params = listOf(AiWriteParam("name", "商品名", required = true)),
    )

    /**
     * 假处理器：只做真处理器做的那三件事 —— 校验（名字对不上就拒绝）、造卡、落库。
     * payload 刻意**只由名字决定**，这样"内容相同的卡"能被 [AiWritePreviewStore] 的去重命中
     * （去掉重那条判据就测不出来了）。
     */
    private class FakeHandler(
        override val actionId: String,
        private val store: AiWritePreviewStore,
    ) : AiWriteHandler {
        val prepared = mutableListOf<String>()
        val committed = mutableListOf<Pair<String, String>>() // 名字 → 幂等键
        var failOn: String? = null
        var notePerRow: String? = null

        val newCards: Int get() = store.list().size

        override suspend fun prepare(params: JsonObject): AiWriteOutcome {
            val name = nameIn(params) ?: throw AiWriteArgException("缺少 name：商品名")
            if (name.contains("查无")) throw AiWriteArgException("系统里没有匹配「$name」的商品。")
            prepared += name
            val payload = buildJsonObject { put("name", name) }
            return AiWriteOutcome.NeedConfirm(
                store.offer(
                    actionId = actionId,
                    title = "改商品",
                    risk = AiWriteRisk.MEDIUM,
                    summary = "改商品：$name",
                    detailLines = listOf("商品：$name", "售价：10.00"),
                    payload = payload,
                ),
            )
        }

        override suspend fun commit(payload: JsonObject, idempotencyKey: String) {
            val name = nameIn(payload) ?: error("payload 缺 name")
            if (name == failOn) throw IllegalStateException("后端不接受这次的参数（第 $name 条）")
            committed += name to idempotencyKey
        }

        override fun commitNote(): String? = notePerRow
    }

    private fun svc(store: AiWritePreviewStore, inner: FakeHandler, risk: AiWriteRisk = AiWriteRisk.MEDIUM) =
        BatchWriteHandler(action(risk), inner, store)

    /** `params={"items":[{name:…},…]}` —— 模型那边就是这么传的。 */
    private fun items(vararg names: String): JsonObject = buildJsonObject {
        putJsonArray(BatchWriteHandler.BATCH_ITEMS) {
            names.forEach { n -> add(buildJsonObject { put("name", n) }) }
        }
    }

    private fun single(name: String): JsonObject = buildJsonObject { put("name", name) }

    private fun card(out: AiWriteOutcome): AiPendingWrite =
        (out as? AiWriteOutcome.NeedConfirm)?.pending ?: error("期望一张确认卡，实际是 $out")

    /**
     * 期望"这次申请被拒绝"，取回那句中文理由。
     *
     * ⚠️ 拒绝的形状是**抛 [AiWriteArgException]**（不是返回 `Rejected`）：那是 [AiWriteHandler]
     * 与 `AiWriteService.preview` 之间的既有契约 —— 处理器只管抛，服务层负责翻成给模型看的一句话。
     * 批量层是处理器，所以它照契约抛；这里的测试也就必须按契约接。
     */
    private suspend fun boom(block: suspend () -> AiWriteOutcome): String {
        val e = try {
            block()
            null
        } catch (x: Throwable) {
            x
        }
        val ax = e as? AiWriteArgException
            ?: error("期望被拒绝（AiWriteArgException），实际是 ${e ?: "正常返回"}")
        return ax.message.orEmpty()
    }

    // ============================================================ 一张卡，列全部行

    @Test
    fun `一次提交多条 → 只留一张卡，逐条列在上面`() = runBlocking {
        val store = AiWritePreviewStore()
        val inner = FakeHandler(actionId, store)
        val out = svc(store, inner).prepare(items("红富士苹果", "皇冠梨", "砂糖橘"))

        val c = card(out)
        // 内层那 3 张单条卡被取走：用户手边只有这一张，不会点错、也不会被挤掉别的卡
        assertEquals(1, store.list().size)
        assertEquals(1, inner.newCards)
        assertEquals("批量改商品：3 条", c.summary)
        // 每一条都在卡上（含它的明细）——用户核对的就是这张卡
        for (n in listOf("红富士苹果", "皇冠梨", "砂糖橘")) {
            assertTrue("卡上没有 $n：${c.detailLines}", c.detailLines.any { it.contains(n) })
        }
        // 卡片上的"条数"必须等于真正要执行的条数（少一条＝用户按"全做完了"理解）
        assertEquals(3, (c.payload[BatchWriteHandler.BATCH_PAYLOAD] as JsonArray).size)
    }

    @Test
    fun `不带 items 时原样走单条那条路（一个字都没变）`() = runBlocking {
        val store = AiWritePreviewStore()
        val inner = FakeHandler(actionId, store)
        val c = card(svc(store, inner).prepare(single("红富士苹果")))
        assertEquals("改商品：红富士苹果", c.summary)
        assertEquals(buildJsonObject { put("name", "红富士苹果") }, c.payload)
        assertNull(c.payload[BatchWriteHandler.BATCH_PAYLOAD])
    }

    @Test
    fun `条数多的时候每条压成一行，但仍然一条不少`() = runBlocking {
        val store = AiWritePreviewStore()
        val inner = FakeHandler(actionId, store)
        val names = (1..BatchWriteHandler.VERBOSE_MAX + 6).map { "商品$it" }
        val c = card(svc(store, inner).prepare(items(*names.toTypedArray())))
        assertEquals("批量改商品：${names.size} 条", c.summary)
        assertTrue("没有写清总数：${c.detailLines.first()}", c.detailLines.first().contains("共 ${names.size} 条"))
        for (n in names) assertTrue("压行之后少了 $n", c.detailLines.any { it.contains(n) })
        // 一行表头 + 每条一行；`detailLines` 还多一行"没有撤回"（暂存区统一追加的）
        assertEquals(names.size + 1, c.bodyLines.size)
        assertEquals(names.size + 2, c.detailLines.size)
    }

    // ============================================================ 宁可整批不发

    @Test
    fun `任何一条不合法 → 整批不发，且指出是第几条`() = runBlocking {
        val store = AiWritePreviewStore()
        val inner = FakeHandler(actionId, store)
        val reason = boom { svc(store, inner).prepare(items("红富士苹果", "查无此物", "砂糖橘")) }
        assertTrue("错误里必须带第几条：$reason", reason.contains("第 2 条"))
        assertTrue(reason.contains("查无此物"))
        assertEquals("一张卡都不许留", 0, store.list().size)
    }

    @Test
    fun `自动执行档（不用确认的那一档）不许批量 —— 它在预览阶段就已经写库了`() = runBlocking {
        val store = AiWritePreviewStore()
        val inner = FakeHandler(actionId, store)
        val reason = boom { svc(store, inner, risk = AiWriteRisk.AUTO_EXECUTABLE).prepare(items("甲", "乙")) }
        assertTrue(reason.contains("不需要确认"))
        assertEquals("内层一次都不许被调用", 0, inner.prepared.size)
    }

    @Test
    fun `items 不是数组、或数组是空的 → 直接拒绝`() = runBlocking {
        val store = AiWritePreviewStore()
        val inner = FakeHandler(actionId, store)
        val s = svc(store, inner)
        assertTrue(
            boom { s.prepare(buildJsonObject { put(BatchWriteHandler.BATCH_ITEMS, "红富士苹果") }) }
                .contains("数组"),
        )
        assertTrue(boom { s.prepare(items()) }.contains("空的"))
    }

    // ============================================================ 逐条执行、逐条汇报

    @Test
    fun `逐条执行：每一条拿到自己那份 payload 与自己的幂等键`() = runBlocking {
        val store = AiWritePreviewStore()
        val inner = FakeHandler(actionId, store)
        val s = svc(store, inner)
        val c = card(s.prepare(items("红富士苹果", "皇冠梨")))
        s.commit(c.payload, "ai-tok")
        assertEquals(listOf("红富士苹果", "皇冠梨"), inner.committed.map { it.first })
        assertEquals(listOf("ai-tok-0", "ai-tok-1"), inner.committed.map { it.second })
        assertEquals("这一批 2 条：成功 2 条，全部成功。", s.commitNote())
        assertNull("取走即清空", s.commitNote())
    }

    @Test
    fun `中间一条失败要如实汇报（成功几条、失败哪几条）`() = runBlocking {
        val store = AiWritePreviewStore()
        val inner = FakeHandler(actionId, store)
        inner.failOn = "皇冠梨"
        val s = svc(store, inner)
        val c = card(s.prepare(items("红富士苹果", "皇冠梨", "砂糖橘")))
        s.commit(c.payload, "ai-tok")
        val note = s.commitNote().orEmpty()
        assertTrue("没说成功几条：$note", note.contains("成功 2 条"))
        assertTrue("没说失败几条：$note", note.contains("失败 1 条"))
        assertTrue("没说是哪一条：$note", note.contains("#2"))
        assertTrue(note.contains("后端不接受"))
        // 失败那条**没有**落库，成功那两条**落了**
        assertEquals(listOf("红富士苹果", "砂糖橘"), inner.committed.map { it.first })
    }

    @Test
    fun `单条 payload 走 commit 时原样转发（批量层不插手）`() = runBlocking {
        val store = AiWritePreviewStore()
        val inner = FakeHandler(actionId, store)
        svc(store, inner).commit(buildJsonObject { put("name", "红富士苹果") }, "ai-tok")
        assertEquals(listOf("红富士苹果" to "ai-tok"), inner.committed)
    }

    // ============================================================ 卡片不许说假话

    @Test
    fun `批量卡最后一行说的是「没有撤回」，而不是单条那句「会出现撤回」`() = runBlocking {
        val store = AiWritePreviewStore()
        val inner = FakeHandler(actionId, store)
        // 前提：这个动作**单条**是可撤回的（否则这条判据是空的）
        val oneLine = AiWrites.undoLineOf(actionId)
        assertNotNull("前提不成立：$actionId 单条应当可撤回", oneLine)
        assertTrue(oneLine!!.contains("撤回"))

        val batch = card(svc(store, inner).prepare(items("红富士苹果", "皇冠梨")))
        assertEquals(AiWrites.BATCH_UNDO_NOTE, batch.detailLines.last())
        // 单条那一句**一次都不许出现**（照抄 detailLines 会把它复制 N 遍）
        assertFalse(batch.detailLines.any { it == oneLine })
        // 每一条自己的行里也不许带它
        assertFalse(batch.bodyLines.any { it.contains("会出现「撤回」") })
    }

    @Test
    fun `批量卡仍然是要确认的档位（批量永远不自动执行）`() = runBlocking {
        val store = AiWritePreviewStore()
        val inner = FakeHandler(actionId, store)
        val c = card(svc(store, inner).prepare(items("红富士苹果", "皇冠梨")))
        assertEquals(AiWriteRisk.MEDIUM, c.risk)
        assertTrue(c.risk.needsConfirm)
    }

    // ============================================================ 别把用户手里的卡偷走

    @Test
    fun `内层命中已有的卡时不许把它删掉（去重命中的是用户手里那张）`() = runBlocking {
        val store = AiWritePreviewStore()
        val inner = FakeHandler(actionId, store)
        // 用户手里已经有一张「改红富士苹果」的单条卡（内容与批量里第一条完全一样）
        val mine = card(inner.prepare(single("红富士苹果")))
        val s = svc(store, inner)
        val c = card(s.prepare(items("红富士苹果", "皇冠梨")))

        // 批量卡 + 用户那张，两张都在
        assertEquals(2, store.list().size)
        assertNotNull("用户手里那张被顺手删掉了", store.take(mine.token))
        // 批量卡自己还在，而且把这一条也列上了
        assertNotNull(store.take(c.token))
        assertTrue(c.detailLines.any { it.contains("红富士苹果") })
    }

    // ============================================================ 保留字

    @Test
    fun `payload 里的 items（退货明细）不会被当成批量`() {
        // 退货那两个动作的 payload 里本来就有 `items`：批量标记必须与它不同名，
        // 否则一次普通退货会被认成"一批"，然后按批逐条提交 —— 不报错，只是退错。
        val ret = buildJsonObject {
            put("order_id", 61)
            putJsonArray("items") { add(buildJsonObject { put("order_product_id", 1) }) }
        }
        assertFalse(isBatchPayload(ret))
        assertTrue(isBatchPayload(buildJsonObject { putJsonArray(BatchWriteHandler.BATCH_PAYLOAD) { } }))
    }

    @Test
    fun `每条明细都进卡，而「没撤回」那句只说一次`() = runBlocking {
        val store = AiWritePreviewStore()
        val inner = FakeHandler(actionId, store)
        val c = card(svc(store, inner).prepare(items("红富士苹果")))
        // 假处理器每条写两行明细（商品 + 售价）—— 它们必须原样进卡
        assertTrue(c.detailLines.contains("商品：红富士苹果"))
        assertTrue(c.detailLines.contains("售价：10.00"))
        // 暂存区统一追加的最后一行 = 批量那一句，且**只出现一次**
        assertEquals(listOf(AiWrites.BATCH_UNDO_NOTE), c.detailLines.filter { it == AiWrites.BATCH_UNDO_NOTE })
        assertEquals(c.bodyLines + AiWrites.BATCH_UNDO_NOTE, c.detailLines)
    }

    @Test
    fun `动作 id 与风险档原样来自动作表（批量层不自己定档）`() {
        val store = AiWritePreviewStore()
        val inner = FakeHandler(actionId, store)
        val h = BatchWriteHandler(action(AiWriteRisk.HIGH), inner, store)
        assertEquals(actionId, h.actionId)
    }
}

/** 测试里读参数的小助手（名字刻意起得直白，免得和 main 源集里那些 `JsonObject.str` 撞上）。 */
private fun nameIn(o: JsonObject): String? = (o["name"] as? JsonPrimitive)?.contentOrNull
