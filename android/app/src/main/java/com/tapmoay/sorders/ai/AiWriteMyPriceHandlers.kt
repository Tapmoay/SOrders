package com.tapmoay.sorders.ai

import java.math.BigDecimal
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.longOrNull
import kotlinx.serialization.json.put

/**
 * 「我的下游价」两条手写处理器：**定价**与**删价**（恢复走 [restoreAction] 那条声明式路）。
 *
 * ## 为什么这两条必须手写（不能走声明式 CRUD）
 * 1. 声明式那一套收的是"一条已有记录的编号 ＋ 要改的字段"，而这两条两头都要解析：
 *    **商品**得在他"可定价的商品"里认（`GET /shipper-prices/products`，后端只回
 *    "他下过单的 ∪ 派单员给他设过专属价的"）、**下游联系人**可选（留空 = 默认价那一档）；
 * 2. 定价卡片还要印出**原来的价**（"原来 8 元 → 现在 9 元"）：用户唯一能确认"我改对了没有"的
 *    东西就是这两个数，声明式拿不到；
 * 3. 删价要先按"商品 ＋ 下游"把那一行找出来（一个商品可能有好几条价：默认价 ＋ 给不同人的价）。
 *
 * ## 两条不许破的规矩（[AiWriteHandler] 的注释里也写着）
 * `prepare` 里**一个字都不许写后端**；`commit` 只认 `prepare` 造出来的 payload。
 * 所以"他现在的价是多少"是在 `prepare` 里读的，`commit` 拿着编号直接发。
 *
 * ## ⚠️ 这本账**只有批发商货主**有
 * 后端三道闸（`backend/app/api/v1/shipper_prices.py:27-38`）：权限点 `shipper_price:manage`
 * ＋ `_require_member`（是不是批发商货主）＋ `_require_downstream`（有没有把下游这本账关掉）。
 * 中间那道在 `prepare` 里如实拦一次（两种货主是**同一个角色**，角色门分不出来）。
 * 第三道（关掉下游账）**这里拦不到**：那是全店的一个开关，手机端要多读一次 `users.downstream_ledger_enabled`
 * 才看得见；真关掉时后端给的是 403 ＋ 一句中文出路，而手机上没有这一段入口、用户也不会来问。
 */

/** 卡片上"这一下动了谁的账"那一段的分隔线（两条动作共用一份，免得两张卡各说各的）。 */
private const val AT_WHO = "———— 这一下动了谁的账 ————"

/** 两张卡上都必须有的那句话：这本账是**他自己的**。 */
private const val DOWNSTREAM_LINES_NOTE =
    "只动你自己那一本下游账：公司（派单员）那边的账一个数字都不会变"

/** 定价：`POST /shipper-prices`（有就改、没有就建；**软删过的那一行会复活**）。 */
class SetMyPriceHandler(
    private val ds: AiWriteDataSource,
    private val store: AiWritePreviewStore,
) : AiWriteHandler {

    override val actionId = AiWrites.SHIPPER_PRICE_SET

    override suspend fun prepare(params: JsonObject): AiWriteOutcome {
        requireMemberShipper(ds)

        val products = ds.myPriceProducts()
        if (products.isEmpty()) {
            throw AiWriteArgException(
                "你这本下游价目表现在一个商品都没有（只能给自己下过单的、或派单员给你设过专属价的" +
                    "商品定价）——先下一单，或者让派单员给你设个价。",
            )
        }
        val rawProduct = AiWriteArgs.required(params, "product", "要给哪个商品定价？说商品名就行。")
        val product = AiWriteArgs.strict(rawProduct, products.map { AiName(it.id, it.name) }, "商品")
            ?: throw AiWriteArgException("没认出「${rawProduct}」是哪个商品，请让用户说准确一点。")

        // 商品那一行（上游给他的价 / 他自己的默认价 / 已单独定价的联系人数）——strict 只回名字，
        // 这三项要回原表里按编号取。
        val row = products.firstOrNull { it.id == product.id }

        val contact = resolveDownstreamContact(ds, params)
        val price = AiWriteArgs.parseMoney(AiWriteArgs.str(params, "price"), "单价", mustPositive = true)
        val priceText = AiWriteArgs.moneyText(price)

        // ⚠️ 连回收站里的一起读：后端"再设一次"是**复活软删那一行**（`shipper_price.py::find_row`
        //    故意不过滤 is_deleted），卡片上要如实说"这次会把它复活"，而不是"新建一条"。
        val same = ds.myPrices(includeDeleted = true)
            .filter { it.productId == product.id && it.contactId == contact?.id }
        val existing = same.firstOrNull { !it.isDeleted }
        val revived = if (existing == null) same.firstOrNull { it.isDeleted } else null

        val who = contact?.label ?: "所有下游"
        return AiWriteOutcome.NeedConfirm(
            store.card(
                actionId,
                summary = "下游价：${product.label} → ${priceText} 元（${who}）",
                detailLines = buildList {
                    add("商品：${product.label}")
                    add(
                        if (contact == null) "给谁：所有下游（这是默认价，没单独定价的人都按它算）"
                        else "给谁：${contact.label}（只对他生效，并且盖过默认价）",
                    )
                    when {
                        existing != null -> add(
                            "原来：${AiWriteArgs.moneyText(existing.unitPrice)} 元 → 现在：${priceText} 元" +
                                "（这一档已经有一条价了，这次是改，不是新建）",
                        )
                        revived != null -> add(
                            "原来：这一档有一条被删掉的价（${AiWriteArgs.moneyText(revived.unitPrice)} 元）" +
                                " → 现在：${priceText} 元（后台会把它复活——不是新建一条）",
                        )
                        else -> add("原来：这一档还没有定过价 → 现在：${priceText} 元")
                    }
                    if (contact != null) {
                        val d = row?.defaultPrice
                        add(
                            if (d == null) "参考：这个商品还没有默认价（他如果没有单独价，就按订单行单价算）"
                            else "参考：这个商品的默认价是 ${AiWriteArgs.moneyText(d)} 元",
                        )
                    }
                    val cnt = row?.contactPriceCount ?: 0
                    if (cnt > 0) {
                        add("参考：这个商品你已经单独给 ${cnt} 个下游定过价")
                    }
                    add(AT_WHO)
                    add("这个价只管以后新下的单：已经下过的单按当时的价定格，一个字节都不动")
                    add(DOWNSTREAM_LINES_NOTE)
                },
                payload = buildJsonObject {
                    put("product_id", product.id)
                    put("product", product.label)
                    put("unit_price", AiWriteArgs.money(price))
                    contact?.let { c ->
                        put("contact_id", c.id)
                        put("contact", c.label)
                    }
                },
            ),
        )
    }

    override suspend fun commit(payload: JsonObject, idempotencyKey: String) {
        ds.setMyPrice(
            productId = payload.reqLong("product_id"),
            contactId = payload["contact_id"]?.jsonPrimitive?.longOrNull,
            unitPrice = payload.req("unit_price"),
        )
    }
}

/** 删价：`DELETE /shipper-prices/{price_id}`（软删；执行完这条消息上会出现「撤回」把同一行原样放回来）。 */
class DeleteMyPriceHandler(
    private val ds: AiWriteDataSource,
    private val store: AiWritePreviewStore,
) : AiWriteHandler {

    override val actionId = AiWrites.SHIPPER_PRICE_DELETE

    override suspend fun prepare(params: JsonObject): AiWriteOutcome {
        requireMemberShipper(ds)

        // 只认**没被删掉**的行：回收站里那些已经"删过了"，再删一次后端会因为条件 UPDATE
        // （`WHERE is_deleted = 0`）命中 0 行而报错（`shipper_prices.py:293-295`）——那是白让用户点一次确认。
        val all = ds.myPrices()
        if (all.isEmpty()) {
            throw AiWriteArgException("你这本下游价目表现在一条价都没有，没有可删的。")
        }
        // 商品名册直接取"价目表上有价的那些商品"：删价只跟这本账有关，
        // 拿"可定价商品"当名册的话，商品已经不在可定价范围时反而删不掉（少一条出路）。
        val rawProduct = AiWriteArgs.required(params, "product", "要删掉哪个商品的价？说商品名就行。")
        val product = AiWriteArgs.strict(
            rawProduct,
            all.distinctBy { it.productId }.map { AiName(it.productId, it.productName) },
            "商品",
        ) ?: throw AiWriteArgException("没认出「${rawProduct}」是哪个商品，请让用户说准确一点。")

        val contact = resolveDownstreamContact(ds, params)
        val cands = all.filter { it.productId == product.id && it.contactId == contact?.id }
        val who = contact?.label ?: "所有下游"
        if (cands.isEmpty()) {
            throw AiWriteArgException(
                if (contact == null) {
                    "「${product.label}」没有定过默认价（没单独定价的人现在按订单行单价算），没有可删的价。"
                } else {
                    "「${product.label}」在「${contact.label}」那里没有单独定过价（他按默认价算），没有可删的价。"
                },
            )
        }
        val row = if (cands.size == 1) cands.first() else pickByPriceArg(params, product.label, who, cands)

        return AiWriteOutcome.NeedConfirm(
            store.card(
                actionId,
                summary = "删掉下游价：${product.label} → ${AiWriteArgs.moneyText(row.unitPrice)} 元（${who}）",
                detailLines = listOf(
                    "商品：${product.label}",
                    if (contact == null) "给谁：所有下游（删的是这个商品的默认价）"
                    else "给谁：${contact.label}（删的是只给他定的那一条价）",
                    "要删的这条价：${AiWriteArgs.moneyText(row.unitPrice)} 元",
                    "———— 删掉之后谁按什么算 ————",
                    if (contact == null) {
                        "删的是默认价：没单独定过价的下游一起回落订单行单价（你这本账按公司给你的价算）"
                    } else {
                        "删的是他的专属价：他回落你的默认价；没有默认价就回落订单行单价"
                    },
                    "后台是伪装删除：行还在，执行完这条消息上会出现「撤回」，随时能原样放回来",
                    "只影响以后新下的单：已经下过的单一个字节都不动",
                    DOWNSTREAM_LINES_NOTE,
                ),
                payload = buildJsonObject {
                    put("price_id", row.id)
                    put("product_id", product.id)
                    put("product", product.label)
                    put("unit_price", row.unitPrice)
                    contact?.let { c ->
                        put("contact_id", c.id)
                        put("contact", c.label)
                    }
                },
            ),
        )
    }

    override suspend fun commit(payload: JsonObject, idempotencyKey: String) {
        ds.deleteMyPrice(payload.reqLong("price_id"))
    }
}

// ---------------------------------------------------------------- 共用小工具

/** 「所有下游」这一类说法 = 不填联系人（默认价那一档）。**都是 [AiWriteArgs.norm] 之后的形状**。 */
private val ALL_DOWNSTREAM_WORDS: Set<String> = setOf(
    "所有下游", "所有下游客户", "所有客户", "全部下游", "所有", "全部", "所有人", "全部人",
    "默认", "默认价", "默认下游价", "不指定", "all", "default", "*", "-", "无",
)

/**
 * 解析可选的「下游联系人」参数。
 *
 * 留空 = 这个商品的**默认价**（`contact_id IS NULL`，对全部下游生效）—— 那是最常用的一档，
 * 所以「给所有下游」「默认价」这些说法也当成留空，⛔ 不要拿它去名册里找人
 * （否则会抛"系统里没有匹配「所有下游」的下游联系人"，用户得重说一遍）。
 */
private suspend fun resolveDownstreamContact(ds: AiWriteDataSource, params: JsonObject): AiName? {
    val raw = AiWriteArgs.str(params, "contact") ?: return null
    if (AiWriteArgs.norm(raw) in ALL_DOWNSTREAM_WORDS) return null
    return AiWriteArgs.strict(raw, ds.contacts(), "下游联系人")
        ?: throw AiWriteArgException("没认出「${raw}」是哪一位下游联系人，请让用户说准确一点。")
}

/**
 * 同一个商品 ＋ 同一个下游**理论上**只有一条价（后端 `find_row` 按 `order_by(id).first()` 定位，
 * 表上还有唯一键 `uq_shipper_price_scope`），但 `contact_id IS NULL`（默认价）那一档
 * **唯一键管不住**（SQLite / MySQL 里 NULL 互不相等，`shipper_prices.py:203` 的注释写的就是这条）。
 * 真出现多条时让用户用单价指认，⛔ 不许替他挑一条。
 */
private fun pickByPriceArg(
    params: JsonObject,
    productName: String,
    who: String,
    cands: List<AiMyPriceRef>,
): AiMyPriceRef {
    val now = cands.joinToString("、") { AiWriteArgs.moneyText(it.unitPrice) + " 元" }
    val names = cands.map { AiWriteArgs.moneyText(it.unitPrice) + " 元" }
    val raw = AiWriteArgs.str(params, "price") ?: throw AiWriteArgException(
        "「${productName}」在「${who}」那里有 ${cands.size} 条价：${now}。要删哪一条？说单价我就知道是哪条。",
        candidates = names,
    )
    val want = AiWriteArgs.parseMoney(raw, "单价", mustPositive = true)
    val hit = cands.filter { sameMoney(it.unitPrice, want) }
    if (hit.size != 1) {
        throw AiWriteArgException(
            "「${productName}」在「${who}」那里的几条价里，没有对上 ${AiWriteArgs.moneyText(want)} 元的那一条" +
                "（现在有：${now}）。",
            candidates = names,
        )
    }
    return hit.first()
}

/** 价格比较：两边都当数字比（后端下发的可能是 `8.5000`，用户说的是 `8.5`）。 */
private fun sameMoney(raw: String?, want: BigDecimal): Boolean {
    if (raw.isNullOrBlank()) return false
    val v = try {
        BigDecimal(raw.trim())
    } catch (e: NumberFormatException) {
        return false
    }
    return v.compareTo(want) == 0
}

/**
 * 只有**批发商货主**有这本下游价（后端 `shipper_prices.py` 第二道闸 `_require_member`）。
 *
 * 为什么在 `prepare` 里拦而不是靠角色门：两种货主是**同一个角色**（`shipper`），角色门分不出来；
 * 而"发一张点了必然 403 的卡"是这个项目明确列为最坏的一类 bug。
 */
private suspend fun requireMemberShipper(ds: AiWriteDataSource) {
    if (!ds.isMemberShipper()) {
        throw AiWriteArgException(
            "你这个账号是普通货主，没有「给下游客户定价」这本账 —— " +
                "下游价是批发商给自己卖出去的商品定的价，普通货主是给自己下单、没有第二个客户。" +
                "（如果你是替别人下单的批发商，请让派单员在「货主管理」里把你设成批发商。）",
        )
    }
}
