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
    suspend fun orders(status: String? = null, q: String? = null, shipperId: Long? = null, tempShipperName: String? = null, dateFrom: String? = null, dateTo: String? = null) =
        api.orderApi.listOrders(status = status, q = q, shipperId = shipperId, tempShipperName = tempShipperName, dateFrom = dateFrom, dateTo = dateTo)

    suspend fun order(orderId: Long) = api.orderApi.getOrder(orderId)

    suspend fun createOrder(body: com.tapmoay.sorders.data.remote.dto.OrderCreateRequest) =
        api.orderApi.createOrder(body)

    suspend fun cancelOrder(orderId: Long, reason: String = "") = api.orderApi.cancelOrder(orderId)

    suspend fun assignOrder(orderId: Long, driverId: Long, note: String? = null, freightFee: String? = null, collectCash: Boolean? = null) =
        api.orderApi.assignOrder(orderId, com.tapmoay.sorders.data.remote.dto.OrderAssignRequest(driverId, note, freightFee, collectCash))

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
    suspend fun createAddress(body: com.tapmoay.sorders.data.remote.dto.AddressCreateRequest) = api.shipperApi.createAddress(body)
    suspend fun updateAddress(id: Long, body: com.tapmoay.sorders.data.remote.dto.AddressCreateRequest) = api.shipperApi.updateAddress(id, body)
    suspend fun deleteAddress(id: Long) = api.shipperApi.deleteAddress(id)
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
    suspend fun createContact(body: com.tapmoay.sorders.data.remote.dto.ContactCreateRequest) = api.shipperApi.createContact(body)
    suspend fun updateContact(id: Long, body: com.tapmoay.sorders.data.remote.dto.ContactUpdateRequest) = api.shipperApi.updateContact(id, body)
    suspend fun deleteContact(id: Long) = api.shipperApi.deleteContact(id)

    // ---- 账本 ----
    suspend fun ledgerAccounts(from: String? = null, to: String? = null, kind: String = "shipper") = api.ledgerApi.accounts(from, to, kind)
    suspend fun ledgerEntries(shipperId: Long? = null, tempShipperName: String? = null, from: String? = null, to: String? = null) =
        api.ledgerApi.listEntries(shipperId, tempShipperName, from, to)

    suspend fun createLedger(body: com.tapmoay.sorders.data.remote.dto.LedgerCreateRequest) = api.ledgerApi.createEntry(body)
    suspend fun updateLedger(id: Long, body: com.tapmoay.sorders.data.remote.api.LedgerUpdateRequest) = api.ledgerApi.updateEntry(id, body)
    suspend fun deleteLedger(id: Long) = api.ledgerApi.deleteEntry(id)
    suspend fun tempShipperNames() = api.ledgerApi.listTempShipperNames()

    // ---- 商品 ----
    suspend fun priceRules() = api.priceRuleApi.listRules()
    suspend fun createPriceRule(shipperId: Long, productId: Long, specialUnitPrice: String) =
        api.priceRuleApi.createRule(
            com.tapmoay.sorders.data.remote.api.PriceRuleCreateRequest(shipperId, productId, specialUnitPrice)
        )
    suspend fun updatePriceRule(ruleId: Long, specialUnitPrice: String) =
        api.priceRuleApi.updateRule(ruleId, com.tapmoay.sorders.data.remote.api.PriceRuleUpdateRequest(specialUnitPrice))
    suspend fun deletePriceRule(ruleId: Long) = api.priceRuleApi.deleteRule(ruleId)
    suspend fun batchPriceRules(shipperIds: List<Long>, productIds: List<Long>, mode: String, value: String? = null, tierIndex: Int? = null) =
        api.priceRuleApi.batchRules(
            com.tapmoay.sorders.data.remote.api.PriceRuleBatchRequest(shipperIds, productIds, mode, value, tierIndex)
        )

    suspend fun products(includeInactive: Boolean = true) = api.productApi.listProducts(includeInactive)
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
    suspend fun createUser(body: com.tapmoay.sorders.data.remote.api.UserCreateRequest) = api.userApi.createUser(body)
    suspend fun updateUser(id: Long, body: com.tapmoay.sorders.data.remote.api.UserUpdateRequest) = api.userApi.updateUser(id, body)
    suspend fun swapRole(id: Long) = api.userApi.swapRole(id)

    // ---- 挂账单位 / 库存 / 收款 ----
    suspend fun arrearsUnits() = api.arrearsApi.listUnits()
    suspend fun createArrearsUnit(body: com.tapmoay.sorders.data.remote.dto.ArrearsUnitCreateRequest) = api.arrearsApi.createUnit(body)
    suspend fun updateArrearsUnit(id: Long, body: com.tapmoay.sorders.data.remote.dto.ArrearsUnitUpdateRequest) = api.arrearsApi.updateUnit(id, body)
    suspend fun deleteArrearsUnit(id: Long) = api.arrearsApi.deleteUnit(id)

    suspend fun inventorySummary() = api.inventoryApi.summary()
    suspend fun inventoryMovements(productId: Long? = null, dateFrom: String? = null, dateTo: String? = null) = api.inventoryApi.listMovements(productId, dateFrom = dateFrom, dateTo = dateTo)
    suspend fun createMovement(body: com.tapmoay.sorders.data.remote.dto.InventoryMovementCreateRequest) = api.inventoryApi.createMovement(body)

    suspend fun payOrder(orderId: Long) = api.orderApi.payOrder(orderId)
    suspend fun chargeOrder(orderId: Long, arrearsUnitId: Long) =
        api.orderApi.chargeOrder(orderId, com.tapmoay.sorders.data.remote.dto.OrderChargeBody(arrearsUnitId))

    suspend fun notifications(limit: Int = 50) = api.notificationApi.listNotifications(limit)
    suspend fun unreadCount() = api.notificationApi.unreadCount()
    suspend fun markRead(id: Long) = api.notificationApi.markRead(id)
    suspend fun readAll() = api.notificationApi.readAll()

    // ===== 司机运费 =====
    suspend fun completeDirect(orderId: Long, remark: String, payment: String? = null, damageItems: List<com.tapmoay.sorders.data.remote.dto.DamageItem> = emptyList(), damageNote: String = "") =
        api.orderApi.completeOrder(orderId, com.tapmoay.sorders.data.remote.dto.OrderCompleteBody(emptyList(), remark, payment, damageItems, damageNote))

    suspend fun updateFreight(orderId: Long, freightFee: String?) =
        api.orderApi.updateFreight(orderId, com.tapmoay.sorders.data.remote.dto.FreightUpdateRequest(freightFee))

    suspend fun splitOrder(orderId: Long, parts: List<Int>) =
        api.orderApi.splitOrder(orderId, com.tapmoay.sorders.data.remote.dto.OrderSplitRequest(parts))

    suspend fun freightTemplates(vehicleType: String? = null) = api.freightTemplateApi.listTemplates(vehicleType)

    suspend fun createFreightTemplate(body: com.tapmoay.sorders.data.remote.dto.FreightTemplateRequest) =
        api.freightTemplateApi.createTemplate(body)

    suspend fun updateFreightTemplate(id: Long, body: com.tapmoay.sorders.data.remote.dto.FreightTemplateRequest) =
        api.freightTemplateApi.updateTemplate(id, body)

    suspend fun deleteFreightTemplate(id: Long) = api.freightTemplateApi.deleteTemplate(id)

    suspend fun freightSettlement(month: String) = api.freightSettlementApi.settlement(month)
    suspend fun freightSettlementRange(from: String, to: String) = api.freightSettlementApi.settlementRange(from, to)

    suspend fun turnoverReport(mode: String, date: String) = api.reportApi.turnover(mode, date)

    suspend fun productReport(mode: String, date: String) = api.reportApi.products(mode, date)

    suspend fun driverPerformance(dateFrom: String, dateTo: String) =
        api.reportApi.driverPerformance(dateFrom, dateTo)

    suspend fun exceptionOrders(dateFrom: String, dateTo: String) = api.reportApi.exceptionOrders(dateFrom, dateTo)

    suspend fun resolveException(orderId: Long, note: String?) =
        api.reportApi.resolveException(orderId, com.tapmoay.sorders.data.remote.dto.ExceptionResolveRequest(note))

    // ===== 账本 V2（P0）=====
    suspend fun customers(kind: String? = null, q: String? = null) = api.accountingApi.listCustomers(kind, q)
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
    suspend fun createExpense(body: com.tapmoay.sorders.data.remote.dto.ExpenseCreateRequest) = api.accountingApi.createExpense(body)
    suspend fun cashFlows(direction: String? = null, bizType: String? = null, dateFrom: String? = null, dateTo: String? = null) =
        api.accountingApi.listCashFlows(direction, bizType, dateFrom, dateTo)
    suspend fun vehicles() = api.accountingApi.listVehicles()
    suspend fun createVehicle(body: com.tapmoay.sorders.data.remote.dto.VehicleCreateRequest) = api.accountingApi.createVehicle(body)
    suspend fun receipts(customerId: Long? = null) = api.accountingApi.listReceipts(customerId)
    suspend fun createReceipt(body: com.tapmoay.sorders.data.remote.dto.ReceiptCreateRequest) = api.accountingApi.createReceipt(body)
}

/** 把异常统一转为可展示的 ApiException */
fun toApiException(e: Throwable) = ApiClient.toApiException(e)