package com.tapmoay.sorders.ai

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 「推荐问题」纯逻辑的判据（CHG-0114）。
 *
 * ⛔ 这里**只测不依赖 Android 的那一半**（`AiSuggests` / `AiSuggestCodec`）。
 * `AiSuggestStore` 要 `Context`，它那半边靠 `_tools/qa/_check_ai_suggest.py` 的源码判据。
 *
 * 为什么值得单测：这一页是用户对 AI 的**第一印象**，而"第一印象"全靠这几条排序规则 ——
 * 把批发商的问题摆给刚注册的货主看，等于告诉他"这东西不是给你的"。
 */
class AiSuggestTest {

    private val dispatcher = AiActor.of(AiRole.DISPATCHER, false)!!
    private val shipper = AiActor.of(AiRole.SHIPPER, false)!!
    private val member = AiActor.of(AiRole.SHIPPER, true)!!

    // ---------------- 角色判定 ----------------

    @Test
    fun `派单员认成派单员`() {
        assertEquals(AiSuggestWho.DISPATCHER, AiSuggests.whoOf(dispatcher))
    }

    @Test
    fun `普通货主与批发商要分开`() {
        assertEquals(AiSuggestWho.SHIPPER, AiSuggests.whoOf(shipper))
        assertEquals(AiSuggestWho.MEMBER, AiSuggests.whoOf(member))
    }

    @Test
    fun `没登录就不猜角色`() {
        // 猜错角色比不推荐更糟：那是"教他做他做不到的事"。
        assertNull(AiSuggests.whoOf(null))
    }

    @Test
    fun `三类角色的标题各不相同`() {
        val titles = AiSuggestWho.entries.map { it.title }
        assertEquals(titles.size, titles.distinct().size)
        assertTrue(AiSuggestWho.MEMBER.title.contains("批发商"))
    }

    // ---------------- 两档：第一次来 / 用过 ----------------

    @Test
    fun `第一次来只给首次档`() {
        val pack = AiSuggests.packFor(AiSuggestWho.SHIPPER)
        val got = AiSuggests.home(AiSuggestWho.SHIPPER, firstTimer = true)
        assertEquals(pack.first.take(AiSuggests.HOME_LIMIT), got)
    }

    @Test
    fun `用过之后给整套里挑`() {
        val pack = AiSuggests.packFor(AiSuggestWho.SHIPPER)
        val first = AiSuggests.home(AiSuggestWho.SHIPPER, firstTimer = true)
        val later = AiSuggests.home(AiSuggestWho.SHIPPER, firstTimer = false)
        assertEquals(AiSuggests.HOME_LIMIT, later.size)
        // 非首次档是从**整套**里挑的，所以它至少得跟首次档不完全一样 ——
        // 一样就等于"首次/常规"这两档根本没做出来。
        assertFalse(
            "首次档与常规档完全一样，等于没分档",
            first == later && pack.flat.size > AiSuggests.HOME_LIMIT,
        )
    }

    @Test
    fun `用户自己编辑的首次预设优先于默认`() {
        val mine = listOf("帮我下单", "加个地址", "查欠款", "看这个月的账")
        val got = AiSuggests.home(AiSuggestWho.SHIPPER, firstTimer = true, customFirst = mine)
        assertEquals(mine, got)
    }

    @Test
    fun `自己编辑的预设不影响用过之后的档`() {
        val mine = listOf("帮我下单", "加个地址", "查欠款", "看这个月的账")
        val a = AiSuggests.home(AiSuggestWho.SHIPPER, firstTimer = false, customFirst = mine)
        val b = AiSuggests.home(AiSuggestWho.SHIPPER, firstTimer = false)
        assertEquals(b, a)
    }

    // ---------------- 排序：固定 → 常用 → 默认 ----------------

    @Test
    fun `固定的一定排最前`() {
        val base = listOf("A", "B", "C", "D", "E")
        val got = AiSuggests.rank(base, pinned = listOf("D"), taps = emptyMap())
        assertEquals("D", got.first())
    }

    @Test
    fun `多个固定的保持用户自己的顺序`() {
        val base = listOf("A", "B", "C", "D", "E")
        val got = AiSuggests.rank(base, pinned = listOf("E", "C"), taps = emptyMap())
        assertEquals(listOf("E", "C"), got.take(2))
    }

    @Test
    fun `问过两次以上的排到固定之后、其余之前`() {
        val base = listOf("A", "B", "C", "D", "E")
        val got = AiSuggests.rank(base, pinned = listOf("E"), taps = mapOf("C" to 3, "D" to 1))
        assertEquals(listOf("E", "C", "A", "B", "D"), got)
    }

    @Test
    fun `只点过一次的不算常用`() {
        // 点一次很可能是好奇点错了，把它顶上来等于用一次误触改掉了他最顺手的那几条。
        val base = listOf("A", "B", "C", "D")
        val got = AiSuggests.rank(base, pinned = emptyList(), taps = mapOf("D" to 1))
        assertEquals(base, got)
    }

    @Test
    fun `不在 base 里的历史问题不硬塞进来`() {
        // base 是"这个角色此刻该看到什么"的唯一来源；允许任意旧问题长期占位，
        // 等于把这一页交给历史。
        val base = listOf("A", "B", "C", "D")
        val got = AiSuggests.rank(base, pinned = emptyList(), taps = mapOf("很久以前问过的" to 9))
        assertEquals(base, got)
    }

    @Test
    fun `排序是稳定的`() {
        val base = listOf("A", "B", "C", "D")
        assertEquals(base, AiSuggests.rank(base, emptyList(), emptyMap()))
        assertEquals(base, AiSuggests.rank(base, emptyList(), mapOf("A" to 2, "B" to 2)))
    }

    // ---------------- 常用区 ----------------

    @Test
    fun `常用区按次数倒序`() {
        val got = AiSuggests.usedQuestions(
            taps = mapOf("X" to 2, "Y" to 5, "Z" to 1),
            base = emptyList(),
        )
        assertEquals(listOf("Y", "X"), got)
    }

    @Test
    fun `常用区里 base 内的排在前面`() {
        val got = AiSuggests.usedQuestions(
            taps = mapOf("自定义的" to 9, "预设的" to 2),
            base = listOf("预设的"),
        )
        // 次数多的是自定义那条，但"这个角色确实该问的"要排前面。
        assertEquals(listOf("预设的", "自定义的"), got)
    }

    @Test
    fun `常用区限量`() {
        val taps = (1..20).associate { "q$it" to 2 }
        assertEquals(AiSuggests.USED_LIMIT, AiSuggests.usedQuestions(taps, emptyList()).size)
    }

    // ---------------- 洗数据（用户手输的那条路） ----------------

    @Test
    fun `空白的预设被丢掉`() {
        assertNull(AiSuggestCodec.clean("   "))
        assertNull(AiSuggestCodec.clean("\n\n"))
        assertNull(AiSuggestCodec.clean(null))
    }

    @Test
    fun `换行被压成空格、首尾空白去掉`() {
        assertEquals("帮我\n下单", AiSuggestCodec.clean("帮我\n下单"))
        assertEquals("帮我下单", AiSuggestCodec.clean("  帮我下单  "))
    }

    @Test
    fun `太长的预设被截断而不是丢掉`() {
        val long = "问".repeat(AiSuggestCodec.MAX_QUESTION_CHARS + 30)
        assertEquals(AiSuggestCodec.MAX_QUESTION_CHARS, AiSuggestCodec.clean(long)!!.length)
    }

    @Test
    fun `列表洗一遍会去重并限量`() {
        val got = AiSuggestCodec.cleanList(listOf("A", "A", " B ", "", "C"), limit = 2)
        assertEquals(listOf("A", "B"), got)
    }

    @Test
    fun `点击计数累加、空白不计`() {
        var taps = AiSuggestCodec.tap(emptyMap(), "A")
        taps = AiSuggestCodec.tap(taps, "A")
        taps = AiSuggestCodec.tap(taps, "   ")
        assertEquals(mapOf("A" to 2), taps)
    }

    @Test
    fun `计数表满了先丢次数最少的`() {
        var taps = mapOf("常问的" to 9)
        repeat(AiSuggestCodec.MAX_TAPS + 10) { i -> taps = AiSuggestCodec.tap(taps, "q$i") }
        assertEquals(AiSuggestCodec.MAX_TAPS, taps.size)
        // 常问的那条必须留住 —— 它正是"常用"区的来源。
        assertEquals(9, taps["常问的"])
    }

    // ---------------- 存盘格式 ----------------

    @Test
    fun `存盘能原样读回来`() {
        val v = AiSuggestSaved(
            first = listOf("A", "B"),
            pinned = listOf("C"),
            taps = mapOf("D" to 3),
        )
        assertEquals(v, AiSuggestCodec.decode(AiSuggestCodec.encode(v)))
    }

    @Test
    fun `坏数据退回空而不是崩`() {
        // 手改过 prefs、跨版本残留都可能让这里读到不是 JSON 的东西；
        // 一页推荐问题不值得让聊天页打不开。
        assertEquals(AiSuggestSaved(), AiSuggestCodec.decode("{不是 JSON"))
        assertEquals(AiSuggestSaved(), AiSuggestCodec.decode(null))
        assertEquals(AiSuggestSaved(), AiSuggestCodec.decode(""))
    }

    // ---------------- 三套内容本身 ----------------

    @Test
    fun `三套预设都不空、都能凑满一屏`() {
        AiSuggestWho.entries.forEach { who ->
            val pack = AiSuggests.packFor(who)
            assertTrue("${who.cn} 的首次档太少", pack.first.size >= AiSuggests.HOME_LIMIT)
            assertTrue("${who.cn} 的类别太少", pack.categories.size >= 3)
            assertTrue("${who.cn} 的问题有空的", pack.flat.none { it.isBlank() })
        }
    }

    @Test
    fun `三套预设互不相同`() {
        val all = AiSuggestWho.entries.map { AiSuggests.packFor(it).first }
        assertEquals(all.size, all.distinct().size)
    }

    @Test
    fun `批发商能看到跟欠款有关的问题、普通货主看不到`() {
        val memberQ = AiSuggests.packFor(AiSuggestWho.MEMBER).flat.joinToString()
        val shipperQ = AiSuggests.packFor(AiSuggestWho.SHIPPER).flat.joinToString()
        assertTrue(memberQ.contains("欠"))
        assertFalse(shipperQ.contains("欠我"))
    }
}
