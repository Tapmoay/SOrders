package com.tapmoay.sorders.ai

import com.tapmoay.sorders.data.remote.dto.ExpenseCreateRequest
import com.tapmoay.sorders.data.remote.dto.LedgerCreateRequest
import com.tapmoay.sorders.data.remote.dto.OrderCreateRequest
import com.tapmoay.sorders.data.remote.dto.OrderProductLine
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull

// ⚠️ 2026-09-25（整改报告 §11 第 2 步）：下面这一块是**从 `AiWriteService.kt` 原样搬过来的**（同一个包，一个字没改）。
// 理由：它是**独立的一块职责**（payload JSON → 请求 DTO），与写闸门的判定逻辑没有任何耦合；
// 而 `AiWriteService.kt` 里那三块职责（数据源 / 写闸门 / DTO 转换）混在一起，改哪一块都要在 2300 行里找。
// ⏔ 搬迁的顺序：**先让判据读并集、再搬**（否则每搬一块就要改一打判据，改漏一个就是“静默不查”）。
// --------------------------------------------------------- payload → 请求体
//
// 这一层是刻意单独放的：payload 是**用户在卡片上看过的那份 JSON**，
// 转成 DTO 的过程里**只允许做类型转换，不允许再补默认值或再算一次**。
// 一旦这里出现"顺手补一个 xxx"，卡片和实际写入就又变成两条路径了。

internal fun JsonObject.toExpenseRequest() = ExpenseCreateRequest(
    expDate = pReqStr("exp_date"),
    category = pReqStr("category"),
    amount = pReqStr("amount"),
    driverId = pLong("driver_id"),
    vehicleId = pLong("vehicle_id"),
    orderId = null,
    note = pStr("note").orEmpty(),
)

internal fun JsonObject.toLedgerRequest() = LedgerCreateRequest(
    shipperId = pLong("shipper_id"),
    tempShipperName = pStr("temp_shipper_name"),
    entryDate = pReqStr("entry_date"),
    productName = pReqStr("product_name"),
    quantity = pStr("quantity")?.toIntOrNull() ?: 1,
    unitPrice = pReqStr("unit_price"),
    total = pReqStr("total"),
    source = "manual",
    note = pStr("note").orEmpty(),
)

internal fun JsonObject.toOrderCreateRequest(): OrderCreateRequest {
    val lines = (this["lines"] as? JsonArray).orEmpty().mapNotNull { el ->
        val o = el as? JsonObject ?: return@mapNotNull null
        OrderProductLine(
            productId = o.pLong("product_id"),
            productNameSnapshot = o.pStr("product_name_snapshot").orEmpty(),
            quantity = o.pStr("quantity")?.toIntOrNull() ?: 1,
            unitPrice = o.pStr("unit_price") ?: "0",
            lineTotal = o.pStr("line_total") ?: "0",
        )
    }
    return OrderCreateRequest(
        lines = lines,
        orderDate = pStr("order_date"),
        deliveryDescription = "",
        addressDetail = pStr("address_detail").orEmpty(),
        // 坐标由 CreateOrderHandler 在 prepare 里查高德拿到（查不到就是 null：
        // 订单照建，只是司机的「高德导航」要自己搜一遍地址——卡片上写明了这一点）。
        addressLat = pStr(GEO_LAT),
        addressLng = pStr(GEO_LNG),
        contactDongjiaPhone = pStr("contact_dongjia_phone").orEmpty(),
        contactBossPhone = pStr("contact_boss_phone").orEmpty(),
        contactDongjiaName = pStr("contact_dongjia_name").orEmpty(),
        contactBossName = pStr("contact_boss_name").orEmpty(),
        remark = pStr("remark").orEmpty(),
        shipperId = pLong("shipper_id"),
        tempShipperName = pStr("temp_shipper_name"),
    )
}

private fun JsonObject.pStr(key: String): String? =
    (this[key] as? JsonPrimitive)?.contentOrNull?.takeIf { it.isNotBlank() }

private fun JsonObject.pLong(key: String): Long? =
    (this[key] as? JsonPrimitive)?.contentOrNull?.toLongOrNull()

private fun JsonObject.pReqStr(key: String): String =
    pStr(key) ?: error("payload 缺少必填字段 $key（App 内部错误，不该发生）")
