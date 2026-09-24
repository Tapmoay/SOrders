package com.tapmoay.sorders.ai

import com.tapmoay.sorders.data.remote.dto.ExpenseCreateRequest
import com.tapmoay.sorders.data.remote.dto.LedgerCreateRequest
import com.tapmoay.sorders.data.remote.dto.OrderCreateRequest
import com.tapmoay.sorders.data.remote.dto.PlaceDto
import com.tapmoay.sorders.data.remote.dto.PlaceUpdateRequest
import com.tapmoay.sorders.data.repo.AppRepository
import com.tapmoay.sorders.ui.dispatcher.centsToMoney
import com.tapmoay.sorders.ui.dispatcher.lineReceivableCents
import com.tapmoay.sorders.ui.shipper.customerNameOf
import com.tapmoay.sorders.ui.shipper.customerPhoneOf
import com.tapmoay.sorders.ui.shipper.settledByLineCents
import com.tapmoay.sorders.util.goodsTotalText
import android.content.Context
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import java.math.BigDecimal
import java.math.RoundingMode


// 2026-09-25（整改报告 §11 第 3 步）：下面这一块是**从 AiWriteService.kt 原样搬过来的**（同一个包，一个字符没改）。

/** 生产实现：全部转发给 App 已有的仓库层（带登录态、带统一异常转换）。 */
class RepoWriteDataSource(
    private val repo: AppRepository,
    /**
     * 当前登录用户 id。
     *
     * 为什么写操作也要它：**"我自己收到的消息"这件事只有服务端按 recipient_id 过滤才准**。
     * 派单员不带过滤时拿到的是所有人的消息（消息中心全局视图），
     * 而"标记已读/删除"只允许动自己的——不按收件人过滤就会对着别人的消息发指令，吃 404。
     */
    private val selfId: () -> Long? = { null },
    /**
     * 地理编码用的 Context（高德搜索 SDK 要它）。
     *
     * null = 不定位：单测里没有 Android 运行时，地址照样能存下来，只是没有坐标。
     * 生产是 [AiContainer] 传进的 `applicationContext`，所以**真机上一定走定位**。
     */
    private val context: Context? = null,
    /**
     * 「当前位置」句柄的定位提供者（[AiLocation]）。
     *
     * null = 没有本机定位能力（单测）：这时用户在地址里写「当前位置」会**当场被拒**并拿到
     * 一句"让他把地址说完整"，而不是写进去一个字面量「当前位置」。
     */
    private val locationProvider: () -> AiLocationProvider? = { null },
) : AiWriteDataSource {

    override suspend fun geocode(address: String): Pair<Double, Double>? =
        AiGeocode.lookup(context, address)

    /**
     * 「当前位置」句柄的**唯一解析点**（模型全程只写那四个字，见 [AiLocation.HERE]）。
     *
     * ⚠️ 放在数据源这一层而不是每个处理器里：地址类动作有三个入口（声明式的 `geocodeFrom`
     * 那一族、下单、改单），各写一遍"认不认句柄"必然会漏掉一个 ——
     * 漏掉的那个会把字面量「当前位置」写进地址库，**不报错**，而司机导航到一个叫"当前位置"的地方。
     */
    override suspend fun resolveAddress(text: String): AiPlace? =
        AiLocation.resolveAddress(text, locationProvider(), geocode = { geocode(it) })

    /**
     * 司机名册。`note` 带上他**现在按什么算钱**（后端 `pay_summary_for` 生成的那句话）。
     *
     * 为什么写操作也需要它：派单卡片上要写出"逐单定额/定比例到底有没有地方生效"——
     * 司机没挂规则时，`order_pay` 返回的是全额运费，两个覆盖值一个都不读。
     * 卡片上不写这句话，用户就是闭着眼睛点确认。
     */
    override suspend fun drivers(): List<AiName> =
        // ⚠️ **必须过滤 isActive**（2026-09-19 审计）：人工派单界面本来就有
        //    `DispatcherPoolViewModel` 里的 `.filter { it.isActive }`，而 AI 的名册原来没有 ——
        //    于是"把单派给王师傅"，只要王师傅是**已停用/已删除**的账号（删号是软删，full_name 保留），
        //    AI 会精确命中他并弹出一张看起来完全合理的确认卡（后端给的 paySummary 看不出账号已停用）。
        //    后果是**静默卡死**：司机登不进来（deps/socket 都拦 is_active=False）、也收不到推送
        //    （消息只推 active 收件人），单子停在「派单中」且不在待派池里，没人能完成它。
        //    后端 `assign_driver` 另有同一道闸（真正兜底的那一道），这里是"别让用户先看到假选项"。
        repo.drivers().filter { it.isActive }.map {
            AiName(
                id = it.id,
                label = it.fullName.trim().ifBlank { it.username.trim() },
                note = it.paySummary.trim().takeIf { s -> s.isNotEmpty() },
                // 手机号只用于匹配：用户说「派给 13800000003」时以前会拿到「没这个人」
                aliases = listOfNotNull(it.phone.trim().takeIf { s -> s.isNotEmpty() }),
            )
        }

    /**
     * 车辆名册。`note` = **这辆车现在归谁**（v3.44）。
     *
     * 为什么必须带这个 note：`vehicle.set_driver` 支持"不填司机 = 解绑"，
     * 而解绑**必须说清被拿掉的是谁** —— 卡片上只写"解绑司机：A12345"，
     * 用户根本看不出这次动的是谁名下的车（尤其在他刚改过几次的时候）。
     * 名字直接取 `VehicleOut.driver_name`（后端 join 好的），不再多发一次请求；
     * note 只用于展示，不参与名字匹配（匹配永远只看 label）。
     *
     * ⚠️ note 是**纯值**（`张三` / `没有司机`），**不带"现在："这种前缀**：
     *    那是给人看的措辞，归卡片管（`AiWriteBasicData` 的 details 里加）。
     *    两边各加一次的话，真机上印出来就是「现在：现在：Driver」（抓到过）。
     */
    override suspend fun vehicles(): List<AiName> =
        repo.vehicles().mapNotNull { v ->
            v.plateNo.trim().takeIf { it.isNotEmpty() }?.let {
                AiName(
                    v.id,
                    it,
                    note = v.driverName?.trim()?.takeIf { s -> s.isNotEmpty() } ?: "没有司机",
                )
            }
        }

    override suspend fun searchShippers(query: String, limit: Int): List<AiName> =
        repo.searchUsers(query, limit).filter { it.role == "shipper" }
            // `note`＝是不是批发商（高级货主）：设置商品可见范围时卡片上要写清改的是谁，
            // 而"批发商"和普通货主在业务上是两拨人（批发商有专属价）。它只用于展示，不参与匹配。
            // ⚠️ 手机号进 `aliases`（v3.44）：名册是**按 `?q=` 搜出来的**，用户十有八九
            //    就是拿手机号说的（「把货主 13800000002 的商品可见范围改成…」）。
            //    以前只在 label（姓名）上匹配 → 搜到了人却报「系统里没有匹配」。
            .map {
                AiName(
                    it.id,
                    it.fullName.trim().ifBlank { it.username.trim() },
                    note = if (it.isMember) "批发商" else null,
                    aliases = listOfNotNull(it.phone.trim().takeIf { s -> s.isNotEmpty() }),
                )
            }

    override suspend fun products(): List<AiName> =
        repo.products().map { AiName(it.id, it.name) }

    override suspend fun arrearsUnits(): List<AiName> =
        repo.arrearsUnits().map { AiName(it.id, it.name) }

    override suspend fun findOrders(query: String, limit: Int): List<AiOrderRef> =
        repo.orders(q = query).take(limit).map { d ->
            AiOrderRef(
                id = d.id,
                orderNo = d.orderNo,
                shipper = d.shipperName?.trim().orEmpty().ifBlank { d.tempShipperName?.trim().orEmpty() },
                // 报价要绑这个货主（专属价优先）——只有名字查不出专属价，所以编号必须带上
                shipperId = d.shipperId,
                status = d.status,
                address = d.addressDetail.trim(),
                driverLabel = d.driverName?.trim()?.takeIf { it.isNotEmpty() },
                // 商品行合计只有一处实现（`util/Money.kt::goodsTotalText`）——它也是收款页的判据
                amount = d.goodsTotalText(),
                collectCash = d.collectCash,
                isException = d.isException,
                hasNav = !d.addressLat.isNullOrBlank() && !d.addressLng.isNullOrBlank(),
                paid = d.paid,
                settledAmount = d.settledAmount,
                arrearsAmount = d.arrearsAmount,
            )
        }

    override suspend fun readAllNotifications(): JsonObject = repo.readAll()

    override suspend fun createExpense(req: ExpenseCreateRequest, idempotencyKey: String?) {
        repo.createExpense(req, idempotencyKey)
    }

    override suspend fun createLedgerEntry(req: LedgerCreateRequest) {
        repo.createLedger(req)
    }

    override suspend fun assignOrder(
        orderId: Long,
        driverId: Long,
        note: String?,
        freightFee: String?,
        collectCash: Boolean?,
        pieceAmount: String?,
        commissionRate: String?,
    ) {
        repo.assignOrder(orderId, driverId, note, freightFee, collectCash, pieceAmount, commissionRate)
    }

    override suspend fun recallOrder(orderId: Long, reason: String) {
        repo.recallOrder(orderId, reason)
    }

    override suspend fun cancelOrder(orderId: Long) {
        repo.cancelOrder(orderId)
    }

    override suspend fun returnableLines(orderId: Long): List<AiReturnableLine> =
        repo.order(orderId).orderProducts.map { p ->
            AiReturnableLine(
                id = p.id,
                name = p.productNameSnapshot,
                quantity = p.quantity,
                returned = p.returnedQuantity,
                damaged = p.damageQuantity,
                unitPrice = p.unitPrice ?: "0",
            )
        }

    override suspend fun returnOrder(orderId: Long, items: List<Pair<Long, Int>>, note: String) {
        repo.returnOrder(
            orderId,
            items.map { com.tapmoay.sorders.data.remote.dto.OrderReturnItem(it.first, it.second) },
            note,
        )
    }

    override suspend fun updateFreight(orderId: Long, freightFee: String?) {
        repo.updateFreight(orderId, freightFee)
    }

    override suspend fun payOrder(orderId: Long) {
        repo.payOrder(orderId)
    }

    override suspend fun chargeOrder(orderId: Long, arrearsUnitId: Long) {
        repo.chargeOrder(orderId, arrearsUnitId)
    }

    override suspend fun createOrder(req: OrderCreateRequest) {
        repo.createOrder(req)
    }

    override suspend fun fillOrderNavigation(
        orderId: Long,
        lat: String,
        lng: String,
        name: String,
        detail: String,
    ) {
        repo.fillOrderNavigation(
            orderId,
            com.tapmoay.sorders.data.remote.dto.OrderNavigationBody(
                addressLat = lat,
                addressLng = lng,
                name = name,
                detailAddress = detail,
            ),
        )
    }

    override suspend fun placeById(id: Long): PlaceDto? = repo.placesAll().firstOrNull { it.id == id }

    override suspend fun updateOrder(id: Long, fields: JsonObject) {
        // 只把 handler 明确要改的键搬进 DTO——DTO 的默认值全是 null，等于"不改这一项"。
        repo.updateOrder(
            id,
            com.tapmoay.sorders.data.remote.dto.OrderUpdateRequest(
                deliveryDescription = fields.str("delivery_description"),
                addressDetail = fields.str("address_detail"),
                contactDongjiaPhone = fields.str("contact_dongjia_phone"),
                contactBossPhone = fields.str("contact_boss_phone"),
                contactDongjiaName = fields.str("contact_dongjia_name"),
                contactBossName = fields.str("contact_boss_name"),
                remark = fields.str("remark"),
                internalNotes = fields.str("internal_notes"),
            ),
        )
    }

    override suspend fun setOrderException(
        id: Long,
        isException: Boolean,
        reason: String?,
        resolution: String?,
        expectedBefore: String?,
    ) {
        repo.markException(
            id,
            com.tapmoay.sorders.data.remote.dto.OrderExceptionBody(
                isException = isException,
                exceptionReason = reason.orEmpty(),
                exceptionResolution = resolution.orEmpty(),
                expectedDeliverBefore = expectedBefore,
            ),
        )
    }

    override suspend fun resolveOrderException(id: Long, note: String?) {
        repo.resolveException(id, note)
    }

    override suspend fun splitOrder(id: Long, parts: List<Int>) {
        repo.splitOrder(id, parts)
    }

    override suspend fun batchAssignOrders(
        orderIds: List<Long>,
        driverId: Long,
        note: String?,
        collectCash: Boolean?,
    ) {
        repo.batchAssign(orderIds, driverId, note, collectCash)
    }

    override suspend fun ledgerEntries(
        shipper: String?,
        from: String,
        to: String,
        limit: Int,
    ): List<AiLedgerRef> {
        // 货主名 → 编号（模型只会给名字）。
        // ⚠️ 两种"没给货主"要分清：
        //   · 用户没说货主 → 不收窄，在日期窗口内全找（宁可多找几条让他认，也别假装找不到）；
        //   · 用户说了货主但**对不上** → 返回空、由调用方拒绝。**绝不能退化成"全找"**：
        //     那等于把范围从"某个货主"悄悄放大成"所有货主"，而错改一行账不会立刻被发现。
        val sid = shipper?.trim()?.takeIf { it.isNotEmpty() }?.let { name ->
            repo.searchUsers(name, USER_PROBE_LIMIT)
                .firstOrNull { it.role == "shipper" || it.isMember }
                ?.id ?: return emptyList()
        }
        return repo.ledgerEntries(shipperId = sid, from = from, to = to).rows.take(limit).map { d ->
            AiLedgerRef(
                id = d.id,
                date = d.entryDate,
                product = d.productName.trim(),
                total = d.total,
                shipper = d.tempShipperName?.trim()?.takeIf { it.isNotEmpty() }
                    ?: "",
                source = d.source,
                note = d.note,
                orderNo = d.orderNo,
            )
        }
    }

    override suspend fun customers(): List<AiName> =
        repo.customers().map { AiName(it.id, it.name.trim()) }.filter { it.label.isNotEmpty() }

    // ---------------- 货主自己那一本账 ----------------

    override suspend fun isMemberShipper(): Boolean = repo.me().isMember

    override suspend fun currentRoleKey(): String? = repo.me().role

    /** 与 [currentRoleKey] 同一个来源（`users/me`），只是要的是编号（报价绑货主时用它）。 */
    override suspend fun currentUserId(): Long? = repo.me().id

    override suspend fun mySettleOrder(orderNo: String): AiSettleOrder? {
        val want = AiWriteArgs.normCode(orderNo)
        if (want.length < MIN_ORDER_NO_LEN) return null
        // 用自己的订单名册找那一张（`GET /orders?q=` 对货主是**只搜自己的单**，
        // 作用域由后端保证），再**精确比单号**——模糊命中一堆时不许挑一个。
        val hit = repo.orders(q = orderNo.trim())
            .firstOrNull { AiWriteArgs.normCode(it.orderNo) == want }
            ?: return null

        val order = repo.order(hit.id)
        val settled = settledByLineCents(repo.mySettlements(orderId = order.id).rows)
        return AiSettleOrder(
            id = order.id,
            orderNo = order.orderNo,
            customer = customerNameOf(order),
            customerPhone = customerPhoneOf(order),
            status = order.status,
            lines = order.orderProducts.map { line ->
                AiSettleLine(
                    id = line.id,
                    name = line.productNameSnapshot.ifBlank { "（未命名商品）" },
                    // 逐行口径只有一处：`lineReceivableCents`（与界面、与后端同一个式子）
                    receivable = BigDecimal(centsToMoney(lineReceivableCents(line))),
                    settled = BigDecimal(centsToMoney(settled[line.id] ?: 0L)),
                )
            },
        )
    }

    override suspend fun mySettlements(orderId: Long): List<AiMySettlementRef> =
        repo.mySettlements(orderId = orderId, includeDeleted = true, limit = MY_SETTLE_PROBE)
            .rows
            .map { s ->
                AiMySettlementRef(
                    id = s.id,
                    orderId = s.orderId,
                    orderNo = s.orderNo ?: "",
                    customer = s.customerName,
                    amount = s.amount,
                    method = s.method,
                    settledAt = s.settledAt.take(16).replace("T", " "),
                    isDeleted = s.isDeleted,
                    products = s.lines.map { it.productName },
                )
            }

    override suspend fun createMySettlement(
        orderId: Long,
        lines: List<Pair<Long, String>>,
        method: String,
        note: String,
    ) {
        repo.createMySettlement(
            com.tapmoay.sorders.data.remote.api.ShipperSettlementCreateRequest(
                orderId = orderId,
                lines = lines.map {
                    com.tapmoay.sorders.data.remote.api.ShipperSettlementLineRequest(
                        orderProductId = it.first,
                        amount = it.second,
                    )
                },
                method = method,
                note = note,
                // 这笔核销是 AI 确认卡提交的：审计与列表上会如实标出来
                source = "ai",
            ),
        )
    }

    override suspend fun revokeMySettlement(id: Long) = repo.revokeMySettlement(id)

    override suspend fun restoreMySettlement(id: Long) {
        repo.restoreMySettlement(id)
    }

    // ---------------------------------------------------------------- 退货申请（2026-09-21）

    /**
     * DTO → 模型看得见的形状。
     *
     * ⚠️ `id` 留着（撤回/办理都要按它认人），但**不进候选名单文案** ——
     * [AiReturnRequest.label] 里只有单号、商品名和中文状态（模型第一条硬规矩：不给编号）。
     */
    private fun toAiReturnRequest(dto: com.tapmoay.sorders.data.remote.dto.ReturnRequestDto) =
        AiReturnRequest(
            id = dto.id,
            orderId = dto.orderId,
            orderNo = dto.orderNo,
            status = dto.status,
            statusLabel = dto.statusLabel,
            shipperName = dto.shipperName,
            note = dto.note,
            rejectReason = dto.rejectReason,
            handledByName = dto.handledByName,
            lines = dto.lines.map { it.productName to it.quantity },
        )

    override suspend fun myReturnRequests(orderId: Long?): List<AiReturnRequest> =
        repo.myReturnRequests(orderId = orderId).items.map { toAiReturnRequest(it) }

    override suspend fun applyReturnRequest(orderId: Long, items: List<Pair<Long, Int>>, note: String) {
        repo.applyReturnRequest(
            orderId = orderId,
            items = items.map {
                com.tapmoay.sorders.data.remote.dto.OrderReturnItem(
                    orderProductId = it.first,
                    quantity = it.second,
                )
            },
            note = note,
        )
    }

    override suspend fun withdrawReturnRequest(id: Long) {
        repo.withdrawReturnRequest(id)
    }

    override suspend fun pendingReturnRequests(orderId: Long?): List<AiReturnRequest> =
        repo.returnRequestTodo(status = "pending", orderId = orderId).items.map { toAiReturnRequest(it) }

    override suspend fun rejectReturnRequest(id: Long, reason: String) {
        repo.rejectReturnRequest(id, reason)
    }

    override suspend fun fulfillReturnRequest(id: Long) {
        repo.fulfillReturnRequest(id)
    }

    override suspend fun updateLedgerEntry(id: Long, fields: JsonObject) {
        // ⚠️ 数量必须**要么解析成整数、要么当场炸**（2026-09-19 审计）：
        //    原来这里是 `fields.str("quantity")?.toIntOrNull()` —— 解析失败静默变 null，
        //    再被 `explicitNulls = false` 整条丢掉 → 请求体 `{}` → 后端一个字段都没改，
        //    而卡片写着「数量 3.00」、界面回「已完成」。**静默空转比报错糟得多**。
        val qtyRaw = fields.str("quantity")
        val qty = qtyRaw?.toIntOrNull()
        if (qtyRaw != null && qty == null) {
            throw IllegalStateException("数量「$qtyRaw」不是整数，这次没有改动任何数据，请重新说一次数量")
        }
        require(
            listOfNotNull(
                fields.str("note"), fields.str("entry_date"), fields.str("product_name"),
                qtyRaw, fields.str("unit_price"), fields.str("total"),
            ).isNotEmpty(),
        ) { "这次没有任何要改的内容，已取消（避免弹一张什么都不改的卡）" }
        repo.updateLedger(
            id,
            com.tapmoay.sorders.data.remote.api.LedgerUpdateRequest(
                note = fields.str("note"),
                entryDate = fields.str("entry_date"),
                productName = fields.str("product_name"),
                quantity = qty,
                unitPrice = fields.str("unit_price"),
                total = fields.str("total"),
            ),
        )
    }

    override suspend fun deleteLedgerEntry(id: Long) {
        repo.deleteLedger(id)
    }

    override suspend fun createReceipt(
        customerId: Long,
        amount: String,
        method: String,
        receivedAt: String,
        orderIds: List<Long>,
        settleMode: String,
        note: String?,
    ) {
        repo.createReceipt(
            com.tapmoay.sorders.data.remote.dto.ReceiptCreateRequest(
                customerId = customerId,
                amount = amount,
                method = method,
                receivedAt = receivedAt,
                orderIds = orderIds,
                settleMode = settleMode,
                note = note.orEmpty(),
            ),
        )
    }

    override suspend fun syncDeliveredOrders(shipperId: Long?) {
        repo.syncLedgerFromDelivered(shipperId)
    }

    override suspend fun orderLines(orderId: Long): List<AiOrderLine> =
        repo.orderProductLines(orderId).map { r ->
            AiOrderLine(
                id = r.id,
                product = r.productNameSnapshot.trim(),
                quantity = r.quantity,
                unitPrice = r.unitPrice,
                lineTotal = r.lineTotal,
            )
        }

    override suspend fun addOrderLine(orderId: Long, product: String, quantity: Int, unitPrice: String) {
        repo.addOrderProduct(
            com.tapmoay.sorders.data.remote.dto.OrderProductCreateRequest(
                orderId = orderId,
                // 商品库里有同名商品就带上它的编号（这样这行能跟库存/报表挂上钩）；
                // 没有就留空——**不改名字、不报错**：货主口头说的名字本来就允许不在商品库里。
                productId = repo.products()
                    .firstOrNull { it.name.trim().equals(product.trim(), ignoreCase = true) }
                    ?.id,
                productNameSnapshot = product,
                quantity = quantity,
                unitPrice = unitPrice,
            ),
        )
    }

    override suspend fun updateOrderLine(lineId: Long, fields: JsonObject) {
        repo.updateOrderProduct(
            lineId,
            com.tapmoay.sorders.data.remote.dto.OrderProductUpdateRequest(
                productNameSnapshot = fields.str("product_name"),
                quantity = fields.str("quantity")?.toIntOrNull(),
                unitPrice = fields.str("unit_price"),
                lineTotal = null, // 让后端按 单价×数量 自己算，避免两边算不一致
            ),
        )
    }

    override suspend fun deleteOrderLine(lineId: Long) {
        repo.deleteOrderProduct(lineId)
    }

    override suspend fun findDeletedOrders(query: String, limit: Int): List<AiOrderRef> =
        repo.deletedOrders(q = query).take(limit).map { d ->
            AiOrderRef(
                id = d.id,
                orderNo = d.orderNo,
                shipper = d.shipperName?.trim().orEmpty().ifBlank { d.tempShipperName?.trim().orEmpty() },
                // 报价要绑这个货主（专属价优先）——只有名字查不出专属价，所以编号必须带上
                shipperId = d.shipperId,
                status = d.status,
                address = d.addressDetail.trim(),
                driverLabel = d.driverName?.trim()?.takeIf { it.isNotEmpty() },
                // 商品行合计只有一处实现（`util/Money.kt::goodsTotalText`）——它也是收款页的判据
                amount = d.goodsTotalText(),
                collectCash = d.collectCash,
                isException = d.isException,
                paid = d.paid,
                settledAmount = d.settledAmount,
                arrearsAmount = d.arrearsAmount,
            )
        }

    override suspend fun softDeleteOrder(orderId: Long) {
        repo.deleteOrder(orderId)
    }

    override suspend fun restoreOrder(orderId: Long) {
        repo.restoreOrder(orderId)
    }

    override suspend fun myNotifications(limit: Int): List<AiNotificationRef> =
        // ⚠️ 必须带 recipient_id：不带的话派单员会拿到**所有人的消息**，
        // 而"标记已读/删除"只认自己的（后端 `n.recipient_id != current.id` → 404）。
        // 真机实测过：卡片上列了 6 条，点确认后第一条就 404。
        repo.notificationsFor(selfId(), limit).map { n ->
            AiNotificationRef(
                id = n.id,
                title = n.title.trim(),
                content = n.content.trim(),
                createdAt = n.createdAt,
                read = n.readAt != null,
            )
        }

    override suspend fun sendNotification(
        recipientId: Long,
        title: String,
        content: String,
        important: Boolean,
    ) {
        repo.sendNotification(
            com.tapmoay.sorders.data.remote.dto.NotificationCreateRequest(
                recipientId = recipientId,
                title = title,
                content = content,
                speechImportant = important,
            ),
        )
    }

    override suspend fun notifyPriceChange(
        shipperIds: List<Long>,
        productId: Long,
        productName: String,
        priceType: String,
        newPrice: String,
        oldPrice: String?,
    ) {
        repo.notifyPriceChange(
            com.tapmoay.sorders.data.remote.dto.PriceChangeNotifyRequest(
                shipperIds = shipperIds,
                productId = productId,
                productName = productName,
                priceType = priceType,
                newPrice = newPrice,
                oldPrice = oldPrice,
            ),
        )
    }

    override suspend fun markNotificationRead(id: Long) {
        repo.markRead(id)
    }

    override suspend fun updateNotification(id: Long, title: String?, content: String?) {
        repo.updateNotification(id, title, content)
    }

    override suspend fun deleteNotifications(ids: List<Long>, all: Boolean) {
        repo.deleteNotifications(ids, all)
    }

    // ------------------------------------------------ 司机账单与结算（第四批）

    override suspend fun salaryDrivers(): List<AiSalaryDriver> =
        repo.drivers()
            // ⚠️ `billing_mode` 是自由文本列，库里同时存在 `salary` 与 `SALARY`
            // （后端已按 `lower()` 比，这里必须同口径，否则卡片上念的人数与真正建的对不上）。
            .filter { it.billingMode.equals("salary", ignoreCase = true) }
            .map { d ->
                AiSalaryDriver(
                    id = d.id,
                    label = d.fullName.trim().ifBlank { d.phone.trim() },
                    salary = d.salary?.trim().orEmpty(),
                )
            }
            // 后端对 `salary <= 0`（或空）的司机是直接 skip 的，卡片上不能把他们算进去。
            .filter { (it.salary.toBigDecimalOrNull() ?: BigDecimal.ZERO).signum() > 0 }

    override suspend fun driverBills(
        driverId: Long?,
        month: String?,
        billType: String?,
    ): List<AiDriverBill> =
        // 这里不把 bill_type 交给后端：量很小（一个月一个司机几张），
        // 客户端筛一次比在 Api/Repo/调用点三层各加一个参数更不容易改坏。
        repo.driverBills(driverId, month, null)
            .filter { billType == null || it.billType.equals(billType, ignoreCase = true) }
            .map { b ->
                AiDriverBill(
                    id = b.id,
                    driverId = b.driverId,
                    driverLabel = b.driverName?.trim().orEmpty(),
                    billType = b.billType,
                    month = b.month,
                    amount = b.amount,
                    status = b.status,
                    orderNo = b.orderNo?.trim()?.takeIf { it.isNotEmpty() },
                )
            }

    override suspend fun driverSettlements(
        driverId: Long?,
        month: String?,
        status: String?,
    ): List<AiSettlementRef> =
        repo.settlements(driverId, month, status).map { s ->
            AiSettlementRef(
                id = s.id,
                driverId = s.driverId,
                driverLabel = s.driverName?.trim().orEmpty(),
                settleType = s.settleType,
                month = s.month,
                amount = s.amount,
                status = s.status,
                orderCount = s.orderIds?.size ?: 0,
            )
        }

    override suspend fun monthlyFreight(month: String): List<AiDriverFreight> =
        repo.freightSettlement(month).groups.map { g ->
            AiDriverFreight(
                driverId = g.driverId,
                driverLabel = g.driverName.trim(),
                count = g.count,
                // 后端给的是 Double（`round(total + fee, 2)`），用 valueOf 走它的字符串形式，
                // 避免 BigDecimal(0.1+0.2) 那种二进制尾巴。
                total = BigDecimal.valueOf(g.total).setScale(2, RoundingMode.HALF_UP).toPlainString(),
            )
        }

    override suspend fun generateDriverBills(driverId: Long?, month: String, billType: String) {
        repo.generateBills(
            com.tapmoay.sorders.data.remote.dto.DriverBillGenerateRequest(
                driverId = driverId,
                month = month,
                billType = billType,
            ),
        )
    }

    override suspend fun createSettlement(driverId: Long, settleType: String, month: String, note: String?) {
        // ⚠️ 金额**必须**留空：后端允许手工给一个 amount，但确认结算单时要求
        // 「结算单金额 == 明细合计」，两者不等时**永远确认不了**（只能作废重来）。
        // 所以这里不给这条口子——金额一律由后端按待结算明细汇总。
        repo.createSettlement(
            com.tapmoay.sorders.data.remote.dto.SettlementCreateRequest(
                driverId = driverId,
                settleType = settleType,
                month = month,
                amount = null,
                note = note.orEmpty(),
            ),
        )
    }

    override suspend fun settlementAction(id: Long, action: String, method: String) {
        repo.settlementAction(id, action, method)
    }

    // ------------------------------------------------ 名册（主数据域）

    override suspend fun usersOfRole(query: String, role: String): List<AiName> =
        users(query).let { all ->
            // `AiName` 不带角色，所以这里要再查一遍带角色的那份（同一批名字，只是过滤）
            val ids = repo.searchUsers(query, USER_PROBE_LIMIT).filter { it.role == role }.map { it.id }.toSet()
            all.filter { it.id in ids }
        }

    override suspend fun users(query: String): List<AiName> =
        repo.searchUsers(query, USER_PROBE_LIMIT)
            // 手机号进别名：`targetUser` 的提示词写的就是「姓名（或手机号）」（v3.44）
            .map {
                AiName(
                    it.id,
                    it.fullName.trim().ifBlank { it.username.trim() },
                    aliases = listOfNotNull(it.phone.trim().takeIf { s -> s.isNotEmpty() }),
                )
            }

    override suspend fun addresses(): List<AiName> = repo.addresses().map {
        AiName(it.id, listOf(it.receiverName.trim(), it.detailAddress.trim()).filter { s -> s.isNotEmpty() }.joinToString(" "))
    }

    override suspend fun locations(): List<AiName> = repo.locations().map { AiName(it.id, it.name.trim()) }

    override suspend fun places(): List<AiName> = repo.placesAll().map {
        AiName(
            it.id,
            listOf(it.name.trim(), it.detailAddress.trim()).filter { s -> s.isNotEmpty() }.joinToString(" "),
        )
    }

    override suspend fun contacts(): List<AiName> =
        repo.contacts().map { AiName(it.id, listOf(it.displayName.trim(), it.phone.trim()).filter { s -> s.isNotEmpty() }.joinToString(" ")) }

    override suspend fun priceRules(): List<AiName> = repo.priceRules().map {
        val who = it.shipperName?.trim().orEmpty().ifBlank { "（未命名批发商）" }
        val what = it.productName?.trim().orEmpty().ifBlank { "（未命名商品）" }
        // ⚠️ 价格必须**格式化**再拼进标签：后端把 `Numeric(12,2)` 序列化成字符串时带四位小数，
        //    于是确认卡上出现了「城东水果批发 AI测试果篮 = 11.5000」——金额栏里出现四位小数，
        //    用户会怀疑这个数是不是没对齐（真机实测看到的）。
        //    这里只格式化**展示**用的那一份；批量调价算 before→after 用的原始值不动。
        val price = it.specialUnitPrice.toBigDecimalOrNull()?.let { v -> AiWriteArgs.moneyText(v) }
            ?: it.specialUnitPrice
        AiName(it.id, "$who $what = $price")
    }

    // ------------------------------------------------ 商品 / 定价 / 库存

    override suspend fun createProduct(
        name: String,
        defaultUnitPrice: String,
        unit: String,
        stock: Int,
        lowStockAlert: Int,
    ) {
        // ⚠️ **新建**商品时不带 cost_price（用 DTO 默认 "0"）：新商品通常还没进过货，
        //    成本价是"还不知道"的状态，硬要模型填一个只会逼它编。
        //    成本价之后有两个**真实**入口：改商品（`products.update` 的 cost_price 字段）
        //    与进货入库（`inventory.adjust` 的 unit_cost），两者都要过 `allowCost` 那道门。
        repo.createProduct(
            com.tapmoay.sorders.data.remote.api.ProductCreateRequest(
                name = name,
                defaultUnitPrice = defaultUnitPrice,
                unit = unit.ifBlank { null },
                stock = stock,
                lowStockAlert = lowStockAlert,
            ),
        )
    }

    override suspend fun updateProduct(id: Long, fields: JsonObject) {
        // 部分更新体空了说明**规格里的 key 和后端字段名对不上**（`pick()` 会静默丢掉认不出的键）。
        // 那种情况下 PATCH 什么都不改，而卡片上明明写着"改成 X"——最难发现的一类 bug。
        // 宁可在这里炸出来，也不要静默地什么都不做。
        require(fields.isNotEmpty()) { "updateProduct 的部分更新体是空的（动作规格的 key 写错了）" }
        repo.updateProduct(
            id,
            com.tapmoay.sorders.data.remote.api.ProductUpdateRequest(
                name = fields.str("name"),
                defaultUnitPrice = fields.str("default_unit_price"),
                isActive = fields.str("is_active")?.toBooleanStrictOrNull(),
                unit = fields.str("unit"),
                lowStockAlert = fields.str("low_stock_alert")?.toIntOrNull(),
                // ⚠️ cost_price **不在这里判**：门开在 `AiWriteService`（所有动作的唯一入口）。
                //    分散到各个数据源方法里迟早漏一个，而漏掉的后果是"成本价被写进去了"。
                costPrice = fields.str("cost_price"),
            ),
        )
    }

    override suspend fun deleteProduct(id: Long) = repo.deleteProduct(id)

    override suspend fun createPriceRule(shipperId: Long, productId: Long, price: String) {
        repo.createPriceRule(shipperId, productId, price)
    }

    override suspend fun updatePriceRule(ruleId: Long, price: String) {
        repo.updatePriceRule(ruleId, price)
    }

    override suspend fun deletePriceRule(ruleId: Long) = repo.deletePriceRule(ruleId)

    override suspend fun createMovement(productId: Long, change: Int, note: String, unitCost: String?) {
        repo.createMovement(
            com.tapmoay.sorders.data.remote.dto.InventoryMovementCreateRequest(
                productId = productId,
                change = change,
                note = note,
                // 同一个门：进货价也是成本，见上面那段注释
                unitCost = unitCost,
            ),
        )
    }

    // ------------------------------------------------ 账号与收费规则

    override suspend fun createUser(
        phone: String,
        password: String,
        role: String,
        fullName: String,
        isMember: Boolean,
    ) {
        repo.createUser(
            com.tapmoay.sorders.data.remote.api.UserCreateRequest(
                phone = phone,
                password = password,
                role = role,
                fullName = fullName,
                isMember = isMember,
            ),
        )
    }

    override suspend fun updateUser(id: Long, fields: JsonObject) {
        // 见 updateProduct 里同一条理由：空的部分更新体＝规格 key 写错了，
        // 而它的表现是"卡片说改了、实际什么都没改"。必须炸出来。
        require(fields.isNotEmpty()) { "updateUser 的部分更新体是空的（动作规格的 key 写错了）" }
        // **只带填了的键**：后端 PATCH 语义是"没带的字段不改"，
        // 所以这里绝不能补默认值——补了就等于"顺手把用户没提的项也改了"。
        repo.updateUser(
            id,
            com.tapmoay.sorders.data.remote.api.UserUpdateRequest(
                phone = fields.str("phone"),
                password = fields.str("password"),
                fullName = fields.str("full_name"),
                isActive = fields.str("is_active")?.toBooleanStrictOrNull(),
                isMember = fields.str("is_member")?.toBooleanStrictOrNull(),
                vehicleType = fields.str("vehicle_type"),
                billingMode = fields.str("billing_mode"),
                salary = fields.str("salary"),
            ),
        )
    }

    override suspend fun swapUserRole(id: Long) {
        repo.swapRole(id)
    }

    override suspend fun deleteUser(id: Long) = repo.deleteUser(id)

    // ------------------------------------------------ 批量调价

    override suspend fun members(): List<AiName> =
        repo.members().map {
            AiName(
                it.id,
                it.fullName.trim().ifBlank { it.username.trim() },
                aliases = listOfNotNull(it.phone.trim().takeIf { s -> s.isNotEmpty() }),
            )
        }

    override suspend fun productPrices(): List<AiPriceProduct> =
        repo.products().map { AiPriceProduct(it.id, it.name, it.defaultUnitPrice) }

    override suspend fun priceRuleRows(): List<AiPriceRuleRow> =
        repo.priceRules().map { AiPriceRuleRow(it.shipperId, it.productId, it.specialUnitPrice) }

    override suspend fun batchPriceRules(
        shipperIds: List<Long>,
        productIds: List<Long>,
        mode: String,
        value: String?,
        adjustPercent: String?,
    ) {
        repo.batchPriceRules(shipperIds, productIds, mode, value, adjustPercent = adjustPercent)
    }

    // ------------------------------------------------ 基础资料

    override suspend fun freightTemplates(): List<AiName> = repo.freightTemplates().map {
        AiName(it.id, it.name.trim().ifBlank { "${it.fromPlace}→${it.toPlace}" })
    }

    override suspend fun driverRules(): List<AiName> = repo.driverBillingRules().map {
        AiName(it.id, it.name.trim())
    }

    override suspend fun createDriverRule(fields: JsonObject) {
        repo.createDriverBillingRule(
            com.tapmoay.sorders.data.remote.dto.DriverBillingRuleRequest(
                name = fields.req("name"),
                vehicleType = fields.str("vehicle_type"),
                salary = fields.str("salary"),
                pieceAmount = fields.str("piece_amount"),
                pieceUnit = fields.str("piece_unit"),
                commissionBase = fields.str("commission_base"),
                commissionRate = fields.str("commission_rate"),
                commissionProductIds = resolveProductIds(fields.str("commission_products")),
                remark = fields.str("remark"),
            ),
        )
    }

    /**
     * 「哪些商品」这类**名单**字段：名字 → 编号。
     *
     * 匹配仍然走唯一那份严格解析（`AiWriteArgs.strict`：认不出来就抛并给候选，**不自己挑一个**）
     * ——名单只是把它按分隔符跑多遍，不是另立一套判据。「全部」= 不限范围。
     */
    private suspend fun resolveProductIds(raw: String?): List<Long> {
        val text = raw?.trim().orEmpty()
        if (text.isEmpty() || text == "全部" || text == "所有商品") return emptyList()
        val pool = products()
        return text.split('、', ',', '，', ';', '；', ' ')
            .map { it.trim() }
            .filter { it.isNotEmpty() }
            .map { AiWriteArgs.strict(it, pool, "商品")!!.id }  // strict 查不到会抛，不会返回 null
    }

    override suspend fun updateDriverRule(id: Long, fields: JsonObject) {
        require(fields.isNotEmpty()) { "updateDriverRule 的部分更新体是空的（规格 key 写错了）" }
        // ⚠️ 这里**不读回原值再整体提交**（和运费模板那条相反）：后端的 PUT 是**部分更新**语义
        //    （只放用户点名的键）。读回原值整体重写的话，"只改提成比例"会把别的同时改的字段
        //    按我读到的旧值覆盖回去——而卡片上只写了改的那一项，用户根本看不出被覆盖了。
        repo.updateDriverBillingRule(
            id,
            com.tapmoay.sorders.data.remote.dto.DriverBillingRuleRequest(
                name = fields.str("name"),
                salary = fields.str("salary"),
                pieceAmount = fields.str("piece_amount"),
                // ⚠️ 这两行原来**漏了**（2026-09-19 审计）：`DRIVER_RULE_KEYS` 与字段规格里
                //    都有 `piece_unit` / `commission_base`，声明式那层也把它们 pick 进了 payload，
                //    但这里没往请求里搬 → 模型说「改成每件」、卡片上也写「每件：3 元」，
                //    实际发出去的请求里根本没有这个键 → **规则还是"每单"**。
                //    钱算错而且看不出来（卡片与库里的说法不一致，只有对账单能发现）。
                pieceUnit = fields.str("piece_unit"),
                commissionBase = fields.str("commission_base"),
                commissionRate = fields.str("commission_rate"),
                // 没点名 = null（后端不动它）；点名了就整体替换（空/「全部」= 取消范围）
                commissionProductIds = if (fields.containsKey("commission_products")) {
                    resolveProductIds(fields.str("commission_products"))
                } else {
                    null
                },
                remark = fields.str("remark"),
            ),
        )
    }

    override suspend fun deleteDriverRule(id: Long) = repo.deleteDriverBillingRule(id)

    override suspend fun attachDriverRule(driverId: Long, ruleId: Long?) {
        repo.attachDriverRule(driverId, ruleId)
    }

    override suspend fun createAddress(fields: JsonObject) {
        repo.createAddress(
            com.tapmoay.sorders.data.remote.dto.AddressCreateRequest(
                receiverName = fields.str("receiver_name").orEmpty(),
                phone = fields.str("phone").orEmpty(),
                detailAddress = fields.str("detail_address").orEmpty(),
                remark = fields.str("remark").orEmpty(),
                isDefault = fields.str("default")?.toBooleanStrictOrNull() ?: false,
                addressLat = fields.str(GEO_LAT),
                addressLng = fields.str(GEO_LNG),
                originAddress = fields.str("origin_address"),
            ),
        )
    }

    override suspend fun updateAddress(id: Long, fields: JsonObject) {
        require(fields.isNotEmpty()) { "updateAddress 的部分更新体是空的（动作规格的 key 写错了）" }
        // ⚠️ 地址的 PATCH 是**整体替换**语义（后端收 AddressCreateRequest），
        // 所以这里要先把原值读回来补齐没改的字段——否则"只改电话"会把地址清空。
        val cur = repo.addresses().firstOrNull { it.id == id }
            ?: error("找不到要改的地址（$id）")
        val newText = fields.str("detail_address")
        val lat = fields.str(GEO_LAT)
        val lng = fields.str(GEO_LNG)
        // 改了地址文字却没有新坐标 = 会把**旧地址的坐标**留在库里（PATCH 传 null 清不掉）。
        // 卡片那一层已经拦过（`geocodeRequired`），这里再兜一次：宁可报错，也不能让
        // 司机被导航到上一个地址去。
        if (newText != null && lat == null) {
            error("改地址失败：新地址没有定位到坐标，留着旧坐标会把司机带到旧地址去。请让用户把地址说完整。")
        }
        repo.updateAddress(
            id,
            com.tapmoay.sorders.data.remote.dto.AddressCreateRequest(
                receiverName = fields.str("receiver_name") ?: cur.receiverName,
                phone = fields.str("phone") ?: cur.phone,
                detailAddress = newText ?: cur.detailAddress,
                remark = fields.str("remark") ?: cur.remark,
                isDefault = cur.isDefault,
                addressLat = lat ?: cur.addressLat,
                addressLng = lng ?: cur.addressLng,
                originAddress = fields.str("origin_address") ?: cur.originAddress,
                // ⚠️ **必须回填图片**（2026-09-19 审计「声明式 CRUD」专项，高）：
                //    `AddressCreateRequest.imageUrls` 的默认值是 `emptyList()`，而 ApiClient 的
                //    `encodeDefaults = true` 会把它**永远发出去** → 后端 `_apply_images` 把
                //    `[]` 当成"清空"（只有 `None` 才是不改）→ **每次 AI 改这条线路的电话/地址，
                //    线路上的照片全没了**，而卡片照样回「已完成」。
                //    更糟的是撤回救不回来：`AiResources` 的 ADDRESS.readKeys 里没有 image_urls，
                //    而卡片最后一行承诺"点它就能改回原样"。
                //    地点那条路（`updatePlace`）一直有这一行 —— 这里是漏写。
                imageUrls = cur.imageUrls,
            ),
        )
    }

    override suspend fun deleteAddress(id: Long) = repo.deleteAddress(id)

    override suspend fun setDefaultAddress(id: Long) {
        repo.setDefaultAddress(id)
    }

    override suspend fun createContact(fields: JsonObject) {
        repo.createContact(
            com.tapmoay.sorders.data.remote.dto.ContactCreateRequest(
                phone = fields.req("phone"),
                displayName = fields.str("display_name").orEmpty(),
            ),
        )
    }

    override suspend fun updateContact(id: Long, fields: JsonObject) {
        require(fields.isNotEmpty()) { "updateContact 的部分更新体是空的（规格 key 写错了）" }
        repo.updateContact(
            id,
            com.tapmoay.sorders.data.remote.dto.ContactUpdateRequest(
                phone = fields.str("phone"),
                displayName = fields.str("display_name"),
            ),
        )
    }

    override suspend fun deleteContact(id: Long) = repo.deleteContact(id)

    override suspend fun createLocation(fields: JsonObject) {
        repo.createLocation(
            com.tapmoay.sorders.data.remote.dto.LocationCreateRequest(
                name = fields.req("name"),
                detailAddress = fields.req("detail_address"),
                remark = fields.str("remark").orEmpty(),
                addressLat = fields.str(GEO_LAT),
                addressLng = fields.str(GEO_LNG),
                // 地点绑定的联系人（2026-09-24）：下单选中这个地点时会自动带出收货人两栏
                contactName = fields.str("contact_name").orEmpty(),
                contactPhone = fields.str("contact_phone").orEmpty(),
            ),
        )
    }

    override suspend fun updateLocation(id: Long, fields: JsonObject) {
        require(fields.isNotEmpty()) { "updateLocation 的部分更新体是空的（规格 key 写错了）" }
        // 同样是整体替换语义：先读回原值补齐
        val cur = repo.locations().firstOrNull { it.id == id } ?: error("找不到要改的地点（$id）")
        val newText = fields.str("detail_address")
        val lat = fields.str(GEO_LAT)
        val lng = fields.str(GEO_LNG)
        if (newText != null && lat == null) {
            error("改地点失败：新地址没有定位到坐标，留着旧坐标会把司机带到旧地点去。请让用户把地址说完整。")
        }
        // 「把这个地点归到那一类」：**严格对名册**。
        // ⛔ 不许让它顺手新建：用户说的"那一类"如果库里没有，多半是名字记错了（错别字会**静默**
        //    多出一格分组），所以这里对不上就拒绝、并把现有分组名列出来。
        val wantCat = fields.str("category")?.trim()?.takeIf { it.isNotEmpty() }
        var cat = cur.category
        if (wantCat != null && wantCat != cur.category) {
            val pool = repo.placeCategories()
            val hit = pool.firstOrNull { it.name == wantCat }
                ?: throw AiWriteArgException(
                    "你的地点分组里没有「$wantCat」。现有分组：" +
                        (if (pool.isEmpty()) "（还没有分组，先用「新建地点分组」建一个）"
                        else pool.joinToString("、") { it.name }) +
                        "。要么用上面某个名字，要么先新建这个分组。"
                )
            cat = hit.name
        }
        repo.updateLocation(
            id,
            com.tapmoay.sorders.data.remote.dto.LocationCreateRequest(
                name = fields.str("name") ?: cur.name,
                detailAddress = newText ?: cur.detailAddress,
                remark = fields.str("remark") ?: cur.remark,
                addressLat = lat ?: cur.addressLat,
                addressLng = lng ?: cur.addressLng,
                // ⛔ 分类与仓库标记必须**回填原值**（没点名分组时就是原值）：
                //    `LocationCreateRequest` 走的是"整体替换"语义，不回填就等于
                //    "AI 改个地点名把它从分组里踢出去 / 顺手取消仓库标记"——
                //    而界面上只会显示「已改地点」，用户看不出分组没了。
                category = cat,
                isWarehouse = cur.isWarehouse,
                // ⛔ 地点绑定的联系人同样要**回填原值**（理由与上面分类、仓库标记一模一样）：
                //    AI 只说了"改个地点名"，不回填就等于把收货人绑定**静默清掉** ——
                //    而界面上只会显示「已改地点」。
                contactName = fields.str("contact_name") ?: cur.contactName,
                contactPhone = fields.str("contact_phone") ?: cur.contactPhone,
                imageUrls = cur.imageUrls,
            ),
        )
    }

    override suspend fun deleteLocation(id: Long) = repo.deleteLocation(id)

    // ---- 共享地点（全库共用那张表）：改 / 删 / 撤销 / 设为共享 ----
    //
    // 四个都是**转发**，没有一处自己算业务：
    // 合并判据（1 米/同名 30 米）与"名字地址不能都空"都在后端 `services/place_service.py`，
    // 客户端的任何一处再写一遍就会与它走散（而两边都不报错）。

    override suspend fun updatePlace(id: Long, fields: JsonObject) {
        require(fields.isNotEmpty()) { "updatePlace 的部分更新体是空的（规格 key 写错了）" }
        repo.updatePlace(
            id,
            PlaceUpdateRequest(
                name = fields.str("name"),
                detailAddress = fields.str("detail_address"),
            ),
        )
    }

    override suspend fun deletePlace(id: Long) = repo.deletePlace(id)

    override suspend fun restorePlace(id: Long) {
        repo.restorePlace(id)
    }

    override suspend fun demotePlace(id: Long) {
        repo.demotePlace(id)
    }

    override suspend fun publishLocation(id: Long) {
        repo.shareLocation(id)
    }

    override suspend fun createArrearsUnit(fields: JsonObject) {
        repo.createArrearsUnit(
            com.tapmoay.sorders.data.remote.dto.ArrearsUnitCreateRequest(
                name = fields.req("name"),
                phone = fields.str("phone").orEmpty(),
                remark = fields.str("remark").orEmpty(),
            ),
        )
    }

    override suspend fun updateArrearsUnit(id: Long, fields: JsonObject) {
        require(fields.isNotEmpty()) { "updateArrearsUnit 的部分更新体是空的（规格 key 写错了）" }
        repo.updateArrearsUnit(
            id,
            com.tapmoay.sorders.data.remote.dto.ArrearsUnitUpdateRequest(
                name = fields.str("name"),
                phone = fields.str("phone"),
                remark = fields.str("remark"),
            ),
        )
    }

    override suspend fun deleteArrearsUnit(id: Long) = repo.deleteArrearsUnit(id)

    // ---- 单位换算（2026-09-24：一车 = 8 方）----
    //
    // ⚠️ 换算率按**字符串**进出（后端是 `Numeric(14,4)`）：走 Double 会让 `0.1` 变成
    //    `0.1000000000000000055…`，而它是印在订单上的数（与金额同一个理由）。

    override suspend fun unitConversions(): List<AiName> =
        // "名字"就是那行等式本身：换算没有别的自然名字，用户嘴里说的也正是它
        // （「把一车八方改成十方」）。被删掉的换成 `deletedOnly` 那一份（撤回时要读现场）。
        repo.unitConversions().map { AiName(it.id, "1 ${it.fromUnit} = ${it.factor} ${it.toUnit}") }

    override suspend fun createUnitConversion(fields: JsonObject) {
        repo.createUnitConversion(
            com.tapmoay.sorders.data.remote.api.UnitConversionCreateRequest(
                fromUnit = fields.req("from_unit"),
                toUnit = fields.req("to_unit"),
                factor = fields.req("factor"),
                remark = fields.str("remark").orEmpty(),
            ),
        )
    }

    override suspend fun updateUnitConversion(id: Long, fields: JsonObject) {
        require(fields.isNotEmpty()) { "updateUnitConversion 的部分更新体是空的（规格 key 写错了）" }
        repo.updateUnitConversion(
            id,
            com.tapmoay.sorders.data.remote.api.UnitConversionUpdateRequest(
                fromUnit = fields.str("from_unit"),
                toUnit = fields.str("to_unit"),
                factor = fields.str("factor"),
                remark = fields.str("remark"),
            ),
        )
    }

    override suspend fun deleteUnitConversion(id: Long) = repo.deleteUnitConversion(id)

    // ---- 预订单 / 订单模板（2026-09-22）----

    override suspend fun orderTemplates(): List<AiName> =
        repo.orderTemplates().map { AiName(it.id, it.name) }

    override suspend fun createOrderTemplate(fields: JsonObject) {
        repo.createOrderTemplate(
            com.tapmoay.sorders.data.remote.dto.OrderTemplateCreateRequest(
                name = fields.req("name"),
                shipperId = fields.str("shipper_id")?.toLongOrNull(),
                address = fields.str("address").orEmpty(),
                receiverName = fields.str("receiver_name").orEmpty(),
                receiverPhone = fields.str("receiver_phone").orEmpty(),
                freightFee = fields.str("freight_fee"),
                remark = fields.str("remark").orEmpty(),
                lines = fields.orderTemplateLines(),
            ),
        )
    }

    override suspend fun updateOrderTemplate(id: Long, fields: JsonObject) {
        require(fields.isNotEmpty()) { "updateOrderTemplate 的部分更新体是空的（规格 key 写错了）" }
        repo.updateOrderTemplate(
            id,
            com.tapmoay.sorders.data.remote.dto.OrderTemplateUpdateRequest(
                name = fields.str("name"),
                shipperId = fields.str("shipper_id")?.toLongOrNull(),
                address = fields.str("address"),
                receiverName = fields.str("receiver_name"),
                receiverPhone = fields.str("receiver_phone"),
                // ⚠️ 空串（＝"不预设"）**不要**当成一个值发出去：后端把空串也当"不预设"，
                //    但发出去会覆盖掉原有的预设运费 —— 模型没提这一项时就不该动它。
                freightFee = fields.str("freight_fee")?.takeIf { it.isNotBlank() },
                remark = fields.str("remark"),
                // 只有 payload 里真给了 lines 才换（给了就整份换掉）
                lines = if (fields.containsKey("lines")) fields.orderTemplateLines() else null,
                // ⚠️ **非空默认值字段必须显式回填**（判据 `_check_ai_dto_defaults.py`）：
                //    漏掉它，Kotlin 的默认值会被序列化成"要清空货主"发出去 ——
                //    而模型只是想改个备注。默认 false = 不动货主。
                clearShipper = false,
            ),
        )
    }

    override suspend fun deleteOrderTemplate(id: Long) = repo.deleteOrderTemplate(id)

    override suspend fun restoreOrderTemplate(id: Long) {
        // 返回值（恢复后的那条）这一层用不上：撤回走的是"同一条写路径，把旧值塞回去"
        repo.restoreOrderTemplate(id)
    }

    /**
     * payload 里的 `lines` → DTO 行。
     *
     * ⚠️ 这里的键名是**处理器拼好的 payload 键**（`product_id`/`qty`），不是模型参数名
     * （模型传的是 `product`/`quantity`，那一步在 `OrderTemplateWriteHandler` 里做完了）。
     * 两套名字混用的后果是"卡片上写着 6 样货、请求里一行都没有"。
     */
    private fun JsonObject.orderTemplateLines(): List<com.tapmoay.sorders.data.remote.dto.OrderTemplateLineDto> =
        (this["lines"] as? kotlinx.serialization.json.JsonArray)?.mapNotNull { el ->
            val o = el as? JsonObject ?: return@mapNotNull null
            com.tapmoay.sorders.data.remote.dto.OrderTemplateLineDto(
                productId = o.str("product_id")?.toLongOrNull(),
                name = o.str("name").orEmpty(),
                unit = o.str("unit").orEmpty(),
                qty = o.str("qty")?.toIntOrNull() ?: 1,
            )
        } ?: emptyList()

    override suspend fun createFreightTemplate(fields: JsonObject) {
        repo.createFreightTemplate(
            com.tapmoay.sorders.data.remote.dto.FreightTemplateRequest(
                name = fields.req("name"),
                fromPlace = fields.str("from_place").orEmpty(),
                toPlace = fields.str("to_place").orEmpty(),
                vehicleType = fields.str("vehicle_type"),
                fee = fields.str("fee") ?: "0",
                remark = fields.str("remark").orEmpty(),
            ),
        )
    }

    override suspend fun updateFreightTemplate(id: Long, fields: JsonObject) {
        require(fields.isNotEmpty()) { "updateFreightTemplate 的部分更新体是空的（规格 key 写错了）" }
        // PUT 是整体替换：先读回原值
        val cur = repo.freightTemplates().firstOrNull { it.id == id } ?: error("找不到要改的运费模板（$id）")
        repo.updateFreightTemplate(
            id,
            com.tapmoay.sorders.data.remote.dto.FreightTemplateRequest(
                name = cur.name,
                fromPlace = fields.str("from_place") ?: cur.fromPlace,
                toPlace = fields.str("to_place") ?: cur.toPlace,
                vehicleType = cur.vehicleType,
                fee = fields.str("fee") ?: cur.fee,
                remark = fields.str("remark") ?: cur.remark,
            ),
        )
    }

    override suspend fun deleteFreightTemplate(id: Long) = repo.deleteFreightTemplate(id)

    // ---- 供应商 / 厂商档案 + 应付款（2026-09-22）----

    override suspend fun suppliers(): List<AiName> = repo.suppliers().map { AiName(it.id, it.name) }

    /**
     * 应付单名册。
     *
     * `supplierId = null` 时 label 拼成 **「供应商名 · 事由」**：声明式那条路（改/删应付单）
     * 只能给一个参数，而事由是用户自己写的（「9 月货款」），所以必须把供应商名一起拼进去
     * 才认得出用户说的是哪一张。给了编号时（付款那条路）就只用事由 ——
     * 那时候"哪一个供应商"已经由供应商参数确定了。
     *
     * `note` 带上"还差多少"：用户核对时真正要看的就是这个数。
     */
    override suspend fun supplierPayables(supplierId: Long?): List<AiSupplierPayable> {
        val rows = if (supplierId == null) repo.allSupplierPayables() else repo.supplierPayables(supplierId)
        return rows.map {
            AiSupplierPayable(
                id = it.id,
                supplierId = it.supplierId,
                title = if (supplierId == null && it.supplierName.isNotBlank()) {
                    "${it.supplierName} · ${it.title}"
                } else {
                    it.title
                },
                amount = it.amount,
                paid = it.paid,
                unpaid = it.unpaid,
                paymentCount = it.paymentCount,
            )
        }
    }

    /**
     * 付款记录名册：label 拼「供应商 · 事由 · 金额（日期）」。
     *
     * 付款记录**没有天然名字** —— 用户嘴里的说法就是这几项，所以 label 就是那几项。
     * 拼成一条之后 `AiWriteArgs.strict` 的"包含"匹配才认得出「永盛那笔 800」。
     */
    override suspend fun supplierPayments(): List<AiName> = repo.supplierPayments().map {
        AiName(
            id = it.id,
            label = listOf(it.supplierName, it.payableTitle, "${it.amount} 元")
                .filter { s -> s.isNotBlank() }.joinToString(" · ") +
                if (it.payDate.isNotBlank()) "（${it.payDate}）" else "",
            note = if (it.remark.isNotBlank()) "备注：${it.remark}" else null,
        )
    }

    override suspend fun createSupplier(fields: JsonObject) {
        repo.createSupplier(
            com.tapmoay.sorders.data.remote.dto.SupplierCreateRequest(
                name = fields.req("name"),
                contactName = fields.str("contact_name").orEmpty(),
                phone = fields.str("phone").orEmpty(),
                address = fields.str("address").orEmpty(),
                remark = fields.str("remark").orEmpty(),
            ),
        )
    }

    override suspend fun updateSupplier(id: Long, fields: JsonObject) {
        require(fields.isNotEmpty()) { "updateSupplier 的部分更新体是空的（规格 key 写错了）" }
        repo.updateSupplier(
            id,
            com.tapmoay.sorders.data.remote.dto.SupplierUpdateRequest(
                name = fields.str("name"),
                contactName = fields.str("contact_name"),
                phone = fields.str("phone"),
                address = fields.str("address"),
                remark = fields.str("remark"),
            ),
        )
    }

    override suspend fun deleteSupplier(id: Long) = repo.deleteSupplier(id)

    override suspend fun restoreSupplier(id: Long) {
        // 返回值（恢复后的那条）这一层用不上：撤回走的是"同一条写路径，把旧值塞回去"
        repo.restoreSupplier(id)
    }

    override suspend fun createSupplierPayable(fields: JsonObject) {
        repo.createSupplierPayable(
            fields.reqLong("supplier_id"),
            com.tapmoay.sorders.data.remote.dto.SupplierPayableCreateRequest(
                supplierId = fields.reqLong("supplier_id"),
                title = fields.req("title"),
                category = fields.str("category") ?: "货款",
                amount = fields.req("amount"),
                docDate = fields.str("doc_date") ?: java.time.LocalDate.now().toString(),
                remark = fields.str("remark").orEmpty(),
            ),
        )
    }

    override suspend fun updateSupplierPayable(id: Long, fields: JsonObject) {
        require(fields.isNotEmpty()) { "updateSupplierPayable 的部分更新体是空的（规格 key 写错了）" }
        repo.updateSupplierPayable(
            id,
            com.tapmoay.sorders.data.remote.dto.SupplierPayableUpdateRequest(
                title = fields.str("title"),
                category = fields.str("category"),
                amount = fields.str("amount"),
                docDate = fields.str("doc_date"),
                remark = fields.str("remark"),
            ),
        )
    }

    override suspend fun deleteSupplierPayable(id: Long) = repo.deleteSupplierPayable(id)

    override suspend fun restoreSupplierPayable(id: Long) {
        repo.restoreSupplierPayable(id)
    }

    /**
     * 付一笔款。
     *
     * ⚠️ `channel` 与 `pay_date` **必须回填**：`SupplierPaymentCreateRequest` 的默认值
     * （`cash` / 今天是 Kotlin 侧默认）在 `explicitNulls=false` 的序列化下会被**发出去**
     * —— 那样"模型没提付款方式"就会静默变成"现金"。这里的两项都是
     * `SupplierPaymentWriteHandler` **显式算好**放进 payload 的（缺一个就是漏了一处）。
     */
    override suspend fun paySupplierPayable(fields: JsonObject) {
        repo.paySupplierPayable(
            fields.reqLong("payable_id"),
            com.tapmoay.sorders.data.remote.dto.SupplierPaymentCreateRequest(
                amount = fields.req("amount"),
                payDate = fields.req("pay_date"),
                channel = fields.str("channel") ?: "cash",
                remark = fields.str("remark").orEmpty(),
            ),
        )
    }

    override suspend fun cancelSupplierPayment(flowId: Long) = repo.cancelSupplierPayment(flowId)

    override suspend fun restoreSupplierPayment(flowId: Long) {
        repo.restoreSupplierPayment(flowId)
    }

    override suspend fun createVehicle(fields: JsonObject) {
        repo.createVehicle(
            com.tapmoay.sorders.data.remote.dto.VehicleCreateRequest(
                plateNo = fields.req("plate_no"),
                vehicleType = fields.str("vehicle_type").orEmpty(),
                driverId = fields.str("driver_id")?.toLongOrNull(),
            ),
        )
    }

    /**
     * 改车辆：**只搬点名的那几项**（DTO 里没被赋值的字段是 null = 后端"不改这一项"）。
     *
     * ⚠️ `driver_id` 传 null 只会被省略 —— 这条接口**解绑不了司机**。
     *    卡片上写明了这件事（见 `AiWriteBasicData.VEHICLE_UPDATE`），这里不再偷偷改写。
     */
    override suspend fun updateVehicle(id: Long, fields: JsonObject) {
        require(fields.isNotEmpty()) { "updateVehicle 的部分更新体是空的（规格 key 写错了）" }
        repo.updateVehicle(
            id,
            com.tapmoay.sorders.data.remote.dto.VehicleUpdateRequest(
                plateNo = fields.str("plate_no"),
                vehicleType = fields.str("vehicle_type"),
                driverId = null,   // ⚠️ 司机不从这里走（见 setVehicleDriver）
                isActive = fields.str("active")?.toBooleanStrictOrNull(),
            ),
        )
    }

    /**
     * 换/解绑司机：`driverId = null` = **解绑**（v3.44）。
     *
     * 为什么单独一个方法而不是并进 [updateVehicle]：那条路走的是
     * `VehicleUpdateRequest`，而安卓的 `Json { explicitNulls = false }` 会把 `null`
     * 整个键丢掉 —— **解绑在那条路上没有表达方式**。这条走专用接口
     * （`POST /vehicles/{id}/driver`，缺省/null 都算解绑），和 `attachDriverRule` 同形。
     */
    override suspend fun setVehicleDriver(id: Long, driverId: Long?) {
        repo.setVehicleDriver(id, driverId)
    }

    // ---- 商品分类名册 + 商品可见范围（v3.43）----

    /**
     * 分类名册。名字后面挂一个 `note`＝"这一类下有几个在用的商品"（**空分类不给 note**）。
     *
     * 为什么用 `note` 而不是塞进 label：label 要参与**名字匹配**（用户说"水果"要能对上），
     * 混进数字之后 `strict` 的包含匹配会变得莫名其妙；`note` 只用于展示，正好。
     *
     * 为什么 0 个商品时给 null：卡片上那句"改名会把这 N 个商品一起改过去"在 N=0 时是废话，
     * 而它会让人以为"这一改要动一批商品"。空分类就什么都不说。
     */
    override suspend fun productCategories(): List<AiName> = repo.productCategories().map {
        AiName(it.id, it.name, note = if (it.productCount > 0) "${it.productCount} 个商品" else null)
    }

    override suspend fun productVisibility(userId: Long): AiVisibility =
        repo.productVisibility(userId).let { AiVisibility(it.scope, it.productIds) }

    override suspend fun createProductCategory(fields: JsonObject) {
        val created = repo.createProductCategory(
            name = fields.req("name"),
            // 先按"排在最后"建出来；有位置要求时再用 reorder 挪过去（见 moveCategoryTo）。
            sortOrder = null,
        )
        fields.str("sort_order")?.toIntOrNull()?.let { moveCategoryTo(created.id, it) }
    }

    /**
     * 把某个分类挪到「第 N 位」（**从 1 数**，卡片上说的就是这个）。
     *
     * ⚠️ 为什么不能只写 `sort_order = N-1`（2026-09-19 审计）：那是**绝对值**，
     * 后端不会把别人往后挤（`product_categories.py` 的 PATCH 只改自己那一行），
     * 于是"排第 1 位"会和现有第 1 位**撞值**、按 id 排序后落到别处 ——
     * 而卡片上明确承诺了「1 = 最前面」。顺序这件事的真相是**整份列表**，
     * 所以只能走 reorder（`ids[0]` 排最前，后端要求一个不漏）。
     */
    private suspend fun moveCategoryTo(id: Long, position1Based: Int) {
        val ids = repo.productCategories().sortedBy { it.sortOrder }.map { it.id }.toMutableList()
        ids.remove(id)
        val idx = (position1Based - 1).coerceIn(0, ids.size)
        ids.add(idx, id)
        repo.reorderProductCategories(ids)
    }

    override suspend fun updateProductCategory(id: Long, fields: JsonObject) {
        require(fields.isNotEmpty()) { "updateProductCategory 的部分更新体是空的（规格 key 写错了）" }
        repo.updateProductCategory(id, name = fields.str("name"), sortOrder = null)
        // 位置走 reorder（理由见 moveCategoryTo）：只写绝对值会撞车、落到别处
        fields.str("sort_order")?.toIntOrNull()?.let { moveCategoryTo(id, it) }
    }

    override suspend fun deleteProductCategory(id: Long) {
        repo.deleteProductCategory(id)
    }

    /** 我自己的地点分组（按人分区：`repo.placeCategories()` 读的就是当前登录人那一份）。 */
    override suspend fun placeCategories(): List<AiName> = repo.placeCategories().map {
        AiName(it.id, it.name, note = if (it.locationCount > 0) "${it.locationCount} 个地点" else null)
    }

    override suspend fun createPlaceCategory(fields: JsonObject) {
        val created = repo.createPlaceCategory(
            name = fields.req("name"),
            // 先按"排在最后"建出来；有位置要求时再用 reorder 挪过去（与商品分类同一套理由）。
            sortOrder = null,
        )
        fields.str("sort_order")?.toIntOrNull()?.let { movePlaceCategoryTo(created.id, it) }
    }

    /**
     * 把某个分组挪到「第 N 位」（**从 1 数**）。走 reorder 而不是写绝对值 ——
     * 理由与商品分类那份一字不差（绝对值会与现有第 1 位撞车、按 id 排后落到别处）。
     */
    private suspend fun movePlaceCategoryTo(id: Long, position1Based: Int) {
        val ids = repo.placeCategories().sortedBy { it.sortOrder }.map { it.id }.toMutableList()
        ids.remove(id)
        val idx = (position1Based - 1).coerceIn(0, ids.size)
        ids.add(idx, id)
        repo.reorderPlaceCategories(ids)
    }

    override suspend fun updatePlaceCategory(id: Long, fields: JsonObject) {
        require(fields.isNotEmpty()) { "updatePlaceCategory 的部分更新体是空的（规格 key 写错了）" }
        repo.updatePlaceCategory(id, name = fields.str("name"), sortOrder = null)
        fields.str("sort_order")?.toIntOrNull()?.let { movePlaceCategoryTo(id, it) }
    }

    override suspend fun deletePlaceCategory(id: Long) {
        repo.deletePlaceCategory(id)
    }

    override suspend fun reorderPlaceCategories(ids: List<Long>) {
        repo.reorderPlaceCategories(ids)
    }

    override suspend fun reorderProductCategories(ids: List<Long>) {
        repo.reorderProductCategories(ids)
    }

    // ---- 另外三张配置名册（开销 / 运费 / 预订单分类，2026-09-23 补齐 AI 能力覆盖）----
    //
    // ⚠️ 三张的 `note` 都带"这一类下挂着多少东西"：**改名会级联改掉它们**、
    //    **删除会被后端拒绝**（数量就写在报错里）—— 那是用户判断影响面的唯一依据。
    // ⚠️ 位置（第 N 位）与商品/地点分组同一条规矩：**先按"排在最后"建出来，再走 reorder 挪过去**。
    //    直接写 `sort_order = N-1` 是绝对值：后端不会把别人往后挤，于是"排第 1 位"会与
    //    现有第 1 位撞值、按 id 排序后落到别处，而卡片上明确承诺了「1 = 最前面」。

    override suspend fun expenseCategories(): List<AiName> = repo.expenseCategories().map {
        AiName(
            it.id, it.name,
            note = buildString {
                append(if (it.expenseCount > 0) "${it.expenseCount} 笔开销" else "还没有开销")
                append("，卡片突出显示：").append(linkKindCn(it.linkKind))
            },
        )
    }

    override suspend fun freightCategories(): List<AiName> = repo.freightCategories().map {
        AiName(
            it.id, it.name,
            note = if (it.templateCount > 0 || it.ruleCount > 0) {
                "${it.templateCount} 条价目、${it.ruleCount} 份计费规则"
            } else {
                "这一类下还没有价目/规则"
            },
        )
    }

    override suspend fun orderTemplateCategories(): List<AiName> =
        repo.orderTemplateCategories().map {
            AiName(it.id, it.name, note = if (it.templateCount > 0) "${it.templateCount} 张预设单" else null)
        }

    override suspend fun createExpenseCategory(fields: JsonObject) {
        val created = repo.createExpenseCategory(
            name = fields.req("name"),
            // ⚠️ 不传 = 后端默认 "none"（不突出任何一项）；这个仓储方法**没有** sortOrder，
            //    位置要走 reorder 挪（与商品/地点分组同一条规矩，见 moveExpenseCategoryTo）。
            linkKind = fields.str("link_kind") ?: "none",
        )
        fields.str("sort_order")?.toIntOrNull()?.let { moveExpenseCategoryTo(created.id, it) }
    }

    private suspend fun moveExpenseCategoryTo(id: Long, position1Based: Int) {
        val ids = repo.expenseCategories().sortedBy { it.sortOrder }.map { it.id }.toMutableList()
        ids.remove(id)
        ids.add((position1Based - 1).coerceIn(0, ids.size), id)
        repo.reorderExpenseCategories(ids)
    }

    override suspend fun updateExpenseCategory(id: Long, fields: JsonObject) {
        require(fields.isNotEmpty()) { "updateExpenseCategory 的部分更新体是空的（规格 key 写错了）" }
        repo.updateExpenseCategory(
            id,
            name = fields.str("name"),
            linkKind = fields.str("link_kind"),
        )
        fields.str("sort_order")?.toIntOrNull()?.let { moveExpenseCategoryTo(id, it) }
    }

    override suspend fun deleteExpenseCategory(id: Long) {
        repo.deleteExpenseCategory(id)
    }

    override suspend fun reorderExpenseCategories(ids: List<Long>) {
        repo.reorderExpenseCategories(ids)
    }

    override suspend fun createFreightCategory(fields: JsonObject) {
        val created = repo.createFreightCategory(
            com.tapmoay.sorders.data.remote.dto.FreightCategoryCreateRequest(
                name = fields.req("name"),
                sortOrder = null,
            ),
        )
        fields.str("sort_order")?.toIntOrNull()?.let { moveFreightCategoryTo(created.id, it) }
    }

    private suspend fun moveFreightCategoryTo(id: Long, position1Based: Int) {
        val ids = repo.freightCategories().sortedBy { it.sortOrder }.map { it.id }.toMutableList()
        ids.remove(id)
        ids.add((position1Based - 1).coerceIn(0, ids.size), id)
        repo.reorderFreightCategories(ids)
    }

    override suspend fun updateFreightCategory(id: Long, fields: JsonObject) {
        require(fields.isNotEmpty()) { "updateFreightCategory 的部分更新体是空的（规格 key 写错了）" }
        repo.updateFreightCategory(
            id,
            com.tapmoay.sorders.data.remote.dto.FreightCategoryUpdateRequest(
                name = fields.str("name"),
                sortOrder = null,
            ),
        )
        fields.str("sort_order")?.toIntOrNull()?.let { moveFreightCategoryTo(id, it) }
    }

    override suspend fun deleteFreightCategory(id: Long) {
        repo.deleteFreightCategory(id)
    }

    override suspend fun reorderFreightCategories(ids: List<Long>) {
        repo.reorderFreightCategories(ids)
    }

    override suspend fun createOrderTemplateCategory(fields: JsonObject) {
        val created = repo.createOrderTemplateCategory(
            com.tapmoay.sorders.data.remote.dto.OrderTemplateCategoryCreateRequest(
                name = fields.req("name"),
                sortOrder = null,
            ),
        )
        fields.str("sort_order")?.toIntOrNull()?.let { moveOrderTemplateCategoryTo(created.id, it) }
    }

    private suspend fun moveOrderTemplateCategoryTo(id: Long, position1Based: Int) {
        val ids = repo.orderTemplateCategories().sortedBy { it.sortOrder }.map { it.id }.toMutableList()
        ids.remove(id)
        ids.add((position1Based - 1).coerceIn(0, ids.size), id)
        repo.reorderOrderTemplateCategories(ids)
    }

    override suspend fun updateOrderTemplateCategory(id: Long, fields: JsonObject) {
        require(fields.isNotEmpty()) { "updateOrderTemplateCategory 的部分更新体是空的（规格 key 写错了）" }
        repo.updateOrderTemplateCategory(
            id,
            com.tapmoay.sorders.data.remote.dto.OrderTemplateCategoryUpdateRequest(
                name = fields.str("name"),
                sortOrder = null,
            ),
        )
        fields.str("sort_order")?.toIntOrNull()?.let { moveOrderTemplateCategoryTo(id, it) }
    }

    override suspend fun deleteOrderTemplateCategory(id: Long) {
        repo.deleteOrderTemplateCategory(id)
    }

    override suspend fun reorderOrderTemplateCategories(ids: List<Long>) {
        repo.reorderOrderTemplateCategories(ids)
    }

    /** 「卡片上突出哪一项」的中文（开销分类专用，与后端 `LINK_KINDS` 逐值对齐）。 */
    private fun linkKindCn(kind: String): String = when (kind) {
        "vehicle" -> "车辆"
        "driver" -> "司机"
        "order" -> "订单"
        else -> "不突出"
    }

    override suspend fun setProductVisibility(userId: Long, scope: String, productIds: List<Long>) {
        repo.setProductVisibility(userId, scope, productIds)
    }

    override suspend fun createCustomer(fields: JsonObject) {
        repo.createCustomer(
            com.tapmoay.sorders.data.remote.dto.CustomerCreateRequest(
                kind = "tmp",
                name = fields.req("name"),
                phone = fields.str("phone"),
                isMember = fields.str("member")?.toBooleanStrictOrNull() ?: false,
            ),
        )
    }

    // ---- 撤回：全部转发给仓库层的 restore 端点 ----
    // ⚠️ 用块体（`{ ... }`）而不是表达式体（`= ...`）：这些仓库方法返回 DTO，
    //    而接口声明的是 Unit——表达式体在 Kotlin 里会把 DTO 当成返回值，类型对不上。

    override suspend fun restoreAddress(id: Long) {
        repo.restoreAddress(id)
    }

    override suspend fun restoreLocation(id: Long) {
        repo.restoreLocation(id)
    }

    override suspend fun restoreContact(id: Long) {
        repo.restoreContact(id)
    }

    override suspend fun restoreArrearsUnit(id: Long) {
        repo.restoreArrearsUnit(id)
    }

    override suspend fun restoreUnitConversion(id: Long) {
        repo.restoreUnitConversion(id)
    }

    override suspend fun restoreFreightTemplate(id: Long) {
        repo.restoreFreightTemplate(id)
    }

    override suspend fun restoreDriverRule(id: Long) {
        repo.restoreDriverBillingRule(id)
    }

    override suspend fun restoreProduct(id: Long) {
        repo.restoreProduct(id)
    }

    override suspend fun restoreUser(id: Long) {
        repo.restoreUser(id)
    }

    /**
     * 撤回的原料：**把这条记录现在的值读回来**（键名与各动作 payload 一致）。
     *
     * 三条实现约定（每条都有它的理由）：
     * 1. **能用 `GET /{id}` 就用**（少拉一整张表）。后端有单取端点但 Android 侧原来没接的
     *    那几个，这一轮补上了：商品、账号、订单商品行、账本流水、消息。
     * 2. **没有单取的就拉列表再挑**（联系人、地点、挂账单位、运费模板——这些是"某个人名下
     *    的几十条"，拉回来挑一条是合理的）。挑不到 = 返回 null，**不编造**。
     * 3. **键名一律按 payload 键**（`AiRevertRead` 那一份纯函数负责映射）。
     *    两套名字混用的后果是"快照读到了、撤回时取不到"，而那种错不会报错。
     */
    override suspend fun snapshot(resourceKey: String, id: Long): AiBefore? {
        // 两类读法，各自诚实：
        // · **按 id 单取**（后端有 `GET /{id}`）——记录不存在时它会抛 404，
        //   由 [AiRevert.plan] 统一兜住（读不到 = 撤不回来），所以这里不吞异常；
        // · **拉列表再挑**（后端没有单取端点的那几个）——挑不到就是 null，**不编造**。
        return when (resourceKey) {
            "address" -> AiBefore(id, AiRevertRead.address(repo.addressById(id)))
            "product" -> repo.products().firstOrNull { it.id == id }?.let { AiBefore(id, AiRevertRead.product(it)) }
            "product_category" ->
                repo.productCategories().firstOrNull { it.id == id }?.let { AiBefore(id, AiRevertRead.productCategory(it)) }
            "place_category" ->
                repo.placeCategories().firstOrNull { it.id == id }?.let { AiBefore(id, AiRevertRead.placeCategory(it)) }
            // 另外三张配置名册（2026-09-23）：与上面两张同一种做法（拉列表再挑，后端没有单取）。
            "expense_category" ->
                repo.expenseCategories().firstOrNull { it.id == id }
                    ?.let { AiBefore(id, AiRevertRead.expenseCategory(it)) }
            "freight_category" ->
                repo.freightCategories().firstOrNull { it.id == id }
                    ?.let { AiBefore(id, AiRevertRead.freightCategory(it)) }
            "order_template_category" ->
                repo.orderTemplateCategories().firstOrNull { it.id == id }
                    ?.let { AiBefore(id, AiRevertRead.orderTemplateCategory(it)) }
            "vehicle" -> repo.vehicles().firstOrNull { it.id == id }?.let { AiBefore(id, AiRevertRead.vehicle(it)) }
            "product_visibility" ->
                repo.productVisibility(id).let { AiBefore(id, AiRevertRead.productVisibility(it)) }
            "user" -> AiBefore(id, AiRevertRead.user(repo.userById(id)))
            "order" -> AiBefore(id, AiRevertRead.order(repo.order(id)))
            "order_line" -> AiBefore(id, AiRevertRead.orderLine(repo.orderProductLine(id)))
            "ledger_entry" -> AiBefore(id, AiRevertRead.ledgerEntry(repo.ledgerEntry(id)))
            "notification" -> AiBefore(id, AiRevertRead.notification(repo.notificationById(id)))
            "price_rule" -> repo.priceRules().firstOrNull { it.id == id }?.let { AiBefore(id, AiRevertRead.priceRule(it)) }
            "location" -> repo.locations().firstOrNull { it.id == id }?.let { AiBefore(id, AiRevertRead.location(it)) }
            "place" -> repo.placesAll().firstOrNull { it.id == id }?.let { AiBefore(id, AiRevertRead.place(it)) }
            "contact" -> repo.contacts().firstOrNull { it.id == id }?.let { AiBefore(id, AiRevertRead.contact(it)) }
            "arrears_unit" -> repo.arrearsUnits().firstOrNull { it.id == id }?.let { AiBefore(id, AiRevertRead.arrearsUnit(it)) }
            // 单位换算：拉列表再挑（后端没有单取端点）。
            // ⚠️ 撤回一个"恢复"要读的正是那条已经从名册里消失的记录，所以**两份都查**：
            //    活着的读不到就去回收站里找（`deletedOnly = true`）。
            "unit_conversion" ->
                (repo.unitConversions() + repo.unitConversions(deletedOnly = true))
                    .firstOrNull { it.id == id }
                    ?.let { AiBefore(id, AiRevertRead.unitConversion(it)) }
            // 预设单：拉列表再挑（后端没有单取端点）。挑不到 = null，**不编造**。
            "order_template" ->
                repo.orderTemplates().firstOrNull { it.id == id }?.let { AiBefore(id, AiRevertRead.orderTemplate(it)) }
            // 供应商 / 应付款 / 付款记录（2026-09-22）：同样拉列表再挑。
            // ⚠️ 三张都**必须包含回收站里的行**（`includeDeleted = true`）：
            //    撤回一个"恢复"动作时要读的正是那条已经从名册里消失的记录 ——
            //    不带上它，撤回链的第二步会读不到现场而退化成"撤不回来"。
            "supplier" ->
                repo.suppliers(includeDeleted = true).firstOrNull { it.id == id }
                    ?.let { AiBefore(id, AiRevertRead.supplier(it)) }
            "supplier_payable" ->
                repo.allSupplierPayables(includeDeleted = true).firstOrNull { it.id == id }
                    ?.let { AiBefore(id, AiRevertRead.supplierPayable(it)) }
            "supplier_payment" ->
                repo.supplierPayments(includeDeleted = true).firstOrNull { it.id == id }
                    ?.let { AiBefore(id, AiRevertRead.supplierPayment(it)) }
            "freight_template" ->
                repo.freightTemplates().firstOrNull { it.id == id }?.let { AiBefore(id, AiRevertRead.freightTemplate(it)) }
            "driver_rule" ->
                repo.driverBillingRules().firstOrNull { it.id == id }?.let { AiBefore(id, AiRevertRead.driverRule(it)) }
            // 我自己那一本账上的核销记录：**按 id 拉列表再挑**（后端没有单取端点）。
            // 它只被"改类"撤回用到，而撤销/恢复是一对**成对动作**（不需要读现场），
            // 所以这条分支存在的意义是"这条资源真有读法"——红线会逐个资源对账，缺一个就红。
            "shipper_settlement" ->
                repo.mySettlements(includeDeleted = true, limit = SETTLE_SNAPSHOT_PROBE)
                    .rows.firstOrNull { it.id == id }
                    ?.let { AiBefore(id, buildJsonObject { put("settlement_id", it.id) }) }
            // 认不出的资源标识 = **撤不回来**（不是"不需要撤"）。
            // 静默返回一份空现场会让撤回卡弹出来却什么都没写回去——那比没有撤回更糟。
            else -> null
        }
    }

    private companion object {
        /** 查账号名册时一次拉多少条。 */
        const val USER_PROBE_LIMIT = 20

        /**
         * 单号短于这个长度**直接拒绝**（核销/撤销都按单号认单）。
         *
         * 与订单域同一条理由：`GET /orders?q=` 是模糊匹配，两三个字符会命中一堆单，
         * 而"挑一个最像的"在钱上是不可接受的。
         */
        const val MIN_ORDER_NO_LEN = 6

        /** 一笔订单最多列几笔核销记录（撤销时要全摆出来让用户自己指认）。 */
        const val MY_SETTLE_PROBE = 50

        /** 撤回快照最多在多少笔核销里找那一条（后端这个端点一次最多 2000）。 */
        const val SETTLE_SNAPSHOT_PROBE = 300
    }
}