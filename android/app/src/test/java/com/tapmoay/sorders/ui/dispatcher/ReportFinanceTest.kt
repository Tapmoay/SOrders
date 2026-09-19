package com.tapmoay.sorders.ui.dispatcher

import com.tapmoay.sorders.data.remote.dto.ProductReportDto
import com.tapmoay.sorders.data.remote.dto.ProductReportItemDto
import com.tapmoay.sorders.data.remote.dto.TurnoverReportDto
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 报表中心的三个纯映射（[ReportFinance]）。
 *
 * ### 为什么这三条值得一个测试文件
 * 它们**全都曾经悄悄错过**，而且错法一模一样：界面上不报错、不崩、看起来正常——
 * 只是数字和标签是错的。这类 bug 只有"钉住取值"才防得住，靠人眼复查是防不住的。
 */
class ReportFinanceTest {

    // ---------------------------------------------------------- 页签 → 导出 kind

    @Test
    fun `页签顺序与报表入口页一致（0 营业纵览 … 5 异常与审计）`() {
        // 与 ReportHomeScreen 里那份入口清单逐项对齐
        assertEquals("turnover", ReportFinance.exportKind(0))
        assertEquals("products", ReportFinance.exportKind(1))
        assertEquals("drivers", ReportFinance.exportKind(2))
        assertEquals("customers", ReportFinance.exportKind(3))
        assertEquals("finance", ReportFinance.exportKind(4))
        assertEquals("audit", ReportFinance.exportKind(5))
    }

    @Test
    fun `六个页签导出的 kind 两两不同（错位的根因就是有两个页签映射到同一个词）`() {
        val kinds = (0..5).map { ReportFinance.exportKind(it) }
        assertEquals(kinds.size, kinds.toSet().size)
    }

    @Test
    fun `越界页签兜到 audit，不会崩`() {
        assertEquals("audit", ReportFinance.exportKind(6))
        assertEquals("audit", ReportFinance.exportKind(-1))
    }

    @Test
    fun `只有后四个页签按日期区间导出`() {
        assertFalse(ReportFinance.usesDateRange(0))
        assertFalse(ReportFinance.usesDateRange(1))
        assertTrue(ReportFinance.usesDateRange(2))
        assertTrue(ReportFinance.usesDateRange(3))
        assertTrue(ReportFinance.usesDateRange(4))
        assertTrue(ReportFinance.usesDateRange(5))
    }

    // ---------------------------------------------------------- 毛利公式

    @Test
    fun `商品毛利只算有成本快照的那批行（旧公式虚高约七倍）`() {
        // 实测同一个月：旧公式（营业金额 − 成本）算出 72,177.75，
        // 正确值（有成本那批行的收入 − 成本）是 10,789.00。
        val data = TurnoverReportDto(
            totalAmount = "97131.75",          // 全部行的金额
            costTotal = "24954.00",            // 只有成本行的成本
            costCoveredAmount = "35743.00",    // 有成本那批行的**收入**
        )
        assertEquals(10789.0, grossProfit(data), 0.005)
        assertTrue("不许退回旧公式", grossProfit(data) < 20000.0)

        // 缺字段时按 0 处理，不崩
        assertEquals(0.0, grossProfit(TurnoverReportDto()), 0.005)
    }

    @Test
    fun `商品页的毛利也走后端给的参与毛利金额（不许客户端自己再筛一遍）`() {
        // 实测同一个月三处三个数：App 商品页 11,071.00 / 正确的 10,789.00 / 导出逐行合计 72,177.75。
        // 根因：客户端与导出**各自** sum 了一遍"有成本行的金额"，于是两边一起错。
        val data = ProductReportDto(
            totalAmount = "97131.75",
            costTotal = "24954.00",
            costCoveredAmount = "35743.00",
            costCoveredLines = 147,
            totalLines = 557,
        )
        assertEquals(10789.0, productGrossProfit(data), 0.005)

        // 老后端不下发 cost_covered_amount → 回落到本地筛选（过渡口径）：只有带成本的行进收入侧
        val legacy = ProductReportDto(
            totalAmount = "100",
            costTotal = "40",
            items = listOf(ProductReportItemDto(productName = "有成本", amount = "100", cost = "40")),
        )
        assertEquals(60.0, productGrossProfit(legacy), 0.005)
    }

    @Test
    fun `逐行毛利必须用参与毛利的金额，没有成本快照的行返回 null`() {
        // 唯一混合组实测：正确 305.50−260=45.50；老公式（全额金额 − 成本）印 587.50−260=327.50（7.2 倍）
        val mixed = ProductReportItemDto(
            productName = "ttt", amount = "587.50", cost = "260", coveredAmount = "305.50", coveredLines = 3
        )
        assertEquals(45.50, productItemProfit(mixed)!!, 0.005)

        // 一行都没有成本快照 → 不进毛利（界面印「—」，不是印一个 100% 毛利的大数）
        val noCost = ProductReportItemDto(productName = "没成本", amount = "61106.75", cost = "0")
        assertNull(productItemProfit(noCost))

        // 老后端（没有 coveredAmount）：有成本才算，收入侧仍按全额 → 与老行为一致，不崩
        val legacy = ProductReportItemDto(productName = "老后端", amount = "100", cost = "40")
        assertEquals(60.0, productItemProfit(legacy)!!, 0.005)
    }

    // ---------------------------------------------------------- 资金方向

    @Test
    fun `后端存的是小写 in out（大写的旧写法会让流入恒为 0）`() {
        assertTrue(ReportFinance.isIncome("in"))
        assertFalse(ReportFinance.isIncome("out"))
        // 旧代码比的是 "IN" → 永远 false → 每一笔收款都显示成"支出 −¥500"
        assertTrue("大写也要认", ReportFinance.isIncome("IN"))
        assertTrue(ReportFinance.isIncome(" in "))
        assertFalse(ReportFinance.isIncome(null))
        assertFalse(ReportFinance.isIncome(""))
    }

    // ---------------------------------------------------------- 取值 → 中文

    @Test
    fun `资金业务类型按枚举名认（不是猜出来的小写短语）`() {
        assertEquals("客户收款（现金）", ReportFinance.bizLabel("RECEIPT_CASH"))
        assertEquals("司机运费", ReportFinance.bizLabel("PAYMENT_DRIVER"))
        assertEquals("货损", ReportFinance.bizLabel("EXPENSE_LOSS"))
        assertEquals("挂账结清", ReportFinance.bizLabel("RECEIPT_ARREARS"))
        // 旧词表里的写法（"payment"/"driver_payment"/"damage"）**一个都不是真值**：
        // 认不出来就原样显示，绝不编一个"其他"把它藏起来。
        assertEquals("payment", ReportFinance.bizLabel("payment"))
    }

    @Test
    fun `空值与未知值原样返回，不编造`() {
        assertEquals("", ReportFinance.bizLabel(null))
        assertEquals("", ReportFinance.bizLabel(""))
        assertEquals("SOMETHING_NEW", ReportFinance.bizLabel("SOMETHING_NEW"))
    }

    @Test
    fun `开销分类八个真实取值都能翻`() {
        assertEquals("油费", ReportFinance.expenseCategoryLabel("fuel"))
        assertEquals("维修", ReportFinance.expenseCategoryLabel("repair"))
        assertEquals("过路费", ReportFinance.expenseCategoryLabel("toll"))
        assertEquals("停车费", ReportFinance.expenseCategoryLabel("parking"))
        assertEquals("罚款", ReportFinance.expenseCategoryLabel("fine"))
        assertEquals("保险", ReportFinance.expenseCategoryLabel("insurance"))
        assertEquals("货损", ReportFinance.expenseCategoryLabel("loss"))
        assertEquals("其他", ReportFinance.expenseCategoryLabel("other"))
        // 旧词表把货损写成 "damage"（后端从来没有这个值）→ 真值 loss 落到 else，页面显示英文
        assertEquals("damage", ReportFinance.expenseCategoryLabel("damage"))
    }

    @Test
    fun `时间窗口：整月就是整月、整周就是整周（不许只到锚点当天）`() {
        // 2026-09-19 审计：标题与取数窗口原来是**两处各写一遍**，而且写法不同 ——
        // 标题写整月 `2026-09-01 ~ 2026-09-30`，取数只到锚点当天 `2026-09-01 ~ 2026-09-05`。
        // 结果 9/5 打开报表：标题写整月、数字只含 5 天；9/20 打开则少掉后面 10 天的收支。
        // 现在两边都走 rangeFor，这里把它钉死。
        assertEquals("2026-09-01" to "2026-09-30", ReportFinance.rangeFor("month", "2026-09-19"))
        assertEquals("2026-02-01" to "2026-02-28", ReportFinance.rangeFor("month", "2026-02-10"))
        // 2026-09-19 是周六 → 本周一 09-14、周日 09-20
        assertEquals("2026-09-14" to "2026-09-20", ReportFinance.rangeFor("week", "2026-09-19"))
        assertEquals("2026-09-19" to "2026-09-19", ReportFinance.rangeFor("day", "2026-09-19"))
    }
}
