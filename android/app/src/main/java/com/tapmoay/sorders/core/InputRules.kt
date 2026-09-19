package com.tapmoay.sorders.core

/**
 * 输入框的通用规则 —— **唯一实现处**。
 *
 * ## 为什么要有这个文件
 * 用户 2026-09-19 的原话：「我在下单的时候，它不是要填电话号码吗？这个电话号码只能填数字，
 * 而且必须填正确的格式，它是不能填字母和文字的。包括其他类似的这样子都要做相应的限制」。
 *
 * 这不是"用户没想到"的问题，是**生产库里真的躺着脏数据**（改之前查过）：
 * - `orders.contact_dongjia_phone` 有 6 行是 `嘿嘿` `嘻嘻` `问问` `刚刚好` —— 中文进了电话字段，
 *   **司机拿到这单根本没法打电话**，而且下单时没有任何提示；
 * - `shipper_contacts` 有一条 `222`；
 * - 金额输入框用的是 `it.filter { c -> c.isDigit() || c == '.' }`，能敲出 `1.2.3` 与 `...`，
 *   它们 `toDoubleOrNull()` 得到 null，界面上小计变 ¥0.00、提交后靠后端 422 兜底。
 *
 * 这些字段有一个共同点：**它们能表达的内容本来就有边界**（电话是数字、金额只有两位小数），
 * 而当时的代码把这个边界留给了用户去遵守。所以要有一处**唯一的**实现，让所有输入框都走它。
 *
 * ## 两条纪律
 * 1. **过滤 + 校验都要**。过滤（[mobileInput] 等）让非法字符根本敲不进去 —— 这是"不能填字母"
 *    那一半；校验（[mobileError] 等）负责"位数对不对" —— 光过滤挡不住"138"，光校验
 *    挡不住"嘿嘿"（虽然也能拦，但用户要的是敲不进去）。
 * 2. **不在调用点手写过滤**。任何一个 `onValueChange = { x = it.filter { ... } }` 都是
 *    这条规则的一个副本，改的时候一定会漏掉一个。`_tools/qa/_check_input_rules.py`
 *    会把这种手写过滤与"电话/金额字段没走 InputRules"都报出来。
 *
 * ## 这个文件**不依赖 Android**
 * 纯 Kotlin（只用了 `Char.isDigit`），所以能在 `app/src/test/` 里直接跑单测 ——
 * 规则本身不能靠模拟器点出来。`InputRulesTest` 盯着每一条。
 */
object InputRules {

    /**
     * 一个字符 → ASCII 数字（不是数字则 null）。**全角数字归一成半角，而不是丢掉。**
     *
     * ## 为什么不能写 `it.isDigit()`
     * Kotlin 的 `Char.isDigit()` 是 **Unicode** 判断：全角数字 `１２３` 它也算"数字"。
     * 于是一个用全角数字敲出来的"手机号"能一路通过 App 的过滤，而**后端的 `\d` 在
     * Python 里同样是 Unicode 的**（`re.match(r"^1\d{10}$", "1３８０００００００")` 会匹配），
     * 结果是一个**长得像手机号、但谁也没法照着拨**的登录账号。
     * （这条是写单测时被抓出来的：第一版用 `isDigit()`，断言 `１３８` 要变成空串，结果原样返回。）
     *
     * ## 为什么是"归一"而不是"丢掉"
     * 全角数字的来源很具体：中文输入法在**全角模式**下打出来的就是它们。用户不是想输垃圾，
     * 是输入法状态不对 —— 丢掉等于让他对着一个"明明打了却没进去"的框发愣。
     * 第一版就是丢掉的，单测立刻暴露了一个荒唐结果：`moneyInput("１.５")` 只剩一个 ASCII 点儿，
     * 算出 `0.`（想输 1.5，得到 0）。归一之后 `１.５` → `1.5`。
     * 只映射 U+FF10~U+FF19（全角）这一段：别的 Unicode 数字（阿拉伯-印度数字等）
     * 与这个用户群无关，硬认反而会把莫名其妙的字符转成号码。
     */
    private fun asciiDigit(c: Char): Char? = when (c) {
        in '0'..'9' -> c
        // `c - '０'` 是 Int（两个 Char 相减 = 码位差），再加回 ASCII 的 '0'
        in '０'..'９' -> '0' + (c - '０')
        else -> null
    }

    /**
     * 只留 ASCII 数字 + 去掉国际写法里的国家码 + 截断。手机号和联系电话共用这一份。
     *
     * ## 为什么要剥 `+86`
     * 用户从通讯录/微信里粘一个号码，很常见的形式是 `+86 138 0000 0000`。
     * 只做"留数字"的话它会变成 `86138000000` —— **11 位、看起来完全正常、
     * 但在联系电话那条规则（7~12 位）下会被放过去**，司机照着拨就是一个空号，
     * 而且**中间不会有任何提示**。所以国家码必须剥掉，不能只过滤字符。
     *
     * 只在"**正好 13 位且以 86 开头**"时剥：中国手机号带国家码就是 86 + 11 位 = 13 位，
     * 这个形状无歧义。刻意不写通用的国际号码解析（库号/分机/别的国家码都是另一个话题，
     * 猜错了比不猜更糟）—— 剥不掉的会留在框里被 [phoneError] / [mobileError] 挡下。
     */
    private fun digits(v: String, max: Int): String {
        val d = v.mapNotNull { asciiDigit(it) }.joinToString("")
        val stripped = if (d.length == 13 && d.startsWith("86")) d.substring(2) else d
        return stripped.take(max)
    }

    // ------------------------------------------------------------------ 手机号
    // 用在"这是登录账号"的地方（建账号 / 改账号 / 登录名）。中国手机号就是 11 位数字。

    /** 手机号位数（与后端 `^1\d{10}$` 是同一条规则的两端）。 */
    const val MOBILE_LEN = 11

    /** 手机号输入过滤：只留数字、最多 11 位（超位直接截断，敲不出字母）。 */
    fun mobileInput(v: String): String = digits(v, MOBILE_LEN)

    /** 手机号格式校验；null = 通过。[required] = false 时允许留空。 */
    fun mobileError(v: String, required: Boolean = true): String? = when {
        v.isBlank() -> if (required) "请填写手机号" else null
        v.length != MOBILE_LEN -> "手机号要填 $MOBILE_LEN 位数字（现在 ${v.length} 位）"
        !v.startsWith("1") -> "手机号要以 1 开头"
        else -> null
    }

    // ---------------------------------------------------------------- 联系电话
    // 用在"这是给司机打过去的电话"的地方：收货人电话、下单人电话、东家/老板电话、
    // 联系人电话、挂账单位电话、客户档案电话。
    //
    // ⚠️ 下限 7、上限 12 是**故意放宽**的：这里不只收手机号，也收座机。
    //    `01012345678`（区号 010 + 8 位）是合法的 11 位座机；`057188888888`
    //    （区号 0571 + 8 位）是 12 位。所以**不能**要求"11 位必须以 1 开头"——
    //    那条规则会把所有座机挡在门外，而门店/工厂留座机是常态。
    //    真正要挡住的是"嘿嘿""222"这种根本打不通的东西。

    /** 联系电话最短位数（座机连区号一起填）。 */
    const val PHONE_MIN = 7

    /** 联系电话最长位数。 */
    const val PHONE_MAX = 12

    /** 联系电话输入过滤：只留数字、最多 12 位。 */
    fun phoneInput(v: String): String = digits(v, PHONE_MAX)

    /**
     * 联系电话格式校验；null = 通过。[required] = false 时允许留空。
     *
     * 消息里带**实际位数**：用户看到"现在 3 位"就知道是自己少输了（而不是我们乱报错）。
     */
    fun phoneError(v: String, required: Boolean = false): String? = when {
        v.isBlank() -> if (required) "请填写电话" else null
        v.length < PHONE_MIN -> "电话太短（现在 ${v.length} 位，至少 $PHONE_MIN 位；座机请把区号一起填上）"
        else -> null
    }

    // -------------------------------------------------------------------- 金额
    // 用在单价 / 售价 / 成本价 / 收款金额 / 运费 / 工资 这些地方。

    /**
     * **金额**（收款/开销/运费/工资）的小数位数上限。
     *
     * 口径来自数据库列本身：这些列都是 `Numeric(12, 2)`
     * （`cash_flows.amount` / `expenses.amount` / `shipper_receipts.amount` /
     * `driver_bills.amount` / `orders.freight_fee` / `users.salary` / `freight_templates.fee`）。
     * 多打的小数位**存不进去**（MySQL 会四舍五入），所以拦在输入框上不是限制用户，
     * 而是别让他输一个"看着是 12.3456、存下去是 12.35"的数字。
     */
    const val MONEY_DECIMALS = 2

    /**
     * **单价**的小数位数上限 —— 比金额多两位，因为库里的单价列就是 4 位。
     *
     * ⚠️ 这条是 2026-09-19 差点改错的地方：第一版把**所有**金额框都收成两位小数，
     * 而 `products.default_unit_price` / `cost_price` / `special_unit_price`、
     * `order_products.unit_price`、`ledgers.unit_price` 都是 **`Numeric(14, 4)`** ——
     * 于是"给商品定 12.3456 元"这种本来能干的事**被悄悄封掉了**（用户只会发现
     * 打第四位小数打不进去）。**单价与金额不是同一条精度**，别合并。
     */
    const val PRICE_DECIMALS = 4

    /** 金额整数位数上限（8 位 = 最大 99999999 元，够用且能挡住手滑连按）。 */
    const val MONEY_WHOLE_DIGITS = 8

    /**
     * 金额输入过滤：只留 ASCII 数字，**最多一个小数点**，小数最多两位。
     *
     * 行为约定（都有单测）：
     * - `1.2.3` → `1.23`（多余的点儿当噪声丢掉，**不丢数字** —— 用户多半是手滑多按了一下点儿）；
     * - `.5` → `0.5`（补前导 0，否则 `toDoubleOrNull()` 也是 0.5，但显示与提交都不好看）；
     * - `1.` → `1.`（**允许停在点儿上**：用户正准备输小数，这时把它吃掉会让下一个数字跑到整数位）；
     * - 整数位超过 8 位 → 截断；
     * - 全角数字 `１.５` → 丢掉（理由见 [digits]：`isDigit()` 是 Unicode 判断）。
     */
    fun moneyInput(
        v: String,
        maxDecimals: Int = MONEY_DECIMALS,
        maxWhole: Int = MONEY_WHOLE_DIGITS,
    ): String {
        val cleaned = v.mapNotNull { c -> asciiDigit(c) ?: if (c == '.') '.' else null }.joinToString("")
        if (cleaned.isEmpty()) return ""
        val firstDot = cleaned.indexOf('.')
        if (firstDot < 0) return cleaned.take(maxWhole)
        val whole = cleaned.substring(0, firstDot).take(maxWhole).ifBlank { "0" }
        val frac = cleaned.substring(firstDot + 1).mapNotNull { asciiDigit(it) }.joinToString("").take(maxDecimals)
        return "$whole.$frac"
    }

    /** 金额格式校验；null = 通过。[required] = false 时允许留空。 */
    fun moneyError(v: String, required: Boolean = false): String? {
        if (v.isBlank()) return if (required) "请填写金额" else null
        val n = v.toDoubleOrNull() ?: return "金额只能填数字（最多 $MONEY_DECIMALS 位小数）"
        if (required && n == 0.0) return "金额要大于 0"
        return null
    }

    /**
     * **单价**输入过滤：与 [moneyInput] 同一条规则，只是小数位放到 [PRICE_DECIMALS]（4 位）。
     *
     * 用在"这是**每单位多少钱**"的地方：商品默认售价 / 成本价 / 批发价档位 /
     * 批发商特价 / 订单行的单价 / 账本流水单价 / 批量调价的统一单价。
     * 为什么它们与金额分开见 [PRICE_DECIMALS] 的注释（库里的列精度不同）。
     */
    fun priceInput(v: String): String = moneyInput(v, maxDecimals = PRICE_DECIMALS)

    // ------------------------------------------------------------------ 正整数
    // 用在数量 / 库存 / 低库存提醒 / 拆单份数这些地方。

    /** 正整数输入过滤：只留数字（全角归一成半角，见 [asciiDigit]）、最多 [maxLen] 位。 */
    fun intInput(v: String, maxLen: Int): String =
        v.mapNotNull { asciiDigit(it) }.joinToString("").take(maxLen)

    // -------------------------------------------------------------- 拆单份数
    // 用在「拆分订单」那个 `150/150` 的输入框。

    /** 拆单输入过滤：只留数字（全角归一）与 `/`，最多 [maxLen] 位。 */
    fun splitPartsInput(v: String, maxLen: Int = 24): String =
        v.mapNotNull { c -> asciiDigit(c) ?: if (c == '/') '/' else null }
            .joinToString("")
            .replace("//", "/")
            .take(maxLen)
}
