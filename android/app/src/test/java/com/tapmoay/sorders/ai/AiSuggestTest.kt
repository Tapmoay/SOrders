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
        // 预设是一行一颗按钮，换行会把按钮撑高、还可能被当成两条 —— 一律压成空格。
        assertEquals("帮我 下单", AiSuggestCodec.clean("帮我\n下单"))
        assertEquals("帮我 下单", AiSuggestCodec.clean("帮我\r\n下单"))
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

    // ---------------- 操作（DO）：面板左抽屉的右半张表 ----------------

    @Test
    fun `三类身份换算回去还是原来那个 actor`() {
        assertEquals(dispatcher, AiSuggests.actorOf(AiSuggestWho.DISPATCHER))
        assertEquals(shipper, AiSuggests.actorOf(AiSuggestWho.SHIPPER))
        // ⛔ 批发商在**后端仍然是货主**，靠 memberShipper 分叉；多造一个角色等于多开一扇门。
        assertEquals(AiRole.SHIPPER, AiSuggests.actorOf(AiSuggestWho.MEMBER)?.role)
        assertEquals(true, AiSuggests.actorOf(AiSuggestWho.MEMBER)?.memberShipper)
    }

    @Test
    fun `操作不是另抄一份表，而是注册表现算`() {
        // 这条是这一段的核心约束：谁把 action 清单抄进 AiSuggest 里，这里立刻红。
        AiSuggestWho.entries.forEach { who ->
            assertEquals(AiWrites.forModel(AiSuggests.actorOf(who)), AiSuggests.opsFor(who))
        }
    }

    @Test
    fun `每种角色的操作一条都不少、也没有多出来的`() {
        val d = AiSuggests.opsFor(AiSuggestWho.DISPATCHER)
        val s = AiSuggests.opsFor(AiSuggestWho.SHIPPER)
        val m = AiSuggests.opsFor(AiSuggestWho.MEMBER)
        assertEquals(AiWrites.forModel(dispatcher).size, d.size)
        assertTrue("派单员能干的活应该远多于货主", d.size > s.size)
        assertEquals(s.size + 4, m.size)
    }

    @Test
    fun `撤回专用的动作不该出现在面板里`() {
        AiSuggestWho.entries.forEach { who ->
            assertTrue(AiSuggests.opsFor(who).none { it.undoOnly })
        }
    }

    @Test
    fun `操作按域分组、域名就是注册表自己的 group`() {
        val secs = AiSuggests.opsSections(AiSuggests.opsFor(AiSuggestWho.DISPATCHER))
        assertTrue(secs.isNotEmpty())
        assertTrue(secs.all { it.kind == AiSuggestKind.DO })
        assertTrue(secs.all { it.ops.isNotEmpty() && it.questions.isEmpty() })
        // 分完组要一条不丢：这是"铺得下两百多条"的前提。
        assertEquals(AiSuggests.opsFor(AiSuggestWho.DISPATCHER).size, secs.sumOf { it.ops.size })
        assertEquals(AiWrites.forModel(dispatcher).groupBy { it.group }.keys.toList(), secs.map { it.cn })
    }

    @Test
    fun `点一下就是把这句话说出去，不改写任何东西`() {
        val op = AiSuggestOp("orders.assign", "派单", AiWriteRisk.HIGH)
        assertEquals("帮我派单", op.say)
        // 动作名本身就是一句话的（"消息全部标为已读"）不要再套"帮我"，否则读起来像病句。
        assertEquals("帮我把这单派出去", AiSuggestOp("x", "帮我把这单派出去", AiWriteRisk.MEDIUM).say)
        assertEquals("orders.assign", op.id)
        assertEquals(AiWriteRisk.HIGH, op.risk)
    }

    @Test
    fun `高风险动作照样摆得出来——它只是替用户说话，不执行`() {
        val high = AiSuggests.opsSections(AiSuggests.opsFor(AiSuggestWho.DISPATCHER))
            .flatMap { it.ops }.filter { it.risk == AiWriteRisk.HIGH }
        assertTrue("高风险动作占了大半张表，全藏起来用户就不知道 AI 能帮忙", high.size > 50)
        // 摆出来 ≠ 点得动：真要执行还得用户在确认卡上再点一次（AiPendingWrite 的三条不变量）。
        assertTrue(high.map { it.say }.all { it.startsWith("帮我") })
    }

    @Test
    fun `左抽屉的格子：我常问的 → 问题分类 → 操作分类`() {
        val pack = AiSuggests.packFor(AiSuggestWho.SHIPPER)
        val taps = mapOf(pack.flat.first() to 3, pack.flat[1] to 1)
        val shelf = AiSuggests.shelf(pack, taps, AiSuggests.opsFor(AiSuggestWho.SHIPPER))
        assertEquals(AiSuggestKind.USED, shelf.first().kind)
        assertEquals(listOf(pack.flat.first()), shelf.first().questions)
        // 左栏是按类别名排的：两格同名 = 用户看到两个一模一样的入口，点进去一个有问一个有活。
        // 问题分类与操作域的名字必然撞（都叫「订单」「账目」「地址与联系人」），所以必须并。
        assertEquals(shelf.size, shelf.map { it.cn }.distinct().size)
        assertEquals(pack.categories.size, shelf.count { it.questions.isNotEmpty() } - 1)
        assertTrue("操作那一半要铺得出来", shelf.any { it.ops.isNotEmpty() })
        assertTrue("并过的那格两面都有", shelf.any { it.kind == AiSuggestKind.MIXED } ||
            shelf.none { it.ops.isNotEmpty() && it.questions.isNotEmpty() })
    }

    @Test
    fun `一次都没点过就不摆我常问的`() {
        val pack = AiSuggests.packFor(AiSuggestWho.SHIPPER)
        val shelf = AiSuggests.shelf(pack, emptyMap(), AiSuggests.opsFor(AiSuggestWho.SHIPPER))
        assertTrue(shelf.none { it.kind == AiSuggestKind.USED })
    }
}
