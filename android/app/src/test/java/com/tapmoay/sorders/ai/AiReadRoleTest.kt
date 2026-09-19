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

    private fun actionsOf(role: AiRole) = AiReads.forRole(role).map { it.action }.toSet()

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
    fun `派单员拿到全部表`() {
        assertEquals(AiReadCatalog.ACTIONS.size, AiReads.forRole(AiRole.DISPATCHER).size)
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
        val got = actionsOf(AiRole.SHIPPER)
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
        val got = actionsOf(AiRole.SHIPPER)
        val missing = must.filter { it !in got }
        assertTrue("货主能做的事却没给他读：$missing", missing.isEmpty())
    }

    @Test
    fun `关掉的模块对两个角色都生效`() {
        val only = setOf("orders")
        for (role in listOf(AiRole.DISPATCHER, AiRole.SHIPPER)) {
            val ok = AiReads.forRole(role, only).all { it.action.startsWith("orders.") }
            assertTrue("$role 在只开 orders 模块时仍拿到了别的表", ok)
        }
    }

    @Test
    fun `工具说明里的清单与可执行集合同源`() {
        // 说明里列了却调不了（或反过来）是最难查的一类问题：模型会照抄说明里的 action，
        // 然后拿到一句"没有名为 X 的查询"。两边必须来自同一个 forRole。
        for (role in listOf(AiRole.DISPATCHER, AiRole.SHIPPER)) {
            val described = AiReads.describeForModel(role).lines().filter { it.startsWith("- ") }
            assertEquals("$role 的说明行数与可读表数不一致", AiReads.forRole(role).size, described.size)
        }
    }
}
