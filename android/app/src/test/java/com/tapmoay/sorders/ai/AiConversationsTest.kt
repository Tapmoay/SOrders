package com.tapmoay.sorders.ai

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.ZoneId

/**
 * [AiConversations] 的单元测试（纯 JVM，不碰 Android、不碰文件系统）。
 *
 * 重点覆盖三件**用户天天会用到、出错却很难发现**的事：
 * ① 分叉只复制"分叉点之前"的消息（多复制一条 = 上下文串味；少一条 = 前情丢失）；
 * ② 用量重新累计（不重算就会把父对话的 token 也算进来，显示一个假数字）；
 * ③ 上限与字节预算（历史不能无限膨胀，但**当前这段对话绝不能被整个丢掉**）。
 */
class AiConversationsTest {

    private val zone = ZoneId.of("Asia/Shanghai")

    /** 固定的「今天」，让时间显示断言与运行时刻无关。 */
    private val today0 = LocalDate.of(2026, 9, 15)

    private fun at(y: Int, m: Int, d: Int, h: Int, min: Int = 0): Long =
        LocalDateTime.of(y, m, d, h, min).atZone(zone).toInstant().toEpochMilli()

    private fun user(text: String, tokens: Int = 0) =
        StoredMessage(role = StoredMessage.ROLE_USER, text = text, at = 1000L, tokens = tokens)

    private fun assistant(text: String, tokens: Int = 0) =
        StoredMessage(role = StoredMessage.ROLE_ASSISTANT, text = text, at = 2000L, tokens = tokens)

    /** 一段 6 条消息的对话：问/答 ×3，助手各带用量。 */
    private fun conversation(id: String = "c1", updatedAt: Long = 5000L) = StoredConversation(
        id = id,
        createdAt = 1000L,
        updatedAt = updatedAt,
        messages = listOf(
            user("问题一"),
            assistant("答案一", tokens = 100),
            user("问题二"),
            assistant("答案二", tokens = 200),
            user("问题三"),
            assistant("答案三", tokens = 300),
        ),
    )

    // ================================================================== 标题

    @Test
    fun titleComesFromFirstUserMessage() {
        assertEquals("问题一", AiConversations.titleOf(conversation()))
        assertEquals(AiConversations.NEW_CHAT_TITLE, AiConversations.titleOf(AiConversations.blank()))
    }

    @Test
    fun titleIsClippedAndSingleLine() {
        val conv = conversation().copy(
            messages = listOf(user("这个月哪个货主下单数量最多啊到底是谁呢")),
        )
        val title = AiConversations.titleOf(conv)
        assertEquals("这个月哪个货主下单数量最多啊到底…", title)

        val multiline = conversation().copy(messages = listOf(user("第一行\n第二行")))
        assertEquals("第一行 第二行", AiConversations.titleOf(multiline))
    }

    // ================================================================== 分支

    @Test
    fun branchKeepsMessagesUpToAndIncludingTheFork() {
        val src = conversation()
        val branched = AiConversations.branch(src, upToIndex = 1, newId = "b1", now = 9000L)

        assertEquals(listOf("问题一", "答案一"), branched.messages.map { it.text })
        assertEquals("b1", branched.id)
        assertEquals(src.id, branched.parentId)
        assertEquals(1, branched.branchAt)
        assertTrue(branched.isBranch)
        assertEquals(9000L, branched.updatedAt)
        assertTrue("原对话不能被改动", src.messages.size == 6)
    }

    @Test
    fun branchRecountsTokensInsteadOfInheritingParentTotal() {
        val branched = AiConversations.branch(conversation(), upToIndex = 3, newId = "b1", now = 1L)
        // 只带了 答案一(100) + 答案二(200)，绝不能是父对话的 600
        assertEquals(300, branched.totalTokens)
    }

    @Test
    fun branchClampsOutOfRangeIndex() {
        val src = conversation()
        assertEquals(6, AiConversations.branch(src, 99, "b1", 1L).messages.size)
        assertEquals(0, AiConversations.branch(src, -5, "b1", 1L).messages.size)
        assertEquals(0, AiConversations.branch(AiConversations.blank("e"), 3, "b1", 1L).messages.size)
    }

    // ================================================================== 复制

    @Test
    fun duplicateKeepsEverythingButIsNotABranch() {
        val copy = AiConversations.duplicate(conversation(), newId = "d1", now = 7000L)
        assertEquals(6, copy.messages.size)
        assertEquals(600, copy.totalTokens)
        assertEquals("d1", copy.id)
        assertFalse("整段复制不是分支，不该标成分支", copy.isBranch)
        assertEquals(7000L, copy.updatedAt)
    }

    // ================================================================== 上限

    @Test
    fun capKeepsNewestMessagesAndTruncatesHugeText() {
        var conv = AiConversations.blank("c")
        repeat(250) { i -> conv = AiConversations.append(conv, user("第 $i 条")) }
        assertEquals(AiConversations.MAX_MESSAGES_PER_CONVERSATION, conv.messages.size)
        assertEquals("丢的必须是最早的", "第 50 条", conv.messages.first().text)

        val huge = AiConversations.cap(
            AiConversations.blank("c").copy(messages = listOf(user("字".repeat(9000)))),
        )
        assertTrue(huge.messages[0].text.length < 9000 + 20)
        assertTrue(huge.messages[0].text.endsWith("（过长已截断）"))
    }

    @Test
    fun capAllKeepsNewestConversations() {
        val many = (0 until 60).map { i -> conversation(id = "c$i", updatedAt = i.toLong()) }
        val kept = AiConversations.capAll(many)
        assertEquals(AiConversations.MAX_CONVERSATIONS, kept.size)
        assertEquals("c59", kept.first().id)
        assertEquals("c10", kept.last().id)
    }

    @Test
    fun fitToBudgetDropsOldestWholeConversations() {
        // 每段约 480KB（800 字 × 200 条，中文 3 字节），预算 700KB → 只装得下最新的一段
        val big = "字".repeat(800)
        fun heavy(id: String, updatedAt: Long) = StoredConversation(
            id = id,
            createdAt = 1L,
            updatedAt = updatedAt,
            messages = (0 until 200).map { user(big) },
        )
        val fitted = AiConversations.fitToBudget(
            listOf(heavy("old", 1000L), heavy("new", 2000L)),
            maxBytes = 700_000,
        )
        assertEquals(listOf("new"), fitted.map { it.id })
        assertEquals("超预算时丢的是整段旧对话，不是最新那段的消息", 200, fitted[0].messages.size)
    }

    @Test
    fun fitToBudgetNeverDropsTheOnlyConversation() {
        val big = "字".repeat(2000)
        val solo = StoredConversation(
            id = "only",
            createdAt = 1L,
            updatedAt = 1L,
            messages = (0 until 30).map { user(big) },
        )
        val fitted = AiConversations.fitToBudget(listOf(solo), maxBytes = 50_000)
        assertEquals(1, fitted.size)
        assertEquals("only", fitted[0].id)
        assertTrue("应当只剩很少几条消息", fitted[0].messages.size < 30)
        assertTrue("至少留一条", fitted[0].messages.isNotEmpty())
    }

    @Test
    fun encodeAlwaysRespectsByteBudget() {
        // 30 段 × 30 条 × 2000 字 ≈ 5.4MB，超过 2MB 预算 → encode 必须自己裁到预算内
        val big = "字".repeat(2000)
        val list = (0 until 30).map { i ->
            StoredConversation(
                id = "c$i",
                createdAt = 1L,
                updatedAt = i.toLong(),
                messages = (0 until 30).map { user(big) },
            )
        }
        val text = AiConversations.encode(list)
        assertTrue(
            "encode 必须自带预算闸，实际 ${text.toByteArray(Charsets.UTF_8).size} 字节",
            text.toByteArray(Charsets.UTF_8).size <= AiConversations.MAX_FILE_BYTES,
        )
        assertTrue("预算内也要留下多段对话，而不是只剩一段", AiConversations.decode(text).size > 1)
    }

    // ================================================================== 合并（防覆盖丢历史）

    @Test
    fun mergeByIdKeepsConversationsThatOnlyExistOnDisk() {
        // 这是一次真实丢历史事故的回归测试：
        // ViewModel 的对话列表是异步读进来的，读进来之前落一次盘，
        // 写下去的就只有"当前这一段"——盘上原有的对话必须被保住。
        val onDisk = listOf(conversation("keep1", 3000L), conversation("keep2", 2000L))
        val incoming = listOf(conversation("current", 4000L))
        val merged = AiConversations.mergeById(onDisk, incoming)
        assertEquals(
            setOf("keep1", "keep2", "current"),
            merged.map { it.id }.toSet(),
        )
    }

    @Test
    fun mergeByIdLetsIncomingWinForSameId() {
        val old = conversation("same", 1000L).copy(totalTokens = 1)
        val new = conversation("same", 9000L).copy(totalTokens = 600)
        val merged = AiConversations.mergeById(listOf(old), listOf(new))
        assertEquals(1, merged.size)
        assertEquals(600, merged.single().totalTokens)
        assertEquals(9000L, merged.single().updatedAt)
    }

    @Test
    fun mergeByIdWithEmptyIncomingKeepsDiskUntouched() {
        val onDisk = listOf(conversation("a", 1L), conversation("b", 2L))
        assertEquals(
            setOf("a", "b"),
            AiConversations.mergeById(onDisk, emptyList()).map { it.id }.toSet(),
        )
    }

    // ================================================================== 编解码

    @Test
    fun encodeDecodeRoundTrip() {
        val list = listOf(conversation("c1", 5000L), AiConversations.branch(conversation(), 1, "b1", 6000L))
        val back = AiConversations.decode(AiConversations.encode(list))
        assertEquals(list.map { it.id }.toSet(), back.map { it.id }.toSet())
        val c1 = back.first { it.id == "c1" }
        assertEquals(6, c1.messages.size)
        assertEquals(600, c1.totalTokens)
        assertEquals("答案二", c1.messages[3].text)
        val b1 = back.first { it.id == "b1" }
        assertTrue(b1.isBranch)
        assertEquals("c1", b1.parentId)
    }

    @Test
    fun decodeToleratesGarbageAndEmpty() {
        assertEquals(emptyList<StoredConversation>(), AiConversations.decode(""))
        assertEquals(emptyList<StoredConversation>(), AiConversations.decode("   "))
        assertEquals(emptyList<StoredConversation>(), AiConversations.decode("{ 这不是 json"))
        assertEquals(emptyList<StoredConversation>(), AiConversations.decode("""{"version":1,"conversations":"x"}"""))
    }

    @Test
    fun decodeIgnoresUnknownFieldsFromNewerVersions() {
        val text = """{"version":9,"conversations":[{"id":"c1","createdAt":1,"updatedAt":2,""" +
            """"totalTokens":5,"futureField":"x","messages":[{"role":"user","text":"你好","newThing":1}]}]}"""
        val list = AiConversations.decode(text)
        assertEquals(1, list.size)
        assertEquals("你好", list[0].messages[0].text)
    }

    @Test
    fun newIdsAreUnique() {
        assertNotEquals(AiConversations.newId(), AiConversations.newId())
    }

    // ================================================================== 显示

    @Test
    fun timeLabelCoversTodayYesterdayThisYearAndOlder() {
        val now = at(2026, 9, 15, 14, 32)
        assertEquals("09:05", AiConversations.timeLabel(at(2026, 9, 15, 9, 5), now, zone))
        assertEquals("昨天 20:10", AiConversations.timeLabel(at(2026, 9, 14, 20, 10), now, zone))
        assertEquals("9月3日", AiConversations.timeLabel(at(2026, 9, 3, 8, 0), now, zone))
        assertEquals("2025年12月1日", AiConversations.timeLabel(at(2025, 12, 1, 8, 0), now, zone))
        assertEquals("", AiConversations.timeLabel(0L, now, zone))
    }

    @Test
    fun clockLabelSwitchesToDateOnOtherDays() {
        assertEquals("09:05", AiConversations.clockLabel(at(2026, 9, 15, 9, 5), zone, today0))
        assertEquals("9月14日 20:10", AiConversations.clockLabel(at(2026, 9, 14, 20, 10), zone, today0))
    }

    @Test
    fun tokenLabelAvoidsLongNumbers() {
        assertEquals("0 tokens", AiConversations.tokenLabel(0))
        assertEquals("999 tokens", AiConversations.tokenLabel(999))
        assertEquals("1.0k tokens", AiConversations.tokenLabel(1000))
        assertEquals("1.6k tokens", AiConversations.tokenLabel(1584))
        assertEquals("12.0k tokens", AiConversations.tokenLabel(12_000))
    }

    @Test
    fun plainTextHasHeaderAndSkipsProcessNoise() {
        val conv = StoredConversation(
            id = "c1",
            createdAt = at(2026, 9, 15, 14, 0),
            updatedAt = at(2026, 9, 15, 14, 5),
            messages = listOf(
                user("这个月谁下单最多？"),
                assistant("老张蔬菜行 6 单。", tokens = 320).copy(
                    reasoning = "思考过程不该出现在复制内容里",
                    toolTrace = listOf("🔧 正在查：货主下单排行"),
                ),
            ),
        )
        val text = AiConversations.toPlainText(conv, zone)
        assertTrue(text.contains("【我】"))
        assertTrue(text.contains("【助手】"))
        assertTrue(text.contains("老张蔬菜行 6 单。"))
        assertTrue("头部要带时间，实际：$text", text.contains("2026-09-15 14:00"))
        assertTrue("头部要带用量", text.contains("320 tokens"))
        assertFalse("思考过程不该被复制出去", text.contains("思考过程不该出现"))
        assertFalse("工具痕迹不该被复制出去", text.contains("正在查"))
    }

    @Test
    fun messageHelperMapsRoleBothWays() {
        val u = AiConversations.message(isUser = true, text = "问")
        val a = AiConversations.message(isUser = false, text = "答")
        assertTrue(u.isUser)
        assertFalse(a.isUser)
        assertEquals(StoredMessage.ROLE_USER, u.role)
        assertEquals(StoredMessage.ROLE_ASSISTANT, a.role)
    }
}
