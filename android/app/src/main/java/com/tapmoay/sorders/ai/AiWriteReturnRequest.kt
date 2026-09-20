package com.tapmoay.sorders.ai

/**
 * **退货申请**的动作清单（2026-09-21 用户要求）。
 *
 * 用户原话：「批发商……他要进行退货，他**可以直接在订单上**作退货。然后我们的那个派单员，
 * 他会接到一个**通知**，这个时候派单员就会去帮他进行一个退货的操作。**派单员进行完了之后，
 * 整个才进行库存才会发生一个改变和变动**。也就是说**批发商只是一个申请，派单员才是实际性的操作**」。
 * 紧接着又补了一句：「同时**货主的 AI 可以代替货主进行申请退货**」。
 *
 * ## 四个动作分给两个人（这是本组动作唯一的重点）
 *
 * | 动作 | 谁 | 风险 | 它到底动了什么 |
 * | --- | --- | --- | --- |
 * | [AiWrites.RETURN_REQUEST_APPLY] | 货主 | MEDIUM | **只写一张申请单**，给派单员发一条站内信 |
 * | [AiWrites.RETURN_REQUEST_WITHDRAW] | 货主 | MEDIUM | 把申请单标成「已撤回」 |
 * | [AiWrites.RETURN_REQUEST_REJECT] | 派单员 | MEDIUM | 标成「已驳回」+ 必填理由 |
 * | [AiWrites.RETURN_REQUEST_FULFILL] | 派单员 | **HIGH** | ★ 真的退货：账本红冲、库存回补、可能退现、订单状态 |
 *
 * ## ⛔ 前三个动作一行钱、一件货都不许动
 * 这是用户那句话的直接落地，也是这套流程存在的意义：货主按一下**不能**改自己的应收与公司库存，
 * 否则 `core/rbac.py` 当初不给货主退货权的理由（"这份账就没有第二个人核对了"）当场作废。
 * 后端的执行入口只有 `services/order_return.py::return_order` 一处，
 * 而 `fulfill` 是**唯一**会调到它的 AI 动作。
 *
 * ## 为什么货主那两个动作不是 `memberOnly`
 * 用户拍板「**所有货主都能申请**」（不只是批发商）：普通货主同样会遇到要退货的情况，
 * 而"申请"不涉及任何越权（它不改既成事实）。⛔ 别把它收窄成 `memberOnly = true` ——
 * 那会让一半订单没有退货入口。
 */
object AiWriteReturnRequest {

    /** 一次申请最多几种商品（够用且便于核对，与 `orders.return` 同一档）。 */
    const val MAX_ITEMS = 20

    val ACTIONS: List<AiWriteAction> = listOf(
        // ---------------------------------------------------------------- 货主
        AiWriteAction(
            id = AiWrites.RETURN_REQUEST_APPLY,
            title = "申请退货",
            // MEDIUM：它**不改账、不改库存**，但会**通知派单员**（现实世界里有人会因此动身）——
            // 所以仍然要用户点一下确认，而不是模型说完就发出去。
            risk = AiWriteRisk.MEDIUM,
            group = AiWrites.G_RETURN_REQUEST,
            blurb = "对一张**已送达**的订单提出退货申请：可以整单申请，也可以只申请其中几个商品。" +
                "**这只是申请**——库存、账本、订单状态现在都不会变，货还在客户手上；" +
                "派单员收到通知并**实际办理**之后，库存才回补、账上才红冲。数量会锁死（派单员不能改）。",
            params = listOf(
                AiWriteParam(
                    "order",
                    "订单",
                    required = true,
                    hint = "必填，订单号。只能申请**自己的、已送达的**订单",
                ),
                AiWriteParam(
                    "lines",
                    "退哪些商品",
                    kind = AiWriteParamKind.TEXT,
                    hint = "**留空 = 整单申请**。只申请一部分时传数组：" +
                        "[{\"product\":\"红富士苹果\",\"quantity\":2}]（product 传商品名，quantity 只传数字）",
                ),
                AiWriteParam("note", "申请备注", hint = "可选，一句话（如「有两件破了」），派单员会看到"),
            ),
            // ⛔ 只有货主：派单员没有"申请退货"这件事（他自己就能直接退）。
            //    不标的话它会落进派单员清单 —— `forRole(DISPATCHER) = ALL 减会员专属`，
            //    而点下去必被后端以「这不是你的订单」拒绝（"能看见但一定失败"）。
            roles = setOf(AiRole.SHIPPER),
        ),
        AiWriteAction(
            id = AiWrites.RETURN_REQUEST_WITHDRAW,
            title = "撤回退货申请",
            risk = AiWriteRisk.MEDIUM,
            group = AiWrites.G_RETURN_REQUEST,
            blurb = "把**自己刚提的**退货申请撤回（**不是删除**：记录留着，派单员看得到「他提过又撤了」）。" +
                "撤回之后可以重新申请一次（改数量只能这么改：数量是锁死的）。",
            params = listOf(
                AiWriteParam(
                    "order",
                    "订单",
                    required = true,
                    hint = "必填，订单号。这一单上**待处理**的那张申请会被撤回",
                ),
            ),
            roles = setOf(AiRole.SHIPPER),
        ),
        // ---------------------------------------------------------------- 派单员
        AiWriteAction(
            id = AiWrites.RETURN_REQUEST_REJECT,
            title = "驳回退货申请",
            risk = AiWriteRisk.MEDIUM,
            group = AiWrites.G_RETURN_REQUEST,
            blurb = "驳回货主提的退货申请，**必须写原因**（那是货主唯一能拿到的答复）。" +
                "驳回**不动**账本、不动库存、不改订单——只是把这张申请关掉。",
            params = listOf(
                AiWriteParam("order", "订单", required = true, hint = "必填，订单号"),
                AiWriteParam(
                    "reason",
                    "驳回原因",
                    required = true,
                    hint = "必填，会**推送给申请人**，所以要写清楚（如「货已拆封，不能退」）",
                ),
            ),
            // 派单员专属：货主既看不到"驳回"也不该看到（他的申请只有派单员能驳回）。
            // 虽然它没进 `SHIPPER_ACTIONS` 白名单，这里仍然显式写出来 ——
            // 白名单是"加进去才有"，这个字段是"写清楚归谁"，两边都写着才不会有人改错一边。
            roles = setOf(AiRole.DISPATCHER),
        ),
        AiWriteAction(
            id = AiWrites.RETURN_REQUEST_FULFILL,
            title = "办理退货申请",
            // HIGH：这是全套动作里唯一**真的退货**的一条 —— 一次动四样（账本红冲、库存回补、
            // 可能真退钱给客户、订单状态）。与 `orders.return` 同级，理由完全相同。
            risk = AiWriteRisk.HIGH,
            group = AiWrites.G_RETURN_REQUEST,
            blurb = "照货主那张申请**实际退货**：账本按这几行红冲（营业额减）、退回来的货**补回库存**、" +
                "这单如果已经收过钱就自动记一笔退款、整单退完变「已退货」。" +
                "**数量锁死**：只能按申请单上的数量退，不能改（要改先驳回，让货主重新申请）。" +
                "确认之后会给货主发一条消息。",
            params = listOf(
                AiWriteParam(
                    "order",
                    "订单",
                    required = true,
                    hint = "必填，订单号。这一单上**待处理**的那张申请会被办理",
                ),
            ),
            roles = setOf(AiRole.DISPATCHER),
        ),
    )
}

/**
 * 一张退货申请（模型看得见的形状：**没有内部编号**，只有单号、商品名、件数与中文状态）。
 *
 * ⚠️ 中文状态名用后端给的 `status_label`（[AiWrites] 那一侧不许再写一套映射：
 * 后端加了新状态，前端就会显示 `pending` 这种原始码）。
 */
data class AiReturnRequest(
    val id: Long,
    val orderId: Long,
    val orderNo: String,
    val status: String,
    val statusLabel: String,
    val shipperName: String,
    val note: String,
    val rejectReason: String,
    val handledByName: String,
    /** 商品名 + 件数（模型只认名字，不认编号）。 */
    val lines: List<Pair<String, Int>>,
) {
    val isPending: Boolean get() = status == "pending"

    /** 一行摘要：`红富士苹果×2、白菜×1`。 */
    fun linesText(): String =
        lines.joinToString("、") { "${it.first}×${it.second}" }.ifBlank { "（未填明细）" }

    /** 候选名单/卡片上的一行字（**不带内部编号**）。 */
    fun label(): String = buildString {
        append("订单 ").append(orderNo)
        if (shipperName.isNotBlank()) append(" · ").append(shipperName)
        append("：").append(linesText())
        append("（").append(statusLabel.ifBlank { status }).append("）")
    }
}
