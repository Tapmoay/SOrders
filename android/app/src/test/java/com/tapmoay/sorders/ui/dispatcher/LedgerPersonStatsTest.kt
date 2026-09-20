package com.tapmoay.sorders.ui.dispatcher

import com.tapmoay.sorders.data.remote.dto.OrderDto
import com.tapmoay.sorders.data.remote.dto.OrderProductDto
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.math.BigDecimal

/**
 * 账本「某个货主的账」那一页的商品统计（`productStats`）。
 *
 * 为什么值得钉：这一块是**给用户照着做决定的**（"哪几样货还欠着钱"）——
 * 数字错了不会有任何报错，用户会拿着一个偏大的欠款去催收，或者以为自己收多了。
 * 三条最要紧的判据：
 * 1. 各商品的「未收」加起来 == 各订单欠款之和（**一分不差**）；
 * 2. 退货那部分既不算数量也不算金额（货已经回来了）；
 * 3. 单价 = 金额 ÷ 数量（不是行上那个单价原样抄 —— 同一商品多次不同价时要给加权均价）。
 */
class LedgerPersonStatsTest {

    private fun line(
        name: String,
        qty: Int,
        price: String,
        returned: Int = 0,
        unit: String = "件",
        id: Long = 0,
    ) = OrderProductDto(
        id = id,
        productNameSnapshot = name,
        quantity = qty,
        unitPrice = price,
        lineTotal = BigDecimal(price).multiply(BigDecimal(qty)).toPlainString(),
        unit = unit,
        returnedQuantity = returned,
    )

    private fun order(
        lines: List<OrderProductDto>,
        arrears: String,
        settled: String = "0",
        returned: String = "0",
    ) = OrderDto(
        id = 1,
        orderNo = "SO1",
        status = "DELIVERED",
        orderProducts = lines,
        arrearsAmount = arrears,
        settledAmount = settled,
        returnedAmount = returned,
    )

    @Test
    fun `一张全欠的单按商品摊开`() {
        val o = order(
            listOf(line("苹果", 10, "5.00", id = 1), line("梨", 4, "10.00", id = 2)),
            arrears = "90.00",
        )
        val stats = productStats(listOf(o))
        assertEquals(listOf("苹果", "梨"), stats.map { it.name })
        assertEquals(10, stats[0].quantity)
        assertEquals(BigDecimal("50.00"), stats[0].amount)
        assertEquals(BigDecimal("50.00"), stats[0].owed)
        assertEquals(BigDecimal("40.00"), stats[1].owed)
        assertEquals(BigDecimal("5.00"), stats[0].unitPrice)
        assertEquals(BigDecimal("10.00"), stats[1].unitPrice)
    }

    @Test
    fun `各商品的未收加起来精确等于订单欠款`() {
        // 应收 50 + 40 = 90，实欠 30（收过 60）→ 按比例摊：苹果 30×50/90、梨 吃掉余数
        val o = order(
            listOf(line("苹果", 10, "5.00", id = 1), line("梨", 4, "10.00", id = 2)),
            arrears = "30.00",
            settled = "60.00",
        )
        val stats = productStats(listOf(o))
        assertEquals(
            "分摊之后必须一分不差地等于订单欠款（否则报表上会多出/少掉一笔没人认领的钱）",
            3000L,
            stats.sumOf { moneyCents(it.owed.toPlainString()) },
        )
    }

    @Test
    fun `除不尽时余数落在最后一行`() {
        // 三行等额、欠款 1 分：前两行各 0，最后一行拿 1 分 —— 加起来仍然是 1 分
        val o = order(
            listOf(
                line("甲", 1, "0.01", id = 1),
                line("乙", 1, "0.01", id = 2),
                line("丙", 1, "0.01", id = 3),
            ),
            arrears = "0.01",
        )
        val stats = productStats(listOf(o))
        assertEquals(1L, stats.sumOf { moneyCents(it.owed.toPlainString()) })
    }

    @Test
    fun `退掉的数量与金额都不算进来`() {
        val o = order(
            listOf(line("苹果", 10, "5.00", returned = 4, id = 1)),
            arrears = "30.00",
            returned = "20.00",
        )
        val stats = productStats(listOf(o))
        assertEquals("退了 4 件的货不该还算在'卖了哪些货'里", 6, stats[0].quantity)
        assertEquals(BigDecimal("30.00"), stats[0].amount)
        assertEquals(BigDecimal("30.00"), stats[0].owed)
    }

    @Test
    fun `整行退完的商品不出现在统计里`() {
        val o = order(
            listOf(
                line("苹果", 2, "5.00", returned = 2, id = 1),
                line("梨", 1, "10.00", id = 2),
            ),
            arrears = "10.00",
            returned = "10.00",
        )
        val stats = productStats(listOf(o))
        assertEquals(listOf("梨"), stats.map { it.name })
    }

    @Test
    fun `多张单同一个商品要合并`() {
        val a = order(listOf(line("苹果", 2, "5.00", id = 1)), arrears = "10.00")
        val b = OrderDto(
            id = 2, orderNo = "SO2", status = "DELIVERED",
            orderProducts = listOf(line("苹果", 3, "6.00", id = 2)),
            arrearsAmount = "0", settledAmount = "18.00",
        )
        val stats = productStats(listOf(a, b))
        assertEquals(1, stats.size)
        assertEquals(5, stats[0].quantity)
        assertEquals(BigDecimal("28.00"), stats[0].amount)
        assertEquals("只有还欠着的那一单计入未收", BigDecimal("10.00"), stats[0].owed)
        assertEquals(BigDecimal("5.60"), stats[0].unitPrice)
    }

    @Test
    fun `已收清的单未收为 0`() {
        val o = order(listOf(line("苹果", 2, "5.00", id = 1)), arrears = "0.00", settled = "10.00")
        val stats = productStats(listOf(o))
        assertEquals(BigDecimal("0.00"), stats[0].owed)
        assertEquals(BigDecimal("10.00"), stats[0].amount)
    }

    @Test
    fun `没有订单时不炸`() {
        assertTrue(productStats(emptyList()).isEmpty())
    }

    @Test
    fun `单价是加权均价而不是抄行上的价`() {
        // 同一商品两次不同价（5 元 × 2、6 元 × 3）→ 均价 5.60，不是任何一行上的价
        val a = order(listOf(line("苹果", 2, "5.00", id = 1)), arrears = "10.00")
        val b = OrderDto(
            id = 3, orderNo = "SO3", status = "DELIVERED",
            orderProducts = listOf(line("苹果", 3, "6.00", id = 2)),
            arrearsAmount = "18.00",
        )
        assertEquals(BigDecimal("5.60"), productStats(listOf(a, b))[0].unitPrice)
    }
}
