package com.tapmoay.sorders.ai

import java.math.BigDecimal
import java.math.RoundingMode

/**
 * 「这件货对**这个货主**是多少钱」—— AI 这条路上**唯一一处**报价口径。
 *
 * ## 为什么必须有它（2026-09-22 查出来的真缺陷）
 * 用户定的规则只有一条（原话）：
 * > 「只要是商品的价格都跟他货主配置的价格进行绑定……如果派单员没有做任何的改动的话，
 * >   那就是默认的价格；如果派单员给批发商做了一些价格调整的话，那就是走他们自己的那个预设好的价格。」
 *
 * 而这个绑定**没有任何后端兜底**：`api/v1/order_products.py::create_order_product` 直接收
 * `body.unit_price`，`services/order_flow.py::build_order_products` 同理 —— 也就是说
 * **绑价全是客户端责任**。界面那一半在 569a23d 修过（`OrderCreateViewModel.priceFor` /
 * `LedgerCreateScreen.priceFor`：专属价优先、`priceRulesShipper` 对不上就回退默认价、
 * 价格未知时挡住下单）。**AI 那一半一直没修**：
 *
 * | 路 | 原来的做法 | 后果 |
 * |---|---|---|
 * | `orders.create` | `lines[].unit_price` 必填，模型自己编一个价 | 批发商谈好 10 元，AI 建出来的单按 20 元 |
 * | `orders.add_line` | 没给价就取**商品库默认价**（这个单的货主是谁根本没看） | 同上 |
 * | `ledger.create_entry` | `unit_price` 必填、同样不绑 | 账本记的价与这个货主的实际价对不上 |
 *
 * ## 分工（⛔ 别在这里再抄一份价）
 * - **只读**：专属价来自 `ds.priceRuleRows()`、商品默认价来自 `ds.productPrices()`；
 * - **只在一处**做"专属价优先、否则默认价"这个判断（就是本文件的 [of]）；
 * - 卡片文案由 [mismatchNote] 统一给，免得三个处理器各写一句、口径又走散。
 *
 * ⚠️ 构造器是 `internal`（不是 `private`）：单测要能直接摆一份"专属价 + 默认价"进来验
 *    「专属价优先」「不知道价时返回 null」这几条 —— 而这几条正是**钱算错与否**的分界，
 *    必须有单测钉着（`AiPriceBasisTest`）。
 */
internal class AiPriceBasis internal constructor(
    private val special: Map<Pair<Long, Long>, BigDecimal>,
    private val defaults: Map<Long, BigDecimal>,
) {

    /**
     * 一个价 + **它是从哪来的**。
     *
     * 为什么"从哪来的"必须跟着一起传：卡片上只写「单价 10 元」时，用户没法判断
     * 这 10 元是"他谈好的专属价"还是"商品库默认价"——而那正是他要核对的东西。
     */
    internal data class Price(val value: BigDecimal, val fromSpecial: Boolean) {

        /**
         * **值**就是 [value] 本身：它从 [of] 出来时已经是两位小数
         * （[moneyOf] 归一到 `setScale(2)`），处理器的 payload 直接 `value.toPlainString()`。
         *
         * ⛔ 这里**故意没有**一个"给我值口径字符串"的属性：有了它就会出现
         *    「这个属性是值、那个属性是显示」的第二份口径，而全 App 的分工本来就是
         *    `AiWriteArgs.money`（值）与 [display]／`moneyText`（显示）两件事 —— 那两份实现都在别处。
         */

        /** **显示**口径（卡片文字）：去掉末尾多余的 0。 */
        val display: String get() = AiWriteArgs.moneyText(value)

        /** 卡片上那句"是哪一种价"（单价那一行还放得下，所以写全）。 */
        val basisCn: String get() = if (fromSpecial) "这个货主的专属价" else "商品库的默认价"

        /** 同上，**短写**（只给 [mismatchNote] 那种已经写不下的一行用）。 */
        val basisCnShort: String get() = if (fromSpecial) "专属价" else "默认价"
    }

    /**
     * 这个货主（`null` = 认不出人／临时货主：没有专属价可言，只能看默认价）这件货的生效价。
     *
     * 两边都没有 → `null`，意思是**不知道价**。⛔ 调用方这时**不许猜**：
     * 要按老规矩去问用户要一个价（宁可多问一句，也不要按一个编出来的数建单）。
     */
    fun of(shipperId: Long?, productId: Long): Price? {
        if (shipperId != null) {
            special[shipperId to productId]?.let { return Price(it, fromSpecial = true) }
        }
        return defaults[productId]?.let { Price(it, fromSpecial = false) }
    }

    /**
     * 用户/模型**点名给了一个价**时，与系统价不一致要说的话；一致（或系统价未知）返回 null。
     *
     * ### 为什么是"提示"而不是"拒绝"
     * 派单员当场改价是**真实业务**（"这单按 8 块算"、"这批便宜 5 毛"），拒绝了就没法干活。
     * 但模型也完全可能只是**没查专属价**就照着商品库默认价填了一个数 —— 这两件事从参数上分不出来，
     * 所以卡片必须把**系统价本身**摆出来，用户扫一眼就能说"不对，是 10 块"。
     *
     * ⚠️ 这句话同时是给**模型**看的：它写明了"先跟用户核对"，模型据此回头问一句，
     *    而不是默默按自己填的数建单。
     *
     * ⚠️ **长度是有预算的**（2026-09-22 真机截图抓到的）：卡片明细区是
     *    `heightIn(max = 200.dp)` + 内部滚动（见 `AiChatScreen.CardInfoTable` 的调用点），
     *    这张卡本来就有 5 行（货主/日期/商品明细/货/合计）。第一版这句话有 3 行，
     *    整块内容顶到 ~210dp → **最后一行被切掉半行**（用户会以为卡片坏了）。
     *    所以：**只写两个数和"去核对"**，那两种价的说明用短写（[Price.basisCnShort]）。
     */
    fun mismatchNote(typed: BigDecimal, system: Price?): String? {
        if (system == null) return null
        if (typed.compareTo(system.value) == 0) return null
        return "⚠️ 这个货主的价是 ${system.display} 元（${system.basisCnShort}），" +
            "卡上按 ${AiWriteArgs.moneyText(typed)} 元算 —— 没让你改价就先跟用户核对按哪个"
    }

    companion object {
        /**
         * 拉一次、用一整张卡（最多 10 行商品都查这一份）。
         *
         * ⚠️ 两个名册都是**现拉**（不缓存）：专属价刚被改过、商品刚建出来都要立刻生效 ——
         *    缓存会让"刚调完价，AI 还按旧价报"这种最难查的不一致多一个来源。
         */
        suspend fun load(ds: AiWriteDataSource): AiPriceBasis {
            val special = HashMap<Pair<Long, Long>, BigDecimal>()
            for (r in ds.priceRuleRows()) {
                moneyOf(r.price)?.let { special[r.shipperId to r.productId] = it }
            }
            val defaults = HashMap<Long, BigDecimal>()
            for (p in ds.productPrices()) {
                moneyOf(p.defaultPrice)?.let { defaults[p.id] = it }
            }
            return AiPriceBasis(special, defaults)
        }

        /**
         * 后端下发的金额字符串 → 两位小数的数。
         *
         * 读不出来（空串/不是数字）当作**没有这个价**，而不是 0：0 会被当成"这件货不要钱"，
         * 那个后果比"不知道价"严重得多。
         *
         * ⚠️ `internal`（不是 private）只为单测：[AiPriceBasisTest] 要直接钉住
         *    「空串 / 非数字 → null，绝不是 0」这一条 —— 它是"钱算错"与"不知道"的分界。
         */
        internal fun moneyOf(raw: String): BigDecimal? =
            raw.trim().takeIf { it.isNotEmpty() }
                ?.toBigDecimalOrNull()
                ?.setScale(2, RoundingMode.HALF_UP)
    }
}
