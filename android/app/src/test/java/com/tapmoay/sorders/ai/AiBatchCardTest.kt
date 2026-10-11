package com.tapmoay.sorders.ai

import java.lang.reflect.Proxy
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
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * **一张卡 = 一张长表格**（CHG-0119，用户 2026-10-11）的纯逻辑测试。
 *
 * ### 用户在真机上踩到的那件事
 * > 他那个确认卡呀，他不要一个（角色）一个（角色）的弹啊……如果是叫他批量干活的话，
 * > 那个确认卡也是只弹一个，只是那个表格卡是多个、长表格显示多个人，这样就省事。
 * > 不然你一弹一堆的确认卡，你全都要确认一遍，这样太麻烦了。
 *
 * 40 条批发商专属价被**一张张弹**之后，他在 14:21 连着看到 4 条
 * 「没写成：这张确认卡已经失效了（有效期 5 分钟…）」——**卡还没点就过期了，活儿白干**。
 *
 * ### 这个文件钉死的四件事
 * 1. 一次申请 N 条**只出一张卡**，卡上是一张**一个人一行**的长表格（[AiCardBatchTable]）；
 * 2. 表格超行 / 超列**不静默**：说清"只列了前 30 条"，写下去的仍然一条不少；
 * 3. 批量卡有效期 **30 分钟**（单条卡维持 5 分钟），数字是具名常量；
 * 4. 连点第二下 / 过期 / 被顶掉，三句话**分开说**、都是人话
 *    （⛔ 不许再出现「没写成：这张确认卡已经失效了」）。
 *
 * 这里用**假处理器**（不碰后端、不碰仓库）：批量层只依赖 [AiWriteHandler] 与
 * [AiWritePreviewStore]，所以整条"多条 → 一张卡 → 一张表"可以在纯 JVM 里被钉死。
 */
class AiBatchCardTest {

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
     * 假处理器：造卡 + 落库。`rows` 决定这条卡正文里出现哪些「标签：值」——
     * 批量表的列就是从这些行里抽出来的（真处理器写的也是这个形状）。
     */
    private class FakeHandler(
        override val actionId: String,
        private val store: AiWritePreviewStore,
        // ⚠️ [note] 必须排在 [rows] **前面**：本文件四处用的是尾随 lambda 写法
        //    (`FakeHandler(actionId, store) { i -> … }`)，而尾随 lambda 绑的是**最后一个**形参 ——
        //    顺序一反过来就是四条编译错误（Argument type mismatch: actual type is Function1…）。
        private val note: String? = null,
        private val rows: (Int) -> List<String> = { _ -> listOf("商品：甲", "售价：10.00") },
    ) : AiWriteHandler {
        var prepared = 0
        var failOn: String? = null

        override suspend fun prepare(params: JsonObject): AiWriteOutcome {
            val name = (params["name"] as? JsonPrimitive)?.contentOrNull
                ?: throw AiWriteArgException("缺少 name：商品名")
            val lines = rows(prepared)
            prepared += 1
            return AiWriteOutcome.NeedConfirm(
                store.card(
                    actionId = actionId,
                    summary = "改商品：$name",
                    detailLines = lines,
                    payload = buildJsonObject { put("name", name) },
                ),
            )
        }

        override suspend fun commit(payload: JsonObject, idempotencyKey: String) {
            val name = (payload["name"] as? JsonPrimitive)?.contentOrNull ?: error("payload 缺 name")
            if (name == failOn) throw IllegalStateException("后端不接受这一条")
        }

        override fun commitNote(): String? = note
    }

    /** 模型那边就是这么传批量的：`params={"items":[{name:…},…]}`（见 [BatchWriteHandler]）。 */
    private fun items(vararg names: String): JsonObject = buildJsonObject {
        putJsonArray(BatchWriteHandler.BATCH_ITEMS) {
            names.forEach { n -> add(buildJsonObject { put("name", n) }) }
        }
    }

    private fun batch(
        store: AiWritePreviewStore,
        inner: FakeHandler,
        risk: AiWriteRisk = AiWriteRisk.MEDIUM,
    ) = BatchWriteHandler(action(risk), inner, store)

    /** 走一遍 `items=[…]`，取回那一张批量卡（拿不到就直接炸，别让断言在后面才失败）。 */
    private suspend fun card(
        store: AiWritePreviewStore,
        inner: FakeHandler,
        vararg names: String,
    ): AiPendingWrite {
        val out = batch(store, inner).prepare(items(*names))
        return (out as? AiWriteOutcome.NeedConfirm)?.pending
            ?: error("期望一张确认卡，实际是 $out")
    }

    private fun sheetOf(card: AiPendingWrite): AiCardBatchTableSheet =
        card.table ?: error("批量卡必须带一张长表格（table 为 null 就是又退回逐张弹卡了）")

    // ============================================================ 一张卡，一张表

    @Test
    fun `一次申请五条只出一张卡_不是一条一张`() = runBlocking {
        val store = AiWritePreviewStore()
        val inner = FakeHandler(actionId, store)
        card(store, inner, "甲", "乙", "丙", "丁", "戊")
        assertEquals("五条只能留一张卡（多一张就是又回到'一弹一堆'）", 1, store.list().size)
    }

    @Test
    fun `表头是序号对象改前后_再跟上各条自己的字段`() = runBlocking {
        val store = AiWritePreviewStore()
        val inner = FakeHandler(actionId, store) { i ->
            val names = listOf("甲", "乙", "丙")
            listOf("商品：" + names[i], "原来：10.00 元 → 现在：12.00 元")
        }
        val sheet = sheetOf(card(store, inner, "甲", "乙", "丙"))
        assertEquals(
            listOf(
                AiCardBatchTable.INDEX_HEADER, AiCardBatchTable.SUBJECT_HEADER,
                AiCardBatchTable.CHANGE_HEADER, "商品", "原来",
            ),
            sheet.headers,
        )
        assertEquals("三个人三行", 3, sheet.rows.size)
        assertEquals(listOf("1", "2", "3"), sheet.rows.map { it[0] })
        assertEquals(listOf("改商品：甲", "改商品：乙", "改商品：丙"), sheet.rows.map { it[1] })
        // 第 3 列是用户真正要看的那一列：这一条到底把什么改成了什么
        assertEquals("10.00 元 → 现在：12.00 元", sheet.rows[0][2])
        assertTrue("每一行都得带箭头：${sheet.rows}", sheet.rows.all { it[2].contains("→") })
        assertEquals("不超限就不许多话", "", sheet.note)
    }

    @Test
    fun `某一列在这条上没有值时写破折号_不是空串`() = runBlocking {
        val store = AiWritePreviewStore()
        val inner = FakeHandler(actionId, store) { i ->
            if (i == 0) listOf("商品：甲", "售价：10.00") else listOf("商品：乙", "原价：9.00")
        }
        val sheet = sheetOf(card(store, inner, "甲", "乙"))
        assertEquals(listOf("商品", "售价", "原价"), sheet.headers.drop(3))
        assertEquals(listOf("甲", "10.00", AiCardBatchTable.MISSING), sheet.rows[0].drop(3))
        assertEquals(listOf("乙", AiCardBatchTable.MISSING, "9.00"), sheet.rows[1].drop(3))
    }

    @Test
    fun `超过三十条时表格说清只列了前三十条_但不是不干`() = runBlocking {
        val store = AiWritePreviewStore()
        val names = (1..32).map { "商品$it" }
        val inner = FakeHandler(actionId, store) { i ->
            listOf("商品：商品" + (i + 1), "原来：1 → 现在：2")
        }
        val sheet = sheetOf(card(store, inner, *names.toTypedArray()))
        assertEquals("表最多 30 行", AiCardBatchTable.MAX_ROWS, sheet.rows.size)
        assertEquals("最后一行是第 30 条", "30", sheet.rows.last()[0])
        assertTrue("超限必须说清条数：${sheet.note}", "共 32 条" in sheet.note)
        assertTrue("要说清只列了前 30 条：${sheet.note}", "只列了前 30 条" in sheet.note)
        assertTrue("更要紧的是说清仍然全部执行：${sheet.note}", "仍然是这 32 条全部执行" in sheet.note)
    }

    @Test
    fun `字段太多时表尾说清有哪几个字段没列出来`() = runBlocking {
        val store = AiWritePreviewStore()
        val inner = FakeHandler(actionId, store) { i ->
            if (i == 0) (1..4).map { "字段$it：值$it" } else (5..8).map { "字段$it：值$it" }
        }
        val sheet = sheetOf(card(store, inner, "甲", "乙"))
        assertEquals("表最多 7 列", AiCardBatchTable.MAX_COLS, sheet.headers.size)
        assertTrue("列被截了必须说：${sheet.note}", "另有 4 个字段没列出来" in sheet.note)
        assertTrue("要给出路：${sheet.note}", "每一条的明细都在正文里" in sheet.note)
    }

    @Test
    fun `表格只是显示_写下去的仍然是那几条`() = runBlocking {
        val store = AiWritePreviewStore()
        val inner = FakeHandler(actionId, store)
        val c = card(store, inner, "甲", "乙", "丙")
        assertTrue("批量卡要认得出来", isBatchPayload(c.payload))
        val rows = c.payload[BatchWriteHandler.BATCH_PAYLOAD] as JsonArray
        assertEquals("payload 里一条都不能少", 3, rows.size)
    }

    @Test
    fun `单条动作不套 items 时没有表格_照旧走标签值两列`() = runBlocking {
        val store = AiWritePreviewStore()
        val inner = FakeHandler(actionId, store)
        val out = batch(store, inner).prepare(buildJsonObject { put("name", "甲") })
        val single = (out as? AiWriteOutcome.NeedConfirm)?.pending ?: error("期望一张卡，实际是 $out")
        assertNull("单条卡不许带批量表格", single.table)
        assertEquals("单条卡照旧只有一张", 1, store.list().size)
    }

    // ============================================================ 有效期

    @Test
    fun `批量卡三十分钟_单条卡维持五分钟`() = runBlocking {
        val store = AiWritePreviewStore()
        val inner = FakeHandler(actionId, store)
        val batchCard = card(store, inner, "甲")
        assertEquals(30 * 60 * 1000L, AiWritePreviewStore.BATCH_TTL_MS)
        assertEquals(
            "批量卡要够长（用户踩过'一堆卡全过期'）",
            AiWritePreviewStore.BATCH_TTL_MS,
            batchCard.expiresAtMs - batchCard.createdAtMs,
        )
        val single = (inner.prepare(buildJsonObject { put("name", "乙") }) as AiWriteOutcome.NeedConfirm).pending
        assertEquals(
            "单条卡维持现状",
            AiWritePreviewStore.DEFAULT_TTL_MS,
            single.expiresAtMs - single.createdAtMs,
        )
        assertTrue(
            "批量卡的窗口必须比单条卡长",
            AiWritePreviewStore.BATCH_TTL_MS > AiWritePreviewStore.DEFAULT_TTL_MS,
        )
    }

    @Test
    fun `批量卡的有效期是可注入的_单测和以后调档都不用改结构`() = runBlocking {
        val store = AiWritePreviewStore(batchTtlMs = 60_000L)
        val inner = FakeHandler(actionId, store)
        val c = card(store, inner, "甲")
        assertEquals(60_000L, c.expiresAtMs - c.createdAtMs)
    }

    @Test
    fun `批量卡过期之后拿不到_且不会被当成写过`() = runBlocking {
        var now = 1_000L
        val store = AiWritePreviewStore(now = { now })
        val inner = FakeHandler(actionId, store)
        val c = card(store, inner, "甲")
        now += AiWritePreviewStore.BATCH_TTL_MS + 1
        assertNull("过期就是取不到", store.take(c.token))
        assertFalse("取不到 ≠ 写过", store.hasWritten(c.token))
    }

    // ============================================================ 连点 / 幂等

    @Test
    fun `一张卡只能取走一次_连点五下也只有第一下拿得到`() {
        val store = AiWritePreviewStore()
        val c = store.card(
            actionId = actionId,
            summary = "改商品：甲",
            detailLines = listOf("商品：甲"),
            payload = buildJsonObject { put("name", "甲") },
        )
        repeat(5) { i ->
            val got = store.take(c.token)
            if (i == 0) assertTrue("第一下必须拿得到", got != null) else assertNull("第 $i 下必须拿不到", got)
        }
    }

    @Test
    fun `写成功之后记下那句结果_连点第二下才说得出哪几行没成`() {
        val store = AiWritePreviewStore()
        val c = store.card(
            actionId = actionId,
            summary = "批量改商品：3 条",
            detailLines = listOf("商品：甲"),
            payload = buildJsonObject { put("name", "甲") },
            batch = true,
        )
        store.take(c.token)
        store.markWritten(c.token)
        assertTrue(store.hasWritten(c.token))
        assertNull("还没报结果时问不到东西", store.writtenNote(c.token))
        store.noteResult(c.token, "这一批 3 条：成功 2 条，失败 1 条 —— #3 后端不接受这一条。")
        assertEquals(
            "这一句要留到连点第二下的时候用",
            "这一批 3 条：成功 2 条，失败 1 条 —— #3 后端不接受这一条。",
            store.writtenNote(c.token),
        )
        store.noteResult(c.token, "   ")
        assertEquals(
            "空话不许覆盖上一次的真实结果",
            "这一批 3 条：成功 2 条，失败 1 条 —— #3 后端不接受这一条。",
            store.writtenNote(c.token),
        )
    }

    @Test
    fun `被新卡顶掉的和过期的分得开`() = runBlocking {
        val store = AiWritePreviewStore(maxPending = 2)
        val inner = FakeHandler(actionId, store)
        val first = card(store, inner, "甲")
        card(store, inner, "乙")
        card(store, inner, "丙")
        assertTrue("最旧那张应当被顶掉", store.wasDropped(first.token))
        assertFalse("没被顶掉的卡不许乱认", store.wasDropped("从来没见过的 token"))
    }

    // ============================================================ execute() 的那几句话

    /**
     * 一个**永远不会被调到**的数据源替身。
     *
     * ### 为什么用动态代理，而不是手写一个空替身
     * [AiWriteDataSource] 有 60 多个成员（订单、账本、名册、地理编码…），而下面三条用例
     * 想证明的是 `execute()` 在 `take(token)` **拿不到卡**时说的那几句话 ——
     * 那条路上一个数据源方法都不会被调到。手写 60 行空替身只会把判据淹没，接口一改还得跟着改。
     * 所以这里让它**真被调到就当场抛**：比返回空值好 —— 空名册会被误读成"系统里没这个人"。
     */
    private fun neverTouchedDs(): AiWriteDataSource = Proxy.newProxyInstance(
        AiWriteDataSource::class.java.classLoader,
        arrayOf(AiWriteDataSource::class.java),
    ) { _, method, _ ->
        when (method.name) {
            "toString" -> "neverTouchedDs"
            "hashCode" -> 0
            "equals" -> false
            else -> throw UnsupportedOperationException("这条用例不该碰数据源：" + method.name)
        }
    } as AiWriteDataSource

    private fun svc(store: AiWritePreviewStore) = AiWriteService(
        neverTouchedDs(),
        store,
        actorProvider = { AiActor.byRole(AiRole.DISPATCHER) },
    )

    @Test
    fun `过期卡_说这张卡过期了并给一条出路`() = runBlocking {
        val out = svc(AiWritePreviewStore()).execute("这张卡早就没了")
        val r = out as? AiWriteOutcome.Rejected ?: error("期望 Rejected，实际是 $out")
        assertFalse("过期不是写过", r.alreadyWritten)
        assertTrue("要说人话：${r.reason}", "这张卡过期了" in r.reason)
        assertTrue("要给一条出路：${r.reason}", "重新说一句我就再给你发一张" in r.reason)
        assertTrue("还要保住'什么都没写'这句（既有判据钉着它）", "这一次什么都没写" in r.reason)
        assertFalse("⛔ 那句'已经失效了（有效期 5 分钟…）'不许回来", "已经失效了" in r.reason)
    }

    @Test
    fun `执行过的卡再点_承认执行过并带上上次的逐行结果`() = runBlocking {
        val store = AiWritePreviewStore()
        val inner = FakeHandler(actionId, store)
        val c = card(store, inner, "甲", "乙")
        store.take(c.token)
        store.markWritten(c.token)
        store.noteResult(c.token, "这一批 2 条：成功 1 条，失败 1 条 —— #2 后端不接受这一条。")
        val out = svc(store).execute(c.token)
        val r = out as? AiWriteOutcome.Rejected ?: error("期望 Rejected，实际是 $out")
        assertTrue("连点第二下要承认已经执行过", r.alreadyWritten)
        assertTrue("要说人话：${r.reason}", "这张卡已经执行过了" in r.reason)
        assertTrue("要保住'已经写进去了'这句（既有单测钉着它）", "这一次已经写进去了" in r.reason)
        assertTrue("要点出哪几行没成：${r.reason}", "这一批 2 条：成功 1 条，失败 1 条" in r.reason)
        assertFalse("⛔ 不许再用'没写成'吓人", "没写成" in r.reason)
    }

    @Test
    fun `被顶掉的卡_说被顶掉而不是过期`() = runBlocking {
        val store = AiWritePreviewStore(maxPending = 2)
        val inner = FakeHandler(actionId, store)
        val first = card(store, inner, "甲")
        card(store, inner, "乙")
        card(store, inner, "丙")
        val out = svc(store).execute(first.token)
        val r = out as? AiWriteOutcome.Rejected ?: error("期望 Rejected，实际是 $out")
        assertTrue("要说准是哪一种：${r.reason}", "被新的一张顶掉了" in r.reason)
        assertFalse("它没过期，不许往有效期上引：${r.reason}", "这张卡过期了" in r.reason)
    }

    // ============================================================ 部分失败不静默

    @Test
    fun `这一批里有失败的行_汇报里逐条点名`() = runBlocking {
        val store = AiWritePreviewStore()
        val inner = FakeHandler(actionId, store)
        val h = batch(store, inner)
        val c = (h.prepare(items("甲", "乙", "丙")) as? AiWriteOutcome.NeedConfirm)?.pending
            ?: error("期望一张批量卡")
        inner.failOn = "乙"
        // ⚠️ 必须提交**这张卡自己的 payload**（_batch 那三条就在里面）：
        //    提交一个空 payload 会落到"单条"那条路，内层处理器拿不到 name 当场炸
        //    —— 第一版就是这么写的，1708 条单测里唯一一条红的。
        h.commit(c.payload, "k")
        val note = h.commitNote().orEmpty()
        assertTrue("成功条数要说：$note", "成功 2 条" in note)
        assertTrue("失败条数要说：$note", "失败 1 条" in note)
        assertTrue("失败的是哪一条要指名：$note", "#2" in note)
        assertTrue("失败原因要带上：$note", "后端不接受这一条" in note)
        assertTrue("要给出路：$note", "要重来就告诉我" in note)
    }
}
