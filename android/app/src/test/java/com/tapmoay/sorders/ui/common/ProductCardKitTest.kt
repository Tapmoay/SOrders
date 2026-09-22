package com.tapmoay.sorders.ui.common

import androidx.compose.ui.graphics.Color
import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * 商品外观零件的**判据**单测（2026-09-21 第二轮）。
 *
 * 为什么这些"看起来只是排版"的东西要有单测：它们全是**一条业务口径**——
 * 「库存在售价下面」「到报警线是黄的、断货才是红的」「报警线 0 = 不报警」。
 * 这几条都**不会报错**：改错了界面照常渲染，只是颜色/顺序变了，
 * 而用户是靠颜色扫列表决定先处理哪几件的（红线只能盯住"字符串里写的顺序"，
 * 盯不住"运行时到底谁在前"）。
 */
class ProductCardKitTest {

    @Test
    fun `售价排在库存前面`() {
        val facts = productFacts(price = "25.00", unit = "袋", stock = 30, lowStockAlert = 0)
        assertEquals(listOf("售价", "库存"), facts.map { it.label })
    }

    @Test
    fun `售价带上单位与两位小数`() {
        val f = productPriceFact("25", "袋")
        assertEquals("¥25.00/袋", f.value)
    }

    @Test
    fun `单位为空时退回件`() {
        // 各页自己写 ifBlank 的话，同一件商品会出现「¥25.00/件」和「¥25.00/」两种
        assertEquals("¥25.00/件", productPriceFact("25", "").value)
        assertEquals("30 件", productStockFact(30, 0, null).value)
    }

    @Test
    fun `断货是红的`() {
        assertEquals(Color(0xFFE53935), productStockColor(stock = 0, lowStockAlert = 0))
        assertEquals(Color(0xFFE53935), productStockColor(stock = -3, lowStockAlert = 10))
    }

    @Test
    fun `到报警线是黄的`() {
        assertEquals(Color(0xFFFFB300), productStockColor(stock = 5, lowStockAlert = 10))
        assertEquals(Color(0xFFFFB300), productStockColor(stock = 10, lowStockAlert = 10))
    }

    @Test
    fun `报警线为零表示不报警而不是阈值为零`() {
        // 少了 lowStockAlert > 0 这个前置条件的话，库存 3 件会被判成"到报警线了"（黄），
        // 而 0 表示的是"这个商品不设报警线"
        assertEquals(Color(0xFF00BCD4), productStockColor(stock = 3, lowStockAlert = 0))
        assertEquals(Color(0xFFFFB300), productStockColor(stock = 3, lowStockAlert = 10))
    }

    @Test
    fun `角标只在缺货与到报警线时出现`() {
        assertEquals(null, productStockBadgeText(stock = 30, lowStockAlert = 0))
        assertEquals(null, productStockBadgeText(stock = 30, lowStockAlert = 10))
        assertEquals("低库存", productStockBadgeText(stock = 6, lowStockAlert = 10))
        assertEquals("缺货", productStockBadgeText(stock = 0, lowStockAlert = 0))
    }

    @Test
    fun `名称色碰到坏值不抛异常`() {
        // ⚠️ 这个用例**证明不了颜色对不对**，只证明"不抛" —— 本工程开了
        //    `unitTests.isReturnDefaultValues = true`，于是 `android.graphics.Color.parseColor`
        //    是一根**返回 0 的桩**：既不解析、也不抛，`productNameColor` 在单测里一律返回透明色
        //    （写这个用例时才发现：一开始断言"坏值退回物流蓝"，红了，红的原因是桩、不是代码）。
        //    "坏值真的会抛 / 兜底值真的是物流蓝"这两条只能靠
        //    真机截图 + 反向验证（`_reverse_verify_product_card.py` 把 try/catch 拆掉就红）。
        productNameColor(null)
        productNameColor("深蓝")
        productNameColor("#12345")
    }

    @Test
    fun `占用那一行是负数并带单位`() {
        val f = productReservedFact(5, "件")
        assertEquals("占用", f.label)
        assertEquals("-5 件", f.value)
    }
}
