package com.tapmoay.sorders.ai

import com.tapmoay.sorders.core.ApiClient
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.LocalDate

/**
 * 「AI 把表递进聊天、点了能下载」这条链路的**数据面**（v3.34，CHG-0078，台账 L-43）。
 *
 * ### 为什么这几条非钉不可
 * 用户原话（m01794）：「他**首先第一点，他要自己做表格先给我看**……他会输出一个**下载按钮**……
 * **这个功能是要具备的在聊天框中**」。那颗按钮的全部依据就是一条**配方**（[StoredExportRecipe]）：
 * 它跟着消息**落盘**，所以 ——
 * - 键名漂一个字母，解出来就是一条**全默认值**的配方（`ignoreUnknownKeys` 把对不上的键当"多出来的"
 *   整段吃掉），症状是"按钮点了没反应"，而且一眼看不出为什么；
 * - 老对话（那时还没有这个键）必须**照读**且**不长出按钮**（⛔ 不许按今天的规则猜他当时想导出什么）；
 * - 文件名是**给用户对账用的凭证**（后端栽过一次"名字与内容不符"，2026-09-19 外部检查 R2-4），
 *   所以区间规则与中文名单独钉一遍。
 *
 * ### 什么不在这里
 * "点按钮之前**不发任何请求**"（工具回合不打后端、不建账本任务）与"配方**不进模型上下文**"这两条
 * 是**源码形状**，不在纯 JVM 单测里 —— 它们由 `_tools/qa/_check_ai_export_files.py` 逐字钉着，
 * 坏法注入见 `_tools/qa/_reverse_verify_ai_export_files.py`（"工具回合就建任务"／"配方漏给模型"两条）。
 */
class AiExportRecipeTest {

    private fun d(year: Int, month: Int, day: Int): LocalDate = LocalDate.of(year, month, day)

    /** 读盘那侧只吃"多出来的键"（`AiConversations` 那份 Json 同款）。 */
    private val stored = Json { ignoreUnknownKeys = true }

    private val ledgerRecipe = StoredExportRecipe(
        source = StoredExportRecipe.SOURCE_LEDGER,
        dateFrom = "2026-10-01",
        dateTo = "2026-10-31",
        shipperId = 12L,
        shipperName = "张三",
        fileName = "账本-张三-2026-10-01_2026-10-31.xlsx",
    )

    @Test
    fun `配方走一圈还是原来那条，十个键一个都不能少`() {
        // 用**写出去的那份 Json**（ApiClient.json，encodeDefaults = true）
        val raw = ApiClient.json.encodeToString(StoredExportRecipe.serializer(), ledgerRecipe)
        assertEquals(
            "键名漂了：读盘那侧会把对不上的键当「多出来的」整段忽略，解出来是一条全默认值的空配方",
            setOf(
                "source", "kind", "mode", "date", "dateFrom", "dateTo",
                "shipperId", "shipperName", "fileName", "jobId",
            ),
            Json.parseToJsonElement(raw).jsonObject.keys,
        )
        assertEquals(ledgerRecipe, StoredExportRecipe.parse(raw))
    }

    @Test
    fun `脏 JSON 只回 null，绝不把聊天页搞崩`() {
        assertNull(StoredExportRecipe.parse(""))
        assertNull(StoredExportRecipe.parse("不是 JSON"))
        assertNull(StoredExportRecipe.parse("[]"))
        assertNull(StoredExportRecipe.parse("null"))
        // 类型不对（source 给了数字）：宁可整条不要，也不许造出一条半真的配方
        assertNull(StoredExportRecipe.parse("{\"source\":123}"))
    }

    @Test
    fun `将来多出来的字段被忽略（加字段不会把老客户端搞崩）`() {
        val back = StoredExportRecipe.parse("{\"source\":\"report\",\"kind\":\"turnover\",\"future\":\"x\"}")
        assertNotNull(back)
        assertEquals(StoredExportRecipe.SOURCE_REPORT, back!!.source)
        assertEquals("turnover", back.kind)
    }

    @Test
    fun `老对话（没有 exportRecipe 这个键）照读，而且不长出文件行`() {
        val old = "{\"role\":\"assistant\",\"text\":\"已生成，请到「报表中心」查看/下载。\",\"at\":1759000000000}"
        val msg = stored.decodeFromString(StoredMessage.serializer(), old)
        assertNull("老对话不该凭空长出按钮", msg.exportRecipe)
        assertEquals("已生成，请到「报表中心」查看/下载。", msg.text)
        // 多一个将来才有的键也照读（老客户端遇到新写法不崩）
        val newer = stored.decodeFromString(StoredMessage.serializer(), "{\"role\":\"user\",\"text\":\"在\",\"somethingNew\":1}")
        assertEquals("在", newer.text)
    }

    @Test
    fun `带配方的消息存得下也读得回（关掉 App 再打开，按钮还在）`() {
        val msg = StoredMessage(
            role = StoredMessage.ROLE_ASSISTANT,
            text = "表在这儿，点下面的按钮就能下载。",
            exportRecipe = ledgerRecipe,
        )
        val raw = ApiClient.json.encodeToString(StoredMessage.serializer(), msg)
        assertEquals(ledgerRecipe, stored.decodeFromString(StoredMessage.serializer(), raw).exportRecipe)
    }

    @Test
    fun `账本任务号落盘后还在，没建过任务的配方是 0`() {
        // >0 = 再点只重新下载（⛔ 不再建任务、不再吃每天 20 次配额）；这条分支在 AiExportService.ledgerBytes，判据钉着
        val done = ledgerRecipe.copy(jobId = 42L)
        assertEquals(42L, StoredExportRecipe.parse(ApiClient.json.encodeToString(StoredExportRecipe.serializer(), done))!!.jobId)
        assertEquals(0L, StoredExportRecipe.parse("{\"source\":\"ledger\"}")!!.jobId)
    }

    @Test
    fun `文件名：只有一天就写一天，跨天写起止`() {
        assertEquals("2026-09-30", AiTools.spanLabel(d(2026, 9, 30), d(2026, 9, 30)))
        assertEquals("2026-09-01_2026-09-30", AiTools.spanLabel(d(2026, 9, 1), d(2026, 9, 30)))
        // 报表那颗按钮落盘的名字（报表页页签同名 + 区间 + .xlsx）
        assertEquals(
            "营业纵览-2026-09-01_2026-09-30.xlsx",
            AiTools.exportTitle("turnover") + "-" + AiTools.spanLabel(d(2026, 9, 1), d(2026, 9, 30)) + ".xlsx",
        )
        assertEquals(
            "账本-张三-2026-10-01_2026-10-31.xlsx",
            "账本-张三-" + AiTools.spanLabel(d(2026, 10, 1), d(2026, 10, 31)) + ".xlsx",
        )
    }

    @Test
    fun `六张表的中文名与报表页页签同名，认不出的原样回`() {
        assertEquals("营业纵览", AiTools.exportTitle("turnover"))
        assertEquals("商品经营", AiTools.exportTitle("products"))
        assertEquals("司机绩效", AiTools.exportTitle("drivers"))
        assertEquals("客户经营", AiTools.exportTitle("customers"))
        assertEquals("资金收支", AiTools.exportTitle("finance"))
        assertEquals("异常与审计", AiTools.exportTitle("audit"))
        assertEquals("不认识", AiTools.exportTitle("不认识"))
        assertEquals(6, AiTools.EXPORT_TITLES.size)
    }

    @Test
    fun `区间：月＝1 号到月末（⛔ 不是下月 1 号）`() {
        assertEquals(d(2026, 10, 1) to d(2026, 10, 31), AiTools.reportSpan("month", d(2026, 10, 7), null, null))
        assertEquals(d(2026, 12, 1) to d(2026, 12, 31), AiTools.reportSpan("month", d(2026, 12, 31), null, null))
        assertEquals("闰年 2 月要闭到 29 号", d(2024, 2, 1) to d(2024, 2, 29), AiTools.reportSpan("month", d(2024, 2, 10), null, null))
        assertEquals(d(2026, 10, 7) to d(2026, 10, 7), AiTools.reportSpan("day", d(2026, 10, 7), null, null))
        // 2026-10-07 是周三 ⇒ 本周 = 周一 10-05 ~ 周日 10-11
        assertEquals(d(2026, 10, 5) to d(2026, 10, 11), AiTools.reportSpan("week", d(2026, 10, 7), null, null))
        // 给了起止就照给（不按锚点重算）
        assertEquals(d(2026, 9, 1) to d(2026, 9, 30), AiTools.reportSpan("month", d(2026, 10, 7), d(2026, 9, 1), d(2026, 9, 30)))
    }

    @Test
    fun `区间：只给一头或倒着给，都要如实拒绝（⛔ 不猜另一头）`() {
        val oneHead = assertThrows(Exception::class.java) {
            AiTools.reportSpan("day", d(2026, 10, 7), d(2026, 10, 1), null)
        }
        assertTrue(oneHead.message!!, oneHead.message!!.contains("一起给"))
        val reversed = assertThrows(Exception::class.java) {
            AiTools.reportSpan("day", d(2026, 10, 7), d(2026, 10, 7), d(2026, 10, 1))
        }
        assertTrue(reversed.message!!, reversed.message!!.contains("开始日期不能晚于结束日期"))
    }
}
