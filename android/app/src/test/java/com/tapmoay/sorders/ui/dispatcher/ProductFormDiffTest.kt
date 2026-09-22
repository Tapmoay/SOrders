package com.tapmoay.sorders.ui.dispatcher

import com.tapmoay.sorders.data.remote.dto.ProductDto
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 商品编辑页「哪些键真的改了」的纯逻辑（`productEdits` / `moneySame`）。
 *
 * ## 为什么这几条必须单测
 * 它守的是**钱**，而且失败的样子是"界面上什么都看不出来"：
 *
 * 1. 这一版之前编辑页**整份回传** 8 个字段，值来自打开那一刻的草稿 ——
 *    你开着编辑页时别人改了这条商品的任何字段（或你自己在商品卡上快捷改过价），
 *    一保存就**静默写回旧值**；
 * 2. 反过来，如果"哪些键改了"算错成"全都改了"，那就退回了 1 的老毛病；
 * 3. 库里 `default_unit_price` 是 `Numeric(14,4)`（`"12.3400"`），而草稿预填走
 *    `trimMoneyZeros`（`"12.34"`）—— **按字符串比会把"没改价"判成改过**，
 *    于是每次保存都在"改价"（操作日志里每次多一条价格变更，等于把审计记录灌水）。
 *
 * 模拟器上这几种错**都看不出来**（点了保存、也确实存上了），所以钉在纯函数上。
 */
class ProductFormDiffTest {

    private fun product(
        name: String = "五常大米",
        price: String = "25.0000",
        cost: String = "18.0000",
        unit: String = "袋",
        category: String = "粮油",
        alert: Int = 0,
        color: String? = "#1565C0",
        active: Boolean = true,
    ) = ProductDto(
        id = 7L,
        name = name,
        nameColor = color,
        defaultUnitPrice = price,
        costPrice = cost,
        isActive = active,
        stock = 12,
        unit = unit,
        category = category,
        lowStockAlert = alert,
    )

    /** 草稿默认 = "原样打开、什么都没碰"（预填口径与 `ProductFormViewModel.fill` 一致）。 */
    private fun draftOf(p: ProductDto) = ProductDraft(
        name = p.name,
        price = com.tapmoay.sorders.util.trimMoneyZeros(p.defaultUnitPrice),
        cost = com.tapmoay.sorders.util.trimMoneyZeros(p.costPrice),
        unit = p.unit,
        category = p.category,
        alert = if (p.lowStockAlert > 0) p.lowStockAlert.toString() else "",
        color = p.nameColor ?: com.tapmoay.sorders.ui.common.DEFAULT_PRODUCT_NAME_COLOR,
        active = p.isActive,
    )

    @Test
    fun `一个键都没改 → 不发请求`() {
        val p = product()
        assertNull(productEdits(p, draftOf(p)))
    }

    @Test
    fun `库里四位小数与草稿去尾零是同一个价（不然每次保存都在改价）`() {
        val p = product(price = "12.3456", cost = "3.1000")
        // 预填是 trimMoneyZeros：12.3456 原样、"3.1000" → "3.1"
        assertEquals("12.3456", com.tapmoay.sorders.util.trimMoneyZeros(p.defaultUnitPrice))
        assertEquals("3.1", com.tapmoay.sorders.util.trimMoneyZeros(p.costPrice))
        assertNull("没改价就不该发价", productEdits(p, draftOf(p)))
    }

    @Test
    fun `只改售价时，请求里只有售价这一个键`() {
        val p = product(price = "25.0000")
        val req = productEdits(p, draftOf(p).copy(price = "26.5"))
        assertNotNull(req)
        assertEquals("26.5", req!!.defaultUnitPrice)
        // 其余键必须是 null —— Json 配了 explicitNulls=false，null 的键**根本不会出现在请求体里**，
        // 后端 `exclude_unset` 也就不会碰它们（这就是"静默写回旧值"被堵住的地方）
        assertNull(req.name)
        assertNull(req.costPrice)
        assertNull(req.unit)
        assertNull(req.category)
        assertNull(req.isActive)
        assertNull(req.nameColor)
        assertNull(req.lowStockAlert)
        assertNull(req.imageUrl)
    }

    @Test
    fun `只改名字时，售价不会被一起带上（哪怕它被重新格式化过）`() {
        val p = product(price = "25.0000")
        val req = productEdits(p, draftOf(p).copy(name = "五常大米（新）"))
        assertNotNull(req)
        assertEquals("五常大米（新）", req!!.name)
        assertNull("价没碰过就不许带", req.defaultUnitPrice)
    }

    @Test
    fun `分类可以清空（空串 = 未分类），但不能与「没改」混为一谈`() {
        val p = product(category = "粮油")
        val req = productEdits(p, draftOf(p).copy(category = ""))
        assertNotNull(req)
        assertEquals("", req!!.category)
        assertNull(productEdits(p, draftOf(p)))
    }

    @Test
    fun `单位留空按「件」兜底再比（不然会把库里的单位覆盖成空）`() {
        assertEquals("件", com.tapmoay.sorders.ui.common.DEFAULT_UNIT)
        // ① 商品本来就是「件」：草稿空着 = 没改
        assertNull(productEdits(product(unit = "件"), draftOf(product(unit = "件")).copy(unit = "")))
        // ② 商品是「袋」：草稿空着 = 改成「件」（这是用户真的动了它）
        val req = productEdits(product(unit = "袋"), draftOf(product(unit = "袋")).copy(unit = ""))
        assertNotNull(req)
        assertEquals("件", req!!.unit)
    }

    @Test
    fun `报警阈值：空串与 0 是同一件事`() {
        assertNull(productEdits(product(alert = 0), draftOf(product(alert = 0)).copy(alert = "")))
        val req = productEdits(product(alert = 5), draftOf(product(alert = 5)).copy(alert = ""))
        assertNotNull(req)
        assertEquals(0, req!!.lowStockAlert)
    }

    @Test
    fun `上下架开关真的改了才带上`() {
        val p = product(active = true)
        val req = productEdits(p, draftOf(p).copy(active = false))
        assertNotNull(req)
        assertEquals(false, req!!.isActive)
        assertNull(productEdits(p, draftOf(p)))
    }

    @Test
    fun `移除图片会写空串（旧版那个按钮只清本地草稿，服务端那张图原样还在）`() {
        val p = product()
        val req = productEdits(p, draftOf(p).copy(imageCleared = true))
        assertNotNull(req)
        assertEquals("", req!!.imageUrl)
    }

    @Test
    fun `名称与分类会去掉首尾空格再比（不然「粮油 」会被当成改动）`() {
        val p = product(name = "五常大米", category = "粮油")
        val d = draftOf(p).copy(name = "  五常大米  ", category = "粮油 ")
        assertNull(productEdits(p, d))
    }

    @Test
    fun `没设过名称颜色的商品：草稿用兜底色不算改动，换成别的色才算`() {
        val p = product(color = null)
        val base = draftOf(p)
        assertEquals(com.tapmoay.sorders.ui.common.DEFAULT_PRODUCT_NAME_COLOR, base.color)
        assertNull(productEdits(p, base))
        val req = productEdits(p, base.copy(color = "#2E7D32"))
        assertNotNull(req)
        assertEquals("#2E7D32", req!!.nameColor)
    }

    @Test
    fun `moneySame 对非法串不抛异常（宁可比字符串也不崩）`() {
        assertTrue(moneySame("12.34", "12.3400"))
        assertTrue(moneySame("0", ""))
        assertTrue(moneySame("0", null))
        assertFalse(moneySame("12.34", "12.35"))
        assertFalse(moneySame("abc", "12.34"))
        assertTrue(moneySame("abc", "abc"))
    }
}
