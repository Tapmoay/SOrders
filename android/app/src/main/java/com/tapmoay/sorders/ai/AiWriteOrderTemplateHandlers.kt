package com.tapmoay.sorders.ai

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

/**
 * 预订单的 `create` / `update` —— **手写处理器**，因为这两个动作要收 `lines`。
 *
 * ## 为什么不能走声明式（`CrudSpec`）
 * 声明式的字段类型表（`AiFieldType`）里**没有数组**：文本/金额/整数/日期/是-否/枚举。
 * 而"这张预设单要备哪几样、各多少"必须是一组结构化数据 —— 让模型把它压成一句自由文本，
 * 就等于让解析器去猜（本仓库在「按表格调价」那一轮定过：**宁可让模型原样给数组，App 校验**）。
 * 这与 `orders.create` 是同一个处境、同一个解法（那边也是手写 + `lines`）。
 *
 * ## 一个处理器管两个动作（不是"在既有处理器里加分支"）
 * `create` 与 `update` 共用**同一套行解析与同一套字段校验**，差别只有两处：
 * ① update 要先按名字找到那张预设单；② update 的 `lines` 是可选的（填了整份换掉）。
 * 拆成两个类就是把这段解析抄两遍 —— 而两份解析迟早会在"上限/重名/不认识的商品名"
 * 这三件事上走散（那正是本仓库反复栽过的形状）。
 *
 * ## ⛔ 两件刻意不做的事
 * 1. **不生成订单**：「一键下单」是界面动作（读预设单 → 走已有的 `POST /orders`）。
 *    AI 要下单用**已有的** `orders.create`，这个处理器一行都不碰订单。
 * 2. **不静默丢掉单价**：模型可能照着 `orders.create` 的习惯在每行里多写一个 `unit_price`，
 *    预设单**不存单价**（价格会变，存旧价＝几个月后按旧价下单）。所以卡片上会**明写**
 *    「你给的单价不会写进去」——⛔ 不许悄悄忽略（用户按卡片理解，才不会以为预设了价格）。
 */
internal class OrderTemplateWriteHandler(
    override val actionId: String,
    private val ds: AiWriteDataSource,
    private val store: AiWritePreviewStore,
) : AiWriteHandler {

    /** 解析出来的一行货（`unit` 留空：AI 这条路拿不到单位，界面会按商品库显示）。 */
    private data class Line(val productId: Long, val name: String, val qty: Int)

    override suspend fun prepare(params: JsonObject): AiWriteOutcome {
        val isCreate = actionId == AiWriteOrderTemplates.CREATE

        // ---- 1. 改哪一张（只有 update 有目标）----
        val target = if (isCreate) {
            null
        } else {
            val raw = AiWriteArgs.required(params, "template", "要改哪一张预设单？把预设单的名字告诉我。")
            AiWriteArgs.strict(raw, ds.orderTemplates(), "预设单")
                ?: throw AiWriteArgException(
                    "系统里没有叫「$raw」的预设单。请先让用户确认名字（可以在预设单页面上看到全部预设单）。",
                )
        }

        // ---- 2. 商品行 ----
        val linesGiven = AiWriteArgs.str(params, "lines") != null
        if (isCreate && !linesGiven) {
            throw AiWriteArgException(
                "缺少 lines：这张预设单要备哪几样货？请传一个数组，形如 " +
                    "[{\"product\":\"红富士苹果\",\"quantity\":6}, {\"product\":\"赣南脐橙\",\"quantity\":2}]。",
            )
        }
        val parsed = if (linesGiven) parseLines(params) else null

        // ---- 3. 其余字段（只收用户/模型点名的那几项）----
        val name = AiWriteArgs.text(AiWriteArgs.str(params, "name"), "预设单名")
        if (isCreate && name.isBlank()) {
            throw AiWriteArgException("这张预设单叫什么名字？（用户以后在列表里就靠这个名字认它）")
        }
        val address = AiWriteArgs.str(params, "address")?.let { AiWriteArgs.text(it, "送货地址") }
        val receiverName = AiWriteArgs.str(params, "receiver_name")?.let { AiWriteArgs.text(it, "收货人") }
        val receiverPhone = AiWriteArgs.str(params, "receiver_phone")?.let { AiWriteArgs.text(it, "收货人电话") }
        val remark = AiWriteArgs.str(params, "remark")?.let { AiWriteArgs.text(it, "备注") }
        val feeRaw = AiWriteArgs.str(params, "freight_fee")
        // `mustPositive = false`：**0 是合法值**（＝免运费），而"不填"是另一件事（＝不预设）
        val fee = feeRaw?.let { AiWriteArgs.money(AiWriteArgs.parseMoney(it, "预设运费", mustPositive = false)) }

        // 货主：只认系统里真有的（预设单的货主必须是真账号，不像订单可以记临时货主）
        val shipperRaw = AiWriteArgs.str(params, "shipper")?.let { AiWriteArgs.text(it, "货主名") }
        val shipper = shipperRaw?.takeIf { it.isNotBlank() }?.let {
            AiWriteArgs.strict(it, ds.searchShippers(it, SHIPPER_PROBE), "货主")
        }

        // ---- 4. 「什么都没改」的空卡直接拒绝 ----
        if (!isCreate) {
            val nothing = !linesGiven && name.isBlank() && address == null && receiverName == null &&
                receiverPhone == null && remark == null && feeRaw == null && shipper == null
            if (nothing) {
                throw AiWriteArgException("你没有说要改哪一项。请先问用户到底要改什么，再提交。")
            }
        }

        // ---- 5. payload（只放点名的那几项：后端 PATCH 是部分更新语义）----
        val payload = buildJsonObject {
            target?.let { put("template_id", it.id) }
            if (name.isNotBlank()) put("name", name)
            address?.let { put("address", it) }
            receiverName?.let { put("receiver_name", it) }
            receiverPhone?.let { put("receiver_phone", it) }
            remark?.let { put("remark", it) }
            fee?.let { put("freight_fee", it) }
            shipper?.let { put("shipper_id", it.id) }
            parsed?.let { rows ->
                put(
                    "lines",
                    buildJsonArray {
                        rows.forEach { l ->
                            add(
                                buildJsonObject {
                                    put("product_id", l.productId)
                                    put("name", l.name)
                                    // 单位留给界面/商品库；预设单里它是显示用快照
                                    put("unit", "")
                                    put("qty", l.qty)
                                },
                            )
                        }
                    },
                )
            }
        }

        // ---- 6. 卡片：与 payload 同源 ----
        val head = if (isCreate) "建预设单：$name" else "改预设单：${target?.label ?: ""}"
        return card(
            summary = head + (parsed?.let { " · ${it.size} 样货" } ?: ""),
            details = buildList {
                if (!isCreate) add("改的是：${target?.label ?: "（没对上）"}（只改下面列出的那几项）")
                add("预设单名：$name")
                shipper?.let { add("货主：${it.label}") }
                address?.let { add("送货地址：$it") }
                receiverName?.let { add("收货人：$it") }
                receiverPhone?.let { add("收货人电话：$it") }
                add(
                    "预设运费：" + when {
                        fee == null -> "不预设（下单时按运费规则算）"
                        fee == "0.00" -> "0 元（免运费）"
                        else -> "${AiWriteArgs.moneyText(fee)} 元（下单时默认用这个数，仍可改）"
                    },
                )
                remark?.let { add("备注：$it") }
                if (parsed != null) {
                    add("———— 要备的货（${parsed.size} 样）————")
                    parsed.forEach { add("· ${it.name}  ${it.qty}") }
                    add("金额不在预设单里：下单那一刻按商品价（有批发商专属价就用专属价）算")
                }
                if (sawUnitPrice) {
                    add("⚠️ 你给的单价不会写进去：预设单只记「哪几样、各多少」")
                }
                add("———— 它是什么 ————")
                add("⛔ 这张预设单不生成订单、不占订单号、不动库存与账本")
                add("以后要用它：在「预订单」页面点「下单」，商品与数量会带进下单页（参数还能改）")
            },
            payload = payload,
        )
    }

    override suspend fun commit(payload: JsonObject, idempotencyKey: String) {
        val id = payload["template_id"]?.toString()?.trim('"')?.toLongOrNull()
        if (id == null) {
            ds.createOrderTemplate(payload)
        } else {
            ds.updateOrderTemplate(id, payload)
        }
    }

    /** 这一次模型有没有多给单价（卡片要如实说"不会写进去"）。 */
    private var sawUnitPrice = false

    /**
     * 解析 `lines`：`[{"product":"红富士苹果","quantity":6}, …]`。
     *
     * 与 `orders.create` 的 `lines` **同一个形状**（只是不许带单价）：`product` 传商品名、
     * `quantity` 只传数字。名字→编号那一半走共用的 [AiWriteArgs.strict]（⛔ 不自己写匹配）。
     */
    private suspend fun parseLines(params: JsonObject): List<Line> {
        val raw = params["lines"] as? JsonArray
            ?: throw AiWriteArgException(
                "lines 要是一个数组，形如 [{\"product\":\"红富士苹果\",\"quantity\":6}]。",
            )
        if (raw.isEmpty()) throw AiWriteArgException("lines 是空的：一张预设单至少要有一样货。")
        if (raw.size > AiWriteOrderTemplates.MAX_LINES) {
            throw AiWriteArgException(
                "一张预设单最多 ${AiWriteOrderTemplates.MAX_LINES} 行货，收到 ${raw.size} 行。请让用户先合并。",
            )
        }
        val pool = ds.products()
        val out = ArrayList<Line>(raw.size)
        raw.forEachIndexed { i, el ->
            val obj = el as? JsonObject
                ?: throw AiWriteArgException("lines 第 ${i + 1} 项不是一个对象，应该形如 {\"product\":\"…\",\"quantity\":2}。")
            val name = AiWriteArgs.required(obj, "product", "第 ${i + 1} 行是哪一样货？")
            val hit = AiWriteArgs.strict(name, pool, "商品库")
                ?: throw AiWriteArgException("商品库里没有「$name」，请让用户确认商品名（可以在商品管理页看到）。")
            if (out.any { it.productId == hit.id }) {
                throw AiWriteArgException("「${hit.label}」在 lines 里出现了两次，请合成一行（数量相加）。")
            }
            // ⚠️ 单价：**收下但明说不会写进去**（见文件头第 2 条）。不在这里静默忽略。
            if (AiWriteArgs.str(obj, "unit_price") != null) sawUnitPrice = true
            val qty = AiWriteArgs.str(obj, "quantity")?.let { AiWriteArgs.parseQuantity(it) } ?: 1
            out += Line(productId = hit.id, name = hit.label, qty = qty)
        }
        return out
    }

    /** 造卡只有一处实现（`AiWritePreviewStore.card`）：这里只把本处理器的 [actionId] 递进去。 */
    private fun card(summary: String, details: List<String>, payload: JsonObject): AiWriteOutcome =
        AiWriteOutcome.NeedConfirm(
            store.card(actionId, summary = summary, detailLines = details, payload = payload),
        )

    private companion object {
        /** 按名字找货主时先取多少个候选（够了：撞名时 `AiWriteArgs.strict` 会让他说清楚）。 */
        const val SHIPPER_PROBE = 20
    }
}
