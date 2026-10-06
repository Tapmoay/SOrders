package com.tapmoay.sorders.ai

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * [AiAnswerTone] 的纯逻辑测试（台账 L-24「重要的信息用特殊的样式」）。
 *
 * 为什么单独给一份：颜色是**界面给用户的核心视觉信号**（钱 / 异常 / 提醒 / 正常），
 * 判定却只是一张封闭词表 + 一条正则。词表写歪的后果不是"丑"，而是**误导**——
 * 把「无异常」染成红的，用户会以为出了事、去核账；把该红的漏掉，用户会漏掉一笔逾期。
 * 所以这里逐类穷举，并把三条上限（条数 / 种类 / 长度）钉死。
 */
class AiAnswerToneTest {

    private fun tone(s: String): AnswerTone? = AiAnswerTone.toneOf(s)

    @Test
    fun 四类各命中一次() {
        assertEquals(AnswerTone.MONEY, tone("¥1,280"))
        assertEquals(AnswerTone.MONEY, tone("合计 ¥1,280"))
        assertEquals(AnswerTone.MONEY, tone("3200 元"))
        assertEquals(AnswerTone.DANGER, tone("逾期 3 单"))
        assertEquals(AnswerTone.WARN, tone("待处理"))
        assertEquals(AnswerTone.OK, tone("已送达"))
    }

    @Test
    fun 无异常是正常而不是危险() {
        // 词表里「异常」两个字会把「无异常」判成坏消息。这是最难发现的一类错：
        // 屏幕上出现红色，用户会去核账，而其实什么都没发生。
        assertEquals(AnswerTone.OK, tone("无异常"))
        assertEquals(AnswerTone.OK, tone("没有异常"))
        assertEquals(AnswerTone.OK, tone("已恢复"))
    }

    @Test
    fun 一整句话不上色() {
        // 长句里出现「逾期」不代表这句话是一个"值"；整句染色正是用户说的"乱搞样式"。
        assertNull(tone("这个月一共 3 单逾期，建议尽快联系司机"))
        assertNull(tone("异常情况请及时上报，避免影响结算"))
        // 没有标点但太长，同样不上色（\n 换成空格也一样）
        assertNull(tone("这一个订单已经送达而且款项也已经结清"))
    }

    @Test
    fun 普通行不上色() {
        assertNull(tone("王建国"))
        assertNull(tone("SO20260001"))
        assertNull(tone(""))
        assertNull(tone("   "))
    }

    @Test
    fun 整条回答按阅读顺序先到先得且最多两种颜色() {
        // 第三种颜色一出现，重点就不成其为重点了（用户原话：「不能随便乱搞」）。
        val blocks = AiMarkdown.parse("逾期 3 单\n¥1,280\n待处理\n已送达")
            .filterIsInstance<AiMarkdown.Block.Line>()
        val toned = AiAnswerTone.apply(blocks).filterIsInstance<AiMarkdown.Block.Line>()
        assertEquals(
            listOf(AnswerTone.DANGER, AnswerTone.MONEY, null, null),
            toned.map { it.spans.first().tone },
        )
    }

    @Test
    fun 最多染十二处() {
        val text = (1..20).joinToString("\n") { "¥" + it }
        val blocks = AiMarkdown.parse(text).filterIsInstance<AiMarkdown.Block.Line>()
        val toned = AiAnswerTone.apply(blocks).filterIsInstance<AiMarkdown.Block.Line>()
        assertEquals(AiAnswerTone.MAX_TONED, toned.count { it.spans.first().tone != null })
        assertEquals(20, toned.size)
    }

    @Test
    fun 标题与列表行同样上色() {
        val blocks = AiMarkdown.parse("## 合计 ¥3,200\n- 已送达")
            .filterIsInstance<AiMarkdown.Block.Line>()
        val toned = AiAnswerTone.apply(blocks).filterIsInstance<AiMarkdown.Block.Line>()
        assertEquals(AnswerTone.MONEY, toned[0].spans.first().tone)
        assertEquals(AnswerTone.OK, toned[1].spans.first().tone)
        // 「欠款」是坏消息 —— 即使后面跟着钱：危险优先于钱（顺序反了会把催款行染成橙色）。
        assertEquals(AnswerTone.DANGER, tone("欠款 ¥3,200"))
    }

    @Test
    fun 表格原样返回且粗体一个字都不改() {
        // 表格的配色是既有裁定（中性白卡、不跟随气泡），这里不许掺一脚。
        val table = AiMarkdown.Block.Table(
            listOf("项目", "金额"),
            listOf(listOf("货款", "¥1,280")),
        )
        val line = AiMarkdown.Block.Line(
            listOf(AiMarkdown.Span("合计 ", bold = true), AiMarkdown.Span("¥1,280")),
            AiMarkdown.Block.Kind.TEXT,
        )
        val out = AiAnswerTone.apply(listOf(table, line))
        assertEquals(table, out[0])
        val l = out[1] as AiMarkdown.Block.Line
        assertEquals("合计 ", l.spans[0].text)
        assertTrue("粗体不许被改掉", l.spans[0].bold)
        assertNull("粗体那一格不因为行里有金额就跟着变色", l.spans[0].tone)
        assertEquals(AnswerTone.MONEY, l.spans[1].tone)
        assertEquals("¥1,280", l.spans[1].text)
    }
}
