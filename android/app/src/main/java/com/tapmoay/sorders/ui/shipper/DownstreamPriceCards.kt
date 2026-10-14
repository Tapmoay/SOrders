package com.tapmoay.sorders.ui.shipper

import com.tapmoay.sorders.data.remote.api.ShipperPriceDto
import com.tapmoay.sorders.data.remote.dto.ContactDto

/**
 * 「下游定价」这一页的**纯逻辑**：把后端回的几行价按人分组、算出谁最终按哪个价算。
 *
 * 三条口径跟后端那一处保持一致：
 * 1. 一个人只认一条价（contact_id 相同的那条）；没单独定过价的人按「全部下游的默认价」算。
 * 2. 软删过的那条不算价（等于这条价不存在了）—— 但它在「回收站」那一档里还看得见、还恢复得回来。
 * 3. 默认价那一行的 contact_id 是 null，一个人只会有自己那一行，所以恢复不会跟谁撞车。
 *
 * ⚠️ 这里算出来的只是**给人看的那一个数**：真正的钱怎么算只有后端那一处，这一页一个数都不参与计算。
 */

/** 抽屉里一个人一行：名字、电话、他自己的那条价（null = 还没给他单独定过价）、他现在按哪个价算。 */
data class DownstreamPersonRow(
    val contactId: Long,
    val name: String,
    val phone: String,
    val price: ShipperPriceDto?,
    val effectiveUnitPrice: String?,
)

/** 「联系人 N」这种兜底名字 —— 名字空、电话也空的时候才用得上。 */
fun personName(contact: ContactDto): String =
    contact.displayName.ifBlank { contact.phone.ifBlank { "联系人 " + contact.id } }

/** 一件商品「全部下游的默认价」那一行；null = 还没设过默认价。 */
fun defaultPrice(prices: List<ShipperPriceDto>): ShipperPriceDto? =
    prices.firstOrNull { it.contactId == null }

/** 某个人自己的那条价（含回收站里躺着的那条）；null = 从来没给他定过价。 */
fun personPrice(prices: List<ShipperPriceDto>, contactId: Long): ShipperPriceDto? =
    prices.firstOrNull { it.contactId == contactId }

/**
 * 这个人现在实际按哪个价算：他自己在用的那条优先，没有就落到默认价，两个都没有 = null。
 *
 * 回收站里那条**不算**（软删了就等于没有），所以他会掉回默认价那一档 —— 跟页首那句
 * 「不填的人按默认价算」是同一件事。
 */
fun effectiveUnitPrice(prices: List<ShipperPriceDto>, contactId: Long): String? {
    val own = personPrice(prices, contactId)
    if (own != null && !own.isDeleted) return own.unitPrice
    val fallback = defaultPrice(prices)
    return if (fallback != null && !fallback.isDeleted) fallback.unitPrice else null
}

/** 在用的人头数（按人算，不看回收站）—— 抽屉上「在用」那一档的数字。 */
fun activePersonCount(prices: List<ShipperPriceDto>): Int =
    prices.count { it.contactId != null && !it.isDeleted }

/** 回收站里躺着几条价 —— 抽屉上「回收站」那一档的数字。 */
fun deletedCount(prices: List<ShipperPriceDto>): Int = prices.count { it.isDeleted }

/**
 * 输入框草稿格的键：**商品编号 + 人**（默认价那一行用 [SHIPPER_PRICE_DEFAULT_KEY]）。
 *
 * ⛔ 键里必须带商品编号：只按人存的话，A 商品打了一半的字会跑到 B 商品的框里去，
 *    而用户以为那就是 B 的价。
 */
fun draftKeyOf(productId: Long, contactId: Long?): String =
    productId.toString() + ":" + (contactId ?: SHIPPER_PRICE_DEFAULT_KEY)

/**
 * 抽屉里怎么排：一个联系人一行，**行序跟联系人列表一模一样**（存完价行不会跳走，
 * 跳走的话用户得重新找自己刚改的那一行）。
 *
 * - [includeDeleted] = true（看「回收站」那一档）时，软删的那条**仍挂在这个人这一行上**：
 *   「恢复」的入口就在这一档里，切走就没地方点了。
 * - [includeDeleted] = false（看「在用」那一档）时，软删的那条不挂在这一行上（这一行看起来就是
 *   "这个人还没单独定过价"），但他**算的仍是默认价** —— 跟他现在实际按哪个价算一致。
 * - 联系人里已经没有、后端却还回了价的人（人删了/改过）**排在最后**：
 *   这一页不显示无主价，但也不许它悄悄消失（回收站里能看到、能恢复）。
 */
fun personRows(
    contacts: List<ContactDto>,
    prices: List<ShipperPriceDto>,
    includeDeleted: Boolean,
): List<DownstreamPersonRow> {
    val known = contacts.map { it.id }.toSet()
    val rows = contacts.map { contact ->
        val own = personPrice(prices, contact.id)
        val shown = if (own != null && (includeDeleted || !own.isDeleted)) own else null
        DownstreamPersonRow(
            contactId = contact.id,
            name = personName(contact),
            phone = contact.phone,
            price = shown,
            effectiveUnitPrice = effectiveUnitPrice(prices, contact.id),
        )
    }
    val orphans = prices
        .filter { it.contactId != null && it.contactId !in known }
        .filter { includeDeleted || !it.isDeleted }
        .map { price ->
            DownstreamPersonRow(
                contactId = price.contactId!!,
                name = price.contactName.orEmpty().ifBlank { "联系人 " + price.contactId },
                phone = "",
                price = price,
                effectiveUnitPrice = effectiveUnitPrice(prices, price.contactId!!),
            )
        }
    return rows + orphans
}
