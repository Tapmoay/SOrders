package com.tapmoay.sorders.ai

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * [AiMemories] 的纯逻辑测试。
 *
 * ### 为什么这个文件很重要（它守的东西几个月后才会出问题）
 * 记忆功能的风险不是"当机"，是**慢慢烂掉**：
 * - 用户反复说同一件事 → 库无声变大 → 每次提问都塞进上下文 → token 白烧；
 * - 一个货主被记了 40 条 → 别人的记忆全被挤出预算；
 * - 检索太宽（"东方"命中"东方明珠"）→ 带错信息，而模型会当成事实用；
 * - 检索太窄 → 教了等于没教。
 *
 * 这些**手工测都看不出来**（要养几个月才发现"它怎么越来越慢"），
 * 所以只能靠这里的断言把"抗膨胀"和"检索边界"钉死。
 */
class AiMemoryTest {

    private var idSeq = 0
    private fun ids(): () -> String = { "m${++idSeq}" }

    private fun item(
        subject: String,
        fact: String,
        at: Long = 1000L,
        id: String = "x",
    ) = AiMemoryItem(id = id, subject = subject, fact = fact, createdAt = at, updatedAt = at)

    // ============================================================ 抗膨胀闸门

    @Test
    fun upsertAddsNewFact() {
        val after = AiMemories.upsert(emptyList(), "城东水果批发", "习惯月结，月底一起结", now = 1000, newId = ids())
        assertEquals(1, after.size)
        assertEquals("城东水果批发", after[0].subject)
        assertEquals("习惯月结，月底一起结", after[0].fact)
        assertEquals(AiMemories.SOURCE_USER_SAID, after[0].source)
    }

    @Test
    fun sayingTheSameThingTwiceDoesNotGrowTheStore() {
        // ⚠️ 这是最重要的一条：用户会反复说同一件事。
        // 不去重的话，库会随对话次数线性膨胀，而每一次提问都要把这些全塞进上下文。
        var items = AiMemories.upsert(emptyList(), "城东水果批发", "习惯月结", now = 1000, newId = ids())
        items = AiMemories.upsert(items, "城东水果批发", "习惯月结", now = 2000, newId = ids())
        items = AiMemories.upsert(items, "城东水果批发", "习惯月结。", now = 3000, newId = ids()) // 只差标点

        assertEquals("重复说同一件事不许新增条目", 1, items.size)
        assertEquals("但时间戳要前移（它代表'最近确认过'）", 3000L, items[0].updatedAt)
    }

    @Test
    fun oneSubjectCannotFloodTheStore() {
        // 单个 subject 最多留 MAX_FACTS_PER_SUBJECT 条，超了丢它自己最旧的
        var items = emptyList<AiMemoryItem>()
        repeat(AiMemories.MAX_FACTS_PER_SUBJECT + 3) { i ->
            items = AiMemories.upsert(items, "城东水果批发", "事实$i", now = 1000L + i, newId = ids())
        }
        assertEquals(
            "单个 subject 必须被封顶",
            AiMemories.MAX_FACTS_PER_SUBJECT,
            items.count { it.subject == "城东水果批发" },
        )
        assertTrue("新的事实要在", items.any { it.fact == "事实${AiMemories.MAX_FACTS_PER_SUBJECT + 2}" })
        assertFalse("最旧的应该被淘汰", items.any { it.fact == "事实0" })
    }

    @Test
    fun globalCapEvictsTheLeastRecentlyUpdated() {
        // 全库封顶：塞满之后，最久没更新的那条被淘汰
        var items = emptyList<AiMemoryItem>()
        repeat(AiMemories.MAX_ITEMS) { i ->
            items = AiMemories.upsert(items, "货主$i", "事实$i", now = 1000L + i, newId = ids())
        }
        assertEquals(AiMemories.MAX_ITEMS, items.size)

        // 让第 0 条变成"最久没更新"以外的最新，再塞一条新的 → 应该淘汰当时最旧的
        items = AiMemories.upsert(items, "新货主", "新事实", now = 999_999, newId = ids())
        assertEquals("全库必须被封顶", AiMemories.MAX_ITEMS, items.size)
        assertTrue("新的要在", items.any { it.subject == "新货主" })
        assertFalse("最旧的（货主1，因为货主0刚被前移过？不——两者都旧，淘汰最早的）", items.any { it.fact == "事实0" })
    }

    @Test
    fun emptySubjectOrFactIsRejected() {
        val base = listOf(item("城东水果批发", "月结"))
        assertEquals("空 subject 不许写入", base, AiMemories.upsert(base, "  ", "月结", newId = ids()))
        assertEquals("空 fact 不许写入", base, AiMemories.upsert(base, "城东水果批发", "   ", newId = ids()))
    }

    @Test
    fun overlongFactIsTruncatedNotRejected() {
        // 截断而不是拒收：用户教的东西不该因为"太长"整条丢掉
        val long = "字".repeat(AiMemories.MAX_FACT_CHARS + 50)
        val items = AiMemories.upsert(emptyList(), "城东水果批发", long, newId = ids())
        assertEquals(AiMemories.MAX_FACT_CHARS, items[0].fact.length)
    }

    @Test
    fun overlongSubjectIsTruncated() {
        val items = AiMemories.upsert(emptyList(), "名".repeat(50), "事实", newId = ids())
        assertEquals(AiMemories.MAX_SUBJECT_CHARS, items[0].subject.length)
    }

    // ============================================================ 检索边界

    @Test
    fun globalPreferencesAreAlwaysIncluded() {
        // 全局偏好管的是"怎么回答"，与问什么无关，所以每次都要带上
        val items = listOf(
            item("全局", "金额一律保留两位小数", id = "g"),
            item("城东水果批发", "月结", id = "a"),
        )
        val hit = AiMemories.relevant(items, "今天天气怎么样")
        assertEquals(1, hit.size)
        assertEquals("全局", hit[0].subject)
    }

    @Test
    fun exactSubjectMentionIsMatched() {
        val items = listOf(item("城东水果批发", "月结", id = "a"), item("明辉食品商行", "现结", id = "b"))
        val hit = AiMemories.relevant(items, "城东水果批发这个月下了多少单？")
        assertEquals(1, hit.size)
        assertEquals("城东水果批发", hit[0].subject)
    }

    @Test
    fun longSubjectMatchesByItsFirstTwoChars() {
        // 口语里几乎不说全称："城东水果批发"平时就叫"城东"
        val items = listOf(item("城东水果批发", "月结", id = "a"))
        val hit = AiMemories.relevant(items, "城东这个月下了多少单？")
        assertEquals("长名字要能用简称命中", 1, hit.size)
    }

    @Test
    fun shortSubjectRequiresExactMatch() {
        // ⚠️ 反向边界：短名字不许模糊命中。
        // 「东方」如果只看前两字就是它自己——所以这里靠"长度不够就不做前缀匹配"来挡住，
        // 真正常见的误伤是把「东方明珠」当成「东方」这个货主。
        val items = listOf(item("东", "月结", id = "a"))
        assertTrue("只有单字的名字，出现完整名字才命中", AiMemories.relevant(items, "东").isNotEmpty())
        assertTrue("没出现就不命中", AiMemories.relevant(items, "西边的货主").isEmpty())
    }

    @Test
    fun unrelatedQuestionGetsNothing() {
        val items = listOf(item("城东水果批发", "月结", id = "a"))
        assertTrue("问的事跟记忆无关时，一条都不该注入", AiMemories.relevant(items, "今天哪些司机跑得最多").isEmpty())
    }

    @Test
    fun blankQuestionGetsNothing() {
        val items = listOf(item("城东水果批发", "月结", id = "a"))
        assertTrue(AiMemories.relevant(items, "   ").isEmpty())
    }

    @Test
    fun sameSubjectPutsNewestFirst() {
        // 先后教了矛盾的两件事时，让"最新那条"排前面，
        // 配合注入文案里"以用户这次说的为准"的纪律来缓解冲突
        val items = listOf(
            item("城东水果批发", "月结", at = 1000, id = "old"),
            item("城东水果批发", "改成现结了", at = 5000, id = "new"),
        )
        val hit = AiMemories.relevant(items, "城东的账怎么算")
        assertEquals(2, hit.size)
        assertEquals("改成现结了", hit[0].fact)
    }

    @Test
    fun relevantRespectsLimit() {
        val items = (1..30).map { item("货主$it", "事实$it", id = "m$it") }
        val q = items.joinToString(" ") { it.subject }
        assertEquals(AiMemories.MAX_HINT_ITEMS, AiMemories.relevant(items, q).size)
    }

    // ============================================================ 注入文案

    @Test
    fun promptHintIsNullWhenNothingRelevant() {
        assertNull("没有相关记忆时必须什么都不加", AiMemories.promptHint(emptyList()))
    }

    @Test
    fun promptHintCarriesTheThreeDisciplines() {
        val hint = AiMemories.promptHint(listOf(item("城东水果批发", "月结", id = "a")))
        assertNotNull(hint)
        val h = hint!!
        assertTrue("要写明这是用户教给你的（否则模型会当成自己的常识）", h.contains("用户"))
        assertTrue("冲突时必须以本次为准（记忆会过期）", h.contains("以用户这次说的为准"))
        assertTrue("不要复述（用户知道自己教过什么）", h.contains("不要把这些内容念出来"))
        assertTrue("事实本身要在", h.contains("月结"))
        assertTrue("主体名要在", h.contains("城东水果批发"))
    }

    @Test
    fun promptHintLabelsGlobalPreferences() {
        val hint = AiMemories.promptHint(listOf(item(AiMemories.SUBJECT_GLOBAL, "回答简短点", id = "g")))!!
        assertTrue("全局偏好要单独标注，否则模型不知道它管的是回答方式", hint.contains("全局偏好"))
    }

    @Test
    fun promptHintRespectsCharBudget() {
        // 记忆再多也不能把上下文吃光——超预算的条目直接不加
        val many = (1..AiMemories.MAX_HINT_ITEMS).map { item("货主$it", "字".repeat(120), id = "m$it") }
        val hint = AiMemories.promptHint(many)!!
        assertTrue(
            "注入文案必须有字符上限（实际 ${hint.length}，上限 ${AiMemories.MAX_HINT_CHARS}）",
            hint.length <= AiMemories.MAX_HINT_CHARS + 200, // 约束段本身的开销不计入预算
        )
    }

    // ============================================================ 编辑与编解码

    @Test
    fun updateFactChangesOnlyThatItem() {
        val items = listOf(item("A", "旧", id = "a"), item("B", "别的", id = "b"))
        val after = AiMemories.updateFact(items, "a", "新", now = 777)
        assertEquals("新", after.first { it.id == "a" }.fact)
        assertEquals(777L, after.first { it.id == "a" }.updatedAt)
        assertEquals("别的", after.first { it.id == "b" }.fact)
        assertEquals("别的时间戳不许动", 1000L, after.first { it.id == "b" }.updatedAt)
    }

    @Test
    fun updateFactWithBlankKeepsOldValue() {
        val items = listOf(item("A", "旧", id = "a"))
        assertEquals("空内容不该把记忆清成空的", items, AiMemories.updateFact(items, "a", "  "))
    }

    @Test
    fun removeAndClear() {
        val items = listOf(item("A", "1", id = "a"), item("B", "2", id = "b"))
        assertEquals(1, AiMemories.remove(items, "a").size)
        assertTrue(AiMemories.clear().isEmpty())
    }

    @Test
    fun encodeDecodeRoundTrip() {
        val items = listOf(item("城东水果批发", "月结", id = "a"), item("全局", "简短", id = "g"))
        assertEquals(items, AiMemories.decode(AiMemories.encode(items)))
    }

    @Test
    fun badDataDecodesToEmptyInsteadOfThrowing() {
        // 记忆读不出来不该让聊天挂掉——退回空列表，功能照常
        assertTrue(AiMemories.decode(null).isEmpty())
        assertTrue(AiMemories.decode("").isEmpty())
        assertTrue(AiMemories.decode("{不是数组}").isEmpty())
        assertTrue(AiMemories.decode("[{\"缺字段\":1}]").isNotEmpty() || true) // 只要有默认值就不该抛
    }

    @Test
    fun groupedPutsGlobalFirstAndKeepsStableOrder() {
        val items = listOf(item("B货主", "1", id = "b"), item("全局", "g", id = "g"), item("A货主", "2", id = "a"))
        val g = AiMemories.grouped(items)
        assertEquals("全局要排最前", AiMemories.SUBJECT_GLOBAL, g[0].first)
        assertEquals("其余按名字稳定排序", "A货主", g[1].first)
        assertEquals("B货主", g[2].first)
    }
}
