package com.tapmoay.sorders.ai

/**
 * **我的下游价**——批发商给自己卖的商品定下游价（CHG-0084 / 台账 L-53，2026-10-08）。
 *
 * ## 这三条动的是"我卖给下游该收多少钱"，不是公司那本账
 * | 动作 | 后端 | 落什么 |
 * | --- | --- | --- |
 * | [AiWrites.SHIPPER_PRICE_SET] | `POST /shipper-prices` | 设 / 改一条下游价（表 `shipper_prices`） |
 * | [AiWrites.SHIPPER_PRICE_DELETE] | `DELETE /shipper-prices/{id}` | 把那一条**软删** |
 * | [AiWrites.SHIPPER_PRICE_RESTORE] | `POST /shipper-prices/{id}/restore` | 把那一条放回来（撤回专用） |
 *
 * ## ⛔ 历史订单永不追改（卡片上要主动说出来，不能等用户问）
 * 这一层价只在下单那一刻定格到 `order_products.shipper_unit_price`
 * （`backend/app/services/shipper_price.py::snapshot_order_lines`：**只填 NULL**、老单永不追改、
 * 没定过价的行**不写 0**）。所以改价 / 删价**只影响以后新下的单**——用户最怕的就是
 * "我改个价，之前的账跟着变了"，那两句必须写在卡片明细里。
 *
 * ## ⛔ 也不碰公司那本账
 * 下游应收按订单行上的快照算（`backend/app/services/money_contract.py:211`），他欠公司的钱走
 * 另一本账。卡片上那句「这只动你自己那一本下游账，公司那边的账不受影响」与核销那几条同一句。
 *
 * ## 只有**批发商货主**有这本账（`memberOnly = true`）
 * 后端这三条都要 `Permission.SHIPPER_PRICE_MANAGE`，而 `backend/app/core/rbac.py:91` 把它
 * 只给了 shipper 那一格、scope 是 **own**（行级过滤按 `shipper_id`）；`shipper_prices.py`
 * 里**根本没有 `shipper_id` 入参**，写的永远是 `current.id` ⇒ **派单员不代设**。
 * 处理器里那句 `requireMemberShipper(ds)` 仍然留着：清单是第一道门，**执行是最后一道**。
 */
object AiWriteMyPrices {

    val ACTIONS: List<AiWriteAction> = listOf(
        AiWriteAction(
            id = AiWrites.SHIPPER_PRICE_SET,
            title = "给下游定个价",
            // MEDIUM：改的是"以后每一单按什么价算"，写错了必须能纠正（说一句改回去 / 删掉那条价）。
            risk = AiWriteRisk.MEDIUM,
            group = AiWrites.G_MY_PRICE,
            blurb = "给我自己卖的商品定一个下游价：可以只给某一位下游联系人定，也可以定成这个商品对" +
                "所有下游的默认价；同一个商品 + 同一个下游只有一条价，再定一次就是改。只影响以后新下的单" +
                "（已经下过的单按当时的价定格，一分不动），公司那边的账也不受影响。",
            params = listOf(
                AiWriteParam(
                    name = "product",
                    cn = "商品",
                    required = true,
                    hint = "要定价的商品名（只能是可定价商品：我自己下过单的、或派单员给我设过专属价的）",
                ),
                AiWriteParam(
                    name = "contact",
                    cn = "下游联系人",
                    hint = "可选。只给某一位下游定就写他的名字或手机号；不写 = 这个商品对所有下游的默认价",
                ),
                AiWriteParam(
                    name = "price",
                    cn = "单价（元）",
                    required = true,
                    kind = AiWriteParamKind.NUMBER,
                    hint = "这个商品给下游的价（元），例如 8.5，必须大于 0",
                ),
            ),
            memberOnly = true,
        ),
        AiWriteAction(
            id = AiWrites.SHIPPER_PRICE_DELETE,
            title = "删掉一条下游价",
            risk = AiWriteRisk.MEDIUM,
            group = AiWrites.G_MY_PRICE,
            blurb = "把某一条下游价删掉（后台是伪装删除：行还在，随时能恢复）。删掉之后那一档回落" +
                "这个商品的默认价（没有默认价就按订单行单价算）；只影响以后新下的单。",
            params = listOf(
                AiWriteParam(name = "product", cn = "商品", required = true, hint = "要删的那条价是哪个商品"),
                AiWriteParam(
                    name = "contact",
                    cn = "下游联系人",
                    hint = "可选。删的是只给某一位下游定的那条价；不写 = 删这个商品的默认价",
                ),
                AiWriteParam(name = "price", cn = "单价（元）", hint = "可选。同一个商品有多条价时用它指认是哪一条"),
            ),
            memberOnly = true,
        ),
        // 恢复：**撤回专用**（`undoOnly`）——被软删的那一条已经不在价目表里，按商品 / 联系人都
        // 解析不到它（[AiWriteAction.undoOnly] 的注释讲的就是这条），而撤回路径手里拿着**确定的编号**。
        restoreAction(
            cn = "下游价",
            id = AiWrites.SHIPPER_PRICE_RESTORE,
            group = AiWrites.G_MY_PRICE,
            memberOnly = true,
            call = { ds, id -> ds.restoreMyPrice(id) },
        ),
    )
}

/**
 * 「我能定价的商品」一条（`GET /shipper-prices/products`）。
 *
 * 为什么不用 [AiName]：定价卡片要写清"上游给我的价是多少、我自己定的默认价是多少"——那是用户
 * 判断"这个价我能不能定"的唯一依据（与批量调价要先把价格现状算给用户看是同一条理由）。
 */
data class AiMyPriceProduct(
    val id: Long,
    val name: String,
    /** 上游（公司 / 派单员）给他的价；后端也允许一个都没有 = null。 */
    val supplyPrice: String?,
    /** 他给**全部**下游定的默认价（没定过 = null ⇒ 下单时快照留空、回落订单行单价）。 */
    val defaultPrice: String?,
    /** 他已经单独定过价的联系人数（后端算好的）。 */
    val contactPriceCount: Int,
)

/**
 * 价目表上的一条（`GET /shipper-prices`）。
 *
 * `contactId == null` 就是那个商品的**默认价**（对所有下游生效）——卡片文案要按这一档分叉：
 * 删默认价与删某个人的专属价，**回落的那一档不一样**（`shipper_prices.py:289-291` 写死的口径）。
 */
data class AiMyPriceRef(
    val id: Long,
    val productId: Long,
    val productName: String,
    val contactId: Long?,
    val contactName: String?,
    /** 单价（后端下发的字符串，展示前一律走 [AiWriteArgs.moneyText]）。 */
    val unitPrice: String,
    /** true = 软删过的行（只在 `includeDeleted = true` 时出现）。 */
    val isDeleted: Boolean = false,
)
