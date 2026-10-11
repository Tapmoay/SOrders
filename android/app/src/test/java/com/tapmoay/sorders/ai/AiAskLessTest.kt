package com.tapmoay.sorders.ai

import com.tapmoay.sorders.core.AccountRules
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 「**能按默认值推断出来的，就不要问**」—— 用户 2026-10-11 的口径（CHG-0120）。
 *
 * 用户原话（逐字）：
 * > 「这个 AI 啊**太过繁琐**了 —— 教他执行任务了，他**老是反复确定**，但其实任务其实
 * >   **也全都已经写好了、基本是已经确认的**。」
 *
 * 这几条测试钉的是**提示词真的那一份**（[AiDefaults.RULES]）：它是不是真的列了默认值、
 * 是不是真的写了「能推断就别问 / 假设写在卡上 / 真要问就一次问全 / 没有默认值才问」。
 * 为什么非得有它：这段文字**少一句都不会报错**，只会表现为「AI 又开始一轮一轮地问」——
 * 而那正是用户抱怨的事（真机上为了一张 21 人的表格，来回五六轮才动手）。
 *
 * ⚠️ 这里读的必须是**提示词用的那一份**（不是测试里另抄一份）：抄一份之后，
 * 提示词改了、测试还是绿的（本仓库栽过多次）。
 */
class AiAskLessTest {

    /** 提示词真正用的那一份（[AiAgentLoop.systemPrompt] 里 `append(AiDefaults.RULES)` 就是它）。 */
    private val rules: String = AiDefaults.RULES

    @Test
    fun `默认值清单出现在提示词里（六条都在）`() {
        val p = rules
        for (w in listOf("初始密码", "成本价", "默认单价", "单位", "专属价", "先取来用")) {
            assertTrue("默认值清单里要有「$w」这一条 → $p", p.contains(w))
        }
        assertTrue("要说明这张单子的完整版在哪（改之前先看它）→ $p", p.contains("docs/AI_DEFAULTS.md"))
    }

    @Test
    fun `规则语句在：能按默认值推断出来的，不要问`() {
        val p = rules
        assertTrue("要有这一条 → $p", p.contains("能按下面这张单子推断出来的，不要问"))
        assertTrue("要写清是「直接做」，不是「先问一句再动手」→ $p", p.contains("直接做"))
    }

    @Test
    fun `禁多轮那句在：真要问，就一次问全`() {
        val p = rules
        assertTrue("要写明一次问全 → $p", p.contains("真要问，就一次问全"))
        assertTrue("要明确禁止一轮问一个 → $p", p.contains("不许一轮问一个"))
        assertTrue("并写明用户答完就照着做 → $p", p.contains("不要回头再确认一遍"))
    }

    @Test
    fun `假设要写在确认卡上（用户要能看出 AI 替他定了什么）`() {
        val p = rules
        assertTrue("要写明假设写在卡片上 → $p", p.contains("用过的假设写在**卡片**上"))
        assertTrue("要给出样子（初始密码那条）→ $p", p.contains("初始密码按"))
        assertTrue("要给出样子（成本价那条）→ $p", p.contains("成本价按进货成本"))
    }

    @Test
    fun `安全底线仍在：单子上没有默认值的钱与身份必须先问`() {
        val p = rules
        assertTrue("三类都要写到 → $p", p.contains("钱") && p.contains("身份") && p.contains("撤不回来"))
        assertTrue("而且要写明前提是「没有默认值」→ $p", p.contains("都没有默认值"))
        assertTrue("并写明这时必须问 → $p", p.contains("必须先问他"))
        assertTrue("拿不准时按没有处理（不许猜一个数）→ $p",
            p.contains("按没有处理") && p.contains("不许猜一个数字"))
        assertTrue("确认卡不许被这张单子绕过 → $p", p.contains("跳过确认卡"))
    }

    @Test
    fun `清单里那几条口径写得明白（成本价、单价、单位、专属价）`() {
        val p = rules
        assertTrue("成本价存进货成本 → $p", p.contains("那一格填**进货成本**"))
        assertTrue("返点后成本不是那一格 → $p", p.contains("返点后成本"))
        assertTrue("默认单价用表里的零售价 → $p", p.contains("**默认单价**：表格"))
        assertTrue("单位沿用同类或既有商品 → $p", p.contains("沿用**同类或既有商品**的单位"))
        assertTrue("专属价逐家给价就直接设 → $p", p.contains("直接按表格设专属价"))
    }

    @Test
    fun `密码那一项只引用 AccountRules 常量（提示词里不许手抄数字）`() {
        val p = rules
        assertEquals("App 侧那个常量本身就是规定值", "123321", AccountRules.DEFAULT_INITIAL_PASSWORD)
        assertTrue("提示词里要有密码这一项 → $p", p.contains("初始密码"))
        assertTrue("而且要用常量拼出来 → $p", p.contains(AccountRules.DEFAULT_INITIAL_PASSWORD))
        assertFalse(
            "这两个数只该由常量拼出来，字面量只许留在 core/AccountRules.kt → $p",
            p.replace(AccountRules.DEFAULT_INITIAL_PASSWORD, "").contains("123321"),
        )
    }
}
