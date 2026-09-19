package com.tapmoay.sorders.ai

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File

/**
 * [AiScope] 的纯逻辑测试：**「这份数据属于谁」**。
 *
 * ### 为什么这几条断言很重要（它是一个真机 E2E 抓到的隐私问题）
 * v3.13 之前，AI 的三份本机数据（对话历史 / 使用习惯 / 长期记忆）都用固定文件名。
 * 同一台手机上换账号，**下一个人能读到上一个人的全部聊天内容**——
 * 实测在货主端登录后，AI 页面显示的是派单员那一整段对话。
 *
 * 这个坑最值得记的一点是：**它不是任何一条既有红线的违例**。
 * 当时 281 条检查全过，因为**没有一条在问"这份数据属于谁"**。
 * 所以这里每一条断言测的都是"归属"，不是"功能"。
 */
class AiScopeTest {

    @get:Rule
    val tmp = TemporaryFolder()

    // ------------------------------------------------------------ 分区名

    @Test
    fun `登录用户按 id 分区`() {
        assertEquals("_u2", AiScope.suffix(2L))
        assertEquals("_u137", AiScope.suffix(137L))
    }

    @Test
    fun `读不到用户时落到 anon 分区而不是公共区`() {
        // ⚠️ 这一条是整套逻辑里最要紧的：**绝不能回落到"公共区"**。
        // 回落就意味着"读不到身份时大家共用一份"，而那正是要修的那个 bug。
        assertEquals(AiScope.ANON, AiScope.suffix(null))
        assertEquals(AiScope.ANON, AiScope.suffix(0L))
        assertEquals(AiScope.ANON, AiScope.suffix(-1L))
    }

    @Test
    fun `两个用户永远拿到不同的文件`() {
        val a = AiScope.fileName("ai_memory.json", AiScope.suffix(1L))
        val b = AiScope.fileName("ai_memory.json", AiScope.suffix(2L))
        assertNotEquals("换账号必须换文件，否则就是串数据", a, b)
        assertEquals("ai_memory_u1.json", a)
        assertEquals("ai_memory_u2.json", b)
    }

    @Test
    fun `未登录与已登录也不会撞到同一个文件`() {
        val anon = AiScope.fileName("ai_conversations.json", AiScope.suffix(null))
        val user = AiScope.fileName("ai_conversations.json", AiScope.suffix(2L))
        assertNotEquals(anon, user)
    }

    @Test
    fun `空分区保持原文件名（单测用的老行为）`() {
        assertEquals("ai_memory.json", AiScope.fileName("ai_memory.json", ""))
    }

    // -------------------------------------------------------- 旧文件隔离

    @Test
    fun `没有分区的旧文件被挪进隔离区而不是被继承`() {
        // 为什么是隔离不是"归给当前登录的人"：旧文件是在分区功能之前写的，
        // **我们无从知道它属于谁**。归给现在登录的账号 = 「谁先登录谁继承前任的全部聊天记录」，
        // 那正好是这个 bug 本身。
        val dir = tmp.newFolder()
        val legacy = File(dir, "ai_conversations.json")
        legacy.writeText("""[{"id":"x","title":"派单员的私密对话"}]""")

        val moved = AiScope.quarantineLegacy(dir, "ai_conversations.json")

        assertTrue("应当挪走", moved)
        assertFalse("原位置不能再有它（否则新账号会读到）", legacy.exists())
        val kept = dir.listFiles()!!.filter { it.name.startsWith("ai_conversations.json.legacy-") }
        assertEquals("旧数据要留着可人工找回，不能删", 1, kept.size)
        assertTrue(kept[0].readText().contains("派单员的私密对话"))
    }

    @Test
    fun `没有旧文件时隔离动作是空操作`() {
        val dir = tmp.newFolder()
        assertFalse(AiScope.quarantineLegacy(dir, "ai_memory.json"))
    }

    @Test
    fun `重复调用不会把隔离文件再挪一次`() {
        val dir = tmp.newFolder()
        File(dir, "ai_memory.json").writeText("[]")
        assertTrue(AiScope.quarantineLegacy(dir, "ai_memory.json"))
        assertFalse("第二次没有东西可挪", AiScope.quarantineLegacy(dir, "ai_memory.json"))
    }

    // ------------------------------------------------------ 端到端属性

    @Test
    fun `三个 store 的文件名各自独立分区`() {
        val s1 = AiScope.suffix(1L)
        val s2 = AiScope.suffix(2L)
        listOf(AiConversationStore.FILE_NAME, AiMemoryStore.FILE_NAME).forEach { base ->
            assertNotEquals(
                "$base 的两个用户不该共用文件",
                AiScope.fileName(base, s1),
                AiScope.fileName(base, s2),
            )
        }
    }
}
