package com.tapmoay.sorders.ai

import com.tapmoay.sorders.core.OrderStatusModel
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import java.math.BigDecimal
import java.math.RoundingMode
import java.time.LocalDate

/**
 * 订单域的写动作（派单 / 撤回 / 撤销 / 下单 / 改运费 / 收款 / 挂账）。
 *
 * ### 这一批全是 HIGH 或 MEDIUM 档，理由不是"操作类型危险"，是**后果的形状**
 * 它们和"记一笔支出"有三个本质区别：
 * 1. **影响别人**：派单会给司机推一条通知、撤回会给他推一条撤回通知——他不知道是你点错了；
 * 2. **有前置状态**：不是所有单都能派、都能撤。后端会 400，但如果等到用户点了确认才报错，
 *    那张卡就是白弹的（他会以为"系统坏了"）。所以每个 prepare 都**先把状态查出来核对**；
 * 3. **多数撤不回来**：撤销之后是终态。
 *
 * 第 2 条是这一批里唯一"多做了一步"的地方，也是它们和账目动作最大的实现差别：
 * **先把订单查出来，把状态、原来的司机、地址都摆到卡片上**，用户才能判断"是不是这一单"。
 */

/** 订单处理器共用的骨架：查单、状态核对、卡片明细。 */
abstract class OrderWriteHandler(
    protected val ds: AiWriteDataSource,
    protected val store: AiWritePreviewStore,
) : AiWriteHandler {

    /**
     * 解析订单号 → 一张订单。**严格：对不上、对上多张都拒绝。**
     *
     * 用 [AiOrderRef.label] 做候选——它带单号 + 货主 + 状态，
     * 用户能一眼认出是哪一单（光给单号他记不住，光给货主又分不清是哪一批）。
     */
    protected suspend fun resolveOrder(args: JsonObject): AiOrderRef {
        val ref = AiWriteArgs.required(args, "order", "要操作哪一张订单？把订单号告诉我。")

        // ⚠️ 长度下限不是为了严谨，是为了**别把后端拖垮**：
        // `GET /orders?q=` 在派单员视角下是**全量匹配**（单号/货主/电话/地址/司机都搜），
        // 且不传 status 时后端默认不限条数。拿「01」这种片段去搜，会拉回几万条订单、
        // 几十 MB 响应，而这条路上没有任何分页兜底。真正要拦的是"用户只是随口说了个词"，
        // 那本来也该让模型先查清楚再动手。
        if (AiWriteArgs.normCode(ref).length < MIN_REF_CHARS) {
            throw AiWriteArgException(
                "「$ref」太短了，没法定位到具体订单。请让用户给**完整订单号**" +
                    "（形如 SOTEST2026091100230），或者先用查询工具把这一单找出来。",
            )
        }

        val hits = ds.findOrders(ref, ORDER_PROBE_LIMIT)
        val q = AiWriteArgs.normCode(ref)
        val exact = hits.filter { AiWriteArgs.normCode(it.orderNo) == q }
        val pool = if (exact.isNotEmpty()) exact else hits

        return when {
            pool.isEmpty() -> throw AiWriteArgException(
                "没找到订单「$ref」。请让用户确认单号；他说的也可能不是单号（比如只是「上午那单」）——" +
                    "那就先查一下再问他是哪一张。",
            )

            pool.size == 1 -> pool.first()

            else -> throw AiWriteArgException(
                "「$ref」对上了多张订单：${pool.take(AiWriteArgs.MAX_CANDIDATES).joinToString("、") { it.label() }}。" +
                    "请让用户说清楚是哪一张，**不要自己挑一个**。",
                candidates = pool.take(AiWriteArgs.MAX_CANDIDATES).map { it.label() },
            )
        }
    }

    /** 卡片上"这一单是谁"的那几行——每个订单动作都要有，用户靠它核对。 */
    protected fun orderLines(o: AiOrderRef): List<String> = buildList {
        add("订单号：${o.orderNo}")
        add("货主：${o.shipper.ifBlank { "（未填）" }}")
        add("当前状态：${o.statusCn}")
        if (o.address.isNotBlank()) add("送货地址：${o.address}")
        if (o.amount != "0.00") add("订单金额：${o.amount} 元")
        if (o.driverLabel != null) add("当前司机：${o.driverLabel}")
    }

    /** 状态不满足时抛出一句**人话**（用户看不懂「仅 PENDING_DISPATCH 可派单」）。
     *
     * ⚠️ 判据是 [AiOrderRef.status]（后端原始状态码）而不是中文：中文只是显示名，
     *    拿它当键的话，改一次文案就会悄悄改掉 12 处状态门的含义（见 `AiOrderRef.status` 的注释）。
     *    集合一律取自 [OrderStatusModel]（与后端逐值对账，红线 `_check_client_contract.py` 管着）。
     */
    protected fun requireStatus(o: AiOrderRef, allowed: Set<String>, why: String) {
        if (o.status !in allowed) {
            throw AiWriteArgException(
                "这单现在是「${o.statusCn}」，$why。请如实告诉用户，不要换一张单去操作。",
            )
        }
    }

    /** 造卡只有一处实现（`AiWritePreviewStore.card`）：这里只把本处理器的 [actionId] 递进去。 */
    protected fun card(summary: String, details: List<String>, payload: JsonObject): AiWriteOutcome =
        AiWriteOutcome.NeedConfirm(
            store.card(actionId, summary = summary, detailLines = details, payload = payload),
        )

    companion object {
        const val ORDER_PROBE_LIMIT = 10

        /** 订单号的最短可搜长度（见 [resolveOrder] 里那段关于"别把后端拖垮"的注释）。 */
        const val MIN_REF_CHARS = 6
    }
}

// ============================================================== 派单

/**
 * 把待派单派给某个司机。
 *
 * ### 为什么 `driver` 是必填、而且**不许有默认值**
 * "派给谁"就是这件事本身。用户没说 → 模型必须回去问，**不能挑一个"看起来合适"的**
 * （比如"上次也是他跑的"）。挑错人的后果不是一条错数据，是**一个司机白跑一趟、
 * 另一个司机没活干、货主那边的时间也对不上**。
 */
class AssignOrderHandler(
    ds: AiWriteDataSource,
    store: AiWritePreviewStore,
) : OrderWriteHandler(ds, store) {

    override val actionId = AiWrites.ORDERS_ASSIGN

    override suspend fun prepare(params: JsonObject): AiWriteOutcome {
        val order = resolveOrder(params)
        requireStatus(order, OrderStatusModel.ASSIGNABLE, "只有「待派单」的单能派单")

        val driverName = AiWriteArgs.required(params, "driver", "这单派给谁？把司机姓名告诉我。")
        val driver = AiWriteArgs.strict(driverName, ds.drivers(), "司机")

        val freight = AiWriteArgs.str(params, "freight")?.let {
            AiWriteArgs.parseMoney(it, "freight", mustPositive = false)
        }
        // 逐单覆盖（v3.37）：用户 2026-09-18「每单是不固定的…这些单价是由派单员来决定的」。
        // ⚠️ 这两个数**只在司机挂着规则时才会生效**（没挂规则 → 后端算的是全额运费）。
        //    所以卡片必须把"他现在按什么算钱"写出来，并且由后端在派单时做最终判定
        //    （判据只有一份：`driver_pay.override_problem`）。
        val pieceAmount = AiWriteArgs.str(params, "piece_amount")?.let {
            AiWriteArgs.parseMoney(it, "piece_amount", mustPositive = false)
        }
        val commissionRate = AiWriteArgs.str(params, "commission_rate")?.let {
            AiWriteArgs.parseMoney(it, "commission_rate", mustPositive = false)
        }
        val collectCash = AiWriteArgs.parseBool(params, "collect_cash")
        val note = AiWriteArgs.text(AiWriteArgs.str(params, "note"), "给司机的备注")

        return card(
            summary = "派单：${order.orderNo} → ${driver!!.label}",
            details = buildList {
                addAll(orderLines(order))
                add("———— 派给 ————")
                add("司机：${driver.label}")
                add("他现在的计费规则：${driver.note?.takeIf { it.isNotBlank() } ?: "没挂规则（按老口径：计件=全额运费）"}")
                add(
                    if (freight != null) "司机运费：${AiWriteArgs.money(freight)} 元"
                    else "司机运费：不填（保持待定，可事后在页面上补录）",
                )
                pieceAmount?.let { add("这一单单独定价：${AiWriteArgs.money(it)} 元（不走规则里的每单金额）") }
                commissionRate?.let { add("这一单单独定提成：${AiWriteArgs.money(it)}%（提成基数仍按上面的规则）") }
                if (collectCash != null) {
                    add(if (collectCash) "收款方式：司机送达时收现金" else "收款方式：送达后挂账")
                } else {
                    add("收款方式：按订单原本的设置")
                }
                if (note.isNotBlank()) add("给司机的备注：$note")
            },
            payload = buildJsonObject {
                put("order_id", order.id)
                put("driver_id", driver.id)
                put("internal_note", note)
                freight?.let { put("freight_fee", it.toPlainString()) }
                pieceAmount?.let { put("driver_piece_amount", it.toPlainString()) }
                commissionRate?.let { put("driver_commission_rate", it.toPlainString()) }
                collectCash?.let { put("collect_cash", it) }
            },
        )
    }

    override suspend fun commit(payload: JsonObject, idempotencyKey: String) {
        ds.assignOrder(
            orderId = payload.reqLong("order_id"),
            driverId = payload.reqLong("driver_id"),
            note = payload.str("internal_note"),
            freightFee = payload.str("freight_fee"),
            collectCash = payload.bool("collect_cash"),
            pieceAmount = payload.str("driver_piece_amount"),
            commissionRate = payload.str("driver_commission_rate"),
        )
    }

    /**
     * ⚠️ v3.27 起**这里不再手写撤回**：撤回只有一处（[AiRevert] + [AiResources]）。
     * 派单 ↔ 撤回派单现在只是那边的一行 `paired(...)` 声明——
     * 手写这一份做的事一模一样，只是多了一处要记得改的地方。
     */
}

// ============================================================== 撤回派单

/**
 * 把已经派出去的订单收回来（回到待派单）。
 *
 * `reason` 是**必填**的，因为后端要求非空，而且它会**原样推送给原司机**——
 * "撤回"两个字发过去，司机只会来问你为什么。所以文案里明确要求写原因。
 */
class RecallOrderHandler(
    ds: AiWriteDataSource,
    store: AiWritePreviewStore,
) : OrderWriteHandler(ds, store) {

    override val actionId = AiWrites.ORDERS_RECALL

    override suspend fun prepare(params: JsonObject): AiWriteOutcome {
        val order = resolveOrder(params)
        requireStatus(order, OrderStatusModel.RECALLABLE, "只有「派单中」或「已接单」的单能撤回")

        val reason = AiWriteArgs.required(params, "reason", "为什么要撤回？这句话会推送给原司机，要说清楚。")
        AiWriteArgs.text(reason, "撤回原因", max = 200)

        return card(
            summary = "撤回派单：${order.orderNo}（原司机 ${order.driverLabel ?: "—"}）",
            details = buildList {
                addAll(orderLines(order))
                add("———— 撤回后 ————")
                add("这单会回到「待派单」，司机栏清空，可以重新派给别人")
                add("原司机会收到一条撤回推送，原因：$reason")
            },
            payload = buildJsonObject {
                put("order_id", order.id)
                put("reason", reason)
            },
        )
    }

    override suspend fun commit(payload: JsonObject, idempotencyKey: String) {
        ds.recallOrder(payload.reqLong("order_id"), payload.req("reason"))
    }
}

// ============================================================== 撤回派单

// ============================================================== 撤销订单

/**
 * 撤销订单（终态）。
 *
 * 状态门槛放在卡片**之前**核对：不是所有单都能撤，而"点了确认才告诉你不能撤"
 * 会让用户以为系统坏了。所以查出来先看状态，不对就直接拒绝并说清楚。
 */
class CancelOrderHandler(
    ds: AiWriteDataSource,
    store: AiWritePreviewStore,
) : OrderWriteHandler(ds, store) {

    override val actionId = AiWrites.ORDERS_CANCEL

    override suspend fun prepare(params: JsonObject): AiWriteOutcome {
        val order = resolveOrder(params)
        requireStatus(order, OrderStatusModel.CANCELLABLE, "只有「待派单」和「派单中（司机未接单）」的单能撤销")

        return card(
            summary = "撤销订单：${order.orderNo}",
            details = buildList {
                addAll(orderLines(order))
                add("———— 撤销后 ————")
                add("这单会变成「已撤销」，撤不回来")
                add("占用的库存会自动释放")
                if (order.driverLabel != null) add("司机 ${order.driverLabel} 会收到一条撤销通知")
            },
            payload = buildJsonObject { put("order_id", order.id) },
        )
    }

    override suspend fun commit(payload: JsonObject, idempotencyKey: String) {
        ds.cancelOrder(payload.reqLong("order_id"))
    }
}

// ============================================================== 退货

/**
 * **订单退货**（2026-09-20 用户要求：整单退 / 只退其中几个商品）。
 *
 * ### 这个动作为什么是 HIGH 而不是 MEDIUM
 * 它一次动四样东西：账本红冲（营业额减）、库存回补、**可能真退钱给客户**、订单状态。
 * 撤销只是"让一张没发生的单作废"，退货是"已经发生的生意改了一部分" —— 后者赔的是真金白银。
 *
 * ### 三道前置核对（都在卡片之前，理由同撤销）
 * 1. **状态必须是已送达**（后端只认 DELIVERED）——"点了确认才告诉你不能退"会让用户以为系统坏了；
 * 2. **必须真有余量**：整单已退完、或者每一行的余量都是 0（全是货损）时直接拒绝，
 *    而不是弹一张"退 0 件"的卡；
 * 3. **数量不许超过余量**（[AiReturnableLine.maxReturnable] 一处算）。
 *
 * ### 卡片上必须写出来的两件事
 * · **货损那几件退不了**：用户看到"可退 8（下单 10、货损 2）"才知道为什么不是 10；
 * · **退完会发生什么**：账本红冲、库存回补、已结账则自动退款、整单退完变「已退货」。
 *   ⛔ 退款**金额**不在卡片上编一个数：它取决于"累计收过多少、退过多少"，
 *   那只有后端算得对（卡片写"以后端为准"比写一个错数强）。
 */
class ReturnOrderHandler(
    ds: AiWriteDataSource,
    store: AiWritePreviewStore,
) : OrderWriteHandler(ds, store) {

    override val actionId = AiWrites.ORDERS_RETURN

    override suspend fun prepare(params: JsonObject): AiWriteOutcome {
        val order = resolveOrder(params)
        requireStatus(order, OrderStatusModel.RETURNABLE, "只有「已送达」的单能退货（货还没送到的请用「撤销」）")

        // ⚠️ 这一单若挂着一张**待处理的退货申请**：直连退货**照旧允许**（2026-09-21 用户拍板
        //    「如果是派单员的话，就不需要去修改这个按钮」），退完之后那张申请会被后端**自动关闭**
        //    （状态转「已关闭（派单员已直接退货）」，并把"申请了什么 / 实退什么"发给货主）。
        //    ⛔ 所以这里**不再拒绝**（早先那版是 fail-closed 挡掉，规则已按用户口径改回来）——
        //    但卡片上必须把这件事写出来：派单员才知道货主手上那张申请会跟着关掉、货主会收到消息。
        val pendingReq = ds.pendingReturnRequests(order.id).firstOrNull { it.isPending }

        val lines = ds.returnableLines(order.id)
        if (lines.isEmpty()) {
            throw AiWriteArgException("这一单一件商品都没有，退不了。请让派单员打开订单详情看一眼。")
        }
        val available = lines.filter { it.maxReturnable > 0 }
        if (available.isEmpty()) {
            throw AiWriteArgException(
                "这一单没有可以退的商品了：" +
                    lines.joinToString("；") { it.label() } +
                    "。请如实告诉用户（已经退完的部分不要再退一次）。",
            )
        }

        val picked = parseItems(params, available)
        val amount = picked.fold(BigDecimal.ZERO) { acc, (line, qty) ->
            acc.add(BigDecimal(line.unitPrice).multiply(BigDecimal(qty)))
        }.setScale(2, RoundingMode.HALF_UP)
        val whollyReturned = lines.all { it.maxReturnable <= 0 || picked.any { p -> p.first.id == it.id && p.second >= it.maxReturnable } }
        val note = AiWriteArgs.text(AiWriteArgs.str(params, "note"), "退货备注")

        return card(
            summary = "退货：${order.orderNo} · ${picked.sumOf { it.second }} 件 · " +
                "${AiWriteArgs.money(amount)} 元",
            details = buildList {
                addAll(orderLines(order))
                add("———— 退回 ————")
                picked.forEach { (line, qty) ->
                    add(
                        "· ${line.name}  $qty × ${line.unitPrice} 元 = " +
                            "${AiWriteArgs.money(BigDecimal(line.unitPrice).multiply(BigDecimal(qty)).setScale(2, RoundingMode.HALF_UP))} 元",
                    )
                    add("    ${line.label()}")
                }
                add("合计：${AiWriteArgs.money(amount)} 元")
                add("———— 会发生什么 ————")
                add("账本按这几行红冲（营业额减 ${AiWriteArgs.money(amount)} 元）")
                add("退回来的货补回库存")
                add("这单如果已经收过钱：自动记一笔退给客户的现金（金额按「收过多少、退过多少」由系统算）")
                add(
                    if (whollyReturned) "这几行退完，整单就退完了 → 订单变成「已退货」"
                    else "这是部分退货，订单仍然是「已送达」，剩下的还欠着",
                )
                add("⚠️ 已经报过货损的那几件退不了（那部分已经按损失计过账）")
                if (pendingReq != null) {
                    add(
                        "这一单还有一张待处理的退货申请（${pendingReq.linesText()}）：" +
                            "退完之后那张申请会自动关闭，并给货主发一条消息说明实退了多少" +
                            "（两边件数不一致时会如实写出来）",
                    )
                }
                if (note.isNotBlank()) add("备注：$note")
            },
            payload = buildJsonObject {
                put("order_id", order.id)
                put("note", note)
                put(
                    "items",
                    buildJsonArray {
                        picked.forEach { (line, qty) ->
                            add(
                                buildJsonObject {
                                    put("order_product_id", line.id)
                                    put("quantity", qty)
                                },
                            )
                        }
                    },
                )
            },
        )
    }

    override suspend fun commit(payload: JsonObject, idempotencyKey: String) {
        val items = payload["items"] as? JsonArray
            ?: throw AiWriteArgException("退货明细丢了，请重新发起一次。")
        val pairs = items.map { el ->
            val obj = el as? JsonObject ?: throw AiWriteArgException("退货明细格式不对，请重新发起一次。")
            obj.reqLong("order_product_id") to obj.reqInt("quantity")
        }
        ds.returnOrder(payload.reqLong("order_id"), pairs, payload.str("note").orEmpty())
    }

    /**
     * 解析 `lines`；**留空 = 整单退货**（每行都退到余量上限）。
     *
     * ⚠️ 整单退货**不是另一条路径**：它就是"每一行都填满"，走同一套上限校验。
     *    多一个 `all=true` 开关就多一条绕过上限的路（后端 `OrderReturnBody` 也没有这个开关）。
     */
    private suspend fun parseItems(
        params: JsonObject,
        available: List<AiReturnableLine>,
    ): List<Pair<AiReturnableLine, Int>> {
        val raw = params["lines"] as? JsonArray
        if (raw == null || raw.isEmpty()) {
            return available.map { it to it.maxReturnable }
        }
        if (raw.size > MAX_ITEMS) {
            throw AiWriteArgException("一次最多退 $MAX_ITEMS 种商品，收到 ${raw.size} 种。")
        }
        val pool = available.map { AiName(it.id, it.name) }
        val out = mutableListOf<Pair<AiReturnableLine, Int>>()
        raw.forEachIndexed { i, el ->
            val obj = el as? JsonObject
                ?: throw AiWriteArgException("lines 第 ${i + 1} 项不是一个对象，应该形如 {\"product\":\"…\",\"quantity\":2}。")
            val name = AiWriteArgs.required(obj, "product", "第 ${i + 1} 行退哪个商品？")
            val hit = AiWriteArgs.strict(name, pool, "可退的商品")
            val line = available.first { it.id == hit!!.id }
            val qty = AiWriteArgs.str(obj, "quantity")?.let { AiWriteArgs.parseQuantity(it) } ?: 1
            if (qty > line.maxReturnable) {
                throw AiWriteArgException(
                    "「${line.name}」最多只能退 ${line.maxReturnable} 件（${line.label()}），你填了 $qty。",
                )
            }
            if (out.any { it.first.id == line.id }) {
                throw AiWriteArgException("「${line.name}」在 lines 里出现了两次，请合成一行。")
            }
            out += line to qty
        }
        return out
    }

    private companion object {
        /** 与后端 `OrderReturnBody.items` 的 `max_length=20` 对齐（一张单的商品行上限是 10）。 */
        const val MAX_ITEMS = 10
    }
}

// ============================================================== 创建订单

/**
 * 替货主新建一张订单（派单员代理下单）。
 *
 * ### 为什么这里的 `lines` 允许是数组，而不是把参数拍平
 * 一张单天然是**多行商品**。拍平成 `product1/quantity1/unit_price1…` 会立刻撞上限
 * （后端最多 10 行），而模型填 `product7` 时极容易串行。
 * 数组的结构和它要表达的语义是一致的，所以这里破例允许 `params` 里出现一个数组——
 * 工具描述里也专门写明了这个例外。
 */
class CreateOrderHandler(
    ds: AiWriteDataSource,
    store: AiWritePreviewStore,
) : OrderWriteHandler(ds, store) {

    override val actionId = AiWrites.ORDERS_CREATE

    override suspend fun prepare(params: JsonObject): AiWriteOutcome {
        // ⚠️⚠️ **按角色分叉，这一步不能省**（2026-09-20 实测的坑，用户第七轮要求"手机能做的 AI 也要能做"）：
        //     派单员代理下单要先查"这单是谁的"（`GET /users?q=`），而**货主是给自己下单** ——
        //     后端 `orders.py::create_order` 对货主是 `target_shipper_id = current.id`，
        //     传了 `shipper_id` 还会 400「货主下单无需指定货主」。
        //     而 `GET /users` 的角色门是 `USER_MANAGE`（只有派单员），**货主调它 403**
        //     （真后端实测：`{"detail":"无操作权限…"}`）—— 于是货主的 AI「帮我下一单」
        //     在第一步就抛异常，**卡片永远发不出来**，而手机上他自己明明能下单。
        //
        // 判据取 `ds.currentRoleKey()`（数据源里现问一次 `users/me`），不是"传了 shipper 参数就算代理"：
        // 货主随口说"给张三下单"也不该被当成代理（后端会 403，他也没有那个能力）。
        val selfOrder = ds.currentRoleKey() == "shipper"
        val shipperRaw = if (selfOrder) {
            "" // 自己给自己下单，没有"这单是谁的"这个问题
        } else {
            AiWriteArgs.required(params, "shipper", "这单是谁的？把货主名告诉我。")
        }
        // 货主允许"查不到"→ 按临时货主记（代理下单时很常见：来收一趟货、没建过档）
        val shipper = if (selfOrder) {
            null
        } else {
            AiWriteArgs.strict(
                shipperRaw,
                ds.searchShippers(shipperRaw, LedgerEntryWriteHandler.SHIPPER_PROBE_LIMIT),
                "货主",
                allowMissing = true,
            )
        }

        val lines = parseLines(params)
        val address = AiWriteArgs.text(AiWriteArgs.str(params, "address"), "送货地址")
        val date = AiWriteArgs.parseDate(AiWriteArgs.str(params, "date"), "date") ?: LocalDate.now()
        val phoneDongjia = AiWriteArgs.text(AiWriteArgs.str(params, "phone_dongjia"), "收货人电话", 32)
        val phoneBoss = AiWriteArgs.text(AiWriteArgs.str(params, "phone_boss"), "下单人电话", 32)
        // 收货人 / 下单人的**名称**（2026-09-20 加的两个字段，卡片与详情都会显示它们）
        val nameDongjia = AiWriteArgs.text(AiWriteArgs.str(params, "name_dongjia"), "收货人名称", 64)
        val nameBoss = AiWriteArgs.text(AiWriteArgs.str(params, "name_boss"), "下单人名称", 64)
        val remark = AiWriteArgs.text(AiWriteArgs.str(params, "remark"), "备注")

        // 送货地址换成坐标（高德地理编码，只读）。不查这一步的后果很具体：
        // 司机在订单详情点「高德导航」时，[openAmapNavigation] 拿到空坐标会退化成
        // "打开高德首页"——**没有目的地**，司机得自己把地址再手打一遍。
        //
        // 例外是「当前位置」句柄：那一条取的是**手机定位**（真实地址 + 精确坐标，
        // 见 `AiWriteDataSource.resolveAddress`）——拿不到会当场抛一句"去开定位权限"的中文。
        val geo = if (address.isNotBlank()) ds.resolveAddress(address) else null
        // 写进 payload 的地址文字：句柄要换成**解析出来的真实地址**
        // （不换的话地址库里、订单上、司机看到的都是「当前位置」四个字，而且不会报错）。
        val addressText = geo?.address ?: address

        val total = lines.fold(BigDecimal.ZERO) { acc, l ->
            acc.add(BigDecimal(l.unitPrice).multiply(BigDecimal(l.quantity)))
        }.setScale(2, RoundingMode.HALF_UP)

        return card(
            summary = "新建订单：" +
                (if (selfOrder) "你自己" else shipper?.label ?: "$shipperRaw（临时货主）") + " · " +
                "${lines.size} 种商品 · 合计 ${AiWriteArgs.money(total)} 元",
            details = buildList {
                add(
                    if (selfOrder) "货主：你自己（货主给自己下单，不用指定货主）"
                    else if (shipper != null) "货主：${shipper.label}（系统里的货主）"
                    else "货主：$shipperRaw（系统里没有这个名字，将按「临时货主」记）",
                )
                add("下单日期：$date")
                add("———— 商品明细 ————")
                lines.forEach { l -> add("· ${l.name}  ${l.quantity} × ${l.unitPrice} 元 = ${l.lineTotal} 元") }
                add("合计：${AiWriteArgs.money(total)} 元")
                if (geo != null && AiLocation.isHere(address)) {
                    add("送货地址（用手机上当前的位置）：$addressText")
                } else if (address.isNotBlank()) {
                    add("送货地址：$addressText")
                } else {
                    add("送货地址：没填（可事后在页面上补）")
                }
                if (address.isNotBlank() && geo == null) {
                    add(
                        "⚠️ 这个送货地址没在地图上定位到：司机点「高德导航」时会落到高德首页，" +
                            "得自己再搜一遍地址。想准就把地址说得更完整（带上城市和区/路名）。",
                    )
                }
                if (nameDongjia.isNotBlank() || phoneDongjia.isNotBlank()) {
                    add("收货人：" + listOf(nameDongjia, phoneDongjia).filter { it.isNotBlank() }.joinToString(" "))
                }
                if (nameBoss.isNotBlank() || phoneBoss.isNotBlank()) {
                    add("下单人：" + listOf(nameBoss, phoneBoss).filter { it.isNotBlank() }.joinToString(" "))
                }
                if (remark.isNotBlank()) add("备注：$remark")
                add("———— 建好后 ————")
                add("新单进入「待派单」，需要再派单才会到司机手上")
            },
            payload = buildJsonObject {
                // ⚠️ 货主自己下单**不许**带 shipper_id / temp_shipper_name：
                //    后端 `create_order` 对货主是 `target_shipper_id = current.id`，
                //    带了 shipper_id 直接 400「货主下单无需指定货主」。
                if (!selfOrder) {
                    shipper?.id?.let { put("shipper_id", it) }
                    if (shipper == null) put("temp_shipper_name", shipperRaw)
                }
                put("order_date", date.toString())
                put("address_detail", addressText)
                geo?.let {
                    put(GEO_LAT, it.lat.toString())
                    put(GEO_LNG, it.lng.toString())
                }
                put("contact_dongjia_phone", phoneDongjia)
                put("contact_boss_phone", phoneBoss)
                put("contact_dongjia_name", nameDongjia)
                put("contact_boss_name", nameBoss)
                put("remark", remark)
                put(
                    "lines",
                    buildJsonArray {
                        lines.forEach { l ->
                            add(
                                buildJsonObject {
                                    l.productId?.let { put("product_id", it) }
                                    put("product_name_snapshot", l.name)
                                    put("quantity", l.quantity)
                                    put("unit_price", l.unitPrice)
                                    put("line_total", l.lineTotal)
                                },
                            )
                        }
                    },
                )
            },
        )
    }

    override suspend fun commit(payload: JsonObject, idempotencyKey: String) {
        ds.createOrder(payload.toOrderCreateRequest())
    }

    /** 卡片/请求体共用的一行商品（编号只活在这里，绝不回给模型）。 */
    private data class Line(
        val productId: Long?,
        val name: String,
        val quantity: Int,
        val unitPrice: String,
        val lineTotal: String,
    )

    /**
     * 解析 `lines` 数组。
     *
     * 商品名会去商品表里查（**严格**：查不到就拒绝）。
     * 不做成"查不到就当自由文本商品"——那样会建出一张系统里根本不存在的商品的单，
     * 库存扣不了、报表里也会多出一个只出现过一次的商品名。
     */
    private suspend fun parseLines(params: JsonObject): List<Line> {
        val raw = params["lines"] as? JsonArray
            ?: throw AiWriteArgException(
                "缺少 lines：这单要下什么货？要传一个数组，" +
                    "例如 [{\"product\":\"红富士苹果\",\"quantity\":3,\"unit_price\":5.5}]。",
            )
        if (raw.isEmpty()) throw AiWriteArgException("lines 是空的：至少要有一种商品。")
        if (raw.size > MAX_LINES) throw AiWriteArgException("一张单最多 $MAX_LINES 行商品，收到 ${raw.size} 行。")

        val catalog = ds.products()

        return raw.mapIndexed { i, el ->
            val obj = el as? JsonObject
                ?: throw AiWriteArgException("lines 第 ${i + 1} 项不是一个对象，应该形如 {\"product\":\"…\",\"quantity\":1,\"unit_price\":0}。")
            val name = AiWriteArgs.required(obj, "product", "第 ${i + 1} 行是哪个商品？")
            val product = AiWriteArgs.strict(name, catalog, "商品")
            val qty = AiWriteArgs.str(obj, "quantity")?.let { AiWriteArgs.parseQuantity(it) } ?: 1
            val price = AiWriteArgs.parseMoney(AiWriteArgs.str(obj, "unit_price"), "第 ${i + 1} 行的 unit_price", mustPositive = false)
            Line(
                productId = product!!.id,
                name = product.label,
                quantity = qty,
                unitPrice = price.toPlainString(),
                lineTotal = price.multiply(BigDecimal(qty)).setScale(2, RoundingMode.HALF_UP).toPlainString(),
            )
        }
    }

    private companion object {
        const val MAX_LINES = 10
    }
}

// ============================================================== 改司机运费

/**
 * 补录/修改司机运费。
 *
 * MEDIUM 档不是因为"钱不重要"，而是因为**它可改**：
 * 已送达/已撤销之前随时能再改一次，没有终态后果。卡片上仍要写清"原来是 X → 改成 Y"。
 */
class FreightWriteHandler(
    ds: AiWriteDataSource,
    store: AiWritePreviewStore,
) : OrderWriteHandler(ds, store) {

    override val actionId = AiWrites.ORDERS_FREIGHT

    override suspend fun prepare(params: JsonObject): AiWriteOutcome {
        val order = resolveOrder(params)
        requireStatus(order, OrderStatusModel.FREIGHT_EDITABLE, "已送达或已撤销的单不能再改运费")

        val freight = AiWriteArgs.parseMoney(
            AiWriteArgs.str(params, "freight"),
            "freight",
            mustPositive = false,
        )

        return card(
            summary = "改司机运费：${order.orderNo} → ${AiWriteArgs.money(freight)} 元",
            details = buildList {
                addAll(orderLines(order))
                add("———— 改成 ————")
                add("司机运费：${AiWriteArgs.money(freight)} 元" + if (freight.signum() == 0) "（不收运费）" else "")
            },
            payload = buildJsonObject {
                put("order_id", order.id)
                put("freight_fee", freight.toPlainString())
            },
        )
    }

    override suspend fun commit(payload: JsonObject, idempotencyKey: String) {
        ds.updateFreight(payload.reqLong("order_id"), payload.req("freight_fee"))
    }
}

// ============================================================== 现场收款 / 挂账

/** 现场收款确认（货到付款）：把这单记成已收现金，并清掉原来挂的账。 */
class PayOrderHandler(
    ds: AiWriteDataSource,
    store: AiWritePreviewStore,
) : OrderWriteHandler(ds, store) {

    override val actionId = AiWrites.ORDERS_PAY

    override suspend fun prepare(params: JsonObject): AiWriteOutcome {
        val order = resolveOrder(params)
        requireStatus(order, OrderStatusModel.NOT_CANCELLED, "已撤销的单不能收款")

        return card(
            summary = "收款：${order.orderNo} · ${order.amount} 元",
            details = buildList {
                addAll(orderLines(order))
                add("———— 记成 ————")
                add("收款方式：现金（已收）")
                add("原本挂账的话，挂账记录会一起清掉")
            },
            payload = buildJsonObject { put("order_id", order.id) },
        )
    }

    override suspend fun commit(payload: JsonObject, idempotencyKey: String) {
        ds.payOrder(payload.reqLong("order_id"))
    }
}

/** 挂账到某个挂账单位名下。 */
class ChargeOrderHandler(
    ds: AiWriteDataSource,
    store: AiWritePreviewStore,
) : OrderWriteHandler(ds, store) {

    override val actionId = AiWrites.ORDERS_CHARGE

    override suspend fun prepare(params: JsonObject): AiWriteOutcome {
        val order = resolveOrder(params)
        requireStatus(order, OrderStatusModel.NOT_CANCELLED, "已撤销的单不能挂账")

        val unitName = AiWriteArgs.required(params, "unit", "挂到哪个单位名下？把单位名字告诉我。")
        val unit = AiWriteArgs.strict(unitName, ds.arrearsUnits(), "挂账单位")

        return card(
            summary = "挂账：${order.orderNo} · ${order.amount} 元 → ${unit!!.label}",
            details = buildList {
                addAll(orderLines(order))
                add("———— 记成 ————")
                add("收款方式：挂账（未收）")
                add("欠款记在：${unit.label}")
            },
            payload = buildJsonObject {
                put("order_id", order.id)
                put("arrears_unit_id", unit.id)
            },
        )
    }

    override suspend fun commit(payload: JsonObject, idempotencyKey: String) {
        ds.chargeOrder(payload.reqLong("order_id"), payload.reqLong("arrears_unit_id"))
    }
}

// ============================================================== 改单
//
// 第二批订单动作（改单 / 异常 / 拆单 / 批量派单）与第一批共用同一套骨架：
// **先把订单查出来、把状态核对掉，再把"改前 → 改后"摆到卡上**。
// 差别在"错一次的代价"：
//   · 改单：改错了司机会跑错地方 —— 所以卡片必须逐字段写清改前改后；
//   · 标记/解除异常：它是给别人看的警示标记 —— 错标会让一单正常的货看起来有问题；
//   · 拆单：会**新建**若干子单并撤销原单 —— 撤不回来；
//   · 批量派单：一次动多张单 —— 范围错一个，用户看不出来（部分成功最危险）。

/**
 * 改单（送达说明 / 地址 / 联系人电话 / 备注 / 内部备注）。
 *
 * ### 为什么卡片必须写「改前 → 改后」
 * 这是唯一一个"改完之后司机按新信息跑"的动作。用户说"把地址改成 XX 号"，
 * 模型可能听成另一个门牌——只显示"新地址"他看不出来，**两个都摆出来他才会去核对**。
 *
 * ### 为什么至少要有一项要改
 * 一个字段都没带 = 这张卡什么也不改。白弹一次卡比报错更糟：用户会以为改成功了。
 */
class UpdateOrderHandler(
    ds: AiWriteDataSource,
    store: AiWritePreviewStore,
) : OrderWriteHandler(ds, store) {

    override val actionId = AiWrites.ORDERS_UPDATE

    override suspend fun prepare(params: JsonObject): AiWriteOutcome {
        val order = resolveOrder(params)
        // 后端规则：已送达 / 已撤销不可再编辑。核对放在卡片之前，别让用户点了确认才被拒。
        requireStatus(order, OrderStatusModel.EDITABLE, "已送达或已撤销的单不能再改")

        val changes = changesOf(params)
        if (changes.isEmpty()) {
            throw AiWriteArgException(
                "你还没说要改哪一项。这单可以改：送达说明、送货地址、东家电话、老板电话、备注、内部备注。" +
                    "请让用户说清楚改哪一项、改成什么。",
            )
        }

        // 改了送货地址就必须同时换坐标：后端 PATCH 是 `if body.address_lat is not None`
        // 语义，**传 null 清不掉旧坐标**，于是"只改地址文字"会留下**上一条地址的坐标**——
        // 司机点「高德导航」会被带到旧地址，而且没有任何提示。定位不到就**不弹卡**。
        val newAddress = changes.firstOrNull { it.key == "address_detail" }?.to?.takeIf { it.isNotBlank() }
        // 「当前位置」在这里换成**真实地址 + 精确坐标**（拿不到会抛一句"去开定位权限"的中文，不弹卡）
        val geo = newAddress?.let { ds.resolveAddress(it) }
        // 卡片与 payload 都要用**解析后**的地址：句柄那四个字写进订单等于把收货地址废了
        val newAddressText = geo?.address
        if (newAddress != null && geo == null) {
            throw AiWriteArgException(
                "「$newAddress」在地图上定位不到，这单的地址先不改。" +
                    "照改的话司机会被导航到**旧地址**去，而且不会有任何提示。" +
                    "请让用户把地址说得更完整（带上城市和区/路名），或者回 App 用地图选点改一次。",
            )
        }
        // 逐项值：地址那一项用解析后的文字，其余原样
        fun valueOf(c: OrderChange): String = if (c.key == "address_detail") newAddressText ?: c.to else c.to

        return card(
            summary = "改单：${order.orderNo}（改 ${changes.size} 项）",
            details = buildList {
                addAll(orderLines(order))
                add("———— 改动 ————")
                changes.forEach { c -> add("${c.cn}：${c.from.ifBlank { "（空）" }} → ${valueOf(c)}") }
                if (newAddress != null && AiLocation.isHere(newAddress)) {
                    add("🧭 送货地址用的是手机上当前的位置（坐标取自这次定位，司机导航直达）")
                }
                if (newAddress != null) add("（送货地址换了，司机的导航目的地会跟着换）")
            },
            payload = buildJsonObject {
                put("order_id", order.id)
                changes.forEach { c -> put(c.key, valueOf(c)) }
                geo?.let {
                    put(GEO_LAT, it.lat.toString())
                    put(GEO_LNG, it.lng.toString())
                }
            },
        )
    }

    /**
     * 逐项比对：**只收用户真的说了的项**。
     *
     * 顺序即卡片上的顺序；`key` 是后端字段名（`delivery_description` 那一列）。
     * 「改前」只有地址能从 [AiOrderRef] 拿到——其余显示"（空）"是刻意的：
     * 多查一次接口就多一次失败可能，而卡片要用户核对的是**新值**。
     */
    private fun changesOf(params: JsonObject): List<OrderChange> = listOf(
        Triple("delivery", "送达说明", "delivery_description"),
        Triple("address", "送货地址", "address_detail"),
        Triple("dongjia_name", "收货人名称", "contact_dongjia_name"),
        Triple("dongjia_phone", "收货人电话", "contact_dongjia_phone"),
        Triple("boss_name", "下单人名称", "contact_boss_name"),
        Triple("boss_phone", "下单人电话", "contact_boss_phone"),
        Triple("remark", "备注", "remark"),
        Triple("internal_note", "内部备注", "internal_notes"),
    ).mapNotNull { (param, cn, backendKey) ->
        val raw = AiWriteArgs.str(params, param)?.trim() ?: return@mapNotNull null
        OrderChange(cn, "", AiWriteArgs.text(raw, cn, max = 200), backendKey)
    }

    override suspend fun commit(payload: JsonObject, idempotencyKey: String) {
        val fields = buildJsonObject {
            listOf(
                "delivery_description", "address_detail", "contact_dongjia_phone",
                "contact_boss_phone", "contact_dongjia_name", "contact_boss_name",
                "remark", "internal_notes",
                // 改了地址才带上坐标（prepare 已经保证"要改地址就一定查到了坐标"）
                GEO_LAT, GEO_LNG,
            ).forEach { k -> payload.str(k)?.let { put(k, it) } }
        }
        ds.updateOrder(payload.reqLong("order_id"), fields)
    }
}

/** 改单的一行改动（抽出来是为了让「卡片上的顺序」和「payload 的键」同源）。 */
private data class OrderChange(val cn: String, val from: String, val to: String, val key: String)

// ============================================================== 标记异常

/**
 * 标记异常——它不是一个状态，是给所有人看的一枚**警示标记**。
 *
 * 为什么必须写原因：这枚标记会出现在订单列表与报表的异常清单里，
 * 而看的人（别的派单员、以后的你）只有这一行字能判断"这单当时怎么了"。
 */
class MarkOrderExceptionHandler(
    ds: AiWriteDataSource,
    store: AiWritePreviewStore,
) : OrderWriteHandler(ds, store) {

    override val actionId = AiWrites.ORDERS_MARK_EXCEPTION

    override suspend fun prepare(params: JsonObject): AiWriteOutcome {
        val order = resolveOrder(params)
        if (order.isException) {
            throw AiWriteArgException(
                "这单**已经是异常**了，不用再标一次。请如实告诉用户；" +
                    "如果他是想改异常说明，那要先把异常解除再重新标记。",
            )
        }
        requireStatus(order, OrderStatusModel.NOT_CANCELLED, "已撤销的单不该再标异常")

        val reason = AiWriteArgs.required(params, "reason", "为什么标异常？这句话会显示在异常清单里，要说清楚。")
        val reasonText = AiWriteArgs.text(reason, "异常原因", max = 200)
        val expected = AiWriteArgs.str(params, "expected_before")?.let {
            AiWriteArgs.text(it, "预计送达时间", max = 40)
        }

        return card(
            summary = "标记异常：${order.orderNo}",
            details = buildList {
                addAll(orderLines(order))
                add("———— 标记后 ————")
                add("这单会带上一枚「异常」标记，出现在报表中心的异常清单里")
                add("异常原因：$reasonText")
                if (!expected.isNullOrBlank()) add("预计送达：$expected")
                add("（货物状态、司机都不变；不需要时可以「解除异常」）")
            },
            payload = buildJsonObject {
                put("order_id", order.id)
                put("reason", reasonText)
                if (!expected.isNullOrBlank()) put("expected_before", expected)
            },
        )
    }

    override suspend fun commit(payload: JsonObject, idempotencyKey: String) {
        ds.setOrderException(
            id = payload.reqLong("order_id"),
            isException = true,
            reason = payload.str("reason"),
            resolution = null,
            expectedBefore = payload.str("expected_before"),
        )
    }
}

// ============================================================== 解除异常

/**
 * 解除异常：清掉标记 + 记下怎么解决的。
 *
 * 走的是**报表中心「异常与审计」那个按钮同一条路**（`POST /stats/exception-orders/{id}/resolve`），
 * 所以 AI 做完之后页面上看到的状态与手工操作完全一致。
 *
 * ⚠️ 这个端点原来有个后端 bug：解除时把 `is_exception` 又设成了 True，
 * 而异常清单按 `is_exception` 筛——"点了解除、单子还在清单里"。本轮已修
 * （见 `backend/app/api/v1/stats.py` 的注释）。
 */
class ResolveOrderExceptionHandler(
    ds: AiWriteDataSource,
    store: AiWritePreviewStore,
) : OrderWriteHandler(ds, store) {

    override val actionId = AiWrites.ORDERS_RESOLVE_EXCEPTION

    override suspend fun prepare(params: JsonObject): AiWriteOutcome {
        val order = resolveOrder(params)
        if (!order.isException) {
            throw AiWriteArgException(
                "这单现在**不是异常**，没有需要解除的东西。请如实告诉用户，不要顺手做别的操作。",
            )
        }

        val note = AiWriteArgs.required(params, "note", "是怎么解决的？写一句，以后回查靠它。")
        val noteText = AiWriteArgs.text(note, "解决说明", max = 200)

        return card(
            summary = "解除异常：${order.orderNo}",
            details = buildList {
                addAll(orderLines(order))
                add("当前：异常")
                add("———— 解除后 ————")
                add("异常标记清掉，这单从异常清单里消失")
                add("解决说明：$noteText")
                add("（订单状态、司机、金额都不变）")
            },
            payload = buildJsonObject {
                put("order_id", order.id)
                put("note", noteText)
            },
        )
    }

    override suspend fun commit(payload: JsonObject, idempotencyKey: String) {
        ds.resolveOrderException(payload.reqLong("order_id"), payload.str("note"))
    }
}

// ============================================================== 拆单

/**
 * 拆单：把一张待派单按比例拆成几张子单，原单撤销留痕。
 *
 * ### 为什么 `parts` 收的是"比例"而不是"数量"
 * 后端就是这么定义的（`parts` 是各份权重，商品数量按比例分，余数归首份）。
 * 卡片把"你要的比例"和"会拆成几单"都写出来，用户不必懂权重也能核对。
 *
 * ### 为什么它是 HIGH
 * 它**新建**若干订单并撤销原单——撤销是终态，拆错了只能重建。
 */
class SplitOrderHandler(
    ds: AiWriteDataSource,
    store: AiWritePreviewStore,
) : OrderWriteHandler(ds, store) {

    override val actionId = AiWrites.ORDERS_SPLIT

    override suspend fun prepare(params: JsonObject): AiWriteOutcome {
        val order = resolveOrder(params)
        requireStatus(order, OrderStatusModel.ASSIGNABLE, "只有「待派单」的单能拆")

        val raw = AiWriteArgs.required(
            params,
            "parts",
            "按什么比例拆？例如「5,3,2」表示三等份按 5:3:2 分。至少两份。",
        )
        val parts = parseParts(raw)
        val total = order.amount.toBigDecimalOrNull() ?: BigDecimal.ZERO

        return card(
            summary = "拆单：${order.orderNo} → ${parts.size} 单（${parts.joinToString(":")}）",
            details = buildList {
                addAll(orderLines(order))
                add("———— 拆成 ————")
                val weight = parts.sum()
                parts.forEachIndexed { i, w ->
                    val share = if (weight == 0) BigDecimal.ZERO else total
                        .multiply(BigDecimal(w))
                        .divide(BigDecimal(weight), 2, RoundingMode.HALF_UP)
                    add("第 ${i + 1} 单：占 $w 份（约 ${AiWriteArgs.money(share)} 元，单号加后缀 -${i + 1}）")
                }
                add("商品数量按 ${parts.joinToString(":")} 的比例分到各子单，除不尽的余数归第 1 单")
                add("原单会变成「已撤销」留痕——撤不回来，要合并只能重新建单")
                add("子单都是「待派单」，之后要分别派车")
            },
            payload = buildJsonObject {
                put("order_id", order.id)
                put("parts", parts.joinToString(","))
            },
        )
    }

    /** `5,3,2` / `5 3 2` / `5:3:2` / `5、3` 都收；给不出 ≥2 份就报错，**绝不默认平均分**。 */
    private fun parseParts(raw: String): List<Int> {
        val nums = Regex("\\d+").findAll(raw).map { it.value }.toList()
        val parts = nums.map { AiWriteArgs.parseQuantity(it) }
        if (parts.size < 2) {
            throw AiWriteArgException(
                "拆单至少要两份（后端要求），你说的「$raw」只解析出 ${parts.size} 份。" +
                    "请让用户说清楚要怎么分，例如「按 5:3:2 拆成三单」。",
            )
        }
        if (parts.size > AiWrites.MAX_SPLIT_PARTS) {
            throw AiWriteArgException("一次最多拆 ${AiWrites.MAX_SPLIT_PARTS} 单，你说的份数太多了。")
        }
        if (parts.any { it <= 0 }) {
            throw AiWriteArgException("比例里不能有 0，请让用户重新给一份拆分比例。")
        }
        return parts
    }

    override suspend fun commit(payload: JsonObject, idempotencyKey: String) {
        val parts = payload.req("parts").split(",").mapNotNull { it.trim().toIntOrNull() }
        ds.splitOrder(payload.reqLong("order_id"), parts)
    }
}

// ============================================================== 批量派单

/**
 * 批量派单：把**多张待派单**一次派给同一个司机。
 *
 * ### 为什么它比单张派单更危险（所以是 HIGH）
 * 单张派单的范围错一眼能看出来（就那一单）；批量派单的范围错 1 张，用户核对 20 行时
 * 根本发现不了——后果是**多派一趟车**。所以：
 * 1. 单号必须逐个解析、逐个核对状态，**有一个不对就整批不做**（不做部分成功）；
 * 2. 卡片把每一单都列出来，用户逐行核对"是不是这些"；
 * 3. 有数量上限，避免"今天所有单都派给老王"一句话动几十单。
 *
 * ⚠️ 后端这个端点**没有运费字段**：页面上批量派单也不能逐单定价。
 * 所以模型如果给了运费，卡片要明说"不会写进去"，而不是悄悄丢掉。
 */
class BatchAssignOrderHandler(
    ds: AiWriteDataSource,
    store: AiWritePreviewStore,
) : OrderWriteHandler(ds, store) {

    override val actionId = AiWrites.ORDERS_BATCH_ASSIGN

    override suspend fun prepare(params: JsonObject): AiWriteOutcome {
        val raw = AiWriteArgs.required(
            params,
            "orders",
            "要派哪几张单？把订单号都给我（逗号或空格分开）。",
        )
        val refs = raw.split(',', '，', ' ', '\n', '、').map { it.trim() }.filter { it.isNotEmpty() }
        if (refs.size < 2) {
            throw AiWriteArgException("批量派单至少要两张单（只有一张就用普通派单）。请让用户把单号都列出来。")
        }
        if (refs.size > AiWrites.MAX_BATCH_ASSIGN) {
            throw AiWriteArgException(
                "一次最多派 ${AiWrites.MAX_BATCH_ASSIGN} 张，你说的有 ${refs.size} 张。" +
                    "请分批来，或者让用户在 App 的待派单池里用「批量派单」。",
            )
        }

        val orders = refs.map { resolveOrder(buildJsonObject { put("order", it) }) }
        orders.forEach { requireStatus(it, OrderStatusModel.ASSIGNABLE, "只有「待派单」的单能派单（这一张不是）") }

        val driverName = AiWriteArgs.required(params, "driver", "这批单派给谁？把司机姓名告诉我。")
        val driver = AiWriteArgs.strict(driverName, ds.drivers(), "司机")
        val collectCash = AiWriteArgs.parseBool(params, "collect_cash")
        val note = AiWriteArgs.text(AiWriteArgs.str(params, "note"), "给司机的备注")
        val freight = AiWriteArgs.str(params, "freight")?.let {
            AiWriteArgs.parseMoney(it, "freight", mustPositive = false)
        }
        val sum = orders
            .fold(BigDecimal.ZERO) { a, o -> a.add(o.amount.toBigDecimalOrNull() ?: BigDecimal.ZERO) }
            .setScale(2, RoundingMode.HALF_UP)

        return card(
            summary = "批量派单：${orders.size} 张 → ${driver!!.label}",
            details = buildList {
                add("———— 这些单 ————")
                orders.forEach { add("· ${it.label()}") }
                add("合计金额：${AiWriteArgs.money(sum)} 元")
                add("———— 派给 ————")
                add("司机：${driver.label}")
                if (freight != null) {
                    add("⚠️ 批量派单没有逐单运费这个字段：你说的 $freight 元不会写进去（运费要事后再录）")
                }
                if (collectCash != null) {
                    add(if (collectCash) "收款方式：司机送达时收现金" else "收款方式：送达后挂账")
                } else {
                    add("收款方式：按各单原本的设置")
                }
                if (note.isNotBlank()) add("给司机的备注：$note")
                add("司机会一次收到这 ${orders.size} 条派单")
            },
            payload = buildJsonObject {
                put("order_ids", orders.joinToString(",") { it.id.toString() })
                put("driver_id", driver.id)
                put("internal_note", note)
                collectCash?.let { put("collect_cash", it) }
            },
        )
    }

    override suspend fun commit(payload: JsonObject, idempotencyKey: String) {
        val ids = payload.req("order_ids").split(",").mapNotNull { it.trim().toLongOrNull() }
        ds.batchAssignOrders(
            orderIds = ids,
            driverId = payload.reqLong("driver_id"),
            note = payload.str("internal_note"),
            collectCash = payload.bool("collect_cash"),
        )
    }
}

// ============================================================== 补导航（2026-09-20）

/**
 * 补导航信息：把**共享地点库里已有**的坐标写到一张还没有坐标的单上。
 *
 * ### 用户为什么要它（原话）
 * > 同时派单员其实也可以对这些地点…叫 AI 补上地点，也可以叫 AI 补上照片。
 *
 * 派单员坐在电脑前，他没有坐标（那是到过现场的人测出来的）。所以这条路**不是**
 * "让模型编一个坐标"，而是"让模型**指**库里哪一个点"—— 坐标由 App 从库里取。
 * 这也正是当初把这个端点列进"永久不做"的原因，现在换了个入口把它打开了：
 * **模型仍然一个经纬度都碰不到**。
 *
 * ### 三条硬约束（都在 prepare 里先核对，绝不"点了确认才报错"）
 * 1. 这单**还没有坐标**：后端对已有坐标的单一律 400（错坐标比没坐标更危险），
 *    所以卡片根本不弹，直接告诉用户"已经有了"；
 * 2. 这单不能是已撤销的（撤销的单不需要导航）；
 * 3. 用哪个点必须**说全**：对不上、对上多个都拒绝（`AiWriteArgs.strict`）——
 *    「并到隔壁那家」的代价是司机照着跑，而且看不出来。
 */
class FillNavigationHandler(
    ds: AiWriteDataSource,
    store: AiWritePreviewStore,
) : OrderWriteHandler(ds, store) {

    override val actionId = AiWrites.ORDERS_FILL_NAV

    override suspend fun prepare(params: JsonObject): AiWriteOutcome {
        val order = resolveOrder(params)
        requireStatus(order, OrderStatusModel.NOT_CANCELLED, "已撤销的单不需要补导航信息")
        if (order.hasNav) {
            throw AiWriteArgException(
                "${order.orderNo} 已经有导航信息了 —— 这个动作**只补不改**" +
                    "（把对的坐标改成错的，比没有坐标更糟）。位置不对的话，" +
                    "请让派单员在地图上重新标一个点，不要在这条路上改。",
            )
        }

        val wanted = AiWriteArgs.required(params, "place", "用共享地点库里的哪个地点？把地点名告诉我。")
        val name = AiWriteArgs.strict(wanted, ds.places(), "共享地点")
        // ⛔ 坐标**从库里取**（`placeById`），不是从参数里取 —— 模型说的话里没有任何数
        val point = name?.let { ds.placeById(it.id) }
        if (point == null || point.addressLat.isNullOrBlank() || point.addressLng.isNullOrBlank()) {
            throw AiWriteArgException(
                "共享地点库里的「$wanted」没有坐标，补不了导航。请让用户先在地图上标一个点" +
                    "（下单时的「地图选点」或订单详情里的「补导航」都会把它存进共享库）。",
            )
        }
        val placeName = AiWriteArgs.str(params, "name").orEmpty().trim().ifBlank { name.label }

        return card(
            summary = "补导航：${order.orderNo} → ${point.name.ifBlank { placeName }}",
            details = buildList {
                addAll(orderLines(order))
                add("———— 用这个点的坐标 ————")
                // 坐标写在脸上：用户核对的是这两个数，不是那句话
                add("地点：${point.name.ifBlank { placeName }}")
                if (point.detailAddress.isNotBlank()) add("地址：${point.detailAddress}")
                add("坐标：${point.addressLat}, ${point.addressLng}")
                add("———— 会写三处 ————")
                add("这单的导航、货主的地点库、全库共享地点库")
                add("⚠️ 写进去就撤不回来（没有「取消导航」这个动作）—— 核对好坐标再确定")
            },
            payload = buildJsonObject {
                put("order_id", order.id)
                put("address_lat", point.addressLat.orEmpty())
                put("address_lng", point.addressLng.orEmpty())
                put("name", placeName)
                put("detail", point.detailAddress)
            },
        )
    }

    override suspend fun commit(payload: JsonObject, idempotencyKey: String) {
        ds.fillOrderNavigation(
            orderId = payload.reqLong("order_id"),
            lat = payload.req("address_lat"),
            lng = payload.req("address_lng"),
            name = payload.str("name").orEmpty(),
            detail = payload.str("detail").orEmpty(),
        )
    }
}

// ------------------------------------------------------------------ 小工具
//
// payload 取值（`str/req/reqLong/bool`）在 AiWriteMasterData.kt 里**只有一份**，
// 声明式动作和手写动作共用。这里刻意不再定义一遍——两份取值的实现迟早会在
// 「键缺失时是报错还是返回 null」上分叉，而那个分叉只会在线上出现。