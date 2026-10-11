package com.tapmoay.sorders.ai

import java.math.BigDecimal
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.longOrNull
import kotlinx.serialization.json.put

/**
 * 商品的**附加成本价口径**（FEAT-0025，2026-10-11）。
 *
 * ### 用户要什么（逐字）
 * 「我们是可以设置多个成本价的，AI 也都可以调。只不过我们一般情况下是默认按一个成本价，
 * 也就是真实成本价，按那个来计算的……有时候计算的时候还有第二个成本价 —— 这个成本价可能是
 * 加了其他东西、或者比如说有补贴啊等等之后的成本价。所以一定要有多个成本价啊。
 * 我在跟他聊天的过程当中，他就没办法设置第二个成本价。」
 *
 * ### 口径（一个字都不许含糊）
 * · **默认口径**＝商品的 `cost_price`（真实成本价）：订单行的成本快照、毛利报表一律按它算。
 *   它**不在这张表里**（后端合成一条 `is_default = true` 的出来给界面看），下面的动作都碰不到它。
 * · 本文件管的是**附加口径**（「返点后成本」「补贴后成本」…）：只是一个参考值，
 *   ⛔ 不参与订单、账单、毛利、库存的任何计算。
 *
 * ### 三条动作
 * | 动作 | 后端 | 说明 |
 * |---|---|---|
 * | `products.cost_price.set` | `POST /products/{id}/cost-prices`（同名 upsert）／`PATCH /products/cost-prices/{rowId}` | 没有就新建、已有同名就改价；改名要说清「它现在叫什么」 |
 * | `products.cost_price.delete` | `DELETE /products/cost-prices/{rowId}` | 伪装删除（行还在回收站，有「撤回」） |
 * | `products.cost_price.restore` | `POST /products/cost-prices/{rowId}/restore` | 撤回专用（`undoOnly`，模型看不到它） |
 *
 * ⚠️ 参数里带 `cost_price` ⇒ 自动落进「允许 AI 查看成本与毛利」那道开关
 * （[AiWriteService] 的 `costFieldIn`）：开关关着时卡片根本不弹，用户拿到的是一句
 * 「去哪儿打开它」的中文 —— 这是全仓统一的成本门，本文件不另开一道。
 */

/** 一条成本价口径（AI 侧用的单行）。默认那条由后端合成：`isDefault = true`、`id = 0`。 */
data class AiCostPriceRef(
    val id: Long,
    val name: String,
    val costPrice: String,
    val isDefault: Boolean = false,
)

/** 默认口径的名字（与后端 `products.py::DEFAULT_COST_PRICE_NAME` 是同一个字面量）。 */
private const val DEFAULT_COST_PRICE_NAME = "真实成本价"

internal object AiWriteCostPrices {
    val ACTIONS: List<AiWriteAction> = listOf(
        setAction(),
        deleteAction(),
        restoreAction(
            cn = "成本价口径",
            id = AiWrites.PRODUCTS_COST_PRICE_RESTORE,
            group = AiWrites.G_PRODUCT,
        ) { ds, id -> ds.restoreProductCostPrice(id) },
    )

    private fun setAction() = AiWriteAction(
        id = AiWrites.PRODUCTS_COST_PRICE_SET,
        title = "设置成本价口径",
        risk = AiWriteRisk.MEDIUM,
        group = AiWrites.G_PRODUCT,
        blurb = "给某个商品设一条「附加」成本价（如「返点后成本」「补贴后成本」）：没有同名的就新建、" +
            "已经有同名的就改价；要给它改名，就把「它现在叫什么」一起说出来。",
        params = listOf(
            AiWriteParam(name = "product", cn = "商品", required = true, hint = "商品名称"),
            AiWriteParam(
                name = "name",
                cn = "成本价口径名",
                required = true,
                hint = "这条成本价叫什么，如：返点后成本",
            ),
            AiWriteParam(
                name = "cost_price",
                cn = "成本价（元）",
                kind = AiWriteParamKind.NUMBER,
                hint = "这件商品按这个口径是多少钱一件（新建必填；只是改名可以不说）",
            ),
            AiWriteParam(
                name = "old_name",
                cn = "这条口径现在叫什么",
                hint = "只有「改名」时填：它现在的名字",
            ),
        ),
    )

    private fun deleteAction() = AiWriteAction(
        id = AiWrites.PRODUCTS_COST_PRICE_DELETE,
        title = "删掉一条成本价口径",
        risk = AiWriteRisk.MEDIUM,
        group = AiWrites.G_PRODUCT,
        blurb = "把某个商品上多余的成本价口径删掉（后台是伪装删除：行还在回收站，这条消息上会出现「撤回」）。" +
            "默认的「$DEFAULT_COST_PRICE_NAME」删不掉 —— 它跟着商品走。",
        params = listOf(
            AiWriteParam(name = "product", cn = "商品", required = true, hint = "商品名称"),
            AiWriteParam(
                name = "name",
                cn = "成本价口径名",
                required = true,
                hint = "要删掉哪一条，如：补贴后成本",
            ),
        ),
    )
}

/**
 * 「给某个商品设/改一条附加成本价口径」。
 *
 * ⛔ 这里一个字都不许写库：只在 [prepare] 里读回现状 → 弹一张写着「原来 → 现在」的卡，
 * 真正落库在 [commit]（全仓唯一的写路径，见 [AiWriteService.execute]）。
 */
class SetCostPriceHandler(
    private val ds: AiWriteDataSource,
    private val store: AiWritePreviewStore,
) : AiWriteHandler {
    override val actionId = AiWrites.PRODUCTS_COST_PRICE_SET

    override suspend fun prepare(params: JsonObject): AiWriteOutcome {
        val product = AiWriteArgs.strict(
            AiWriteArgs.required(params, "product", "商品"),
            ds.products(),
            "商品",
        ) ?: throw AiWriteArgException("请把商品名说全（名字是空的，名册里对不上任何一条）。")
        val name = AiWriteArgs.text(AiWriteArgs.required(params, "name", "成本价口径名"), "成本价口径名", max = 32)
        val oldName = AiWriteArgs.str(params, "old_name")
            ?.let { AiWriteArgs.text(it, "这条口径现在叫什么", max = 32) }
        if (AiWriteArgs.norm(name) == AiWriteArgs.norm(DEFAULT_COST_PRICE_NAME)) {
            throw AiWriteArgException(
                "「$DEFAULT_COST_PRICE_NAME」是默认口径（订单与毛利按它算），它不在附加口径这一族里：" +
                    "要改它就说一句「把商品 ${product.label} 的成本价改成 X」——那是「改商品」那个动作",
            )
        }

        // 只列**附加口径**：默认那一条（isDefault）是合成的，改名/改价/删除都不许碰它。
        val live = ds.productCostPrices(product.id).filter { !it.isDefault }
        val names = live.map { it.name }
        fun rowOf(raw: String): AiCostPriceRef =
            live.firstOrNull { AiWriteArgs.norm(it.name) == AiWriteArgs.norm(raw) }
                ?: throw AiWriteArgException("这个商品上没有叫「$raw」的成本价口径", candidates = names.take(5))

        val renaming = oldName?.let { rowOf(it) }
        val sameName = live.firstOrNull { AiWriteArgs.norm(it.name) == AiWriteArgs.norm(name) }
        if (renaming != null && sameName != null && sameName.id != renaming.id) {
            throw AiWriteArgException(
                "这个商品已经有一条叫「$name」的成本价口径了：要么给它换个名字，要么把要改的那条先换个名字",
                candidates = names.take(5),
            )
        }
        val existing = renaming ?: sameName
        val price = AiWriteArgs.str(params, "cost_price")
            ?.let { AiWriteArgs.parseMoney(it, "成本价", mustPositive = false) }

        if (existing == null && price == null) {
            throw AiWriteArgException("新建一条成本价口径要给出金额：这件商品按「$name」是多少钱一件？")
        }
        if (existing != null && renaming == null && price == null) {
            throw AiWriteArgException(
                "「${existing.name}」已经是这个商品上的一条成本价口径了：" +
                    "要改价就把金额说出来；要改名就把「它现在叫什么」说出来",
            )
        }

        val lines = mutableListOf("商品：${product.label}", "口径：$name")
        if (renaming != null) {
            lines += "改名：原来叫「${renaming.name}」→ 现在叫「$name」"
        }
        if (price != null) {
            lines += if (existing != null) {
                "金额：原来：${AiWriteArgs.moneyText(existing.costPrice)} 元 → 现在：${AiWriteArgs.moneyText(price)} 元"
            } else {
                "金额：原来：没有「$name」这一条 → 现在：新建 ${AiWriteArgs.moneyText(price)} 元"
            }
        } else {
            lines += "金额：${AiWriteArgs.moneyText(existing?.costPrice ?: "0")} 元（这次不动它）"
        }
        if (existing == null) {
            // 回收站里同名的会被后端的 upsert **放回来**（不是新建第二条）—— 卡片必须先说清，
            // 否则用户会以为"删过的又冒出来了"。
            val recycled = ds.deletedProductCostPrices(product.id)
                .firstOrNull { AiWriteArgs.norm(it.name) == AiWriteArgs.norm(name) }
            if (recycled != null) {
                lines += "回收站里已经有一条同名的「${recycled.name}」" +
                    "（${AiWriteArgs.moneyText(recycled.costPrice)} 元）：执行后会把它放回来，并按这次说的改"
            }
        }
        lines += "⛔ 订单与毛利的口径不变：那两个只按商品的「$DEFAULT_COST_PRICE_NAME」算，这一条只是参考"
        lines += "这条没有「撤回」按钮（后台是「有就改、没有就建」）：要改回去就说一句" +
            "「把商品 ${product.label} 的『$name』改成 X」"

        return AiWriteOutcome.NeedConfirm(
            store.card(
                actionId,
                summary = if (existing != null) {
                    "改商品「${product.label}」的成本价口径「$name」"
                } else {
                    "给商品「${product.label}」新建成本价口径「$name」"
                },
                detailLines = lines,
                payload = buildJsonObject {
                    put("product_id", product.id)
                    put("name", name)
                    existing?.let { put("cost_price_id", it.id) }
                    price?.let { put("cost_price", AiWriteArgs.money(it)) }
                },
            ),
        )
    }

    override suspend fun commit(payload: JsonObject, idempotencyKey: String) {
        val productId = payload.reqLong("product_id")
        val name = payload.req("name")
        val price = payload["cost_price"]?.jsonPrimitive?.contentOrNull
        val rowId = payload["cost_price_id"]?.jsonPrimitive?.longOrNull
        if (rowId == null) {
            ds.setProductCostPrice(productId, name, price ?: throw AiWriteArgException("缺少成本价金额"))
        } else {
            // 已经有这一条 ⇒ 走 PATCH（改名 / 改价）。名字没变时后端只是不写这一项（它自己比对）。
            ds.updateProductCostPrice(rowId, name, price)
        }
    }
}

/** 「删掉某个商品上的一条附加成本价口径」（伪装删除：撤回按钮由 [AiResources] 的成对动作给）。 */
class DeleteCostPriceHandler(
    private val ds: AiWriteDataSource,
    private val store: AiWritePreviewStore,
) : AiWriteHandler {
    override val actionId = AiWrites.PRODUCTS_COST_PRICE_DELETE

    override suspend fun prepare(params: JsonObject): AiWriteOutcome {
        val product = AiWriteArgs.strict(
            AiWriteArgs.required(params, "product", "商品"),
            ds.products(),
            "商品",
        ) ?: throw AiWriteArgException("请把商品名说全（名字是空的，名册里对不上任何一条）。")
        val raw = AiWriteArgs.required(params, "name", "成本价口径名")
        val live = ds.productCostPrices(product.id).filter { !it.isDefault }
        val row = live.firstOrNull { AiWriteArgs.norm(it.name) == AiWriteArgs.norm(raw) }
            ?: throw AiWriteArgException(
                "这个商品上没有叫「$raw」的成本价口径" +
                    "（默认的「$DEFAULT_COST_PRICE_NAME」不在这一族里，它跟着商品走、删不掉）",
                candidates = live.map { it.name }.take(5),
            )
        return AiWriteOutcome.NeedConfirm(
            store.card(
                actionId,
                summary = "删掉商品「${product.label}」的成本价口径「${row.name}」",
                detailLines = listOf(
                    "商品：${product.label}",
                    "口径：${row.name}",
                    "金额：原来：${AiWriteArgs.moneyText(row.costPrice)} 元 → 现在：这一条没有了",
                    "⛔ 订单与毛利的口径不变：那两个只按商品的「$DEFAULT_COST_PRICE_NAME」算，这一条只是参考",
                    "后台是伪装删除：行还在回收站，执行完这条消息上会出现「撤回」",
                ),
                payload = buildJsonObject {
                    put("product_id", product.id)
                    put("cost_price_id", row.id)
                    put("name", row.name)
                    put("cost_price", row.costPrice)
                },
            ),
        )
    }

    override suspend fun commit(payload: JsonObject, idempotencyKey: String) {
        ds.deleteProductCostPrice(payload.reqLong("cost_price_id"))
    }
}
