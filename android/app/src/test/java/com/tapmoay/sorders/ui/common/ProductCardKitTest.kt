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
    fun `售价带上单位，金额末尾多余的 0 去掉`() {
        // 用户 2026-09-22：「有零的全省」—— 25.00 就写 25（这个价卡在全 App 五处复用）
        val f = productPriceFact("25", "袋")
        assertEquals("¥25/袋", f.value)
    }

    @Test
    fun `子分价不许被四舍五入（卡片=弹窗=库）`() {
        // BUG-0028 / 测试台账 TA-08（2026-10-10）：商品的默认售价列是 Numeric(14,4)，可以是 0.005 元/箱。
        // 这一行原来走 formatMoney（"到分四舍五入"），0.005 被印成 ¥0.01/箱 —— 卡片上是真值的**两倍**，
        // 而同一件商品的改价弹窗预填用的是 trimMoneyZeros，显示 0.005：同一个数两个答案。
        // ⛔ 口径按列精度选：金额（Numeric(12,2)）用 formatMoney，单价（Numeric(14,4)）用 trimMoneyZeros。
        assertEquals("¥0.005/箱", productPriceFact("0.005", "箱").value)
        assertEquals("¥12.3456/件", productPriceFact("12.3456", "").value)
        assertEquals("¥12.5/袋", productPriceFact("12.5000", "袋").value)
        // 拿不到数时才退回 "0"（改造前 formatMoney("") 也是 0，卡片上不会出现「¥/箱」）
        assertEquals("¥0/件", productPriceFact("", "").value)
    }

    @Test
    fun `单位为空时退回件`() {
        // 各页自己写 ifBlank 的话，同一件商品会出现「¥25/件」和「¥25/」两种
        assertEquals("¥25/件", productPriceFact("25", "").value)
        assertEquals("30 件", productStockFact(30, 0, null).value)
    }

    @Test
    fun `断货是红的`() {
        assertEquals(Color(0xFFE53935), productStockColor(stock = 0, lowStockAlert = 0))
        assertEquals(Color(0xFFE53935), productStockColor(stock = -3, lowStockAlert = 10))
    }

    @Test
    fun `到报警线是黄的`() {
        // ⚠️ 这两个色跟着"判据的配色"走过三程，但**判据本身一个字没动**：
        //    · CHG-0101（2026-10-09 用户三张配色图）换成低饱和的那套：
        //      黄 0xFFFFB300 → 0xFFC8B270、青 0xFF00BCD4 → 0xFF6BA6AE。
        //    · CHG-0102（2026-10-10 用户选了 H 档）黄再跟着走一档：
        //      0xFFC8B270 → 0xFF908643（＝ ProgressYellow 订单管理那格）。
        //    · CHG-0105（2026-10-10 只还色相）黄一度按"还色相"换成 0xFFA17C42，
        //      随后按用户「工作台就按我们一开始的那个题目那个方案」退回 0xFF908643
        //      （净结果：这个黄没变）；青则微调 0xFF6BA6AE → 0xFF6CA6B1。
        //    ⛔ 青读的是 `OriginTeal`（线路起点），不是工作台那 19 格里的任何一个。
        //    ⛔ 色值跟着换是对的，但**判据本身一个字没动**：断货红 / 报警黄 / 正常青
        //    这三档的语义与优先级是这条用例在守的东西（换色不该顺手把它放宽）。
        assertEquals(Color(0xFF908643), productStockColor(stock = 5, lowStockAlert = 10))
        assertEquals(Color(0xFF908643), productStockColor(stock = 10, lowStockAlert = 10))
    }

    @Test
    fun `报警线为零表示不报警而不是阈值为零`() {
        // 少了 lowStockAlert > 0 这个前置条件的话，库存 3 件会被判成"到报警线了"（黄），
        // 而 0 表示的是"这个商品不设报警线"
        assertEquals(Color(0xFF6CA6B1), productStockColor(stock = 3, lowStockAlert = 0))
        assertEquals(Color(0xFF908643), productStockColor(stock = 3, lowStockAlert = 10))
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
