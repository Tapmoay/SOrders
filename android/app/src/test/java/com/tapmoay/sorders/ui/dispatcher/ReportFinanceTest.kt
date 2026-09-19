package com.tapmoay.sorders.ui.dispatcher

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
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
}
