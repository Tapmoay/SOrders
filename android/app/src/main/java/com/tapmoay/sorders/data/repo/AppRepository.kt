package com.tapmoay.sorders.data.repo

import com.tapmoay.sorders.core.ApiBundle
import com.tapmoay.sorders.core.ApiClient
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.RequestBody
import okhttp3.RequestBody.Companion.asRequestBody
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.File

/** 薄仓库层：统一异常转 ApiException，VM 不再直接接触 Retrofit */
class AppRepository(private val api: ApiBundle) {

    // ---- 订单 ----
    suspend fun orders(status: String? = null, q: String? = null, shipperId: Long? = null, tempShipperName: String? = null, dateFrom: String? = null, dateTo: String? = null, deletedOnly: Boolean? = null) =
        api.orderApi.listOrders(status = status, q = q, shipperId = shipperId, tempShipperName = tempShipperName, dateFrom = dateFrom, dateTo = dateTo, deletedOnly = deletedOnly)

    /** 回收站（隔离区）里按关键词找订单——只有派单员能查。 */
    suspend fun deletedOrders(q: String? = null, limit: Int? = null) =
        api.orderApi.listOrders(q = q, deletedOnly = true).let { if (limit == null) it else it.take(limit) }

    /** 把订单从回收站恢复（仅派单员）。 */
    suspend fun restoreOrder(orderId: Long) = api.orderApi.restoreOrder(orderId)

    /** 一张订单的商品行（带 id，改/删商品行要靠它定位）。 */
    suspend fun orderProductLines(orderId: Long) = api.orderApi.listOrderProducts(orderId)

    suspend fun addOrderProduct(body: com.tapmoay.sorders.data.remote.dto.OrderProductCreateRequest) =
        api.orderApi.createOrderProduct(body)

    suspend fun updateOrderProduct(lineId: Long, body: com.tapmoay.sorders.data.remote.dto.OrderProductUpdateRequest) =
        api.orderApi.updateOrderProduct(lineId, body)

    suspend fun deleteOrderProduct(lineId: Long) = api.orderApi.deleteOrderProduct(lineId)

    /** 撤回用：单取一行商品行（`line_id` 在手里，但没有 order_id 就查不动列表端点）。 */
    suspend fun orderProductLine(lineId: Long) = api.orderApi.getOrderProduct(lineId)

    suspend fun order(orderId: Long) = api.orderApi.getOrder(orderId)

    suspend fun createOrder(body: com.tapmoay.sorders.data.remote.dto.OrderCreateRequest) =
        api.orderApi.createOrder(body)

    suspend fun cancelOrder(orderId: Long, reason: String = "") = api.orderApi.cancelOrder(orderId)

    /** 软删除订单（进入隔离区 30 天：用户不可见，派单员可恢复） */
    suspend fun deleteOrder(orderId: Long) = api.orderApi.deleteOrder(orderId)

    /**
     * 派单。最后两个是**派单员对这一单单独定的计费参数**（v3.37）：
     * 逐单金额（这一单的钱不固定时用）与逐单提成比例；不传 = 用司机挂着的规则里的值。
     */
    suspend fun assignOrder(
        orderId: Long,
        driverId: Long,
        note: String? = null,
        freightFee: String? = null,
        collectCash: Boolean? = null,
        pieceAmount: String? = null,
        commissionRate: String? = null,
    ) = api.orderApi.assignOrder(
        orderId,
        com.tapmoay.sorders.data.remote.dto.OrderAssignRequest(
            driverId, note, freightFee, collectCash, pieceAmount, commissionRate,
        ),
    )

    suspend fun batchAssign(orderIds: List<Long>, driverId: Long, note: String? = null, collectCash: Boolean? = null) =
        api.orderApi.batchAssign(com.tapmoay.sorders.data.remote.dto.OrderBatchAssignRequest(orderIds, driverId, note, collectCash))

    suspend fun recallOrder(orderId: Long, reason: String) =
        api.orderApi.recallOrder(orderId, com.tapmoay.sorders.data.remote.dto.OrderRecallBody(reason))

    suspend fun updateOrder(orderId: Long, body: com.tapmoay.sorders.data.remote.dto.OrderUpdateRequest) =
        api.orderApi.updateOrder(orderId, body)

    suspend fun markException(orderId: Long, body: com.tapmoay.sorders.data.remote.dto.OrderExceptionBody) =
        api.orderApi.markException(orderId, body)

    suspend fun pendingCount() = api.orderApi.pendingDispatchCount()

    // ---- 司机端操作 ----
    suspend fun driverAck(orderId: Long) = api.orderApi.driverAck(orderId)

    suspend fun driverNote(orderId: Long, note: String) =
        api.orderApi.driverNote(orderId, com.tapmoay.sorders.data.remote.dto.DriverNoteBody(note))

    suspend fun uploadDeliveryPhotos(orderId: Long, files: List<File>) =
        api.orderApi.uploadDeliveryPhotos(orderId, files.toParts())

    suspend fun uploadOrderAddressImage(orderId: Long, file: File) =
        api.orderApi.uploadOrderAddressImage(
            orderId,
            MultipartBody.Part.createFormData(
                "file",
                file.name,
                file.asRequestBody("image/jpeg".toMediaType()),
            ),
        )

    suspend fun completeWithUpload(orderId: Long, files: List<File>, remark: String, payment: String? = null, damageItems: List<com.tapmoay.sorders.data.remote.dto.DamageItem> = emptyList(), damageNote: String = ""): com.tapmoay.sorders.data.remote.dto.OrderDto =
        api.orderApi.completeOrderWithUpload(
            orderId,
            files.toParts(),
            remark.toRequestBody("text/plain".toMediaType()),
            (payment ?: "").toRequestBody("text/plain".toMediaType()),
            ApiClient.json.encodeToString(com.tapmoay.sorders.data.remote.dto.DamageItem.serializer().let { kotlinx.serialization.builtins.ListSerializer(it) }, damageItems).toRequestBody("text/plain".toMediaType()),
            damageNote.toRequestBody("text/plain".toMediaType()),
        )

    private fun List<File>.toParts(): List<MultipartBody.Part> = map { f ->
        MultipartBody.Part.createFormData(
            "files",
            f.name,
            f.asRequestBody("image/jpeg".toMediaType()),
        )
    }

    // ---- 货主 ----
    suspend fun addresses() = api.shipperApi.listAddresses()

    /** 撤回用：单取一条地址（见 Apis.kt 上的注释）。 */
    suspend fun addressById(id: Long) = api.shipperApi.getAddress(id)

    suspend fun createAddress(body: com.tapmoay.sorders.data.remote.dto.AddressCreateRequest) = api.shipperApi.createAddress(body)
    suspend fun updateAddress(id: Long, body: com.tapmoay.sorders.data.remote.dto.AddressCreateRequest) = api.shipperApi.updateAddress(id, body)
    suspend fun deleteAddress(id: Long) = api.shipperApi.deleteAddress(id)

    /** 撤回：DELETE 的逆操作（后端是软删，恢复是逐字段照搬）。 */
    suspend fun restoreAddress(id: Long) = api.shipperApi.restoreAddress(id)
    suspend fun setDefaultAddress(id: Long) = api.shipperApi.setDefaultAddress(id)
    suspend fun contacts() = api.shipperApi.listContacts()
    suspend fun locations() = api.shipperApi.listLocations()
    suspend fun uploadLocationImage(file: File) = api.shipperApi.uploadLocationImage(
        MultipartBody.Part.createFormData(
            "file",
            file.name,
            file.asRequestBody("image/jpeg".toMediaType()),
        ),
    )
    suspend fun createLocation(body: com.tapmoay.sorders.data.remote.dto.LocationCreateRequest) = api.shipperApi.createLocation(body)
    suspend fun updateLocation(id: Long, body: com.tapmoay.sorders.data.remote.dto.LocationCreateRequest) = api.shipperApi.updateLocation(id, body)
    suspend fun deleteLocation(id: Long) = api.shipperApi.deleteLocation(id)

    suspend fun restoreLocation(id: Long) = api.shipperApi.restoreLocation(id)
    suspend fun createContact(body: com.tapmoay.sorders.data.remote.dto.ContactCreateRequest) = api.shipperApi.createContact(body)
    suspend fun updateContact(id: Long, body: com.tapmoay.sorders.data.remote.dto.ContactUpdateRequest) = api.shipperApi.updateContact(id, body)
    suspend fun deleteContact(id: Long) = api.shipperApi.deleteContact(id)

    suspend fun restoreContact(id: Long) = api.shipperApi.restoreContact(id)

    // ---- 共享地点库（导航信息）----
    /**
     * 全库共享的导航坐标（**不按人分区**，三种角色共用一张表）。
     * `q` 为空 = 按"用过多少次"倒序取前 N 条（常用的排前面）。
     */
    suspend fun places(q: String? = null, limit: Int = 100) = api.placeApi.listPlaces(q, limit)

    /** 手工往共享地点库加一个点（坐标 1 米内/同名 30 米内会并入已有记录）。 */
    suspend fun createPlace(body: com.tapmoay.sorders.data.remote.dto.PlaceCreateRequest) =
        api.placeApi.createPlace(body)

    /** 记一次「我用了这个共享地点」；用到第 2 次后端会自动收进我的地点库。 */
    suspend fun usePlace(placeId: Long) = api.placeApi.usePlace(placeId)

    /**
     * 司机到场补导航信息。后端一次写三处：这一单、货主的地点库、全库共享地点库。
     * 订单原本已有坐标时会 400（`ApiException.message` 是一句可读的中文）。
     */
    suspend fun fillOrderNavigation(orderId: Long, body: com.tapmoay.sorders.data.remote.dto.OrderNavigationBody) =
        api.orderApi.fillNavigation(orderId, body)

    // ---- 账本 ----
    suspend fun ledgerAccounts(from: String? = null, to: String? = null, kind: String = "shipper") = api.ledgerApi.accounts(from, to, kind)
    suspend fun ledgerEntries(shipperId: Long? = null, tempShipperName: String? = null, from: String? = null, to: String? = null) =
        api.ledgerApi.listEntries(shipperId, tempShipperName, from, to)

    suspend fun createLedger(body: com.tapmoay.sorders.data.remote.dto.LedgerCreateRequest) = api.ledgerApi.createEntry(body)
    suspend fun updateLedger(id: Long, body: com.tapmoay.sorders.data.remote.api.LedgerUpdateRequest) = api.ledgerApi.updateEntry(id, body)
    suspend fun deleteLedger(id: Long) = api.ledgerApi.deleteEntry(id)

    /**
     * 撤回用：单取一条账本流水。
     *
     * 端点（`GET /ledger/entries/{id}`）**一直在 Apis.kt 里躺着，从来没有人调过**——
     * 上面那个列表端点不传日期就是"全部流水"（派单员视角几万行），
     * 为了读一行而拉全表是不行的。
     */
    suspend fun ledgerEntry(id: Long) = api.ledgerApi.getEntry(id)

    suspend fun tempShipperNames() = api.ledgerApi.listTempShipperNames()

    /** 把已送达订单补进账本（幂等）。`shipperId` 为 null = 全部货主。 */
    suspend fun syncLedgerFromDelivered(shipperId: Long?) =
        api.ledgerApi.syncFromDelivered(com.tapmoay.sorders.data.remote.api.LedgerSyncBody(shipperId = shipperId))

    // ---- 商品 ----
    suspend fun priceRules() = api.priceRuleApi.listRules()
    suspend fun createPriceRule(shipperId: Long, productId: Long, specialUnitPrice: String) =
        api.priceRuleApi.createRule(
            com.tapmoay.sorders.data.remote.api.PriceRuleCreateRequest(shipperId, productId, specialUnitPrice)
        )
    suspend fun updatePriceRule(ruleId: Long, specialUnitPrice: String) =
        api.priceRuleApi.updateRule(ruleId, com.tapmoay.sorders.data.remote.api.PriceRuleUpdateRequest(specialUnitPrice))
    suspend fun deletePriceRule(ruleId: Long) = api.priceRuleApi.deleteRule(ruleId)
    /**
     * 批量调价（多批发商 × 多商品一次写价）。
     *
     * @param mode fixed / tier / percent / adjust
     * @param adjustPercent 只在 adjust 模式下用：在当前生效价基础上涨/降百分之多少。
     *   它和 percent 模式**不是一回事**（见 PriceRuleBatchRequest 的注释）。
     */
    suspend fun batchPriceRules(
        shipperIds: List<Long>,
        productIds: List<Long>,
        mode: String,
        value: String? = null,
        tierIndex: Int? = null,
        adjustPercent: String? = null,
    ) = api.priceRuleApi.batchRules(
        com.tapmoay.sorders.data.remote.api.PriceRuleBatchRequest(
            shipperIds = shipperIds,
            productIds = productIds,
            mode = mode,
            value = value,
            tierIndex = tierIndex,
            adjustPercent = adjustPercent,
        ),
    )

    suspend fun products(includeInactive: Boolean = true) = api.productApi.listProducts(includeInactive)

    // ---- 商品分类名册（顺序由派单员定，下单页左侧那一列按它排）----
    suspend fun productCategories() = api.productApi.listCategories()
    suspend fun createProductCategory(name: String, sortOrder: Int? = null) =
        api.productApi.createCategory(com.tapmoay.sorders.data.remote.dto.ProductCategoryCreateRequest(name, sortOrder))
    /**
     * 改名 / 改顺序（`PATCH /product-categories/{id}`，后端是部分更新：null = 不动）。
     *
     * `sortOrder` 是**名册里的绝对位置值**：后端按 `(sort_order, id)` 排序，
     * `reorder` 写的也是同一套值（`ids[0]` = 0），所以"排到第几位"这层换算由调用方负责。
     */
    suspend fun updateProductCategory(id: Long, name: String? = null, sortOrder: Int? = null) =
        api.productApi.updateCategory(
            id,
            com.tapmoay.sorders.data.remote.dto.ProductCategoryUpdateRequest(name = name, sortOrder = sortOrder),
        )
    suspend fun deleteProductCategory(id: Long) = api.productApi.deleteCategory(id)
    /** 整份顺序一次提交（`ids[0]` 排最前）。只传一部分后端会 400。 */
    suspend fun reorderProductCategories(ids: List<Long>) =
        api.productApi.reorderCategories(com.tapmoay.sorders.data.remote.dto.ProductCategoryReorderRequest(ids))

    // ---- 商品可见范围（白名单：勾了的才给他看）----
    suspend fun productVisibility(userId: Long) = api.productApi.getProductVisibility(userId)
    suspend fun setProductVisibility(userId: Long, scope: String, productIds: List<Long>) =
        api.productApi.setProductVisibility(
            userId,
            com.tapmoay.sorders.data.remote.dto.ProductVisibilityRequest(scope, productIds),
        )

    // AI 写动作要用的三个（原来只转发了 list 与传图）
    suspend fun createProduct(body: com.tapmoay.sorders.data.remote.api.ProductCreateRequest) =
        api.productApi.createProduct(body)

    suspend fun updateProduct(id: Long, body: com.tapmoay.sorders.data.remote.api.ProductUpdateRequest) =
        api.productApi.updateProduct(id, body)

    suspend fun deleteProduct(id: Long) = api.productApi.deleteProduct(id)

    suspend fun restoreProduct(id: Long) = api.productApi.restoreProduct(id)
    suspend fun uploadProductImage(productId: Long, file: File) =
        api.productApi.uploadProductImage(
            productId,
            MultipartBody.Part.createFormData(
                "file",
                file.name,
                file.asRequestBody("image/jpeg".toMediaType()),
            ),
        )

    // ---- 用户/通知 ----
    suspend fun me() = api.userApi.me()
    suspend fun drivers() = api.userApi.listUsers(role = "driver", limit = 500)
    suspend fun shippers() = api.userApi.listUsers(role = "shipper", limit = 500)
    /** 会员 = 高级货主 */
    suspend fun members() = api.userApi.listUsers(role = "shipper", isMember = true, limit = 500)
    suspend fun shippersOrDrivers(role: String = "shipper") = api.userApi.listUsers(role = role, limit = 500)
    /** 全量用户（账户管理：派单员视角） */
    suspend fun usersAll() = api.userApi.listUsers(limit = 500)
    suspend fun createUser(body: com.tapmoay.sorders.data.remote.api.UserCreateRequest) = api.userApi.createUser(body)
    suspend fun updateUser(id: Long, body: com.tapmoay.sorders.data.remote.api.UserUpdateRequest) = api.userApi.updateUser(id, body)
    suspend fun swapRole(id: Long) = api.userApi.swapRole(id)
    suspend fun deleteUser(id: Long) = api.userApi.deleteUser(id)

    suspend fun restoreUser(id: Long) = api.userApi.restoreUser(id)

    /** 撤回用：单取一个账号（`users/me` 只能取自己，搜名字是模糊匹配，都不行）。 */
    suspend fun userById(id: Long) = api.userApi.getUser(id)

    // ---- 挂账单位 / 库存 / 收款 ----
    suspend fun arrearsUnits() = api.arrearsApi.listUnits()
    suspend fun createArrearsUnit(body: com.tapmoay.sorders.data.remote.dto.ArrearsUnitCreateRequest) = api.arrearsApi.createUnit(body)
    suspend fun updateArrearsUnit(id: Long, body: com.tapmoay.sorders.data.remote.dto.ArrearsUnitUpdateRequest) = api.arrearsApi.updateUnit(id, body)
    suspend fun deleteArrearsUnit(id: Long) = api.arrearsApi.deleteUnit(id)

    suspend fun restoreArrearsUnit(id: Long) = api.arrearsApi.restoreArrearsUnit(id)

    suspend fun inventorySummary() = api.inventoryApi.summary()
    suspend fun inventoryMovements(productId: Long? = null, dateFrom: String? = null, dateTo: String? = null) = api.inventoryApi.listMovements(productId, dateFrom = dateFrom, dateTo = dateTo)
    suspend fun createMovement(body: com.tapmoay.sorders.data.remote.dto.InventoryMovementCreateRequest) = api.inventoryApi.createMovement(body)

    suspend fun payOrder(orderId: Long) = api.orderApi.payOrder(orderId)
    suspend fun chargeOrder(orderId: Long, arrearsUnitId: Long) =
        api.orderApi.chargeOrder(orderId, com.tapmoay.sorders.data.remote.dto.OrderChargeBody(arrearsUnitId))

    /**
     * 我的消息列表。
     *
     * ⚠️ `limit` 这个参数后端**不认**（FastAPI 静默忽略未知 query），后端是硬 `.limit(200)`。
     * 也就是说真实上限永远是 200 条，传 50 或 100 只是"看起来能控制条数"。
     * 这里保留参数是为了调用方语义清楚（将来后端支持时不用改调用点），**不要**把它当成有效约束。
     */
    suspend fun notifications(limit: Int = 50) = api.notificationApi.listNotifications(limit)

    /**
     * AI 附件：把用户选的文件交给服务端读成文本表格。
     *
     * **服务端不保存这个文件**（读一遍就还回来，不落盘、不进库）——用户传的可能是
     * 带成本价的商品表，留副本就要回答"存哪、留多久、谁能下"，而这三个问题在这里没有存在的必要。
     */
    suspend fun parseSheet(filename: String, mime: String, bytes: ByteArray, maxRows: Int = 200) =
        api.fileApi.parseSheet(
            MultipartBody.Part.createFormData(
                "file",
                filename.ifBlank { "upload" },
                bytes.toRequestBody(mime.ifBlank { "application/octet-stream" }.toMediaType()),
            ),
            maxRows,
        )

    /**
     * 撤回用：单取一条消息。
     *
     * 为什么不能用列表代替：列表最多回 200 条（后端硬上限，见 [notifications]），
     * 而"改消息"撤回要知道它**改之前**的标题正文——那条大概率不在最近 200 条里，
     * 于是撤回会静默地没有入口。
     */
    suspend fun notificationById(id: Long) = api.notificationApi.getNotification(id)

    /**
     * **发给某个人**的消息（按收件人过滤）。
     *
     * 用途是"要看别人收到了什么"：派单员传 recipientId 就能看某个账户的消息
     * （消息中心的管理视角）。
     *
     * ⚠️ 传 null 时后端**不是**"不过滤"，而是**等同传自己**——收件人过滤在这条接口上
     * 与"清空/标记已读只动自己的"是同一套口径（2026-09-17 修正，之前那个
     * "派单员不带 recipient_id 会拿到所有人的消息"的行为是个 bug，已修）。
     */
    suspend fun notificationsFor(recipientId: Long?, limit: Int = 50) =
        api.notificationApi.listNotifications(limit, recipientId)
    suspend fun unreadCount() = api.notificationApi.unreadCount()
    suspend fun markRead(id: Long) = api.notificationApi.markRead(id)
    suspend fun readAll() = api.notificationApi.readAll()

    /** 给某个人发一条站内消息（会推送）。 */
    suspend fun sendNotification(body: com.tapmoay.sorders.data.remote.dto.NotificationCreateRequest) =
        api.notificationApi.create(body)

    /** 价格变更通知：一次通知一批货主（后端自己拼标题正文）。 */
    suspend fun notifyPriceChange(body: com.tapmoay.sorders.data.remote.dto.PriceChangeNotifyRequest) =
        api.notificationApi.priceNotify(body)

    /** 批量删消息：`ids` 指定列表，或 `all=true` 清空（二选一）。 */
    suspend fun deleteNotifications(ids: List<Long>, all: Boolean) =
        api.notificationApi.batchDelete(
            com.tapmoay.sorders.data.remote.dto.NotificationBatchDeleteRequest(ids = ids, all = all),
        )

    /** 改一条消息的标题/正文。 */
    suspend fun updateNotification(id: Long, title: String?, content: String?) =
        api.notificationApi.update(
            id,
            buildMap {
                title?.let { put("title", it) }
                content?.let { put("content", it) }
            },
        )

    // ===== 司机运费 =====
    suspend fun completeDirect(orderId: Long, remark: String, payment: String? = null, damageItems: List<com.tapmoay.sorders.data.remote.dto.DamageItem> = emptyList(), damageNote: String = "") =
        api.orderApi.completeOrder(orderId, com.tapmoay.sorders.data.remote.dto.OrderCompleteBody(emptyList(), remark, payment, damageItems, damageNote))

    suspend fun updateFreight(orderId: Long, freightFee: String?) =
        api.orderApi.updateFreight(orderId, com.tapmoay.sorders.data.remote.dto.FreightUpdateRequest(freightFee))

    suspend fun splitOrder(orderId: Long, parts: List<Int>) =
        api.orderApi.splitOrder(orderId, com.tapmoay.sorders.data.remote.dto.OrderSplitRequest(parts))

    suspend fun freightTemplates(vehicleType: String? = null) = api.freightTemplateApi.listTemplates(vehicleType)

    /** 运费模板名册（AI 改/删模板时先找到那一条） */
    suspend fun freightTemplates() = api.freightTemplateApi.listTemplates()
    suspend fun createFreightTemplate(body: com.tapmoay.sorders.data.remote.dto.FreightTemplateRequest) =
        api.freightTemplateApi.createTemplate(body)

    suspend fun updateFreightTemplate(id: Long, body: com.tapmoay.sorders.data.remote.dto.FreightTemplateRequest) =
        api.freightTemplateApi.updateTemplate(id, body)

    suspend fun deleteFreightTemplate(id: Long) = api.freightTemplateApi.deleteTemplate(id)

    suspend fun restoreFreightTemplate(id: Long) = api.freightTemplateApi.restoreFreightTemplate(id)

    // ---- 司机计费规则模板 ----
    //
    // 这一组是**界面和 AI 写能力共用**的接口（AI 侧照这些名字直接调），所以签名不要随手改。

    /** 计费规则列表。`deletedOnly = true` = 回收站（删错了要能看见并恢复）。 */
    suspend fun driverBillingRules(
        vehicleType: String? = null,
        deletedOnly: Boolean = false,
    ): List<com.tapmoay.sorders.data.remote.dto.DriverBillingRuleDto> =
        api.driverBillingRuleApi.listRules(vehicleType, deletedOnly)

    suspend fun createDriverBillingRule(
        body: com.tapmoay.sorders.data.remote.dto.DriverBillingRuleRequest,
    ): com.tapmoay.sorders.data.remote.dto.DriverBillingRuleDto =
        api.driverBillingRuleApi.createRule(body)

    suspend fun updateDriverBillingRule(
        id: Long,
        body: com.tapmoay.sorders.data.remote.dto.DriverBillingRuleRequest,
    ): com.tapmoay.sorders.data.remote.dto.DriverBillingRuleDto =
        api.driverBillingRuleApi.updateRule(id, body)

    suspend fun deleteDriverBillingRule(id: Long) = api.driverBillingRuleApi.deleteRule(id)

    suspend fun restoreDriverBillingRule(
        id: Long,
    ): com.tapmoay.sorders.data.remote.dto.DriverBillingRuleDto =
        api.driverBillingRuleApi.restoreRule(id)

    /**
     * 把规则挂到司机身上；`ruleId = null` = 解挂（他退回按车型/工资的老口径）。
     *
     * @return 挂上之后的规则；**解挂时返回 null**（后端那时回的就是 JSON `null`）。
     *
     * 三条拦截在后端，错误是中文原文，直接显示即可：不是司机账号 / 规则在回收站 /
     * 车型对不上（规则限挂车、司机是大车）。最后一条最要紧——挂错了不会报错，
     * 只是他从这一刻起每一单都按错的规则算钱。
     */
    suspend fun attachDriverRule(
        driverId: Long,
        ruleId: Long?,
    ): com.tapmoay.sorders.data.remote.dto.DriverBillingRuleDto? {
        val el = api.driverBillingRuleApi.attachRule(
            com.tapmoay.sorders.data.remote.dto.DriverBillingRuleAttachRequest(driverId, ruleId),
        )
        // JsonNull = 解挂成功（不是"没返回"）。读不出形状时**不编造**：让它抛，
        // 调用方（AI/编辑页）会把它转成一句人话，而不是显示"已挂载"。
        if (el is kotlinx.serialization.json.JsonNull) return null
        return ApiClient.json.decodeFromString(
            com.tapmoay.sorders.data.remote.dto.DriverBillingRuleDto.serializer(),
            el.toString(),
        )
    }

    suspend fun freightSettlement(month: String) = api.freightSettlementApi.settlement(month)
    suspend fun freightSettlementRange(from: String, to: String) = api.freightSettlementApi.settlementRange(from, to)

    suspend fun turnoverReport(mode: String, date: String) = api.reportApi.turnover(mode, date)

    suspend fun productReport(mode: String, date: String) = api.reportApi.products(mode, date)

    suspend fun driverPerformance(dateFrom: String, dateTo: String) =
        api.reportApi.driverPerformance(dateFrom, dateTo)

    suspend fun exceptionOrders(dateFrom: String, dateTo: String) = api.reportApi.exceptionOrders(dateFrom, dateTo)

    suspend fun resolveException(orderId: Long, note: String?) =
        api.reportApi.resolveException(orderId, com.tapmoay.sorders.data.remote.dto.ExceptionResolveRequest(note))

    suspend fun operationLogs(limit: Int = 60) = api.reportApi.operationLogs(limit)

    /**
     * 原始 GET（只给 AI 的通用读工具用）。
     *
     * 路径来自 `AiReadCatalog`（32/36 条编译期白名单），参数已过白名单——**不接受任意 URL**。
     * 单独放一个方法而不是让 AI 自己造 Retrofit：这样它走的就是同一个带 token 的客户端，
     * 权限与用户在 App 里点页面完全一致。
     */
    suspend fun rawGet(path: String, params: Map<String, String>) = api.rawApi.get(path, params)

    suspend fun exportReport(kind: String, mode: String, date: String, dateFrom: String? = null, dateTo: String? = null) =
        api.reportApi.exportReport(kind, mode, date, dateFrom, dateTo)

    suspend fun arrearsSummary(dateFrom: String, dateTo: String) = api.reportApi.arrearsSummary(dateFrom, dateTo)

    // ===== 账本 V2（P0）=====
    suspend fun customers(kind: String? = null, q: String? = null) = api.accountingApi.listCustomers(kind, q)

    suspend fun checkUpdate() = api.systemApi.appVersion()
    suspend fun createCustomer(body: com.tapmoay.sorders.data.remote.dto.CustomerCreateRequest) = api.accountingApi.createCustomer(body)
    suspend fun driverBills(driverId: Long? = null, month: String? = null, status: String? = null) =
        api.accountingApi.listDriverBills(driverId, month, status)
    suspend fun generateBills(body: com.tapmoay.sorders.data.remote.dto.DriverBillGenerateRequest) = api.accountingApi.generateBills(body)
    suspend fun settlements(driverId: Long? = null, month: String? = null, status: String? = null) =
        api.accountingApi.listSettlements(driverId, month, status)
    suspend fun createSettlement(body: com.tapmoay.sorders.data.remote.dto.SettlementCreateRequest) = api.accountingApi.createSettlement(body)
    suspend fun settlementAction(id: Long, action: String, method: String = "cash") =
        api.accountingApi.settlementAction(id, com.tapmoay.sorders.data.remote.dto.SettlementActionRequest(action, method))
    suspend fun expenses(category: String? = null, driverId: Long? = null, dateFrom: String? = null, dateTo: String? = null) =
        api.accountingApi.listExpenses(category, driverId, dateFrom, dateTo)
    /** @param idempotencyKey 见 [com.tapmoay.sorders.data.remote.api.AccountingApi.createExpense]；手动记账不传。 */
    suspend fun createExpense(
        body: com.tapmoay.sorders.data.remote.dto.ExpenseCreateRequest,
        idempotencyKey: String? = null,
    ) = api.accountingApi.createExpense(body, idempotencyKey)
    suspend fun cashFlows(direction: String? = null, bizType: String? = null, dateFrom: String? = null, dateTo: String? = null) =
        api.accountingApi.listCashFlows(direction, bizType, dateFrom, dateTo)
    suspend fun vehicles() = api.accountingApi.listVehicles()
    suspend fun createVehicle(body: com.tapmoay.sorders.data.remote.dto.VehicleCreateRequest) = api.accountingApi.createVehicle(body)
    /** 改车辆（只传要改的键）。解绑司机**不走这里**，见 [setVehicleDriver]。 */
    suspend fun updateVehicle(id: Long, body: com.tapmoay.sorders.data.remote.dto.VehicleUpdateRequest) =
        api.accountingApi.updateVehicle(id, body)

    /**
     * 绑司机 / 解绑：`driverId = null` **就是解绑**。
     *
     * 为什么不能顺手用 `updateVehicle`：那个 DTO 的 null 会被序列化层丢掉，
     * 于是"解绑"变成一个**没有表达方式**的动作（界面点了、请求发出去了、司机还在车上）。
     * 详见 `dto/VehicleDriverSetRequest` 的注释。
     */
    suspend fun setVehicleDriver(id: Long, driverId: Long?) =
        api.accountingApi.setVehicleDriver(id, com.tapmoay.sorders.data.remote.dto.VehicleDriverSetRequest(driverId))
    suspend fun receipts(customerId: Long? = null) = api.accountingApi.listReceipts(customerId)
    suspend fun createReceipt(body: com.tapmoay.sorders.data.remote.dto.ReceiptCreateRequest) = api.accountingApi.createReceipt(body)

    // ===== AI 助手（全部只读，5 个工具的唯一数据出口）=====

    /** 按姓名/手机号搜用户（AI 工具 search_shipper；调用方按 role 过滤出货主） */
    suspend fun searchUsers(q: String, limit: Int = 50) = api.userApi.searchUsers(q, limit)

    /** 库存已达报警阈值的商品（AI 工具 inventory_alerts） */
    suspend fun inventoryBelowAlert() = api.inventoryApi.summaryBelowAlert(true)

    /** 货主下单排行（AI 工具 shipper_performance；后端新端点，未上线时抛 404） */
    suspend fun shipperPerformance(dateFrom: String, dateTo: String) =
        api.reportApi.shipperPerformance(dateFrom, dateTo)
}

/** 把异常统一转为可展示的 ApiException */
fun toApiException(e: Throwable) = ApiClient.toApiException(e)