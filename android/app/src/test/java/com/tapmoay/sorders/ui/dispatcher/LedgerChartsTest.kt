package com.tapmoay.sorders.ui.dispatcher

import com.tapmoay.sorders.core.ledgerSourceLabel
import com.tapmoay.sorders.data.remote.dto.FreightSettlementGroupDto
import com.tapmoay.sorders.data.remote.dto.FreightSettlementOrderDto
import com.tapmoay.sorders.data.remote.dto.LedgerEntryDto
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 账本页三张图的取数规则（纯函数）。
 *
 * 最要紧的一组断言是**"图上的数与屏幕上那个合计同源"**：
 * 图自己另算一遍（比如漏掉退款行、把没日期的算进今天），就会出现
 * 「上面写 ¥3,200、扇形加起来 ¥2,800」——两个数都不报错，用户只能怀疑人生。
 * 所以这里既验分组，也验**求和等于合计**。
 */
class LedgerChartsTest {

    private fun entry(date: String, total: String, source: String = "order") =
        LedgerEntryDto(id = 1, entryDate = date, productName = "货", total = total, source = source)

    private fun order(day: String, pay: String) =
        FreightSettlementOrderDto(orderId = 1, orderNo = "SO1", deliveredAt = day, payTotal = pay)

    private fun group(id: Long, name: String, total: Double, orders: List<FreightSettlementOrderDto> = emptyList()) =
        FreightSettlementGroupDto(driverId = id, driverName = name, count = orders.size, total = total, orders = orders)

    private fun row(name: String, total: Double) =
        LedgerAccountRow(key = "u|$name", title = name, phone = null, inactive = false, count = 1, countUnit = "笔", total = total)

    // ---------------------------------------------------------------- 按天序列

    @Test
    fun `给了区间就把没有流水的那天补成 0`() {
        val rows = listOf("2026-09-01" to 100.0, "2026-09-03" to 50.0)
        val series = dailySeries(rows, "2026-09-01", "2026-09-03")
        assertEquals(listOf("2026-09-01", "2026-09-02", "2026-09-03"), series.map { it.first })
        assertEquals(listOf(100.0, 0.0, 50.0), series.map { it.second })
    }

    @Test
    fun `同一天的多笔会先合并再画`() {
        val series = dailySeries(listOf("2026-09-01" to 10.0, "2026-09-01" to 5.0), "2026-09-01", "2026-09-01")
        assertEquals(listOf(15.0), series.map { it.second })
    }

    @Test
    fun `没有区间时只列有流水的那几天（不凭空补一条零线）`() {
        val series = dailySeries(listOf("2026-09-05" to 1.0, "2026-09-01" to 2.0))
        assertEquals(listOf("2026-09-01", "2026-09-05"), series.map { it.first })
    }

    @Test
    fun `日期读不出来的行不计入（不当成今天）`() {
        val series = dailySeries(listOf("" to 99.0, "2026-09-01" to 1.0), "2026-09-01", "2026-09-01")
        assertEquals(listOf(1.0), series.map { it.second })
    }

    @Test
    fun `区间本身读不出来时退回有流水的那几天`() {
        val series = dailySeries(listOf("2026-09-01" to 1.0), "不是日期", "2026-09-30")
        assertEquals(listOf("2026-09-01"), series.map { it.first })
    }

    // ---------------------------------------------------------------- 切片合并

    @Test
    fun `切片不超过上限时原样返回（按金额倒序）`() {
        val s = topSlices(listOf("A" to 1.0, "B" to 3.0), max = 6)
        assertEquals(listOf("B", "A"), s.map { it.first })
    }

    @Test
    fun `切片超上限时其余合并成其他并排在最后，且总额不丢`() {
        val items = (1..10).map { "户$it" to it.toDouble() }
        val s = topSlices(items, max = 4)
        assertEquals(4, s.size)
        assertEquals(OTHER_SLICE, s.last().first)
        assertEquals("合并之后总额必须还是原来的总额", 55.0, s.sumOf { it.second }, 1e-9)
    }

    @Test
    fun `金额为 0 或负的切片不进扇形（画出来是个看不见的零度块）`() {
        val s = topSlices(listOf("零" to 0.0, "负" to -5.0, "正" to 8.0))
        assertEquals(listOf("正"), s.map { it.first })
    }

    // ---------------------------------------------------------------- 订单账

    @Test
    fun `订单账的来源标签与 AI 卡片同一份实现`() {
        assertEquals("订单入账", ledgerSourceLabel("order"))
        assertEquals("手工记账", ledgerSourceLabel("manual"))
        assertEquals("货损红冲", ledgerSourceLabel("refund"))
        // 认不出的来源**原样显示**，不并进"其他"（那会把两类账混成一个科目）
        assertEquals("warehouse", ledgerSourceLabel("warehouse"))
        assertEquals("未知来源", ledgerSourceLabel(""))
    }

    @Test
    fun `订单账的按天序列与来源构成加起来都等于那批流水的合计`() {
        val entries = listOf(
            entry("2026-09-01", "100.00", "order"),
            entry("2026-09-01", "20.50", "manual"),
            entry("2026-09-03", "7.50", "order"),
            // 货损红冲行金额是 0（只冲成本）：它会进列表，但不该把两个数拉偏
            entry("2026-09-03", "0", "refund"),
        )
        val total = 128.0
        assertEquals(total, orderDailySeries(entries, "2026-09-01", "2026-09-03").sumOf { it.second }, 1e-9)
        assertEquals(total, orderSourceTotals(entries).sumOf { it.second }, 1e-9)
        // 金额为 0 的那一类不进扇形（否则图例上挂一个 ¥0.00）
        assertEquals(listOf("订单入账", "手工记账"), topSlices(orderSourceTotals(entries)).map { it.first })
    }

    // ---------------------------------------------------------------- 司机账

    @Test
    fun `司机账按天用的是司机应得 pay_total（与组头合计同源）`() {
        val groups = listOf(
            group(1, "王建国", 300.0, listOf(order("2026-09-01T10:00:00", "100.00"), order("2026-09-02T09:00:00", "200.00"))),
            group(2, "李四", 50.0, listOf(order("2026-09-02T18:00:00", "50.00"))),
        )
        val series = driverDailySeries(groups, "2026-09-01", "2026-09-02")
        assertEquals(listOf(100.0, 250.0), series.map { it.second })
        // 三处必须一模一样：按天序列 / 按司机切片 / 组头合计
        val byDriver = driverTotals(groups)
        assertEquals(350.0, byDriver.sumOf { it.second }, 1e-9)
        assertEquals(byDriver.sumOf { it.second }, series.sumOf { it.second }, 1e-9)
    }

    @Test
    fun `没名字的司机用编号兜底（不能显示成空行）`() {
        assertEquals("司机 7", driverTotals(listOf(group(7, "", 10.0))).first().first)
    }

    // ---------------------------------------------------------------- 货主账 / 批发商账

    @Test
    fun `账户构成直接用仪表盘那一批行`() {
        val rows = listOf(row("张老板", 120.0), row("李老板", 80.0))
        assertEquals(200.0, accountTotals(rows).sumOf { it.second }, 1e-9)
        assertEquals(listOf("张老板", "李老板"), topSlices(accountTotals(rows)).map { it.first })
    }

    // ---------------------------------------------------------------- 标签与类型码

    @Test
    fun `图上日期标签折线与条形共用一份`() {
        assertEquals("09/20", dayLabel("2026-09-20"))
        assertEquals("09/20", dayLabel("2026-09-20T10:00:00"))
        assertEquals("坏日期", dayLabel("坏日期"))
    }

    @Test
    fun `账户名太长要截短（否则会把旁边的标签挤出屏幕）`() {
        assertEquals("张老板", shortLabel("张老板"))
        assertEquals("张老板张老板…", shortLabel("张老板张老板张老板张老板"))
        assertEquals("六个字刚刚好", shortLabel("六个字刚刚好"))
    }

    @Test
    fun `三种图的类型码与显示名一一对应`() {
        assertEquals(listOf("折线", "条形", "扇形"), CHART_TYPES_ALL.map { chartTypeLabel(it) })
        assertTrue(CHART_LINE in CHART_TYPES_ALL && CHART_BAR in CHART_TYPES_ALL && CHART_PIE in CHART_TYPES_ALL)
        // 订单账与司机账三样都有；货主/批发商账没有折线（接口没有按天的数）
        assertEquals(3, CHART_TYPES_ALL.size)
    }

    @Test
    fun `账户类那两档不给折线（数据不支持，给了就会画出比合计小的线）`() {
        assertEquals(CHART_TYPES_ALL, chartTypesFor(0))
        assertEquals(CHART_TYPES_ALL, chartTypesFor(1))
        assertEquals(listOf(CHART_BAR, CHART_PIE), chartTypesFor(2))
        assertEquals(listOf(CHART_BAR, CHART_PIE), chartTypesFor(3))
        // 每一档至少要给一种图，否则切换条是空的、右边什么都没有
        (0..3).forEach { assertTrue("tab $it 一种图都没有", chartTypesFor(it).isNotEmpty()) }
    }
}
