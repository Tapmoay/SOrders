package com.tapmoay.sorders.ui.shipper

import com.tapmoay.sorders.data.remote.api.ShipperSettlementDto
import com.tapmoay.sorders.data.remote.api.ShipperSettlementLineDto
import com.tapmoay.sorders.data.remote.dto.OrderDto
import com.tapmoay.sorders.data.remote.dto.OrderProductDto
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 货主账本（以订单为基础）的分组与合计：**纯函数单测**（JVM，不需要模拟器）。
 *
 * 这一份钉的是"钱算得对不对"和"两本账有没有串"：
 * · 归属 = **收货人**（真实数据里下单人恒为批发商自己，见 `ShipperLedgerGrouping` 的注释）；
 * · 「客户欠我」= 货款 − 我已核销；「我欠总分销商」= 后端给的 `arrears_amount`（客户端不重算）；
 * · 撤销掉的核销**不算已收**（软删的语义：这一笔不存在）。
 */
class ShipperLedgerGroupingTest {

    private fun line(
        id: Long,
        name: String,
        qty: Int,
        price: String,
        returned: Int = 0,
    ) = OrderProductDto(
        id = id,
        productNameSnapshot = name,
        quantity = qty,
        unitPrice = price,
        lineTotal = (price.toBigDecimal() * qty.toBigDecimal()).toPlainString(),
        returnedQuantity = returned,
    )

    private fun order(
        id: Long,
        dongjia: String,
        phone: String = "",
        boss: String = "永盛食品",
        lines: List<OrderProductDto>,
        arrears: String = "0",
    ) = OrderDto(
        id = id,
        orderNo = "SO$id",
        status = "DELIVERED",
        contactDongjiaName = dongjia,
        contactDongjiaPhone = phone,
        contactBossName = boss,
        arrearsAmount = arrears,
        orderProducts = lines,
    )

    private fun settle(
        id: Long,
        orderId: Long,
        amount: String,
        lines: List<Pair<Long, String>>,
        deleted: Boolean = false,
    ) = ShipperSettlementDto(
        id = id,
        orderId = orderId,
        amount = amount,
        isDeleted = deleted,
        lines = lines.map { (opid, amt) ->
            ShipperSettlementLineDto(id = opid, orderProductId = opid, amount = amt)
        },
    )

    @Test
    fun `归属取收货人 空则退到下单人 再空进未指定`() {
        val a = order(1, dongjia = "罗伟东", lines = listOf(line(11, "白菜", 1, "10")))
        val b = order(2, dongjia = "", boss = "李老板", lines = listOf(line(21, "萝卜", 1, "10")))
        val c = order(3, dongjia = "", boss = "", lines = listOf(line(31, "土豆", 1, "10")))
        assertEquals("罗伟东", customerNameOf(a))
        assertEquals("李老板", customerNameOf(b))
        assertEquals(UNSET_CUSTOMER, customerNameOf(c))
    }

    @Test
    fun `同名不同电话是两个货主 不许并成一个`() {
        val a = order(1, "张老板", "13500000001", lines = listOf(line(11, "白菜", 1, "10")))
        val b = order(2, "张老板", "13500000002", lines = listOf(line(21, "萝卜", 1, "10")))
        val groups = groupByCustomer(listOf(a, b), emptyList())
        assertEquals(2, groups.size)
        assertEquals(setOf("13500000001", "13500000002"), groups.map { it.phone }.toSet())
    }

    @Test
    fun `货主总计 等于他名下订单的货款减去已核销`() {
        // 罗伟东：两单 100 + 60 = 160，其中一单核销了 40
        val o1 = order(1, "罗伟东", lines = listOf(line(11, "白菜", 10, "10")))   // 100
        val o2 = order(2, "罗伟东", lines = listOf(line(21, "萝卜", 3, "20")))    // 60
        val s = settle(101, 1, "40", listOf(11L to "40"))

        val g = groupByCustomer(listOf(o1, o2), listOf(s)).single()
        assertEquals(16000L, g.goodsCents)
        assertEquals(4000L, g.settledCents)
        assertEquals(12000L, g.owedCents)
        assertEquals(2, g.orders.size)
        // 两单都还没结清：o1 核销 40 后还欠 60，o2 一分没核销
        assertEquals(2, g.unsettledOrders)   // o1 还欠 60，o2 一分没核销 → 两单都没结清
    }

    @Test
    fun `撤销掉的核销不算已收`() {
        val o = order(1, "罗伟东", lines = listOf(line(11, "白菜", 10, "10")))
        val s = settle(101, 1, "100", listOf(11L to "100"), deleted = true)
        val g = groupByCustomer(listOf(o), listOf(s)).single()
        assertEquals(0L, g.settledCents)
        assertEquals(10000L, g.owedCents)
    }

    @Test
    fun `按商品核销只冲掉那一行`() {
        val o = order(
            1, "罗伟东",
            lines = listOf(line(11, "白菜", 2, "10"), line(12, "萝卜", 3, "20")),  // 20 + 60
        )
        val s = settle(101, 1, "60", listOf(12L to "60"))
        val settled = settledByLineCents(listOf(s))
        assertEquals(2000L, lineRemainingCents(o.orderProducts[0], settled))
        assertEquals(0L, lineRemainingCents(o.orderProducts[1], settled))
        assertEquals(2000L, orderRemainingCents(o, settled))
    }

    @Test
    fun `退过货的行 应收按退货后的算`() {
        // 10 件 × 10 元，退了 4 件 → 应收 60
        val o = order(1, "罗伟东", lines = listOf(line(11, "白菜", 10, "10", returned = 4)))
        assertEquals(6000L, orderGoodsCents(o))
        assertEquals(6000L, orderRemainingCents(o, emptyMap()))
    }

    @Test
    fun `合计里 我欠总分销商取后端给的数 客户端不重算`() {
        val o1 = order(1, "罗伟东", lines = listOf(line(11, "白菜", 10, "10")), arrears = "100")
        val o2 = order(2, "李老板", lines = listOf(line(21, "萝卜", 3, "20")), arrears = "60")
        val t = ledgerTotals(listOf(o1, o2), emptyList())
        assertEquals(16000L, t.dispatcherArrearsCents)
        assertEquals(2, t.orders)
        assertEquals(0, t.clearedOrders)
    }

    @Test
    fun `分组按欠款倒序 欠得多的在前`() {
        val rich = order(1, "小客户", lines = listOf(line(11, "白菜", 1, "10")))
        val big = order(2, "大客户", lines = listOf(line(21, "萝卜", 100, "20")))
        val groups = groupByCustomer(listOf(rich, big), emptyList())
        assertEquals(listOf("大客户", "小客户"), groups.map { it.name })
    }

    @Test
    fun `联系人搜索 按名字或电话 大小写不敏感`() {
        val a = order(1, "Luo伟东", "13500000001", lines = listOf(line(11, "白菜", 1, "10")))
        val b = order(2, "李老板", "13800000002", lines = listOf(line(21, "萝卜", 1, "10")))
        val groups = groupByCustomer(listOf(a, b), emptyList())
        assertEquals(listOf("李老板"), filterByCustomer(groups, "李").map { it.name })
        // 后 4 位天然命中（子串匹配，没有"取后四位"这种额外分支）
        assertEquals(listOf("李老板"), filterByCustomer(groups, "0002").map { it.name })
        assertEquals(listOf("Luo伟东"), filterByCustomer(groups, "luo").map { it.name })
        assertEquals(2, filterByCustomer(groups, "  ").size)   // 空白 = 不过滤
    }

    @Test
    fun `某人已结清的单不再算欠 但仍在明细里`() {
        val o = order(1, "罗伟东", lines = listOf(line(11, "白菜", 10, "10")))
        val s = settle(101, 1, "100", listOf(11L to "100"))
        val g = groupByCustomer(listOf(o), listOf(s)).single()
        assertEquals(0L, g.owedCents)
        assertEquals(0, g.unsettledOrders)
        assertEquals(1, g.orders.size)
        assertTrue(ledgerTotals(listOf(o), listOf(s)).clearedOrders == 1)
    }
}
