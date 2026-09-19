package com.tapmoay.sorders.data.remote.api

import com.tapmoay.sorders.data.remote.dto.*
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import okhttp3.MultipartBody
import okhttp3.RequestBody
import retrofit2.http.*

interface AuthApi {
    @POST("auth/login")
    suspend fun login(@Body body: LoginRequest): TokenDto
}

/**
 * 文件：把用户从手机里选的表格读成文本（AI 助手的「挂载文件」入口）。
 *
 * ### 为什么解析在服务端
 * 真实的 Excel 比看上去脏：日期是序列号、公式只有缓存值、中文 CSV 是 GBK……
 * 服务端有 openpyxl（报表导出一直在用），手机端自己写一个 xlsx 解析器既贵又测不了。
 * 手机只负责选文件、上传、把结果摆给用户看。
 *
 * **服务器不保存这个文件**：读一遍就还回来，不落盘、不进库。
 */
interface FileApi {
    /**
     * 上传表格文件 → 拿到「一格一格」的文本表格。
     *
     * @param maxRows 每张表最多读几行（后端上限 1000）。默认 200：
     *   附件最终要塞进模型的上下文，读太多只会把窗口撑爆。
     */
    @Multipart
    @POST("files/parse-sheet")
    suspend fun parseSheet(
        @Part file: MultipartBody.Part,
        @Query("max_rows") maxRows: Int = 200,
    ): SheetParseDto
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

    /**
     * 单取一个账号（v3.27 为**撤回**补的）。
     *
     * ⚠️ 不能用 `GET /users/me` 顶替：那只返回**当前登录人自己**。
     * 而"读回这条记录写之前长什么样"要读的是**被改的那一个账号**。
     * 也不能靠 `GET /users?q=` 去搜：那是模糊匹配，搜不到就是静默地没有撤回。
     */
    @GET("users/{userId}")
    suspend fun getUser(@Path("userId") userId: Long): UserDto

    @PATCH("users/{userId}")
    suspend fun updateUser(@Path("userId") userId: Long, @Body body: UserUpdateRequest): UserDto

    @POST("users/{userId}/swap-shipper-driver")
    suspend fun swapRole(@Path("userId") userId: Long): UserDto
    @DELETE("users/{userId}")
    suspend fun deleteUser(@Path("userId") userId: Long)

    /** 撤回：把软删的账号恢复回来（手机号会去掉 _del 后缀，冲突时保留现号）。 */
    @POST("users/{userId}/restore")
    suspend fun restoreUser(@Path("userId") userId: Long): UserDto

    /**
     * 只读：按姓名/手机号模糊搜索用户（后端 `q` 参数）。
     * 供 AI 工具 `search_shipper` 使用；不传 role，由调用方按 role 过滤（保证既能搜货主也能搜批发商）。
     */
    @GET("users")
    suspend fun searchUsers(
        @Query("q") q: String,
        @Query("limit") limit: Int = 50,
    ): List<UserDto>
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
        /**
         * 只看**回收站**（隔离区）里的订单——仅派单员。
         *
         * 为什么要这个参数：软删掉的单在普通列表里查不到，而"把删掉的单恢复回来"
         * 恰恰要先找到它。没有它，恢复功能就只能靠用户报编号，而 AI 拿不到编号。
         */
        @Query("deleted_only") deletedOnly: Boolean? = null,
    ): List<OrderDto>

    /** 把订单从回收站恢复（仅派单员；订单必须在隔离区里）。 */
    @POST("orders/{orderId}/restore")
    suspend fun restoreOrder(@Path("orderId") orderId: Long): OrderDto

    // ---- 订单商品行（派单员修正订单明细用；订单受状态门限制）----

    @GET("order-products")
    suspend fun listOrderProducts(@Query("order_id") orderId: Long): List<OrderProductRow>

    /**
     * 单取一行商品行（v3.27 为**撤回**补的）。
     *
     * 为什么必须有：删除一行商品的 payload 里只有 `line_id`，而"把它加回来"需要
     * 这一行的商品名/数量/单价**以及它属于哪张单**——列表端点是按 `order_id` 查的，
     * 手里没有 order_id 就查不动。
     */
    @GET("order-products/{lineId}")
    suspend fun getOrderProduct(@Path("lineId") lineId: Long): OrderProductRow

    @POST("order-products")
    suspend fun createOrderProduct(@Body body: OrderProductCreateRequest): OrderProductRow

    @PATCH("order-products/{lineId}")
    suspend fun updateOrderProduct(@Path("lineId") lineId: Long, @Body body: OrderProductUpdateRequest): OrderProductRow

    @DELETE("order-products/{lineId}")
    suspend fun deleteOrderProduct(@Path("lineId") lineId: Long)

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

    // ⚠️ 必须是 PATCH。后端是 `@router.patch("/{order_id}/exception")`，
    // 这里原先写成了 @POST —— 结果是派单员在「订单管理 → 标记异常」点一次、405 一次，
    // 而且错误信息只会显示成一句笼统的失败，没人会想到是动词写错了。
    // 2026-09-15 核对端点索引时发现（`docs/PROJECT_MAP/08A_ENDPOINT_INDEX.md` 写的是 PATCH）。
    @PATCH("orders/{orderId}/exception")
    suspend fun markException(@Path("orderId") orderId: Long, @Body body: OrderExceptionBody): OrderDto

    @POST("orders/{orderId}/driver-ack")
    suspend fun driverAck(@Path("orderId") orderId: Long): OrderDto

    @POST("orders/{orderId}/driver-note")
    suspend fun driverNote(@Path("orderId") orderId: Long, @Body body: DriverNoteBody): OrderDto

    /**
     * 司机到场补导航信息（订单原本没有坐标时才能补）。
     *
     * 后端会把坐标一次性写三处：**这一单**、**货主自己的地点库**、**全库共享地点库**。
     * 已有坐标的订单会被 400 拒绝 —— 司机到的地方不一定是收货点，
     * 覆盖掉一个货主确认过的坐标 = 把"有坐标"变成"有错坐标"，而错坐标更危险。
     */
    @POST("orders/{orderId}/navigation")
    suspend fun fillNavigation(@Path("orderId") orderId: Long, @Body body: OrderNavigationBody): OrderDto

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

    /**
     * 单取一条地址（v3.27 为**撤回**补的：撤回要知道这条记录写之前长什么样）。
     *
     * ⚠️ 后端一直有这个端点（`GET /shipper/addresses/{id}`），只是 Android 侧没接。
     * 明明能单取却拉整张表是"能用但浪费"，而漏了它就会退化成"读不到 = 撤不回来"。
     */
    @GET("shipper/addresses/{addressId}")
    suspend fun getAddress(@Path("addressId") addressId: Long): AddressDto

    @POST("shipper/addresses")
    suspend fun createAddress(@Body body: AddressCreateRequest): AddressDto

    @PATCH("shipper/addresses/{addressId}")
    suspend fun updateAddress(@Path("addressId") addressId: Long, @Body body: AddressCreateRequest): AddressDto

    @DELETE("shipper/addresses/{addressId}")
    suspend fun deleteAddress(@Path("addressId") addressId: Long)

    @POST("shipper/addresses/{addressId}/set-default")
    suspend fun setDefaultAddress(@Path("addressId") addressId: Long): AddressDto

    /** 撤回：把软删的地址恢复回来（DELETE 的逆操作，v3.26）。 */
    @POST("shipper/addresses/{addressId}/restore")
    suspend fun restoreAddress(@Path("addressId") addressId: Long): AddressDto

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

    @POST("shipper/locations/{locationId}/restore")
    suspend fun restoreLocation(@Path("locationId") locationId: Long): LocationDto

    @POST("shipper/contacts")
    suspend fun createContact(@Body body: ContactCreateRequest): ContactDto

    @PATCH("shipper/contacts/{contactId}")
    suspend fun updateContact(@Path("contactId") contactId: Long, @Body body: ContactUpdateRequest): ContactDto

    @DELETE("shipper/contacts/{contactId}")
    suspend fun deleteContact(@Path("contactId") contactId: Long)

    @POST("shipper/contacts/{contactId}/restore")
    suspend fun restoreContact(@Path("contactId") contactId: Long): ContactDto
}

/**
 * 共享地点库（导航信息）。
 *
 * ⚠️ 这张表**不按人分区**：司机到场补录的坐标、别人标过的点，三种角色都查得到。
 * 这正是用户 2026-09-18 要的「共同的库，相同位置直接拉过来，省的每个人都要手动上传一次」。
 */
interface PlaceApi {
    @GET("places")
    suspend fun listPlaces(
        @Query("q") q: String? = null,
        @Query("limit") limit: Int = 100,
    ): List<PlaceDto>

    @POST("places")
    suspend fun createPlace(@Body body: PlaceCreateRequest): PlaceDto

    /**
     * 记一次「我用了这个共享地点」。**同一个人用到第 2 次**会自动把它收进我自己的地点库，
     * 返回值里的 `auto_added` 就是"这一次刚加的"——界面要据此说一句，不能不吭声。
     */
    @POST("places/{placeId}/use")
    suspend fun usePlace(@Path("placeId") placeId: Long): PlaceUseOut
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

    /**
     * 商品分类名册（按显示顺序）。
     * 下单页要用它排左侧那一列 —— 所以**三种角色都能读**（后端就是 `CurrentUser`）。
     */
    @GET("product-categories")
    suspend fun listCategories(): List<ProductCategoryDto>

    @POST("product-categories")
    suspend fun createCategory(@Body body: ProductCategoryCreateRequest): ProductCategoryDto

    @PATCH("product-categories/{categoryId}")
    suspend fun updateCategory(
        @Path("categoryId") categoryId: Long,
        @Body body: ProductCategoryUpdateRequest,
    ): ProductCategoryDto

    @DELETE("product-categories/{categoryId}")
    suspend fun deleteCategory(@Path("categoryId") categoryId: Long)

    /** 整份顺序一次提交（`ids[0]` 排最前）。只传一部分后端会 400。 */
    @POST("product-categories/reorder")
    suspend fun reorderCategories(@Body body: ProductCategoryReorderRequest): List<ProductCategoryDto>

    /** 某个货主/批发商的商品可见范围（白名单）。 */
    @GET("users/{userId}/product-visibility")
    suspend fun getProductVisibility(@Path("userId") userId: Long): ProductVisibilityDto

    @PUT("users/{userId}/product-visibility")
    suspend fun setProductVisibility(
        @Path("userId") userId: Long,
        @Body body: ProductVisibilityRequest,
    ): ProductVisibilityDto

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

    @POST("products/{productId}/restore")
    suspend fun restoreProduct(@Path("productId") productId: Long): ProductDto

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
    /** fixed=统一单价 / tier=第N档批发价 / percent=默认价的百分比 / **adjust=在现有价上±百分比**。 */
    val mode: String,
    @Serializable(with = FlexibleStringSerializer::class) val value: String? = null,
    @SerialName("tier_index") val tierIndex: Int? = null,
    /**
     * adjust 模式的涨/降百分比：`+10` = 涨 10%，`-15` = 降 15%。
     *
     * ⚠️ 它和 [value] 的 `percent` 模式**不是一回事**：
     * `percent` 算的是「商品默认价 × value/100」（设定一个值），
     * `adjust` 算的是「**当前生效价** × (1 + adjust_percent/100)」（相对调整）。
     * 对一个已经单独谈过价的批发商，用默认价算出来的数字**看着也合理**——
     * 所以这两种模式搞混了不会报任何错，只会静默算错钱。
     */
    @SerialName("adjust_percent")
    @Serializable(with = NullableFlexibleStringSerializer::class)
    val adjustPercent: String? = null,
)

@Serializable
data class PriceRuleBatchChangeDto(
    @SerialName("shipper_name") val shipperName: String = "",
    @SerialName("product_name") val productName: String = "",
    /** null = 之前没有专属价（按通用价买）。 */
    @Serializable(with = NullableFlexibleStringSerializer::class) val before: String? = null,
    @Serializable(with = FlexibleStringSerializer::class) val after: String = "0",
)

@Serializable
data class PriceRuleBatchResult(
    val count: Int = 0,
    /** 因为"算不出价"而被跳过的组合数（如 tier 模式但商品没配档位）。 */
    val skipped: Int = 0,
    /** 前后值明细（后端截前 200 条）。 */
    val changes: List<PriceRuleBatchChangeDto> = emptyList(),
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
    /** 商品分类（选品页左侧分组用）；空 = 未分类。 */
    val category: String? = null,
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
    /** 传空串 = 清成"未分类"；传 null = 不改（PATCH 部分更新语义）。 */
    val category: String? = null,
    @SerialName("low_stock_alert") val lowStockAlert: Int? = null,
)

interface ArrearsApi {
    @GET("arrears-units")
    suspend fun listUnits(): List<ArrearsUnitDto>

    @POST("arrears-units")
    suspend fun createUnit(@Body body: ArrearsUnitCreateRequest): ArrearsUnitDto

    @PATCH("arrears-units/{unitId}")
    suspend fun updateUnit(@Path("unitId") unitId: Long, @Body body: ArrearsUnitUpdateRequest): ArrearsUnitDto

    @POST("arrears-units/{unitId}/restore")
    suspend fun restoreArrearsUnit(@Path("unitId") unitId: Long): ArrearsUnitDto

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

    /** 只读：只要「库存已达报警阈值」的商品（后端 `below_alert=true`）。供 AI 工具 `inventory_alerts` 使用。 */
    @GET("inventory/summary")
    suspend fun summaryBelowAlert(@Query("below_alert") belowAlert: Boolean = true): List<InventorySummaryItemDto>
}

interface NotificationApi {
    /**
     * 消息列表。
     *
     * ⚠️ 没带 `recipient_id` 时后端返回的是**自己**的消息（不是"全部人的"）——
     * 这条口径 2026-09-17 才修对：以前派单员不带这个参数会拿到**所有人的消息**，
     * 于是「清空」清的是自己的、列表里却还有别人的，重启后"消息又回来了"。
     * 要看某个账户的消息，显式传 [recipientId]。
     *
     * ⚠️ `limit` **后端不认**（硬 `.limit(200)`），传什么都一样。
     */
    @GET("notifications")
    suspend fun listNotifications(
        @Query("limit") limit: Int = 50,
        /** 只看发给谁的。null = 自己（后端语义），非 null 时派单员可以看别人的。 */
        @Query("recipient_id") recipientId: Long? = null,
    ): List<NotificationDto>

    @GET("notifications/unread-count")
    suspend fun unreadCount(): UnreadCountDto

    /**
     * 单取一条消息（v3.27 为**撤回**补的）。
     *
     * 为什么不能靠列表："改消息"撤回时要知道它**改之前**的标题和正文，
     * 而列表默认只回最近 50 条（后端硬上限 200）——要改的那条大概率不在里面，
     * 于是撤回会静默地没有入口。
     */
    @GET("notifications/{notificationId}")
    suspend fun getNotification(@Path("notificationId") notificationId: Long): NotificationDto

    @POST("notifications")
    suspend fun create(@Body body: NotificationCreateRequest): NotificationDto

    @POST("notifications/read-all")
    suspend fun readAll(): JsonObject

    @POST("notifications/price-notify")
    suspend fun priceNotify(@Body body: PriceChangeNotifyRequest): List<NotificationDto>

    @POST("notifications/batch-delete")
    suspend fun batchDelete(@Body body: NotificationBatchDeleteRequest): BatchDeleteResultDto

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

    @POST("freight-templates/{templateId}/restore")
    suspend fun restoreFreightTemplate(@Path("templateId") templateId: Long): FreightTemplateDto

    @DELETE("freight-templates/{templateId}")
    suspend fun deleteTemplate(@Path("templateId") templateId: Long)
}

/**
 * 司机计费规则模板（派单员）：一份规则挂到司机身上，决定他怎么算钱。
 *
 * ### 后端的 400/409 是**中文原因**，必须原样给用户看
 * 例：`"还有 3 个司机挂着这份规则，先给他们换掉或解挂再删"`、
 * `"填了提成比例，就要选提成基数（按运费还是按商品金额）——否则这份规则一分钱都算不出来"`。
 * `ApiClient.toApiException` 会把 `detail` 抠进 `ApiException.message`（`core/ApiClient.kt:117-132`），
 * 界面把它原样显示即可 —— 改写成"删除失败""保存失败"等于把用户能照着改的那句话扔了。
 *
 * ### 挂载**不在**这里
 * 把规则挂给司机走 `POST /driver-billing-rules/attach`（后端注释说明：写路径只许有一条），
 * 入口在司机编辑页，不在这张规则管理页上。
 */
interface DriverBillingRuleApi {
    /** `deletedOnly = true` = 回收站（删错了要能看见并恢复）。 */
    @GET("driver-billing-rules")
    suspend fun listRules(
        @Query("vehicle_type") vehicleType: String? = null,
        @Query("deleted_only") deletedOnly: Boolean = false,
    ): List<DriverBillingRuleDto>

    @POST("driver-billing-rules")
    suspend fun createRule(@Body body: DriverBillingRuleRequest): DriverBillingRuleDto

    @PUT("driver-billing-rules/{ruleId}")
    suspend fun updateRule(@Path("ruleId") ruleId: Long, @Body body: DriverBillingRuleRequest): DriverBillingRuleDto

    @DELETE("driver-billing-rules/{ruleId}")
    suspend fun deleteRule(@Path("ruleId") ruleId: Long)

    @POST("driver-billing-rules/{ruleId}/restore")
    suspend fun restoreRule(@Path("ruleId") ruleId: Long): DriverBillingRuleDto

    /**
     * 把规则挂给司机；`rule_id = null` = 解挂。
     *
     * ⚠️ 出参写成 [JsonElement] 而不是 `DriverBillingRuleDto?`：解挂时后端返回的是
     * **JSON `null`**（`response_model=DriverBillingRuleOut | None`），而本仓库没有任何
     * "可空 DTO 出参"的先例，`JsonNull` 是能接住它的那一层（同 `Apis.kt` 里
     * `stats.shipperPerformance` / `rawApi.get` 用 JsonElement 接住未冻结形状的做法）。
     * 转成 DTO 的动作放在仓库层（`AppRepository.attachDriverRule`）。
     */
    @POST("driver-billing-rules/attach")
    suspend fun attachRule(@Body body: DriverBillingRuleAttachRequest): JsonElement
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

    @GET("reports/export")
    suspend fun exportReport(
        @Query("kind") kind: String,
        @Query("mode") mode: String,
        @Query("date") date: String,
        @Query("date_from") dateFrom: String? = null,
        @Query("date_to") dateTo: String? = null,
    ): okhttp3.ResponseBody

    @GET("reports/arrears-summary")
    suspend fun arrearsSummary(
        @Query("date_from") dateFrom: String,
        @Query("date_to") dateTo: String,
    ): List<ReportArrearsUnitDto>

    /**
     * 只读：货主下单量与金额排行（列名/字段名由后端新增端点决定）。
     *
     * 返回 [JsonElement] 而不是强类型 DTO，是**刻意的**：该端点由另一个人同步在后端新增，
     * 出参形状（对象包 shippers / items / 还是裸数组）尚未冻结。用 JsonElement 接住，
     * 由 [com.tapmoay.sorders.ai.AiTools] 宽松解析，后端改形状也不会让 App 编译/运行出错。
     * 端点不存在时返回 404，由工具层转成「该能力暂不可用」。
     */
    @GET("stats/shipper-performance")
    suspend fun shipperPerformance(
        @Query("date_from") dateFrom: String,
        @Query("date_to") dateTo: String,
    ): JsonElement
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

    /**
     * 新增一条支出。
     *
     * @param idempotencyKey 幂等键（**目前只有 AI 写操作会传**）。OkHttp 默认
     *   `retryOnConnectionFailure=true`，POST 在连接断开时会自动重发一次——
     *   没有这个键，重发就会变成两笔支出。后端暂未实现，但多带一个自定义头对
     *   FastAPI/nginx 无害，等后端支持时客户端不用再改。传 null 则不发这个头。
     */
    @POST("expenses")
    suspend fun createExpense(
        @Body body: ExpenseCreateRequest,
        @Header("Idempotency-Key") idempotencyKey: String? = null,
    ): ExpenseDto

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

    @PATCH("vehicles/{vehicleId}")
    suspend fun updateVehicle(
        @Path("vehicleId") vehicleId: Long,
        @Body body: VehicleUpdateRequest,
    ): VehicleDto

    /**
     * 绑司机 / 解绑（v3.44）。
     *
     * 为什么要单独一条而不是复用 `PATCH`：本项目的 `Json { explicitNulls = false }`
     * 会把 `Long? = null` **整个键丢掉** —— 客户端**发不出**"显式 null"。
     * 这条接口的契约是"`driver_id` 缺省或 null 都 = 解绑"，
     * 于是"把车从张三名下拿掉"终于有了表达方式（和 `driver-billing-rules/attach` 同形）。
     */
    @POST("vehicles/{vehicleId}/driver")
    suspend fun setVehicleDriver(
        @Path("vehicleId") vehicleId: Long,
        @Body body: VehicleDriverSetRequest,
    ): VehicleDto

    @GET("ledger/receipts")
    suspend fun listReceipts(
        @Query("customer_id") customerId: Long? = null,
    ): List<ReceiptDto>

    @POST("ledger/receipts")
    suspend fun createReceipt(@Body body: ReceiptCreateRequest): ReceiptDto
}

/** 系统：版本更新检测 */
interface SystemApi {
    @GET("system/app-version")
    suspend fun appVersion(): AppVersionDto
}

/**
 * 动态 GET —— **只给 AI 的通用读工具用**。
 *
 * 为什么需要它：AI 要能读"所有列表"（36 个只读端点），逐个写 Retrofit 方法既冗长又必然漏。
 * 但**路径不是模型自由填的**：模型只能在 `AiReadCatalog`（由 `_gen_ai_read_catalog.py` 从后端 AST
 * 生成的 36 条白名单）里选 `模块.动作`，路径由 App 侧查表拼出，查询参数还要过一次白名单。
 * 也就是说，这个"动态"的上限是**编译期就定死的 36 条**，不是任意 URL。
 *
 * 复用同一个 Retrofit 实例 = 复用登录 token 与统一异常转换，所以 AI **没有特权**：
 * 它在后端走的就是登录用户自己的那套 RBAC（和用户在 App 里点页面完全一样）。
 */
interface RawApi {
    @GET
    suspend fun get(@Url path: String, @QueryMap params: Map<String, String>): JsonElement
}