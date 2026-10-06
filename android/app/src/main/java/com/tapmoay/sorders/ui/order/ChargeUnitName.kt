package com.tapmoay.sorders.ui.order

/**
 * # 点「挂账」时，那个"新建单位"的框该预填什么名字（台账 L-29）
 *
 * 用户口述（m01072）：
 * > 「我们这个**挂账**啊：假如有个订单，他**没有**新的挂账单位，我们**直接点击挂账**的话是
 * >  **自动给他添加挂账单位的**……所以这个就直接**自动化**吧，**不要我到那个"选择挂账单位"
 * >  那里去选择**。……如果他点击新建挂账单位的话，那就**直接按着他对应的名字进行挂账** ——
 * >  如果是按照**下单人**来进行挂账的；如果**没有下单人、只有收货人**，那就按**收货人**来进行挂账。」
 *
 * m01132 定稿：**预填名字 + 让他看一眼再确认**（用户否决了"点一下直接挂上"：
 * 「可以直接（填）名字……他**可以看一眼再确认**」）—— 所以这里只算"该填什么"，
 * ⛔ 不许在这里替用户按下确认。
 *
 * ## 为什么单独一个文件
 * 「下单人 → 收货人」这条回退与账本页那条 [com.tapmoay.sorders.ui.shipper.customerNameOf]
 * 是**同一个意思**（先认下单的人、没有再认接货的人），但**不能复用**它：
 * 那条问的是"这一笔记在谁头上"（第三个兜底是「未指定货主」），这条问的是"给新单位起什么名字"
 * （没有兜底，两个都空就留空让用户自己写）。混在一起的后果是**挂账单位叫「未指定货主」**。
 */

/**
 * 「新建挂账单位」框里预填的名字：**下单人 → 收货人 → 空**。
 *
 * ⚠️ 只去首尾空白（与后端 `find_or_create_unit` 的 `raw_name.strip()` 同一口径）；
 * 空档不编名字（⛔ 编出来的名字会把欠款记到一个不存在的单位头上）。
 */
fun defaultArrearsUnitName(ordererName: String?, receiverName: String?): String =
    ordererName.orEmpty().trim().ifBlank { receiverName.orEmpty().trim() }

/**
 * 用户打的名字与名册里某个名字**很像但不是同一个** ⇒ 返回名册里那一个（用来提示）；否则 `null`。
 *
 * 用户 m01132 原话：「名字很像但不同，比如说**打了一个空格**，这个**要提示**」。
 * 两种情况：**都只差空白**（`永盛 食品` vs `永盛食品` —— 后端只 strip 首尾，中间那个空格
 * 会让它变成**第二个单位**，而用户以为自己填的是同一家），
 * 或**只差一个字**且长度相同（`文天祥` vs `文天翔`，长度 ≥ 2）。
 *
 * ⛔ 判据只此一处（界面不许自己再写一套模糊匹配）：宽了会天天弹提示（用户就不看了），
 * 窄了等于没有 —— 所以刻意**不做**前缀/包含匹配（「永盛」与「永盛食品厂」可能是两家）。
 *
 * @param candidate 用户正在输入的名字（会自己做 trim）。
 * @param existing 名册里已有的名字（`arrearsUnits` 的 `name`）。完全同名的**不算相近**：
 *   那种情况后端会直接复用，不是"要提示"的场景。
 */
fun similarArrearsUnitName(candidate: String, existing: List<String>): String? {
    val c = candidate.trim()
    if (c.isEmpty()) return null
    val squashed = c.filterNot { it.isWhitespace() }
    return existing.firstOrNull { raw ->
        val other = raw.trim()
        if (other.isEmpty() || other == c) return@firstOrNull false
        val os = other.filterNot { it.isWhitespace() }
        os == squashed || (os.length == squashed.length && os.length >= 2 && differByOne(os, squashed))
    }
}

/** 两个**等长**字符串是否只差一个字符。 */
private fun differByOne(a: String, b: String): Boolean {
    var diff = 0
    for (i in a.indices) {
        if (a[i] != b[i] && ++diff > 1) return false
    }
    return diff == 1
}
