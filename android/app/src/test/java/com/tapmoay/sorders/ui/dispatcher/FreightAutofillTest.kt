package com.tapmoay.sorders.ui.dispatcher

import com.tapmoay.sorders.data.remote.dto.FreightQuoteCandidateDto
import com.tapmoay.sorders.data.remote.dto.FreightQuoteDto
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 派单时「按路线自动带出运费」的三条规则（CHG-0129）。
 *
 * 用户 2026-10-15：「运费模板已经绑定了路线，派单时路线匹配就直接带出钱。」
 * 这里钉的不是「多了一个功能」，是三件**错了也不报错**的事：
 * · 匹配不上却填了个价（甚至填 0）→ 用户以为这就是价，直接派单；
 * · 用户改过的数被自动带价盖回去 → 他改的那一下白改了，而且没有任何提示；
 * · 带了价却不说带的是哪一条 → 同一条路线本来就有「价格一价格二价格三」，
 *   看到 88 却不知道凭什么，用户只能去模板页一条条翻。
 */
class FreightAutofillTest {

    private fun cand(fee: String = "88.50", id: Long = 7, name: String = "价格一") =
        FreightQuoteCandidateDto(templateId = id, name = name, fee = fee)

    @Test
    fun `匹配上了就把那条价目的钱带出来`() {
        val a = autoFreightOf(FreightQuoteDto(matched = cand(), why = "同一条路线"))
        assertEquals("88.50", a!!.fee)
        assertEquals(7L, a.templateId)
        assertEquals("价格一", a.templateName)
    }

    @Test
    fun `带出来的钱是值不是字 —— 一位都不许动`() {
        // `12.3456` 过 formatMoney 会印成 `12.35`：那是「没改价、价却变了」
        assertEquals("12.3456", autoFreightOf(FreightQuoteDto(matched = cand(fee = "12.3456")))!!.fee)
    }

    @Test
    fun `匹配不上什么也不填`() {
        assertNull(autoFreightOf(null))
        assertNull(autoFreightOf(FreightQuoteDto(matched = null, reason = "这条路线还没有价目")))
    }

    @Test
    fun `后端说匹配上了但钱是空白也不填（不许拿 0 顶上）`() {
        assertNull(autoFreightOf(FreightQuoteDto(matched = cand(fee = "   "))))
        assertNull(autoFreightOf(FreightQuoteDto(matched = cand(fee = ""))))
    }

    @Test
    fun `没名字的价目也要能对上号`() {
        assertEquals("价目 #9", autoFreightOf(FreightQuoteDto(matched = cand(id = 9, name = " ")))!!.templateName)
    }

    @Test
    fun `手改过之后不许再覆盖`() {
        assertTrue(shouldOverwriteFreight(false))   // 没动过：可以带
        assertFalse(shouldOverwriteFreight(true))   // 自己填过：⛔ 不许改它
    }

    @Test
    fun `带出之后要说清选了哪一条、凭什么`() {
        val text = autoHint(AutoFreight(fee = "88.50", templateId = 7, templateName = "价格一", why = "同一条路线"))
        assertTrue(text.contains("价格一"))
        assertTrue(text.contains("同一条路线"))
        assertTrue("要说清可改（否则用户以为不能动）", text.contains("可改"))
    }

    @Test
    fun `后端没给理由时那一行也要能显示`() {
        val text = autoHint(AutoFreight(fee = "88.50", templateId = 7, templateName = "价格一", why = ""))
        assertTrue(text.contains("价格一"))
        assertTrue(text.isNotBlank())
    }

    @Test
    fun `没匹配到时只说为什么、不写金额`() {
        val text = noMatchHint("这条路线上的价目都不是「蔬菜」的")
        assertTrue(text.contains("这条路线上的价目都不是「蔬菜」的"))
        assertFalse("不许出现金额（此刻还没有价）", text.contains("¥"))
    }

    @Test
    fun `后端没给原因时也不能空着`() {
        assertTrue(noMatchHint("").isNotBlank())
        assertTrue(noMatchHint("   ").contains("没有匹配"))
    }

    @Test
    fun `问不出来时如实说是问不出来、不说没有价目`() {
        val text = failedHint("连接超时")
        assertTrue(text.contains("连接超时"))
        assertFalse("不能说成「没有匹配的价目」—— 那是在替后端编结论", text.contains("没有匹配"))
        assertTrue(failedHint(null).contains("网络错误"))
    }

    @Test
    fun `车型只传后端认的那三个值（传别的会把整次自动带价打成 400）`() {
        assertEquals("small", vehicleForAutofill("small"))
        assertEquals("large", vehicleForAutofill(" large "))
        assertEquals("trailer", vehicleForAutofill("trailer"))
        assertNull(vehicleForAutofill(null))
        assertNull(vehicleForAutofill(""))
        assertNull(vehicleForAutofill("大车"))   // 老数据里的中文：当没填
    }
}
