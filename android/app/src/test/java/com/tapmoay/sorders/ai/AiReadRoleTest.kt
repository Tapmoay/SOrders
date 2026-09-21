package com.tapmoay.sorders.ai

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 读能力的角色裁剪（v3.15）。
 *
 * 背景：`read_data` 的 36 张表原来是**派单员视角**的整份目录，货主拿到的是同一份。
 * 实测（`_tools/ai/_probe_read_roles.py`：对三个角色逐条打真后端）货主调
 * `users / operation-logs / reports / stats / inventory / order-products` 全是 403——
 * 他问一句，模型去查一张查不了的表，只能回"查不到"。
 *
 * 所以角色从后端授权推导（见 `_tools/ai/_gen_ai_read_catalog.py`），这里守的是：
 * **每张表都有角色、货主拿到的是他真能读的那些、认不出角色就一张都不给**。
 */
class AiReadRoleTest {

    private fun actionsOf(actor: AiActor) = AiReads.forRole(actor).map { it.action }.toSet()

    /** 两个货主：普通货主（`is_member=0`）与批发商货主（`is_member=1`）。 */
    private val plainShipper = AiActor.byRole(AiRole.SHIPPER)!!
    private val memberShipper = AiActor.of(AiRole.SHIPPER, true)!!

    @Test
    fun `每张表都标了角色，没有谁都不给的孤儿`() {
        val orphans = AiReadCatalog.ACTIONS.filter { it.roles.isEmpty() }.map { it.action }
        assertTrue("这些表没标角色（生成器出问题或被人手改了）：$orphans", orphans.isEmpty())
    }

    @Test
    fun `认不出角色就一张表都不给（fail-closed）`() {
        assertTrue(AiReads.forRole(null).isEmpty())
        assertFalse(AiReads.allows(null, "orders.list_orders"))
    }

    @Test
    fun `派单员拿到全部表（除了只给货主的那几张）`() {
        // ⚠️ 原来这里断言的是"派单员拿到**全部**"，那是 2026-09-20 之前成立的前提：
        //    那时目录里没有一张表是"只给货主"的。加了 `shipper_ledger.list_settlements`
        //    （批发商自己那一本核销账，**派单员读它是 403**）之后，那条断言变成了假话。
        //    现在按目录自己算"应该拿到几张"——多一张少一张都会红。
        //
        // ⚠️ 2026-09-21：分母再换一次 —— 从「后端目录」换成 **`AiReads.allActions()`**
        //    （目录 + 本机能力）：`location.current` 这类本机能力也给派单员，
        //    还按目录算的话会因为差 1 条而红（而那是**对的**，不是 bug）。
        val all = AiReads.allActions()
        val shipperOnly = all.filter { it.roles == setOf("shipper") }
        assertEquals(
            all.size - shipperOnly.size,
            AiReads.forRole(AiActor.byRole(AiRole.DISPATCHER)).size,
        )
        // 双向：**批发商货主**能拿到自己那一张（裁多了和裁少了都是能力缺失）。
        // ⚠️ 2026-09-20 第七轮：这张表从"只给 shipper"再收窄成"只给**批发商**货主" ——
        //    普通货主手机上「我的账本」根本没有核销那一段（他给自己下单，没有第二个债务人），
        //    所以他的清单里不该出现这张表。判据在目录的 `memberOnly` 上（生成器写的）。
        assertTrue(
            "批发商货主拿不到自己的核销账目录（生成器或角色推导坏了）",
            AiReads.allows(memberShipper, "shipper_ledger.list_settlements"),
        )
        assertFalse(
            "普通货主不该拿到核销账（手机上他没有这一段）",
            AiReads.allows(plainShipper, "shipper_ledger.list_settlements"),
        )
        assertFalse(
            "派单员不该拿到货主私账那张表（后端对它 403）",
            AiReads.allows(AiActor.byRole(AiRole.DISPATCHER), "shipper_ledger.list_settlements"),
        )
    }

    @Test
    fun `货主拿不到派单专属的表`() {
        // 每一条都对应实测的 403（写死在测试里是刻意的：真到了要给货主开某张表那天，
        // 这条会红，逼着你回去改后端守卫、再重新生成目录，而不是悄悄把能力放出去）
        val forbidden = listOf(
            "users.list_users",
            "operation_logs.list_operation_logs",
            "reports.turnover_report",
            "reports.product_report",
            "reports.arrears_summary",
            "stats.get_driver_performance",
            "stats.get_shipper_activity",
            "stats.get_exception_orders",
            "stats.get_product_drilldown",
            "stats.get_shipper_product_chart",
            "inventory.inventory_summary",
            "inventory.list_movements",
            "order_products.list_order_products",
            "cash_flows.list_cash_flows",
            "expenses.list_expenses",
            "ledger.list_accounts",
            "ledger.list_receipts",
            "ledger.list_temp_shipper_names",
            "arrears.list_units",
            "driver_bills.list_driver_bills",
            "driver_settlements.list_settlements",
            "freight_templates.list_templates",
            "vehicles.list_vehicles",
            "customers.list_customers",
            "orders.pending_dispatch_count",
        )
        val got = actionsOf(plainShipper)
        val leaked = forbidden.filter { it in got }
        assertTrue("货主不该拿到这些表：$leaked", leaked.isEmpty())
    }

    @Test
    fun `货主工作台里能干的事，读目录里都得有`() {
        // 这条是反向的守卫：裁得太狠和裁得太松一样糟——用户明明能查却被告知"没权限"，
        // 他永远不知道有这功能。每条都对应一个货主能点到的页面。
        val must = listOf(
            "orders.list_orders",          // 我的订单
            "products.list_products",      // 下单时选商品
            "shipper.list_addresses",      // 地址与联系人
            "shipper.list_contacts",
            "shipper.list_locations",
            "ledger.list_entries",         // 我的账本
            "notifications.list_notifications", // 消息中心
            "notifications.unread_count",
            "price_rules.list_price_rules",     // 批发商专属价
        )
        val got = actionsOf(plainShipper)
        val missing = must.filter { it !in got }
        assertTrue("货主能做的事却没给他读：$missing", missing.isEmpty())
    }

    @Test
    fun `关掉的模块对两个角色都生效`() {
        val only = setOf("orders")
        for (actor in listOf(AiActor.byRole(AiRole.DISPATCHER)!!, plainShipper)) {
            val ok = AiReads.forRole(actor, only).all { it.action.startsWith("orders.") }
            assertTrue("$actor 在只开 orders 模块时仍拿到了别的表", ok)
        }
    }

    @Test
    fun `工具说明里的清单与可执行集合同源`() {
        // 说明里列了却调不了（或反过来）是最难查的一类问题：模型会照抄说明里的 action，
        // 然后拿到一句"没有名为 X 的查询"。两边必须来自同一个 forRole。
        for (actor in listOf(AiActor.byRole(AiRole.DISPATCHER)!!, plainShipper, memberShipper)) {
            val described = AiReads.describeForModel(actor).lines().filter { it.startsWith("- ") }
            assertEquals("$actor 的说明行数与可读表数不一致", AiReads.forRole(actor).size, described.size)
        }
    }
}
