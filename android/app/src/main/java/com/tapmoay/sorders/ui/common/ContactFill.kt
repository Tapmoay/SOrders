package com.tapmoay.sorders.ui.common

/**
 * # 「收货人（联系人）两栏怎么被带出来」—— **全 App 唯一一份判据**
 *
 * 用户 2026-09-24 的原话：
 * > 「给户主也加一个在选择下单的时候**可以选择联系人**，就不用每次要手动填入了。同时再给他
 * >  添加个功能就是**可以通过地点来绑定联系人**，就大家选择地点之后，自动填入对应的联系人。…
 * >  我们的**派单员**，它也要具有这个功能，也可以通过**地点或者是线路**去绑定联系人。」
 *
 * 于是"收货人名称 / 收货人电话"这两栏有**四个**来源：手打、选联系人、选线路（`shipper_addresses`
 * 的 `receiver_name`/`phone`）、选地点（`shipper_locations` 的 `contact_name`/`contact_phone`）。
 * 四个来源各自的覆盖规矩如果各写一遍，一定会走散 —— 而走散的表现是**静默的**：
 * 用户刚敲好的名字被一次选点清掉、或者上一个人的电话留在这一单上（司机会打给错的人）。
 *
 * ## 两条规矩，**不是一条**（这是本文件存在的理由）
 *
 * | 模式 | 什么时候 | 规矩 |
 * |---|---|---|
 * | [ContactFillMode.BROUGHT] | 选地点 / 选线路时**顺带带出** | **有值才覆盖**：来值空着的那一栏，原样留着用户已经填的 |
 * | [ContactFillMode.PICKED] | 用户明确**挑了一个联系人** | **整对替换**（含清空）：挑的是"这个人"，只换一半会拼出一个不存在的人 |
 *
 * ⛔ 两条都别合并：带出用"整对替换"会**把用户刚填的名字抹掉**（他选地点只是为了填地址）；
 * 挑人用"有值才覆盖"更糟 —— 名册里那个人没写名字时，电话换了人、名字还是上一位的，
 * 而**界面上完全看不出来**（司机照着这个名字找到的是另一个人）。
 *
 * ## 与"线路带出"的既有行为的关系
 * `OrderCreateViewModel.applyAddress` 在 2026-09-22 就有自己的写法（名字"非空才覆盖"、电话"照搬"），
 * 且被红线（`_reverse_verify_contact_names.py` 与 `_check_contact_names.py` 的锚点）钉着。
 * 这一轮**不动它**：本轮新增的两个来源（选联系人 / 选地点）走这里，规矩写清楚、有单测；
 * 谁以后要把线路那一支也收进来，先看清上表第二行（"电话照搬"其实是 [ContactFillMode.PICKED] 那一档）。
 */
data class ReceiverContact(val name: String = "", val phone: String = "") {
    /** 两栏都空 = 这一单没有收货人信息（界面上就是两个空框）。 */
    val isBlank: Boolean get() = name.isBlank() && phone.isBlank()
}

/** 见 [fillReceiver] 的两条规矩。 */
enum class ContactFillMode {
    /** 选地点 / 选线路时**顺带带出**：有值才覆盖、空值不清空。 */
    BROUGHT,

    /** 明确挑了一个联系人：**整对替换**（那个人没写名字就是没写，不留上一位的）。 */
    PICKED,
}

/**
 * 把一次"来的人 / 来的地点"合并进当前那两栏 —— **唯一实现**。
 *
 * @param name / @param phone 来值（线路的 `receiver_name`/`phone`、地点的 `contact_name`/`contact_phone`、
 *   或名册里那位联系人的 `display_name`/`phone`）。null 与 `""`、纯空格都当"这个来源没给"。
 */
fun fillReceiver(
    current: ReceiverContact,
    name: String?,
    phone: String?,
    mode: ContactFillMode,
): ReceiverContact = when (mode) {
    ContactFillMode.BROUGHT -> ReceiverContact(
        name = name.orEmpty().trim().ifBlank { current.name },
        phone = phone.orEmpty().trim().ifBlank { current.phone },
    )
    // 整对替换：这一支刻意**不**看 current（挑的是那个人，不是"在现有基础上补一补"）
    ContactFillMode.PICKED -> ReceiverContact(
        name = name.orEmpty().trim(),
        phone = phone.orEmpty().trim(),
    )
}

/**
 * 「这一栏带不带得出联系人」—— 地点卡片上那行小字的判据（有联系人时写一行、没有就不占位）。
 *
 * 空串与纯空格都算没绑（后端两列的缺省值就是空串；老库补列之后的行也是空串）。
 */
fun hasBoundContact(name: String?, phone: String?): Boolean =
    !name.orEmpty().isBlank() || !phone.orEmpty().isBlank()

/**
 * 地点绑定的联系人怎么显示在一行里：**有名字写名字、没名字写电话**，两个都有就连起来。
 *
 * ⛔ 与订单卡片上「收货人 / 下单人」那一行的拼法（`OrderCard.kt::contactWho`）**故意不同**：
 * 那边是"人 + 电话都要看见"（派单员要照着拨号），这边是地点卡片上的一行摘要
 * （手机号本来就占宽度，两个都写会把这行的其余信息挤掉）。所以不合并成一处。
 */
fun boundContactLabel(name: String?, phone: String?): String {
    val n = name.orEmpty().trim()
    val p = phone.orEmpty().trim()
    return when {
        n.isNotEmpty() && p.isNotEmpty() -> "$n · $p"
        n.isNotEmpty() -> n
        else -> p
    }
}
