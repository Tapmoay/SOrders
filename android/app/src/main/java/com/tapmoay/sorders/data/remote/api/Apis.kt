package com.tapmoay.sorders.data.remote.api

import com.tapmoay.sorders.data.remote.dto.*
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonObject
import okhttp3.MultipartBody
import okhttp3.RequestBody
import retrofit2.http.*

interface AuthApi {
    @POST("auth/login")
    suspend fun login(@Body body: LoginRequest): TokenDto

    @POST("auth/sms/send")
    suspend fun sendSms(@Body body: SendSmsRequest): JsonObject

    @POST("auth/register")
    suspend fun register(@Body body: RegisterRequest): TokenDto
}

interface UserApi {
    @GET("users/me")
    suspend fun me(): UserDto

    @GET("users")
    suspend fun listUsers(
        @Query("role") role: String? = null,
        @Query("is_member") isMember: Boolean? = null,
        @Query("skip") skip: Int = 0,
        @Query("limit") limit: Int = 100,
    ): List<UserDto>

    @POST("users")
    suspend fun createUser(@Body body: UserCreateRequest): UserDto

    @PATCH("users/{userId}")
    suspend fun updateUser(@Path("userId") userId: Long, @Body body: UserUpdateRequest): UserDto

    @POST("users/{userId}/swap-shipper-driver")
    suspend fun swapRole(@Path("userId") userId: Long): UserDto
}

@Serializable
data class UserCreateRequest(
    val phone: String,
    val username: String? = null,
    val password: String,
    @SerialName("full_name") val fullName: String = "",
    val role: String,
    @SerialName("is_member") val isMember: Boolean = false,
    @SerialName("vehicle_type") val vehicleType: String? = null,
    @SerialName("billing_mode") val billingMode: String? = null,
    @Serializable(with = com.tapmoay.sorders.data.remote.dto.NullableFlexibleStringSerializer::class) val salary: String? = null,
)

@Serializable
data class UserUpdateRequest(
    val phone: String? = null,
    val password: String? = null,
    @SerialName("full_name") val fullName: String? = null,
    val role: String? = null,
    @SerialName("is_active") val isActive: Boolean? = null,
    @SerialName("is_member") val isMember: Boolean? = null,
    @SerialName("vehicle_type") val vehicleType: String? = null,
    @SerialName("billing_mode") val billingMode: String? = null,
    @Serializable(with = com.tapmoay.sorders.data.remote.dto.NullableFlexibleStringSerializer::class) val salary: String? = null,
)

interface OrderApi {
    @GET("orders")
    suspend fun listOrders(
        @Query("status") status: String? = null,
        @Query("q") q: String? = null,
        @Query("shipper_id") shipperId: Long? = null,
        @Query("temp_shipper_name") tempShipperName: String? = null,
        @Query("date_from") dateFrom: String? = null,
        @Query("date_to") dateTo: String? = null,
    ): List<OrderDto>

    @GET("orders/pending-dispatch-count")
    suspend fun pendingDispatchCount(): JsonObject

    @GET("orders/{orderId}")
    suspend fun getOrder(@Path("orderId") orderId: Long): OrderDto

    @POST("orders")
    suspend fun createOrder(@Body body: OrderCreateRequest): OrderDto

    @PATCH("orders/{orderId}")
    suspend fun updateOrder(@Path("orderId") orderId: Long, @Body body: OrderUpdateRequest): OrderDto

    @DELETE("orders/{orderId}")
    suspend fun deleteOrder(@Path("orderId") orderId: Long)

    @POST("orders/batch-assign")
    suspend fun batchAssign(@Body body: OrderBatchAssignRequest): OrderBatchAssignOut

    @POST("orders/{orderId}/assign")
    suspend fun assignOrder(@Path("orderId") orderId: Long, @Body body: OrderAssignRequest): OrderDto

    @POST("orders/{orderId}/freight")
    suspend fun updateFreight(@Path("orderId") orderId: Long, @Body body: FreightUpdateRequest): OrderDto

    @POST("orders/{orderId}/split")
    suspend fun splitOrder(@Path("orderId") orderId: Long, @Body body: OrderSplitRequest): List<OrderDto>

    @POST("orders/{orderId}/cancel")
    suspend fun cancelOrder(@Path("orderId") orderId: Long): OrderDto

    @POST("orders/{orderId}/pay")
    suspend fun payOrder(@Path("orderId") orderId: Long): OrderDto

    @POST("orders/{orderId}/charge")
    suspend fun chargeOrder(@Path("orderId") orderId: Long, @Body body: OrderChargeBody): OrderDto

    @POST("orders/{orderId}/recall")
    suspend fun recallOrder(@Path("orderId") orderId: Long, @Body body: OrderRecallBody): OrderDto

    @POST("orders/{orderId}/exception")
    suspend fun markException(@Path("orderId") orderId: Long, @Body body: OrderExceptionBody): OrderDto

    @POST("orders/{orderId}/driver-ack")
    suspend fun driverAck(@Path("orderId") orderId: Long): OrderDto

    @POST("orders/{orderId}/driver-note")
    suspend fun driverNote(@Path("orderId") orderId: Long, @Body body: DriverNoteBody): OrderDto

    @Multipart
    @POST("orders/{orderId}/address-image")
    suspend fun uploadOrderAddressImage(
        @Path("orderId") orderId: Long,
        @Part file: MultipartBody.Part,
    ): OrderDto

    @Multipart
    @POST("orders/{orderId}/delivery-photos")
    suspend fun uploadDeliveryPhotos(
        @Path("orderId") orderId: Long,
        @Part files: List<@JvmSuppressWildcards MultipartBody.Part>,
    ): DeliveryPhotoUploadOut

    @POST("orders/{orderId}/complete")
    suspend fun completeOrder(@Path("orderId") orderId: Long, @Body body: OrderCompleteBody): OrderDto

    @Multipart
    @POST("orders/{orderId}/complete-with-upload")
    suspend fun completeOrderWithUpload(
        @Path("orderId") orderId: Long,
        @Part files: List<@JvmSuppressWildcards MultipartBody.Part>,
        @Part("driver_remark") driverRemark: RequestBody,
        @Part("payment") payment: RequestBody,
        @Part("damage_items") damageItems: RequestBody,
        @Part("damage_note") damageNote: RequestBody,
    ): OrderDto
}

interface ShipperApi {
    @GET("shipper/addresses")
    suspend fun listAddresses(): List<AddressDto>

    @POST("shipper/addresses")
    suspend fun createAddress(@Body body: AddressCreateRequest): AddressDto

    @PATCH("shipper/addresses/{addressId}")
    suspend fun updateAddress(@Path("addressId") addressId: Long, @Body body: AddressCreateRequest): AddressDto

    @DELETE("shipper/addresses/{addressId}")
    suspend fun deleteAddress(@Path("addressId") addressId: Long)

    @POST("shipper/addresses/{addressId}/set-default")
    suspend fun setDefaultAddress(@Path("addressId") addressId: Long): AddressDto

    @GET("shipper/contacts")
    suspend fun listContacts(): List<ContactDto>

    @GET("shipper/locations")
    suspend fun listLocations(): List<LocationDto>

    @Multipart
    @POST("shipper/locations/image")
    suspend fun uploadLocationImage(@Part file: MultipartBody.Part): LocationImageOut

    @POST("shipper/locations")
    suspend fun createLocation(@Body body: LocationCreateRequest): LocationDto

    @PATCH("shipper/locations/{locationId}")
    suspend fun updateLocation(@Path("locationId") locationId: Long, @Body body: LocationCreateRequest): LocationDto

    @DELETE("shipper/locations/{locationId}")
    suspend fun deleteLocation(@Path("locationId") locationId: Long)

    @POST("shipper/contacts")
    suspend fun createContact(@Body body: ContactCreateRequest): ContactDto

    @PATCH("shipper/contacts/{contactId}")
    suspend fun updateContact(@Path("contactId") contactId: Long, @Body body: ContactUpdateRequest): ContactDto

    @DELETE("shipper/contacts/{contactId}")
    suspend fun deleteContact(@Path("contactId") contactId: Long)
}

interface LedgerApi {
    @GET("ledger/accounts")
    suspend fun accounts(
        @Query("date_from") dateFrom: String? = null,
        @Query("date_to") dateTo: String? = null,
        @Query("kind") kind: String = "shipper",
    ): List<LedgerAccountOut>

    @GET("ledger/entries")
    suspend fun listEntries(
        @Query("shipper_id") shipperId: Long? = null,
        @Query("temp_shipper_name") tempShipperName: String? = null,
        @Query("date_from") dateFrom: String? = null,
        @Query("date_to") dateTo: String? = null,
    ): List<LedgerEntryDto>

    @POST("ledger/entries")
    suspend fun createEntry(@Body body: LedgerCreateRequest): LedgerEntryDto

    @GET("ledger/entries/{entryId}")
    suspend fun getEntry(@Path("entryId") entryId: Long): LedgerEntryDto

    @PATCH("ledger/entries/{entryId}")
    suspend fun updateEntry(@Path("entryId") entryId: Long, @Body body: LedgerUpdateRequest): LedgerEntryDto

    @DELETE("ledger/entries/{entryId}")
    suspend fun deleteEntry(@Path("entryId") entryId: Long)

    @POST("ledger/sync-from-delivered-orders")
    suspend fun syncFromDelivered(@Body body: LedgerSyncBody): JsonObject

    @GET("ledger/temp-shipper-names")
    suspend fun listTempShipperNames(): List<String>
}

@Serializable
data class LedgerUpdateRequest(
    val note: String? = null,
    @SerialName("entry_date") val entryDate: String? = null,
    @SerialName("product_name") val productName: String? = null,
    val quantity: Int? = null,
    @Serializable(with = FlexibleStringSerializer::class) @SerialName("unit_price")
    val unitPrice: String? = null,
    @Serializable(with = FlexibleStringSerializer::class) val total: String? = null,
    @SerialName("order_id") val orderId: Long? = null,
    @SerialName("product_id") val productId: Long? = null,
)

@Serializable
data class LedgerSyncBody(
    @SerialName("shipper_id") val shipperId: Long? = null,
    @SerialName("temp_shipper_name") val tempShipperName: String? = null,
)

interface ProductApi {
    @GET("products")
    suspend fun listProducts(@Query("include_inactive") includeInactive: Boolean = true): List<ProductDto>

    @POST("products")
    suspend fun createProduct(@Body body: ProductCreateRequest): ProductDto

    @PATCH("products/{productId}")
    suspend fun updateProduct(@Path("productId") productId: Long, @Body body: ProductUpdateRequest): ProductDto

    @Multipart
    @POST("products/{productId}/image")
    suspend fun uploadProductImage(
        @Path("productId") productId: Long,
        @Part file: MultipartBody.Part,
    ): ProductDto

    @DELETE("products/{productId}")
    suspend fun deleteProduct(@Path("productId") productId: Long)
}

interface PriceRuleApi {
    @GET("price-rules")
    suspend fun listRules(): List<PriceRuleDto>

    @POST("price-rules")
    suspend fun createRule(@Body body: PriceRuleCreateRequest): PriceRuleDto

    @PATCH("price-rules/{ruleId}")
    suspend fun updateRule(@Path("ruleId") ruleId: Long, @Body body: PriceRuleUpdateRequest): PriceRuleDto

    @DELETE("price-rules/{ruleId}")
    suspend fun deleteRule(@Path("ruleId") ruleId: Long)

    @POST("price-rules/batch")
    suspend fun batchRules(@Body body: PriceRuleBatchRequest): PriceRuleBatchResult
}

@Serializable
data class PriceRuleBatchRequest(
    @SerialName("shipper_ids") val shipperIds: List<Long>,
    @SerialName("product_ids") val productIds: List<Long>,
    val mode: String,
    @Serializable(with = FlexibleStringSerializer::class) val value: String? = null,
    @SerialName("tier_index") val tierIndex: Int? = null,
)

@Serializable
data class PriceRuleBatchResult(
    val count: Int = 0,
)

@Serializable
data class PriceRuleDto(
    val id: Long = 0,
    @SerialName("shipper_id") val shipperId: Long = 0,
    @SerialName("product_id") val productId: Long = 0,
    @SerialName("special_unit_price") @Serializable(with = FlexibleStringSerializer::class)
    val specialUnitPrice: String = "0",
    @SerialName("shipper_name") val shipperName: String? = null,
    @SerialName("product_name") val productName: String? = null,
)

@Serializable
data class PriceRuleCreateRequest(
    @SerialName("shipper_id") val shipperId: Long,
    @SerialName("product_id") val productId: Long,
    @SerialName("special_unit_price") @Serializable(with = FlexibleStringSerializer::class)
    val specialUnitPrice: String,
)

@Serializable
data class PriceRuleUpdateRequest(
    @SerialName("special_unit_price") @Serializable(with = FlexibleStringSerializer::class)
    val specialUnitPrice: String? = null,
)

@Serializable
data class ProductCreateRequest(
    val name: String,
    @SerialName("default_unit_price") @Serializable(with = FlexibleStringSerializer::class)
    val defaultUnitPrice: String = "0",
    @SerialName("cost_price") @Serializable(with = FlexibleStringSerializer::class)
    val costPrice: String = "0",
    @SerialName("image_url") val imageUrl: String? = null,
    @SerialName("name_color") val nameColor: String? = null,
    @SerialName("tier_prices") val tierPrices: List<ProductTierDto> = emptyList(),
    val stock: Int? = null,
    val unit: String? = null,
    @SerialName("low_stock_alert") val lowStockAlert: Int? = null,
)

@Serializable
data class ProductUpdateRequest(
    val name: String? = null,
    @SerialName("default_unit_price") @Serializable(with = FlexibleStringSerializer::class)
    val defaultUnitPrice: String? = null,
    @SerialName("cost_price") @Serializable(with = FlexibleStringSerializer::class)
    val costPrice: String? = null,
    @SerialName("is_active") val isActive: Boolean? = null,
    @SerialName("image_url") val imageUrl: String? = null,
    @SerialName("name_color") val nameColor: String? = null,
    @SerialName("tier_prices") val tierPrices: List<ProductTierDto>? = null,
    val unit: String? = null,
    @SerialName("low_stock_alert") val lowStockAlert: Int? = null,
)

interface ArrearsApi {
    @GET("arrears-units")
    suspend fun listUnits(): List<ArrearsUnitDto>

    @POST("arrears-units")
    suspend fun createUnit(@Body body: ArrearsUnitCreateRequest): ArrearsUnitDto

    @PATCH("arrears-units/{unitId}")
    suspend fun updateUnit(@Path("unitId") unitId: Long, @Body body: ArrearsUnitUpdateRequest): ArrearsUnitDto

    @DELETE("arrears-units/{unitId}")
    suspend fun deleteUnit(@Path("unitId") unitId: Long)
}

interface InventoryApi {
    @GET("inventory/movements")
    suspend fun listMovements(
        @Query("product_id") productId: Long? = null,
        @Query("limit") limit: Int = 100,
        @Query("offset") offset: Int = 0,
        @Query("date_from") dateFrom: String? = null,
        @Query("date_to") dateTo: String? = null,
    ): List<InventoryMovementDto>

    @POST("inventory/movements")
    suspend fun createMovement(@Body body: InventoryMovementCreateRequest): InventoryMovementDto

    @GET("inventory/summary")
    suspend fun summary(): List<InventorySummaryItemDto>
}

interface NotificationApi {
    @GET("notifications")
    suspend fun listNotifications(@Query("limit") limit: Int = 50): List<NotificationDto>

    @GET("notifications/unread-count")
    suspend fun unreadCount(): UnreadCountDto

    @POST("notifications")
    suspend fun create(@Body body: NotificationCreateRequest): NotificationDto

    @POST("notifications/read-all")
    suspend fun readAll(): JsonObject

    @PATCH("notifications/{notificationId}")
    suspend fun update(@Path("notificationId") notificationId: Long, @Body body: Map<String, String>): NotificationDto

    @POST("notifications/{notificationId}/read")
    suspend fun markRead(@Path("notificationId") notificationId: Long): NotificationDto

    @DELETE("notifications/{notificationId}")
    suspend fun delete(@Path("notificationId") notificationId: Long)
}
interface FreightTemplateApi {
    @GET("freight-templates")
    suspend fun listTemplates(@Query("vehicle_type") vehicleType: String? = null): List<FreightTemplateDto>

    @POST("freight-templates")
    suspend fun createTemplate(@Body body: FreightTemplateRequest): FreightTemplateDto

    @PUT("freight-templates/{templateId}")
    suspend fun updateTemplate(@Path("templateId") templateId: Long, @Body body: FreightTemplateRequest): FreightTemplateDto

    @DELETE("freight-templates/{templateId}")
    suspend fun deleteTemplate(@Path("templateId") templateId: Long)
}

interface ReportApi {
    @GET("reports/turnover")
    suspend fun turnover(@Query("mode") mode: String, @Query("date") date: String): TurnoverReportDto

    @GET("reports/products")
    suspend fun products(@Query("mode") mode: String, @Query("date") date: String): ProductReportDto

    @GET("stats/driver-performance")
    suspend fun driverPerformance(
        @Query("date_from") dateFrom: String,
        @Query("date_to") dateTo: String,
        @Query("interval") interval: String = "day",
    ): DriverPerformanceDto

    @GET("stats/exception-orders")
    suspend fun exceptionOrders(@Query("date_from") dateFrom: String, @Query("date_to") dateTo: String): List<ExceptionOrderDto>

    @POST("stats/exception-orders/{orderId}/resolve")
    suspend fun resolveException(@Path("orderId") orderId: Long, @Body body: ExceptionResolveRequest): ExceptionResolveResult

    @GET("operation-logs")
    suspend fun operationLogs(@Query("limit") limit: Int = 60): List<OperationLogDto>
}

interface FreightSettlementApi {
    @GET("freight-settlement")
    suspend fun settlement(@Query("month") month: String): FreightSettlementDto

    @GET("freight-settlement")
    suspend fun settlementRange(@Query("from") from: String, @Query("to") to: String): FreightSettlementDto

}

interface AccountingApi {
    @GET("customers")
    suspend fun listCustomers(
        @Query("kind") kind: String? = null,
        @Query("q") q: String? = null,
    ): List<CustomerDto>

    @POST("customers")
    suspend fun createCustomer(@Body body: CustomerCreateRequest): CustomerDto

    @GET("driver-bills")
    suspend fun listDriverBills(
        @Query("driver_id") driverId: Long? = null,
        @Query("month") month: String? = null,
        @Query("status") status: String? = null,
    ): List<DriverBillDto>

    @POST("driver-bills/generate")
    suspend fun generateBills(@Body body: DriverBillGenerateRequest): List<DriverBillDto>

    @GET("driver-settlements")
    suspend fun listSettlements(
        @Query("driver_id") driverId: Long? = null,
        @Query("month") month: String? = null,
        @Query("status") status: String? = null,
    ): List<SettlementDto>

    @POST("driver-settlements")
    suspend fun createSettlement(@Body body: SettlementCreateRequest): SettlementDto

    @PATCH("driver-settlements/{id}")
    suspend fun settlementAction(@Path("id") id: Long, @Body body: SettlementActionRequest): SettlementDto

    @GET("expenses")
    suspend fun listExpenses(
        @Query("category") category: String? = null,
        @Query("driver_id") driverId: Long? = null,
        @Query("date_from") dateFrom: String? = null,
        @Query("date_to") dateTo: String? = null,
    ): List<ExpenseDto>

    @POST("expenses")
    suspend fun createExpense(@Body body: ExpenseCreateRequest): ExpenseDto

    @GET("cash-flows")
    suspend fun listCashFlows(
        @Query("direction") direction: String? = null,
        @Query("biz_type") bizType: String? = null,
        @Query("date_from") dateFrom: String? = null,
        @Query("date_to") dateTo: String? = null,
    ): List<CashFlowDto>

    @GET("vehicles")
    suspend fun listVehicles(): List<VehicleDto>

    @POST("vehicles")
    suspend fun createVehicle(@Body body: VehicleCreateRequest): VehicleDto

    @GET("ledger/receipts")
    suspend fun listReceipts(
        @Query("customer_id") customerId: Long? = null,
    ): List<ReceiptDto>

    @POST("ledger/receipts")
    suspend fun createReceipt(@Body body: ReceiptCreateRequest): ReceiptDto
}