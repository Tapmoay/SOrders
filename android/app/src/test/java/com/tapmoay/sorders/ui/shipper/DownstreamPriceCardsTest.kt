package com.tapmoay.sorders.ui.shipper

import com.tapmoay.sorders.data.remote.api.ShipperPriceDto
import com.tapmoay.sorders.data.remote.dto.ContactDto
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/**
 * 「下游定价」卡片的**纯逻辑**：一个人一行怎么分组、谁最终按哪个价算。
 *
 * ⚠️ 这里调的都是**产品代码里那个函数本身**（`personRows` / `effectiveUnitPrice` / `defaultPrice`），
 * 不是测试里再抄一份规则 —— 抄一份的后果是"测试全绿、产品坏了"，
 * 本仓库栽过这个跟头（见 `_tools/ai/_reverse_verify_all.py` 的由来）。
 */
class DownstreamPriceCardsTest {

    private fun contact(id: Long, name: String = "客户$id", phone: String = "1380000000$id") =
        ContactDto(id = id, displayName = name, phone = phone)

    /** contactId = null 的那一行 = 「全部下游的默认价」。 */
    private fun price(id: Long, contactId: Long?, unitPrice: String, deleted: Boolean = false) =
        ShipperPriceDto(
            id = id,
            productId = 7L,
            contactId = contactId,
            unitPrice = unitPrice,
            isDeleted = deleted,
        )

    // ---------------- 谁按哪个价算 ----------------

    @Test
    fun `没单独定过价的人按默认价算`() {
        val prices = listOf(price(1, null, "18"), price(2, 21L, "16.5"))
        assertEquals("18", effectiveUnitPrice(prices, 22L))
    }

    @Test
    fun `自己那条在用价优先于默认价`() {
        val prices = listOf(price(1, null, "18"), price(2, 21L, "16.5"))
        assertEquals("16.5", effectiveUnitPrice(prices, 21L))
    }

    @Test
    fun `回收站里那条不算价_掉回默认价`() {
        val prices = listOf(price(1, null, "18"), price(2, 21L, "16.5", deleted = true))
        // 软删 = 这条价不存在了；他要按默认价算，而不是"按 16.5 算"
        assertEquals("18", effectiveUnitPrice(prices, 21L))
    }

    @Test
    fun `默认价也在回收站里时谁都按不了_返回 null`() {
        val prices = listOf(price(1, null, "18", deleted = true))
        assertNull(effectiveUnitPrice(prices, 21L))
    }

    @Test
    fun `一个字都没定过的时候返回 null`() {
        assertNull(effectiveUnitPrice(emptyList(), 21L))
        assertNull(defaultPrice(emptyList()))
    }

    // ---------------- 一个人一行 ----------------

    @Test
    fun `名字空的用电话_电话也空的用编号`() {
        assertEquals("洪惠珍", personName(contact(21L, name = "洪惠珍")))
        assertEquals("13800000021", personName(contact(21L, name = "  ", phone = "13800000021")))
        assertEquals("联系人 21", personName(contact(21L, name = "", phone = " ")))
    }

    @Test
    fun `一个联系人一行_行序跟联系人列表一致`() {
        val rows = personRows(
            contacts = listOf(contact(22L, name = "乙"), contact(21L, name = "甲")),
            prices = listOf(price(1, null, "18"), price(2, 21L, "16.5")),
            includeDeleted = false,
        )
        assertEquals(listOf("乙", "甲"), rows.map { it.name })
        assertEquals(listOf(22L, 21L), rows.map { it.contactId })
        assertEquals("16.5", rows[1].price?.unitPrice)
        // 他自己在用的那条优先于默认价（18 只是"没单独定过价的人"的价）
        assertEquals("16.5", rows[1].effectiveUnitPrice)
        // 乙没单独定过价：他这一行不该挂着自己那条价，只按默认价算
        assertNull(rows[0].price)
        assertEquals("18", rows[0].effectiveUnitPrice)
    }

    @Test
    fun `看在用那一档时不挂回收站那条_切到回收站那一档才给恢复的入口`() {
        val prices = listOf(price(1, null, "18"), price(2, 21L, "16.5", deleted = true))
        val inUse = personRows(listOf(contact(21L)), prices, includeDeleted = false)
        // 「在用」那一档：软删的那条不挂在这一行上（这一行看起来就是"这个人还没单独定过价"），
        // 但他实际算的仍是默认价 —— 跟他现在按哪个价算一致。
        assertNull(inUse[0].price)
        assertEquals("18", inUse[0].effectiveUnitPrice)
        // 「回收站」那一档：那条还挂在这个人这一行上（不然「恢复」就没地方点了）。
        val trash = personRows(listOf(contact(21L)), prices, includeDeleted = true)
        assertEquals(2L, trash[0].price?.id)
        assertEquals(true, trash[0].price?.isDeleted)
        assertEquals("18", trash[0].effectiveUnitPrice)
    }

    @Test
    fun `联系人表里没有的那条价排在最后_不许悄悄消失`() {
        val dangling = ShipperPriceDto(
            id = 3,
            productId = 7L,
            contactId = 99L,
            unitPrice = "17",
            contactName = "旧客户",
            isDeleted = true,
        )
        val rows = personRows(listOf(contact(21L)), listOf(price(1, null, "18"), dangling), includeDeleted = true)
        assertEquals(listOf(21L, 99L), rows.map { it.contactId })
        assertEquals("旧客户", rows[1].name)
        assertEquals(1, deletedCount(listOf(price(1, null, "18"), dangling)))
    }

    @Test
    fun `两档的数字_在用按人算_回收站按行算`() {
        val prices = listOf(
            price(1, null, "18"),
            price(2, 21L, "16.5"),
            price(3, 22L, "17", deleted = true),
        )
        // 默认价那一行不算人头（它不是"某个人"的价）
        assertEquals(1, activePersonCount(prices))
        assertEquals(1, deletedCount(prices))
    }
}
