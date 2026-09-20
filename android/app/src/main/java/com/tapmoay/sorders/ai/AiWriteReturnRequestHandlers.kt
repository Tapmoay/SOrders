package com.tapmoay.sorders.ai

import com.tapmoay.sorders.core.OrderStatusModel
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

/**
 * 退货申请的四个处理器（2026-09-21 用户要求）。
 *
 * 用户原话：「批发商……他要进行退货，他**可以直接在订单上**作退货。然后我们的那个派单员，
 * 他会接到一个**通知**，这个时候派单员就会去帮他进行一个退货的操作。**派单员进行完了之后，
 * 整个才进行库存才会发生一个改变和变动**」＋「同时**货主的 AI 可以代替货主进行申请退货**」。
 *
 * ## 四条动作、两个人（这个文件里最要紧的一件事）
 *
 * | 处理器 | 谁 | 卡片上必须写出来的一句话 |
 * | --- | --- | --- |
 * | [ApplyReturnRequestHandler] | 货主 | 「账本、库存、订单状态**现在都不动**」 |
 * | [WithdrawReturnRequestHandler] | 货主 | 「记录留着，派单员看得到你提过又撤了」 |
 * | [RejectReturnRequestHandler] | 派单员 | 「驳回不动账、不动库存、不改订单」 |
 * | [FulfillReturnRequestHandler] | 派单员 | 「**库存和账本在这一刻才变**」 |
 *
 * 第一句和最后一句是同一件事的两面：用户要的正是"申请与执行分开"。卡片上不写清楚，
 * 货主会以为点完就退了（然后发现库存没动，以为系统坏了），派单员会以为自己只是在"批一下"。
 *
 * ## 三道前置核对（理由同订单域那一批）
 * 1. **订单必须是「已送达」** —— 后端只认这一档，等用户点了确认才报错就是白弹一张卡；
 * 2. **这一单有没有已经待处理的申请** —— 后端"一张单同时只允许一条"，不先查就会发一张必然失败的卡；
 * 3. **数量不许超过可退上限**（[AiReturnableLine.maxReturnable] 一处算，与界面、与后端同源）。
 */
abstract class ReturnRequestWriteHandler(
    ds: AiWriteDataSource,
    store: AiWritePreviewStore,
) : OrderWriteHandler(ds, store) {

    /**
     * 找这一单**待处理**的那张申请。
     *
     * ⚠️ 按**订单**找而不是按申请单号：模型拿不到内部编号（第一条硬规矩），
     *    而"一张单同时只有一条待处理申请"这条后端规则保证了按订单找是**唯一**的。
     *    真出现第二条（历史数据）时 [firstPending] 只取最新那条，并在卡片上把明细写清楚 ——
     *    用户核对的是商品和件数，不是编号。
     */
    protected suspend fun firstPending(orderId: Long): AiReturnRequest? =
        ds.pendingReturnRequests(orderId).firstOrNull { it.isPending }

    protected suspend fun pendingOrFail(orderId: Long, orderNo: String, who: String): AiReturnRequest =
        firstPending(orderId) ?: throw AiWriteArgException(
            "订单 $orderNo 上现在没有待处理的退货申请，没有可$who 的。" +
                "请让用户确认一下单号；如果货主还没提过申请，那这件事要先由他发起（货主端「申请退货」）。",
        )

    /** 卡片上"这张申请是什么"的那几行。 */
    protected fun requestLines(req: AiReturnRequest): List<String> = buildList {
        add("申请人：${req.shipperName.ifBlank { "（未填）" }}")
        add("申请内容：${req.linesText()}")
        if (req.note.isNotBlank()) add("申请备注：${req.note}")
        add("申请状态：${req.statusLabel.ifBlank { req.status }}")
    }

    /**
     * 解析 `lines`；**留空 = 整单申请**（每行都申请到余量上限）。
     *
     * ⚠️ 与 `ReturnOrderHandler.parseItems` 同一套判据与同一套话术（数量上限、重名、超额），
     *    只是把"退"换成"申请退" —— 两个动作共用一套上限口径，卡片才不会一处说 4、一处说 3。
     */
    protected fun parseApplyItems(
        params: JsonObject,
        available: List<AiReturnableLine>,
        maxItems: Int,
    ): List<Pair<AiReturnableLine, Int>> {
        val raw = params["lines"] as? JsonArray
        if (raw == null || raw.isEmpty()) {
            return available.map { it to it.maxReturnable }
        }
        if (raw.size > maxItems) {
            throw AiWriteArgException("一次最多申请退 $maxItems 种商品，收到 ${raw.size} 种。")
        }
        val pool = available.map { AiName(it.id, it.name) }
        val out = mutableListOf<Pair<AiReturnableLine, Int>>()
        raw.forEachIndexed { i, el ->
            val obj = el as? JsonObject
                ?: throw AiWriteArgException("lines 第 ${i + 1} 项不是一个对象，应该形如 {\"product\":\"…\",\"quantity\":2}。")
            val name = AiWriteArgs.required(obj, "product", "第 ${i + 1} 行申请退哪个商品？")
            val hit = AiWriteArgs.strict(name, pool, "可申请退货的商品")
            val line = available.first { it.id == hit!!.id }
            val qty = AiWriteArgs.str(obj, "quantity")?.let { AiWriteArgs.parseQuantity(it) } ?: 1
            if (qty > line.maxReturnable) {
                throw AiWriteArgException(
                    "「${line.name}」最多只能申请退 ${line.maxReturnable} 件（${line.label()}），你填了 $qty。",
                )
            }
            if (out.any { it.first.id == line.id }) {
                throw AiWriteArgException("「${line.name}」在 lines 里出现了两次，请合成一行。")
            }
            out += line to qty
        }
        return out
    }

    /** 商品行的显示名 + 件数（卡片与 payload 共用一份，不许两处各拼一遍）。 */
    protected fun itemLines(picked: List<Pair<AiReturnableLine, Int>>): List<String> =
        picked.map { (line, qty) -> "· ${line.name}  $qty 件　（${line.label()}）" }
}

// ============================================================== 货主：申请
/**
 * **申请退货**（货主）。
 *
 * ### 为什么是 MEDIUM 而不是 LOW
 * 它不改账、不改库存，但它**会通知派单员** —— 现实世界里有人会因此动身去看货。
 * 模型自己判断"客户说要退"就直接发出去，与本仓库"缺信息就问、绝不替用户决定"那条规则相冲。
 *
 * ### 卡片上最要紧的一句
 * 「账本、库存、订单状态**现在都不动**」。用户（尤其批发商）最怕的是
 * "我在这儿点一下，公司的账和库存跟着变了" —— 而这正是本流程要保证不发生的事。
 */
class ApplyReturnRequestHandler(
    ds: AiWriteDataSource,
    store: AiWritePreviewStore,
) : ReturnRequestWriteHandler(ds, store) {

    override val actionId = AiWrites.RETURN_REQUEST_APPLY

    override suspend fun prepare(params: JsonObject): AiWriteOutcome {
        val order = resolveOrder(params)
        requireStatus(order, OrderStatusModel.RETURNABLE, "只有「已送达」的单能申请退货（货还没送到的请用「撤销」）")

        // 已经有一张待处理的了：说清楚"要改就先撤回"，而不是弹一张点了必然失败的卡
        // （后端 `submit` 的判据一模一样，这里只是把它提前到卡片之前）。
        val existing = firstPending(order.id)
        if (existing != null) {
            throw AiWriteArgException(
                "订单 ${order.orderNo} 已经有一张待处理的退货申请了（${existing.linesText()}），派单员还没处理。" +
                    "要改就先把那一张撤回（动作「撤回退货申请」），再重新申请一次。",
            )
        }

        val lines = ds.returnableLines(order.id)
        if (lines.isEmpty()) {
            throw AiWriteArgException("这一单一件商品都没有，申请不了退货。请让用户打开订单详情看一眼。")
        }
        val available = lines.filter { it.maxReturnable > 0 }
        if (available.isEmpty()) {
            throw AiWriteArgException(
                "这一单没有可以申请退货的商品了：" + lines.joinToString("；") { it.label() } +
                    "。请如实告诉用户（已经退完的部分不要再申请一次）。",
            )
        }

        val picked = parseApplyItems(params, available, AiWriteReturnRequest.MAX_ITEMS)
        val totalQty = picked.sumOf { it.second }
        val note = AiWriteArgs.text(AiWriteArgs.str(params, "note"), "申请备注")

        return card(
            summary = "申请退货：${order.orderNo} · $totalQty 件（等派单员处理）",
            details = buildList {
                addAll(orderLines(order))
                add("———— 要申请退的 ————")
                addAll(itemLines(picked))
                add("合计：$totalQty 件")
                add("———— 会发生什么 ————")
                add("① 现在就发出这张申请，派单员会收到一条通知")
                add("② 账本、库存、订单状态现在都不动（货还在客户手里）")
                add("③ 派单员实际办理之后：退回来的货才补回库存、账上才按这几行红冲、这单收过钱才退款")
                add("数量是锁死的：派单员只能按这张申请退、不能改；要改得先撤回再重新申请")
                add("⚠️ 已经报过货损的那几件申请不了（那部分已经按损失计过账）")
                if (note.isNotBlank()) add("申请备注：$note")
            },
            payload = buildJsonObject {
                put("order_id", order.id)
                put("order_no", order.orderNo)
                put("note", note)
                put(
                    "items",
                    buildJsonArray {
                        picked.forEach { (line, qty) ->
                            add(
                                buildJsonObject {
                                    put("order_product_id", line.id)
                                    put("product_name", line.name)
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
            ?: throw AiWriteArgException("申请明细丢了，请重新发起一次。")
        val pairs = items.map { el ->
            val obj = el as? JsonObject ?: throw AiWriteArgException("申请明细格式不对，请重新发起一次。")
            obj.reqLong("order_product_id") to obj.reqInt("quantity")
        }
        ds.applyReturnRequest(payload.reqLong("order_id"), pairs, payload.str("note").orEmpty())
    }
}

// ============================================================== 货主：撤回
/**
 * **撤回我的退货申请**（货主）。
 *
 * 为什么这个动作必须存在（不是"顺手加的"）：数量是锁死的，所以"想改数量"的唯一路径
 * 就是**撤回重提**。手机上有这个按钮，助手没有的话，货主对助手说"我改成退 2 件"会得到
 * 一句"做不到"——而他自己在手机上明明能做（用户定的规矩：手机能做到的，助手也要能做）。
 */
class WithdrawReturnRequestHandler(
    ds: AiWriteDataSource,
    store: AiWritePreviewStore,
) : ReturnRequestWriteHandler(ds, store) {

    override val actionId = AiWrites.RETURN_REQUEST_WITHDRAW

    override suspend fun prepare(params: JsonObject): AiWriteOutcome {
        val order = resolveOrder(params)
        val pending = pendingOrFail(order.id, order.orderNo, "撤回")

        return card(
            summary = "撤回退货申请：${order.orderNo} · ${pending.linesText()}",
            details = buildList {
                addAll(orderLines(order))
                add("———— 要撤回的申请 ————")
                addAll(requestLines(pending))
                add("———— 会发生什么 ————")
                add("这张申请变成「已撤回」，派单员那边就不能再办理它了")
                add("记录留着：派单员看得到你提过又撤了（这不是删除）")
                add("账本、库存、订单状态本来就没动过，撤回之后也一样")
                add("撤回之后可以重新申请一次（想改数量只能这么改）")
            },
            payload = buildJsonObject {
                put("request_id", pending.id)
                put("order_no", order.orderNo)
                put("lines", pending.linesText())
            },
        )
    }

    override suspend fun commit(payload: JsonObject, idempotencyKey: String) {
        ds.withdrawReturnRequest(payload.reqLong("request_id"))
    }
}

// ============================================================== 派单员：驳回
/**
 * **驳回退货申请**（派单员）。
 *
 * 理由**必填**：这是货主唯一能拿到的答复。不填的后果是他只能反复重提，
 * 而派单员每次都要重新看一遍（这条流程在真实门店里每天都在发生）。
 */
class RejectReturnRequestHandler(
    ds: AiWriteDataSource,
    store: AiWritePreviewStore,
) : ReturnRequestWriteHandler(ds, store) {

    override val actionId = AiWrites.RETURN_REQUEST_REJECT

    override suspend fun prepare(params: JsonObject): AiWriteOutcome {
        val order = resolveOrder(params)
        val pending = pendingOrFail(order.id, order.orderNo, "驳回")
        val reason = AiWriteArgs.required(params, "reason", "为什么驳回？这个原因会发给申请人。")

        return card(
            summary = "驳回退货申请：${order.orderNo} · ${pending.linesText()}",
            details = buildList {
                addAll(orderLines(order))
                add("———— 这张申请 ————")
                addAll(requestLines(pending))
                add("———— 会发生什么 ————")
                add("这张申请变成「已驳回」，并把下面这句话发给申请人")
                add("驳回原因：$reason")
                add("账本、库存、订单一律不动（这一单仍然是「${order.statusCn}」）")
                add("驳回之后货主可以重新提一张（他会看到这个原因）")
            },
            payload = buildJsonObject {
                put("request_id", pending.id)
                put("order_no", order.orderNo)
                put("reason", reason)
                put("lines", pending.linesText())
            },
        )
    }

    override suspend fun commit(payload: JsonObject, idempotencyKey: String) {
        ds.rejectReturnRequest(payload.reqLong("request_id"), payload.str("reason").orEmpty())
    }
}

// ============================================================== 派单员：办理（真的退货）
/**
 * **办理退货申请** = 照这张申请**实际退货**（派单员）。
 *
 * ### 为什么是 HIGH
 * 这是全套动作里唯一真的退货的一条：一次动四样（账本红冲、库存回补、可能真退钱给客户、
 * 订单状态），与 `orders.return` 同级 —— 撤销只是"让一张没发生的单作废"，
 * 这条是"已经发生的生意改了一部分"，赔的是真金白银。
 *
 * ### 数量锁死（用户拍板）
 * 工具参数里**没有数量**，`commit` 也不传数量：数量只能来自申请单本身。
 * 卡片上因此必须把"按哪几件、各几件"逐行写出来让派单员核对 ——
 * 他能做的决定只有两个：**照办**，或者**驳回**（让货主重新申请）。
 *
 * ⚠️ 数量在申请之后可能变小（别的退货先办了 / 司机补报了货损）：那种情况下后端会拒绝，
 *    并把"只剩 N 件可退"原样回给用户。这里**不提前替后端判断** ——
 *    可退量以取数那一刻的库为准，App 侧算一遍只会多一个可能过期的数。
 */
class FulfillReturnRequestHandler(
    ds: AiWriteDataSource,
    store: AiWritePreviewStore,
) : ReturnRequestWriteHandler(ds, store) {

    override val actionId = AiWrites.RETURN_REQUEST_FULFILL

    override suspend fun prepare(params: JsonObject): AiWriteOutcome {
        val order = resolveOrder(params)
        requireStatus(
            order,
            OrderStatusModel.RETURNABLE,
            "只有「已送达」的单能按申请退货（这张单已经不是已送达了，退不了）",
        )
        val pending = pendingOrFail(order.id, order.orderNo, "办理")

        return card(
            summary = "办理退货：${order.orderNo} · ${pending.linesText()}",
            details = buildList {
                addAll(orderLines(order))
                add("———— 这张申请 ————")
                addAll(requestLines(pending))
                add("———— 会发生什么（确认后就发生）————")
                add("账本按这几行红冲：营业额减掉这几行的金额")
                add("退回来的货补回库存")
                add("这单如果已经收过钱：自动记一笔退给客户的现金（金额按「收过多少、退过多少」由系统算）")
                add("这几件是全单最后没退的 → 订单变成「已退货」；否则仍然是「已送达」，剩下的还欠着")
                add("⚠️ 数量锁死：只能按申请单上的数量退，不能改（要改请先驳回，让货主重新申请）")
                add("⚠️ 已经报过货损的那几件退不了（那部分已经按损失计过账）")
                add("办完会给货主发一条消息（退了什么、退了多少钱）")
            },
            payload = buildJsonObject {
                put("request_id", pending.id)
                put("order_no", order.orderNo)
                put("lines", pending.linesText())
            },
        )
    }

    override suspend fun commit(payload: JsonObject, idempotencyKey: String) {
        ds.fulfillReturnRequest(payload.reqLong("request_id"))
    }
}
