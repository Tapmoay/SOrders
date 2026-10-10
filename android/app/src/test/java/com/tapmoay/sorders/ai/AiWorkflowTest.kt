package com.tapmoay.sorders.ai

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 业务多步工作流的**登记表与提示词**（[AiWorkflows]，CHG-0096 ＋ FEAT-0020）。
 *
 * 与 [AiAnswerSkillsTest] 同一规矩：直接读提示词真正用的那一份（[AiWorkflows.RULES] /
 * [AiWorkflows.TOOL_DESCRIPTION]），⛔ 不在这里另抄一遍文案。
 *
 * 这里钉的是「登记表本身没写坏」；**跨文件**的那几条（每个 step 的 action 真的在读目录里、
 * 每条 nextAction 真的在**对应角色的写白名单**里、systemPrompt 真的拼了这一块、工具真的
 * 注册进了 AiTools 且 enum 按角色裁）由 `_tools/qa/_check_shipper_ai_workflows.py` 钉。
 *
 * FEAT-0020 起这里多钉三件（用户口径：「货主或者批发商他的 AI 没有对应的技能和工作流，
 * 也是要具备的哦」）：
 * 1. 谁有几条（派单员 2 / 货主 5 / 批发商货主 6 / **认不出角色 0**）；
 * 2. **只读的那两条不发卡**（查单到哪了、本月账本小结）—— 有 nextAction 就会去问"要不要发卡"，
 *    而那张卡**不存在**；
 * 3. 每条要发的写动作都必须在**那个角色**的白名单里（否则用户点了确认被 403 —— 本仓最坏一类 bug）。
 */
class AiWorkflowTest {

    private val rules: String = AiWorkflows.RULES
    private val description: String = AiWorkflows.TOOL_DESCRIPTION

    /** 普通货主（[AiActor.memberShipper] = false）：他自己那 5 条。 */
    private val shipper = AiActor.byRole(AiRole.SHIPPER)!!

    /** 批发商货主（`users.is_member=1`）：货主那 5 条 ＋ 改自己下游价那 1 条。 */
    private val member = AiActor.of(AiRole.SHIPPER, memberShipper = true)!!

    private val dispatcher = AiActor.byRole(AiRole.DISPATCHER)!!

    @Test
    fun `八条工作流都在登记表里_id 不重复`() {
        assertEquals(
            listOf(
                "ledger.reconcile", "price.batch",
                "order.place", "order.track", "ledger.monthly",
                "order.return_request", "order.contact", "price.mine",
            ),
            AiWorkflows.IDS,
        )
        assertEquals(
            "id 不许重复（重复的那条永远选不中）：" + AiWorkflows.IDS,
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
        assertEquals(
            listOf("products.list_products", "shipper.list_contacts", "shipper.list_addresses"),
            AiWorkflows.PLACE_ORDER.steps.map { it.action },
        )
        assertEquals(listOf("orders.list_orders"), AiWorkflows.TRACK_ORDER.steps.map { it.action })
        assertEquals(
            listOf("shipper_ledger.ledger_summary", "orders.list_orders"),
            AiWorkflows.MONTHLY_LEDGER.steps.map { it.action },
        )
        assertEquals(
            listOf("orders.list_orders", "return_requests.list_my_return_requests"),
            AiWorkflows.APPLY_RETURN.steps.map { it.action },
        )
        assertEquals(
            listOf("orders.list_orders", "shipper.list_contacts"),
            AiWorkflows.FIX_CONTACT.steps.map { it.action },
        )
        assertEquals(
            listOf("shipper_prices.list_shipper_prices", "shipper_prices.list_priceable_products"),
            AiWorkflows.MY_PRICES.steps.map { it.action },
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
            assertTrue("没写谁能用：" + w.id, w.roles.isNotEmpty())
            if (w.readOnly) {
                assertNull("只读工作流没有要问的那一句（它没有卡可发）：" + w.id, w.ask)
            } else {
                assertTrue("缺要问用户的那一句：" + w.id, (w.ask ?: "").contains("？"))
            }
        }
    }

    @Test
    fun `只读工作流不发卡：交棒动作与那一句都是 null`() {
        // ⛔ 只读的那两条（查单到哪了 / 本月账本小结）**没有下一步要改的东西**：
        //    给它们配一张卡，模型就会去问"要不要发确认卡"，而那张卡该写什么、点了会改什么，
        //    谁都答不上来；工具说明与第 13 条也照这个事实说（见下面那两条断言）。
        val onlyRead = AiWorkflows.ALL.filter { it.readOnly }
        assertEquals(
            "只读的就这两条（多一条少一条都要过这里）",
            listOf("order.track", "ledger.monthly"),
            onlyRead.map { it.id },
        )
        for (w in onlyRead) {
            assertNull("只读工作流不许有交棒动作：" + w.id, w.nextAction)
            assertNull("只读工作流不许有要问的那一句：" + w.id, w.ask)
            assertTrue("只读那条要在 whenToUse 里写明「只读」（模型才敢照实说）：" + w.id, w.whenToUse.contains("只读"))
        }
        for (w in AiWorkflows.ALL.filterNot { it.readOnly }) {
            assertTrue("发卡的那些必须写明它自己不写数据：" + w.id, w.nextAction != null && w.ask != null)
        }
        assertTrue("工具说明要写明只读的不发卡：$description", description.contains("它们没有卡可发"))
        assertTrue("第 13 条要写明只读的那几条没有 next：" + rules, rules.contains("read_only=true"))
    }

    @Test
    fun `交棒的动作必须是真实存在的写动作_而且在这个角色的写白名单里`() {
        for (w in AiWorkflows.ALL.filterNot { it.readOnly }) {
            val action = w.nextAction ?: error("发卡的工作流 nextAction 不该为空：" + w.id)
            assertTrue(
                "nextAction 不是 AiWrites 里登记过的写动作：「" + action + "」",
                AiWrites.byId(action) != null,
            )
            assertTrue(
                "写动作要有人话名字（结论里要显示）：" + action,
                AiWrites.titleOf(action) != action,
            )
            // ⛔ 这条是本单最要紧的一条：工作流要发的那个动作，必须在**它服务的那个角色**的
            //    写白名单里。不然用户按提示点了"确认"，等来的是一句 403 —— 本仓把
            //    「能看见但一定失败」列在最坏的一类 bug 里。
            // ⚠️ 第二维（memberOnly）不能漏：批发商货主那条只给 is_member=1 的货主，
            //    普通货主点了会被后端拒（他的清单里根本不该有它）。
            for (a in listOf(dispatcher, shipper, member).filter { it.role in w.roles && (!w.memberOnly || it.memberShipper) }) {
                assertTrue(
                    "「" + w.cn + "」要发的「" + action + "」不在【" + a.role + "】的写白名单里：" +
                        "点了确认必被后端拒（403）",
                    AiWrites.allows(a, action),
                )
            }
        }
        assertEquals("对账交棒给「补进账本」", AiWrites.LEDGER_SYNC_DELIVERED, AiWorkflows.RECONCILE.nextAction)
        assertEquals("调价交棒给「批量调价」", AiWrites.PRICE_RULES_BATCH, AiWorkflows.PRICE_ADJUST.nextAction)
        assertEquals("一句话下单交棒给「创建订单」", AiWrites.ORDERS_CREATE, AiWorkflows.PLACE_ORDER.nextAction)
        assertEquals("申请退货交棒给「申请退货」", AiWrites.RETURN_REQUEST_APPLY, AiWorkflows.APPLY_RETURN.nextAction)
        assertEquals("改联系信息交棒给「补联系信息」", AiWrites.ORDERS_UPDATE_CONTACT, AiWorkflows.FIX_CONTACT.nextAction)
        assertEquals("改下游价交棒给「给下游定个价」", AiWrites.SHIPPER_PRICE_SET, AiWorkflows.MY_PRICES.nextAction)
        // 批发商那条**只**动他自己的下游价（shipper_price.*）：⛔ 不是派单员那条批发商专属价。
        assertTrue("改下游价不许交棒给 price_rules.*（那是派单员的价）", AiWorkflows.MY_PRICES.nextAction!!.startsWith("shipper_price."))
        assertFalse(
            "批发商专属那条不许给普通货主（后端只认批发商货主）：点了必被拒",
            AiWrites.allows(shipper, AiWrites.SHIPPER_PRICE_SET),
        )
        assertTrue("批发商货主要能改自己那一本下游价", AiWrites.allows(member, AiWrites.SHIPPER_PRICE_SET))
    }

    @Test
    fun `每一步的 action 都在这个角色的读白名单里`() {
        // 读门与写门是**两个门**，各自都要过：步骤的 action 不在他能读的清单里，
        // 工作流就会跑到一半被权限门挡掉（而那时候结论只写了一半）。
        for ((actor, tag) in listOf(dispatcher to "派单员", shipper to "货主", member to "批发商货主")) {
            val readable = AiReads.forRole(actor, AiReads.allModules().toSet()).map { it.action }.toSet()
            for (w in AiWorkflows.forActor(actor)) {
                for (step in w.steps) {
                    assertTrue(
                        tag + "跑「" + w.cn + "」要读「" + step.action + "」，那不在他能读的清单里",
                        step.action in readable,
                    )
                }
            }
        }
    }

    @Test
    fun `认不出角色就一条都不给（fail-closed）`() {
        assertNull("认不出的 id 不许猜一条相近的", AiWorkflows.byId("order.place2"))
        assertTrue("角色为 null 时一条都不给", AiWorkflows.forActor(null).isEmpty())
        assertFalse("认不出角色时连一条都不 allows", AiWorkflows.allows(null, "order.place"))
        assertTrue(
            "货主不该看到派单员那两条（它们要发的写动作本来就不在货主白名单里）",
            AiWorkflows.forActor(shipper).none { it.id == "ledger.reconcile" || it.id == "price.batch" },
        )
        assertEquals(
            "派单员拿的就是他自己那两条（货主那几条不在他的清单里 —— 他的读/写能力比货主大，" +
                "但那几条工作流是照货主的口径写的）",
            listOf("ledger.reconcile", "price.batch"),
            AiWorkflows.forActor(dispatcher).map { it.id },
        )
    }

    @Test
    fun `货主 5 条、批发商货主 6 条、派单员 2 条（逐字钉住）`() {
        assertEquals(
            "货主 5 条：下单 / 查单 / 账本小结 / 退货申请 / 改联系信息",
            listOf("order.place", "order.track", "ledger.monthly", "order.return_request", "order.contact"),
            AiWorkflows.forActor(shipper).map { it.id },
        )
        assertEquals(
            "批发商货主 6 条 = 货主那 5 条 ＋ 改自己那一本下游价",
            listOf(
                "order.place", "order.track", "ledger.monthly",
                "order.return_request", "order.contact", "price.mine",
            ),
            AiWorkflows.forActor(member).map { it.id },
        )
        assertEquals(
            "派单员那两条一字不变（本单不许动它们的语义）",
            listOf("ledger.reconcile", "price.batch"),
            AiWorkflows.forActor(dispatcher).map { it.id },
        )
        assertTrue("派单员不许拿到批发商专属那条（那本账后端只认货主角色）",
            AiWorkflows.forActor(dispatcher).none { it.id == "price.mine" })
        assertTrue("普通货主不许拿到批发商专属那条（他手机上根本没有那一段）",
            AiWorkflows.forActor(shipper).none { it.id == "price.mine" })
        assertTrue(AiWorkflows.allows(member, "price.mine"))
    }

    @Test
    fun `工具说明里每条都要有_id_中文名_什么时候用`() {
        for (w in AiWorkflows.ALL) {
            assertTrue("工具说明缺 id：" + w.id, description.contains(w.id))
            assertTrue("工具说明缺中文名：" + w.cn, description.contains(w.cn))
            assertTrue("工具说明缺「什么时候用」：" + w.cn, description.contains(w.whenToUse))
            assertTrue(
                "工具说明缺步骤（用户问「你查了什么」时要照它说）：" + w.cn,
                description.contains(w.steps.joinToString("；") { it.title }),
            )
            assertTrue("工具说明缺谁能跑的暗示：" + w.cn, w.roles.isNotEmpty())
        }
        assertTrue("要写明它自己不写数据：$description", description.contains("它自己一步都不写"))
        assertTrue("要写明默认时间范围：$description", description.contains("本月 1 号到今天"))
        assertTrue("要写明先问用户再发卡：$description", description.contains("preview_write"))
        assertTrue("只读的那几条要单独标出来：$description", description.contains("**只读**"))
    }

    @Test
    fun `第 13 条：目录与纪律都写到_而且不写步骤`() {
        assertTrue("要接在 12 之后、编号 13：$rules", rules.startsWith("13. "))
        assertTrue("要写明用 run_workflow 跑：$rules", rules.contains("run_workflow"))
        assertTrue("要写明默认时间范围：$rules", rules.contains("本月 1 号到今天"))
        assertTrue("要写明没查全时不许当完整的账：$rules", rules.contains("incomplete"))
        assertTrue("要写明用户没点头不许发卡：$rules", rules.contains("preview_write"))
        assertTrue("要写明退回自己一步一步查：$rules", rules.contains("read_data"))
        assertTrue("要多于一张卡时一张一张来：$rules", rules.contains("nexts"))
        assertTrue("只读那几条要单独交代（别去问要不要发卡）：$rules", rules.contains("read_only=true"))
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
