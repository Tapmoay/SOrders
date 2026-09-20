package com.tapmoay.sorders.ai

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File
import java.nio.file.Files

/**
 * [AiJsonStore]：本地 JSON 文件仓储的四条策略 —— **它们以前一条测试都没有**。
 *
 * 为什么值得单独一个文件：这四条守的是**数据不丢**：
 * ① 先写 `.tmp` 再改名（写一半被杀不会留半截 JSON）；
 * ② "没读过盘就存"要退化成合并（否则会把盘上原来的东西盖掉 —— 真实发生过的丢历史事故）；
 * ③ 坏文件改名留证而不是删掉/覆盖；④ 任何异常都不抛。
 *
 * 它们原来散在 `AiConversationStore` / `AiMemoryStore` 里**各写一遍**（约 120 行），
 * 而且已经有一处走散（`clear()` 里 `everLoaded` 一个设一个没设）。那两个类需要 `Context`，
 * JVM 单测根本碰不到；收成一个只认 [File] 的 [AiJsonStore] 之后就能像这样覆盖。
 */
class AiJsonStoreTest {

    private data class Row(val id: String, val text: String)

    private fun newDir(): File = Files.createTempDirectory("aijsonstore").toFile()

    private fun storeIn(dir: File) = AiJsonStore(
        file = File(dir, "data.json"),
        encode = { list -> list.joinToString("\n") { "${it.id}|${it.text}" } },
        decode = { text ->
            // ⚠️ 认不出来的行直接丢掉（于是"有内容却解析不出任何一行"= 坏文件，走隔离那条路）
            text.lineSequence().filter { it.isNotBlank() && it.contains('|') }.map {
                val (id, body) = it.split("|", limit = 2)
                Row(id, body)
            }.toList()
        },
        merge = { disk, mine -> disk.filterNot { d -> mine.any { it.id == d.id } } + mine },
    )

    @Test
    fun `存了能读回来（往返）`() {
        val s = storeIn(newDir())
        assertTrue(s.save(listOf(Row("a", "一"), Row("b", "二"))))
        assertEquals(listOf(Row("a", "一"), Row("b", "二")), s.load())
        assertTrue(s.sizeBytes() > 0)
    }

    @Test
    fun `文件不存在时读出来是空的（不抛）`() {
        val s = storeIn(newDir())
        assertEquals(emptyList<Row>(), s.load())
        assertEquals(0L, s.sizeBytes())
    }

    @Test
    fun `没读过盘就存 → 合并而不是覆盖（防丢数据那条兜底）`() {
        val dir = newDir()
        // 先用一个实例落下旧数据，再用**另一个**实例（模拟"启动后还没 load"的那段窗口）保存
        storeIn(dir).save(listOf(Row("old", "旧的")))
        val fresh = storeIn(dir)
        assertTrue(fresh.save(listOf(Row("new", "新的"))))
        assertEquals(
            listOf(Row("old", "旧的"), Row("new", "新的")),
            storeIn(dir).load(),
        )
    }

    @Test
    fun `读过盘之后再存就是全量覆盖（删掉的条目真的没了）`() {
        val dir = newDir()
        storeIn(dir).save(listOf(Row("a", "一"), Row("b", "二")))
        val s = storeIn(dir)
        assertEquals(2, s.load().size)
        s.save(listOf(Row("a", "一改")))
        assertEquals(listOf(Row("a", "一改")), storeIn(dir).load())
    }

    @Test
    fun `坏文件读出来是空的，而且被改名留证（不是删掉也不是覆盖）`() {
        val dir = newDir()
        val file = File(dir, "data.json")
        file.writeText("这不是能解析的内容")   // 有内容、但解析不出任何一行 = 坏文件
        val s = storeIn(dir)
        assertEquals(emptyList<Row>(), s.load())
        val quarantined = dir.listFiles()!!.filter { it.name.startsWith("data.json.bad-") }
        assertEquals("坏文件必须留证（改名成 *.bad-<时间戳>）", 1, quarantined.size)
        assertEquals("这不是能解析的内容", quarantined[0].readText())
        assertFalse("原文件不该还留在原地", file.exists())
    }

    @Test
    fun `clear 之后文件没了、占用归零，且下一次保存是覆盖而不是又去合并`() {
        val dir = newDir()
        val s = storeIn(dir)
        s.save(listOf(Row("a", "一")))
        assertTrue(s.clear())
        assertFalse(File(dir, "data.json").exists())
        assertEquals(0L, s.sizeBytes())
        s.save(listOf(Row("b", "二")))
        assertEquals(listOf(Row("b", "二")), storeIn(dir).load())
    }

    @Test
    fun `原子写用完的临时文件不留下来`() {
        val dir = newDir()
        storeIn(dir).save(listOf(Row("a", "一")))
        assertEquals("写完不该留下 .tmp", 0, dir.listFiles()!!.count { it.name.endsWith(".tmp") })
    }
}
