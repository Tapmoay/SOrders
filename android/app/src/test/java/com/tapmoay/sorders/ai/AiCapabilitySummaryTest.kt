package com.tapmoay.sorders.ai

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 「AI 设置页的能力说明默认折起来」在**纯函数**这一侧的测试（台账 L-63 / CHG-0098）。
 *
 * ### 为什么这件事要有机器判据
 * 用户 2026-10-09 发来「AI 设置」页截图：那张卡**大半屏**都是「能查：…」「能改：…」，
 * 语音转写逐字（ref `m01649`）：「顺便把这个做一个折叠和隐藏啊，他那些详情的解释啊，
 * 不然太长了很占位子。」
 *
 * 折起来这一行是用户点开之前**唯一的线索**，而它有两个"坏了谁都不报错"的坑：
 * 1. 只写「展开」两个字 —— 能力清单一并藏了，用户得盲点一次才知道有没有他要找的；
 * 2. 报的数字是**手写**的 —— 手写清单会和真实能力走散，这一页已经因此错过一次
 *    （批量调价 v3.21 上线了，这页还写着「改价做不了」，见 `AiSettingsScreen` 里那段 KDoc）。
 *
 * ⛔ 所以这一档测试**故意不写死"90 项"这种数字**，而是把 `AiRolePrompt.settingsSummary`
 * 真跑出来的那段话数一遍、拿它当期望值 —— 将来真加了能力，测试跟着走，不会假红。
 */
class AiCapabilitySummaryTest {

    /** 真·派单员（管理员）的能力说明。 */
    private val dispatcherSummary =
        AiRolePrompt.settingsSummary(AiActor.byRole(AiRole.DISPATCHER))

    @Test
    fun `派单员_报出来的数字就是那段话里数出来的`() {
        val counts = capabilitySummaryCounts(dispatcherSummary)
        // 期望值**从那段话本身算**（不去手写 90/24 这种数字）
        val readLine = dispatcherSummary.lines().first { it.startsWith("能查：") }
        val writeLine = dispatcherSummary.lines().first { it.startsWith("能改：") }
        assertEquals(
            "能查的项数必须等于那段话里「、」分隔的条数",
            readLine.removePrefix("能查：").split('、').count { it.isNotBlank() },
            counts.canRead,
        )
        assertEquals(
            "能改的项数必须等于那段话里「、」分隔的条数",
            writeLine.removePrefix("能改：").split('、').count { it.isNotBlank() },
            counts.canWrite,
        )
        // 反空转：解析真挂了就会双双为 0，那是"全绿但其实什么都没数"
        assertTrue("派单员的能查项数不该是 0（解析挂了？）：$counts", counts.canRead > 0)
        assertTrue("派单员的能改项数不该是 0（解析挂了？）：$counts", counts.canWrite > 0)
        assertTrue("派单员这档必须认为「能改」是已知的", counts.canWriteKnown)
    }

    @Test
    fun `折起来那一行要报数_不能只写展开两个字`() {
        val label = capabilitySummaryLabel(capabilitySummaryCounts(dispatcherSummary), expanded = false)
        val counts = capabilitySummaryCounts(dispatcherSummary)
        assertTrue("折起来的标题里要有能查的项数：$label", label.contains("能查 ${counts.canRead} 项"))
        assertTrue("折起来的标题里要有能改的项数：$label", label.contains("能改 ${counts.canWrite} 项"))
        assertTrue("还要说清点得开：$label", label.contains("点开看清单"))
        // ⛔ 只写「展开」= 把"有多少东西"一起藏了
        assertFalse("标题不许退化成一个光秃秃的「展开」：$label", label == "展开" || label == "查看")
    }

    @Test
    fun `展开之后那句要写收起_不然点不动第二次`() {
        val label = capabilitySummaryLabel(capabilitySummaryCounts(dispatcherSummary), expanded = true)
        assertEquals("展开态那一行只写「收起清单」", "收起清单", label)
        assertFalse("展开态不该还留着「点开看清单」：$label", label.contains("点开看清单"))
        assertFalse("展开态不该还报数（数字是给折起来那行用的）：$label", label.contains("项"))
    }

    @Test
    fun `认不出角色_不许报数_只说点开看清单`() {
        // 这一段是 fail-closed 的兜底话（没有「能查：」「能改：」两行）
        val lost = AiRolePrompt.settingsSummary(null)
        assertTrue("这是兜底那句话，前提得对上：$lost", lost.contains("没认出你的角色"))
        val counts = capabilitySummaryCounts(lost)
        assertEquals("认不出角色时不该数出能查项数", 0, counts.canRead)
        assertEquals("认不出角色时不该数出能改项数", 0, counts.canWrite)
        assertFalse("认不出角色时「能改」是未知的，不许报 0 项", counts.canWriteKnown)
        assertEquals("能做什么（点开看清单）", capabilitySummaryLabel(counts, expanded = false))
    }

    @Test
    fun `读开关全关掉_能查那行写的是暂时没有_不许数成一项`() {
        // 「能查：暂时没有（下面的只读开关都被关掉了）」—— 那是**兜底话**，不是清单里的一项
        val none = AiRolePrompt.settingsSummary(
            actor = AiActor.byRole(AiRole.DISPATCHER),
            readModules = emptySet(),
        )
        assertTrue("前提得对上（这行确实写了「暂时没有」）：$none", none.contains("暂时没有"))
        assertEquals("兜底话不许被数成 1 项", 0, capabilitySummaryCounts(none).canRead)
    }

    @Test
    fun `一项能改的都没有_不许报能改0项`() {
        // 「看起来有、其实没有」在本项目里是红线：报「能改 0 项」和报一个假能力一样糟
        val counts = AiCapabilitySummary(canRead = 12, canWrite = 0, canWriteKnown = true)
        val label = capabilitySummaryLabel(counts, expanded = false)
        assertEquals("没有能改的就只报能查：$label", "能查 12 项（点开看清单）", label)
        assertFalse("不许出现「能改 0 项」：$label", label.contains("能改"))
    }

    @Test
    fun `数出来的项数跟开关联动_关掉一个少一项`() {
        // 这条是"数字真是从那段话里来的"的反证：把只读模块少给一个，数字必须跟着小
        val full = capabilitySummaryCounts(dispatcherSummary).canRead
        val all = AiReads.allModules().toSet()
        assertEquals("前提：模块清单不止一个", true, all.size > 1)
        val less = AiReads.allModules().toSet() - all.first()
        val fewer = capabilitySummaryCounts(
            AiRolePrompt.settingsSummary(actor = AiActor.byRole(AiRole.DISPATCHER), readModules = less),
        ).canRead
        assertEquals("少开一个只读模块，能查项数必须少一（说明数字不是手写的）", full - 1, fewer)
    }
}
