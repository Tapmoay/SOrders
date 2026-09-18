package com.tapmoay.sorders.ai

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 带图消息的**线上格式**（[ChatMessageSerializer]）。
 *
 * ### 为什么这条值得单独钉住
 * `content` 从字符串变成多模态数组，是"同一个字段在两种形状之间切换"——
 * 这正是最容易把**不带图的老路径也改坏**的地方：一旦不带图时也发成数组，
 * 所有不支持多模态的端点（DeepSeek 等）会集体 400，而报错信息通常只说"参数错误"。
 * 所以这里两头都测：**不带图必须一个字节都不变**，带图才变数组。
 */
class ChatMessageSerializerTest {

    private val json = Json { encodeDefaults = false; explicitNulls = false; ignoreUnknownKeys = true }
    private val dataUrl = "data:image/jpeg;base64,AAAA"

    @Test
    fun `不带图时 content 仍然是字符串（老端点不受影响）`() {
        val wire = json.encodeToString(ChatMessage.serializer(), ChatMessage.user("你好"))
        assertTrue(wire, wire.contains("\"content\":\"你好\""))
        assertFalse("不带图不该出现数组", wire.contains("["))
        assertFalse("images 不该出现在线上 JSON 里", wire.contains("images"))
    }

    @Test
    fun `system 与 assistant 与 tool 的格式不变`() {
        val sys = json.encodeToString(ChatMessage.serializer(), ChatMessage.system("S"))
        assertEquals("""{"role":"system","content":"S"}""", sys)
        val tool = json.encodeToString(ChatMessage.serializer(), ChatMessage.tool("call_1", "ok"))
        assertTrue(tool, tool.contains("\"tool_call_id\":\"call_1\""))
    }

    @Test
    fun `带图时 content 变成 文本+图片 的多模态数组`() {
        val m = ChatMessage.userWithImages("看看这张", listOf(dataUrl))
        val wire = json.encodeToString(ChatMessage.serializer(), m)
        val obj = Json.parseToJsonElement(wire).jsonObject
        val arr = obj["content"]!!.jsonArray
        assertEquals(2, arr.size)
        assertEquals("text", arr[0].jsonObject["type"]!!.jsonPrimitive.content)
        assertEquals("看看这张", arr[0].jsonObject["text"]!!.jsonPrimitive.content)
        assertEquals("image_url", arr[1].jsonObject["type"]!!.jsonPrimitive.content)
        assertEquals(dataUrl, arr[1].jsonObject["image_url"]!!.jsonObject["url"]!!.jsonPrimitive.content)
    }

    @Test
    fun `只发图不打字时数组里只有图片那一项`() {
        val wire = json.encodeToString(ChatMessage.serializer(), ChatMessage.userWithImages("", listOf(dataUrl)))
        val arr = Json.parseToJsonElement(wire).jsonObject["content"]!!.jsonArray
        assertEquals(1, arr.size)
        assertEquals("image_url", arr[0].jsonObject["type"]!!.jsonPrimitive.content)
    }

    @Test
    fun `反序列化：字符串形态照常读`() {
        val m = json.decodeFromString(ChatMessage.serializer(), """{"role":"assistant","content":"好的"}""")
        assertEquals("好的", m.content)
        assertTrue(m.images.isEmpty())
    }

    @Test
    fun `反序列化：数组形态把 text 分片拼起来（个别端点会这么回）`() {
        val raw = """{"role":"assistant","content":[{"type":"text","text":"前半"},{"type":"text","text":"后半"}]}"""
        val m = json.decodeFromString(ChatMessage.serializer(), raw)
        assertEquals("前半后半", m.content)
    }

    @Test
    fun `反序列化：content 为 null 也不炸（只调工具的那种回复）`() {
        val m = json.decodeFromString(
            ChatMessage.serializer(),
            """{"role":"assistant","content":null,"tool_calls":[{"id":"c1","type":"function","function":{"name":"read_data","arguments":"{}"}}]}""",
        )
        assertNull(m.content)
        assertEquals("read_data", m.toolCalls?.first()?.function?.name)
    }

    @Test
    fun `reasoning_content 原样读进来（由 buildChatRequest 负责剥掉）`() {
        val m = json.decodeFromString(
            ChatMessage.serializer(),
            """{"role":"assistant","content":"x","reasoning_content":"想一下"}""",
        )
        assertEquals("想一下", m.reasoningContent)
    }
}

/**
 * 「这个模型能不能看图」（[AiVision]）。
 *
 * 判错的两种代价都不小：**判成能看** → 带图去撞 400，用户在一次正常提问里遇到报错；
 * **判成不能看** → 用户手上明明是个视觉模型却怎么都传不上图。所以两头都有用例。
 */
class AiVisionTest {

    @Test
    fun `视觉模型按名字认出来`() {
        listOf(
            "qwen-vl-max", "qwen2.5-vl-72b-instruct", "doubao-1.5-vision-pro",
            "glm-4v-plus", "gpt-4o", "gemini-1.5-pro", "claude-3-5-sonnet", "step-1v-8k",
        ).forEach {
            assertEquals(it, AiVision.Support.YES, AiVision.support(it))
            assertTrue(it, AiVision.canSendImages(it))
            assertNull(it, AiVision.hint(it))
        }
    }

    @Test
    fun `不是对话的模型明确拦住并说清怎么办`() {
        // ⚠️ 判据是"从名字就能确定它不聊天"，**不是按厂商前缀判**：
        // 曾经把 `deepseek` 整个判成看不了图，用户当场纠正「最新的 deepseek flash 是多模态的」。
        val model = "text-embedding-3-large"
        assertEquals(AiVision.Support.NO, AiVision.support(model))
        assertFalse(AiVision.canSendImages(model))
        assertTrue(AiVision.hint(model)!!.contains("对话模型"))
    }

    @Test
    fun `deepseek-flash 不再被拦（用户实测它支持看图）`() {
        // 用户原话：「最新的 deepseek flash 是一个多模态的模型，它是支持看照片的」。
        // 认不出名字 ≠ 不支持——放行，万一端点真的不收图，
        // LlmClient 会自动去掉图重试一次并在回答里说明（见 ChatMessageSerializerTest 上方那段注释）。
        assertEquals(AiVision.Support.UNKNOWN, AiVision.support("deepseek-flash"))
        assertTrue(AiVision.canSendImages("deepseek-flash"))
        assertNull("认不出来就不该弹警告（用户比我们清楚自己用的是哪个模型）", AiVision.hint("deepseek-flash"))
    }

    @Test
    fun `embedding 之类的非对话模型也算看不了图`() {
        assertEquals(AiVision.Support.NO, AiVision.support("bge-rerank-v2"))
        assertEquals(AiVision.Support.NO, AiVision.support("whisper-large-v3"))
    }

    @Test
    fun `认不出名字时放行且不打扰`() {
        assertEquals(AiVision.Support.UNKNOWN, AiVision.support("some-new-model-2027"))
        assertTrue(AiVision.canSendImages("some-new-model-2027"))
        assertNull(AiVision.hint("some-new-model-2027"))
    }

    @Test
    fun `空模型名不炸`() {
        assertEquals(AiVision.Support.UNKNOWN, AiVision.support(null))
        assertEquals(AiVision.Support.UNKNOWN, AiVision.support("   "))
        assertTrue(AiVision.canSendImages(null))
    }
}

/** 图片附件在提示词里的样子（[AiAttachment]）：图片是**真的发过去**的，不是转文字。 */
class AiAttachmentImageTest {

    private fun img(name: String = "order.jpg") = AiAttachment(
        filename = name,
        kind = "image",
        tables = emptyList(),
        imageDataUrl = "data:image/jpeg;base64,AAAA",
        imageMeta = "约 120KB（已压缩到长边 1280，够看清）",
    )

    @Test
    fun `图片附件不带表格，摘要写图片与规模`() {
        val a = img()
        assertTrue(a.isImage)
        assertTrue(a.summary(), a.summary().contains("图片"))
        assertTrue(a.summary(), a.summary().contains("120KB"))
    }

    @Test
    fun `提示词里说清「图是发给你看的」，并要求看不清就说看不清`() {
        val text = AiAttachment.augment("帮我看看这单", listOf(img()))
        assertTrue(text, text.contains("帮我看看这单"))
        assertTrue(text, text.contains("order.jpg"))
        assertTrue(text, text.contains("已经作为图片发给你"))
        // 最关键的一句：不许猜（猜出来的名字会一路写进系统）
        assertTrue(text, text.contains("看不清"))
        assertTrue(text, text.contains("不要凭印象猜"))
    }

    @Test
    fun `提示词里绝不能出现 base64（它会写进对话历史，把文件撑爆）`() {
        val text = AiAttachment.augment("看图", listOf(img()))
        assertFalse(text, text.contains("base64"))
        assertFalse(text, text.contains("AAAA"))
    }

    @Test
    fun `data URL 单独取出来给多模态内容用`() {
        assertEquals(listOf("data:image/jpeg;base64,AAAA"), AiAttachment.imagesOf(listOf(img())))
        assertTrue(AiAttachment.imagesOf(listOf()).isEmpty())
    }

    @Test
    fun `图片和表格混着挂时，两种说明都在`() {
        val table = AiAttachment(
            filename = "商品.xlsx", kind = "xlsx",
            tables = listOf(AiAttachment.Table("Sheet1", listOf(listOf("商品名"), listOf("苹果")), 2, 1, false)),
        )
        val text = AiAttachment.augment("一起看", listOf(table, img("list.jpg")))
        assertTrue(text, text.contains("商品名"))
        assertTrue(text, text.contains("已经作为图片发给你"))
        assertEquals(1, AiAttachment.imagesOf(listOf(table, img())).size)
    }
}

/** 表格排版的两个判据（Excel 观感：数字右对齐、合计行加粗）。 */
class AiMarkdownTableLayoutTest {

    private fun table(header: List<String>, vararg rows: List<String>) =
        AiMarkdown.Block.Table(header, rows.toList())

    @Test
    fun `数字列右对齐，文字列左对齐`() {
        val t = table(
            listOf("商品", "数量", "金额"),
            listOf("红富士苹果", "12", "¥540.00"),
            listOf("海南香蕉", "3", "9.00"),
            listOf("农夫山泉", "300", "6600"),
        )
        assertEquals(listOf(false, true, true), AiMarkdown.numericColumns(t))
    }

    @Test
    fun `带单位与百分号的也算数字列`() {
        val t = table(
            listOf("司机", "单量", "准时率", "耗时"),
            listOf("王建国", "22", "31.8%", "430.8 分钟"),
            listOf("李长顺", "18", "95.0%", "120 分钟"),
        )
        assertEquals(listOf(false, true, true, true), AiMarkdown.numericColumns(t))
    }

    @Test
    fun `一列里多数不是数字就不右对齐（混着文字的列右对齐很难看）`() {
        val t = table(
            listOf("状态", "备注"),
            listOf("3 件", "待定价"),
            listOf("已完成", "已收款"),
            listOf("已完成", "已收款"),
        )
        assertEquals(listOf(false, false), AiMarkdown.numericColumns(t))
    }

    @Test
    fun `空表不炸`() {
        assertEquals(listOf(false), AiMarkdown.numericColumns(table(listOf("商品名"))))
    }

    @Test
    fun `合计行认得出来（结论不该长得像明细）`() {
        assertTrue(AiMarkdown.isTotalRow(listOf("合计", "335", "7149.00")))
        assertTrue(AiMarkdown.isTotalRow(listOf("总计", "—", "—")))
        assertFalse(AiMarkdown.isTotalRow(listOf("红富士苹果", "12", "540")))
        assertFalse(AiMarkdown.isTotalRow(emptyList()))
    }
}
