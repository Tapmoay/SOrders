package com.tapmoay.sorders.data.remote.api

import com.tapmoay.sorders.data.remote.dto.*
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import okhttp3.MultipartBody
import okhttp3.RequestBody
import retrofit2.Response
import retrofit2.http.*

interface AuthApi {
    @POST("auth/login")
    suspend fun login(@Body body: LoginRequest): TokenDto

    /**
     * 登出：让**服务端**把这个账号已发出的令牌全部作废（`token_version` +1）。
     *
     * ⚠️ 2026-09-19 审计：原来客户端登出只清本机 DataStore，服务端不知道 ——
     * 被复制走的令牌照样能用满 24 小时。
     */
    @POST("auth/logout")
    suspend fun logout(): JsonObject
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

    /**
     * 账号列表（**一页**）。
     *
     * 返回 `Response<...>` 是为了**读响应头**：后端 `le=500`，账号超过 500 个时只回最近
     * 500 条并置 `X-Truncated: 1`（2026-09-19 补的头）。不读它 = 第 501 个账号在 App 里
     * **不存在**，而派单员的下一步动作正是"那就新建一个"（撞手机号唯一约束）。
     *
     * `q` 是**服务端**的姓名/手机号模糊搜索（后 4 位也命中）：名册页的搜索框走它，
     * 客户端过滤只能看见这一页（见 `AppRepository.usersPage` 的说明）。
     */
    @GET("users")
    suspend fun listUsers(
        @Query("role") role: String? = null,
        @Query("is_member") isMember: Boolean? = null,
        @Query("q") q: String? = null,
        @Query("skip") skip: Int = 0,
        @Query("limit") limit: Int = 100,
    ): Response<List<UserDto>>

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
         * 按**送达日**（业务当地日）筛 —— 账本页"选货主 → 选时间 → 这些单的账"用它。
         *
         * ⚠️ 与 `date_from/date_to`（按**下单时间**）是两件事，不能互相替代：
         *    账本流水按 `entry_date`（＝送达那天）开窗，用下单时间筛会让
         *    「8/31 下单、9/1 送达」的单从 9 月的列表里消失（而账上明明有它）。
         */
        @Query("delivered_from") deliveredFrom: String? = null,
        @Query("delivered_to") deliveredTo: String? = null,
        /**
         * 只看**回收站**（隔离区）里的订单——仅派单员。
         *
         * 为什么要这个参数：软删掉的单在普通列表里查不到，而"把删掉的单恢复回来"
         * 恰恰要先找到它。没有它，恢复功能就只能靠用户报编号，而 AI 拿不到编号。
         */
        @Query("deleted_only") deletedOnly: Boolean? = null,
        /**
         * 这一次最多要多少条（后端缺省 300、上限 5000）。
         *
         * 账本页要它：那页把"这些单的钱"加在一起当合计，300 条一页对批发商那种
         * 一天几十单的账号很快就不够 —— 不给这个参数，界面上就会把一页当全部。
         * **截断与否以响应头为准**（`pageMeta()`），不看"条数是否等于 limit"。
         */
        @Query("limit") limit: Int? = null,
        /**
         * 只看**运费待定价**的单（2026-09-21）：已经派出去了（有司机）但运费还是空的。
         *
         * 用户口径：「没有匹配到就没有计费、没有定价……这个订单就得派单员**手动去给他定价**」。
         * ⚠️ 它**不改异常标记**（那是人工标的业务异常，两件事混在一列就都看不清了）。
         */
        @Query("unpriced") unpriced: Boolean? = null,
    ): Response<List<OrderDto>>

    /**
     * 派单员**手动定价**（没匹配到价目的单）：写订单的运费 + 分类，
     * 并（可选）把这条路线 + 价目**沉淀**下来，下次同样的单自动带价。
     */
    @POST("orders/{orderId}/price-freight")
    suspend fun priceFreight(
        @Path("orderId") orderId: Long,
        @Body body: OrderFreightPriceRequest,
    ): OrderDto

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

    /**
     * **订单退货**（2026-09-20）。
     *
     * 一次调用动五样东西（行级已退数量 / 账本红冲 / 库存回补 / 可能退现 / 订单状态），
     * 全部在后端 `services/order_return.py` 一处。
     * ⚠️ **整单退货也是走这一条**（把每一行的数量填满），没有第二个"整单"端点 ——
     *    多一条路径就多一条能绕过「货损那几件不能退」的路。
     */
    @POST("orders/{orderId}/return")
    suspend fun returnOrder(
        @Path("orderId") orderId: Long,
        @Body body: OrderReturnBody,
    ): OrderReturnResultDto

    // ---------------------------------------------------------- 退货申请（2026-09-21）
    //
    // ⛔ 货主**没有**直接退货的接口：`returnOrder` 上面那条要 `order:return` 权限，只有派单员有。
    //    申请与执行分成两组接口、两组权限，正是这条流程的意义（见 `return_requests.py` 开头）。
    //    「货主能不能自己做这件事」的判据是**后端鉴权**，不是界面上有没有按钮。

    /** 货主提交退货申请（**只写申请单**：账本、库存、订单状态一个都不动）。 */
    @POST("return-requests")
    suspend fun applyReturnRequest(@Body body: ReturnRequestCreateBody): ReturnRequestDto

    /** 我在所有订单上的退货申请（打标记、看驳回理由、撤回都读它）。 */
    @GET("return-requests/mine")
    suspend fun myReturnRequests(
        @Query("order_id") orderId: Long? = null,
        @Query("status") status: String = "all",
        @Query("limit") limit: Int = 200,
    ): ReturnRequestListDto

    /** 货主撤回自己的申请（不是删除：记录留着，派单员看得到"他提过又撤了"）。 */
    @POST("return-requests/{requestId}/withdraw")
    suspend fun withdrawReturnRequest(@Path("requestId") requestId: Long): ReturnRequestDto

    /** 派单员的待办退货申请（默认只给待处理的那几张）。 */
    @GET("return-requests")
    suspend fun returnRequestTodo(
        @Query("status") status: String = "pending",
        @Query("order_id") orderId: Long? = null,
        @Query("limit") limit: Int = 200,
    ): ReturnRequestListDto

    /** 派单员驳回（必带理由）。 */
    @POST("return-requests/{requestId}/reject")
    suspend fun rejectReturnRequest(
        @Path("requestId") requestId: Long,
        @Body body: ReturnRequestRejectBody,
    ): ReturnRequestDto

    /** 派单员**照这张申请实际退货**：库存与账本在这一刻才变。 */
    @POST("return-requests/{requestId}/fulfill")
    suspend fun fulfillReturnRequest(@Path("requestId") requestId: Long): ReturnRequestFulfillDto

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

    /**
     * 地点分类名册（**按人分区**：读回来的是当前登录人自己那一份）。
     *
     * 与商品分类不同：商品分类是全店一份（派单员维护、所有人下单看到同一列），
     * 地点库是每个人自己那一份（货主和派单员都用这套接口，各自的库互不可见）。
     */
    @GET("place-categories")
    suspend fun listPlaceCategories(): List<PlaceCategoryDto>

    @POST("place-categories")
    suspend fun createPlaceCategory(@Body body: PlaceCategoryCreateRequest): PlaceCategoryDto

    @PATCH("place-categories/{categoryId}")
    suspend fun updatePlaceCategory(
        @Path("categoryId") categoryId: Long,
        @Body body: PlaceCategoryUpdateRequest,
    ): PlaceCategoryDto

    @DELETE("place-categories/{categoryId}")
    suspend fun deletePlaceCategory(@Path("categoryId") categoryId: Long)

    /** 整份顺序一次提交（`ids[0]` 排最前）。只传一部分后端会 400。 */
    @POST("place-categories/reorder")
    suspend fun reorderPlaceCategories(@Body body: PlaceCategoryReorderRequest): List<PlaceCategoryDto>

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
    /**
     * 共享地点（**一页**，按"用过多少次"倒序）。
     *
     * 返回 `Response<...>` 是为了**读响应头**（`X-Truncated` / `X-Result-Limit`）：
     * 这张表**没有删除接口**、只会越积越多，所以"一页 100 条"迟早不等于"全部"——
     * 而界面上看不出差别，用户只会以为"我要的那个地点别人没标过"。
     */
    @GET("places")
    suspend fun listPlaces(
        @Query("q") q: String? = null,
        @Query("limit") limit: Int = 100,
    ): Response<List<PlaceDto>>

    @POST("places")
    suspend fun createPlace(@Body body: PlaceCreateRequest): PlaceDto

    /**
     * 改共享地址的名字 / 地址（**只有派单员**）。
     *
     * 用户 2026-09-19：「共享地址的编辑**只有派单员**可以编辑，其他人都编辑不了。
     * 派单员可以改名称…」—— PATCH 语义：只传点名的字段（坐标刻意不给改，见 DTO 注释）。
     */
    @PATCH("places/{placeId}")
    suspend fun updatePlace(@Path("placeId") placeId: Long, @Body body: PlaceUpdateRequest): PlaceDto

    /** 从共享库**删掉**一个地点（只有派单员）。**软删**：`restorePlace` 能原样拿回来。 */
    @DELETE("places/{placeId}")
    suspend fun deletePlace(@Path("placeId") placeId: Long)

    /** 把删掉的共享地点从回收站**原样放回来**（只有派单员）。 */
    @POST("places/{placeId}/restore")
    suspend fun restorePlace(@Path("placeId") placeId: Long): PlaceDto

    /**
     * **撤销**共享地址 → 降为**自己**的普通地点（只有派单员）。
     *
     * 用户 2026-09-19：「也可以撤销某些共享地址，把它降为普通的地址…如果是降为普通的地址的话，
     * 则这个地址会保存在**派单员**的地址库当中，其他的不会显示」。
     */
    @POST("places/{placeId}/demote")
    suspend fun demotePlace(@Path("placeId") placeId: Long): PlaceDemoteOut

    /**
     * 把「我的地点」里的一个地点**设为共享地址**（只有派单员）。
     *
     * ⚠️ 走这个端点而不是 `POST /places`：唯一的输入是**地点编号**，坐标从那一条上取 ——
     * 客户端与 AI 都没有机会自己编一组坐标塞进共享库（那会把司机带错地方）。
     */
    @POST("shipper/locations/{locationId}/share")
    suspend fun shareLocation(@Path("locationId") locationId: Long): PlaceDto

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

    /**
     * 账本流水（**一页**）。
     *
     * 返回 `Response<...>` 是为了**读响应头**：后端缺省上限 1000、最多 5000，被截断时置
     * `X-Truncated: 1`（2026-09-19 外部完整检查 C-4 补的）。**不传日期就是不收窄的全量查询**
     * ——本机实测那条路径 85,474 行 / 27.75 秒 / 29.2MB，拿到的永远只是最近 1000 条。
     * 不说出来的后果：账本页把"一页"当"整段"，合计与趋势都只算了看得见的那些行。
     */
    @GET("ledger/entries")
    suspend fun listEntries(
        @Query("shipper_id") shipperId: Long? = null,
        @Query("temp_shipper_name") tempShipperName: String? = null,
        @Query("date_from") dateFrom: String? = null,
        @Query("date_to") dateTo: String? = null,
    ): Response<List<LedgerEntryDto>>

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

    /** 单个商品（「按商品看各批发商价」页要知道它的名字、默认价、单位）。 */
    @GET("products/{productId}")
    suspend fun getProduct(@Path("productId") productId: Long): ProductDto

    @PATCH("products/{productId}")
    suspend fun updateProduct(@Path("productId") productId: Long, @Body body: ProductUpdateRequest): ProductDto

    /**
     * 成本价的**生效时间轴**（新的在前）。
     *
     * 用户 2026-09-19 要的溯源能力：「保留成本价，还保留这个成本价存在的时间，
     * 从什么时候开始变、从什么时候结束，精确到小时和分钟」。
     *
     * ⚠️ 为什么商品是**查询参数**而不是路径参数：AI 也必须有这个能力，而
     * **模型看不到任何内部编号** —— 带 `{}` 的端点对它是死的
     * （`_gen_ai_read_catalog.py` 按"路径里有没有 `{}`"排除）。
     * 把商品放进 query 之后，模型说商品名、App 解析成编号、调同一条路由。
     *
     * ⚠️ 出参的时间是 **UTC**，显示前必须换算到设备时区（`util/TimeFmt.kt`）。
     * ⛔ 只有派单员能调（成本是内部数，货主/司机连商品详情里的 `cost_price` 都拿不到）。
     */
    @GET("products/cost-history")
    suspend fun productCostHistory(@Query("product_id") productId: Long): List<ProductCostHistoryDto>

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
    /**
     * 专属价列表。
     *
     * ⚠️ **两个方向都要能筛**（2026-09-19）：
     * - `shipperId`：**按批发商**看（「批发商定价」页：这个批发商每个商品多少钱）；
     * - `productId`：**按商品**看（「各批发商价格」页：这个商品每个批发商多少钱）。
     *
     * 后端 `GET /price-rules` 一直支持 `?shipper_id=`，而这里原来一个参数都没有 ——
     * 于是两个页面都是**拉全表再在客户端筛**：批发商一多，打开一页就要下载
     * 所有批发商 × 所有商品的价格。两个参数都传 null 才是"全都要"（只有 AI 按 id 取行需要）。
     */
    @GET("price-rules")
    suspend fun listRules(
        @Query("shipper_id") shipperId: Long? = null,
        @Query("product_id") productId: Long? = null,
    ): List<PriceRuleDto>

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
    /**
     * `fixed` = 统一单价 / `percent` = 商品默认价的百分之多少 /
     * `adjust` = 在**当前生效价**上 ±百分之多少。
     *
     * ⚠️ 原来的 `tier`（引用商品自身第 N 档批发价）已于 2026-09-19 **删除**：
     * 那套"商品上的批发价档位"看起来像是这家商品的批发价，其实下单时谁都不照它走
     * （下单只认按（批发商×商品）存的专属价或商品默认价）—— 用户拍板把那个概念整个删掉。
     * 老客户端若还发 `mode="tier"` 会被后端 422 挡下（这是有意的：宁可报错也不要
     * 让"按一个已经被删掉的概念定价"这条路继续存在）。
     */
    val mode: String,
    @Serializable(with = FlexibleStringSerializer::class) val value: String? = null,
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
    val unit: String? = null,
    /** 传空串 = 清成"未分类"；传 null = 不改（PATCH 部分更新语义）。 */
    val category: String? = null,
    @SerialName("low_stock_alert") val lowStockAlert: Int? = null,
    /** 显示顺序（小的在前）。**只有「商品排序」页会写它**，一次一个商品（逐条 PATCH）。 */
    @SerialName("sort_order") val sortOrder: Int? = null,
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

/**
 * `GET /inventory/movements` 一页取多少条 —— **后端的上限就是 500**（`Query(100, le=500)`）。
 *
 * ⚠️ 取满上限只是"这一页尽量大"，**不等于"全部"**：该端点现在回报 `X-Truncated` /
 *    `X-Result-Limit`（2026-09-19 补的头，见 `AppRepository.parsePageMeta`），界面必须
 *    **读头**说出"还有更早的"。这里原来靠"这页满了就当作还有更多"去猜：后端补头之前
 *    只能这么办，补了头再猜就会在**刚好 500 条**时提示一句假话。
 *    它与后端 `le=500` 是同一件事的两端：改后端上限必须同步这里。
 */
const val INVENTORY_MOVEMENT_PAGE_LIMIT = 500

interface InventoryApi {
    /** 库存流水（**一页**）。返回 `Response<...>` 读截断头，见 [INVENTORY_MOVEMENT_PAGE_LIMIT]。 */
    @GET("inventory/movements")
    suspend fun listMovements(
        @Query("product_id") productId: Long? = null,
        @Query("limit") limit: Int = INVENTORY_MOVEMENT_PAGE_LIMIT,
        @Query("offset") offset: Int = 0,
        @Query("date_from") dateFrom: String? = null,
        @Query("date_to") dateTo: String? = null,
    ): Response<List<InventoryMovementDto>>

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
     * ⚠️ `limit` / `beforeId` **现在后端认了**（2026-09-19 审计 R14-8 修）：原来是一条硬
     * `.limit(200)`，传什么都一样、也不回报截断 —— 于是第 201 条以前的旧消息在 App 里
     * 一个入口都没有（其中包含「账本导出完成」这种 payload 里带唯一下载链接的通知）。
     * 现在返回 `Response<...>` 是为了**读响应头**：`X-Truncated: 1` = 还有更多，
     * 客户端据此显示「加载更多」，用 [beforeId] 往下翻。
     */
    @GET("notifications")
    suspend fun listNotifications(
        @Query("limit") limit: Int = 50,
        /** 只看发给谁的。null = 自己（后端语义），非 null 时派单员可以看别人的。 */
        @Query("recipient_id") recipientId: Long? = null,
        /** 游标：只取 id 小于它的消息（「加载更多」往下翻页）。 */
        @Query("before_id") beforeId: Long? = null,
    ): Response<List<NotificationDto>>

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

    // ---- 运费分类名册（2026-09-21，与商品/开销分类同一套规矩）----
    @GET("freight-categories")
    suspend fun listFreightCategories(): List<FreightCategoryDto>

    @POST("freight-categories")
    suspend fun createFreightCategory(@Body body: FreightCategoryCreateRequest): FreightCategoryDto

    @PATCH("freight-categories/{categoryId}")
    suspend fun updateFreightCategory(
        @Path("categoryId") categoryId: Long,
        @Body body: FreightCategoryUpdateRequest,
    ): FreightCategoryDto

    @DELETE("freight-categories/{categoryId}")
    suspend fun deleteFreightCategory(@Path("categoryId") categoryId: Long)

    @POST("freight-categories/reorder")
    suspend fun reorderFreightCategories(
        @Body body: FreightCategoryReorderRequest,
    ): List<FreightCategoryDto>

    /** 这一单 + 这个司机 → 运价结论（匹配/没匹配到/多条候选都由后端算）。 */
    @GET("freight-templates/quote")
    suspend fun quoteFreight(
        @Query("order_id") orderId: Long,
        @Query("driver_id") driverId: Long? = null,
        @Query("category_id") categoryId: Long? = null,
    ): FreightQuoteDto

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

    /**
     * 敏感操作审计（**一页**）。
     *
     * 返回 `Response<...>` 是为了**读响应头**：被截断时 `X-Truncated: 1`（`le=1000`）。
     * 审计的全部价值就在"能翻到"——不说"还有更早的"，用户会据此判断
     * **"我那次改动没被记录"**，这比少看几条严重得多。
     */
    @GET("operation-logs")
    suspend fun operationLogs(@Query("limit") limit: Int = 60): Response<List<OperationLogDto>>

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

    /** 开销分类名册（按显示顺序）。见 `ExpensesScreen` 左侧那一列。 */
    @GET("expense-categories")
    suspend fun listExpenseCategories(): List<ExpenseCategoryDto>

    @POST("expense-categories")
    suspend fun createExpenseCategory(@Body body: ExpenseCategoryCreateRequest): ExpenseCategoryDto

    @PATCH("expense-categories/{categoryId}")
    suspend fun updateExpenseCategory(
        @Path("categoryId") categoryId: Long,
        @Body body: ExpenseCategoryUpdateRequest,
    ): ExpenseCategoryDto

    @DELETE("expense-categories/{categoryId}")
    suspend fun deleteExpenseCategory(@Path("categoryId") categoryId: Long)

    /** 整份顺序一次提交（`ids[0]` 排最前）。只传一部分后端会 400。 */
    @POST("expense-categories/reorder")
    suspend fun reorderExpenseCategories(
        @Body body: ExpenseCategoryReorderRequest,
    ): List<ExpenseCategoryDto>

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

    /**
     * 资金流水明细（**一页**）。
     *
     * 返回 `Response<...>` 是为了**读响应头**：被截断时 `X-Truncated: 1`（`le=1000`）。
     * 明细条数只影响"看得见几行"（金额一律走下面的 summary，**不许在客户端对一页流水求和**
     * ——实测少算 62%），但"被截断了却不说"会让用户以为这一页就是全部。
     */
    @GET("cash-flows")
    suspend fun listCashFlows(
        @Query("direction") direction: String? = null,
        @Query("biz_type") bizType: String? = null,
        @Query("date_from") dateFrom: String? = null,
        @Query("date_to") dateTo: String? = null,
        // 明细行的条数上限（只影响"看得见几行"）。金额一律走下面的 summary，
        // 不要在客户端对一页流水求和 —— 那会少算（见 CashFlowSummaryDto 的注释）。
        @Query("limit") limit: Int? = null,
    ): Response<List<CashFlowDto>>

    @GET("cash-flows/summary")
    suspend fun cashFlowSummary(
        @Query("direction") direction: String? = null,
        @Query("biz_type") bizType: String? = null,
        @Query("date_from") dateFrom: String? = null,
        @Query("date_to") dateTo: String? = null,
    ): CashFlowSummaryDto

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

/**
 * 常用度（列表排序规则）：**只有一个动作 —— 把我自己的计数清空**（2026-09-22）。
 *
 * 用户在「我的 → 基础设置」里点「重置计数」时调它（界面先弹确认框）。
 * ⛔ 后端只清**当前登录人**的行 —— 这个接口没有"清别人"的口子（见 `api/v1/usage.py`）。
 */
interface UsageApi {
    @POST("usage/reset")
    suspend fun reset(): UsageResetDto
}

/** 系统：版本更新检测 + 测试账号的默认 AI 配置 */
interface SystemApi {
    @GET("system/app-version")
    suspend fun appVersion(): AppVersionDto
    /**
     * 测试账号的默认模型服务（服务端 `.env` 提供）。
     *
     * ⚠️ 只有白名单手机号拿得到：非测试号 → **403**，服务端没配 key → **404**；
     * 两种情况都要按"没有默认可用"处理（各自给一句人话，别把它当成网络错误重试）。
     */
    @GET("system/ai-default")
    suspend fun aiDefault(): AiDefaultDto
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

/**
 * 货主**自己那一本账**：批发商给他下游货主的核销（2026-09-20）。
 *
 * ⛔ 与 [LedgerApi]（派单员开的公司账）是**两本账**，谁都不写谁：
 * 这里记的是"我的客户欠我多少、我收到了多少"，走的是 `shipper-ledger` 这一组端点，
 * 后端一个字节都不写 `orders.paid` / `cash_flows` / `ledgers`。
 *
 * 只有**批发商货主**能写（普通货主调写接口一律 403，后端会给一句中文说明）；
 * 读也限货主自己（派单员/司机 403）。列表返回 `Response<...>` 是为了读
 * `X-Truncated` / `X-Result-Limit` 两个头（`AppRepository.pageRows()`）。
 */
interface ShipperLedgerApi {
    /**
     * 我记下的核销记录。
     *
     * ⚠️ 窗口按**订单的送达日**（`delivered_from/to`）而不是核销时间：
     *    否则"上个月送的单、今天收到钱"会从本月账面上消失，那一单看起来又变成没核销。
     */
    @GET("shipper-ledger/settlements")
    suspend fun listSettlements(
        @Query("order_id") orderId: Long? = null,
        @Query("delivered_from") deliveredFrom: String? = null,
        @Query("delivered_to") deliveredTo: String? = null,
        /** 连**已撤销**的核销一起回（界面上那个「已撤销」折叠区要用它）。 */
        @Query("include_deleted") includeDeleted: Boolean? = null,
        @Query("limit") limit: Int? = null,
    ): Response<List<ShipperSettlementDto>>

    /** 核销一笔：`lines` 留空 = 整单；给了行 = 按商品核销。金额由后端按"还可核销"算。 */
    @POST("shipper-ledger/settlements")
    suspend fun createSettlement(@Body body: ShipperSettlementCreateRequest): ShipperSettlementDto

    /** **撤掉核销**（软删：记录留着，`restore` 能原样放回来）。 */
    @DELETE("shipper-ledger/settlements/{settlementId}")
    suspend fun deleteSettlement(@Path("settlementId") settlementId: Long)

    @POST("shipper-ledger/settlements/{settlementId}/restore")
    suspend fun restoreSettlement(@Path("settlementId") settlementId: Long): ShipperSettlementDto
}

@Serializable
data class ShipperSettlementLineDto(
    val id: Long = 0,
    @SerialName("order_product_id") val orderProductId: Long = 0,
    /** 商品名快照（订单行没了这笔钱仍要能说清核的是哪样货）。 */
    @SerialName("product_name") val productName: String = "",
    @SerialName("amount") @Serializable(with = FlexibleStringSerializer::class) val amount: String = "0",
)

@Serializable
data class ShipperSettlementDto(
    val id: Long = 0,
    @SerialName("order_id") val orderId: Long = 0,
    @SerialName("order_no") val orderNo: String? = null,
    /** 归属货主（订单上的收货人）。 */
    @SerialName("customer_name") val customerName: String = "",
    @SerialName("customer_phone") val customerPhone: String = "",
    @SerialName("amount") @Serializable(with = FlexibleStringSerializer::class) val amount: String = "0",
    val method: String = "cash",
    val note: String = "",
    @SerialName("settled_at") val settledAt: String = "",
    /** `app` = 人工点的；`ai` = AI 助手确认卡提交的。 */
    val source: String = "app",
    @SerialName("is_deleted") val isDeleted: Boolean = false,
    @SerialName("created_at") val createdAt: String = "",
    val lines: List<ShipperSettlementLineDto> = emptyList(),
)

/** 核销的一行：核哪一行商品、核多少钱。 */
@Serializable
data class ShipperSettlementLineRequest(
    @SerialName("order_product_id") val orderProductId: Long,
    @SerialName("amount") val amount: String,
)

@Serializable
data class ShipperSettlementCreateRequest(
    @SerialName("order_id") val orderId: Long,
    /** 留空 = 整单核销（每一行按「还可核销」全额）。 */
    val lines: List<ShipperSettlementLineRequest> = emptyList(),
    val method: String = "cash",
    val note: String = "",
    /** `ai` = AI 助手确认卡。 */
    val source: String = "app",
)