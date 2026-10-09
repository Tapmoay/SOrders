package com.tapmoay.sorders.ai

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 「用户存过的那份**工具**白名单」怎么算成这次生效的工具（`AiKeyStore.resolveEnabledTools`）。
 *
 * ### 为什么要有这个文件（2026-09-21 用户原话）
 * 「ai 它是要具备**所有功能**」—— 而 `enabledTools()` 原来在读的时候会顺手把"见过的清单"
 * 刷成**当前全集**，于是新加的工具**只有第一次读是开的**，之后自己变回关的：
 * 静默、不报错、没有界面提示，等于 AI **悄悄丢能力**。这个文件钉的是修好之后的规则。
 *
 * ### 为什么钉的是纯函数
 * `AiKeyStore` 那一层只有 SharedPreferences（本项目没有 Robolectric，见 `libs.versions.toml`
 * 那条注释），读两次的**状态**没法在纯 JVM 单测里造。所以：
 * - **规则**（本节）钉在纯函数上，`enabledTools()` 只剩"读 prefs → 调它"；
 * - **"读路径不许写盘"** 这条（bug 的根因）钉在红线 `_check_ai_guardrails.py` 的源码形状上，
 *   反向验证 `_reverse_verify_local_reads.py` 里有一条注入专门证明它会红。
 *
 * `defaultEnabledTools` 的首装默认值（2026-10-09 起**所有角色一律全开**）由 `AiEndpointRulesTest`
 * 钉着，这里不重复。
 */
class AiEnabledToolsTest {

    /** 用户在设置页存过的那一份（这里模拟"他当时只见过这两个、都开着"）。 */
    private val saved = setOf(AiTools.READ_DATA, AiTools.REMEMBER)

    /** 保存的那一刻"见过"的工具 —— 同上。 */
    private val seenAtSave = setOf(AiTools.READ_DATA, AiTools.REMEMBER)

    @Test
    fun `新出现且用户没明确关过的工具，按默认打开`() {
        // EXPORT_SHEET 在默认集里，但**不在**"保存时见过的清单"里 = 保存之后新加的。
        val effective = AiKeyStore.resolveEnabledTools(saved, seenAtSave)
        assertTrue("新加的工具没按默认开（老用户升级后新功能会静默失效）：$effective", AiTools.EXPORT_SHEET in effective)
        // 同一个规矩对 CHG-0078 新加的 export_ledger 也成立（漏进默认集 = 静默筛掉）
        assertTrue("新加的工具没按默认开：$effective", AiTools.EXPORT_LEDGER in effective)
        // CHG-0096 的 run_workflow 同一条规矩（BUG-0022 就是漏了它）
        assertTrue("新加的工具没按默认开：$effective", AiTools.RUN_WORKFLOW in effective)
        assertTrue(AiTools.READ_DATA in effective)
    }

    /**
     * BUG-0022（2026-10-09 真机抓到）：`run_workflow` 漏进了 [AiKeyStore.DEFAULT_ENABLED_TOOLS]。
     *
     * 症状**不是**"新工具没自动开"那么轻 —— 设置页那条「跑工作流」开关**能点开**、
     * `enabled_tools` 里**确实存了它的名字**，但末尾那句 `intersect(DEFAULT_ENABLED_TOOLS)`
     * 把它筛掉：再进设置页开关**自己弹回关的**（"查询 7/8"永远差一条），
     * `AiTools.specs` 也从不把它放进模型看到的工具表 —— 模型只能如实回一句
     * 「对账工作流在我这边没有启用」。**开关看起来有、其实没有**。
     */
    @Test
    fun `用户自己点开的 run_workflow 不许被筛掉（存进 prefs 也不生效就是这个 bug）`() {
        // 真机上那一份 prefs（BUG-0022 的取证）：enabled_tools 里有 run_workflow，
        // tools_seen 里没有它（它是 CHG-0096 之后才有的）。修之前这两条断言都是红的。
        val savedWithWorkflow = saved + AiTools.RUN_WORKFLOW
        assertTrue(
            "存进 prefs 的开关被筛掉了（开关点开就弹回）：" + AiKeyStore.resolveEnabledTools(savedWithWorkflow, seenAtSave),
            AiTools.RUN_WORKFLOW in AiKeyStore.resolveEnabledTools(savedWithWorkflow, seenAtSave),
        )
        assertTrue(
            "老用户（存过白名单、没点过它）升级后该自动能跑工作流：" + AiKeyStore.resolveEnabledTools(saved, seenAtSave),
            AiTools.RUN_WORKFLOW in AiKeyStore.resolveEnabledTools(saved, seenAtSave),
        )
    }

    @Test
    fun `用户明确关掉的工具永远不自动开`() {
        // 他见过 SEARCH_SHIPPER 却没勾它 —— 那就是"我不要"。
        val seen = setOf(AiTools.READ_DATA, AiTools.REMEMBER, AiTools.SEARCH_SHIPPER)
        val effective = AiKeyStore.resolveEnabledTools(setOf(AiTools.READ_DATA), seen)
        assertFalse("用户关掉的又被打开了：$effective", AiTools.SEARCH_SHIPPER in effective)
        assertTrue(AiTools.READ_DATA in effective)
    }

    @Test
    fun `连着读两次，第二次新工具还在（读路径不改状态）`() {
        // ⚠️ 这正是修掉的那个 bug 的形状：读的时候若顺手把"见过的清单"刷成全集，
        //    第二次读就会算出"没有新工具"，于是它又变回关的。
        //    纯函数天然满足"同一个状态读两次一模一样"——**这条断言就是那个不变量**。
        val first = AiKeyStore.resolveEnabledTools(saved, seenAtSave)
        val second = AiKeyStore.resolveEnabledTools(saved, seenAtSave)
        assertTrue("第一次读就没有新工具：$first", AiTools.EXPORT_SHEET in first)
        assertTrue("第一次读就没有新工具：$first", AiTools.EXPORT_LEDGER in first)
        assertEquals("读两次结果不一样 = 读路径在改状态：$first vs $second", first, second)
        assertTrue("第二次读丢了新工具（就是那个静默丢能力的 bug）：$second", AiTools.EXPORT_SHEET in second)
        assertTrue("第二次读丢了新工具：$second", AiTools.EXPORT_LEDGER in second)
    }

    @Test
    fun `空串表示主动全关，必须还是空（不能悄悄变回全开）`() {
        // 老约定（类注释里写着）：有键但是空串 = 用户把开关全关了。
        // ⚠️ 这条在修之前是**假话**：`brandNew` 会把整份默认集重新填回来。
        assertTrue(
            "全关的设备被重新打开了：${AiKeyStore.resolveEnabledTools(emptySet(), seenAtSave)}",
            AiKeyStore.resolveEnabledTools(emptySet(), seenAtSave).isEmpty(),
        )
    }

    @Test
    fun `旧数据认不出他见过什么时，按他都见过算（不把他关掉的又打开）`() {
        // seenAtSave = null 对应"prefs 里有白名单、但没有「见过的清单」"（那机制之前存的）。
        // 两种猜法只能选一个：按"他都见过"（= 少给新工具，他下次保存就自愈）
        // 还是按"他什么都没见过"（= 把他明确关掉的工具全打开，其中有能改数据的 preview_write）。
        val effective = AiKeyStore.resolveEnabledTools(setOf(AiTools.READ_DATA), null)
        assertEquals("旧数据下不许凭空多给工具", setOf(AiTools.READ_DATA), effective)
    }

    @Test
    fun `新增的能改数据的工具也按默认开（2026-10-09 起不分角色）`() {
        // 这一条以前断的是"货主不该凭空多出一个会记账的 AI"——2026-10-09 用户改了口径：
        // 「非派单的写工具默认开起来……所有功能的 AI 所有功能默认是开的」。
        // 安全性没有交给开关：写工具永远只能**申请**，落库要用户在确认卡上点一下。
        val seen = setOf(AiTools.READ_DATA)
        val onlyRead = setOf(AiTools.READ_DATA)
        assertTrue(
            "新增的写工具该装上就能用（仍要过确认卡）",
            AiTools.PREVIEW_WRITE in AiKeyStore.resolveEnabledTools(onlyRead, seen),
        )
    }
}
