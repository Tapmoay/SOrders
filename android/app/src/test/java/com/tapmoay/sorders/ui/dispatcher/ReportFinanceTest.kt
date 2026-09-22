package com.tapmoay.sorders.ui.dispatcher

import com.tapmoay.sorders.data.remote.dto.ProductReportDto
import com.tapmoay.sorders.data.remote.dto.ProductReportItemDto
import com.tapmoay.sorders.data.remote.dto.TurnoverReportDto
import com.tapmoay.sorders.ui.common.DatePresets
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.LocalDate

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
    fun `时间窗口：档位 → (from, to)，报表自己不另算一遍区间（2026-09-22 换口径）`() {
        // 2026-09-22 之前报表是 `mode`(day/week/month) + `anchor`，窗口由报表自己算；
        // 现在整页是一段**明确区间**，与账本/订单页共用 `DatePresets.rangeOf` 那一份实现 ——
        // 各算一遍的下场是「本月」在报表是整月、在账本是 1 日到今天，两个页面两个口径。
        val today = LocalDate.of(2026, 9, 22) // 周二
        assertEquals("2026-09-22" to "2026-09-22", ReportFinance.windowOf("今天", null, null, today))
        assertEquals("2026-09-21" to "2026-09-21", ReportFinance.windowOf("昨天", null, null, today))
        // 这周 = 本周一 ~ 今天；上周 = 上周一 ~ 上周日（与 DatePresets 同一套）
        assertEquals("2026-09-21" to "2026-09-22", ReportFinance.windowOf("这周", null, null, today))
        assertEquals("2026-09-14" to "2026-09-20", ReportFinance.windowOf("上周", null, null, today))
        // ⚠️「近 7 天」以前在报表里**表达不出来**（只有日/周/月三档）——现在它就是一个区间，能用了
        assertEquals("2026-09-16" to "2026-09-22", ReportFinance.windowOf("近 7 天", null, null, today))
        assertEquals("2026-09-01" to "2026-09-22", ReportFinance.windowOf("本月", null, null, today))
        assertEquals("2026-08-01" to "2026-08-31", ReportFinance.windowOf("上月", null, null, today))
    }

    @Test
    fun `自定义区间用它自己那一段；半截自定义落到最宽的窗口（宁可多算不许少算）`() {
        val today = LocalDate.of(2026, 9, 22)
        assertEquals(
            "2026-08-01" to "2026-08-20",
            ReportFinance.windowOf(DatePresets.CUSTOM, "2026-08-01", "2026-08-20", today),
        )
        // 只选了一头（弹层的半成品状态，正常不会回调到这里）→ 按**全部**看：
        // 报表宁可多算，也不许悄悄少算一段 —— 少算的那几天页面上完全看不出来
        assertEquals(
            ReportFinance.ALL_FROM to "2026-09-22",
            ReportFinance.windowOf(DatePresets.CUSTOM, "2026-08-01", null, today),
        )
    }

    @Test
    fun `「全部」落成一段覆盖所有数据的区间（报表端点必须给一段窗口）`() {
        val today = LocalDate.of(2026, 9, 22)
        val (from, to) = ReportFinance.windowOf(DatePresets.ALL, null, null, today)
        assertEquals(ReportFinance.ALL_FROM, from)
        assertEquals("2026-09-22", to)
        assertTrue("起点必须早于库里的任何数据（2025 年才开始用）", from < "2025-01-01")
    }

    @Test
    fun `自动挡那一串档位在报表里每一档都能落成区间（没有表达不出来的了）`() {
        val today = LocalDate.of(2026, 9, 22)
        DatePresets.ORDER_PRESET_LADDER.forEach { label ->
            val (from, to) = ReportFinance.windowOf(label, null, null, today)
            assertTrue("$label 的窗口起止反了：$from~$to", from <= to)
            assertTrue("$label 的窗口必须含今天或落在今天之前：$from~$to", to <= "2026-09-22")
        }
    }

    @Test
    fun `有数的判据：单数或金额任一非零才算有数`() {
        // 页面原来是**写死的「按日 + 今天」**：今天没有已送达的单时整页 ¥0.00 / 0 单，
        // 用户 2026-09-22 报的就是「报告中心没有任何数据」。
        assertFalse(ReportFinance.hasData(0, "0"))
        assertFalse(ReportFinance.hasData(0, "0.00"))
        assertTrue(ReportFinance.hasData(1, "0"))
        assertTrue(ReportFinance.hasData(0, "21345.60"))
        // 认不出来的金额串**不许**当成"有数"（那会让页面停在一个空窗口上，等于 bug 没修）
        assertFalse(ReportFinance.hasData(0, ""))
        assertFalse(ReportFinance.hasData(0, "abc"))
    }
}
