package com.tapmoay.sorders.ui.dispatcher

import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 结算页那一行「还有 N 单运费没定价」（CHG-0029 / E2E 走查 P19）。
 *
 * 用户的原话是「王强真实送达的那单在『司机运费结算』页查不到，钱在运费模板 → 待定价，
 * 两页之间没有链接也没有角标」。这里钉的不是"多了一行字"，是**那一行必须把三件事
 * 同句说清**：还有多少单、它们不分司机、它们不在上面那张表里 —— 少任何一条，
 * 用户就会拿着那张表当完整的账去对，而钱其实躺在别处。
 *
 * ⛔ 被服务端截断（`X-Truncated`）时只能说「N 单以上」：说确数就是假话。
 */
class FreightSettlementNoticeTest {

    @Test
    fun `没有待定价的单时不显示那一行`() {
        assertNull(unpricedNotice(0, more = false))
        assertNull(unpricedNotice(0, more = true))
    }

    @Test
    fun `有待定价的单时三件事同句说清`() {
        val text = unpricedNotice(3, more = false)
        assertTrue("要说还有几单", text!!.contains("还有 3 单"))
        assertTrue("要说它们不分司机", text.contains("不分司机"))
        assertTrue("要说它们不在上面那张表里", text.contains("不在上面这张表里"))
        assertTrue("没有一个字提到金额（金额要等定价完才算得出来）", !text.contains("¥"))
    }

    @Test
    fun `被截断时只说单以上不说确数`() {
        val text = unpricedNotice(200, more = true)!!
        assertTrue(text.startsWith("还有 200 单以上"))
    }
}
