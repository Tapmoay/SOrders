package com.tapmoay.sorders.data.remote.dto

import kotlinx.serialization.KSerializer
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.descriptors.PrimitiveKind
import kotlinx.serialization.descriptors.PrimitiveSerialDescriptor
import kotlinx.serialization.descriptors.SerialDescriptor
import kotlinx.serialization.encoding.Decoder
import kotlinx.serialization.encoding.Encoder
import kotlinx.serialization.json.JsonDecoder
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonPrimitive

/**
 * 后端 Decimal/坐标字段在 JSON 中可能为 number 或 string（Pydantic v2 序列化 Decimal 为字符串），
 * 统一解析为 String 避免类型不稳定。
 */
object FlexibleStringSerializer : KSerializer<String> {
    override val descriptor: SerialDescriptor =
        PrimitiveSerialDescriptor("FlexibleString", PrimitiveKind.STRING)
    override fun deserialize(decoder: Decoder): String {
        val el = (decoder as? JsonDecoder)?.decodeJsonElement()
        return when (el) {
            is JsonPrimitive -> if (el.isString) el.content else el.content
            else -> el?.toString() ?: ""
        }
    }
    override fun serialize(encoder: Encoder, value: String) = encoder.encodeString(value)
}

/** 可空版：后端剥离金额返回 null 时落为 null（与"真实0"区分）。 */
object NullableFlexibleStringSerializer : KSerializer<String?> {
    override val descriptor: SerialDescriptor =
        PrimitiveSerialDescriptor("NullableFlexibleString", PrimitiveKind.STRING)
    override fun deserialize(decoder: Decoder): String? {
        val el = (decoder as? JsonDecoder)?.decodeJsonElement()
        return when (el) {
            null, is kotlinx.serialization.json.JsonNull -> null
            is JsonPrimitive -> el.content
            else -> el.toString()
        }
    }
    override fun serialize(encoder: Encoder, value: String?) = encoder.encodeString(value ?: "")
}

// ===== 认证 =====
@Serializable
data class TokenDto(
    val access_token: String,
    val token_type: String = "bearer",
    val role: String,
    val user_id: Long,
)

@Serializable
data class LoginRequest(
    val password: String,
    val phone: String? = null,
    val username: String? = null,
)

@Serializable
data class SendSmsRequest(val phone: String)

@Serializable
data class RegisterRequest(
    val username: String,
    val password: String,
    val phone: String,
    @SerialName("verification_code") val verificationCode: String,
)

// ===== 用户 =====
@Serializable
data class UserDto(
    val id: Long,
    val username: String,
    val phone: String,
    @SerialName("full_name") val fullName: String = "",
    val role: String,
    @SerialName("is_active") val isActive: Boolean = true,
    @SerialName("is_member") val isMember: Boolean = false,
    @SerialName("vehicle_type") val vehicleType: String? = null,
    @SerialName("billing_mode") val billingMode: String? = null,
    @Serializable(with = NullableFlexibleStringSerializer::class) val salary: String? = null,
    @SerialName("created_at") val createdAt: String = "",
)

// ===== 订单 =====
@Serializable
data class OrderProductDto(
    val id: Long = 0,
    @SerialName("order_id") val orderId: Long = 0,
    @SerialName("product_id") val productId: Long? = null,
    @SerialName("product_name_snapshot") val productNameSnapshot: String = "",
    val quantity: Int = 1,
    @Serializable(with = NullableFlexibleStringSerializer::class) @SerialName("unit_price")
    val unitPrice: String? = null,
    @Serializable(with = NullableFlexibleStringSerializer::class) @SerialName("line_total")
    val lineTotal: String? = null,
)

@Serializable
data class OrderDto(
    val id: Long,
    @SerialName("order_no") val orderNo: String,
    val status: String,
    @SerialName("shipper_id") val shipperId: Long? = null,
    @SerialName("temp_shipper_name") val tempShipperName: String? = null,
    @SerialName("driver_id") val driverId: Long? = null,
    @SerialName("order_date") val orderDate: String = "",
    @SerialName("delivery_description") val deliveryDescription: String = "",
    @SerialName("address_detail") val addressDetail: String = "",
    @Serializable(with = FlexibleStringSerializer::class) @SerialName("address_lat")
    val addressLat: String? = null,
    @Serializable(with = FlexibleStringSerializer::class) @SerialName("address_lng")
    val addressLng: String? = null,
    @SerialName("contact_dongjia_phone") val contactDongjiaPhone: String = "",
    @SerialName("contact_boss_phone") val contactBossPhone: String = "",
    val remark: String = "",
    @SerialName("internal_notes") val internalNotes: String = "",
    @SerialName("driver_remark") val driverRemark: String = "",
    @SerialName("delivery_photo_urls") val deliveryPhotoUrls: List<String>? = null,
    @SerialName("created_at") val createdAt: String = "",
    @SerialName("dispatched_at") val dispatchedAt: String? = null,
    @SerialName("driver_acknowledged_at") val driverAcknowledgedAt: String? = null,
    @SerialName("delivered_at") val deliveredAt: String? = null,
    @SerialName("cancelled_at") val cancelledAt: String? = null,
    @SerialName("order_products") val orderProducts: List<OrderProductDto> = emptyList(),
    @SerialName("driver_phone") val driverPhone: String? = null,
    @SerialName("driver_name") val driverName: String? = null,
    @SerialName("shipper_name") val shipperName: String? = null,
    @SerialName("is_new_for_driver") val isNewForDriver: Boolean = false,
    @Serializable(with = NullableFlexibleStringSerializer::class) @SerialName("freight_fee")
    val freightFee: String? = null,
    @SerialName("freight_visible") val freightVisible: Boolean = false,
    @SerialName("driver_billing_mode") val driverBillingMode: String? = null,
    @SerialName("collect_cash") val collectCash: Boolean = false,
    @SerialName("parent_order_id") val parentOrderId: Long? = null,
    @SerialName("expected_deliver_before") val expectedDeliverBefore: String? = null,
    @SerialName("is_exception") val isException: Boolean = false,
    @SerialName("exception_reason") val exceptionReason: String = "",
    @SerialName("exception_resolution") val exceptionResolution: String = "",
    @SerialName("payment_method") val paymentMethod: String = "cash",
    @SerialName("address_image_url") val addressImageUrl: String? = null,
    val paid: Boolean = false,
    @SerialName("arrears_unit_id") val arrearsUnitId: Long? = null,
    @SerialName("arrears_unit_name") val arrearsUnitName: String? = null,
)

@Serializable
data class OrderProductLine(
    @SerialName("product_id") val productId: Long? = null,
    @SerialName("product_name_snapshot") val productNameSnapshot: String = "",
    val quantity: Int = 1,
    @Serializable(with = FlexibleStringSerializer::class) @SerialName("unit_price")
    val unitPrice: String = "0",
    @Serializable(with = FlexibleStringSerializer::class) @SerialName("line_total")
    val lineTotal: String = "0",
) {
    companion object {
        fun create(name: String, qty: Int, price: String): OrderProductLine =
            OrderProductLine(
                productNameSnapshot = name,
                quantity = qty,
                unitPrice = price,
                lineTotal = ((price.toDoubleOrNull() ?: 0.0) * qty).let {
                    if (it % 1.0 == 0.0) it.toInt().toString() else "%.2f".format(it)
                },
            )
    }
}

@Serializable
data class OrderCreateRequest(
    val lines: List<OrderProductLine>,
    @SerialName("order_date") val orderDate: String? = null,
    @SerialName("delivery_description") val deliveryDescription: String = "",
    @SerialName("address_detail") val addressDetail: String = "",
    @Serializable(with = FlexibleStringSerializer::class) @SerialName("address_lat")
    val addressLat: String? = null,
    @Serializable(with = FlexibleStringSerializer::class) @SerialName("address_lng")
    val addressLng: String? = null,
    @SerialName("contact_dongjia_phone") val contactDongjiaPhone: String = "",
    @SerialName("contact_boss_phone") val contactBossPhone: String = "",
    val remark: String = "",
    @SerialName("shipper_id") val shipperId: Long? = null,
    @SerialName("temp_shipper_name") val tempShipperName: String? = null,
)

@Serializable
data class OrderUpdateRequest(
    @SerialName("delivery_description") val deliveryDescription: String? = null,
    @SerialName("address_detail") val addressDetail: String? = null,
    @SerialName("address_lat") val addressLat: String? = null,
    @SerialName("address_lng") val addressLng: String? = null,
    @SerialName("contact_dongjia_phone") val contactDongjiaPhone: String? = null,
    @SerialName("contact_boss_phone") val contactBossPhone: String? = null,
    val remark: String? = null,
    @SerialName("internal_notes") val internalNotes: String? = null,
)

@Serializable
data class OrderAssignRequest(
    @SerialName("driver_id") val driverId: Long,
    @SerialName("internal_note") val internalNote: String? = null,
    @SerialName("freight_fee") val freightFee: String? = null,
    @SerialName("collect_cash") val collectCash: Boolean? = null,
)

@Serializable
data class OrderBatchAssignRequest(
    @SerialName("order_ids") val orderIds: List<Long>,
    @SerialName("driver_id") val driverId: Long,
    @SerialName("internal_note") val internalNote: String? = null,
    @SerialName("collect_cash") val collectCash: Boolean? = null,
)

@Serializable
data class BatchAssignResult(
    @SerialName("order_id") val orderId: Long,
    val success: Boolean,
    val detail: String? = null,
)

@Serializable
data class OrderBatchAssignOut(val results: List<BatchAssignResult> = emptyList())

@Serializable
data class OrderChargeBody(@SerialName("arrears_unit_id") val arrearsUnitId: Long)

@Serializable
data class OrderRecallBody(val reason: String)

@Serializable
data class OrderCancelBody(val reason: String = "")

@Serializable
data class OrderExceptionBody(
    @SerialName("is_exception") val isException: Boolean = true,
    @SerialName("exception_reason") val exceptionReason: String = "",
    @SerialName("exception_resolution") val exceptionResolution: String = "",
    @SerialName("expected_deliver_before") val expectedDeliverBefore: String? = null,
)

@Serializable
data class DeliveryPhotoUploadOut(val urls: List<String> = emptyList())

@Serializable
data class OrderCompleteBody(
    @SerialName("delivery_photo_urls") val deliveryPhotoUrls: List<String>,
    @SerialName("driver_remark") val driverRemark: String = "",
    @SerialName("payment") val payment: String? = null,
)

@Serializable
data class DriverNoteBody(val note: String)

// ===== 货主地址 / 联系人 =====
@Serializable
data class AddressDto(
    val id: Long,
    @SerialName("shipper_id") val shipperId: Long = 0,
    @SerialName("receiver_name") val receiverName: String = "",
    val phone: String = "",
    @SerialName("detail_address") val detailAddress: String = "",
    val remark: String = "",
    @SerialName("is_default") val isDefault: Boolean = false,
    @Serializable(with = FlexibleStringSerializer::class) @SerialName("address_lat")
    val addressLat: String? = null,
    @Serializable(with = FlexibleStringSerializer::class) @SerialName("address_lng")
    val addressLng: String? = null,
    @SerialName("origin_address") val originAddress: String? = null,
    @Serializable(with = FlexibleStringSerializer::class) @SerialName("origin_lat")
    val originLat: String? = null,
    @Serializable(with = FlexibleStringSerializer::class) @SerialName("origin_lng")
    val originLng: String? = null,
    @SerialName("image_urls") val imageUrls: List<String> = emptyList(),
    @SerialName("image_url") val imageUrl: String? = null,
    @SerialName("created_at") val createdAt: String = "",
)

@Serializable
data class AddressCreateRequest(
    @SerialName("receiver_name") val receiverName: String = "",
    val phone: String = "",
    @SerialName("detail_address") val detailAddress: String = "",
    val remark: String = "",
    @SerialName("is_default") val isDefault: Boolean = false,
    @SerialName("address_lat") val addressLat: String? = null,
    @SerialName("address_lng") val addressLng: String? = null,
    @SerialName("origin_address") val originAddress: String? = null,
    @SerialName("origin_lat") val originLat: String? = null,
    @SerialName("origin_lng") val originLng: String? = null,
    @SerialName("image_urls") val imageUrls: List<String> = emptyList(),
)

@Serializable
data class ContactDto(
    val id: Long,
    @SerialName("shipper_id") val shipperId: Long = 0,
    val phone: String,
    @SerialName("display_name") val displayName: String = "",
    @SerialName("created_at") val createdAt: String = "",
)

@Serializable
data class ContactUpdateRequest(
    val phone: String? = null,
    @SerialName("display_name") val displayName: String? = null,
)

@Serializable
data class LocationDto(
    val id: Long,
    @SerialName("shipper_id") val shipperId: Long = 0,
    val name: String = "",
    @SerialName("detail_address") val detailAddress: String = "",
    val remark: String = "",
    @Serializable(with = FlexibleStringSerializer::class) @SerialName("address_lat")
    val addressLat: String? = null,
    @Serializable(with = FlexibleStringSerializer::class) @SerialName("address_lng")
    val addressLng: String? = null,
    @SerialName("image_urls") val imageUrls: List<String> = emptyList(),
    @SerialName("image_url") val imageUrl: String? = null,
    @SerialName("created_at") val createdAt: String = "",
)

@Serializable
data class LocationImageOut(val url: String = "")

@Serializable
data class LocationCreateRequest(
    val name: String = "",
    @SerialName("detail_address") val detailAddress: String = "",
    val remark: String = "",
    @SerialName("address_lat") val addressLat: String? = null,
    @SerialName("address_lng") val addressLng: String? = null,
    @SerialName("image_urls") val imageUrls: List<String> = emptyList(),
)

@Serializable
data class ContactCreateRequest(
    val phone: String,
    @SerialName("display_name") val displayName: String = "",
)

// ===== 账本 =====
@Serializable
data class LedgerEntryDto(
    val id: Long,
    @SerialName("shipper_id") val shipperId: Long? = null,
    @SerialName("temp_shipper_name") val tempShipperName: String? = null,
    @SerialName("entry_date") val entryDate: String = "",
    @SerialName("product_name") val productName: String = "",
    val quantity: Int = 1,
    @Serializable(with = FlexibleStringSerializer::class) @SerialName("unit_price")
    val unitPrice: String = "0",
    @Serializable(with = FlexibleStringSerializer::class) val total: String = "0",
    @SerialName("order_id") val orderId: Long? = null,
    @SerialName("order_product_id") val orderProductId: Long? = null,
    @SerialName("product_id") val productId: Long? = null,
    @SerialName("order_no") val orderNo: String? = null,
    @SerialName("order_delivery_description") val orderDeliveryDescription: String? = null,
    val source: String = "manual",
    val note: String = "",
    @SerialName("created_at") val createdAt: String = "",
)

@Serializable
data class LedgerAccountOut(
    val id: Long? = null,
    @SerialName("temp_name") val tempName: String? = null,
    val name: String = "",
    val count: Int = 0,
    @Serializable(with = FlexibleStringSerializer::class) val total: String = "0",
)

@Serializable
data class LedgerCreateRequest(
    @SerialName("shipper_id") val shipperId: Long? = null,
    @SerialName("temp_shipper_name") val tempShipperName: String? = null,
    @SerialName("entry_date") val entryDate: String,
    @SerialName("product_name") val productName: String,
    val quantity: Int = 1,
    @Serializable(with = FlexibleStringSerializer::class) @SerialName("unit_price")
    val unitPrice: String = "0",
    @Serializable(with = FlexibleStringSerializer::class) val total: String? = null,
    @SerialName("order_id") val orderId: Long? = null,
    @SerialName("order_product_id") val orderProductId: Long? = null,
    @SerialName("product_id") val productId: Long? = null,
    val source: String = "manual",
    val note: String = "",
)

// ===== 通知 =====
@Serializable
data class NotificationDto(
    val id: Long,
    @SerialName("recipient_id") val recipientId: Long = 0,
    val category: String = "system",
    val type: String = "system",
    @SerialName("speech_important") val speechImportant: Boolean = false,
    val title: String = "",
    val content: String = "",
    val payload: Map<String, kotlinx.serialization.json.JsonElement>? = null,
    @SerialName("read_at") val readAt: String? = null,
    @SerialName("created_at") val createdAt: String = "",
)

@Serializable
data class UnreadCountDto(val count: Long = 0)

@Serializable
data class NotificationCreateRequest(
    @SerialName("recipient_id") val recipientId: Long,
    val category: String = "system",
    val type: String = "system",
    val title: String = "",
    val content: String = "",
    val payload: Map<String, String>? = null,
    @SerialName("speech_important") val speechImportant: Boolean = false,
)

// ===== 商品目录 =====
@Serializable
data class ProductDto(
    val id: Long,
    val name: String,
    @SerialName("name_color") val nameColor: String? = null,
    @Serializable(with = FlexibleStringSerializer::class) @SerialName("default_unit_price")
    val defaultUnitPrice: String = "0",
    @Serializable(with = FlexibleStringSerializer::class) @SerialName("cost_price")
    val costPrice: String = "0",
    @SerialName("is_active") val isActive: Boolean = true,
    @SerialName("image_url") val imageUrl: String? = null,
    val stock: Int = 0,
    @SerialName("tier_prices") val tierPrices: List<ProductTierDto> = emptyList(),
    val unit: String = "件",
    @SerialName("low_stock_alert") val lowStockAlert: Int = 0,
)

// ===== 多档批发价 =====
@Serializable
data class ProductTierDto(
    val label: String = "",
    @SerialName("unit_price") @Serializable(with = FlexibleStringSerializer::class)
    val unitPrice: String = "0",
)

// ===== 挂账单位 =====
@Serializable
data class ArrearsUnitDto(
    val id: Long,
    val name: String,
    val phone: String = "",
    val remark: String = "",
    @SerialName("created_at") val createdAt: String = "",
)

@Serializable
data class ArrearsUnitCreateRequest(
    val name: String,
    val phone: String = "",
    val remark: String = "",
)

@Serializable
data class ArrearsUnitUpdateRequest(
    val name: String? = null,
    val phone: String? = null,
    val remark: String? = null,
)

// ===== 库存 =====
@Serializable
data class InventoryMovementDto(
    val id: Long,
    @SerialName("product_id") val productId: Long,
    val change: Int,
    val note: String = "",
    @SerialName("operator_id") val operatorId: Long = 0,
    @SerialName("created_at") val createdAt: String = "",
)

@Serializable
data class InventoryMovementCreateRequest(
    @SerialName("product_id") val productId: Long,
    val change: Int,
    val note: String = "",
)

@Serializable
data class InventorySummaryItemDto(
    @SerialName("product_id") val productId: Long,
    @SerialName("product_name") val productName: String,
    val stock: Int,
    val unit: String = "件",
    @SerialName("low_stock_alert") val lowStockAlert: Int = 0,
)

// ===== 通用响应 =====
@Serializable
data class ApiErrorResponse(val detail: String = "")

// ===== Socket 事件 =====
data class SocketEvent(
    val name: String,          // "realtime" / "notification" / "unread_count" / "sync"
    val data: Map<String, Any?>,
) {
    /** org.json 数字可能是 Integer/Long/Double，统一走 Number 转换 */
    val orderId: Long? = (data["order_id"] as? Number)?.toLong()
        ?: (data["order_id"] as? String)?.toLongOrNull()

    /** realtime 事件类型：order.assigned / order.revoked / dispatcher.pending_pool 等 */
    val type: String = (data["type"] as? String) ?: ""
}

// ===== 报表 =====
@Serializable
data class ReportSeriesItem(
    val label: String = "",
    @Serializable(with = FlexibleStringSerializer::class) val amount: String = "0",
    val orders: Int = 0,
    @Serializable(with = FlexibleStringSerializer::class) val freight: String = "0",
)

@Serializable
data class TurnoverReportDto(
    @SerialName("period_label") val periodLabel: String = "",
    @Serializable(with = FlexibleStringSerializer::class) @SerialName("total_amount") val totalAmount: String = "0",
    @SerialName("total_orders") val totalOrders: Int = 0,
    @Serializable(with = FlexibleStringSerializer::class) @SerialName("total_freight") val totalFreight: String = "0",
    @Serializable(with = FlexibleStringSerializer::class) @SerialName("avg_order") val avgOrder: String = "0",
    val series: List<ReportSeriesItem> = emptyList(),
)

@Serializable
data class ProductReportItemDto(
    @SerialName("product_name") val productName: String = "",
    val qty: Int = 0,
    @Serializable(with = FlexibleStringSerializer::class) val amount: String = "0",
    @SerialName("order_count") val orderCount: Int = 0,
)

@Serializable
data class ProductReportDto(
    @SerialName("period_label") val periodLabel: String = "",
    @SerialName("total_qty") val totalQty: Int = 0,
    @Serializable(with = FlexibleStringSerializer::class) @SerialName("total_amount") val totalAmount: String = "0",
    val items: List<ProductReportItemDto> = emptyList(),
)

@Serializable
data class DriverPerformanceRowDto(
    @SerialName("driver_id") val driverId: Long = 0,
    @SerialName("driver_name") val driverName: String = "",
    @SerialName("completed_count") val completedCount: Int = 0,
    @SerialName("on_time_rate") val onTimeRate: Double? = null,
    @SerialName("avg_delivery_seconds") val avgDeliverySeconds: Double? = null,
    @SerialName("photo_upload_rate") val photoUploadRate: Double = 0.0,
)

@Serializable
data class DriverPerformanceDto(
    @SerialName("period_label") val periodLabel: String = "",
    val drivers: List<DriverPerformanceRowDto> = emptyList(),
)

@Serializable
data class ExceptionOrderDto(
    val id: Long = 0,
    @SerialName("order_no") val orderNo: String = "",
    @SerialName("order_date") val orderDate: String = "",
    val status: String = "",
    @SerialName("shipper_name") val shipperName: String? = null,
    @SerialName("driver_name") val driverName: String? = null,
    @SerialName("exception_reason") val exceptionReason: String = "",
    @SerialName("exception_resolution") val exceptionResolution: String = "",
    @SerialName("expected_deliver_before") val expectedDeliverBefore: String? = null,
    @SerialName("delivered_at") val deliveredAt: String? = null,
    @SerialName("exception_resolved_at") val exceptionResolvedAt: String? = null,
)

@Serializable
data class ExceptionResolveRequest(
    val note: String? = null,
)

@Serializable
data class ExceptionResolveResult(
    val ok: Boolean = false,
    @SerialName("order_id") val orderId: Long = 0,
)


// ===== 运费模板 =====
@Serializable
data class FreightTemplateDto(
    val id: Long = 0,
    val name: String = "",
    @SerialName("from_place") val fromPlace: String = "",
    @SerialName("to_place") val toPlace: String = "",
    @SerialName("vehicle_type") val vehicleType: String? = null,
    @Serializable(with = FlexibleStringSerializer::class) val fee: String = "0",
    val remark: String = "",
    @SerialName("created_by") val createdBy: Long? = null,
    @SerialName("created_at") val createdAt: String = "",
)

@Serializable
data class FreightTemplateRequest(
    val name: String,
    @SerialName("from_place") val fromPlace: String = "",
    @SerialName("to_place") val toPlace: String = "",
    @SerialName("vehicle_type") val vehicleType: String? = null,
    @Serializable(with = FlexibleStringSerializer::class) val fee: String = "0",
    val remark: String = "",
)

@Serializable
data class OrderSplitRequest(
    val parts: List<Int>,
)

@Serializable
data class FreightUpdateRequest(
    @SerialName("freight_fee") val freightFee: String? = null,
)

@Serializable
data class FreightSettlementDto(
    val month: String = "",
    val groups: List<FreightSettlementGroupDto> = emptyList(),
)

@Serializable
data class FreightSettlementGroupDto(
    @SerialName("driver_id") val driverId: Long = 0,
    @SerialName("driver_name") val driverName: String = "",
    val count: Int = 0,
    val total: Double = 0.0,
    val orders: List<FreightSettlementOrderDto> = emptyList(),
)

@Serializable
data class FreightSettlementOrderDto(
    @SerialName("order_id") val orderId: Long = 0,
    @SerialName("order_no") val orderNo: String = "",
    @SerialName("delivered_at") val deliveredAt: String? = null,
    @SerialName("freight_fee") val freightFee: String = "",
    @SerialName("delivery_description") val deliveryDescription: String = "",
    @SerialName("address_detail") val addressDetail: String = "",
)

