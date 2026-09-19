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
    // 计费规则（v3.36）：他挂着哪一份、以及**一句话说明他现在怎么算钱**。
    // `pay_summary` 是后端算好的（和账单口径同源），界面不许自己拼——拼了必然和账单不一致。
    @SerialName("driver_rule_id") val driverRuleId: Long? = null,
    @SerialName("driver_rule_name") val driverRuleName: String = "",
    @SerialName("pay_summary") val paySummary: String = "",
    // 「他按不按单拿钱」——派单端要不要给他显示运费框，**以后端为准**（同 `snapshot_mode`，
    // 规则优先）。界面不许自己按 `billingMode ?: 车型` 猜：挂着运费提成规则的大车司机会被
    // 猜成工资制，于是运费框不显示、运费为空、提成算成 0 → 连账单都不生成（报告 P0-3）。
    // null = 老后端还没这个字段 → 退回兜底判据（与 `resolve_billing_mode` 一致）。
    @SerialName("pays_per_order") val paysPerOrder: Boolean? = null,
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
    /** 下单时定格的单位（件/箱/斤…）；老数据是空串 → 显示时不编"件"出来。 */
    val unit: String = "",
    @SerialName("damage_quantity") val damageQuantity: Int = 0,
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
    /**
     * 导航信息来源：`driver` / `dispatcher` = 到场补录，null/空 = 下单时就带坐标。
     * 货主端那句"司机已帮你补上导航信息"靠它才**是真的**（不靠猜）。
     */
    @SerialName("nav_source") val navSource: String? = null,
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
    @SerialName("driver_piece_amount") val driverPieceAmount: String? = null,
    @SerialName("driver_commission_rate") val driverCommissionRate: String? = null,
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
    @SerialName("damage_note") val damageNote: String = "",
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
    /**
     * 这一行的单位（件/箱/斤…）。
     *
     * 用户在选品弹窗里可以改（"数量后面是要有对应的单位的"），所以它跟着**行**走，
     * 不是每次都回商品库拿。留空 = 后端按商品库里的单位兜底。
     * ⚠️ 它**不参与任何金额计算**（钱只认 quantity × unitPrice）。
     */
    val unit: String = "",
) {
    companion object {
        /**
         * 造一条商品行。
         *
         * ⚠️ **[productId] 一定要传**（从商品目录里选的那一项的编号）。
         * 它不是"顺手带的元数据"，后端靠它做两件事：
         * 1. 写 `cost_price_snapshot`（成本快照）——没有它成本按 0 记，
         *    于是**毛利虚高**，而且虚高的数字看起来完全正常；
         * 2. 送达时按商品扣库存——没有它只能退化成"按商品名找唯一同名"，
         *    改过名或重名的商品就**静默不扣**。
         * 手输的自定义商品行（商品库里没有的）才允许为空。
         */
        fun create(
            name: String,
            qty: Int,
            price: String,
            productId: Long? = null,
            unit: String = "",
        ): OrderProductLine =
            OrderProductLine(
                productId = productId,
                productNameSnapshot = name,
                quantity = qty,
                unitPrice = price,
                unit = unit,
                lineTotal = ((price.toDoubleOrNull() ?: 0.0) * qty).let {
                    if (it % 1.0 == 0.0) it.toInt().toString() else "%.2f".format(it)
                },
            )
    }
}

/**
 * **已存在的**订单商品行（从 `GET /order-products` 读回来的）。
 *
 * 为什么不复用 [OrderProductLine]：那个是"下单时提交的行"，**没有 `id`**
 * （下单不需要它）。而"改/删某一行的商品"必须能指到那一行——没有 id 就无从下手。
 */
@Serializable
data class OrderProductRow(
    val id: Long,
    @SerialName("order_id") val orderId: Long = 0,
    @SerialName("product_id") val productId: Long? = null,
    @SerialName("product_name_snapshot") val productNameSnapshot: String = "",
    val quantity: Int = 1,
    @Serializable(with = FlexibleStringSerializer::class) @SerialName("unit_price")
    val unitPrice: String = "0",
    @Serializable(with = FlexibleStringSerializer::class) @SerialName("line_total")
    val lineTotal: String = "0",
    /** 下单时定格的单位；老数据是空串（不编一个"件"出来）。 */
    val unit: String = "",
)

@Serializable
data class OrderProductCreateRequest(
    @SerialName("order_id") val orderId: Long,
    @SerialName("product_id") val productId: Long? = null,
    @SerialName("product_name_snapshot") val productNameSnapshot: String,
    val quantity: Int,
    @Serializable(with = FlexibleStringSerializer::class) @SerialName("unit_price")
    val unitPrice: String,
    val unit: String = "",
)

@Serializable
data class OrderProductUpdateRequest(
    @SerialName("product_name_snapshot") val productNameSnapshot: String? = null,
    val quantity: Int? = null,
    @Serializable(with = FlexibleStringSerializer::class) @SerialName("unit_price")
    val unitPrice: String? = null,
    @Serializable(with = FlexibleStringSerializer::class) @SerialName("line_total")
    val lineTotal: String? = null,
    val unit: String? = null,
)

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
    @SerialName("driver_piece_amount") val driverPieceAmount: String? = null,
    @SerialName("driver_commission_rate") val driverCommissionRate: String? = null,
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
    @SerialName("damage_items") val damageItems: List<DamageItem> = emptyList(),
    @SerialName("damage_note") val damageNote: String = "",
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
    /** 自定义分类（"" = 未分类）。地址库左侧那一列按它分栏。 */
    val category: String = "",
    /** 是不是仓库（**只有派单员能标**）。送到仓库的单按"货进来了"处理（自动入库）。 */
    @SerialName("is_warehouse") val isWarehouse: Boolean = false,
    @SerialName("image_urls") val imageUrls: List<String> = emptyList(),
    @SerialName("image_url") val imageUrl: String? = null,
    @SerialName("created_at") val createdAt: String = "",
)

/**
 * 地点分类名册（**按人分区**：每个人管自己地址库左侧那一列）。
 *
 * 与商品分类同一套形状，差别是"谁的"——读回来的一定是**当前登录人自己那一份**。
 */
@Serializable
data class PlaceCategoryDto(
    val id: Long,
    val name: String = "",
    @SerialName("sort_order") val sortOrder: Int = 0,
    /** 这一类下**在用**的地点条数（删之前要让用户看见影响面）。 */
    @SerialName("location_count") val locationCount: Int = 0,
)

@Serializable
data class PlaceCategoryCreateRequest(val name: String, @SerialName("sort_order") val sortOrder: Int? = null)

@Serializable
data class PlaceCategoryUpdateRequest(val name: String? = null, @SerialName("sort_order") val sortOrder: Int? = null)

@Serializable
data class PlaceCategoryReorderRequest(val ids: List<Long>)

@Serializable
data class LocationImageOut(val url: String = "")

// ===== 共享地点库（导航信息）=====
/**
 * 一条**全库共用**的导航坐标。
 *
 * 与 [LocationDto] 的区别要说清楚：`LocationDto` 是**某个货主自己的**地点库，
 * 而这张表**不按人分区** —— 司机到场补录的坐标、别人标过的点，三种角色都看得到。
 * 用户 2026-09-18 要的就是这个："共同的库，相同的位置直接拉过来，
 * 省的每个人都要手动上传一次"。
 */
@Serializable
data class PlaceDto(
    val id: Long,
    val name: String = "",
    @SerialName("detail_address") val detailAddress: String = "",
    @Serializable(with = FlexibleStringSerializer::class) @SerialName("address_lat")
    val addressLat: String = "0",
    @Serializable(with = FlexibleStringSerializer::class) @SerialName("address_lng")
    val addressLng: String = "0",
    /** driver / dispatcher / shipper —— 这条坐标是谁标的。 */
    val source: String = "driver",
    /** 被几个单/几个人沿用过的次数，列表按它倒序（常用的排前面）。 */
    @SerialName("use_count") val useCount: Int = 1,
    /**
     * 本次是"并入了已有坐标"还是"新建了一条"。
     * ⚠️ 只有 `POST /places` 的返回里有意义，列表接口恒为 false。
     */
    val merged: Boolean = false,
)

@Serializable
data class PlaceCreateRequest(
    val name: String = "",
    @SerialName("detail_address") val detailAddress: String = "",
    @SerialName("address_lat") val addressLat: String,
    @SerialName("address_lng") val addressLng: String,
)

/** 「我用了一次共享地点」的答复：`autoAdded=true` = 这一次刚把它加进了我的地点库。 */
@Serializable
data class PlaceUseOut(
    @SerialName("place_id") val placeId: Long = 0,
    @SerialName("use_count") val useCount: Int = 0,
    @SerialName("auto_added") val autoAdded: Boolean = false,
)

/**
 * 改共享地址（**只有派单员**）：只放点名的键 —— `null` = 这个字段不动。
 *
 * ⚠️ **坐标刻意不在里面**：改坐标等于把一条别人核对过的导航信息指到另一个地方，
 * 司机照着走就是错的。位置不对就删掉重新录一个点。
 */
@Serializable
data class PlaceUpdateRequest(
    val name: String? = null,
    @SerialName("detail_address") val detailAddress: String? = null,
)

/** 「撤销共享地址」的答复：撤下来的那一条落在**我的地点**里的编号（`created`=是不是新建的）。 */
@Serializable
data class PlaceDemoteOut(
    @SerialName("place_id") val placeId: Long = 0,
    @SerialName("location_id") val locationId: Long = 0,
    val created: Boolean = false,
)

/**
 * 司机到场补导航信息的入参。
 *
 * 只有**原本没有坐标**的订单能补（后端会 400 挡掉覆盖），
 * 因为司机到的地方不一定是收货点 —— 把货主确认过的坐标改错比没有坐标更危险。
 */
@Serializable
data class OrderNavigationBody(
    @SerialName("address_lat") val addressLat: String,
    @SerialName("address_lng") val addressLng: String,
    /** 地点名（选填）：货主地点库里显示的就是它；留空则用订单原有的收货地址。 */
    val name: String = "",
    /** 顺带把文字地址补/改掉（选填）：司机在现场往往比下单人更清楚是哪一栋。 */
    @SerialName("detail_address") val detailAddress: String = "",
)

@Serializable
data class LocationCreateRequest(
    val name: String = "",
    @SerialName("detail_address") val detailAddress: String = "",
    val remark: String = "",
    @SerialName("address_lat") val addressLat: String? = null,
    @SerialName("address_lng") val addressLng: String? = null,
    /** 分类名（空 = 未分类）。名册里没有这个名字时后端**自动补进去**（顺手建分类）。 */
    val category: String = "",
    /** 只在**派单员**的请求里有意义；货主传 true 会被后端 403。 */
    @SerialName("is_warehouse") val isWarehouse: Boolean = false,
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
    /**
     * 这一笔挂在**谁**名下（注册货主 → 人名/手机号；临时货主 → 那句称呼）。
     *
     * ⚠️ 后端 2026-09-19 才补下发的字段。在此之前「订单账」那一栏只能拿 [tempShipperName] 显示，
     * 于是**注册货主**的账全被写成「临时货主」——名字根本没下发，界面上看不出来是缺数据。
     * 老后端没有这个字段 → null → 才退回原来那句（过渡，不是长期口径）。
     */
    @SerialName("shipper_name") val shipperName: String? = null,
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
    /** 注册货主的手机号（临时货主为 null）。没有它 → **同名不同人分不开**、按手机号搜不了。 */
    val phone: String? = null,
    /** 这个账号还能不能登录（停用/已删除都算 false）。 */
    //  ⚠️ 默认 **true**：字段缺席 = 老后端没这个字段，那时把每个货主都标成「已停用」
    //     是凭空造出来的状态；真正的"已停用"由后端显式回 false。
    @SerialName("is_active") val isActive: Boolean = true,
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

// ===== AI 附件：上传表格文件 → 服务器读成文本表格 =====

/**
 * 服务器读出来的一张表。
 *
 * `rowCount` 是**截断前**的真实行数：一张 500 行的表只读回 200 行时，
 * 用户和模型都必须知道"这表其实有 500 行"，否则会拿半张表算出一个看起来对的结论。
 */
@Serializable
data class SheetTableDto(
    val name: String = "",
    val rows: List<List<String>> = emptyList(),
    @SerialName("row_count") val rowCount: Int = 0,
    @SerialName("col_count") val colCount: Int = 0,
    val truncated: Boolean = false,
)

@Serializable
data class SheetParseDto(
    val filename: String = "",
    /** xlsx | text | tsv */
    val kind: String = "text",
    val tables: List<SheetTableDto> = emptyList(),
    /** 一定要让用户看到的话：编码是猜的、行被截断了、有工作表没读…… */
    val warnings: List<String> = emptyList(),
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
data class NotificationBatchDeleteRequest(
    val ids: List<Long> = emptyList(),
    val all: Boolean = false,
)

@Serializable
data class BatchDeleteResultDto(val deleted: Int = 0)

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

/**
 * 价格变更通知（派单员改了价之后通知受影响货主）。
 *
 * 后端会**自己拼标题与正文**（"商品价格调整：X" / "…已更新：旧 → 新"），
 * 所以这里传的是结构化数据，不是文案——AI 也不该自己编一段价格通知的措辞。
 */
@Serializable
data class PriceChangeNotifyRequest(
    @SerialName("shipper_ids") val shipperIds: List<Long>,
    @SerialName("product_id") val productId: Long,
    @SerialName("product_name") val productName: String,
    /** `default` = 默认价；其它值后端按"特殊价"（批发商专属价）处理。 */
    @SerialName("price_type") val priceType: String = "default",
    @SerialName("new_price") val newPrice: String,
    @SerialName("old_price") val oldPrice: String? = null,
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
    val unit: String = "件",
    /**
     * 商品分类（如 饮料/粮油/日化）：选品页左侧导航按它分组。
     * 空串 = 「未分类」——老数据全部在这一档，界面要能优雅显示，不是错误。
     */
    val category: String = "",
    @SerialName("low_stock_alert") val lowStockAlert: Int = 0,
)

// ===== 商品分类名册 =====
/**
 * 商品分类名册里的一行（**顺序由派单员定**，不是按商品数推出来的）。
 *
 * 与 `ProductDto.category` 的关系：名册管**顺序**，商品上的字符串管**归属**。
 * 名册里没有的分类名不是错误（老数据），选品页会把它排到名册后面。
 */
@Serializable
data class ProductCategoryDto(
    val id: Long,
    val name: String,
    @SerialName("sort_order") val sortOrder: Int = 0,
    /** 这个分类下在用的商品数（删之前要让人看见"有多少商品挂在这一类"）。 */
    @SerialName("product_count") val productCount: Int = 0,
)

@Serializable
data class ProductCategoryCreateRequest(
    val name: String,
    @SerialName("sort_order") val sortOrder: Int? = null,
)

@Serializable
data class ProductCategoryUpdateRequest(
    val name: String? = null,
    @SerialName("sort_order") val sortOrder: Int? = null,
)

/** 整份顺序一次提交：`ids[0]` 排最前。只传一部分会被后端拒绝（见接口注释）。 */
@Serializable
data class ProductCategoryReorderRequest(val ids: List<Long>)

// ===== 商品可见范围（白名单）=====
/**
 * 某个货主/批发商能看到哪些商品。
 *
 * `scope = all`（默认）= 不限制；`scope = custom` = **只给他看 `productIds` 里勾选的**。
 * ⚠️ 默认必须是 `all`：老账号没有配置，如果默认当成"白名单为空 = 什么都看不到"，
 * 一上线所有人打开选品页都是空的 —— 这类"默认把功能关掉"的迁移是灾难性的。
 */
@Serializable
data class ProductVisibilityDto(
    val scope: String = "all",
    @SerialName("product_ids") val productIds: List<Long> = emptyList(),
)

@Serializable
data class ProductVisibilityRequest(
    val scope: String,
    @SerialName("product_ids") val productIds: List<Long> = emptyList(),
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
/**
 * 成本价的**一段生效区间**（用户 2026-09-19 要求的成本价时间轴）。
 *
 * 一个商品的多行 = 一条时间轴：每行是"某个价从这一刻到那一刻有效"，
 * `effectiveTo == null` 的那一行 = **当前生效价**。
 *
 * ⚠️ 两个时间都是 **UTC**（后端全库同基准），显示前必须走 `formatDateTime`
 * （它会把 naive UTC 换算到设备时区；直接打印会早 8 小时）。
 */
@Serializable
data class ProductCostHistoryDto(
    val id: Long,
    /** 这一段区间内的单位成本（Numeric(14,4)，字符串形式） */
    @Serializable(with = FlexibleStringSerializer::class) @SerialName("cost_price")
    val costPrice: String = "0",
    @SerialName("effective_from") val effectiveFrom: String = "",
    /** null = 这一段**还在生效中** */
    @SerialName("effective_to") val effectiveTo: String? = null,
    /** CREATE=建商品时填的 / PURCHASE=进货带进来的 / MANUAL=编辑里改的 / BACKFILL=老数据回填 */
    val source: String = "MANUAL",
    /** 进货带进来的那条库存流水（本页只用它显示「哪次进货」这个来源标签） */
    @SerialName("movement_id") val movementId: Long? = null,
)

@Serializable
data class InventoryMovementDto(
    val id: Long,
    @SerialName("product_id") val productId: Long,
    val change: Int,
    val note: String = "",
    @SerialName("operator_id") val operatorId: Long = 0,
    @SerialName("created_at") val createdAt: String = "",
    val source: String = "MANUAL",
    @SerialName("order_id") val orderId: Long? = null,
    @SerialName("order_no") val orderNo: String? = null,
    val status: String = "COMMITTED",
    /** 这一批的进货单价（只有手工入库且填了才有值）；null = 没填。 */
    @SerialName("unit_cost")
    @Serializable(with = NullableFlexibleStringSerializer::class)
    val unitCost: String? = null,
)

@Serializable
data class InventoryMovementCreateRequest(
    @SerialName("product_id") val productId: Long,
    val change: Int,
    val note: String = "",
    /**
     * 本次**进货价**（选填，只在入库时有意义）。
     *
     * 用户 2026-09-19：「成本价也是可以进行调整的，包括进货的时候也要输入成本价，
     * 因为可能这个时间的进货和那个时间进货的成本价是不一样的」。
     *
     * 填了后端做**两件**事（同一事务）：① 这个价**记在流水上**（`inventory_movements.unit_cost`）
     * —— 毛利率的「入库加权平均进货价」就是从它算的；② 把商品的 `cost_price` 更新成它，
     * 并往成本价时间轴里开一段新区间（`product_cost_history`）。
     * 不填就只动库存、不碰成本。
     * ⚠️ 它不是"这批货的成本"（不做 FIFO / 分批结转）—— 那件事没做，别这么说。
     */
    @SerialName("unit_cost")
    @Serializable(with = NullableFlexibleStringSerializer::class)
    val unitCost: String? = null,
)

@Serializable
data class InventorySummaryItemDto(
    @SerialName("product_id") val productId: Long,
    @SerialName("product_name") val productName: String,
    val stock: Int,
    val unit: String = "件",
    @SerialName("low_stock_alert") val lowStockAlert: Int = 0,
    val reserved: Int = 0,
    //: 商品分类（库存页左侧导航条按它分组）。空串 = 未分类，与 `ProductDto.category` 同判据。
    val category: String = "",
)

// ===== 通用响应 =====
@Serializable
data class ApiErrorResponse(val detail: String = "")

@Serializable
data class AppVersionDto(
    val version: String? = null,
    val url: String? = null,
    val note: String? = null,
    /**
     * 服务端 version.json 里的安卓 versionCode。**判新旧必须用它**：
     * 版本名是字符串，"1.0.0.9" > "1.0.0.10" 会比错；而且安卓自己就是按 versionCode
     * 决定要不要装——名字看着更新、versionCode 却更小的话，用户下完只会看到安装失败。
     * 字段可能缺失（旧版 version.json 没有），缺了才退回用版本名比。
     */
    val versionCode: Int? = null,
)

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
    // 报表中心 v2：成本/毛利/货损/资金
    // ⚠️ 毛利 = `cost_covered_amount − cost_total`（**两侧同一批行**：只有算得出成本的行），
    //    2026-09-19 审计 R13-R1 修：界面原来用 `total_amount − cost_total`（全部行的金额 − 只有
    //    成本行的成本），同一个月实测 72,177.75 vs 正确 10,789.00 —— 差 6.7 倍。
    // ⚠️ 成本口径 2026-09-19 又换过一次（用户要求）：不再用订单行的 cost_price_snapshot
    //    （"下单那一刻的最新进货价"，进货价一涨就把旧库存的毛利压低），改成**入库流水的
    //    加权平均进货价**。唯一实现在后端 `services/cost_basis.py`。
    @Serializable(with = FlexibleStringSerializer::class) @SerialName("cost_total") val costTotal: String = "0",
    @Serializable(with = FlexibleStringSerializer::class) @SerialName("cost_covered_amount")
    val costCoveredAmount: String = "0",
    @SerialName("total_lines") val totalLines: Int = 0,
    @SerialName("cost_covered_lines") val costCoveredLines: Int = 0,
    //: 算得出成本的行里，有多少行用的是"入库加权平均进货价"、有多少行退回了"下单时的成本价"
    //  （老后端不下发 → 都是 0 → 说明文字自动退回不带区分的写法，不会说假话）
    @SerialName("cost_avg_lines") val costAvgLines: Int = 0,
    @SerialName("cost_snapshot_lines") val costSnapshotLines: Int = 0,
    @SerialName("damage_qty") val damageQty: Int = 0,
    @Serializable(with = FlexibleStringSerializer::class) @SerialName("damage_amount") val damageAmount: String = "0",
    @Serializable(with = FlexibleStringSerializer::class) @SerialName("collected") val collected: String = "0",
    @Serializable(with = FlexibleStringSerializer::class) @SerialName("arrears_total") val arrearsTotal: String = "0",
    @SerialName("cancelled_orders") val cancelledOrders: Int = 0,
    @SerialName("arrears_units") val arrearsUnits: List<ReportArrearsUnitDto> = emptyList(),
)

@Serializable
data class ReportArrearsUnitDto(
    val name: String = "",
    @Serializable(with = FlexibleStringSerializer::class) val amount: String = "0",
)

@Serializable
data class ProductReportItemDto(
    @SerialName("product_name") val productName: String = "",
    val qty: Int = 0,
    @Serializable(with = FlexibleStringSerializer::class) val amount: String = "0",
    @SerialName("order_count") val orderCount: Int = 0,
    @Serializable(with = FlexibleStringSerializer::class) val cost: String = "0",
    @SerialName("damage_qty") val damageQty: Int = 0,
    @Serializable(with = FlexibleStringSerializer::class) @SerialName("damage_amount") val damageAmount: String = "0",
    // 参与毛利的金额（只有带成本快照的行）与行数 —— 2026-09-19 审计第十七轮：
    // 没有它们，逐行毛利只能拿**全额**收入减成本（本机实测逐行合计 72,177.75，正确 10,789 量级）。
    // 老后端不下发这两个字段 → null → 界面回落到"有成本才算毛利"的老口径（过渡，不是长期口径）。
    @Serializable(with = FlexibleStringSerializer::class) @SerialName("covered_amount") val coveredAmount: String? = null,
    @SerialName("covered_lines") val coveredLines: Int? = null,
)

@Serializable
data class ProductReportDto(
    @SerialName("period_label") val periodLabel: String = "",
    @SerialName("total_qty") val totalQty: Int = 0,
    @Serializable(with = FlexibleStringSerializer::class) @SerialName("total_amount") val totalAmount: String = "0",
    val items: List<ProductReportItemDto> = emptyList(),
    @Serializable(with = FlexibleStringSerializer::class) @SerialName("cost_total") val costTotal: String = "0",
    @SerialName("damage_qty") val damageQty: Int = 0,
    @Serializable(with = FlexibleStringSerializer::class) @SerialName("damage_amount") val damageAmount: String = "0",
    @SerialName("total_lines") val totalLines: Int = 0,
    @SerialName("cost_covered_lines") val costCoveredLines: Int = 0,
    @Serializable(with = FlexibleStringSerializer::class) @SerialName("cost_covered_amount") val costCoveredAmount: String? = null,
    //: 口径区分（同 TurnoverReportDto 的说明）：入库加权平均进货价多少行 / 退回下单成本价多少行
    @SerialName("cost_avg_lines") val costAvgLines: Int = 0,
    @SerialName("cost_snapshot_lines") val costSnapshotLines: Int = 0,
)

@Serializable
data class DriverPerformanceRowDto(
    @SerialName("driver_id") val driverId: Long = 0,
    @SerialName("driver_name") val driverName: String = "",
    @SerialName("completed_count") val completedCount: Int = 0,
    @SerialName("on_time_rate") val onTimeRate: Double? = null,
    @SerialName("avg_delivery_seconds") val avgDeliverySeconds: Double? = null,
    @SerialName("photo_upload_rate") val photoUploadRate: Double = 0.0,
    @SerialName("billing_mode") val billingMode: String? = null,
    @Serializable(with = FlexibleStringSerializer::class) @SerialName("freight_owed") val freightOwed: String? = null,
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

@Serializable
data class OperationLogDto(
    val id: Long = 0,
    @SerialName("operator_id") val operatorId: Long = 0,
    @SerialName("order_id") val orderId: Long? = null,
    val action: String = "",
    @SerialName("change_content") val changeContent: String? = null,
    @SerialName("created_at") val createdAt: String = "",
    // 审计页要回答「谁改的、哪一单」——只给 operator_id/order_id 用户看不懂（v3.29 后端已补）。
    @SerialName("operator_name") val operatorName: String? = null,
    @SerialName("order_no") val orderNo: String? = null,
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

// ===== 司机计费规则模板 =====

/**
 * 一份**可命名**的司机计费规则：固定工资 + 每单/每件 + 提成，三件可任意组合。
 *
 * ### 为什么 `summary` 必须用后端给的那句
 * 它是 `services/driver_pay.py::PayRule.describe()` 算出来的（"每单 300.00 元 + 运费的 5%"）。
 * 界面若自己按字段再拼一遍，两处文案迟早分叉——而分叉的那天用户看到的是
 * "列表说每单 200、账单按 5% 算"，谁也不知道该信哪个。所以这里只**显示** `summary`。
 *
 * ### 金额一律 String
 * 后端 `Numeric` 出参是**字符串**（Pydantic v2 的 Decimal 序列化）。
 * 而且本项目的 Json 配了 `coerceInputValues = true`：字段类型写 Double 时，
 * 数字型 JSON 之外的输入会被**静默替换成默认值** —— 金额静默变 0 是查不出来的那种错。
 */
@Serializable
data class DriverBillingRuleDto(
    val id: Long = 0,
    val name: String = "",
    /** small/large/trailer；null = 通用（不限车型）。 */
    @SerialName("vehicle_type") val vehicleType: String? = null,
    @Serializable(with = FlexibleStringSerializer::class) val salary: String = "0",
    @SerialName("piece_amount") @Serializable(with = FlexibleStringSerializer::class) val pieceAmount: String = "0",
    /** order = 每单/每车；item = 每件。 */
    @SerialName("piece_unit") val pieceUnit: String = "order",
    /** none = 不提成；freight = 按运费；goods = 按商品金额。 */
    @SerialName("commission_base") val commissionBase: String = "none",
    // ⚠️ `@SerialName` 不能省（2026-09-19 审计抓到的真缺陷）：后端出参键名是 `commission_rate`，
    //    少了这一行 → `ApiClient.ignoreUnknownKeys = true` 把它当未知键**静默丢掉** →
    //    提成比例永远读成默认 "0"。后果链：计费规则编辑页回填空白 → 想只改备注会被自己的校验拦住 →
    //    用户唯一出路是把提成基数改成「不提成」→ **真提成被清成 0，挂着它的司机从此少拿钱**；
    //    而且 AI 的撤回快照读的是同一个 DTO，会让「撤回」把 5% 写回成 0%。
    @SerialName("commission_rate")
    @Serializable(with = FlexibleStringSerializer::class) val commissionRate: String = "0",
    /** 只对哪些商品抽成（空 = 不限）。 */
    @SerialName("commission_product_ids") val commissionProductIds: List<Long> = emptyList(),
    /** 上面那些商品叫什么（后端给，界面不用再查一次商品库）。 */
    @SerialName("commission_product_names") val commissionProductNames: List<String> = emptyList(),
    val remark: String = "",
    /** 后端算好的一句话（见类注释，**不要自己拼**）。 */
    val summary: String = "",
    /** 有几个司机挂着它 —— 删之前要让人看见"还有 3 个人在用"。 */
    @SerialName("attached_count") val attachedCount: Int = 0,
    @SerialName("is_deleted") val isDeleted: Boolean = false,
    @SerialName("created_at") val createdAt: String? = null,
)

/**
 * 新建与修改**共用**的提交体；字段**全部可空**，两种语义靠"传什么"区分：
 *
 * | 想表达 | 传什么 | 为什么 |
 * | --- | --- | --- |
 * | 这一项**不改** | `null` | 本项目 Json 是 `explicitNulls = false`（`core/ApiClient.kt:31`）：null 字段被**整个省略**，后端 `PUT` 的 `exclude_unset=True` 就不动它 |
 * | 改成**通用车型** | `vehicle_type = ""` | 空串进后端被 `or None` 归成"不限车型"（`api/v1/driver_billing_rules.py`），而 `null` 只会被省略、改不掉原来那句 |
 * | 改成 **0** | `salary = "0"` | 后端对 `None` 的解释是"不改"，对 `"0"` 才是"归零"——两者不是一回事 |
 *
 * 所以：AI 侧做部分更新时**只传点名的键**（其余留 null）,界面则是"用当前值预填 → 发全字段"，
 * 两边都不需要用 `null` 去表达"清空"。
 *
 * 金额用 `String?` 而不是 `Double`：后端是 `Decimal`，浮点会在这里悄悄丢分；
 * 请求侧不再挂自定义序列化器——那个 `FlexibleStringSerializer` 是给**解析**后端
 * "数字或字符串"两种出参用的，而这份 DTO 只会被**编码**出去。
 */
@Serializable
data class DriverBillingRuleRequest(
    val name: String? = null,
    @SerialName("vehicle_type") val vehicleType: String? = null,
    val salary: String? = null,
    @SerialName("piece_amount") val pieceAmount: String? = null,
    @SerialName("piece_unit") val pieceUnit: String? = null,
    @SerialName("commission_base") val commissionBase: String? = null,
    @SerialName("commission_rate") val commissionRate: String? = null,
    /** 抽成范围（商品编号）。null = 不改；空列表 = 改成"不限商品"。 */
    @SerialName("commission_product_ids") val commissionProductIds: List<Long>? = null,
    val remark: String? = null,
)

/**
 * 把规则挂给司机 / 解挂（`POST /driver-billing-rules/attach`）。
 *
 * `ruleId = null` = 解挂（他会退回按车型/工资的老口径，后端会在操作日志里写明退回什么）。
 * 注意 `ruleId = null` 会因为 `explicitNulls = false` 被**省略**——正好等价于后端
 * `AttachRuleBody.rule_id` 的默认 `None`，所以解挂路径是通的。
 */
@Serializable
data class DriverBillingRuleAttachRequest(
    @SerialName("driver_id") val driverId: Long,
    @SerialName("rule_id") val ruleId: Long? = null,
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
    /** 司机手机号（去软删后缀）。与货主/批发商账同一套：账本要能按**名称/电话/后 4 位**认人。 */
    @SerialName("driver_phone") val driverPhone: String? = null,
    /** 这个司机账号还能不能登录。 */
    //  ⚠️ 默认 **true**：字段缺席只可能是"老后端没这个字段"，那时把每个司机都标成
    //     「已停用」是一条**凭空造出来的状态**（比"少显示一个标记"糟得多）。
    //     真正的"账号不存在/已停用"由后端**显式**回 false。
    @SerialName("driver_active") val driverActive: Boolean = true,
    val count: Int = 0,
    val total: Double = 0.0,
    val orders: List<FreightSettlementOrderDto> = emptyList(),
)

@Serializable
data class FreightSettlementOrderDto(
    @SerialName("order_id") val orderId: Long = 0,
    @SerialName("order_no") val orderNo: String = "",
    @SerialName("delivered_at") val deliveredAt: String? = null,
    // ⚠️ 这里**必须是可空 String**（2026-09-19 审计）：后端对"还没定价"的单明确回 `null`，
    //    而 `ApiClient.coerceInputValues = true` 会把 null 洗成非空字段的默认值 ""，
    //    `formatMoney("")` 又返回 "0.00" → 结算页那一行显示「¥0.00」而不是「待定价」
    //    （界面里 `if (freightFee != null)` 那个 else 分支在非空类型上恒为死代码）。
    //    后果：需要补价的单失去唯一提示 → 运费漏结。
    @SerialName("freight_fee") val freightFee: String? = null,
    // ⛔ 这三个是**司机应得**（后端 `driver_pay.pay_for_order` 算的，与司机账单同源）。
    //    以前 DTO 里没有它们，于是客户端拿 `freight_fee`（货主运费）当"司机该拿多少"自己求和 →
    //    司机端「我的账本」合计与司机账单对不上（账单 675 / 司机端 1500），两边都不报错。
    @SerialName("pay_total") val payTotal: String = "0",
    @SerialName("pay_piece") val payPiece: String = "0",
    @SerialName("pay_commission") val payCommission: String = "0",
    @SerialName("delivery_description") val deliveryDescription: String = "",
    @SerialName("address_detail") val addressDetail: String = "",
)


// ===================== 账本 V2（P0）=====================
@Serializable
data class DamageItem(
    @SerialName("order_product_id") val orderProductId: Long,
    val quantity: Int = 0,
)

@Serializable
data class CustomerCreateRequest(
    val kind: String = "tmp",
    @SerialName("user_id") val userId: Long? = null,
    val name: String,
    val phone: String? = null,
    @SerialName("is_member") val isMember: Boolean = false,
    @SerialName("arrears_unit_id") val arrearsUnitId: Long? = null,
)

@Serializable
data class CustomerDto(
    val id: Long,
    val kind: String = "tmp",
    @SerialName("user_id") val userId: Long? = null,
    val name: String = "",
    val phone: String? = null,
    @SerialName("is_member") val isMember: Boolean = false,
    @SerialName("arrears_unit_id") val arrearsUnitId: Long? = null,
)

@Serializable
data class DriverBillDto(
    val id: Long,
    @SerialName("driver_id") val driverId: Long = 0,
    @SerialName("bill_type") val billType: String = "",
    @SerialName("order_id") val orderId: Long? = null,
    val month: String = "",
    @Serializable(with = FlexibleStringSerializer::class) val amount: String = "0",
    val status: String = "open",
    @SerialName("settled_doc_id") val settledDocId: Long? = null,
    @SerialName("driver_name") val driverName: String? = null,
    @SerialName("order_no") val orderNo: String? = null,
)

@Serializable
data class DriverBillGenerateRequest(
    @SerialName("driver_id") val driverId: Long? = null,
    val month: String,
    @SerialName("bill_type") val billType: String = "salary",
)

@Serializable
data class ReceiptCreateRequest(
    @SerialName("customer_id") val customerId: Long,
    @Serializable(with = FlexibleStringSerializer::class) val amount: String,
    val method: String = "cash",
    @SerialName("received_at") val receivedAt: String,
    @SerialName("order_ids") val orderIds: List<Long> = emptyList(),
    @SerialName("settle_mode") val settleMode: String = "itemized",
    @SerialName("arrears_unit_id") val arrearsUnitId: Long? = null,
    val note: String = "",
)

@Serializable
data class ReceiptDto(
    val id: Long,
    @SerialName("customer_id") val customerId: Long = 0,
    @Serializable(with = FlexibleStringSerializer::class) val amount: String = "0",
    val method: String = "",
    @SerialName("received_at") val receivedAt: String = "",
    @SerialName("order_ids") val orderIds: List<Long> = emptyList(),
    @SerialName("customer_name") val customerName: String? = null,
)

@Serializable
data class SettlementCreateRequest(
    @SerialName("driver_id") val driverId: Long,
    @SerialName("settle_type") val settleType: String = "piece",
    val month: String,
    @Serializable(with = FlexibleStringSerializer::class) val amount: String? = null,
    val note: String = "",
)

@Serializable
data class SettlementActionRequest(
    val action: String,
    val method: String = "cash",
)

@Serializable
data class SettlementDto(
    val id: Long,
    @SerialName("driver_id") val driverId: Long = 0,
    @SerialName("settle_type") val settleType: String = "",
    val month: String = "",
    @Serializable(with = FlexibleStringSerializer::class) val amount: String = "0",
    val status: String = "draft",
    @SerialName("driver_name") val driverName: String? = null,
    @SerialName("order_ids") val orderIds: List<Long>? = null,
    @SerialName("paid_at") val paidAt: String? = null,
    val method: String = "",
)

@Serializable
data class ExpenseCreateRequest(
    @SerialName("exp_date") val expDate: String,
    val category: String,
    @Serializable(with = FlexibleStringSerializer::class) val amount: String,
    @SerialName("driver_id") val driverId: Long? = null,
    @SerialName("vehicle_id") val vehicleId: Long? = null,
    @SerialName("order_id") val orderId: Long? = null,
    val note: String = "",
)

@Serializable
data class ExpenseDto(
    val id: Long,
    @SerialName("exp_date") val expDate: String = "",
    val category: String = "",
    @Serializable(with = FlexibleStringSerializer::class) val amount: String = "0",
    @SerialName("driver_id") val driverId: Long? = null,
    @SerialName("order_id") val orderId: Long? = null,
    @SerialName("driver_name") val driverName: String? = null,
    @SerialName("order_no") val orderNo: String? = null,
    val note: String = "",
)

/**
 * 资金流水的**服务端汇总**（`GET /cash-flows/summary`）。
 *
 * ⚠️ 为什么要服务端算（2026-09-19 审计）：客户端原来"拉一页流水自己求和"，
 * 而列表有 `limit`（默认 200）。实测同一窗口：默认只拿 200 条 → 流入 ¥18,842；
 * limit=1000 → 273 条 → 流入 ¥48,905.50（页面少算 62%），而同一页 Excel 导出是 SQL 侧
 * 全窗口求和（真值）→ "页面一个数、导出一个数"。金额必须在库里算完。
 */
@Serializable
data class CashFlowSummaryDto(
    val income: String = "0",
    val expense: String = "0",
    val net: String = "0",
    val count: Int = 0,
)

@Serializable
data class CashFlowDto(
    val id: Long,
    @SerialName("flow_date") val flowDate: String = "",
    val direction: String = "",
    @Serializable(with = FlexibleStringSerializer::class) val amount: String = "0",
    @SerialName("party_type") val partyType: String = "",
    @SerialName("biz_type") val bizType: String = "",
    @SerialName("party_name") val partyName: String? = null,
    @SerialName("order_id") val orderId: Long? = null,
)

@Serializable
data class VehicleCreateRequest(
    @SerialName("plate_no") val plateNo: String,
    @SerialName("vehicle_type") val vehicleType: String = "",
    @SerialName("driver_id") val driverId: Long? = null,
)

/**
 * 改车辆（`PATCH /vehicles/{id}`）：**只传要改的键**，没传的后端不动。
 *
 * 两条语义（v3.44 修好之后，`api/v1/vehicles.py::update_vehicle`）：
 * 1. `driverId = null` 是"不动司机"（本 DTO 里 null 会被 `explicitNulls = false` 丢掉）；
 *    **解绑要走 `POST /vehicles/{id}/driver`**（见 [VehicleDriverSetRequest]）。
 * 2. 车牌**查重了**，且会排除自己——所以"只改车型也带上同一个车牌"不会再自己撞自己。
 */
@Serializable
data class VehicleUpdateRequest(
    @SerialName("plate_no") val plateNo: String? = null,
    @SerialName("vehicle_type") val vehicleType: String? = null,
    @SerialName("driver_id") val driverId: Long? = null,
    @SerialName("is_active") val isActive: Boolean? = null,
)

/**
 * 绑司机 / 解绑（`POST /vehicles/{id}/driver`）。
 *
 * ⚠️ `driverId = null` 序列化之后**这个键会消失**（`ApiClient.json` 里
 * `explicitNulls = false`），而后端的契约正好是"缺省或 null 都 = 解绑"——
 * 两边对得上，这不是巧合：这条接口就是照这个约束设计的。
 * （`PATCH` 上做不到这件事：那边"没传"和"传 null"必须能分开，见 [VehicleUpdateRequest]。）
 */
@Serializable
data class VehicleDriverSetRequest(
    @SerialName("driver_id") val driverId: Long? = null,
)

@Serializable
data class VehicleDto(
    val id: Long,
    @SerialName("plate_no") val plateNo: String = "",
    @SerialName("vehicle_type") val vehicleType: String = "",
    @SerialName("driver_id") val driverId: Long? = null,
    @SerialName("driver_name") val driverName: String? = null,
    @SerialName("is_active") val isActive: Boolean = true,
)