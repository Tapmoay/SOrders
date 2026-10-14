package com.tapmoay.sorders.ui.driver

import com.tapmoay.sorders.data.remote.dto.DriverBillDto
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 固定工资司机的工资账（CHG-0127，用户 m43131）。
 *
 * 这本账要回答四件事，四条都在这里钉着：
 *  ① **只算工资**：按单的运费单（`bill_type = piece`）一分不许混进工资合计（那是运费那半页的账）；
 *  ② **已核销 / 未核销分开数**（用户：「表示已核销……那个没有核销的工资」）—— 已核销的是拍过板的
 *     凭据，未核销的会随固定工资改变被重算（后端 `refresh_unsettled`），混成一个数就答不上
 *     「这个月到底结了多少」；
 *  ③ **任职期间工资变过要有记录**：相邻两张月薪单金额不一样就是一次变更（工资单是按"当月的固定
 *     工资"生成的，改规则不改历史账单 ⇒ 账单本身就是那张工资表的时间线）；
 *  ④ 月份要说人话（「2026 年 10 月」），脏数据**原样回**，不许把那一行变成空白；
 *  ⑤ 派单端那张结算单要说清自己锁了几张工资单 —— 数 `order_ids` 永远得 0（真机走查抓到过）。
 */
class DriverSalaryTest {

    private fun bill(
        id: Long,
        month: String,
        amount: String,
        type: String = "salary",
        status: String = "open",
        settledDocId: Long? = null,
        ruleName: String = "",
        note: String = "",
    ) = DriverBillDto(
        id = id,
        driverId = 9,
        billType = type,
        month = month,
        amount = amount,
        status = status,
        settledDocId = settledDocId,
        ruleName = ruleName,
        note = note,
    )

    // ① 只算工资 --------------------------------------------------------------

    @Test
    fun `月薪单才算工资_按单的运费单一分不混`() {
        val rows = listOf(
            bill(1, "2026-09", "6000.00"),
            bill(2, "2026-09", "198.00", type = "piece"),
            bill(3, "2026-10", "6000.00"),
        )
        assertTrue(isSalaryBill(rows[0]))
        assertFalse(isSalaryBill(rows[1]))
        // 大小写都认（后端枚举值是小写 salary，但导出的脏数据见过 SALARY）
        assertTrue(isSalaryBill(bill(4, "2026-10", "1", type = "SALARY")))
        assertEquals(listOf(3L, 1L), salaryBillsOf(rows).map { it.id })  // 新的在最上面
        assertEquals(12000.0, salaryTotalsOf(rows).all, 0.001)  // 两张月薪单之和，按单那张不混进来
        assertEquals(2, salaryTotalsOf(rows).count)
    }

    // ② 已核销 / 未核销 -------------------------------------------------------

    @Test
    fun `已核销的两种形态都认_状态变了_或者被结算单点名`() {
        assertTrue(isSettledBill(bill(1, "2026-09", "6000", status = "settled")))
        assertTrue(isSettledBill(bill(2, "2026-09", "6000", settledDocId = 7)))
        // 「已被草稿结算单锁住」的单状态还是 open —— 只认状态会把它当成未核销而重算（那是别人的凭证）
        val locked = bill(3, "2026-09", "6000", status = "open", settledDocId = 8)
        assertTrue(isSettledBill(locked))
        assertFalse(isSettledBill(bill(4, "2026-10", "6000")))
    }

    @Test
    fun `已核销与未核销分开数_不合计了事`() {
        val rows = listOf(
            bill(1, "2026-08", "5000.00", status = "settled", settledDocId = 5),
            bill(2, "2026-09", "6000.00", settledDocId = 6),
            bill(3, "2026-10", "6000.00"),
        )
        val t = salaryTotalsOf(rows)
        assertEquals(2, t.settledCount)
        assertEquals(11000.0, t.settled, 0.001)
        assertEquals(1, t.openCount)
        assertEquals(6000.0, t.open, 0.001)
        assertEquals(17000.0, t.all, 0.001)
    }

    @Test
    fun `金额是字符串_坏数据当零不算崩`() {
        val t = salaryTotalsOf(listOf(bill(1, "2026-10", "6000.5"), bill(2, "2026-09", ""), bill(3, "2026-08", "oops")))
        assertEquals(6000.5, t.open, 0.001)
        assertEquals(3, t.openCount)  // 数照记：一笔坏账不能让那一行凭空消失
    }

    // ③ 工资变更 --------------------------------------------------------------

    @Test
    fun `相邻两张不一样就算一次变更_新的在前_月份是变更后的那个月`() {
        val rows = listOf(
            bill(1, "2026-09", "6000.00", ruleName = "老规则"),
            bill(2, "2026-07", "5000.00", ruleName = "老规则"),
            bill(3, "2026-11", "6500.00", ruleName = "新规则"),
            bill(4, "2026-10", "6000.00", ruleName = "老规则"),
        )
        val ch = salaryChangesOf(rows)
        assertEquals(2, ch.size)
        // 新的在前：11 月那次（6000 → 6500）排在最上面，月份 = 变更后那张单的月份
        assertEquals("2026-11", ch[0].month)
        assertEquals(6000.0, ch[0].from, 0.001)
        assertEquals(6500.0, ch[0].to, 0.001)
        assertEquals("新规则", ch[0].ruleName)
        // 8 月没生成工资单 ⇒ 缺口不当成一次变更（7 月 5000 → 9 月 6000 只算一次，落在 9 月）
        assertEquals("2026-09", ch[1].month)
        assertEquals(5000.0, ch[1].from, 0.001)
        assertEquals(6000.0, ch[1].to, 0.001)
    }

    @Test
    fun `工资没变过就没有变更记录_只有一张单也一样`() {
        assertEquals(0, salaryChangesOf(listOf(bill(1, "2026-10", "6000"))).size)
        assertEquals(
            0,
            salaryChangesOf(listOf(bill(1, "2026-09", "6000"), bill(2, "2026-10", "6000"))).size,
        )
    }

    @Test
    fun `按单的账单不参与变更线`() {
        val rows = listOf(
            bill(1, "2026-09", "6000.00"),
            bill(2, "2026-10", "198.00", type = "piece"),  // 这个月只有一笔运费，没有工资单
        )
        // 月薪单只有 9 月那一张 ⇒ 不产生变更（运费单不许进来当"10 月工资"）
        assertEquals(0, salaryChangesOf(rows).size)
    }

    // ④ 月份说人话 ------------------------------------------------------------

    @Test
    fun `月份说人话_脏数据原样回`() {
        assertEquals("2026 年 10 月", salaryMonthWord("2026-10"))
        assertEquals("2026 年 1 月", salaryMonthWord("2026-01"))
        assertEquals("2026 年 12 月", salaryMonthWord(" 2026-12 "))
        assertEquals("2026", salaryMonthWord("2026"))
        assertEquals("abc-def", salaryMonthWord("abc-def"))
        assertEquals("", salaryMonthWord(""))
    }
    // ①×② 交叉：按单的钱不许混进工资那两边的任何一边 -------------------------

    @Test
    fun `按单的运费单不许混进任何一边_哪怕它已核销`() {
        val rows = listOf(
            bill(1, "2026-10", "6000.00"),
            bill(2, "2026-10", "198.00", type = "piece", status = "settled", settledDocId = 3),
            bill(3, "2026-10", "120.00", type = "piece"),
        )
        val t = salaryTotalsOf(rows)
        // 那张按单的钱确实核销过 —— 但它是运费那半页的账，工资这边两边都不许进
        assertEquals(0, t.settledCount)
        assertEquals(0.0, t.settled, 0.001)
        assertEquals(1, t.openCount)
        assertEquals(6000.0, t.open, 0.001)
        assertEquals(1, t.count)
    }

    // 边界：空账本 / 全是坏金额 ------------------------------------------------

    @Test
    fun `空账本不崩_全是坏金额也不崩_数照记`() {
        val empty = salaryTotalsOf(emptyList())
        assertEquals(0, empty.count)
        assertEquals(0.0, empty.all, 0.001)
        assertTrue(salaryBillsOf(emptyList()).isEmpty())
        assertEquals(0, salaryChangesOf(emptyList()).size)
        val bad = salaryTotalsOf(listOf(bill(1, "2026-10", "oops"), bill(2, "2026-10", "")))
        assertEquals(2, bad.openCount)  // 数照记：一笔坏账不能让那一行凭空消失
        assertEquals(0.0, bad.open, 0.001)
    }

    // ④ 月份形状不对：原样回，不许拼半截 ---------------------------------------

    @Test
    fun `月份形状不对原样回_不拼半截`() {
        assertEquals("2026-1", salaryMonthWord("2026-1"))        // 短于 7 位
        assertEquals("abcd-10", salaryMonthWord("abcd-10"))     // 年不是数字
        assertEquals("2026-xx", salaryMonthWord("2026-xx"))     // 月不是数字
        assertEquals("2026-00", salaryMonthWord("2026-00"))     // 月份是 0（trimStart('0') 之后空了）
        assertEquals("2026 年 10 月", salaryMonthWord(" 2026-10 "))
    }

    // ⑤ 结算单那一行数几张「工资单」 -------------------------------------------

    @Test
    fun `结算单数的是被它锁住的工资单_不是订单`() {
        val rows = listOf(
            bill(1, "2026-09", "6000.00", settledDocId = 7),
            bill(2, "2026-10", "8000.00", settledDocId = 7),
            bill(3, "2026-11", "8000.00"),                      // 还没核销，不算
            bill(4, "2026-11", "198.00", type = "piece", settledDocId = 8),
        )
        // 工资结算单覆盖的是**工资单**（后端存 bill_ids），它那张单的 order_ids 天生是空的 ——
        // 数订单必然得 0：真机上就写着「工资单 0 笔」，旁边挂着 ¥8000。
        assertEquals(2, settledBillCountOf(rows, 7))
        assertEquals(1, settledBillCountOf(rows, 8))
        assertEquals(0, settledBillCountOf(rows, 99))   // 别人的单锁的不算
        assertEquals(0, settledBillCountOf(emptyList(), 7))
    }
}