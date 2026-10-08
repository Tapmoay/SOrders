package com.tapmoay.sorders.ai

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 业务多步工作流的**登记表与提示词**（[AiWorkflows]，CHG-0096）。
 *
 * 与 [AiAnswerSkillsTest] 同一规矩：直接读提示词真正用的那一份（`AiWorkflows.RULES` /
 * `AiWorkflows.TOOL_DESCRIPTION`），⛔ 不在这里另抄一遍文案。
 *
 * 这里钉的是「登记表本身没写坏」；**跨文件**的那几条（每个 step 的 action 真的在读目录里、
 * systemPrompt 真的拼了这一块、工具真的注册进了 AiTools）由 `_tools/qa/_check_ai_workflow.py` 钉。
 */
class AiWorkflowTest {

    private val rules: String = AiWorkflows.RULES
    private val description: String = AiWorkflows.TOOL_DESCRIPTION

    @Test
    fun `两条工作流都在登记表里_id 不重复`() {
        assertEquals(listOf("ledger.reconcile", "price.batch"), AiWorkflows.IDS)
        assertEquals(
            "id 不许重复（重复的那条永远选不中）：$AiWorkflows.IDS",
            AiWorkflows.ALL.size,
            AiWorkflows.ALL.map { it.id }.toSet().size,
        )
    }

    @Test
    fun `步骤用的 action 就是这几个（改动必须过这里）`() {
        assertEquals(
            listOf("orders.list_orders", "ledger.list_entries"),
            AiWorkflows.RECONCILE.steps.map { it.action },
        )
        assertEquals(
            listOf("products.list_products", "price_rules.list_price_rules"),
            AiWorkflows.PRICE_ADJUST.steps.map { it.action },
        )
    }

    @Test
    fun `每条都要写全：什么时候用_参数_步骤_交棒的动作_要问的那一句`() {
        for (w in AiWorkflows.ALL) {
            assertTrue("缺 cn：" + w.id, w.cn.isNotBlank())
            assertTrue("缺「什么时候用」（模型就认不出来）：" + w.id, w.whenToUse.contains("用户说"))
            assertTrue("缺参数说明：" + w.id, w.paramsCn.isNotBlank())
            assertTrue("缺步骤：" + w.id, w.steps.isNotEmpty())
            assertTrue("步骤标题不许空着（痕迹里那一行就是它）：" + w.id, w.steps.all { it.title.isNotBlank() })
            assertTrue("缺要问用户的那一句：" + w.id, w.ask.contains("？"))
            assertTrue("没写谁能用：" + w.id, w.roles.isNotEmpty())
        }
    }

    @Test
    fun `交棒的动作必须是真实存在的写动作_它自己一步都不写`() {
        for (w in AiWorkflows.ALL) {
            assertTrue(
                "nextAction 不是 AiWrites 里登记过的写动作：「" + w.nextAction + "」",
                AiWrites.byId(w.nextAction) != null,
            )
            assertTrue(
                "写动作要有人话名字（结论里要显示）：" + w.nextAction,
                AiWrites.titleOf(w.nextAction) != w.nextAction,
            )
        }
        assertEquals("对账交棒给「补进账本」", AiWrites.LEDGER_SYNC_DELIVERED, AiWorkflows.RECONCILE.nextAction)
        assertEquals("调价交棒给「批量调价」", AiWrites.PRICE_RULES_BATCH, AiWorkflows.PRICE_ADJUST.nextAction)
    }

    @Test
    fun `认不出角色就一条都不给（fail-closed）`() {
        assertNull("没有角色 = 认不出，必须一条都不给", AiWorkflows.byId("ledger.reconcile2"))
        assertEquals(AiWorkflows.ALL.size, AiWorkflows.forRole(AiRole.DISPATCHER).size)
        assertTrue(
            "货主不该看到这两条（它们要发的写动作本来就不在货主白名单里）",
            AiWorkflows.forRole(AiRole.SHIPPER).isEmpty(),
        )
        assertTrue("角色为 null 时一条都不给", AiWorkflows.forRole(null).isEmpty())
    }

    @Test
    fun `工具说明里两条都要有_id_中文名_什么时候用`() {
        for (w in AiWorkflows.ALL) {
            assertTrue("工具说明缺 id：" + w.id, description.contains(w.id))
            assertTrue("工具说明缺中文名：" + w.cn, description.contains(w.cn))
            assertTrue("工具说明缺「什么时候用」：" + w.cn, description.contains(w.whenToUse))
        }
        assertTrue("要写明它自己不写数据：$description", description.contains("它自己一步都不写"))
        assertTrue("要写明默认时间范围：$description", description.contains("本月 1 号到今天"))
        assertTrue("要写明先问用户再发卡：$description", description.contains("preview_write"))
    }

    @Test
    fun `第 13 条：目录与纪律都写到_而且不写步骤`() {
        assertTrue("要接在 12 之后、编号 13：$rules", rules.startsWith("13. "))
        assertTrue("要写明用 run_workflow 跑：$rules", rules.contains("run_workflow"))
        assertTrue("要写明默认时间范围：$rules", rules.contains("本月 1 号到今天"))
        assertTrue("要写明没查全时不许当完整的账：$rules", rules.contains("incomplete"))
        assertTrue("要写明用户没点头不许发卡：$rules", rules.contains("preview_write"))
        assertTrue("要写明退回自己一步一步查：$rules", rules.contains("read_data"))
        for (w in AiWorkflows.ALL) {
            assertTrue("目录里缺 " + w.id, rules.contains(w.id))
        }
        // ⛔ 步骤只在代码里跑：提示词里出现 step 的 action 就等于把步骤又抄了一份（会漂移）。
        for (step in AiWorkflows.ALL.flatMap { it.steps }) {
            assertTrue(
                "提示词里不许出现步骤的 action（步骤写死在 [AiWorkflowRunner] 里）：" + step.action,
                !rules.contains(step.action),
            )
        }
    }
}
