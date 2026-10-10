package com.tapmoay.sorders.ai

import com.tapmoay.sorders.data.remote.dto.ExpenseCreateRequest
import com.tapmoay.sorders.data.remote.dto.LedgerCreateRequest
import com.tapmoay.sorders.data.remote.dto.OrderCreateRequest
import com.tapmoay.sorders.data.remote.dto.PurchaseOrderDto
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import kotlinx.serialization.json.putJsonArray
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.LocalDate

/**
 * 写操作链路（[AiWriteService] + [AiWritePreviewStore] + [AiWrites]）的纯逻辑测试。
 *
 * ### 为什么这个文件比别的测试更要紧
 * 前几个功能出错，最坏是"答得不好"——用户看两眼就发现不对劲。
 * 这一个出错是**把数据写错**：账记到别人头上、金额多三个零、同一笔记两次。
 * 这些错误**不会报错、不会崩**，只会在月底对账时冒出来，而且很难倒查是谁写进去的。
 *
 * 所以这里钉的不是"功能通不通"，是四件**必须永远成立**的事：
 * 1. 一个 token 只能写一次（连点两下不会写两笔）；
 * 2. 名字对不上/对上多个 → **拒绝**，绝不猜（错误信息里只许有名字，不许有编号）；
 * 3. 参数越界（0 元、负数、多打了零）→ **拒绝**，而不是照写；
 * 4. 卡片上写的东西 == 真正发给后端的东西（用**同一份 payload**，不是两条路径）。
 */
class AiWriteTest {

    // ============================================================ 测试替身

    private class FakeDs : AiWriteDataSource {
        // ⚠️ 这一份是**全量司机名册**（结算域也一样按它解析司机）：
        // 工资单的"工资制"名单（salaryDriverRows）只是它的**子集**，
        // 所以这里多一个人（赵德海 14）是必要的——否则"给赵德海建工资单"会得到
        // 「系统里没有这个司机」这种假话（真正的判据是"他不是工资制"）。
        var drivers = listOf(
            AiName(11, "王建国"),
            AiName(12, "王建军"),
            AiName(13, "李强"),
            AiName(14, "赵德海"),
        )
        // 车辆名册带**现在归谁**（v3.44）：真实实现取 `VehicleOut.driver_name`。
        // 「解绑」那张卡上要出现被拿掉的人的名字——只在 label 上做匹配，note 只用于展示。
        var vehicles = listOf(
            AiName(21, "豫A12345", note = "现在：李强"),
            AiName(22, "豫B67890", note = "现在没有司机"),
        )
        var shippers = listOf(AiName(31, "城东水果批发"))
        var products = listOf(AiName(41, "红富士苹果"), AiName(42, "皇冠梨"))
        var units = listOf(AiName(51, "明辉食品商行"))
        var orders = listOf(
            AiOrderRef(61, "SOTEST2026091100230", "城东水果批发", "PENDING_DISPATCH", "测试收货地址 65 号", null, "320.00"),
            AiOrderRef(62, "SOTEST2026091200229", "明辉食品商行", "DISPATCHED", "测试收货地址 4 号", "李强", "704.00"),
        )

        val expenses = mutableListOf<Pair<ExpenseCreateRequest, String?>>()
        val entries = mutableListOf<LedgerCreateRequest>()
        /** 每个订单动作调了几次、带了什么（payload 是否原样落库，靠它证明）。 */
        val orderCalls = mutableListOf<String>()
        val createdOrders = mutableListOf<OrderCreateRequest>()
        var lastAssign: List<Any?>? = null
        /**
         * 司机名册上那句"他现在按什么算钱"（真实实现取自后端 `pay_summary`）。
         * null = 没挂规则——这会影响派单卡片上写出来的那行字，但**判据在后端**
         * （逐单覆盖能不能生效只有 `driver_pay.override_problem` 说了算）。
         */
        var driverNote: String? = null
        var readAllCalls = 0
        var failWith: Exception? = null

        private fun boom() {
            failWith?.let { throw it }
        }

        // 网络/权限失败会打到**这一次预览里的每一个请求**上（名册也要拉），
        // 所以替身的读方法一起吃 failWith —— 只让写方法失败是测不到"预览阶段出错"的。
        override suspend fun drivers() =
            drivers.map { it.copy(note = it.note ?: driverNote) }.also { boom() }
        override suspend fun vehicles() = vehicles.also { boom() }
        /** 查过几次货主名册（`GET /users`）—— 货主那条路**一次都不许有**（对他是 403）。 */
        val searchShipperCalls: MutableList<String> = mutableListOf()

        override suspend fun searchShippers(query: String, limit: Int): List<AiName> {
            searchShipperCalls += query
            return shippers.also { boom() }
        }
        override suspend fun products() = products.also { boom() }
        override suspend fun arrearsUnits() = units.also { boom() }
        // 忠实照抄后端 `GET /orders?q=` 的行为：**模糊匹配**单号/货主/地址，命中几万条也只回这么多。
        // 不做过滤的话，"订单号对不上"这条路径根本测不到（替身会永远回全部订单 → 变成"对上多个"）。
        override suspend fun findOrders(query: String, limit: Int) = orders.filter {
            it.orderNo.contains(query, ignoreCase = true) ||
                it.shipper.contains(query, ignoreCase = true) ||
                it.address.contains(query, ignoreCase = true)
        }.take(limit).also { boom() }

        override suspend fun readAllNotifications(): JsonObject {
            boom()
            readAllCalls++
            return buildJsonObject { put("count", 7) }
        }

        override suspend fun createExpense(req: ExpenseCreateRequest, idempotencyKey: String?) {
            boom()
            expenses += req to idempotencyKey
        }

        override suspend fun createLedgerEntry(req: LedgerCreateRequest) {
            boom()
            entries += req
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
            boom()
            orderCalls += "assign"
            lastAssign = listOf(orderId, driverId, note, freightFee, collectCash, pieceAmount, commissionRate)
        }

        override suspend fun recallOrder(orderId: Long, reason: String) {
            boom()
            orderCalls += "recall:$orderId:$reason"
        }

        override suspend fun cancelOrder(orderId: Long) {
            boom()
            orderCalls += "cancel:$orderId"
        }

        // ---- 订单结构三条（CHG-0085）----
        //
        // 转货的落库记录写成 transfer:<单号>:<目标（编号或临时名）>:<行id>x<件数>,…：
        // 一次调用要同时说清"转给谁"和"转哪几行"，所以两边都在这一行里。
        override suspend fun transferOrderLines(
            orderId: Long,
            shipperId: Long?,
            tempShipperName: String?,
            lines: List<Pair<Long, Int>>,
        ) {
            boom()
            orderCalls += "transfer:$orderId:" + (shipperId?.toString() ?: tempShipperName ?: "?") + ":" +
                lines.joinToString(",") { it.first.toString() + "x" + it.second }
        }

        override suspend fun releaseOrder(orderId: Long, reason: String) {
            boom()
            orderCalls += "release:$orderId:$reason"
        }

        override suspend fun updateOrderContact(orderId: Long, fields: JsonObject) {
            boom()
            orderCalls += "contact:$orderId:" + fields.toString()
        }

        /**
         * 退货（2026-09-20）：可退行由用例摆（[returnLines]），退货调用记进 orderCalls。
         * 与真实现一样是"**先读回可退余量、再按上限校验**"两步，所以这里读方法也吃 `boom()`。
         */
        var returnLines = listOf<AiReturnableLine>()

        override suspend fun returnableLines(orderId: Long): List<AiReturnableLine> =
            returnLines.also { boom() }

        override suspend fun returnOrder(orderId: Long, items: List<Pair<Long, Int>>, note: String) {
            boom()
            orderCalls += "return:$orderId:" +
                items.joinToString(",") { "${it.first}x${it.second}" } +
                (if (note.isBlank()) "" else ":$note")
        }

        // ---- 退货申请（2026-09-21）：货主申请/撤回 + 派单员驳回/办理 ----
        //
        // ⚠️ 替身里**只有一个** `pendingReturn`：这正是后端的真实规则
        //    （一张单同时只允许一条待处理申请），用例靠它验证"已有待办时不许再申请"。
        var pendingReturn: AiReturnRequest? = null
        val appliedReturns = mutableListOf<Triple<Long, List<Pair<Long, Int>>, String>>()
        val withdrawnReturns = mutableListOf<Long>()
        val rejectedReturns = mutableListOf<Pair<Long, String>>()
        val fulfilledReturns = mutableListOf<Long>()

        private fun pendingFor(orderId: Long?): List<AiReturnRequest> {
            val p = pendingReturn ?: return emptyList()
            return if (orderId == null || p.orderId == orderId) listOf(p) else emptyList()
        }

        override suspend fun myReturnRequests(orderId: Long?): List<AiReturnRequest> =
            pendingFor(orderId).also { boom() }

        override suspend fun applyReturnRequest(
            orderId: Long,
            items: List<Pair<Long, Int>>,
            note: String,
        ) {
            boom()
            appliedReturns += Triple(orderId, items, note)
        }

        override suspend fun withdrawReturnRequest(id: Long) {
            boom()
            withdrawnReturns += id
        }

        override suspend fun pendingReturnRequests(orderId: Long?): List<AiReturnRequest> =
            pendingFor(orderId).also { boom() }

        override suspend fun rejectReturnRequest(id: Long, reason: String) {
            boom()
            rejectedReturns += id to reason
        }

        override suspend fun fulfillReturnRequest(id: Long) {
            boom()
            fulfilledReturns += id
        }

        override suspend fun updateFreight(orderId: Long, freightFee: String?) {
            boom()
            orderCalls += "freight:$orderId:$freightFee"
        }

        override suspend fun payOrder(orderId: Long) {
            boom()
            orderCalls += "pay:$orderId"
        }

        override suspend fun chargeOrder(orderId: Long, arrearsUnitId: Long) {
            boom()
            orderCalls += "charge:$orderId:$arrearsUnitId"
        }

        override suspend fun createOrder(req: OrderCreateRequest) {
            boom()
            orderCalls += "create"
            createdOrders += req
        }

        /** 补导航（2026-09-20）：记下"用的是哪一个点的坐标"，用例靠它核对。 */
        override suspend fun fillOrderNavigation(
            orderId: Long,
            lat: String,
            lng: String,
            name: String,
            detail: String,
        ) {
            boom()
            orderCalls += "fillNav:$orderId:$lat,$lng:$name"
        }

        // ---- 订单第二批（v3.16：改单 / 异常 / 拆单 / 批量派单）----
        override suspend fun updateOrder(id: Long, fields: JsonObject) {
            boom()
            orderCalls += "update:$id:${fields.toString()}"
        }

        override suspend fun setOrderException(
            id: Long,
            isException: Boolean,
            reason: String?,
            resolution: String?,
            expectedBefore: String?,
        ) {
            boom()
            orderCalls += "exception:$id:$isException:$reason:$resolution:$expectedBefore"
        }

        override suspend fun resolveOrderException(id: Long, note: String?) {
            boom()
            orderCalls += "resolveException:$id:$note"
        }

        override suspend fun splitOrder(id: Long, parts: List<Int>) {
            boom()
            orderCalls += "split:$id:${parts.joinToString(",")}"
        }

        override suspend fun batchAssignOrders(
            orderIds: List<Long>,
            driverId: Long,
            note: String?,
            collectCash: Boolean?,
        ) {
            boom()
            orderCalls += "batchAssign:${orderIds.joinToString(",")}:$driverId:$note:$collectCash"
        }

        // ---- 账本第二批（v3.17：改/删流水、客户收款、补进账本）----
        var ledgerRows = listOf(
            AiLedgerRef(201, "2026-09-10", "红富士苹果", "320.00", "城东水果批发", "manual", "首批"),
            AiLedgerRef(202, "2026-09-12", "皇冠梨", "120.00", "城东水果批发", "order", "", "SOTEST2026091200229"),
            AiLedgerRef(203, "2026-09-12", "皇冠梨", "130.00", "明辉食品商行", "manual", ""),
        )
        var customerRows = listOf(AiName(301, "老王果行"), AiName(302, "明辉食品商行"))

        /** 每次账本写操作记一行，断言用。 */
        val ledgerCalls = mutableListOf<String>()

        override suspend fun ledgerEntries(
            shipper: String?,
            from: String,
            to: String,
            limit: Int,
        ): List<AiLedgerRef> {
            boom()
            // 忠实照抄生产实现的两条语义：① 货主名对不上 → 空（不是"全给"）；
            // ② 没说货主 → 不收窄（在日期窗口内全找）。这两条正是卡片范围对不对的关键。
            val rows = if (shipper.isNullOrBlank()) {
                ledgerRows
            } else {
                ledgerRows.filter { it.shipper.contains(shipper, ignoreCase = true) }
            }
            return rows.take(limit)
        }

        override suspend fun customers() = customerRows.also { boom() }

        // ---- 货主自己那一本账（批发商核销，2026-09-20）----
        //
        // 这 6 个替身是**接口新增方法时必须补的那一半**：少了它们整个测试源集编译不过
        // （`FakeDs : AiWriteDataSource` 抽象方法没实现），而 885 个单测就一条都跑不出来。
        // 判据与别处一致：读方法也吃 `boom()`（failWith 模拟的是"这一次预览里每个请求都失败"）。

        /** 这个账号是不是批发商货主。测试要验普通货主那条分支时把它设成 false。 */
        var memberShipper: Boolean = true

        /** 我的账本上"查得到"的那些单（按单号匹配）。 */
        var settleOrders: MutableList<AiSettleOrder> = mutableListOf()

        /** 我记过的核销（含已撤销的）。 */
        var mySettlementRows: MutableList<AiMySettlementRef> = mutableListOf()

        /** 核销/撤销/恢复的调用记录（断言"点确认之后真的写了一次"）。 */
        val myLedgerCalls: MutableList<String> = mutableListOf()

        override suspend fun isMemberShipper(): Boolean = memberShipper.also { boom() }

        /**
         * 当前登录角色 key。**默认派单员**（这个替身原来服务的都是代理下单那条路）。
         *
         * ⚠️ 它决定「下单」那条路走哪个分支：货主是**给自己下单**（不查货主名册，
         * `GET /users` 对他是 403），派单员才要查"这单是谁的"。
         */
        var roleKey: String? = "dispatcher"

        override suspend fun currentRoleKey(): String? = roleKey

        /**
         * 当前登录人的**编号**（`users/me` 的 id）。
         *
         * 报价要绑货主（2026-09-22）之后它就有了用处：**货主给自己下单**时后端不收 `shipper_id`，
         * 而专属价挂在他本人这个编号下 —— 所以这里给的就是"他"这个批发商的编号。
         */
        var meId: Long? = 31

        override suspend fun currentUserId(): Long? = meId

        override suspend fun mySettleOrder(orderNo: String): AiSettleOrder? =
            settleOrders.firstOrNull { it.orderNo.contains(orderNo.trim(), ignoreCase = true) }
                .also { boom() }

        override suspend fun mySettlements(orderId: Long): List<AiMySettlementRef> =
            mySettlementRows.filter { it.orderId == orderId }.also { boom() }

        override suspend fun createMySettlement(
            orderId: Long,
            lines: List<Pair<Long, String>>,
            method: String,
            note: String,
        ) {
            boom()
            myLedgerCalls += "settle:$orderId:" +
                lines.joinToString(",") { "${it.first}=${it.second}" } + ":$method:$note"
        }

        override suspend fun revokeMySettlement(id: Long) {
            boom()
            myLedgerCalls += "revoke:$id"
        }

        // ---------------------------------------------------------------- 下游价（2026-10-08 CHG-0084）

        /** 可以给下游定价的商品名册。 */
        var myPriceProductRows: MutableList<AiMyPriceProduct> = mutableListOf()

        /** 他给下游定的价（含被软删的那些）。 */
        var myPriceRows: MutableList<AiMyPriceRef> = mutableListOf()

        /** 下游价的调用记录（断言"点确认之后真的写了一次"）。 */
        val myPriceCalls: MutableList<String> = mutableListOf()

        override suspend fun myPriceProducts(): List<AiMyPriceProduct> =
            myPriceProductRows.toList().also { boom() }

        override suspend fun myPrices(includeDeleted: Boolean): List<AiMyPriceRef> =
            myPriceRows.filter { includeDeleted || !it.isDeleted }.also { boom() }

        override suspend fun setMyPrice(productId: Long, contactId: Long?, unitPrice: String) {
            boom()
            myPriceCalls += "set:" + productId + ":" + (contactId ?: 0L) + ":" + unitPrice
        }

        override suspend fun deleteMyPrice(id: Long) {
            boom()
            myPriceCalls += "delete:" + id
        }

        override suspend fun restoreMyPrice(id: Long) {
            boom()
            myPriceCalls += "restore:" + id
        }
        override suspend fun restoreMySettlement(id: Long) {
            boom()
            myLedgerCalls += "restore:$id"
        }

        override suspend fun updateLedgerEntry(id: Long, fields: JsonObject) {
            boom()
            ledgerCalls += "updateLedger:$id:${fields.toString()}"
        }

        override suspend fun deleteLedgerEntry(id: Long) {
            boom()
            ledgerCalls += "deleteLedger:$id"
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
            boom()
            ledgerCalls += "receipt:$customerId:$amount:$method:$receivedAt:$settleMode:${orderIds.joinToString(",")}:$note"
        }

        override suspend fun syncDeliveredOrders(shipperId: Long?) {
            boom()
            ledgerCalls += "sync:$shipperId"
        }

        // ---- 订单商品行 / 回收站（v3.18）----
        var lineRows = listOf(
            AiOrderLine(901, "红富士苹果", 5, "64.00", "320.00"),
            AiOrderLine(902, "皇冠梨", 2, "50.00", "100.00"),
        )
        var deletedOrderRows = listOf(
            AiOrderRef(71, "SOTEST2026090100220", "明辉食品商行", "CANCELLED", "测试收货地址 9 号", null, "88.00"),
        )

        /** 商品行/回收站写操作记一行，断言用。 */
        val lineCalls = mutableListOf<String>()

        override suspend fun orderLines(orderId: Long) = lineRows.also { boom() }

        override suspend fun addOrderLine(orderId: Long, product: String, quantity: Int, unitPrice: String) {
            boom()
            lineCalls += "addLine:$orderId:$product:$quantity:$unitPrice"
        }

        override suspend fun updateOrderLine(lineId: Long, fields: JsonObject) {
            boom()
            lineCalls += "updateLine:$lineId:${fields.toString()}"
        }

        override suspend fun deleteOrderLine(lineId: Long) {
            boom()
            lineCalls += "deleteLine:$lineId"
        }

        override suspend fun findDeletedOrders(query: String, limit: Int) = deletedOrderRows.filter {
            it.orderNo.contains(query, ignoreCase = true)
        }.take(limit).also { boom() }

        override suspend fun softDeleteOrder(orderId: Long) {
            boom()
            lineCalls += "softDelete:$orderId"
        }

        override suspend fun restoreOrder(orderId: Long) {
            boom()
            lineCalls += "restore:$orderId"
        }

        // ---- 消息（v3.19）----
        var notificationRows = listOf(
            AiNotificationRef(801, "商品价格调整：红富士苹果", "已更新：4.5 → 5", "2026-09-15T10:00:00", false),
            AiNotificationRef(802, "订单已送达", "SO123 已送达", "2026-09-15T09:00:00", true),
            AiNotificationRef(803, "商品价格调整：皇冠梨", "已更新：3 → 3.5", "2026-09-14T10:00:00", false),
        )

        /** 消息域写操作记一行，断言用。 */
        val msgCalls = mutableListOf<String>()

        override suspend fun myNotifications(limit: Int) = notificationRows.take(limit).also { boom() }

        override suspend fun sendNotification(
            recipientId: Long,
            title: String,
            content: String,
            important: Boolean,
        ) {
            boom()
            msgCalls += "send:$recipientId:$title:$content:$important"
        }

        override suspend fun notifyPriceChange(
            shipperIds: List<Long>,
            productId: Long,
            productName: String,
            priceType: String,
            newPrice: String,
            oldPrice: String?,
        ) {
            boom()
            msgCalls += "priceNotify:${shipperIds.joinToString(",")}:$productId:$productName:$priceType:$newPrice:$oldPrice"
        }

        override suspend fun markNotificationRead(id: Long) {
            boom()
            msgCalls += "markRead:$id"
        }

        override suspend fun updateNotification(id: Long, title: String?, content: String?) {
            boom()
            msgCalls += "update:$id:$title:$content"
        }

        override suspend fun deleteNotifications(ids: List<Long>, all: Boolean) {
            boom()
            msgCalls += "delete:${ids.joinToString(",")}:$all"
        }

        // ---- 主数据域（v3.9）----
        var users = listOf(AiName(71, "张三"), AiName(72, "李四"))

        /**
         * 带角色的名册（角色 → 人）。默认：张三=司机、李四=货主。
         *
         * 为什么需要它：「改司机收费规则」这类动作**只对司机有意义**，而全角色名册会让模型
         * 把货主也挑出来 —— 后端打过去是**静默空转**（200、零改动、无日志），界面却回「已完成」。
         */
        var roleUsers = mapOf(
            "driver" to listOf(AiName(71, "张三")),
            "shipper" to listOf(AiName(72, "李四")),
        )
        var priceRuleRows = listOf(AiName(81, "城东水果批发 红富士苹果 = 4.5"))
        var addressRows = listOf(AiName(91, "王五 测试路 1 号"))
        var locationRows = listOf(AiName(92, "东仓库"))
        var contactRows = listOf(AiName(93, "赵六 13700000000"))

        /** 每次写操作记一行「动作:参数」，断言用。 */
        val masterCalls = mutableListOf<String>()

        /** 预订单（2026-09-22）：名册默认空（见下面对 `orderTemplates()` 的override）。 */
        var orderTemplateRows = emptyList<AiName>()
        val orderTemplateCalls = mutableListOf<String>()

        /** 单位换算（2026-09-24）：名册默认空（见下面对 `unitConversions()` 的 override）。 */
        var unitConversionRows = emptyList<AiName>()
        val unitConversionCalls = mutableListOf<String>()

        // ---- 供应商 / 厂商档案 + 应付款（2026-09-22）----
        var supplierRows = emptyList<AiName>()
        var payableRows = emptyList<AiSupplierPayable>()
        var paymentRows = emptyList<AiName>()
        val supplierCalls = mutableListOf<String>()

        override suspend fun users(query: String) = users.also { boom() }

        override suspend fun usersOfRole(query: String, role: String) =
            (roleUsers[role] ?: emptyList()).also { boom() }
        override suspend fun addresses() = addressRows.also { boom() }
        override suspend fun locations() = locationRows.also { boom() }

        /** 共享地点库（全库共用）的名册 —— 与 `locationRows`（自己的地点库）是两份数据。 */
        var placeRows = listOf(AiName(1, "共享探针点"), AiName(2, "北京温榆河公园"))
        override suspend fun places() = placeRows.also { boom() }

        /**
         * 共享地点库的**完整记录**（补导航要它的坐标）：`id` 与 [placeRows] 对得上。
         *
         * 这一份存在的意义就是让"坐标只能从库里取"这条规矩**在单测里也能被证伪**：
         * 用例改这里的坐标，补导航写进去的就该跟着变（而不是用了别处的数）。
         */
        var placePoints = listOf(
            com.tapmoay.sorders.data.remote.dto.PlaceDto(
                id = 1,
                name = "共享探针点",
                detailAddress = "探针路 1 号",
                addressLat = "22.5000000",
                addressLng = "114.0000000",
            ),
            com.tapmoay.sorders.data.remote.dto.PlaceDto(
                id = 2,
                name = "北京温榆河公园",
                detailAddress = "高白路",
                addressLat = "40.1000000",
                addressLng = "116.6000000",
            ),
        )
        override suspend fun placeById(id: Long) = placePoints.firstOrNull { it.id == id }.also { boom() }
        override suspend fun contacts() = contactRows.also { boom() }
        override suspend fun priceRules() = priceRuleRows.also { boom() }

        /**
         * 地理编码替身。
         *
         * 默认**一条都定位不到**（= 真机上没网、或者地址说得太模糊）——这是更危险的那一半：
         * 如果默认"总能定位到"，那"定位不到时的行为"就永远测不到，
         * 而线上恰恰会出现"地址是「东边那个仓库」"这种查不出来的输入。
         * 需要"定位到了"的用例往 [geoCodes] 里塞一条。
         */
        var geoCodes = mapOf<String, Pair<Double, Double>>()
        val geoCalls = mutableListOf<String>()

        override suspend fun geocode(address: String): Pair<Double, Double>? {
            boom()
            geoCalls += address
            return geoCodes[address]
        }

        /** 撤回调的恢复方法（格式：`表:编号`），用来证明"撤回真的走了恢复端点"。 */
        val restores = mutableListOf<String>()

        /**
         * 撤回的原料：`资源:编号` → 「写之前长什么样」。
         *
         * 生产实现（[RepoWriteDataSource.snapshot]）真的去打后端；这里只放**测试自己
         * 摆好的现场**。没摆 = 读不到 = 这一条撤不回来——和线上"记录被别人删了"
         * 是同一档行为，所以"没摆现场就没有撤回"这件事本身也被测到了。
         */
        val snapshots = mutableMapOf<String, JsonObject>()

        override suspend fun snapshot(resourceKey: String, id: Long): AiBefore? {
            boom()
            snapshots["$resourceKey:$id"]?.let { return AiBefore(id, it) }
            // 可见范围没有独立的一行（它就在 users 上）：照真实实现合成一份，否则
            // "撤回要写回旧值"这件事在替身上测不出来。
            if (resourceKey == "product_visibility") {
                // ⚠️ 五个键一个都不能少：撤回是拿这份快照**整份写回**的，少一个键
                //    就等于"撤回时把那一维清空"（分类那一维会让选品页凭空少一批商品）。
                //    这里必须照抄生产实现 [AiRevertRead.productVisibility] 的键集。
                return AiBefore(
                    id,
                    buildJsonObject {
                        put("scope", visibility.scope)
                        put("product_ids", JsonArray(visibility.productIds.map { JsonPrimitive(it) }))
                        put("category_names", JsonArray(visibility.categoryNames.map { JsonPrimitive(it) }))
                        put(
                            "hidden_product_ids",
                            JsonArray(visibility.hiddenProductIds.map { JsonPrimitive(it) }),
                        )
                        put(
                            "hidden_category_names",
                            JsonArray(visibility.hiddenCategoryNames.map { JsonPrimitive(it) }),
                        )
                    },
                )
            }
            // 采购单（CHG-0074）：与生产实现（AiRevertRead.purchaseOrder）同一份键集。
            if (resourceKey == "purchase_order") {
                val dto = purchaseRows.firstOrNull { it.id == id } ?: return null
                return AiBefore(id, AiRevertRead.purchaseOrder(dto))
            }
            return null
        }

        override suspend fun restoreAddress(id: Long) {
            boom()
            restores += "address:$id"
        }

        override suspend fun restoreLocation(id: Long) {
            boom()
            restores += "location:$id"
        }

        override suspend fun restoreContact(id: Long) {
            boom()
            restores += "contact:$id"
        }

        override suspend fun restoreArrearsUnit(id: Long) {
            boom()
            restores += "arrears:$id"
        }

        override suspend fun restoreFreightTemplate(id: Long) {
            boom()
            restores += "template:$id"
        }

        override suspend fun restoreDriverRule(id: Long) {
            boom()
            restores += "driver_rule:$id"
        }

        override suspend fun restoreProduct(id: Long) {
            boom()
            restores += "product:$id"
        }

        override suspend fun restoreUser(id: Long) {
            boom()
            restores += "user:$id"
        }

        override suspend fun createProduct(
            name: String,
            defaultUnitPrice: String,
            unit: String,
            stock: Int,
            lowStockAlert: Int,
        ) {
            boom()
            masterCalls += "createProduct:$name:$defaultUnitPrice:$unit:$stock:$lowStockAlert"
        }

        override suspend fun updateProduct(id: Long, fields: JsonObject) {
            boom()
            masterCalls += "updateProduct:$id:${fields.toString()}"
        }

        override suspend fun deleteProduct(id: Long) {
            boom()
            masterCalls += "deleteProduct:$id"
        }

        override suspend fun createPriceRule(shipperId: Long, productId: Long, price: String) {
            boom()
            masterCalls += "createPriceRule:$shipperId:$productId:$price"
        }

        override suspend fun updatePriceRule(ruleId: Long, price: String) {
            boom()
            masterCalls += "updatePriceRule:$ruleId:$price"
        }

        override suspend fun deletePriceRule(ruleId: Long) {
            boom()
            masterCalls += "deletePriceRule:$ruleId"
        }

        override suspend fun createMovement(productId: Long, change: Int, note: String, unitCost: String?) {
            boom()
            // ⚠️ unit_cost 必须记进来：`成本开关打开后_进货价会写进流水` 那条用例就是靠它断言的。
            //    不记的话那条用例只会看到 movement:… —— 而它要证明的恰恰是"价真的传下去了"。
            masterCalls += "movement:$productId:$change:$note" +
                (unitCost?.let { ":unit_cost=$it" } ?: "")
        }

        override suspend fun createUser(
            phone: String,
            password: String,
            role: String,
            fullName: String,
            isMember: Boolean,
        ) {
            boom()
            // 密码记进调用日志是**测试需要**（要断言它确实发出去了），
            // 生产实现里它只进请求体、不进日志、不进卡片。
            masterCalls += "createUser:$phone:$password:$role:$fullName:$isMember"
        }

        override suspend fun updateUser(id: Long, fields: JsonObject) {
            boom()
            masterCalls += "updateUser:$id:${fields.toString()}"
        }

        override suspend fun swapUserRole(id: Long) {
            boom()
            masterCalls += "swapRole:$id"
        }

        override suspend fun deleteUser(id: Long) {
            boom()
            masterCalls += "deleteUser:$id"
        }

        // ---- 基础资料（v3.9 第二批）----
        var freightTemplateRows = listOf(AiName(101, "市区→城东"))

        override suspend fun freightTemplates() = freightTemplateRows.also { boom() }

        // ---- 司机计费规则（v3.36）----
        var driverRuleRows = listOf(AiName(201, "挂车计件"))

        override suspend fun driverRules() = driverRuleRows.also { boom() }
        override suspend fun createDriverRule(fields: JsonObject) = rec("createDriverRule", fields)
        override suspend fun updateDriverRule(id: Long, fields: JsonObject) {
            boom()
            masterCalls += "updateDriverRule:$id:${fields.toString()}"
        }
        override suspend fun deleteDriverRule(id: Long) {
            boom()
            masterCalls += "deleteDriverRule:$id"
        }
        override suspend fun attachDriverRule(driverId: Long, ruleId: Long?) {
            boom()
            masterCalls += "attachDriverRule:$driverId:${ruleId ?: "none"}"
        }

        private fun rec(name: String, fields: JsonObject) {
            boom()
            masterCalls += "$name:${fields.toString()}"
        }

        override suspend fun createAddress(fields: JsonObject) = rec("createAddress", fields)
        override suspend fun updateAddress(id: Long, fields: JsonObject) {
            boom()
            masterCalls += "updateAddress:$id:${fields.toString()}"
        }
        override suspend fun deleteAddress(id: Long) {
            boom()
            masterCalls += "deleteAddress:$id"
        }
        override suspend fun setDefaultAddress(id: Long) {
            boom()
            masterCalls += "setDefaultAddress:$id"
        }
        override suspend fun createContact(fields: JsonObject) = rec("createContact", fields)
        override suspend fun updateContact(id: Long, fields: JsonObject) {
            boom()
            masterCalls += "updateContact:$id:${fields.toString()}"
        }
        override suspend fun deleteContact(id: Long) {
            boom()
            masterCalls += "deleteContact:$id"
        }
        override suspend fun createLocation(fields: JsonObject) = rec("createLocation", fields)
        override suspend fun updateLocation(id: Long, fields: JsonObject) {
            boom()
            masterCalls += "updateLocation:$id:${fields.toString()}"
        }
        override suspend fun deleteLocation(id: Long) {
            boom()
            masterCalls += "deleteLocation:$id"
        }

        // ---- 共享地点（全库共用那张表）：改 / 删 / 撤销 / 设为共享 ----
        override suspend fun updatePlace(id: Long, fields: JsonObject) {
            boom()
            masterCalls += "updatePlace:$id:${fields.toString()}"
        }

        override suspend fun deletePlace(id: Long) {
            boom()
            masterCalls += "deletePlace:$id"
        }

        override suspend fun demotePlace(id: Long) {
            boom()
            masterCalls += "demotePlace:$id"
        }

        override suspend fun publishLocation(id: Long) {
            boom()
            masterCalls += "publishLocation:$id"
        }

        override suspend fun restorePlace(id: Long) {
            boom()
            masterCalls += "restorePlace:$id"
        }
        override suspend fun createArrearsUnit(fields: JsonObject) = rec("createArrearsUnit", fields)
        override suspend fun updateArrearsUnit(id: Long, fields: JsonObject) {
            boom()
            masterCalls += "updateArrearsUnit:$id:${fields.toString()}"
        }
        override suspend fun deleteArrearsUnit(id: Long) {
            boom()
            masterCalls += "deleteArrearsUnit:$id"
        }

        // ---- 单位换算（一车 = 8 方，2026-09-24）----
        //
        // ⚠️ 名册默认**空**：单测里没设过换算 = 按那行等式找不到（这正是"改/删一条不存在的换算"
        //    该有的样子）。要测"找得到"的用例自己往 `unitConversionRows` 里塞。
        override suspend fun unitConversions() = unitConversionRows.also { boom() }
        override suspend fun createUnitConversion(fields: JsonObject) = rec("createUnitConversion", fields)
        override suspend fun updateUnitConversion(id: Long, fields: JsonObject) {
            boom()
            unitConversionCalls += "updateUnitConversion:$id:${fields.toString()}"
        }
        override suspend fun deleteUnitConversion(id: Long) {
            boom()
            unitConversionCalls += "deleteUnitConversion:$id"
        }
        override suspend fun restoreUnitConversion(id: Long) {
            boom()
            unitConversionCalls += "restoreUnitConversion:$id"
        }

        // ---- 预订单 / 订单模板（2026-09-22）----
        //
        // ⚠️ 名册默认**空**：单测里没有预设单 = 按名字找不到（这正是"改/删一张不存在的预设单"
        //    那条路该有的样子）。要测"找得到"的用例自己往 `orderTemplateRows` 里塞。
        override suspend fun orderTemplates() = orderTemplateRows.also { boom() }
        override suspend fun createOrderTemplate(fields: JsonObject) = rec("createOrderTemplate", fields)
        override suspend fun updateOrderTemplate(id: Long, fields: JsonObject) {
            boom()
            orderTemplateCalls += "updateOrderTemplate:$id:${fields.toString()}"
        }
        override suspend fun deleteOrderTemplate(id: Long) {
            boom()
            orderTemplateCalls += "deleteOrderTemplate:$id"
        }
        override suspend fun restoreOrderTemplate(id: Long) {
            boom()
            orderTemplateCalls += "restoreOrderTemplate:$id"
        }

        // ---- 供应商 / 厂商档案 + 应付款（2026-09-22）----
        //
        // ⚠️ 三个名册默认**空**：单测里没有供应商 = 按名字找不到（这正是"改/删一个不存在的
        //    供应商""给不存在的人付款"那几条路该有的样子）。要测"找得到"的用例自己往
        //    `supplierRows` / `payableRows` / `paymentRows` 里塞。
        override suspend fun suppliers() = supplierRows.also { boom() }
        override suspend fun supplierPayables(supplierId: Long?) =
            (if (supplierId == null) payableRows else payableRows.filter { it.supplierId == supplierId })
                .also { boom() }

        override suspend fun supplierPayments() = paymentRows.also { boom() }
        override suspend fun createSupplier(fields: JsonObject) = rec("createSupplier", fields)
        override suspend fun updateSupplier(id: Long, fields: JsonObject) {
            boom()
            supplierCalls += "updateSupplier:$id:${fields.toString()}"
        }
        override suspend fun deleteSupplier(id: Long) {
            boom()
            supplierCalls += "deleteSupplier:$id"
        }
        override suspend fun restoreSupplier(id: Long) {
            boom()
            supplierCalls += "restoreSupplier:$id"
        }
        override suspend fun createSupplierPayable(fields: JsonObject) = rec("createSupplierPayable", fields)
        override suspend fun updateSupplierPayable(id: Long, fields: JsonObject) {
            boom()
            supplierCalls += "updateSupplierPayable:$id:${fields.toString()}"
        }
        override suspend fun deleteSupplierPayable(id: Long) {
            boom()
            supplierCalls += "deleteSupplierPayable:$id"
        }
        override suspend fun restoreSupplierPayable(id: Long) {
            boom()
            supplierCalls += "restoreSupplierPayable:$id"
        }
        override suspend fun paySupplierPayable(fields: JsonObject) = rec("paySupplierPayable", fields)
        override suspend fun cancelSupplierPayment(flowId: Long) {
            boom()
            supplierCalls += "cancelSupplierPayment:$flowId"
        }
        override suspend fun restoreSupplierPayment(flowId: Long) {
            boom()
            supplierCalls += "restoreSupplierPayment:$flowId"
        }

        // ---- 采购单（CHG-0074）----
        //
        // 默认**一张单都没有**：读不到 = 这一条撤不回来 / 那个动作该如实说"读不到编号 N 的单"。
        // 要测"读得到"的用例自己往 purchaseRows 里塞一张（键集与生产实现一致：只读单头三样）。
        var purchaseRows = emptyList<PurchaseOrderDto>()
        var nextPurchaseOrderId = 700L
        val purchaseCalls = mutableListOf<String>()

        override suspend fun purchaseOrder(id: Long): PurchaseOrderDto? {
            boom()
            purchaseCalls += "purchaseOrder:$id"
            return purchaseRows.firstOrNull { it.id == id }
        }

        override suspend fun createPurchaseOrder(
            supplierId: Long,
            docDate: String,
            remark: String,
            lines: List<AiPurchaseLine>,
        ): Long {
            boom()
            purchaseCalls += "createPurchaseOrder:$supplierId:$docDate:$remark:" +
                lines.joinToString("+") { "${it.productId}x${it.quantity}@${it.unitCost}" }
            return nextPurchaseOrderId
        }

        override suspend fun updatePurchaseOrderHead(orderId: Long, supplierId: Long, docDate: String, remark: String) {
            boom()
            purchaseCalls += "updatePurchaseOrderHead:$orderId:$supplierId:$docDate:$remark"
        }

        override suspend fun deletePurchaseOrder(id: Long) {
            boom()
            purchaseCalls += "deletePurchaseOrder:$id"
        }

        override suspend fun restorePurchaseOrder(id: Long) {
            boom()
            purchaseCalls += "restorePurchaseOrder:$id"
        }

        // ---- 发票台账（CHG-0086）----
        //
        // 默认**台账里一张票都没有**：读不到 = 这一条该如实说"没找到这样一张票"，
        // 而不是凭空动别的票。要测"找得到"的用例自己往 invoiceRows 里塞一张。
        // ⚠️ 假数据源这里**照抄生产的筛选口径**（后端那三个筛子在 repo 里）：
        //    方向 / 关键字（票号或对方名）/ 日期窗口 / 是否含回收站。
        var invoiceRows = emptyList<AiInvoiceRef>()
        var nextInvoiceId = 900L
        val invoiceCalls = mutableListOf<String>()

        override suspend fun invoices(
            direction: String?,
            keyword: String?,
            dateFrom: String?,
            dateTo: String?,
            includeDeleted: Boolean,
        ): List<AiInvoiceRef> {
            boom()
            invoiceCalls += "invoices:$direction:$keyword:$dateFrom:$dateTo:$includeDeleted"
            return invoiceRows.filter { row ->
                (includeDeleted || !row.isDeleted) &&
                    (direction == null || row.direction == direction) &&
                    (keyword == null || row.invoiceNo.contains(keyword, ignoreCase = true) ||
                        row.partyName.contains(keyword, ignoreCase = true)) &&
                    (dateFrom == null || row.invoiceDate >= dateFrom) &&
                    (dateTo == null || row.invoiceDate <= dateTo)
            }
        }

        override suspend fun createInvoice(draft: AiInvoiceDraft): Long {
            boom()
            invoiceCalls += "createInvoice:${draft.direction}:${draft.invoiceNo}:${draft.invoiceDate}:" +
                "${draft.amount}:${draft.taxRate}:${draft.taxAmount}:${draft.supplierId}:" +
                "${draft.customerId}:${draft.purchaseOrderIds.joinToString("+")}:${draft.note}"
            return nextInvoiceId
        }

        override suspend fun updateInvoice(id: Long, changes: JsonObject) {
            boom()
            invoiceCalls += "updateInvoice:$id:${changes.toString()}"
        }

        override suspend fun issueInvoice(id: Long) {
            boom()
            invoiceCalls += "issueInvoice:$id"
        }

        override suspend fun voidInvoice(id: Long) {
            boom()
            invoiceCalls += "voidInvoice:$id"
        }

        override suspend fun deleteInvoice(id: Long) {
            boom()
            invoiceCalls += "deleteInvoice:$id"
        }

        override suspend fun restoreInvoice(id: Long) {
            boom()
            invoiceCalls += "restoreInvoice:$id"
        }

        // ---- 钱相关四条（CHG-0087）----
        //
        // 挂账单位的**额度**只有单读一行才拿得到（名册列表里没有这一列）：默认一行都没有，
        // 要测"设额度"的用例自己往 arrearsUnitRows 里塞一条。四条写操作都记在 moneyCalls 里
        // （读也记，断言"一个字都没写"时用 count { !it.startsWith("arrearsUnit:") }）——
        // 与发票那一批同一个口径：读不到 = 如实说"没找到"，不许凭空写。
        var arrearsUnitRows = emptyList<AiArrearsUnit>()
        val moneyCalls = mutableListOf<String>()

        override suspend fun priceFreight(orderId: Long, freightFee: String, categoryId: Long?) {
            boom()
            moneyCalls += "priceFreight:$orderId:$freightFee:$categoryId"
        }

        override suspend fun applyOrderDiscount(
            orderId: Long,
            kind: String,
            value: String,
            lineIds: List<Long>,
            reason: String?,
        ) {
            boom()
            moneyCalls += "applyOrderDiscount:$orderId:$kind:$value:${lineIds.joinToString(",")}:$reason"
        }

        override suspend fun clearOrderDiscount(orderId: Long) {
            boom()
            moneyCalls += "clearOrderDiscount:$orderId"
        }

        override suspend fun arrearsUnit(id: Long): AiArrearsUnit? {
            boom()
            moneyCalls += "arrearsUnit:$id"
            return arrearsUnitRows.firstOrNull { it.id == id }
        }

        override suspend fun setArrearsUnitCreditLimit(id: Long, creditLimit: JsonElement) {
            boom()
            moneyCalls += "setArrearsUnitCreditLimit:$id:$creditLimit"
        }
        override suspend fun createFreightTemplate(fields: JsonObject) = rec("createFreightTemplate", fields)
        override suspend fun updateFreightTemplate(id: Long, fields: JsonObject) {
            boom()
            masterCalls += "updateFreightTemplate:$id:${fields.toString()}"
        }
        override suspend fun deleteFreightTemplate(id: Long) {
            boom()
            masterCalls += "deleteFreightTemplate:$id"
        }
        override suspend fun createVehicle(fields: JsonObject) = rec("createVehicle", fields)
        override suspend fun updateVehicle(id: Long, fields: JsonObject) {
            boom()
            masterCalls += "updateVehicle:$id:${fields.toString()}"
        }

        /** 换/解绑司机（v3.44）：`null` = 解绑，用 `driverId=null` 记下来才看得见"确实解绑了"。 */
        override suspend fun setVehicleDriver(id: Long, driverId: Long?) {
            boom()
            masterCalls += "setVehicleDriver:$id:$driverId"
        }
        override suspend fun createCustomer(fields: JsonObject) = rec("createCustomer", fields)

        // ---- 商品分类名册 / 商品可见范围（v3.43）----
        /**
         * 分类名册。
         *
         * `note` 照**真实实现**给"这一类下有几个商品"（[RepoWriteDataSource] 就是这么填的，
         * 空分类给 null）——改名卡片上必须有这个数字：用户唯一能判断"这一改会不会波及一片商品"的依据。
         * 第三个分类特意是空分类：那时候那句级联提醒是废话。
         */
        var categoryRows = listOf(
            AiName(71, "水果", note = "12 个商品"),
            AiName(72, "冻品", note = "3 个商品"),
            AiName(73, "干货"),
        )

        override suspend fun productCategories() = categoryRows.also { boom() }
        override suspend fun createProductCategory(fields: JsonObject) = rec("createProductCategory", fields)
        override suspend fun updateProductCategory(id: Long, fields: JsonObject) {
            boom()
            masterCalls += "updateProductCategory:$id:${fields.toString()}"
        }
        override suspend fun deleteProductCategory(id: Long) {
            boom()
            masterCalls += "deleteProductCategory:$id"
        }
        override suspend fun reorderProductCategories(ids: List<Long>) {
            boom()
            masterCalls += "reorderProductCategories:${ids.joinToString(",")}"
        }

        // ---- 地点分组（**按人分区**那一份；2026-09-19 给 AI 开的能力）----
        var placeCategoryRows = listOf(
            AiName(81, "常送小区", note = "3 个地点"),
            AiName(82, "工地"),
        )

        override suspend fun placeCategories() = placeCategoryRows.also { boom() }
        override suspend fun createPlaceCategory(fields: JsonObject) = rec("createPlaceCategory", fields)
        override suspend fun updatePlaceCategory(id: Long, fields: JsonObject) {
            boom()
            masterCalls += "updatePlaceCategory:$id:${fields.toString()}"
        }
        override suspend fun deletePlaceCategory(id: Long) {
            boom()
            masterCalls += "deletePlaceCategory:$id"
        }
        override suspend fun reorderPlaceCategories(ids: List<Long>) {
            boom()
            masterCalls += "reorderPlaceCategories:${ids.joinToString(",")}"
        }

        // ---- 联系人分类（**按人分区**；FEAT-0007 照地点分组克隆的那一份，2026-10-03）----
        // ⚠️ 与地点分组是**两张名册**（级联目标不同：那边挂地点、这边挂联系人），
        //    所以替身这里也是另起一份，⛔ 不许拿 placeCategoryRows 冒充：
        //    真拿它冒充的话，"重排联系人分类"会把地点分组一起排了 —— 那正是两张表要防的错。
        var contactCategoryRows = listOf(
            AiName(111, "供货商", note = "5 位联系人"),
            AiName(112, "老客户"),
        )

        override suspend fun contactCategories() = contactCategoryRows.also { boom() }
        override suspend fun createContactCategory(fields: JsonObject) = rec("createContactCategory", fields)
        override suspend fun updateContactCategory(id: Long, fields: JsonObject) {
            boom()
            masterCalls += "updateContactCategory:$id:${fields.toString()}"
        }
        override suspend fun deleteContactCategory(id: Long) {
            boom()
            masterCalls += "deleteContactCategory:$id"
        }
        override suspend fun reorderContactCategories(ids: List<Long>) {
            boom()
            masterCalls += "reorderContactCategories:${ids.joinToString(",")}"
        }

        // ---- 线路分类（**按人分区**；FEAT-0009 给「常用线路」从零补上的那一份，2026-10-04）----
        // ⚠️ 与前两份是**三张名册**（级联目标各不相同：地点那份挂 `shipper_locations.category`、
        //    联系人那份挂 `shipper_contacts.category`、这一份挂 `shipper_addresses.category`），
        //    所以替身这里也另起一份，⛔ 不许拿 contactCategoryRows 冒充：
        //    真拿它冒充的话，"重排线路分类"会把联系人分类一起排了 —— 那正是三张表要防的错。
        var routeCategoryRows = listOf(
            AiName(121, "城东片区", note = "2 条线路"),
            AiName(122, "常送工地"),
        )

        override suspend fun routeCategories() = routeCategoryRows.also { boom() }
        override suspend fun createRouteCategory(fields: JsonObject) = rec("createRouteCategory", fields)
        override suspend fun updateRouteCategory(id: Long, fields: JsonObject) {
            boom()
            masterCalls += "updateRouteCategory:$id:${fields.toString()}"
        }
        override suspend fun deleteRouteCategory(id: Long) {
            boom()
            masterCalls += "deleteRouteCategory:$id"
        }
        override suspend fun reorderRouteCategories(ids: List<Long>) {
            boom()
            masterCalls += "reorderRouteCategories:${ids.joinToString(",")}"
        }

        // ---- 账号分类 / 车辆分类（**全店各一份**；FEAT-0010 的分类名册，2026-10-05）----
        // ⚠️ 与前几份的分别：这两张是**全店共用**的名册（`users` / `vehicles` 都是全表），
        //    不是「按人分区」的；账号名册一份喂四个页面（账户 / 司机 / 货主 / 批发商），
        //    所以替身这里也只起两份，⛔ 不许拿 routeCategoryRows 冒充。
        var userCategoryRows = listOf(
            AiName(131, "自有车", note = "3 个账号"),
            AiName(132, "外请车"),
        )

        override suspend fun userCategories() = userCategoryRows.also { boom() }
        override suspend fun createUserCategory(fields: JsonObject) = rec("createUserCategory", fields)
        override suspend fun updateUserCategory(id: Long, fields: JsonObject) {
            boom()
            masterCalls += "updateUserCategory:$id:${fields.toString()}"
        }
        override suspend fun deleteUserCategory(id: Long) {
            boom()
            masterCalls += "deleteUserCategory:$id"
        }
        override suspend fun reorderUserCategories(ids: List<Long>) {
            boom()
            masterCalls += "reorderUserCategories:${ids.joinToString(",")}"
        }

        var vehicleCategoryRows = listOf(
            AiName(141, "冷藏车", note = "2 辆车"),
            AiName(142, "平板车"),
        )

        override suspend fun vehicleCategories() = vehicleCategoryRows.also { boom() }
        override suspend fun createVehicleCategory(fields: JsonObject) = rec("createVehicleCategory", fields)
        override suspend fun updateVehicleCategory(id: Long, fields: JsonObject) {
            boom()
            masterCalls += "updateVehicleCategory:$id:${fields.toString()}"
        }
        override suspend fun deleteVehicleCategory(id: Long) {
            boom()
            masterCalls += "deleteVehicleCategory:$id"
        }
        override suspend fun reorderVehicleCategories(ids: List<Long>) {
            boom()
            masterCalls += "reorderVehicleCategories:${ids.joinToString(",")}"
        }
        // ---- 开销 / 运费 / 预订单三份分类名册（2026-09-23 按"人能操作的 AI 都要能操作"补齐）----
        // ⚠️ 三份都照上面那两份的形状写：读那一格 `also { boom() }`（读接口在撤回/重命名卡片
        //    里也要用到，不该顺手写库），写那一格先 `boom()` 再记账（证明它真的调了数据源）。
        var expenseCategoryRows = listOf(
            AiName(91, "加油", note = "4 笔开销"),
            AiName(92, "修车"),
        )

        override suspend fun expenseCategories() = expenseCategoryRows.also { boom() }
        override suspend fun createExpenseCategory(fields: JsonObject) = rec("createExpenseCategory", fields)
        override suspend fun updateExpenseCategory(id: Long, fields: JsonObject) {
            boom()
            masterCalls += "updateExpenseCategory:$id:${fields.toString()}"
        }
        override suspend fun deleteExpenseCategory(id: Long) {
            boom()
            masterCalls += "deleteExpenseCategory:$id"
        }
        override suspend fun reorderExpenseCategories(ids: List<Long>) {
            boom()
            masterCalls += "reorderExpenseCategories:${ids.joinToString(",")}"
        }

        var freightCategoryRows = listOf(
            AiName(93, "日杂", note = "2 条价目 + 1 份规则"),
            AiName(94, "生鲜"),
        )

        override suspend fun freightCategories() = freightCategoryRows.also { boom() }
        override suspend fun createFreightCategory(fields: JsonObject) = rec("createFreightCategory", fields)
        override suspend fun updateFreightCategory(id: Long, fields: JsonObject) {
            boom()
            masterCalls += "updateFreightCategory:$id:${fields.toString()}"
        }
        override suspend fun deleteFreightCategory(id: Long) {
            boom()
            masterCalls += "deleteFreightCategory:$id"
        }
        override suspend fun reorderFreightCategories(ids: List<Long>) {
            boom()
            masterCalls += "reorderFreightCategories:${ids.joinToString(",")}"
        }

        var orderTemplateCategoryRows = listOf(
            AiName(95, "常送", note = "3 张预设单"),
            AiName(96, "临时"),
        )

        override suspend fun orderTemplateCategories() = orderTemplateCategoryRows.also { boom() }
        override suspend fun createOrderTemplateCategory(fields: JsonObject) =
            rec("createOrderTemplateCategory", fields)
        override suspend fun updateOrderTemplateCategory(id: Long, fields: JsonObject) {
            boom()
            masterCalls += "updateOrderTemplateCategory:$id:${fields.toString()}"
        }
        override suspend fun deleteOrderTemplateCategory(id: Long) {
            boom()
            masterCalls += "deleteOrderTemplateCategory:$id"
        }
        override suspend fun reorderOrderTemplateCategories(ids: List<Long>) {
            boom()
            masterCalls += "reorderOrderTemplateCategories:${ids.joinToString(",")}"
        }

        /** 某个货主当前的可见范围（默认值照后端：`all` = 不限制）。 */
        var visibility = AiVisibility("all", emptyList())

        override suspend fun productVisibility(userId: Long) = visibility.also { boom() }
        override suspend fun setProductVisibility(
            userId: Long,
            scope: String,
            productIds: List<Long>,
            categoryNames: List<String>,
            hiddenProductIds: List<Long>,
            hiddenCategoryNames: List<String>,
        ) {
            boom()
            // 整份替换：写完就是新的样子（撤回的探针靠它核对"中间有没有被别人改过"）
            visibility = AiVisibility(scope, productIds, categoryNames, hiddenProductIds, hiddenCategoryNames)
            // 调用串四维全记（用 "|" 分段）：只记授权那一维的话，
            // "少发一维 = 静默清空那一维"这类回归在测试里根本看不见。
            masterCalls += "setProductVisibility:$userId:$scope:" +
                "${productIds.joinToString(",")}|${categoryNames.joinToString(",")}|" +
                "${hiddenProductIds.joinToString(",")}|${hiddenCategoryNames.joinToString(",")}"
        }

        // ---- 批量调价 ----
        // ⚠️ 只留**一份**批发商名册：`members()` 是接口上的一个方法，
        // 两处各定义一份 `memberRows` 会直接编译不过（踩过一次）。
        var memberRows = listOf(AiName(31, "城东水果批发"), AiName(32, "明辉食品商行"))
        var productRows = listOf(
            AiPriceProduct(41, "红富士苹果", "5.00"),
            AiPriceProduct(42, "皇冠梨", "4.00"),
        )
        /** (批发商, 商品) → 专属价。没有条目 = 按商品默认价。 */
        var ruleRows = listOf(AiPriceRuleRow(31, 41, "4.50"))

        override suspend fun members() = memberRows.also { boom() }
        override suspend fun productPrices() = productRows.also { boom() }
        override suspend fun priceRuleRows() = ruleRows.also { boom() }

        override suspend fun batchPriceRules(
            shipperIds: List<Long>,
            productIds: List<Long>,
            mode: String,
            value: String?,
            adjustPercent: String?,
        ) {
            boom()
            val idx = batchCallCount++
            masterCalls += "batchPrice:${shipperIds.sorted()}:${productIds.sorted()}:$mode:$value:$adjustPercent"
            // 让"第 N 个请求失败"可复现：按表格调价是**逐行**发的，必须有办法测「部分成功」。
            if (failBatchAtIndex == idx) throw java.io.IOException("模拟第 ${idx + 1} 个请求失败")
        }

        /** 按表格调价已经发出去几个请求（第 N 个请求失败的注入点靠它）。 */
        var batchCallCount = 0

        /** 让第 N 个（0 基）批量调价请求抛异常；null = 都成功。 */
        var failBatchAtIndex: Int? = null

        // ---- 司机账单与结算（第四批）----
        //
        // ⚠️ 这一组替身必须**照着服务端的过滤语义写**（driver_id / month / bill_type 三个
        // 条件都是"给了才筛"）。如果替身无脑返回全量，handler 里"少传了一个条件"
        // 这类 bug 就测不出来了——而那种 bug 的后果是**把别人的账单算进这张卡片**。
        var salaryDriverRows = listOf(
            AiSalaryDriver(11, "王建国", "4500.00"),
            AiSalaryDriver(14, "赵德海", "6500.00"),
        )
        var billRows = listOf(
            AiDriverBill(901, 11, "王建国", "piece", "2026-09", "30.00", "open", "SOTEST2026091100230"),
            AiDriverBill(902, 11, "王建国", "piece", "2026-09", "40.00", "open", "SOTEST2026091200229"),
            AiDriverBill(903, 12, "王建军", "piece", "2026-09", "25.00", "settled", "SOTEST2026091300228"),
            AiDriverBill(904, 11, "王建国", "salary", "2026-08", "4500.00", "open"),
        )
        var settlementRows = listOf(
            AiSettlementRef(951, 11, "王建国", "piece", "2026-09", "70.00", "draft", 2),
            AiSettlementRef(952, 12, "王建军", "piece", "2026-09", "25.00", "paid", 1),
        )
        var freightRows = listOf(
            AiDriverFreight(11, "王建国", 3, "70.00"),
            AiDriverFreight(12, "王建军", 1, "25.00"),
        )

        /** 结算域写操作记一行，断言用。 */
        val settleCalls = mutableListOf<String>()

        override suspend fun salaryDrivers() = salaryDriverRows.also { boom() }

        override suspend fun driverBills(driverId: Long?, month: String?, billType: String?) =
            billRows.filter {
                (driverId == null || it.driverId == driverId) &&
                    (month == null || it.month == month) &&
                    (billType == null || it.billType.equals(billType, ignoreCase = true))
            }.also { boom() }

        override suspend fun driverSettlements(driverId: Long?, month: String?, status: String?) =
            settlementRows.filter {
                (driverId == null || it.driverId == driverId) &&
                    (month == null || it.month == month) &&
                    (status == null || it.status.equals(status, ignoreCase = true))
            }.also { boom() }

        override suspend fun monthlyFreight(month: String) = freightRows.also { boom() }

        override suspend fun generateDriverBills(driverId: Long?, month: String, billType: String) {
            boom()
            settleCalls += "generateBills:${driverId ?: "-"}:$month:$billType"
        }

        override suspend fun createSettlement(driverId: Long, settleType: String, month: String, note: String?) {
            boom()
            // ⚠️ 故意**不**打印 note/amount：金额这条口子根本不该存在（见 CreateSettlementHandler），
            // 测试要能证明"没有任何金额被传下去"。
            settleCalls += "createSettlement:$driverId:$settleType:$month"
        }

        override suspend fun settlementAction(id: Long, action: String, method: String) {
            boom()
            settleCalls += "settlementAction:$id:$action:$method"
        }
    }

    private class Rig(
        ttlMs: Long = AiWritePreviewStore.DEFAULT_TTL_MS,
        actor: AiActor? = AiActor.byRole(AiRole.DISPATCHER),
        /**
         * 「允许 AI 查看成本与毛利」（`AiKeyStore::costVisible`）。
         * **默认 false = 与真实默认一致**：成本相关的动作在开关关着时必须被拒
         * （见 `成本开关关着时_…` 那几条用例）。
         */
        allowCost: Boolean = false,
    ) {
        val ds = FakeDs()
        val store = AiWritePreviewStore(ttlMs = ttlMs)
        val svc = AiWriteService(ds, store, actorProvider = { actor }, allowCost = { allowCost })
    }

    private fun p(vararg kv: Pair<String, String>): JsonObject =
        buildJsonObject { kv.forEach { (k, v) -> put(k, v) } }

    private fun ok(out: AiWriteOutcome): AiPendingWrite {
        assertTrue("期望 NeedConfirm，实际是 $out", out is AiWriteOutcome.NeedConfirm)
        return (out as AiWriteOutcome.NeedConfirm).pending
    }

    private fun rejected(out: AiWriteOutcome): AiWriteOutcome.Rejected {
        assertTrue("期望 Rejected，实际是 $out", out is AiWriteOutcome.Rejected)
        return out as AiWriteOutcome.Rejected
    }

    private fun expenseParams(vararg extra: Pair<String, String>): JsonObject =
        p(*arrayOf("category" to "油费", "amount" to "300"), *extra)

    // ==================================================== 1. 一个 token 只能写一次

    @Test
    fun `确认一次只写一笔`() = runBlocking {
        val r = Rig()
        val card = ok(r.svc.preview(AiWrites.EXPENSES_CREATE, expenseParams()))

        assertTrue(r.svc.execute(card.token) is AiWriteOutcome.Done)
        assertEquals(1, r.ds.expenses.size)
    }

    @Test
    fun `连点两下确认只写一笔`() = runBlocking {
        val r = Rig()
        val card = ok(r.svc.preview(AiWrites.EXPENSES_CREATE, expenseParams()))

        val first = r.svc.execute(card.token)
        val second = r.svc.execute(card.token)

        assertTrue(first is AiWriteOutcome.Done)
        // 第二次必须拿不到卡。这条是"界面禁用按钮"之外的**数据层**保证——
        // 连点、状态竞争都能绕过界面，绕不过 take()。
        assertTrue("第二次应当被拒，实际是 $second", second is AiWriteOutcome.Rejected)
        assertEquals(1, r.ds.expenses.size)
        // 拒绝的口气必须说准（BUG-0021）：第一下**真的写进去了**，所以这一句要承认它。
        // ⛔ 不许说成"什么都没写"——用户会以为钱没记上，转头手工再补一笔。
        val again = rejected(second)
        assertTrue("应当承认已经写进去了：${again.reason}", again.alreadyWritten)
        assertTrue("要说「已经写进去了」：${again.reason}", "已经写进去了" in again.reason)
        assertFalse("不许说「什么都没写」：${again.reason}", "什么都没写" in again.reason)
    }

    @Test
    fun `过期的卡不能执行`() = runBlocking {
        var clock = 1_000L
        val ds = FakeDs()
        val store = AiWritePreviewStore(ttlMs = 5_000L, now = { clock })
        val svc = AiWriteService(ds, store, actorProvider = { AiActor.byRole(AiRole.DISPATCHER) })

        val card = ok(svc.preview(AiWrites.EXPENSES_CREATE, expenseParams()))
        clock += 5_001L

        val out = rejected(svc.execute(card.token))
        assertEquals(0, ds.expenses.size)
        // 没写进去的那一支必须**明说"什么都没写"**（BUG-0021）：用户看到「没写成」时，
        // 最想知道的就是"到底动没动我的账"，含糊一句他就得自己去翻账本。
        assertFalse("过期的卡不许说成写过了：${out.reason}", out.alreadyWritten)
        assertTrue("应当明说没写：${out.reason}", "什么都没写" in out.reason)
    }

    @Test
    fun `取消之后不能执行`() = runBlocking {
        val r = Rig()
        val card = ok(r.svc.preview(AiWrites.EXPENSES_CREATE, expenseParams()))

        assertTrue(r.store.cancel(card.token))
        val out = rejected(r.svc.execute(card.token))
        assertEquals(0, r.ds.expenses.size)
        assertFalse("取消过的卡不许说成写过了：${out.reason}", out.alreadyWritten)
        assertTrue("应当明说没写：${out.reason}", "什么都没写" in out.reason)
    }

    @Test
    fun `取不到未知 token`() {
        val store = AiWritePreviewStore()
        assertNull(store.take("不存在的令牌"))
        assertFalse(store.cancel("不存在的令牌"))
    }

    @Test
    fun `同一个操作申请两次只留一张卡`() = runBlocking {
        val r = Rig()
        val a = ok(r.svc.preview(AiWrites.EXPENSES_CREATE, expenseParams()))
        val b = ok(r.svc.preview(AiWrites.EXPENSES_CREATE, expenseParams()))

        // 模型重复调用是常态（某轮把工具调用重发一遍）。留两张一样的卡会造出一条
        // **真实的重复写入路径**：用户点了第一张，再看到第二张，很自然地又点一次。
        assertEquals("参数相同应当复用同一张卡", a.token, b.token)
        assertEquals(1, r.store.list().size)
    }

    @Test
    fun `参数不同的两次申请是两张卡`() = runBlocking {
        val r = Rig()
        ok(r.svc.preview(AiWrites.EXPENSES_CREATE, expenseParams("amount" to "300")))
        ok(r.svc.preview(AiWrites.EXPENSES_CREATE, expenseParams("amount" to "500")))
        assertEquals(2, r.store.list().size)
    }

    // ================================================ 2. 严格解析：绝不猜

    @Test
    fun `司机按姓名唯一命中`() = runBlocking {
        val r = Rig()
        val card = ok(r.svc.preview(AiWrites.EXPENSES_CREATE, expenseParams("driver" to "李强")))
        r.svc.execute(card.token)
        assertEquals(13L, r.ds.expenses.single().first.driverId)
    }

    @Test
    fun `司机名字对上多个就拒绝并给候选人名`() = runBlocking {
        val r = Rig()
        val out = rejected(r.svc.preview(AiWrites.EXPENSES_CREATE, expenseParams("driver" to "王建")))

        assertEquals(listOf("王建国", "王建军"), out.candidates)
        assertEquals(0, r.ds.expenses.size)
    }

    @Test
    fun `候选名单里不许出现编号`() = runBlocking {
        val r = Rig()
        val out = rejected(r.svc.preview(AiWrites.EXPENSES_CREATE, expenseParams("driver" to "王建")))
        val text = out.reason + out.candidates.joinToString()
        // 编号红线：模型拿到编号就会写进回答（实测会附「（user_id 122）」）。
        // 这里的候选**只有名字**，所以模型没有任何办法把编号带出去。
        assertFalse("拒绝理由里出现了裸编号：$text", Regex("""\d{2,}""").containsMatchIn(text))
    }

    @Test
    fun `司机完全对不上时拒绝而不是静默丢掉`() = runBlocking {
        val r = Rig()
        // 改之前的实现会把这条参数静静丢掉 → 记成一笔"没有司机的支出"：
        // 摘要上少一行很难发现，月底按司机算油耗时这笔就凭空消失了。
        val out = rejected(r.svc.preview(AiWrites.EXPENSES_CREATE, expenseParams("driver" to "赵铁柱")))
        assertTrue(out.reason.contains("赵铁柱"))
        assertEquals(0, r.ds.expenses.size)
    }

    @Test
    fun `完全相等的名字优先于前缀命中`() = runBlocking {
        val r = Rig()
        // "王建国" 同时是 "王建国" 的完全相等和 "王建国明"（若存在）的前缀。
        // 少了"完全相等优先"这一轮，用户明明说得清清楚楚却要被要求消歧义。
        r.ds.drivers = listOf(AiName(11, "王建国"), AiName(14, "王建国明"))
        val card = ok(r.svc.preview(AiWrites.EXPENSES_CREATE, expenseParams("driver" to "王建国")))
        r.svc.execute(card.token)
        assertEquals(11L, r.ds.expenses.single().first.driverId)
    }

    @Test
    fun `车牌忽略大小写空格和横杠`() = runBlocking {
        val r = Rig()
        val card = ok(r.svc.preview(AiWrites.EXPENSES_CREATE, expenseParams("vehicle" to "豫a 12345")))
        r.svc.execute(card.token)
        assertEquals(21L, r.ds.expenses.single().first.vehicleId)
    }

    @Test
    fun `车牌对不上就拒绝`() = runBlocking {
        val r = Rig()
        rejected(r.svc.preview(AiWrites.EXPENSES_CREATE, expenseParams("vehicle" to "京C00000")))
        assertEquals(0, r.ds.expenses.size)
    }

    @Test
    fun `货主对不上时按临时客户记并在摘要里写明`() = runBlocking {
        val r = Rig()
        val card = ok(
            r.svc.preview(
                AiWrites.LEDGER_CREATE_ENTRY,
                p("shipper" to "老李", "product" to "红富士苹果", "quantity" to "3", "unit_price" to "5.5"),
            ),
        )
        // 摘要必须**明说**系统没认出这个人：用户是唯一能发现"记错对象"的人。
        assertTrue(card.detailLines.any { it.contains("临时客户") })
        r.svc.execute(card.token)
        assertNull(r.ds.entries.single().shipperId)
        assertEquals("老李", r.ds.entries.single().tempShipperName)
    }

    @Test
    fun `货主认得出来时用编号`() = runBlocking {
        val r = Rig()
        val card = ok(
            r.svc.preview(
                AiWrites.LEDGER_CREATE_ENTRY,
                p("shipper" to "城东水果批发", "product" to "红富士苹果", "unit_price" to "5"),
            ),
        )
        r.svc.execute(card.token)
        assertEquals(31L, r.ds.entries.single().shipperId)
        assertNull(r.ds.entries.single().tempShipperName)
    }

    // ==================================================== 3. 参数闸门

    @Test
    fun `金额为零拒绝`() = runBlocking<Unit> {
        val r = Rig()
        rejected(r.svc.preview(AiWrites.EXPENSES_CREATE, p("category" to "油费", "amount" to "0")))
    }

    @Test
    fun `金额为负拒绝`() = runBlocking<Unit> {
        val r = Rig()
        rejected(r.svc.preview(AiWrites.EXPENSES_CREATE, p("category" to "油费", "amount" to "-5")))
    }

    @Test
    fun `金额多打了零拒绝`() = runBlocking {
        val r = Rig()
        // 300 打成 300000 时，用户扫一眼摘要**很难发现**。在校验层拦掉，
        // 模型会拿到一句明确的错误并回去跟用户核对。
        val out = rejected(r.svc.preview(AiWrites.EXPENSES_CREATE, p("category" to "油费", "amount" to "3000000")))
        assertTrue(out.reason.contains("上限"))
    }

    @Test
    fun `金额容忍单位和千分位`() = runBlocking {
        val r = Rig()
        val card = ok(r.svc.preview(AiWrites.EXPENSES_CREATE, p("category" to "油费", "amount" to "1,200.50元")))
        r.svc.execute(card.token)
        assertEquals("1200.50", r.ds.expenses.single().first.amount)
    }

    @Test
    fun `金额不是数字就拒绝`() = runBlocking<Unit> {
        val r = Rig()
        rejected(r.svc.preview(AiWrites.EXPENSES_CREATE, p("category" to "油费", "amount" to "大概三百")))
    }

    @Test
    fun `支出类别收中文名`() = runBlocking {
        val r = Rig()
        val card = ok(r.svc.preview(AiWrites.EXPENSES_CREATE, p("category" to "过路费", "amount" to "50")))
        r.svc.execute(card.token)
        assertEquals("toll", r.ds.expenses.single().first.category)
    }

    @Test
    fun `支出类别收英文 code`() = runBlocking {
        val r = Rig()
        val card = ok(r.svc.preview(AiWrites.EXPENSES_CREATE, p("category" to "fuel", "amount" to "50")))
        r.svc.execute(card.token)
        assertEquals("fuel", r.ds.expenses.single().first.category)
    }

    @Test
    fun `类别不在枚举里就拒绝`() = runBlocking {
        val r = Rig()
        val out = rejected(r.svc.preview(AiWrites.EXPENSES_CREATE, p("category" to "买了个西瓜", "amount" to "50")))
        assertTrue(out.reason.contains("油费"))
    }

    @Test
    fun `日期格式错了就拒绝`() = runBlocking {
        val r = Rig()
        val out = rejected(
            r.svc.preview(AiWrites.EXPENSES_CREATE, expenseParams("exp_date" to "2026/9/15")),
        )
        assertTrue(out.reason.contains("YYYY-MM-DD"))
    }

    @Test
    fun `不填日期就是今天`() = runBlocking {
        val r = Rig()
        val card = ok(r.svc.preview(AiWrites.EXPENSES_CREATE, expenseParams()))
        r.svc.execute(card.token)
        assertEquals(LocalDate.now().toString(), r.ds.expenses.single().first.expDate)
    }

    @Test
    fun `数量为零拒绝`() = runBlocking<Unit> {
        val r = Rig()
        rejected(
            r.svc.preview(
                AiWrites.LEDGER_CREATE_ENTRY,
                p("shipper" to "城东水果批发", "product" to "苹果", "quantity" to "0", "unit_price" to "5"),
            ),
        )
    }

    @Test
    fun `未知操作直接拒绝`() = runBlocking {
        val r = Rig()
        val out = rejected(r.svc.preview("orders.delete", p()))
        assertTrue(out.reason.contains("没有叫"))
    }

    // ============================================ 4. 卡片上写的 = 真正发出去的

    @Test
    fun `预览阶段什么都不写`() = runBlocking {
        val r = Rig()
        ok(r.svc.preview(AiWrites.EXPENSES_CREATE, expenseParams()))
        assertEquals(0, r.ds.expenses.size)
    }

    @Test
    fun `卡片摘要里的数字就是发给后端的数字`() = runBlocking {
        val r = Rig()
        val card = ok(
            r.svc.preview(AiWrites.EXPENSES_CREATE, expenseParams("vehicle" to "豫A12345", "note" to "跑了趟临市")),
        )
        assertTrue(card.summary.contains("300 元"))

        r.svc.execute(card.token)
        val (req, _) = r.ds.expenses.single()
        assertEquals("300.00", req.amount)
        assertEquals("fuel", req.category)
        assertEquals(21L, req.vehicleId)
        assertEquals("跑了趟临市", req.note)
    }

    @Test
    fun `账本合计由数量和单价算出来`() = runBlocking {
        val r = Rig()
        val card = ok(
            r.svc.preview(
                AiWrites.LEDGER_CREATE_ENTRY,
                p("shipper" to "城东水果批发", "product" to "红富士苹果", "quantity" to "3", "unit_price" to "5.5"),
            ),
        )
        assertTrue(card.summary.contains("16.5 元"))
        r.svc.execute(card.token)
        assertEquals("16.50", r.ds.entries.single().total)
    }

    @Test
    fun `幂等键跟着 token 走且每次不同`() = runBlocking {
        val r = Rig()
        val a = ok(r.svc.preview(AiWrites.EXPENSES_CREATE, expenseParams("amount" to "300")))
        val b = ok(r.svc.preview(AiWrites.EXPENSES_CREATE, expenseParams("amount" to "500")))
        r.svc.execute(a.token)
        r.svc.execute(b.token)

        val keys = r.ds.expenses.map { it.second }
        assertNotNull(keys[0])
        assertNotNull(keys[1])
        // 幂等键必须**每次操作不同**：相同的键会被后端当成"同一次重发"而丢掉第二笔。
        assertFalse("两次不同操作的幂等键不该相同", keys[0] == keys[1])
    }

    // ==================================================== 5. 低风险自动执行

    @Test
    fun `低风险动作直接执行不给卡片`() = runBlocking {
        val r = Rig()
        val out = r.svc.preview(AiWrites.NOTIFICATIONS_READ_ALL, p())

        assertTrue(out is AiWriteOutcome.Done)
        assertEquals(1, r.ds.readAllCalls)
        assertEquals(0, r.store.list().size)
        assertTrue((out as AiWriteOutcome.Done).message.contains("7"))
    }

    @Test
    fun `只有低风险动作允许自动执行`() {
        // 这条是"摩擦预算"的守门人：给低风险动作也弹确认，用户会学会无脑点确认，
        // 那个习惯一旦养成，真正危险的确认（派单/收款/撤销）也就一起失效了。
        // 反过来说，任何一个 MEDIUM/HIGH 动作溜进 autoExecutable 都是重大事故。
        val auto = AiWrites.autoExecutable
        assertTrue("低风险动作清单不该为空（否则这条断言就是空转）", auto.isNotEmpty())
        auto.forEach { id ->
            val a = AiWrites.byId(id)
            assertNotNull(a)
            assertEquals("$id 是 ${a!!.risk} 档，不许自动执行", AiWriteRisk.LOW, a.risk)
        }
    }

    @Test
    fun `中高风险动作一律要求确认`() {
        AiWrites.ALL.filter { it.risk != AiWriteRisk.LOW }.forEach {
            assertTrue("${it.id} 必须要求确认", it.risk.needsConfirm)
        }
    }

    @Test
    fun `动作 id 不重复`() {
        assertEquals(AiWrites.ALL.size, AiWrites.ids.toSet().size)
    }

    // ==================================================== 6. 编号不许出现在参数里

    @Test
    fun `任何动作的参数里都没有编号字段`() {
        // 模型只给名字，App 自己换编号。参数表里一旦出现 driver_id / shipper_id 这种键，
        // 就等于把"编造一个编号"的机会交给了模型，而它编出来的编号一定会落在某个真人头上。
        AiWrites.ALL.forEach { a ->
            a.params.forEach { pm ->
                assertFalse(
                    "${a.id} 的参数 ${pm.name} 看起来是编号字段",
                    pm.name.endsWith("_id") || pm.name == "id",
                )
            }
        }
    }

    @Test
    fun `给模型的动作清单包含每个动作和每个必填参数名`() {
        // ⚠️ 判据是 `forModel`（= 模型真的能调的那些），**不是 `ALL`**（2026-09-19 审计）。
        //    原来这里断言的是 `AiWrites.ALL`，把 8 个 `undoOnly`（撤回专用恢复动作）也算进去，
        //    于是它**反向钉住了缺陷**：`describeForModel` 当时用的是 `forRole`（含 undoOnly），
        //    模型在 `preview_write` 说明里看得到 `products.restore` 这种"模型看不到它"的动作，
        //    照着抄必然失败——而这条测试和另一条"恢复动作不进模型清单"同时是绿的。
        //    这是"两条互相矛盾的断言同时绿"的典型：一条查清单文本（含 undoOnly），一条查 enum（不含）。
        val text = AiWrites.describeForModel()
        AiWrites.forModel(AiActor.byRole(AiRole.DISPATCHER)).forEach { a ->
            assertTrue("清单里少了动作 ${a.id}", text.contains(a.id))
            a.params.filter { it.required }.forEach { pm ->
                assertTrue("清单里少了 ${a.id} 的必填参数 ${pm.name}", text.contains(pm.name))
            }
        }
        AiWrites.ALL.filter { it.undoOnly }.forEach { a ->
            assertFalse(
                "撤回专用动作 ${a.id} 不该出现在给模型的清单里（说明与 enum 必须同一套）",
                text.contains(a.id),
            )
        }
    }

    // ==================================================== 7. 失败路径

    @Test
    fun `后端报错变成拒绝而不是抛异常`() = runBlocking {
        val r = Rig()
        r.ds.failWith = RuntimeException("boom")
        val card = ok(r.svc.preview(AiWrites.EXPENSES_CREATE, expenseParams()))

        val out = r.svc.execute(card.token)
        assertTrue(out is AiWriteOutcome.Rejected)
    }

    @Test
    fun `写失败之后同一张卡也不能再点`() = runBlocking {
        val r = Rig()
        r.ds.failWith = RuntimeException("boom")
        val card = ok(r.svc.preview(AiWrites.EXPENSES_CREATE, expenseParams()))

        r.svc.execute(card.token)
        r.ds.failWith = null
        val again = r.svc.execute(card.token)

        // 失败也消耗 token。为什么这样更好：网络抖动时，用户看到的是一句"没写成功"，
        // 而不是一个还能再点的按钮——后者会让他在不确定"上次到底写没写"的情况下再点一次。
        assertTrue(again is AiWriteOutcome.Rejected)
        assertEquals(0, r.ds.expenses.size)
        // ⛔ 这里要**反着说一遍**（BUG-0021）：写失败那一次 token 也被 take 走了，
        // 但绝不能因此把第二次点击谎报成「已经写进去了」——那是一句更贵的错话
        // （用户以为钱记上了，而库里两边都没有）。
        val out = rejected(again)
        assertFalse("写失败以后不许说已经写进去了：${out.reason}", out.alreadyWritten)
        assertTrue("应当明说没写：${out.reason}", "什么都没写" in out.reason)
    }

    @Test
    fun `预览阶段后端异常也变成拒绝`() = runBlocking {
        val r = Rig()
        r.ds.failWith = RuntimeException("拉名册失败")
        val out = r.svc.preview(AiWrites.EXPENSES_CREATE, expenseParams("driver" to "李强"))
        assertTrue(out is AiWriteOutcome.Rejected)
    }

    // ============================================ 8. 动作清单与实现必须一一对应

    @Test
    fun `每个声明了的动作都真的实现了`() {
        val declared = AiWrites.ids.toSet()
        val implemented = Rig().svc.implementedActionIds
        // 少了 → 模型看得见某个动作、调了却报"暂未实现"（能看见但用不了，最坏的一种）；
        // 多了 → 死代码。两头都必须红。
        assertEquals("声明与实现不一致", declared, implemented)
    }

    @Test
    fun `订单动作的档位都不低于中风险`() {
        AiWrites.ALL.filter { it.group == AiWrites.G_ORDER }.forEach {
            assertTrue("${it.id} 是 ${it.risk} 档，订单动作不该有低风险", it.risk.needsConfirm)
        }
    }

    @Test
    fun `每个域都出现在给模型的清单里`() {
        // ⚠️ 2026-09-20 第七轮：域清单不再"一个角色全都有"——「我的账本」那一域
        //    只给**批发商货主**（派单员与普通货主都不该看到它）。
        //    所以判据是"**每个域都得有主人**"：要么派单员有、要么批发商货主有。
        //    （写死成"派单员必须有全部域"会变成一句假话，而假话比没有检查更糟。）
        val seen = AiWrites.describeForModel(AiActor.byRole(AiRole.DISPATCHER)) +
            AiWrites.describeForModel(AiActor.of(AiRole.SHIPPER, true))
        AiWrites.groups.forEach { g -> assertTrue("清单里少了域「$g」（没有任何角色看得到它）", seen.contains("【$g】")) }
        // 双向：那一域**确实**只属于批发商货主
        val memberOnly = AiWrites.G_MY_LEDGER
        assertTrue("批发商货主的清单里该有「$memberOnly」",
            AiWrites.describeForModel(AiActor.of(AiRole.SHIPPER, true)).contains("【$memberOnly】"))
        assertFalse("派单员的清单里不该有「$memberOnly」（后端只认货主角色）",
            AiWrites.describeForModel(AiActor.byRole(AiRole.DISPATCHER)).contains("【$memberOnly】"))
        assertFalse("普通货主的清单里不该有「$memberOnly」（他手机上没这一段）",
            AiWrites.describeForModel(AiActor.byRole(AiRole.SHIPPER)).contains("【$memberOnly】"))
    }

    // ==================================================== 9. 派单

    @Test
    fun `派单把订单和司机都解析成编号`() = runBlocking {
        val r = Rig()
        val card = ok(
            r.svc.preview(
                AiWrites.ORDERS_ASSIGN,
                p("order" to "SOTEST2026091100230", "driver" to "王建国", "freight" to "80"),
            ),
        )
        assertTrue(card.summary.contains("王建国"))
        r.svc.execute(card.token)
        // 卡片上写的是名字，落库时用的是编号——这一步的转换只发生在 App 内部。
        assertEquals(listOf<Any?>(61L, 11L, null, "80.00", null, null, null), r.ds.lastAssign)
    }

    @Test
    fun `派单卡片要写出这个司机现在按什么算钱`() = runBlocking {
        val r = Rig()
        // 逐单定额/定比例只有在他挂着规则时才生效——看不见规则就是闭着眼睛点确认
        r.ds.driverNote = "每单 500 元 + 运费的 5%"
        val card = ok(r.svc.preview(AiWrites.ORDERS_ASSIGN, p("order" to "SOTEST2026091100230", "driver" to "王建国")))
        assertTrue(
            card.detailLines.toString(),
            card.detailLines.any { it.contains("他现在的计费规则") && it.contains("运费的 5%") },
        )

        // ⚠️ 第二个场景必须换一个 Rig：`AiWritePreviewStore.offer` 会按 (actionId + payload)
        //    去重（防"同一件事弹两张卡 → 真的写两遍"），同一份参数第二次预览**拿回的是第一张卡**。
        val r2 = Rig()
        val card2 = ok(r2.svc.preview(AiWrites.ORDERS_ASSIGN, p("order" to "SOTEST2026091100230", "driver" to "王建国")))
        assertTrue(card2.detailLines.toString(), card2.detailLines.any { it.contains("没挂规则") })
    }

    @Test
    fun `派单能逐单定金额和提成比例`() = runBlocking {
        val r = Rig()
        // 用户 2026-09-18：「每单是不固定的…这些单价是由派单员来决定的」
        val card = ok(
            r.svc.preview(
                AiWrites.ORDERS_ASSIGN,
                p(
                    "order" to "SOTEST2026091100230", "driver" to "王建国", "freight" to "1000",
                    "piece_amount" to "300", "commission_rate" to "8",
                ),
            ),
        )
        assertTrue(
            card.detailLines.toString(),
            card.detailLines.any { it.contains("这一单单独定价") && it.contains("300 元") },
        )
        assertTrue(
            card.detailLines.toString(),
            card.detailLines.any { it.contains("这一单单独定提成") && it.contains("8") },
        )
        r.svc.execute(card.token)
        assertEquals(listOf<Any?>(61L, 11L, null, "1000.00", null, "300.00", "8.00"), r.ds.lastAssign)
    }

    @Test
    fun `改司机收费规则不会挑到货主头上（后端对这种目标静默空转）`() = runBlocking<Unit> {
        val r = Rig()
        // 李四是**货主**：后端 `PATCH /users/{id}` 的计费分支只在目标是司机时才生效，
        // 打给货主会返回 200、一个字段不改、连日志都不写 —— 卡片却会回「已完成」。
        val out = r.svc.preview(
            AiWrites.USERS_SET_BILLING,
            p("user" to "李四", "mode" to "salary"),
        )
        assertTrue("货主不该被当成司机挑中，实际返回 $out", out is AiWriteOutcome.Rejected)
        assertTrue(
            "提示里要说清是「司机」，实际：${(out as AiWriteOutcome.Rejected).reason}",
            out.reason.contains("司机"),
        )
        assertEquals("不许对货主下发计费改动", 0, r.ds.masterCalls.size)
    }

    @Test
    fun `改司机收费规则挑得到真司机`() = runBlocking<Unit> {
        val r = Rig()
        // 车型是必填（`vehicle`）——这里只验"**真司机挑得到**"，
        // 所以把必填项一起给上，让卡片能正常弹出来。
        val card = ok(
            r.svc.preview(
                AiWrites.USERS_SET_BILLING,
                p("user" to "张三", "mode" to "piece", "vehicle" to "small"),
            ),
        )
        assertTrue(
            card.summary + card.detailLines.joinToString(),
            card.summary.contains("张三") || card.detailLines.any { it.contains("张三") },
        )
    }

    @Test
    fun `派单没说派给谁就拒绝`() = runBlocking<Unit> {
        val r = Rig()
        val out = rejected(r.svc.preview(AiWrites.ORDERS_ASSIGN, p("order" to "SOTEST2026091100230")))
        assertTrue(out.reason.contains("driver"))
        assertEquals(0, r.ds.orderCalls.size)
    }

    @Test
    fun `派单给不存在的司机就拒绝`() = runBlocking<Unit> {
        val r = Rig()
        rejected(
            r.svc.preview(
                AiWrites.ORDERS_ASSIGN,
                p("order" to "SOTEST2026091100230", "driver" to "赵铁柱"),
            ),
        )
    }

    @Test
    fun `派单司机名字模糊就给候选`() = runBlocking {
        val r = Rig()
        val out = rejected(
            r.svc.preview(
                AiWrites.ORDERS_ASSIGN,
                p("order" to "SOTEST2026091100230", "driver" to "王建"),
            ),
        )
        assertEquals(listOf("王建国", "王建军"), out.candidates)
    }

    @Test
    fun `只有待派单的单能派`() = runBlocking<Unit> {
        val r = Rig()
        // 62 号单已经是「派单中」。让模型先去派一张已经派出去的单，必须被拦住——
        // 而后端也会 400，但等到用户点了确认才报错，那张卡就是白弹的。
        val out = rejected(
            r.svc.preview(
                AiWrites.ORDERS_ASSIGN,
                p("order" to "SOTEST2026091200229", "driver" to "王建国"),
            ),
        )
        assertTrue(out.reason.contains("派单中"))
    }

    @Test
    fun `订单号太短直接拒绝`() = runBlocking<Unit> {
        val r = Rig()
        // `GET /orders?q=` 对派单员是全量模糊匹配且默认不限条数。
        // 拿「02」去搜会拉回几万条、几十 MB，而这条路上没有分页兜底。
        val out = rejected(r.svc.preview(AiWrites.ORDERS_ASSIGN, p("order" to "02", "driver" to "王建国")))
        assertTrue(out.reason.contains("太短"))
    }

    @Test
    fun `订单号对不上就拒绝`() = runBlocking<Unit> {
        val r = Rig()
        val out = rejected(
            r.svc.preview(
                AiWrites.ORDERS_ASSIGN,
                p("order" to "SOTEST9999999999999", "driver" to "王建国"),
            ),
        )
        assertTrue(out.reason.contains("没找到"))
    }

    @Test
    fun `订单号对上多张就给候选`() = runBlocking {
        val r = Rig()
        // 后端 q 是模糊匹配：搜「SOTEST」会命中全部测试单。
        r.ds.orders = listOf(
            AiOrderRef(61, "SOTEST2026091100230", "城东水果批发", "PENDING_DISPATCH", "地址1", null, "320.00"),
            AiOrderRef(63, "SOTEST2026091100231", "明辉食品商行", "PENDING_DISPATCH", "地址2", null, "100.00"),
        )
        val out = rejected(
            r.svc.preview(AiWrites.ORDERS_ASSIGN, p("order" to "SOTEST", "driver" to "王建国")),
        )
        assertEquals(2, out.candidates.size)
        assertTrue(out.candidates[0].contains("SOTEST2026091100230"))
        // 候选里必须有货主和状态，否则用户没法判断是哪一张
        assertTrue(out.candidates[0].contains("城东水果批发"))
    }

    @Test
    fun `卡片上不许出现任何内部编号`() = runBlocking {
        val r = Rig()
        // 用绝不会和业务数字撞车的编号，才能断言得干净
        r.ds.orders = listOf(
            AiOrderRef(900061, "SOTEST2026091100230", "城东水果批发", "PENDING_DISPATCH", "测试收货地址 65 号", null, "320.00"),
        )
        r.ds.drivers = listOf(AiName(900011, "王建国"))

        val card = ok(
            r.svc.preview(
                AiWrites.ORDERS_ASSIGN,
                p("order" to "SOTEST2026091100230", "driver" to "王建国"),
            ),
        )
        val text = card.summary + "\n" + card.detailLines.joinToString("\n")
        assertTrue("payload 里应当有编号（写库要用）", card.payload.toString().contains("900061"))
        // 编号红线：卡片是给用户看的，编号他看不懂也用不上；而模型读到就会写进回答。
        assertFalse("卡片上泄露了订单编号：$text", text.contains("900061"))
        assertFalse("卡片上泄露了司机编号：$text", text.contains("900011"))
    }

    // ==================================================== 10. 撤回 / 撤销

    @Test
    fun `撤回必须给原因`() = runBlocking<Unit> {
        val r = Rig()
        // 原因会原样推送给原司机。"撤回"两个字发过去，司机只会来问你为什么。
        val out = rejected(r.svc.preview(AiWrites.ORDERS_RECALL, p("order" to "SOTEST2026091200229")))
        assertTrue(out.reason.contains("reason"))
    }

    @Test
    fun `撤回会把原因落库`() = runBlocking {
        val r = Rig()
        val card = ok(
            r.svc.preview(
                AiWrites.ORDERS_RECALL,
                p("order" to "SOTEST2026091200229", "reason" to "车辆临时故障，改派他人"),
            ),
        )
        assertTrue(card.detailLines.any { it.contains("车辆临时故障") })
        r.svc.execute(card.token)
        assertEquals(listOf("recall:62:车辆临时故障，改派他人"), r.ds.orderCalls)
    }

    @Test
    fun `待派单的单不能撤回`() = runBlocking<Unit> {
        val r = Rig()
        val out = rejected(
            r.svc.preview(AiWrites.ORDERS_RECALL, p("order" to "SOTEST2026091100230", "reason" to "改派")),
        )
        assertTrue(out.reason.contains("待派单"))
    }

    @Test
    fun `已接单的单不能撤销`() = runBlocking<Unit> {
        val r = Rig()
        r.ds.orders = listOf(
            AiOrderRef(64, "SOTEST2026091300228", "城东水果批发", "ACCEPTED", "地址3", "李强", "200.00"),
        )
        val out = rejected(r.svc.preview(AiWrites.ORDERS_CANCEL, p("order" to "SOTEST2026091300228")))
        assertTrue(out.reason.contains("已接单"))
    }

    @Test
    fun `撤销会把终态风险写在卡片上`() = runBlocking {
        val r = Rig()
        val card = ok(r.svc.preview(AiWrites.ORDERS_CANCEL, p("order" to "SOTEST2026091100230")))
        // "撤不回来"必须写在卡片上：这是用户最后一次能拦住自己的地方
        assertTrue(card.detailLines.any { it.contains("撤不回来") })
        assertEquals(AiWriteRisk.HIGH, card.risk)
    }

    // ==================================================== 11. 创建订单

    private fun lineJson(vararg ls: Triple<String, Int, String>): JsonArray =
        buildJsonArray {
            ls.forEach { (name, qty, price) ->
                add(
                    buildJsonObject {
                        put("product", name)
                        put("quantity", qty)
                        put("unit_price", price)
                    },
                )
            }
        }

    private fun createParams(shipper: String, lines: JsonArray?, address: String? = null): JsonObject =
        buildJsonObject {
            put("shipper", shipper)
            if (lines != null) put("lines", lines)
            if (address != null) put("address", address)
        }

    @Test
    fun `创建订单把商品名换成编号并算好合计`() = runBlocking {
        val r = Rig()
        val card = ok(
            r.svc.preview(
                AiWrites.ORDERS_CREATE,
                createParams("城东水果批发", lineJson(Triple("红富士苹果", 3, "5.5"), Triple("皇冠梨", 2, "4"))),
            ),
        )
        assertTrue(card.summary.contains("24.5 元")) // 3×5.5 + 2×4
        r.svc.execute(card.token)

        val req = r.ds.createdOrders.single()
        assertEquals(31L, req.shipperId)
        assertEquals(2, req.lines.size)
        assertEquals(41L, req.lines[0].productId)
        assertEquals("16.50", req.lines[0].lineTotal)
        assertEquals("8.00", req.lines[1].lineTotal)
        assertEquals(LocalDate.now().toString(), req.orderDate)
    }

    @Test
    fun `创建订单没说下什么货就拒绝`() = runBlocking<Unit> {
        val r = Rig()
        val out = rejected(r.svc.preview(AiWrites.ORDERS_CREATE, createParams("城东水果批发", null)))
        assertTrue(out.reason.contains("lines"))
    }

    @Test
    fun `创建订单里商品名查不到就拒绝`() = runBlocking<Unit> {
        val r = Rig()
        // 不做成"查不到就当自由文本商品"——那样会建出一张系统里根本不存在的商品的单，
        // 库存扣不了，报表里也会多出一个只出现过一次的商品名。
        val out = rejected(
            r.svc.preview(
                AiWrites.ORDERS_CREATE,
                createParams("城东水果批发", lineJson(Triple("火星西瓜", 1, "10"))),
            ),
        )
        assertTrue(out.reason.contains("火星西瓜"))
    }

    @Test
    fun `创建订单的货主查不到时按临时货主记并在摘要写明`() = runBlocking {
        val r = Rig()
        val card = ok(
            r.svc.preview(
                AiWrites.ORDERS_CREATE,
                createParams("老李", lineJson(Triple("红富士苹果", 1, "5.5"))),
            ),
        )
        assertTrue(card.detailLines.any { it.contains("临时货主") })
        r.svc.execute(card.token)
        assertNull(r.ds.createdOrders.single().shipperId)
        assertEquals("老李", r.ds.createdOrders.single().tempShipperName)
    }

    @Test
    fun `创建订单的地址没填时卡片上写明`() = runBlocking {
        val r = Rig()
        val card = ok(
            r.svc.preview(
                AiWrites.ORDERS_CREATE,
                createParams("城东水果批发", lineJson(Triple("红富士苹果", 1, "5.5"))),
            ),
        )
        // 下单漏地址是很常见的失误，卡片上必须看得出来
        assertTrue(card.detailLines.any { it.contains("没填") })
    }

    // ============================================ 12. 运费 / 收款 / 挂账

    @Test
    fun `已送达的单不能改运费`() = runBlocking<Unit> {
        val r = Rig()
        r.ds.orders = listOf(
            AiOrderRef(65, "SOTEST2026091400227", "城东水果批发", "DELIVERED", "地址4", "李强", "200.00"),
        )
        val out = rejected(
            r.svc.preview(AiWrites.ORDERS_FREIGHT, p("order" to "SOTEST2026091400227", "freight" to "80")),
        )
        assertTrue(out.reason.contains("已送达"))
    }

    @Test
    fun `改运费允许填零`() = runBlocking {
        val r = Rig()
        val card = ok(
            r.svc.preview(AiWrites.ORDERS_FREIGHT, p("order" to "SOTEST2026091100230", "freight" to "0")),
        )
        r.svc.execute(card.token)
        assertEquals(listOf("freight:61:0.00"), r.ds.orderCalls)
    }

    @Test
    fun `挂账单位查不到就拒绝`() = runBlocking<Unit> {
        val r = Rig()
        val out = rejected(
            r.svc.preview(
                AiWrites.ORDERS_CHARGE,
                p("order" to "SOTEST2026091100230", "unit" to "不存在的单位"),
            ),
        )
        assertTrue(out.reason.contains("挂账单位"))
    }

    // ============================================ 12b. 补导航（2026-09-20）

    @Test
    fun `补导航用的是共享地点库里那一条的坐标`() = runBlocking {
        val r = Rig()
        // 库里那个点是什么坐标，写进去的就该是什么坐标 —— 这是这条动作的全部意义。
        // （用户 2026-09-20：「叫 AI 补上地点」；而模型全程碰不到经纬度。）
        r.ds.placePoints = listOf(
            com.tapmoay.sorders.data.remote.dto.PlaceDto(
                id = 2,
                name = "北京温榆河公园",
                detailAddress = "高白路",
                addressLat = "40.1234567",
                addressLng = "116.7654321",
            ),
        )
        val card = ok(
            r.svc.preview(
                AiWrites.ORDERS_FILL_NAV,
                p("order" to "SOTEST2026091100230", "place" to "北京温榆河公园"),
            ),
        )
        assertTrue(
            "卡片必须把坐标写在脸上：${card.detailLines}",
            card.detailLines.any { it.contains("40.1234567") },
        )
        r.svc.execute(card.token)
        assertEquals(listOf("fillNav:61:40.1234567,116.7654321:北京温榆河公园"), r.ds.orderCalls)
    }

    @Test
    fun `补导航不改地点名时用库里那个名字`() = runBlocking {
        val r = Rig()
        val card = ok(
            r.svc.preview(
                AiWrites.ORDERS_FILL_NAV,
                p("order" to "SOTEST2026091100230", "place" to "共享探针点"),
            ),
        )
        r.svc.execute(card.token)
        assertEquals(listOf("fillNav:61:22.5000000,114.0000000:共享探针点"), r.ds.orderCalls)
    }

    @Test
    fun `已经有导航信息的单拒绝补导航`() = runBlocking<Unit> {
        val r = Rig()
        r.ds.orders = listOf(
            AiOrderRef(
                61, "SOTEST2026091100230", "城东水果批发", "PENDING_DISPATCH", "地址", null, "320.00",
                hasNav = true,
            ),
        )
        val out = rejected(
            r.svc.preview(
                AiWrites.ORDERS_FILL_NAV,
                p("order" to "SOTEST2026091100230", "place" to "共享探针点"),
            ),
        )
        assertTrue("已经有导航信息", out.reason.contains("已经有导航信息"))
    }

    @Test
    fun `共享库里没有这个地点就拒绝`() = runBlocking<Unit> {
        val r = Rig()
        val out = rejected(
            r.svc.preview(
                AiWrites.ORDERS_FILL_NAV,
                p("order" to "SOTEST2026091100230", "place" to "不存在的地点"),
            ),
        )
        assertTrue("共享地点", out.reason.contains("共享地点"))
    }

    @Test
    fun `库里那条没有坐标时拒绝补导航`() = runBlocking<Unit> {
        val r = Rig()
        r.ds.placePoints = listOf(
            com.tapmoay.sorders.data.remote.dto.PlaceDto(
                id = 1,
                name = "共享探针点",
                detailAddress = "探针路 1 号",
                addressLat = "",
                addressLng = "",
            ),
        )
        val out = rejected(
            r.svc.preview(
                AiWrites.ORDERS_FILL_NAV,
                p("order" to "SOTEST2026091100230", "place" to "共享探针点"),
            ),
        )
        assertTrue("没有坐标", out.reason.contains("没有坐标"))
    }

    @Test
    fun `挂账把单位名换成编号`() = runBlocking {
        val r = Rig()
        val card = ok(
            r.svc.preview(
                AiWrites.ORDERS_CHARGE,
                p("order" to "SOTEST2026091100230", "unit" to "明辉食品商行"),
            ),
        )
        assertTrue(card.summary.contains("明辉食品商行"))
        r.svc.execute(card.token)
        assertEquals(listOf("charge:61:51"), r.ds.orderCalls)
    }

    @Test
    fun `收款不带任何参数只认订单号`() = runBlocking {
        val r = Rig()
        val card = ok(r.svc.preview(AiWrites.ORDERS_PAY, p("order" to "SOTEST2026091200229")))
        assertTrue(card.summary.contains("收款"))
        r.svc.execute(card.token)
        assertEquals(listOf("pay:62"), r.ds.orderCalls)
    }

    // ============================================ 13. 主数据：PATCH 语义与空卡

    @Test
    fun `改商品只发改的那几项`() = runBlocking {
        val r = Rig()
        val card = ok(r.svc.preview(AiWrites.PRODUCTS_UPDATE, p("product" to "红富士苹果", "price" to "6.5")))
        r.svc.execute(card.token)
        val call = r.ds.masterCalls.single()
        // PATCH 语义：没说的字段**不许补默认值**。补了就等于"顺手把用户没提的项也改了"。
        assertTrue("payload 只该有 default_unit_price：$call", call.contains("default_unit_price"))
        assertFalse("不该出现 name：$call", call.contains("\"name\""))
        // 注意要连冒号一起匹配：`"default_unit_price"` 里本来就含 "unit" 这几个字母
        assertFalse("不该出现 unit：$call", call.contains("\"unit\":"))
    }

    @Test
    fun `什么都没说要改就拒绝`() = runBlocking<Unit> {
        val r = Rig()
        // 一张"什么都不改"的卡只会让用户困惑：他点了确认，然后什么都没发生。
        val out = rejected(r.svc.preview(AiWrites.PRODUCTS_UPDATE, p("product" to "红富士苹果")))
        assertTrue(out.reason.contains("要改"))
        assertEquals(0, r.ds.masterCalls.size)
    }

    @Test
    fun `上下架走同一个商品接口且只改 is_active`() = runBlocking {
        val r = Rig()
        val card = ok(
            r.svc.preview(AiWrites.PRODUCTS_SET_ACTIVE, p("product" to "红富士苹果", "active" to "false")),
        )
        assertTrue(card.summary.contains("下架"))
        r.svc.execute(card.token)
        val call = r.ds.masterCalls.single()
        assertTrue(call.contains("\"is_active\":false"))
        assertFalse(call.contains("name"))
    }

    @Test
    fun `固价只改 no_discount 且卡片说清「价格照旧可改」`() = runBlocking {
        val r = Rig()
        val card = ok(
            r.svc.preview(AiWrites.PRODUCTS_SET_NO_DISCOUNT, p("product" to "红富士苹果", "no_discount" to "true")),
        )
        val all = card.summary + "|" + card.detailLines.joinToString("|")
        assertTrue("摘要要写明固价/不参与打折：${card.summary}",
            card.summary.contains("固价") || card.summary.contains("不参与打折"))
        // ⛔ 不许承诺「价格锁死 / 不能改价」：这个 flag 的语义只有一条 —— 订单打折时跳过它，
        //    价格照旧可以改（backend/app/services/order_discount.py 的注释专门澄清过）。
        assertFalse("不许写成价格锁死：$all", all.contains("锁死"))
        assertTrue("要写明价格照旧可改：$all", all.contains("价格"))
        r.svc.execute(card.token)
        val call = r.ds.masterCalls.single()
        assertTrue("payload 只该有 no_discount：$call", call.contains("\"no_discount\":true"))
        assertFalse("不该出现 is_active：$call", call.contains("is_active"))
    }

    @Test
    fun `恢复打折写 no_discount=false`() = runBlocking {
        val r = Rig()
        val card = ok(
            r.svc.preview(AiWrites.PRODUCTS_SET_NO_DISCOUNT, p("product" to "红富士苹果", "no_discount" to "false")),
        )
        assertTrue("摘要要写明是恢复：${card.summary}", card.summary.contains("参与打折"))
        r.svc.execute(card.token)
        assertTrue(r.ds.masterCalls.single().contains("\"no_discount\":false"))
    }

    // ============================================ 14. 主数据：库存增减量

    @Test
    fun `库存调整支持负数`() = runBlocking {
        val r = Rig()
        val card = ok(
            r.svc.preview(
                AiWrites.INVENTORY_ADJUST,
                p("product" to "红富士苹果", "change" to "-20", "note" to "盘点差异"),
            ),
        )
        assertTrue("出库摘要要对：${card.summary}", card.summary.contains("出库"))
        assertTrue(card.summary.contains("-20"))
        r.svc.execute(card.token)
        assertEquals(listOf("movement:41:-20:盘点差异"), r.ds.masterCalls)
    }

    @Test
    fun `库存调整为零就拒绝`() = runBlocking<Unit> {
        val r = Rig()
        // "调整 0 件"是一次没有效果、却会留下一条流水的操作。
        val out = rejected(
            r.svc.preview(AiWrites.INVENTORY_ADJUST, p("product" to "红富士苹果", "change" to "0")),
        )
        assertTrue(out.reason.contains("0"))
    }

    @Test
    fun `入库时摘要写正数`() = runBlocking {
        val r = Rig()
        val card = ok(r.svc.preview(AiWrites.INVENTORY_ADJUST, p("product" to "红富士苹果", "change" to "50")))
        assertTrue(card.summary.contains("入库"))
        assertTrue(card.summary.contains("+50"))
    }

    // ============================================ 15. 主数据：枚举中文别名

    @Test
    fun `司机计费方式收中文别名`() = runBlocking {
        val r = Rig()
        val card = ok(
            r.svc.preview(
                AiWrites.USERS_SET_BILLING,
                p("user" to "张三", "mode" to "计件", "vehicle" to "大货车"),
            ),
        )
        r.svc.execute(card.token)
        val call = r.ds.masterCalls.single()
        // 用户用中文说"计件"，模型多半照抄。只认英文等于逼它猜，猜错了是**钱算错**。
        //
        // ⚠️ 发出去的是**大写** `PIECE`（2026-09-17 起）：后端各消费点比的就是大写，
        //    以前这里发小写 `piece`，于是那个司机在「司机运费结算」页看不到自己的单、
        //    派单页也不给他显示运费输入框（判成工资制）——而司机账单里又算他计件。
        assertTrue("billing_mode 该归一成大写 PIECE：$call", call.contains("\"billing_mode\":\"PIECE\""))
        assertTrue("vehicle_type 该归一成 large：$call", call.contains("\"vehicle_type\":\"large\""))
    }

    @Test
    fun `固定工资写在卡片上`() = runBlocking {
        val r = Rig()
        val card = ok(
            r.svc.preview(
                AiWrites.USERS_SET_BILLING,
                p("user" to "张三", "mode" to "固定工资", "vehicle" to "小货车", "salary" to "6000"),
            ),
        )
        // 「不显示运费」是这个档位最容易被误解的地方，卡片上必须写出来
        assertTrue(card.detailLines.any { it.contains("不显示运费") })
    }

    @Test
    fun `计费方式填了没见过的值就拒绝并列全取值`() = runBlocking<Unit> {
        val r = Rig()
        val out = rejected(
            r.svc.preview(
                AiWrites.USERS_SET_BILLING,
                p("user" to "张三", "mode" to "看心情", "vehicle" to "小货车"),
            ),
        )
        assertTrue(out.reason.contains("piece"))
    }

    // ============================================ 16. 主数据：批发商专属价

    @Test
    fun `专属价按批发商加商品定位`() = runBlocking {
        val r = Rig()
        val card = ok(
            r.svc.preview(AiWrites.PRICE_RULES_SET, p("shipper" to "城东水果批发", "product" to "红富士苹果", "price" to "4.5")),
        )
        assertTrue(card.summary.contains("城东水果批发"))
        r.svc.execute(card.token)
        assertEquals(listOf("createPriceRule:31:41:4.50"), r.ds.masterCalls)
    }

    @Test
    fun `专属价那条规则对不上就拒绝`() = runBlocking<Unit> {
        val r = Rig()
        val out = rejected(
            r.svc.preview(AiWrites.PRICE_RULES_UPDATE, p("rule" to "不存在的组合", "price" to "5")),
        )
        assertTrue(out.reason.contains("批发商专属价"))
    }

    // ============================================ 17. 主数据：账号与凭据红线

    @Test
    fun `新建账号必须给密码不许自己编`() = runBlocking<Unit> {
        val r = Rig()
        // 模型"顺手编一个密码"是这里最坏的一种行为：用户根本不知道密码是什么，
        // 而且他会以为账号能登。
        val out = rejected(
            r.svc.preview(
                AiWrites.USERS_CREATE,
                p("phone" to "13900000000", "role" to "司机", "name" to "王五"),
            ),
        )
        assertTrue(out.reason.contains("password"))
        assertEquals(0, r.ds.masterCalls.size)
    }

    @Test
    fun `密码绝不出现在卡片上`() = runBlocking {
        val r = Rig()
        val card = ok(
            r.svc.preview(
                AiWrites.USERS_CREATE,
                p("phone" to "13900000000", "password" to "S3cret-密码", "role" to "货主", "name" to "王五"),
            ),
        )
        val text = card.summary + "\n" + card.detailLines.joinToString("\n")
        assertFalse("卡片上泄露了密码：$text", text.contains("S3cret"))
        assertTrue("应当写明已设置但不显示", text.contains("不显示"))
        // 但密码必须真的发出去（否则账号建不出来）
        r.svc.execute(card.token)
        assertTrue(r.ds.masterCalls.single().contains("S3cret"))
    }

    @Test
    fun `改密码同样不回显`() = runBlocking {
        val r = Rig()
        val card = ok(
            r.svc.preview(AiWrites.USERS_SET_PASSWORD, p("user" to "张三", "password" to "N3wpass")),
        )
        val text = card.summary + "\n" + card.detailLines.joinToString("\n")
        assertFalse(text.contains("N3wpass"))
    }

    @Test
    fun `成本价在参数表里_因为用户要求 AI 也能操作它`() {
        // ⚠️ 这条**在 2026-09-19 被用户推翻了**。原来写的是「成本价不在任何动作的参数表里」：
        //    成本是红线，不许进模型上下文，所以也不许由模型来设。
        //    用户后来的话是：「只要是我们改过、比如说新加了一些功能，AI 它都要具备操纵这些
        //    功能的能力」—— 而"进货时录成本价""改成本价"正是我们刚加的功能。
        //
        // 所以规则从"**从来不许**"变成"**必须在开关后面**"：
        //   · 参数表里有 cost_price / unit_cost（模型看得见、能申请）；
        //   · 但开关（`AiKeyStore::costVisible`，默认关）没开时 **preview 直接拒绝、不发卡** ——
        //     见下面那条端到端用例，以及 `_check_ai_guardrails.py` 里对应的判据。
        val paramsOf = AiWrites.ALL.flatMap { a -> a.params.map { a.id to it.name } }
        assertTrue(
            "没有任何动作带成本参数 —— AI 就操作不了用户刚刚要求的那两个功能",
            paramsOf.any { it.second == "cost_price" },
        )
        assertTrue(paramsOf.any { it.second == "unit_cost" })
    }

    @Test
    fun `成本开关关着时_改成本价的申请被拒绝且不发卡`() = runBlocking {
        val r = Rig() // 默认 allowCost = false（与真实默认一致）
        val out = r.svc.preview(AiWrites.PRODUCTS_UPDATE, p("product" to "红富士苹果", "cost_price" to "12"))
        assertTrue("开关关着却发了卡：$out", out is AiWriteOutcome.Rejected)
        // ⛔ 拒绝的话必须**告诉用户怎么打开**，否则他只会觉得"AI 又说它不能"
        val msg = (out as AiWriteOutcome.Rejected).reason
        assertTrue("拒绝理由里没说要怎么开：$msg", msg.contains("允许 AI 查看成本与毛利"))
    }

    @Test
    fun `成本开关打开后_改成本价能落库`() = runBlocking {
        val r = Rig(allowCost = true)
        val card = ok(r.svc.preview(AiWrites.PRODUCTS_UPDATE, p("product" to "红富士苹果", "cost_price" to "12")))
        r.svc.execute(card.token)
        assertTrue(
            "开关开了却没把 cost_price 发给后端：${r.ds.masterCalls}",
            r.ds.masterCalls.any { it.contains("cost_price") && it.contains("12") },
        )
    }

    @Test
    fun `成本开关关着时_进货价不会被静默丢掉而是明确拒绝`() = runBlocking {
        val r = Rig()
        val out = r.svc.preview(
            AiWrites.INVENTORY_ADJUST,
            p("product" to "红富士苹果", "change" to "50", "unit_cost" to "9.5"),
        )
        // ⛔ 这里**不能**"收下参数、发张卡、然后悄悄不写进货价" ——
        //    那正是本项目最贵的一类坑（界面填了、库里什么都没有）。
        assertTrue("进货价开关关着却发了卡：$out", out is AiWriteOutcome.Rejected)
    }

    @Test
    fun `成本开关打开后_进货价会写进流水`() = runBlocking {
        val r = Rig(allowCost = true)
        val card = ok(
            r.svc.preview(
                AiWrites.INVENTORY_ADJUST,
                p("product" to "红富士苹果", "change" to "50", "unit_cost" to "9.5"),
            ),
        )
        r.svc.execute(card.token)
        assertTrue(
            "开关开了却没把 unit_cost 发给后端：${r.ds.masterCalls}",
            r.ds.masterCalls.any { it.contains("unit_cost") && it.contains("9.5") },
        )
    }

    @Test
    fun `停用账号的卡片写明登录不了`() = runBlocking {
        val r = Rig()
        val card = ok(r.svc.preview(AiWrites.USERS_SET_ACTIVE, p("user" to "张三", "active" to "false")))
        assertTrue(card.detailLines.any { it.contains("登录不了") })
    }

    @Test
    fun `改资料走的是白名单字段`() = runBlocking {
        val r = Rig()
        val card = ok(r.svc.preview(AiWrites.USERS_UPDATE_PROFILE, p("user" to "张三", "name" to "张三丰")))
        r.svc.execute(card.token)
        val call = r.ds.masterCalls.single()
        assertTrue(call.contains("\"full_name\":\"张三丰\""))
        // 「改资料」不许顺手改权限/计费——那些各有各的动作，各有各的档位
        assertFalse("不该带上 is_active：$call", call.contains("is_active"))
        assertFalse("不该带上 billing_mode：$call", call.contains("billing_mode"))
        assertFalse("不该带上 is_member：$call", call.contains("is_member"))
    }

    // ============================================ 18. 主数据：整体覆盖

    @Test
    fun `每个域都至少有一个动作`() {
        AiWrites.groups.forEach { g ->
            assertTrue("域「$g」没有任何动作", AiWrites.ALL.any { it.group == g })
        }
    }

    @Test
    fun `声明式动作的参数表由规格推导且非空`() {
        AiWrites.ALL.filter { it.crud != null && !it.undoOnly }.forEach { a ->
            assertTrue("${a.id} 是声明式动作，参数表却是空的", a.params.isNotEmpty())
        }
        // ⚠️ 撤回专用的恢复动作是**故意**没有参数的：模型看不到它们，编号由撤回入口带过来。
        //    所以这里跳过 undoOnly，但要断言它们真的存在（不然这条跳过会变成"什么都不查"）。
        assertTrue(
            "撤回专用的声明式动作不该是空的（否则上面那个跳过等于没查）",
            AiWrites.ALL.count { it.crud != null && it.undoOnly } >= 7,
        )
    }

    // ==================================== 19. 摘要必须真的看得见填了的值
    //
    // 这一条是**真机 E2E 抓到的 bug 固化下来的**：把商品单价改成 6.5 时，
    // 卡片上只剩一个光秃秃的「改商品：X」标题——因为摘要读的是 `default_unit_price`（payload 键名），
    // 而当时的值是按参数名 `price` 存的。**用户看到一张什么都没写的卡**，
    // 而它看起来完全正常，点下去也会正常生效。
    //
    // 修法是让 AiWriteCard 同时认两个名字；这条测试保证"两个名字至少有一个是对的"，
    // 也就是：**凡是填了的字段，它的值必须出现在卡片上**。

    private fun dummyFor(f: AiFieldSpec): String = when {
        // 凭据字段用**带自己名字的哨兵值**：普通哑值（"哑值文本"）会和别的 TEXT 字段撞车，
        // 于是"卡片里有没有这个值"就测不准了——第一版就是这么误报的。
        f.secret -> "哨兵${f.name}哨兵"
        f.type == AiFieldType.TEXT -> "哑值文本"
        f.type == AiFieldType.MONEY -> "12.34"
        f.type == AiFieldType.COUNT -> "3"
        f.type == AiFieldType.DELTA -> "5"
        // 非负整数（库存报警阈值/初始库存）：**用 0**——它是这类字段唯一"合法但容易被拒"的值
        // （DELTA 时代填 0 会被拒，那正是 2026-09-19 审计修掉的那条）
        f.type == AiFieldType.NON_NEGATIVE -> "0"
        f.type == AiFieldType.DATE -> "2026-09-15"
        f.type == AiFieldType.BOOL -> "true"
        else -> f.enumValues.first()
    }

    @Test
    fun `每个声明式动作的摘要都能看到填了的值`() {
        var checked = 0
        AiWrites.ALL.forEach { a ->
            val spec = a.crud ?: return@forEach
            fun render(values: Map<String, String>): String {
                val raw = LinkedHashMap<String, JsonElement>()
                values.forEach { (k, v) -> raw[k] = JsonPrimitive(v) }
                val card = AiWriteCard(
                    refs = spec.targets.associate { it.param to AiName(999, "某某") },
                    rawValues = raw,
                    keyOf = spec.fields.associate { it.name to it.key },
                    payload = JsonObject(emptyMap()),
                )
                return spec.headline(card) + "\n" + spec.details(card).joinToString("\n")
            }

            val all = spec.fields.associate { it.name to dummyFor(it) }
            val text = render(all)

            spec.fields.forEach { f ->
                when {
                    // 凭据字段：值**必须不出现在卡片上**（这是红线，不是偏好），
                    // 但卡片要写明"已设置、不显示"——否则用户不知道到底设没设。
                    f.secret -> {
                        assertFalse(
                            "${a.id} 的卡片上泄露了 ${f.name} 的值",
                            text.contains(dummyFor(f)),
                        )
                        assertTrue(
                            "${a.id} 的卡片上没写明 ${f.name}「已设置、不显示」",
                            text.contains("不显示"),
                        )
                    }

                    // 布尔/枚举：不要求把原始值印出来——它们的语义由**措辞**承担
                    // （「下架商品：X」、角色写成「货主」而不是 `shipper`，后者反而更好）。
                    // 但**卡片必须能区分不同的取值**：否则用户看到的两张卡一模一样，
                    // 而点下去的结果完全相反。
                    f.type == AiFieldType.BOOL -> {
                        val other = all.toMutableMap()
                        other[f.name] = if (all[f.name] == "true") "false" else "true"
                        assertTrue(
                            "${a.id} 的卡片在 ${f.name}=true / false 两种情况下长得一样（用户分不出自己点的是哪个）",
                            render(other) != text,
                        )
                    }

                    f.type == AiFieldType.ENUM -> {
                        val seen = f.enumValues.map { v ->
                            render(all.toMutableMap().also { it[f.name] = v })
                        }
                        assertEquals(
                            "${a.id} 的卡片在 ${f.name} 取不同值时长得一样：${f.enumValues}",
                            f.enumValues.size,
                            seen.toSet().size,
                        )
                    }

                    else -> assertTrue(
                        "${a.id} 的卡片上看不到 ${f.name} 的值（名字对不上，用户会看到一张空卡）",
                        text.contains(dummyFor(f)),
                    )
                }
            }
            checked++
        }
        assertTrue("一个声明式动作都没查到，这条测试等于空转", checked >= 15)
    }

    @Test
    fun `摘要不会因为字段没填而崩`() {
        // 用户只填一半是常态（比如只改单价、不动名称）。摘要里那些 `?:` 分支必须都成立。
        AiWrites.ALL.forEach { a ->
            val spec = a.crud ?: return@forEach
            val card = AiWriteCard(
                refs = spec.targets.associate { it.param to AiName(999, "某某") },
                rawValues = emptyMap(),
                keyOf = emptyMap(),
                payload = JsonObject(emptyMap()),
            )
            spec.headline(card)
            spec.details(card)
        }
    }

    // ==================================== 20. 基础资料（地址 / 联系人 / 地点 / 单位等）

    @Test
    fun `新增地址把线路两端都带上`() = runBlocking {
        val r = Rig()
        val card = ok(
            r.svc.preview(
                AiWrites.ADDRESS_CREATE,
                p("receiver" to "张三", "phone" to "13800000000", "address" to "测试路 65 号", "origin" to "东仓库"),
            ),
        )
        assertTrue(card.summary.contains("张三"))
        assertTrue(card.summary.contains("测试路 65 号"))
        r.svc.execute(card.token)
        val call = r.ds.masterCalls.single()
        assertTrue(call.contains("\"receiver_name\":\"张三\""))
        assertTrue(call.contains("\"origin_address\":\"东仓库\""))
    }

    @Test
    fun `新增地址缺收货人就拒绝`() = runBlocking<Unit> {
        val r = Rig()
        val out = rejected(r.svc.preview(AiWrites.ADDRESS_CREATE, p("address" to "测试路 1 号")))
        assertTrue(out.reason.contains("receiver"))
    }

    @Test
    fun `改地址只发改的那几项`() = runBlocking {
        val r = Rig()
        val card = ok(
            r.svc.preview(AiWrites.ADDRESS_UPDATE, p("address" to "王五 测试路 1 号", "phone" to "13900000000")),
        )
        r.svc.execute(card.token)
        val call = r.ds.masterCalls.single()
        assertTrue(call.contains("\"phone\":\"13900000000\""))
        // "只改电话"不该顺手把地址也改掉（后端 PATCH 是整体替换语义，补值由数据源负责）
        assertFalse("不该带上 detail_address：$call", call.contains("detail_address"))
    }

    @Test
    fun `记联系人同一个手机号是更新而不是新增`() = runBlocking {
        val r = Rig()
        val card = ok(
            r.svc.preview(AiWrites.CONTACT_UPSERT, p("phone" to "13700000000", "name" to "赵六")),
        )
        // 摘要上要写明"同号会更新"，否则用户以为会多出一条
        assertTrue(card.detailLines.any { it.contains("更新") })
        r.svc.execute(card.token)
        assertTrue(r.ds.masterCalls.single().startsWith("createContact"))
    }

    @Test
    fun `记联系人可以不填手机号（只报名字的人也能记）`() = runBlocking {
        val r = Rig()
        // CHG-0011：手机号选填（与 CHG-0010 的人工入口同一条下限：姓名与手机号至少填一个）
        val card = ok(r.svc.preview(AiWrites.CONTACT_UPSERT, p("name" to "工地老李")))
        // 没填号时标题不许留一个空尾巴，明细里也不许出现光秃秃的一行「手机号：」
        // 卡片正文那一行（headline）走 summary；title 是动作名「记一个联系人」
        assertEquals("记联系人：工地老李", card.summary)
        assertFalse("没填号却写了手机号那一行：${card.detailLines}", card.detailLines.any { it.startsWith("手机号") })
        r.svc.execute(card.token)
        val call = r.ds.masterCalls.single()
        assertTrue("只填姓名也要能发出去：$call", call.startsWith("createContact"))
        assertTrue("姓名要带上：$call", call.contains("工地老李"))
        // 载荷里只许有模型真给的那些键（crud 只装 values 里有值的项）—— 没填号就不许凭空造一个号
        assertFalse("没填手机号却凭空造了一个：$call", call.contains("phone"))
    }

    @Test
    fun `删挂账单位是高危并且写明欠款会失去归属`() = runBlocking {
        val r = Rig()
        val card = ok(r.svc.preview(AiWrites.ARREARS_UNIT_DELETE, p("unit" to "明辉食品商行")))
        assertEquals(AiWriteRisk.HIGH, card.risk)
        assertTrue(card.detailLines.any { it.contains("失去归属") })
    }

    @Test
    fun `新增车辆可以不带司机`() = runBlocking {
        val r = Rig()
        val card = ok(
            r.svc.preview(AiWrites.VEHICLE_CREATE, p("plate" to "豫A88888", "vehicle" to "大货车")),
        )
        // 司机是可选目标：没给就不绑，而不是拒绝整条登记
        assertTrue(card.detailLines.none { it.contains("绑定司机") })
        r.svc.execute(card.token)
        val call = r.ds.masterCalls.single()
        assertTrue(call.contains("\"plate_no\":\"豫A88888\""))
        assertTrue(call.contains("\"vehicle_type\":\"large\""))
    }

    @Test
    fun `新增车辆绑定的司机查不到时不绑而不是报错`() = runBlocking {
        val r = Rig()
        val card = ok(
            r.svc.preview(
                AiWrites.VEHICLE_CREATE,
                p("plate" to "豫A88888", "vehicle" to "小货车", "driver" to "查无此人"),
            ),
        )
        r.svc.execute(card.token)
        // allowMissing = true：查不到就是"不绑"，不会把整条登记挡下来
        assertFalse(r.ds.masterCalls.single().contains("driver_id"))
    }

    @Test
    fun `删除地址写明已下过的单不受影响`() = runBlocking {
        val r = Rig()
        val card = ok(r.svc.preview(AiWrites.ADDRESS_DELETE, p("address" to "王五 测试路 1 号")))
        assertTrue(card.detailLines.any { it.contains("不受影响") })
        // 用户的原话是「不要删了就搞不回来了」：所以**点确认之前**就要告诉他这条能撤回
        assertTrue("卡片必须写明删错了能撤回：${card.detailLines}", card.detailLines.any { it.contains("撤回") })
    }

    // ---- 撤回（v3.26）：确认之后发现做错了，得能退回去 ----

    @Test
    fun `删除地址之后能撤回并真的走了恢复端点`() = runBlocking {
        val r = Rig()
        val card = ok(r.svc.preview(AiWrites.ADDRESS_DELETE, p("address" to "王五 测试路 1 号")))
        val done = r.svc.execute(card.token)
        assertTrue("期望 Done，实际 $done", done is AiWriteOutcome.Done)
        val undoToken = (done as AiWriteOutcome.Done).undoToken
        assertNotNull("删除类动作执行完必须带撤回入口", undoToken)
        assertTrue("撤回按钮上要指名道姓", done.undoLabel!!.contains("王五"))

        // 点撤回 → **不是直接写库**，而是再弹一张普通的确认卡（走同一条写入口）
        val undoCard = ok(r.svc.offerUndo(undoToken!!))
        assertTrue("撤回卡要说清会发生什么", undoCard.detailLines.any { it.contains("伪装删除") })
        assertTrue("撤回请求体里带的是**编号**：${undoCard.payload}", undoCard.payload.toString().contains("91"))
        assertEquals("点撤回还没写任何东西", 0, r.ds.restores.size)

        // 点确认 → 真正调恢复端点
        r.svc.execute(undoCard.token)
        assertEquals(listOf("address:91"), r.ds.restores)
    }

    @Test
    fun `静默键跟着写回但不单独占一行（真机踩到的裸键）`() = runBlocking<Unit> {
        val r = Rig()
        // 改地址会顺带把坐标换成新地址的（司机靠坐标导航），所以坐标**必须一起写回**；
        // 但它是**静默键**：不该在卡上单独占一行，更不该以 `address_lat` 这种裸键出现。
        // 这一条是真机上踩出来的——卡片上真的写着
        // `address_lat: 39.983342 → 撤回到 40.0119719`，用户核对的是"终点地址"，
        // 两行英文裸键只会让人怀疑是不是改错了地方。
        r.ds.geoCodes = mapOf("上海市浦东新区世纪大道 200 号" to (31.2305 to 121.4738))
        r.ds.snapshots["address:91"] = buildJsonObject {
            put("receiver_name", "王五")
            put("phone", "13800000099")
            put("detail_address", "测试路 1 号")
            put("origin_address", JsonNull)
            put("remark", "")
            put("address_lat", "40.01197192680188")
            put("address_lng", "116.39786327434547")
        }
        val card = ok(
            r.svc.preview(
                AiWrites.ADDRESS_UPDATE,
                p("address" to "王五 测试路 1 号", "detail" to "上海市浦东新区世纪大道 200 号"),
            ),
        )
        val done = r.svc.execute(card.token) as AiWriteOutcome.Done
        val undo = ok(r.svc.offerUndo(done.undoToken!!))
        val lines = undo.detailLines.joinToString("\n")
        // ① 卡片上不留裸键（静默键不占一行）
        assertFalse("卡片上不该出现裸键 address_lat：\n$lines", lines.contains("address_lat"))
        assertFalse("卡片上不该出现裸键 address_lng：\n$lines", lines.contains("address_lng"))
        assertTrue("要写清终点地址改成什么、撤回成什么：\n$lines", lines.contains("终点地址：上海市浦东新区世纪大道 200 号 → 撤回到 测试路 1 号"))
        // ② 但**写回**的请求体里必须有坐标：只回退地址文字、留下新坐标，
        //    等于把司机导到"旧地址的文字 + 新地址的经纬度"——比不撤回更糟。
        assertEquals("40.01197192680188", undo.payload["address_lat"]?.jsonPrimitive?.content)
        assertEquals("116.39786327434547", undo.payload["address_lng"]?.jsonPrimitive?.content)
        // ③ 静默键**读不回来**的时候不静默：那会儿司机真的会被带去错地方，必须写在卡上
        r.ds.snapshots["address:91"] = buildJsonObject {
            put("receiver_name", "王五")
            put("phone", "13800000099")
            put("detail_address", "测试路 1 号")
            put("remark", "")
        }
        val card2 = ok(
            r.svc.preview(
                AiWrites.ADDRESS_UPDATE,
                p("address" to "王五 测试路 1 号", "detail" to "上海市浦东新区世纪大道 200 号"),
            ),
        )
        val done2 = r.svc.execute(card2.token) as AiWriteOutcome.Done
        val undo2 = ok(r.svc.offerUndo(done2.undoToken!!))
        val lines2 = undo2.detailLines.joinToString("\n")
        assertTrue("读不到旧坐标时必须写在卡上：\n$lines2", lines2.contains("撤不回来"))
        assertTrue("警告里也要说人话（「纬度」不是 address_lat）：\n$lines2", lines2.contains("纬度"))
        assertFalse("警告行里同样不许出现裸键：\n$lines2", lines2.contains("address_lat"))
    }

    @Test
    fun `撤回不为「原来是空的」字段给假承诺`() = runBlocking<Unit> {
        // ⛔ 2026-09-24 第 35 轮（第 25 轮 01 区 F1）：快照把空着的字段记成 `""`，而写入侧
        //    `pick` 用 `takeIf { it.isNotBlank() }` 把空串**丢掉** —— 于是"撤回"会静默什么都不做，
        //    卡片却写着"撤回到（空）"。本机活样本：`/shipper/locations` 的 `remark` 70/70 都是 ""。
        //    判据：这种字段**不许**出现在"撤回到"的承诺里（它写不回去）。
        val r = Rig()
        // 改地址要能定位到（否则 prepare 会先拒掉，测不到撤回那一段）——与上一条同一个现场
        r.ds.geoCodes = mapOf("上海市浦东新区世纪大道 200 号" to (31.2305 to 121.4738))
        r.ds.snapshots["address:91"] = buildJsonObject {
            put("receiver_name", "王五")
            put("phone", "13800000099")
            // 这次要改的就是它，而它原来是**空串**（不是 JsonNull）
            put("detail_address", "")
        }
        val card = ok(
            r.svc.preview(
                AiWrites.ADDRESS_UPDATE,
                p("address" to "王五 测试路 1 号", "detail" to "上海市浦东新区世纪大道 200 号"),
            ),
        )
        val done = r.svc.execute(card.token) as AiWriteOutcome.Done
        val msg = done.message
        // ① 不许承诺"撤回到空"：要么给不出撤回按钮，要么明确说这一项撤不回来
        assertFalse(
            "卡片不能承诺把空值撤回去（写入侧会把空串丢掉，撤回是个空转）：\n$msg",
            msg.contains("撤回到（）") || msg.contains("撤回到 )") || msg.contains("撤回到："),
        )
        // ② 挂不上撤回时必须把**两种成因**都说出来（只写"读不到这条记录"会让用户白试一次）
        assertTrue(
            "挂不上撤回的话术要把「原来是空的」这一种成因也说出来：\n$msg",
            msg.contains("原来就是空的") || msg.contains("撤不回来"),
        )
        if (msg.contains("没能挂上")) {
            assertTrue("另一种成因（读不到记录）也要在：\n$msg", msg.contains("读不到"))
            assertTrue("要说清重试也不一定成功：\n$msg", msg.contains("也会失败") || msg.contains("必然") || msg.contains("如实说"))
        }
    }

    @Test
    fun `撤回 token 只能用一次`() = runBlocking<Unit> {
        val r = Rig()
        val card = ok(r.svc.preview(AiWrites.ADDRESS_DELETE, p("address" to "王五 测试路 1 号")))
        val token = (r.svc.execute(card.token) as AiWriteOutcome.Done).undoToken!!
        ok(r.svc.offerUndo(token))
        // 连点两下「撤回」不会弹两张卡（和确认卡同一套一次性保证）
        val second = r.svc.offerUndo(token)
        assertTrue("第二次必须是 Rejected，实际 $second", second is AiWriteOutcome.Rejected)
        assertTrue((second as AiWriteOutcome.Rejected).reason.contains("失效"))
    }

    @Test
    fun `撤回也要过角色门`() = runBlocking<Unit> {
        val r = Rig()
        val card = ok(r.svc.preview(AiWrites.PRODUCTS_DELETE, p("product" to "红富士苹果")))
        val token = (r.svc.execute(card.token) as AiWriteOutcome.Done).undoToken!!
        // 换个身份来点"撤回"：货主没有删商品的权限，撤回自然也不该放行
        val shipper = AiWriteService(r.ds, r.store, actorProvider = { AiActor.byRole(AiRole.SHIPPER) })
        val out = shipper.offerUndo(token)
        assertTrue("货主不能撤回派单员的商品删除，实际 $out", out is AiWriteOutcome.Rejected)
        assertTrue(r.ds.restores.isEmpty())
    }

    @Test
    fun `撤不回来的动作在卡片上就写明理由`() = runBlocking {
        val r = Rig()
        // 发消息撤不回来（已经到对方手机上了）——这句话必须出现在**点确认之前**的卡上
        val card = ok(
            r.svc.preview(
                AiWrites.NOTIFICATIONS_SEND,
                p("to" to "张三", "title" to "明天到货", "content" to "早上八点到"),
            ),
        )
        assertTrue("卡片要写明撤不回来：${card.detailLines}", card.detailLines.any { it.contains("撤不回来") })
    }

    @Test
    fun `每一个动作都必须回答误操作了怎么办`() {
        // 用户的原话是「不要删了就搞不回来了」。所以"能不能撤回"是**每个动作都要回答的问题**：
        // 要么挂在一个**资源**下（[AiResources] 里声明过，撤回由框架推导），
        // 要么在 [AiRevert] 的 UNDO_NONE 里**逐条**写明为什么不能。
        // 两者缺一 = 这个动作在"误操作了怎么办"这件事上没交代 → 这条断言红。
        val missing = AiWrites.ALL.filter { AiWrites.undoNoneOf(it.id) == null && !AiWrites.undoCapableOf(it.id) }
        assertTrue("这些动作既不能撤回、也没写为什么：${missing.map { it.id }}", missing.isEmpty())
        // 反向：两边都写了的（既说能撤回、又给了一条"撤不回来"的理由）也是自相矛盾
        val both = AiWrites.ALL.filter { AiWrites.undoNoneOf(it.id) != null && AiWrites.undoCapableOf(it.id) }
        assertTrue("这些动作既说能撤回、又写了撤不回来的理由：${both.map { it.id }}", both.isEmpty())
    }

    @Test
    fun `撤不回来的理由必须一条一句，不许一句万能话糊住一批动作`() {
        // v3.26 的教训：三十多个"改类"动作共用同一句话（"说一句照上面改回去就行"）。
        // 那看着像交代，其实是把三十个性质不同的问题用一句万能答复盖过去——
        // 钱已经付出去的、密码只存哈希的、消息已经到别人手机上的，后果完全不一样。
        //
        // 所以这条断言给"共用"设一个上限：**同一条理由最多覆盖 2 个动作**。
        // 真属于同一件事的（发消息 / 已读标记）本来就是一对，超过两个就该拆开写。
        //
        // ⚠️ 唯一放行的是**新建类兜底**那一句：它的后果**确实是同一句话**
        //    （建错了就改/停用/删掉），和"改类"那句的区别在于后者把后果完全不同的
        //    动作糊在一起。所以这里不是把它排除掉，而是**要求它只出现在新建类上**。
        val byReason = AiWrites.ALL.filter { !AiWrites.undoCapableOf(it.id) }
            .mapNotNull { a -> AiWrites.undoNoneOf(a.id)?.let { it to a.id } }
            .groupBy({ it.first }, { it.second })
        // 新建类那一句（拿一个确定是新建的动作把它取出来，而不是把整句话抄一遍）
        val createLikeReason = AiRevert.blockedReason(AiWrites.PRODUCTS_CREATE)
        val tooMany = byReason.filterKeys { it != createLikeReason }.filterValues { it.size > 2 }
        assertTrue("这些理由一句糊住了太多动作，请逐条写清后果：$tooMany", tooMany.isEmpty())
        val abused = byReason[createLikeReason].orEmpty().filterNot { AiRevert.isCreateLikeForTest(it) }
        assertTrue("「新建类」那句兜底被用在了非新建类动作上：$abused", abused.isEmpty())
        // 反向：不能反过来把动作都改成"没理由"——那上面那条会红，这里再钉一次数量下限
        assertTrue("能撤回的动作太少了（重构把撤回弄丢了？）", AiWrites.UNDO_CAPABLE.size >= 30)
    }

    @Test
    fun `换司机：绑与解绑两个方向都必须真的挂上撤回（真机抓到的自逆 bug）`() = runBlocking {
        // 真机现象（v3.44 E2E，D9/D10）：`vehicle.set_driver` 执行完那条消息上**没有撤回按钮**，
        // 只回一句「⚠️ 这次没能挂上「撤回」：写之前读不到这条记录现在的样子…」。
        // 根因是资源表把它声明成 `paired(它自己, AiInverse(它自己, …))`，而
        // `AiRevert.pairedPlan` 第一行就是 `if (inverse.actionId == entry.id) return null`
        // ——"逆操作是自己"根本不成立，撤回方案**永远造不出来**；偏偏 `canRevert()` 返回 true，
        // 所以卡片敢印「会出现『撤回』」。全库 16 处 paired 只有那一处是自逆。
        //
        // 这条断言同时钉住两件事，缺一条这个 bug 就能复活：
        //   ① 绑的那次能撤回（把司机写回旧值，包括"原来是没人"）；
        //   ② **解绑的那次也能撤回**（payload 里必须带上 driver_id=null，否则没有键可写回）。
        val r = Rig()
        r.ds.vehicles = listOf(AiName(21, "豫A12345", note = "李强"), AiName(22, "豫B67890", note = "没有司机"))
        // 撤回要读"写之前的现场"（`AiResource.read` → `ds.snapshot("vehicle", id)`）：
        // 替身不给这两条，撤回会走 fail-closed（读不到就不给按钮）——那样这条断言测的就是空气。
        r.ds.snapshots["vehicle:21"] = buildJsonObject {
            put("plate_no", "豫A12345")
            put("vehicle_type", "trailer")
            put("driver_id", 13)
            put("active", true)
        }
        r.ds.snapshots["vehicle:22"] = buildJsonObject {
            put("plate_no", "豫B67890")
            put("vehicle_type", "trailer")
            put("driver_id", JsonNull)   // 原来没绑司机
            put("active", true)
        }

        // ① 先从"没有人"绑给王建国 → 撤回 = 解绑
        val bind = ok(r.svc.preview(AiWrites.VEHICLE_SET_DRIVER, p("vehicle" to "豫B67890", "driver" to "王建国")))
        val bindDone = r.svc.execute(bind.token) as AiWriteOutcome.Done
        assertNotNull("绑完必须带撤回入口", bindDone.undoToken)
        val undo1 = ok(r.svc.offerUndo(bindDone.undoToken!!))
        assertEquals("撤回要把司机改回「没人」", JsonNull, undo1.payload["driver_id"])
        r.svc.execute(undo1.token)
        assertEquals("setVehicleDriver:22:null", r.ds.masterCalls.last())

        // ② 再把有人的那辆解绑 → 撤回 = 把原来那位绑回去
        val un = ok(r.svc.preview(AiWrites.VEHICLE_SET_DRIVER, p("vehicle" to "豫A12345")))
        val unDone = r.svc.execute(un.token) as AiWriteOutcome.Done
        assertNotNull("解绑同样必须带撤回入口（payload 里没有 driver_id 的话这里就是 null）", unDone.undoToken)
        val undo2 = ok(r.svc.offerUndo(unDone.undoToken!!))
        assertEquals("撤回要把李强绑回去", "13", undo2.payload["driver_id"]?.jsonPrimitive?.content)
        // **卡片上不许出现以冒号结尾却没有下文的行**（真机 E2E 报告点出来的：
        // 关联司机是静默键，于是那句"把这几项改回写之前的值（…）："后面一行明细都没有，
        // 读起来像内容被吞了）。判据对所有撤回卡都成立，所以钉在这里当通用哨兵。
        val dangling = undo2.detailLines.filter { it.trim().endsWith("：") }
        assertTrue("撤回卡不该有以冒号结尾的空标题行：$dangling", dangling.isEmpty())
        assertTrue(
            "静默键也要印出中文名（否则用户不知道撤回会动哪一项）：${undo2.detailLines}",
            undo2.detailLines.any { it.contains("关联司机") },
        )
        r.svc.execute(undo2.token)
        assertEquals("setVehicleDriver:21:13", r.ds.masterCalls.last())
    }

    @Test
    fun `没有哪个动作把逆操作声明成它自己（那样撤回永远造不出来）`() {
        // 上一条 bug 的**结构性**判据：`pairedPlan` 的第一行就排除了自逆，
        // 所以"逆操作 = 自己"这种声明一定造不出撤回方案（而卡片照样敢承诺。
        // 组合起来的效果是：用户点了确认，回来一句"这次没能挂上撤回"——比没有撤回更糟）。
        // 扫的是唯一接线处 [AiResources]，新增资源时自动被覆盖。
        val selfInverse = AiResources.TABLE.flatMap { res ->
            res.actions.mapNotNull { a -> a.inverse?.takeIf { it.actionId == a.id }?.let { "${res.key}:${a.id}" } }
        }
        assertTrue("这些动作的逆操作指向了它自己（撤回永远造不出来）：$selfInverse", selfInverse.isEmpty())
        // 反空转：真的扫到了成对动作（全删光的话上面那条就恒真了）
        val pairedCount = AiResources.TABLE.sumOf { res -> res.actions.count { it.inverse != null } }
        assertTrue("成对动作一个都没扫到（这条检查在空转）", pairedCount >= 10)
    }

    @Test
    fun `删除类动作一个都不能少地能撤回`() {
        // 用户最怕的是"删了就没了"，所以删除类单独再加一条更强的断言：
        // 主数据、商品、账号、订单这几张表**必须**能撤回。
        val must = listOf(
            AiWrites.ADDRESS_DELETE, AiWrites.LOCATION_DELETE, AiWrites.CONTACT_DELETE,
            AiWrites.ARREARS_UNIT_DELETE, AiWrites.FREIGHT_TEMPLATE_DELETE,
            AiWrites.PRODUCTS_DELETE, AiWrites.USERS_DELETE, AiWrites.ORDERS_SOFT_DELETE,
            // 专属价没有 `/{id}/restore` 端点，但它的恢复动作是"再设一次同样的价"
            // （后端会复活软删那一行）——所以它也在这一批里。
            AiWrites.PRICE_RULES_DELETE,
        )
        val bad = must.filterNot { AiWrites.undoCapableOf(it) }
        assertTrue("这些删除动作撤不回来：$bad", bad.isEmpty())
        // 反向：**每个资源的恢复动作都必须真实存在**，否则撤回按钮点下去只会报"没有执行入口"。
        // 这条以前靠扫源码里的 `undoAction = …`，现在扫的是唯一的接线处（[AiResources]）。
        val dangling = AiResources.TABLE.mapNotNull { r ->
            r.restore?.actionId?.takeIf { AiWrites.byId(it) == null }?.let { "${r.key} -> $it" }
        }
        assertTrue("撤回指向了不存在的动作：$dangling", dangling.isEmpty())
    }

    @Test
    fun `每个资源的动作清单和读回键必须自洽`() {
        // 这个模块能成立，全靠两件**声明**对得上：
        // ① `labels + silent` 正好等于 `readKeys`——差一个就说明有键在静默地进/出，
        //    而"静默"在这里的表现是"撤回时那一项没写回去"，用户以为撤干净了；
        // ② 每个声明过的动作都真的在注册表里（不然挂上去也调不到）。
        for (r in AiResources.TABLE) {
            assertEquals(
                "${r.key}：labels + silent 必须正好等于 readKeys",
                r.readKeys,
                r.labels.keys + r.silent,
            )
            assertTrue("${r.key} 一个动作都没挂（这条断言会空转）", r.actions.size >= 1)
            for (a in r.actions) {
                assertNotNull("${r.key} 挂了不存在的动作 ${a.id}", AiWrites.byId(a.id))
            }
        }
        assertTrue("资源太少了（重构把资源表弄丢了？）", AiResources.TABLE.size >= 12)
    }

    @Test
    fun `撤回卡不说「这一步撤不回来」（真机抓到的自相矛盾）`() = runBlocking {
        // 真机原样（删批发商专属价 → 点撤回）：
        //     撤回：把批发商专属价恢复回来            ← 标题说这是「撤回」
        //     ⚠️ 这一步撤不回来：新建出来的那一条撤不掉…   ← 却告诉用户「这一步撤不回来」
        // 根因：卡片最后一行由暂存区按 **actionId** 统一拼，而撤回走的是另一个动作
        // （`price_rules.set` 是"新建类"）→ 把那句话原样搬到了撤回卡上。
        val r = Rig()
        r.ds.snapshots["price_rule:81"] = buildJsonObject {
            put("shipper_id", "31")
            put("product_id", "41")
            put("special_unit_price", "4.50")
        }
        val card = ok(r.svc.preview(AiWrites.PRICE_RULES_DELETE, p("rule" to "城东水果批发 红富士苹果 = 4.5")))
        val done = r.svc.execute(card.token) as AiWriteOutcome.Done
        val undoCard = ok(r.svc.offerUndo(done.undoToken!!))

        val lines = undoCard.detailLines
        assertTrue("撤回卡没写「撤回」两个字：${undoCard.summary}", undoCard.summary.contains("撤回"))
        assertTrue(
            "撤回卡上又出现了「这一步撤不回来」这种自相矛盾的话：$lines",
            lines.none { it.contains("这一步撤不回来") },
        )
        assertTrue(
            "撤回卡最后一行应当说的是「这次撤回本身能不能再反悔」：$lines",
            lines.any { it.contains("这次撤回") },
        )
        // 而**普通**卡片仍然要照旧回答"误操作了怎么办"
        val plain = ok(r.svc.preview(AiWrites.PRICE_RULES_DELETE, p("rule" to "城东水果批发 红富士苹果 = 4.5")))
        assertTrue(
            "普通卡片丢掉了「误操作了怎么办」那一行：${plain.detailLines}",
            plain.detailLines.any { it.contains("误操作了不要紧") || it.contains("撤不回来") },
        )
    }

    @Test
    fun `撤回卡上的每个 payload 键都要有中文名（真机抓到过 change 与 note）`() {
        // 真机 E2E 打出来的两行（模拟器 5554，库存调整 → 撤回）：
        //     · change：5 → 撤回到 -5
        //     · 「note」不写回（…）
        // 原因不是"漏写了两条 label"，而是**中文名的来源不对**：上一条断言把资源表的
        // `labels` 钉成 readKeys（那条是对的——它管的是"**读回来**的东西叫什么"），
        // 而 payload 里有一批**读不回来的键**（库存的增减量从来不在商品快照里），
        // 于是它们永远查不到中文名，永远以裸英文键印给用户。
        // 现在中文名有两处来源（资源表 → 动作声明的字段规格，见 AiRevert.cnOf）：
        // 这条断言把**清单自己算出来**——遍历资源表 × 每个动作的声明式规格，
        // 逐个 payload 键问一遍"它在卡片上叫什么"，不是中文就报红。
        val cjk = Regex("[\\u4e00-\\u9fff]")
        var scanned = 0
        val bad = mutableListOf<String>()
        for (r in AiResources.TABLE) {
            for (a in r.actions) {
                val spec = AiWrites.byId(a.id)?.crud ?: continue
                for (k in spec.targets.map { it.key } + spec.fields.map { it.key }) {
                    // 主键那一项不单独占一行（卡片按编号定位，印出来也没法核对）
                    if (k == a.keyIn(r)) continue
                    scanned++
                    val cn = AiRevert.cnOf(r, a.id, k)
                    if (!cjk.containsMatchIn(cn)) bad += "${r.key}:${a.id}:$k → $cn"
                }
            }
        }
        assertTrue("一个 payload 键都没扫到（这条断言在空转）", scanned >= 40)
        assertTrue("这些键在撤回卡上会印成裸英文键：$bad", bad.isEmpty())

        // 具体到真机那一条：要的是**这两个词**，不是"有中文就行"
        val product = AiResources.TABLE.first { it.key == "product" }
        assertEquals("增减量", AiRevert.cnOf(product, AiWrites.INVENTORY_ADJUST, "change"))
        assertEquals("原因备注", AiRevert.cnOf(product, AiWrites.INVENTORY_ADJUST, "note"))
        // 资源表那份优先：同一个键在字段规格里可能叫别的（"新商品名"），卡片上该用资源表那个
        assertEquals("商品名", AiRevert.cnOf(product, AiWrites.PRODUCTS_UPDATE, "name"))
    }

    @Test
    fun `改类动作能一键撤回：撤回就是同一个动作写回旧值`() = runBlocking {
        val r = Rig()
        // 写之前的现场：单价 8.00、名字「红富士苹果」
        r.ds.snapshots["product:41"] = buildJsonObject {
            put("name", "红富士苹果")
            put("default_unit_price", "8.00")
            put("unit", "件")
            put("low_stock_alert", "0")
            put("active", "true")
        }
        val card = ok(r.svc.preview(AiWrites.PRODUCTS_UPDATE, p("product" to "红富士苹果", "price" to "12.00")))
        val done = r.svc.execute(card.token) as AiWriteOutcome.Done
        r.ds.masterCalls.clear()

        val undoToken = done.undoToken
        assertNotNull("改类动作现在也必须能撤回（v3.27 起全部接入）", undoToken)
        assertTrue("撤回按钮上要指名道姓：${done.undoLabel}", done.undoLabel!!.contains("红富士苹果"))

        val undoCard = ok(r.svc.offerUndo(undoToken!!))
        // 卡片必须写清"改成多少"（用户核对的就是这一行），而不是一句"改回原样"
        assertTrue("撤回卡要写清会改成什么：${undoCard.detailLines}", undoCard.detailLines.any { it.contains("撤回到 8") })
        assertTrue("撤回卡要写清现在是什么：${undoCard.detailLines}", undoCard.detailLines.any { it.contains("：12 → 撤回到 8") })
        assertEquals("点撤回还没写任何东西", 0, r.ds.masterCalls.size)

        // 点确认 → 走的是**同一个动作**（products.update），带的是旧值
        r.svc.execute(undoCard.token)
        val call = r.ds.masterCalls.single()
        assertTrue("撤回该走 updateProduct：$call", call.startsWith("updateProduct:41:"))
        assertTrue("要把旧单价写回去：$call", call.contains("\"default_unit_price\":\"8.00\""))
        // ⚠️ 只回写"这次会改的键"：这单没改名字，就不许碰名字
        assertFalse("撤回不该顺手改别的字段：$call", call.contains("\"name\""))
    }

    @Test
    fun `撤回之后发现又错了：撤回本身也能再撤回`() = runBlocking {
        val r = Rig()
        // 「撤回的撤回」不是特意做的，是"撤回＝普通动作"这个形状白送的。
        // 这一条钉的就是那个性质：它不该在重构里丢掉。
        r.ds.snapshots["product:41"] = buildJsonObject { put("default_unit_price", "8.00") }
        val card = ok(r.svc.preview(AiWrites.PRODUCTS_UPDATE, p("product" to "红富士苹果", "price" to "12.00")))
        val first = r.svc.execute(card.token) as AiWriteOutcome.Done
        val undoCard = ok(r.svc.offerUndo(first.undoToken!!))
        val undone = r.svc.execute(undoCard.token) as AiWriteOutcome.Done
        assertNotNull("撤回执行完还得再挂一个撤回入口（否则来回退不了）", undone.undoToken)
        assertTrue("按钮上要说清撤回的是什么：${undone.undoLabel}", undone.undoLabel!!.contains("撤回"))
        // 标题不许套娃：真机上出现过「改回原样（改回原样（改商品：红富士苹果））」——
        // 用户读不出这一次到底要改成什么（区分靠的是明细里那行 `12.00 → 撤回到 8.00`）。
        val again = ok(r.svc.offerUndo(undone.undoToken!!))
        assertFalse("标题不许嵌套：${again.summary}", again.summary.contains("改回原样（撤回"))
        assertEquals(1, Regex("改回原样").findAll(again.summary).count())
    }

    @Test
    fun `撤回卡会提醒这条在操作之后又被改过`() = runBlocking {
        val r = Rig()
        r.ds.snapshots["product:41"] = buildJsonObject { put("default_unit_price", "8.00") }
        val card = ok(r.svc.preview(AiWrites.PRODUCTS_UPDATE, p("product" to "红富士苹果", "price" to "12.00")))
        val done = r.svc.execute(card.token) as AiWriteOutcome.Done
        // 中间别人（或用户自己）把价改成了 15.00：撤回会把 15.00 一起盖掉，用户必须知道
        r.ds.snapshots["product:41"] = buildJsonObject { put("default_unit_price", "15.00") }
        r.ds.masterCalls.clear()

        val undoCard = ok(r.svc.offerUndo(done.undoToken!!))
        val warn = undoCard.detailLines.firstOrNull { it.contains("盖掉") }
        assertNotNull("这条被人改过就必须说：${undoCard.detailLines}", warn)
        assertTrue("要说清现在是多少：$warn", warn!!.contains("现在是 15"))
        assertTrue("也要说清撤回会写成多少：$warn", warn.contains("撤回会写成 8"))
        assertEquals("提醒不是拦截：撤回照样能点", 0, r.ds.masterCalls.size)
    }

    @Test
    fun `数值进制不同不算「被改过」（真机踩到的误报）`() = runBlocking {
        val r = Rig()
        // 真机现场：App 写进去的是 "12.00"，后端把 Decimal 读回来是 "12.0000"。
        // 按字符串比这两个永远不等 → **每一张撤回卡都会报"被改过"** →
        // 用户学会无视这行警告，而这行警告存在的唯一理由就是让他看见真被改过的那次。
        r.ds.snapshots["product:41"] = buildJsonObject { put("default_unit_price", "8.0000") }
        val card = ok(r.svc.preview(AiWrites.PRODUCTS_UPDATE, p("product" to "红富士苹果", "price" to "12.00")))
        val done = r.svc.execute(card.token) as AiWriteOutcome.Done
        r.ds.snapshots["product:41"] = buildJsonObject { put("default_unit_price", "12.0000") }

        val undoCard = ok(r.svc.offerUndo(done.undoToken!!))
        assertTrue(
            "同一个数写成 12.00 / 12.0000 不该报警：${undoCard.detailLines}",
            undoCard.detailLines.none { it.contains("盖掉") },
        )
        // 卡片上的金额按两位小数写（「撤回到 8.00」而不是「撤回到 8.0000」）
        assertTrue(
            "金额要写成 8.00：${undoCard.detailLines}",
            undoCard.detailLines.any { it.contains("撤回到 8") && !it.contains("8.0000") },
        )
    }

    @Test
    fun `删除类撤回卡不带「又被改过」探针（那条正躺在回收站里，读不到是正常的）`() = runBlocking {
        val r = Rig()
        val card = ok(r.svc.preview(AiWrites.ADDRESS_DELETE, p("address" to "王五 测试路 1 号")))
        val done = r.svc.execute(card.token) as AiWriteOutcome.Done
        // 故意把现场清空：删除之后那条「读不到」是**正常的**，不该变成一句狼来了
        r.ds.snapshots.clear()
        val undoCard = ok(r.svc.offerUndo(done.undoToken!!))
        assertTrue(
            "删除撤回卡上不该出现「读不到这一条」这种吓人的话：${undoCard.detailLines}",
            undoCard.detailLines.none { it.contains("读不到这一条") },
        )
    }

    @Test
    fun `读不到写之前的现场就不给撤回按钮，而且事后必须说`() = runBlocking {
        val r = Rig()
        // 没摆现场 = 读不到（线上对应"这条已经被别人删了 / 这个账号看不到"）
        val card = ok(r.svc.preview(AiWrites.PRODUCTS_UPDATE, p("product" to "红富士苹果", "price" to "12.00")))
        val done = r.svc.execute(card.token) as AiWriteOutcome.Done
        assertNull("读不到旧值就不该给按钮（给了也点不动）", done.undoToken)
        // 但卡片上**答应过**会出现撤回，所以这里必须如实说清为什么没有
        assertTrue("必须如实交代为什么没挂上撤回：${done.message}", done.message.contains("没能挂上「撤回」"))
    }

    @Test
    fun `改订单运费能一键撤回`() = runBlocking {
        val r = Rig()
        r.ds.snapshots["order:62"] = buildJsonObject { put("freight_fee", "300.00") }
        val card = ok(
            r.svc.preview(AiWrites.ORDERS_FREIGHT, p("order" to "SOTEST2026091200229", "freight" to "500.00")),
        )
        val done = r.svc.execute(card.token) as AiWriteOutcome.Done
        // 替身不会自己"写进去"，所以要手动把它推到写完之后的样子——不然撤回卡的
        // "又被改过"探针会拿"写之前的 300"去比，那是在测替身，不是在测代码。
        r.ds.snapshots["order:62"] = buildJsonObject { put("freight_fee", "500.00") }
        r.ds.orderCalls.clear()
        val undoCard = ok(r.svc.offerUndo(done.undoToken!!))
        assertTrue(
            "撤回卡要写清运费改成多少：${undoCard.detailLines}",
            undoCard.detailLines.any { it.contains("撤回到 300") },
        )
        r.svc.execute(undoCard.token)
        assertEquals(listOf("freight:62:300.00"), r.ds.orderCalls)
    }

    @Test
    fun `派单的撤回现在由资源表推导（不再是手写的）`() = runBlocking {
        val r = Rig()
        // 派单的逆操作是"撤回派单"这个**另一个动作**——不是"把司机栏改回去"。
        r.ds.snapshots["order:61"] = buildJsonObject { put("driver_id", "12") }
        val card = ok(
            r.svc.preview(AiWrites.ORDERS_ASSIGN, p("order" to "SOTEST2026091100230", "driver" to "李强")),
        )
        val done = r.svc.execute(card.token) as AiWriteOutcome.Done
        r.ds.orderCalls.clear()
        val undoCard = ok(r.svc.offerUndo(done.undoToken!!))
        assertTrue("要说清撤回派单会发生什么", undoCard.detailLines.any { it.contains("退回「待派单」") })
        r.svc.execute(undoCard.token)
        assertTrue("撤回该走 recall：${r.ds.orderCalls}", r.ds.orderCalls.single().startsWith("recall:61:"))
    }

    @Test
    fun `撤回派单的撤回是照原样再派一次`() = runBlocking {
        val r = Rig()
        // 撤回派单之后想反悔：司机、运费、收款方式都从"撤回时抓的现场"里搬回来
        r.ds.snapshots["order:62"] = buildJsonObject {
            put("driver_id", "13")
            put("freight_fee", "180.00")
            put("collect_cash", "true")
            put("internal_note", "上午送到")
        }
        val card = ok(r.svc.preview(AiWrites.ORDERS_RECALL, p("order" to "SOTEST2026091200229", "reason" to "派错了")))
        val done = r.svc.execute(card.token) as AiWriteOutcome.Done
        r.ds.orderCalls.clear()
        val undoCard = ok(r.svc.offerUndo(done.undoToken!!))
        r.svc.execute(undoCard.token)
        val assign = r.ds.lastAssign
        assertNotNull("该重新派一次：${r.ds.orderCalls}", assign)
        assertEquals(62L, assign!![0])
        assertEquals(13L, assign[1])
        assertEquals("180.00", assign[3])
        assertEquals(true, assign[4])
    }

    @Test
    fun `删掉一行商品能加回来，并且说明新行编号不一样`() = runBlocking {
        val r = Rig()
        // 假替身里 62 号单的皇冠梨是 902 行、2 件、单价 50.00
        r.ds.snapshots["order_line:902"] = buildJsonObject {
            put("order_id", "62")
            put("product", "皇冠梨")
            put("product_name", "皇冠梨")
            put("quantity", "2")
            put("unit_price", "50.00")
        }
        val card = ok(r.svc.preview(AiWrites.ORDERS_DELETE_LINE, p("order" to "SOTEST2026091200229", "product" to "皇冠梨")))
        val done = r.svc.execute(card.token) as AiWriteOutcome.Done
        r.ds.lineCalls.clear()
        val undoCard = ok(r.svc.offerUndo(done.undoToken!!))
        assertTrue(
            "必须写明这是硬删、新行编号不同：${undoCard.detailLines}",
            undoCard.detailLines.any { it.contains("硬删") },
        )
        r.svc.execute(undoCard.token)
        assertEquals(listOf("addLine:62:皇冠梨:2:50.00"), r.ds.lineCalls)
    }

    @Test
    fun `库存调整的撤回是记一条反向流水，不是把库存改回去`() = runBlocking {
        val r = Rig()
        r.ds.snapshots["product:41"] = buildJsonObject { put("name", "红富士苹果") }
        val card = ok(r.svc.preview(AiWrites.INVENTORY_ADJUST, p("product" to "红富士苹果", "change" to "+50", "note" to "到货")))
        val done = r.svc.execute(card.token) as AiWriteOutcome.Done
        r.ds.masterCalls.clear()
        val undoCard = ok(r.svc.offerUndo(done.undoToken!!))
        assertTrue(
            "要说清这是「再记一条相反的」而不是改库存：${undoCard.detailLines}",
            undoCard.detailLines.any { it.contains("相反方向") },
        )
        r.svc.execute(undoCard.token)
        // 原来是 +50，撤回就是 -50。
        // ⚠️ 备注**不搬旧那句**（旧那句说的是"上一次为什么入库"），但**必须补一句新的**：
        //    这里以前断言的是 `movement:41:-50:`（备注空）—— 那条断言把真机上抓到的缺陷
        //    钉成了"预期行为"（库里真出现过 note='' 的反向流水，事后没人说得清那 5 件是怎么少的）。
        assertEquals(
            listOf("movement:41:-50:撤回：刚才那次库存调整（由撤回入口发起）"),
            r.ds.masterCalls,
        )
        // 卡片上要写明它会写什么字，以及旧备注去哪了（用户点确认前就能核对）
        assertTrue(
            "卡片要写清这条流水上会留什么原因：${undoCard.detailLines}",
            undoCard.detailLines.any { it.contains("不搬原来那句") && it.contains("由撤回入口发起") },
        )
        // 而且不许写成「撤回到 一句新原因」——那句话读不通（反向验证那次注入打出来过这行）。
        // 分辨"撤回成旧值"与"补一句新的"就是这里的分界线。
        assertTrue(
            "把「补一句新原因」写成了「撤回到 新原因」：${undoCard.detailLines}",
            undoCard.detailLines.none { "撤回到" in it && "撤回：" in it.substringAfter("撤回到") },
        )
        // 两行不许再印同一个键名（真机上 `change` / `note` 两个裸键就是这么被看见的）
        assertTrue(
            "撤回卡上又出现了裸英文键：${undoCard.detailLines.filter { it.contains("change") || it.contains("note") }}",
            undoCard.detailLines.none { it.contains("change：") || it.contains("「note」") || it.contains("· note") },
        )
    }

    @Test
    fun `专属价删掉之后靠再设一次同样的价来恢复`() = runBlocking {
        val r = Rig()
        r.ds.snapshots["price_rule:81"] = buildJsonObject {
            put("shipper_id", "31")
            put("product_id", "41")
            put("special_unit_price", "4.50")
        }
        val card = ok(r.svc.preview(AiWrites.PRICE_RULES_DELETE, p("rule" to "城东水果批发 红富士苹果 = 4.5")))
        val done = r.svc.execute(card.token) as AiWriteOutcome.Done
        r.ds.masterCalls.clear()
        val undoCard = ok(r.svc.offerUndo(done.undoToken!!))
        assertTrue(
            "要说清是复活原来那一行：${undoCard.detailLines}",
            undoCard.detailLines.any { it.contains("复活") },
        )
        r.svc.execute(undoCard.token)
        assertEquals(listOf("createPriceRule:31:41:4.50"), r.ds.masterCalls)
    }


    @Test
    fun `恢复动作不进模型清单`() {
        // 被软删的记录不在名册里，模型按名字一定解析不到——放进清单就是"能看见但一定失败"
        val modelIds = AiWrites.forModel(AiActor.byRole(AiRole.DISPATCHER)).map { it.id }
        val undoOnlyIds = AiWrites.ALL.filter { it.undoOnly }.map { it.id }
        assertTrue("undoOnly 动作不该是空的（否则这条断言在空转）", undoOnlyIds.size >= 7)
        assertTrue(
            "撤回专用动作漏进了模型清单：${undoOnlyIds.filter { it in modelIds }}",
            undoOnlyIds.none { it in modelIds },
        )
        // 但权限门认识它们（撤回要过 allows）
        assertTrue(AiWrites.allows(AiActor.byRole(AiRole.DISPATCHER), AiWrites.ADDRESS_RESTORE))
    }

    // ---- 坐标（v3.24）：AI 没有人点地图，坐标得自己去高德换 ----

    @Test
    fun `新增地址会把地址换成坐标一起写进去`() = runBlocking {
        val r = Rig()
        // 没有这一步，AI 建的地址就没有坐标：司机在订单详情点「高德导航」只会打开高德首页
        r.ds.geoCodes = mapOf("上海市浦东新区世纪大道 100 号" to (31.2304 to 121.4737))
        val card = ok(
            r.svc.preview(AiWrites.ADDRESS_CREATE, p("receiver" to "张三", "address" to "上海市浦东新区世纪大道 100 号")),
        )
        r.svc.execute(card.token)
        val call = r.ds.masterCalls.single()
        assertTrue("坐标要进请求体：$call", call.contains("\"address_lat\":\"31.2304\""))
        assertTrue("坐标要进请求体：$call", call.contains("\"address_lng\":\"121.4737\""))
        // 定位到了就没什么好提醒的（卡片上多一行废话 = 用户开始不读卡片）
        assertTrue(card.detailLines.none { it.contains("没在地图上定位到") })
    }

    @Test
    fun `新增地址定位不到时照样能建但卡片必须写明导航会失灵`() = runBlocking {
        val r = Rig()
        // 默认替身一条都定位不到。地址本身还是真的，所以不拦——但后果必须写在卡上，
        // 否则用户是在司机打电话说"导航找不到地方"时才知道。
        val card = ok(r.svc.preview(AiWrites.ADDRESS_CREATE, p("receiver" to "张三", "address" to "东边那个仓库")))
        assertTrue(card.detailLines.any { it.contains("没在地图上定位到") })
        r.svc.execute(card.token)
        val call = r.ds.masterCalls.single()
        assertFalse("没坐标就不要塞空键：$call", call.contains("address_lat"))
    }

    @Test
    fun `只改电话时不去查高德`() = runBlocking {
        val r = Rig()
        val card = ok(
            r.svc.preview(AiWrites.ADDRESS_UPDATE, p("address" to "王五 测试路 1 号", "phone" to "13900000000")),
        )
        // 没动地址文字就没有必要查——白查一次就是白等一次（卡片会慢半秒）
        assertTrue(r.ds.geoCalls.isEmpty())
        r.svc.execute(card.token)
        assertTrue(r.ds.masterCalls.single().contains("\"phone\":\"13900000000\""))
    }

    @Test
    fun `改地址定位不到就拒绝而不是留下旧坐标`() = runBlocking<Unit> {
        val r = Rig()
        // 这条是**防司机被带到旧地址**的：后端 PATCH 是 `if address_lat is not None` 语义，
        // 传 null 清不掉旧坐标。照改的话库里会留着上一条地址的坐标，导航照旧指向老地方。
        val out = rejected(
            r.svc.preview(AiWrites.ADDRESS_UPDATE, p("address" to "王五 测试路 1 号", "detail" to "东边那个仓库")),
        )
        assertTrue("要说清为什么拒绝：${out.reason}", out.reason.contains("上一版"))
        assertTrue(r.ds.masterCalls.isEmpty())
    }

    @Test
    fun `改地址定位到了就把新坐标一起写进去`() = runBlocking {
        val r = Rig()
        r.ds.geoCodes = mapOf("上海市浦东新区世纪大道 200 号" to (31.2305 to 121.4738))
        val card = ok(
            r.svc.preview(AiWrites.ADDRESS_UPDATE, p("address" to "王五 测试路 1 号", "detail" to "上海市浦东新区世纪大道 200 号")),
        )
        r.svc.execute(card.token)
        val call = r.ds.masterCalls.single()
        assertTrue(call.contains("\"detail_address\":\"上海市浦东新区世纪大道 200 号\""))
        assertTrue(call.contains("\"address_lat\":\"31.2305\""))
    }

    @Test
    fun `新增地点也会换坐标`() = runBlocking {
        val r = Rig()
        r.ds.geoCodes = mapOf("北京市朝阳区建国路 1 号" to (39.9087 to 116.4574))
        val card = ok(
            r.svc.preview(AiWrites.LOCATION_CREATE, p("name" to "东仓库", "address" to "北京市朝阳区建国路 1 号")),
        )
        r.svc.execute(card.token)
        val call = r.ds.masterCalls.single()
        assertTrue("地点也要有坐标（拼线路时要用）：$call", call.contains("\"address_lat\":\"39.9087\""))
    }

    @Test
    fun `新建订单会把送货地址换成坐标`() = runBlocking {
        val r = Rig()
        r.ds.geoCodes = mapOf("测试收货地址 65 号" to (31.2 to 121.4))
        val card = ok(
            r.svc.preview(
                AiWrites.ORDERS_CREATE,
                createParams(
                    "城东水果批发",
                    lineJson(Triple("红富士苹果", 2, "5.00")),
                    address = "测试收货地址 65 号",
                ),
            ),
        )
        r.svc.execute(card.token)
        val req = r.ds.createdOrders.single()
        assertEquals("31.2", req.addressLat)
        assertEquals("121.4", req.addressLng)
    }

    @Test
    fun `新建订单定位不到时卡片写明司机导航会落到高德首页`() = runBlocking {
        val r = Rig()
        val card = ok(
            r.svc.preview(
                AiWrites.ORDERS_CREATE,
                createParams(
                    "城东水果批发",
                    lineJson(Triple("红富士苹果", 2, "5.00")),
                    address = "测试收货地址 65 号",
                ),
            ),
        )
        assertTrue(card.detailLines.any { it.contains("高德首页") })
        r.svc.execute(card.token)
        assertNull(r.ds.createdOrders.single().addressLat)
    }

    @Test
    fun `改单换地址定位不到就拒绝`() = runBlocking<Unit> {
        val r = Rig()
        val out = rejected(
            r.svc.preview(
                AiWrites.ORDERS_UPDATE,
                p("order" to "SOTEST2026091100230", "address" to "东边那个仓库"),
            ),
        )
        assertTrue("要说清后果：${out.reason}", out.reason.contains("旧地址"))
    }

    @Test
    fun `动作总数与域覆盖`() {
        // 用户口径是「整个 App 的功能它都能做」，所以这条断言是**防止能力悄悄缩水**的。
        assertTrue("动作数不该少于 40（当前 ${AiWrites.ALL.size}）", AiWrites.ALL.size >= 40)
        // ⚠️ 上界只是"大概没重复"的粗判据，每加一批动作都得抬它一次（v3.36 加了 5 个计费规则动作，
        //    2026-09-19 给「地点分组」加了 4 个，2026-09-20 加了「补导航」1 个与「订单退货」1 个，
        //    2026-09-22 给「预订单」加了 4 个：建/改/删/恢复预设单 —— 120；
        //    2026-09-22 当天又给「供应商/应付款」加了 11 个：档案/应付单/付款三条线各四个
        //    减去付款那条线的「撤销付款」—— 131；
        //    2026-09-23 给三份「分类名册」（开销/运费/预订单）各加 4 个：建/改名/删/重排 —— 143；
        //    2026-10-04 给「线路分类名册」（FEAT-0009，线路这一档也要能分类）加了 4 个：
        //    建/改名/删/重排 —— 147；
        //    2026-10-05 给「账号分类 / 车辆分类」两份名册（FEAT-0010）各加 4 个：建/改名/删/重排 —— 155；
        //    2026-10-07 给「采购单」加 4 个（CHG-0074，台账 L-42）：建单/改单头/撤单/恢复 —— 159；
        //    2026-10-08 给「我的下游价」加 3 个（CHG-0084，台账 L-53）：定价/删价/恢复 —— 162；
        //    2026-10-08 当天又给「订单结构」加 3 个（CHG-0085，台账 L-54）：转货 / 静默退回派单池 /
        //    补联系信息 —— 165；
        //    2026-10-08 当天再给「发票台账」加 6 个（CHG-0086，台账 L-55）：登记/改/开具/作废/撤票/恢复
        //    —— 171（这六件事手工页早就能做，这次是把它们也开给 AI）；
        //    2026-10-08 当天再给「钱相关四条」加 4 个（CHG-0087，台账 L-56）：定价 / 让价 /
        //    取消让价 / 设挂账额度 —— 175。
        //    2026-10-10 给「商品固价（不参与打折）」加 1 个（CHG-0109 / FEAT-0016：用户点名要 AI
        //    也能接管批量操作页那件事）：它就是 products.no_discount 的开/关 —— 176。
        //    所以下面补了一条**真正的去重断言**——不然这条会退化成"一个过一阵就要手动抬的魔数"，
        //    而它本来想防的"同一个动作声明两遍"一次都拦不住。
        assertTrue("动作数不该多于 176（当前 ${AiWrites.ALL.size}）", AiWrites.ALL.size <= 176)
        val ids = AiWrites.ALL.map { it.id }
        assertEquals(
            "动作 id 声明重复了：${ids.groupBy { it }.filter { it.value.size > 1 }.keys}",
            ids.size,
            ids.distinct().size,
        )
    }

    // ==================================== 21. 批量调价

    @Test
    fun `范围全空直接拒绝（防全表调价）`() = runBlocking<Unit> {
        val r = Rig()
        // 这是这个动作最危险的一种误用：一句"全部涨价"就把整张价格表改了。
        // 所以批发商和商品**不能同时留空**——范围写错比幅度写错严重得多。
        val out = rejected(r.svc.preview(AiWrites.PRICE_RULES_BATCH, p("adjust" to "10")))
        assertTrue(out.reason.contains("范围太大"))
        assertEquals(0, r.ds.masterCalls.size)
    }

    @Test
    fun `某商品对全部批发商降价`() = runBlocking {
        val r = Rig()
        val card = ok(
            r.svc.preview(AiWrites.PRICE_RULES_BATCH, p("product" to "红富士苹果", "adjust" to "-15")),
        )
        assertTrue("摘要要写清条数：${card.summary}", card.summary.contains("2 条"))
        assertTrue(card.summary.contains("降 15%"))
        // 卡片必须逐条列出 before → after —— 用户核对的就是这串数字
        assertTrue(
            "卡片上要看得到 4.5 → 3.83：${card.detailLines}",
            card.detailLines.any { it.contains("4.5") && it.contains("3.83") },
        )
        // 没有专属价的那个批发商按**商品默认价** 5 算
        assertTrue(
            "卡片上要看得到 5 → 4.25：${card.detailLines}",
            card.detailLines.any { it.contains("5") && it.contains("4.25") },
        )
        r.svc.execute(card.token)
        assertEquals(listOf("batchPrice:[31, 32]:[41]:adjust:null:-15"), r.ds.masterCalls)
    }

    @Test
    fun `某批发商对全部商品涨价`() = runBlocking {
        val r = Rig()
        val card = ok(
            r.svc.preview(AiWrites.PRICE_RULES_BATCH, p("shipper" to "城东水果批发", "adjust" to "10")),
        )
        assertTrue(card.summary.contains("2 条"))
        assertTrue(card.summary.contains("涨 10%"))
        r.svc.execute(card.token)
        assertEquals(listOf("batchPrice:[31]:[41, 42]:adjust:null:10"), r.ds.masterCalls)
    }

    @Test
    fun `指定多个批发商加指定商品`() = runBlocking {
        val r = Rig()
        val card = ok(
            r.svc.preview(
                AiWrites.PRICE_RULES_BATCH,
                p("shipper" to "城东水果批发、明辉食品商行", "product" to "皇冠梨", "adjust" to "-5"),
            ),
        )
        assertTrue(card.summary.contains("2 条"))
        r.svc.execute(card.token)
        assertEquals(listOf("batchPrice:[31, 32]:[42]:adjust:null:-5"), r.ds.masterCalls)
    }

    @Test
    fun `全部这类词等同于留空`() = runBlocking {
        val r = Rig()
        val card = ok(
            r.svc.preview(
                AiWrites.PRICE_RULES_BATCH,
                p("shipper" to "全部批发商", "product" to "红富士苹果", "adjust" to "-15"),
            ),
        )
        assertTrue(card.summary.contains("2 条"))
    }

    @Test
    fun `也可以直接设一个统一单价`() = runBlocking {
        val r = Rig()
        val card = ok(
            r.svc.preview(AiWrites.PRICE_RULES_BATCH, p("product" to "红富士苹果", "price" to "6")),
        )
        assertTrue(card.summary.contains("统一设为 6 元"))
        r.svc.execute(card.token)
        assertEquals(listOf("batchPrice:[31, 32]:[41]:fixed:6.00:null"), r.ds.masterCalls)
    }

    @Test
    fun `幅度和统一单价同时给就拒绝`() = runBlocking<Unit> {
        val r = Rig()
        val out = rejected(
            r.svc.preview(AiWrites.PRICE_RULES_BATCH, p("product" to "红富士苹果", "adjust" to "-15", "price" to "6")),
        )
        assertTrue(out.reason.contains("只能给一个"))
    }

    @Test
    fun `幅度和单价都没给就拒绝`() = runBlocking<Unit> {
        val r = Rig()
        val out = rejected(r.svc.preview(AiWrites.PRICE_RULES_BATCH, p("product" to "红富士苹果")))
        assertTrue(out.reason.contains("adjust") || out.reason.contains("price"))
    }

    @Test
    fun `降幅超过百分之百会被拦下`() = runBlocking<Unit> {
        val r = Rig()
        // -100% 会让价格变成 0，再低就是负数——那是没有意义的，必须拦。
        val out = rejected(
            r.svc.preview(AiWrites.PRICE_RULES_BATCH, p("product" to "红富士苹果", "adjust" to "-150")),
        )
        assertTrue(out.reason.contains("范围") || out.reason.contains("负数"))
    }

    @Test
    fun `百分比接受中文写法`() = runBlocking {
        val r = Rig()
        val card = ok(
            r.svc.preview(AiWrites.PRICE_RULES_BATCH, p("shipper" to "城东水果批发", "adjust" to "降15%")),
        )
        assertTrue(card.summary.contains("降 15%"))
        r.svc.execute(card.token)
        assertTrue(r.ds.masterCalls.single().endsWith(":-15"))
    }

    @Test
    fun `指定的批发商查不到就拒绝`() = runBlocking<Unit> {
        val r = Rig()
        val out = rejected(
            r.svc.preview(AiWrites.PRICE_RULES_BATCH, p("shipper" to "查无此商", "adjust" to "-10")),
        )
        assertTrue(out.reason.contains("查无此商"))
    }

    @Test
    fun `指定的商品查不到就拒绝`() = runBlocking<Unit> {
        val r = Rig()
        val out = rejected(
            r.svc.preview(AiWrites.PRICE_RULES_BATCH, p("product" to "火星西瓜", "adjust" to "-10")),
        )
        assertTrue(out.reason.contains("火星西瓜"))
    }

    @Test
    fun `卡片写明会覆盖已有专属价`() = runBlocking {
        val r = Rig()
        val card = ok(r.svc.preview(AiWrites.PRICE_RULES_BATCH, p("product" to "红富士苹果", "adjust" to "-15")))
        assertTrue(card.detailLines.any { it.contains("覆盖") })
        assertEquals(AiWriteRisk.HIGH, card.risk)
    }

    // ==================================== 22. 角色权限阶梯（目标③）
    //
    // 用户口径：派单员 > 货主 > 司机。这一组测的不是"界面藏没藏"，
    // 而是**服务层到底拦不拦**——界面藏起来的动作，模型仍然能从提示词里知道它存在。

    @Test
    fun `货主能用下单和撤单`() {
        assertTrue(AiWrites.allows(AiActor.byRole(AiRole.SHIPPER), AiWrites.ORDERS_CREATE))
        assertTrue(AiWrites.allows(AiActor.byRole(AiRole.SHIPPER), AiWrites.ORDERS_CANCEL))
    }

    @Test
    fun `货主能用地址与联系人`() {
        listOf(
            AiWrites.ADDRESS_CREATE, AiWrites.ADDRESS_UPDATE, AiWrites.ADDRESS_DELETE, AiWrites.ADDRESS_SET_DEFAULT,
            AiWrites.CONTACT_UPSERT, AiWrites.CONTACT_UPDATE, AiWrites.CONTACT_DELETE,
            AiWrites.LOCATION_CREATE, AiWrites.LOCATION_UPDATE, AiWrites.LOCATION_DELETE,
        ).forEach { assertTrue("货主该能用 $it", AiWrites.allows(AiActor.byRole(AiRole.SHIPPER), it)) }
    }

    @Test
    fun `货主不能用派单和主数据管理`() {
        listOf(
            AiWrites.ORDERS_ASSIGN, AiWrites.ORDERS_RECALL,
            AiWrites.PRODUCTS_CREATE, AiWrites.PRODUCTS_DELETE,
            AiWrites.PRICE_RULES_SET, AiWrites.PRICE_RULES_BATCH,
            AiWrites.INVENTORY_ADJUST,
            AiWrites.USERS_CREATE, AiWrites.USERS_SET_BILLING, AiWrites.USERS_SET_PASSWORD,
            AiWrites.EXPENSES_CREATE, AiWrites.ARREARS_UNIT_DELETE,
        ).forEach { assertFalse("货主不该能用 $it", AiWrites.allows(AiActor.byRole(AiRole.SHIPPER), it)) }
    }

    @Test
    fun `货主不能记账本流水（他对账本只有只读权限）`() {
        // 后端 shipper 的权限点是 ledger:read_own（**只读**），记流水要 LEDGER_EDIT。
        // 这一条特别容易想当然："货主当然能记自己的账"——不能。
        assertFalse(AiWrites.allows(AiActor.byRole(AiRole.SHIPPER), AiWrites.LEDGER_CREATE_ENTRY))
    }

    @Test
    fun `认不出角色就什么都不能用`() {
        // fail-closed：解析不出角色时**不给任何动作**。
        // 反过来（默认全开）一旦出问题就是"某个角色拿到了全部权限"，而那种错不会有人发现。
        assertTrue(AiWrites.forRole(null).isEmpty())
        assertFalse(AiWrites.allows(null, AiWrites.NOTIFICATIONS_READ_ALL))
    }

    @Test
    fun `新动作默认只给派单员`() {
        // 守的是**默认值的方向**：新加的动作如果不显式进 SHIPPER_ACTIONS 白名单，货主就看不到它。
        // 漏标 = 少给一个能力（会被立刻发现）；"默认全开"则漏标 = 多给一个权限（不会有人发现）。
        val plain = AiActor.byRole(AiRole.SHIPPER)!!
        // ⚠️ 2026-09-20 第七轮：白名单里那 3 条 `memberOnly`（货主自己那本账）**不给普通货主**，
        //    所以这里比的是"白名单减去 memberOnly"，而不是白名单本身。
        val memberOnlyIds = AiWrites.forRole(AiActor.of(AiRole.SHIPPER, true)!!).map { it.id }.toSet() -
            AiWrites.forRole(plain).map { it.id }.toSet()
        // ⚠️ 2026-10-08（CHG-0084 / 台账 L-53）：会员专属又多了一组 —— 「我的下游价」那三条
        //    （下游这本账只有批发商货主有，后端 `shipper_prices.py` 第二道闸就是 `_require_member`）。
        assertEquals(
            setOf(
                AiWrites.MY_LEDGER_SETTLE, AiWrites.MY_LEDGER_REVOKE, AiWrites.MY_LEDGER_RESTORE,
                AiWrites.SHIPPER_PRICE_SET, AiWrites.SHIPPER_PRICE_DELETE, AiWrites.SHIPPER_PRICE_RESTORE,
            ),
            memberOnlyIds,
        )
        assertEquals(AiWrites.SHIPPER_ACTIONS - memberOnlyIds, AiWrites.forRole(plain).map { it.id }.toSet())
        // ⚠️ 2026-09-21：派单员的算式多了一项 —— 退货申请那一组里 `roles = setOf(SHIPPER)` 的两条
        //    （申请/撤回）**点名不给派单员**（他点了必被后端以「这不是你的订单」拒绝）。
        //    这里仍然按"全集减去不该给他的"来算：新动作默认还是发给派单员，
        //    只有显式点名（`roles`）或会员专属（`memberOnly`）才会被减掉。
        val notForDispatcher = AiWrites.ALL
            .filter { it.memberOnly || (it.roles != null && AiRole.DISPATCHER !in it.roles) }
            .map { it.id }
            .toSet()
        assertEquals(
            "派单员应当拿到全集减掉货主自己那本账、以及点名不给他的那些",
            AiWrites.ALL.size - notForDispatcher.size,
            AiWrites.forRole(AiActor.byRole(AiRole.DISPATCHER)).size,
        )
        // 反向钉住：点名不给派单员的**只有**退货申请那两条 ＋ 补联系信息（2026-10-08 CHG-0085；
        // 别人顺手给 orders.assign 加个 `roles = setOf(SHIPPER)` 就会把派单的核心能力裁掉，而那不会有人发现）。
        // ⚠️ 补联系信息是**故意**不给派单员的：他要动联系人走「改单」那张卡（`orders.update`），
        //    这一条开的是货主那一扇门（后端 `order:edit_contact`，scope = own），给派单员等于多开一扇。
        assertEquals(
            setOf(
                AiWrites.RETURN_REQUEST_APPLY, AiWrites.RETURN_REQUEST_WITHDRAW,
                AiWrites.ORDERS_UPDATE_CONTACT,
            ),
            notForDispatcher - memberOnlyIds,
        )
    }

    @Test
    fun `两个货主：批发商能用核销，普通货主连清单里都没有`() {
        // 用户 2026-09-20 第七轮原话：「AI 也会分成 2 个：一个是普通货主、一个是批发商货主的 AI……
        // 他不能越权，批发商没有的功能 AI 也做不到；普通货主**手机做不到的事情，AI 也做不到**」。
        // 手机上这两个货主的「我的账本」就不一样：批发商多一段"我的货主欠我多少"、每单能核销。
        val plain = AiActor.byRole(AiRole.SHIPPER)!!
        val member = AiActor.of(AiRole.SHIPPER, true)!!
        val book = listOf(
            AiWrites.MY_LEDGER_SETTLE, AiWrites.MY_LEDGER_REVOKE, AiWrites.MY_LEDGER_RESTORE,
            // ⚠️ 2026-10-08（CHG-0084 / 台账 L-53）：「我的下游价」那三条也是**只有批发商货主**有的
            //    账（普通货主没有第二个客户）—— 与核销那三条同一个道理，一起进这本"会员专属"的账。
            AiWrites.SHIPPER_PRICE_SET, AiWrites.SHIPPER_PRICE_DELETE, AiWrites.SHIPPER_PRICE_RESTORE,
        )
        // ① 批发商三条都要能用（少一条他的账就管不了；撤回那条不走这里就点不动）
        book.forEach { assertTrue("批发商该能用 $it", AiWrites.allows(member, it)) }
        // ② 普通货主：**清单里都没有**，而且工具说明里也不许出现
        val plainText = AiWrites.describeForModel(plain)
        book.forEach {
            assertFalse("普通货主不该能用 $it", AiWrites.allows(plain, it))
            assertFalse("普通货主的工具说明里不该出现 $it", plainText.contains(it))
        }
        // ③ 派单员也不该有这本账（后端 `shipper_ledger.py` 是 `require_roles(SHIPPER)`）
        book.forEach {
            assertFalse("派单员不该有货主自己那本账：$it", AiWrites.allows(AiActor.byRole(AiRole.DISPATCHER), it))
        }
        // ④ 双向：两人**共有**的能力一个都不能因为这次拆分而少
        val plainIds = AiWrites.forRole(plain).map { it.id }.toSet()
        val memberIds = AiWrites.forRole(member).map { it.id }.toSet()
        assertEquals("批发商 = 普通货主 + 那三条，多一条少一条都说明裁错了", plainIds + book, memberIds)
    }

    // ==================================================== 退货申请（2026-09-21）
    //
    // 用户原话：「批发商**只是一个申请**，派单员才是实际性的操作。派单员进行完了之后，
    // 整个才进行库存才会发生一个改变和变动」＋「同时**货主的 AI 可以代替货主进行申请退货**」。
    //
    // 这一组钉四件事：
    // ① 申请卡片必须写明"**现在库存和账本都不动**"（用户最怕的正是它偷偷动）；
    // ② 数量锁死：办理时**不带数量**，只能按申请单来；
    // ③ 越权：**派单员的清单里不许出现"申请退货"**（点了必被后端以「这不是你的订单」拒），
    //    货主的清单里不许出现"办理/驳回"；
    // ④ 一张单已经有一张待处理申请时**不许再申请**（否则发一张必然失败的卡）。

    /** 一张已送达、能退 5 件的单（用 `orders` 里那张 SOTEST2026091100230，id=61）。 */
    private fun Rig.withReturnableOrder() = apply {
        // ⚠️ 状态必须是**已送达**：`RETURNABLE` 只认这一档（假名册里那两张是待派/已派，
        //    拿它们测"申请退货"会得到一张发不出来的卡 —— 那就把用例测成了别的东西）
        ds.orders = listOf(
            AiOrderRef(61, "SOTEST2026091100230", "城东水果批发", "DELIVERED", "测试收货地址 65 号", null, "320.00"),
        )
        ds.returnLines = listOf(
            AiReturnableLine(71, "红富士苹果", quantity = 5, returned = 0, damaged = 0, unitPrice = "10.00"),
        )
    }

    private fun pendingRequest(orderId: Long = 61) = AiReturnRequest(
        id = 901,
        orderId = orderId,
        orderNo = "SOTEST2026091100230",
        status = "pending",
        statusLabel = "待派单员处理",
        shipperName = "城东水果批发",
        note = "有两件破了",
        rejectReason = "",
        handledByName = "",
        lines = listOf("红富士苹果" to 2),
    )

    @Test
    fun `货主的 AI 能代替他申请退货，卡片写明现在什么都不动`() = runBlocking<Unit> {
        val r = Rig(actor = AiActor.byRole(AiRole.SHIPPER)).withReturnableOrder()
        val card = ok(
            r.svc.preview(
                AiWrites.RETURN_REQUEST_APPLY,
                p("order" to "SOTEST2026091100230", "note" to "有两件破了"),
            ),
        )
        // ★ 卡片上必须说清"现在还不动"（这句话没了，用户会以为点完就退了）
        val text = card.detailLines.joinToString("\n")
        assertTrue("卡片必须写明库存/账本现在不动：$text", text.contains("现在都不动") || text.contains("都不动"))
        assertTrue("卡片必须写明派单员会收到通知：$text", text.contains("派单员会收到"))
        assertTrue("卡片必须写明数量锁死：$text", text.contains("锁死"))

        // 提交：走的是申请接口，**不是退货接口**
        assertTrue(r.svc.execute(card.token) is AiWriteOutcome.Done)
        assertEquals(1, r.ds.appliedReturns.size)
        val (orderId, items, note) = r.ds.appliedReturns.first()
        assertEquals(61L, orderId)
        assertEquals(listOf(71L to 5), items) // lines 留空 = 整单申请（每行填满）
        assertEquals("有两件破了", note)
        assertTrue("申请阶段绝不许调退货：${r.ds.orderCalls}", r.ds.orderCalls.isEmpty())
    }

    @Test
    fun `已有待处理申请时不再发第二张卡`() = runBlocking<Unit> {
        val r = Rig(actor = AiActor.byRole(AiRole.SHIPPER)).withReturnableOrder()
        r.ds.pendingReturn = pendingRequest()
        val out = r.svc.preview(AiWrites.RETURN_REQUEST_APPLY, p("order" to "SOTEST2026091100230"))
        val why = rejected(out).reason
        assertTrue("要说清「已经有一张待处理的」：$why", why.contains("待处理"))
        assertTrue("要给出路（先撤回）：$why", why.contains("撤回"))
        assertTrue(r.ds.appliedReturns.isEmpty())
    }

    @Test
    fun `货主撤回自己的申请`() = runBlocking<Unit> {
        val r = Rig(actor = AiActor.byRole(AiRole.SHIPPER))
        r.ds.pendingReturn = pendingRequest()
        val card = ok(r.svc.preview(AiWrites.RETURN_REQUEST_WITHDRAW, p("order" to "SOTEST2026091100230")))
        assertTrue(
            "撤回卡片要写明「这不是删除」：${card.detailLines}",
            card.detailLines.any { it.contains("不是删除") || it.contains("记录留着") },
        )
        assertTrue(r.svc.execute(card.token) is AiWriteOutcome.Done)
        assertEquals(listOf(901L), r.ds.withdrawnReturns)
    }

    @Test
    fun `派单员办理时数量锁死、卡片写明库存此刻才变`() = runBlocking<Unit> {
        val r = Rig().withReturnableOrder() // 默认 actor = 派单员
        r.ds.pendingReturn = pendingRequest()
        val card = ok(r.svc.preview(AiWrites.RETURN_REQUEST_FULFILL, p("order" to "SOTEST2026091100230")))
        val text = card.detailLines.joinToString("\n")
        assertTrue("卡片必须写明这一刻才动库存：$text", text.contains("库存"))
        assertTrue("卡片必须写明数量锁死：$text", text.contains("不能改"))
        assertTrue("卡片要写出申请单上的明细（红富士苹果×2）：$text", text.contains("红富士苹果×2"))

        // ★ 数量锁死：commit 只带申请单号，**没有任何数量参数**
        val payload = card.payload.toString()
        assertFalse("payload 不许出现数量：$payload", payload.contains("quantity"))
        assertEquals("办理卡片是 HIGH（真退钱、真动库存）", AiWriteRisk.HIGH, AiWrites.byId(AiWrites.RETURN_REQUEST_FULFILL)!!.risk)

        assertTrue(r.svc.execute(card.token) is AiWriteOutcome.Done)
        assertEquals(listOf(901L), r.ds.fulfilledReturns)
    }

    @Test
    fun `驳回必须写理由，理由会发给申请人`() = runBlocking<Unit> {
        val r = Rig().withReturnableOrder()
        r.ds.pendingReturn = pendingRequest()
        val blank = r.svc.preview(AiWrites.RETURN_REQUEST_REJECT, p("order" to "SOTEST2026091100230"))
        assertTrue("空理由必须被拒（后端也要求必填）", blank is AiWriteOutcome.Rejected)

        val card = ok(
            r.svc.preview(
                AiWrites.RETURN_REQUEST_REJECT,
                p("order" to "SOTEST2026091100230", "reason" to "货已拆封，不能退"),
            ),
        )
        assertTrue(
            "卡片要写明这句话会发给申请人：${card.detailLines}",
            card.detailLines.any { it.contains("发给申请人") },
        )
        assertTrue(r.svc.execute(card.token) is AiWriteOutcome.Done)
        assertEquals(listOf(901L to "货已拆封，不能退"), r.ds.rejectedReturns)
    }

    @Test
    fun `没有待处理申请时办理与驳回都要如实说清楚`() = runBlocking<Unit> {
        val r = Rig().withReturnableOrder() // pendingReturn 默认 null
        listOf(AiWrites.RETURN_REQUEST_FULFILL, AiWrites.RETURN_REQUEST_REJECT).forEach { id ->
            val why = rejected(r.svc.preview(id, p("order" to "SOTEST2026091100230"))).reason
            assertTrue("$id 要说清「没有待处理的申请」：$why", why.contains("没有待处理的退货申请"))
        }
        assertTrue(r.ds.fulfilledReturns.isEmpty() && r.ds.rejectedReturns.isEmpty())
    }

    // ============================== 退货明细的**形状**（2026-09-24 第 22 轮 F1-D4）
    // 背景：原来解析是 `params["lines"] as? JsonArray`，拿不到就当"留空" —— 于是模型把明细
    // 写成**一个字符串**（把数组 toString 了，或干脆写成「苹果 2 件」）时静默变成
    // **整单退货**：账本整单红冲 + 库存全量回补 + 自动退款 + 订单转「已退货」，
    // 而两边都不报错。这一组就是钉住"形状不对必须拒绝"。

    /** 造一个 `lines` 不是数组的入参（`p()` 只能放字符串，这里要放任意 JsonElement）。 */
    private fun returnParamsWith(lines: JsonElement): JsonObject = buildJsonObject {
        put("order", "SOTEST2026091100230")
        put("lines", lines)
    }

    @Test
    fun `退货明细写成字符串会被拒绝，而不是静默退掉整单`() = runBlocking<Unit> {
        val r = Rig().withReturnableOrder()
        val why = rejected(
            r.svc.preview(
                AiWrites.ORDERS_RETURN,
                // 模型把数组 toString() 成了字符串 —— 这正是历史上会被当成"整单退货"的形状
                returnParamsWith(JsonPrimitive("[{\"product\":\"红富士苹果\",\"quantity\":2}]")),
            ),
        ).reason
        assertTrue("要说清必须写成数组：$why", why.contains("数组"))
        assertTrue("要告诉它这次收到的是什么形状（它看不到自己的 JSON）：$why", why.contains("字符串"))
        assertTrue("要提醒这个形状曾经会被当成整单退货：$why", why.contains("整单退货"))
        assertTrue("必须一张卡都不发", r.ds.orderCalls.isEmpty())
    }

    @Test
    fun `退货明细是空数组也会被拒绝`() = runBlocking<Unit> {
        val r = Rig().withReturnableOrder()
        val why = rejected(
            r.svc.preview(AiWrites.ORDERS_RETURN, returnParamsWith(JsonArray(emptyList()))),
        ).reason
        assertTrue("要说清是空数组、并给出两条出路：$why", why.contains("空数组"))
        assertTrue("要告诉它不传 lines 才是整单退货：$why", why.contains("完全不传"))
        assertTrue("必须一张卡都不发", r.ds.orderCalls.isEmpty())
    }

    @Test
    fun `退货明细完全不传仍然是整单退货（这条不许被上面两条改坏）`() = runBlocking<Unit> {
        val r = Rig().withReturnableOrder()
        val card = ok(
            r.svc.preview(AiWrites.ORDERS_RETURN, p("order" to "SOTEST2026091100230")),
        )
        val text = card.detailLines.joinToString("\n")
        assertTrue("整单退货要在卡片上写明退哪样、退多少：$text", text.contains("红富士苹果"))
        // ⚠️ 卡上的钱走 `moneyText`（显示口径，末尾 0 全省）——所以是「50 元」不是「50.00 元」
        assertTrue("整单退货的合计要写在卡上：$text", text.contains("合计：50 元"))
        assertTrue("要有一段「退回」把行列出来：$text", text.contains("退回"))
        assertTrue(r.svc.execute(card.token) is AiWriteOutcome.Done)
        // 替身把退货调用记成 `orderCalls` 里的一行（`return:<单号>:<行id>x<数量>`）
        assertEquals(listOf("return:61:71x5"), r.ds.orderCalls)
    }

    @Test
    fun `越权：派单员看不见申请退货，货主看不见办理驳回`() {
        val dispatcher = AiActor.byRole(AiRole.DISPATCHER)
        val shipper = AiActor.byRole(AiRole.SHIPPER)

        // ① 货主的申请/撤回：**只给货主**（派单员点它必被后端以「这不是你的订单」拒绝）
        listOf(AiWrites.RETURN_REQUEST_APPLY, AiWrites.RETURN_REQUEST_WITHDRAW).forEach {
            assertTrue("货主该有 $it", AiWrites.allows(shipper, it))
            assertFalse("派单员不该有 $it（点了必然失败）", AiWrites.allows(dispatcher, it))
            assertFalse("派单员的工具说明里也不许出现 $it", AiWrites.describeForModel(dispatcher).contains(it))
        }
        // ② 派单员的办理/驳回：货主不该有（手机上没有这个按钮）
        listOf(AiWrites.RETURN_REQUEST_FULFILL, AiWrites.RETURN_REQUEST_REJECT).forEach {
            assertTrue("派单员该有 $it", AiWrites.allows(dispatcher, it))
            assertFalse("货主不该有 $it", AiWrites.allows(shipper, it))
            assertFalse("货主的工具说明里不许出现 $it", AiWrites.describeForModel(shipper).contains(it))
        }
        // ③ ★ 所有货主都能申请（用户拍板）—— 普通货主与批发商**一样**
        val member = AiActor.of(AiRole.SHIPPER, true)!!
        assertEquals(
            "申请退货不该按 is_member 收窄（收窄一半订单就没有退货入口）",
            AiWrites.allows(shipper, AiWrites.RETURN_REQUEST_APPLY),
            AiWrites.allows(member, AiWrites.RETURN_REQUEST_APPLY),
        )
    }

    @Test
    fun `货主给自己下单不查货主名册`() = runBlocking<Unit> {
        // ⚠️ 真机/真后端实测过的 bug：`CreateOrderHandler` 原来无条件走
        //    `ds.searchShippers()` → `GET /users`，而那个端点对货主是 **403**
        //    （角色门是 USER_MANAGE＝派单员）。于是货主的 AI「帮我下一单」第一步就炸，
        //    **卡片永远发不出来** —— 手机上他自己明明能下单。
        //    现在按 `ds.currentRoleKey()` 分叉：货主走"给自己下单"，连 shipper_id 都不传。
        val r = Rig(actor = AiActor.byRole(AiRole.SHIPPER))
        r.ds.roleKey = "shipper"
        val card = ok(
            r.svc.preview(
                AiWrites.ORDERS_CREATE,
                buildJsonObject {
                    // ⚠️ 货主那条路**不传 shipper**（他自己就是货主）——传了反而会被判成代理下单。
                    put("lines", lineJson(Triple("红富士苹果", 2, "3.5")))
                },
            ),
        )
        assertTrue("卡片上要写明这单是他自己的：${card.detailLines}", card.detailLines.any { it.contains("你自己") })
        assertFalse("货主那条路不许带 shipper_id", card.payload.containsKey("shipper_id"))
        assertFalse("也不许退化成临时货主", card.payload.containsKey("temp_shipper_name"))
        assertTrue("没查过货主名册（查了就是 403）", r.ds.searchShipperCalls.isEmpty())
    }

    @Test
    fun `货主的动作清单里没有派单员的动作`() {
        val text = AiWrites.describeForModel(AiActor.byRole(AiRole.SHIPPER))
        assertTrue("清单里该有下单", text.contains(AiWrites.ORDERS_CREATE))
        assertTrue("清单里该有地址", text.contains(AiWrites.ADDRESS_CREATE))
        assertFalse("清单里不该出现派单", text.contains(AiWrites.ORDERS_ASSIGN))
        assertFalse("清单里不该出现改价", text.contains(AiWrites.PRODUCTS_UPDATE))
        assertFalse("清单里不该出现库存调整", text.contains(AiWrites.INVENTORY_ADJUST))
    }

    @Test
    fun `货主越权调用会被服务层拒绝`() = runBlocking<Unit> {
        // ⚠️ 这一段里最重要的一条：**界面藏了不等于拦住**。
        // 模型可能从别处知道有这个动作（提示词、历史对话），直接就调过来了。
        val r = Rig(actor = AiActor.byRole(AiRole.SHIPPER))
        val out = rejected(
            r.svc.preview(AiWrites.ORDERS_ASSIGN, p("order" to "SOTEST2026091100230", "driver" to "王建国")),
        )
        assertTrue("拒绝理由要说明是权限问题：${out.reason}", out.reason.contains("权限"))
        assertEquals(0, r.ds.orderCalls.size)
    }

    @Test
    fun `货主用自己范围内的动作正常放行`() = runBlocking {
        val r = Rig(actor = AiActor.byRole(AiRole.SHIPPER))
        val card = ok(
            r.svc.preview(AiWrites.ADDRESS_CREATE, p("receiver" to "张三", "address" to "测试路 1 号")),
        )
        r.svc.execute(card.token)
        assertTrue(r.ds.masterCalls.single().startsWith("createAddress"))
    }

    @Test
    fun `派单员仍然拿到全集`() = runBlocking {
        val r = Rig(actor = AiActor.byRole(AiRole.DISPATCHER))
        val card = ok(
            r.svc.preview(AiWrites.ORDERS_ASSIGN, p("order" to "SOTEST2026091100230", "driver" to "王建国")),
        )
        r.svc.execute(card.token)
        assertEquals(1, r.ds.orderCalls.size)
    }

    // ==================================================== 订单第二批（v3.16）
    //
    // 这五个动作的共同点：**卡片上写的东西必须和真正发出去的一致**。
    // 所以每条测试都走完 preview → execute，并且断言的落库参数是"卡片上那一行"。

    @Test
    fun `改单只带用户点名的字段，其余不动`() = runBlocking {
        val r = Rig()
        // 换地址必须同时换坐标（v3.24）：只改文字会留下旧坐标，司机被导航回旧地方
        r.ds.geoCodes = mapOf("测试收货地址 88 号" to (31.1 to 121.1))
        val card = ok(
            r.svc.preview(
                AiWrites.ORDERS_UPDATE,
                p("order" to "SOTEST2026091100230", "address" to "测试收货地址 88 号"),
            ),
        )
        assertTrue("卡片要写清改成什么：${card.summary}", card.summary.contains("改 1 项"))
        assertTrue(card.detailLines.any { it.contains("测试收货地址 88 号") })
        r.svc.execute(card.token)
        // 只有地址那几个键——别的键不出现在 payload 里，后端就不会动它们
        assertEquals(
            "update:61:{\"address_detail\":\"测试收货地址 88 号\",\"address_lat\":\"31.1\",\"address_lng\":\"121.1\"}",
            r.ds.orderCalls.single(),
        )
    }

    @Test
    fun `改单改的是别的项时不查高德`() = runBlocking {
        val r = Rig()
        val card = ok(
            r.svc.preview(AiWrites.ORDERS_UPDATE, p("order" to "SOTEST2026091100230", "remark" to "轻拿轻放")),
        )
        assertTrue(r.ds.geoCalls.isEmpty())
        r.svc.execute(card.token)
        assertEquals("update:61:{\"remark\":\"轻拿轻放\"}", r.ds.orderCalls.single())
    }

    @Test
    fun `改单什么都没说就拒绝（不许弹一张什么都不改的卡）`() = runBlocking<Unit> {
        val r = Rig()
        val out = rejected(r.svc.preview(AiWrites.ORDERS_UPDATE, p("order" to "SOTEST2026091100230")))
        assertTrue(out.reason.contains("改哪一项"))
        assertEquals(0, r.ds.orderCalls.size)
    }

    @Test
    fun `已送达的单不能改`() = runBlocking<Unit> {
        val r = Rig()
        r.ds.orders = r.ds.orders + AiOrderRef(63, "SOTEST2026091300228", "城东水果批发", "DELIVERED", "测试收货地址 1 号")
        rejected(
            r.svc.preview(
                AiWrites.ORDERS_UPDATE,
                p("order" to "SOTEST2026091300228", "remark" to "改一下"),
            ),
        )
        assertEquals(0, r.ds.orderCalls.size)
    }

    @Test
    fun `标记异常要原因，且已经是异常的不再重复标`() = runBlocking<Unit> {
        val r = Rig()
        rejected(r.svc.preview(AiWrites.ORDERS_MARK_EXCEPTION, p("order" to "SOTEST2026091100230")))

        val card = ok(
            r.svc.preview(
                AiWrites.ORDERS_MARK_EXCEPTION,
                p("order" to "SOTEST2026091100230", "reason" to "客户临时改时间"),
            ),
        )
        r.svc.execute(card.token)
        assertEquals("exception:61:true:客户临时改时间:null:null", r.ds.orderCalls.single())

        // 已经是异常的单：再标一次没有意义，必须拒绝而不是照做
        val r2 = Rig()
        r2.ds.orders = listOf(
            AiOrderRef(61, "SOTEST2026091100230", "城东水果批发", "PENDING_DISPATCH", "测试收货地址 65 号", null, "320.00", false, true),
        )
        val out = rejected(
            r2.svc.preview(
                AiWrites.ORDERS_MARK_EXCEPTION,
                p("order" to "SOTEST2026091100230", "reason" to "再标一次"),
            ),
        )
        assertTrue(out.reason.contains("已经是异常"))
    }

    @Test
    fun `解除异常只对异常单生效，并带上解决说明`() = runBlocking<Unit> {
        val r = Rig()
        // 普通单：没东西可解除
        val out = rejected(
            r.svc.preview(AiWrites.ORDERS_RESOLVE_EXCEPTION, p("order" to "SOTEST2026091100230", "note" to "处理完了")),
        )
        assertTrue(out.reason.contains("不是异常"))

        val r2 = Rig()
        r2.ds.orders = listOf(
            AiOrderRef(61, "SOTEST2026091100230", "城东水果批发", "PENDING_DISPATCH", "测试收货地址 65 号", null, "320.00", false, true),
        )
        val card = ok(
            r2.svc.preview(AiWrites.ORDERS_RESOLVE_EXCEPTION, p("order" to "SOTEST2026091100230", "note" to "已补发两件")),
        )
        assertTrue(card.detailLines.any { it.contains("已补发两件") })
        r2.svc.execute(card.token)
        assertEquals("resolveException:61:已补发两件", r2.ds.orderCalls.single())
    }

    @Test
    fun `拆单要至少两份，比例原样落库且卡片写清怎么分`() = runBlocking<Unit> {
        val r = Rig()
        rejected(r.svc.preview(AiWrites.ORDERS_SPLIT, p("order" to "SOTEST2026091100230", "parts" to "3")))

        val card = ok(
            r.svc.preview(AiWrites.ORDERS_SPLIT, p("order" to "SOTEST2026091100230", "parts" to "5:3:2")),
        )
        assertTrue("卡片要说清拆成几单：${card.summary}", card.summary.contains("3 单"))
        // 320 元按 5:3:2 → 160 / 96 / 64
        assertTrue(card.detailLines.any { it.contains("约 160 元") })
        assertTrue(card.detailLines.any { it.contains("约 96 元") })
        assertTrue(card.detailLines.any { it.contains("撤不回来") })
        r.svc.execute(card.token)
        assertEquals("split:61:5,3,2", r.ds.orderCalls.single())
    }

    @Test
    fun `拆单比例里有 0 就拒绝（后端会 400，别等用户点了确认才报错）`() = runBlocking<Unit> {
        val r = Rig()
        rejected(r.svc.preview(AiWrites.ORDERS_SPLIT, p("order" to "SOTEST2026091100230", "parts" to "5,0")))
        assertEquals(0, r.ds.orderCalls.size)
    }

    @Test
    fun `批量派单逐单核对状态，有一张不对就整批不做`() = runBlocking<Unit> {
        val r = Rig()
        // 62 号是「派单中」——整批必须拒绝，且**一张都不许落库**
        val out = rejected(
            r.svc.preview(
                AiWrites.ORDERS_BATCH_ASSIGN,
                p("orders" to "SOTEST2026091100230,SOTEST2026091200229", "driver" to "王建国"),
            ),
        )
        assertTrue(out.reason.contains("只有「待派单」"))
        assertEquals(0, r.ds.orderCalls.size)
    }

    @Test
    fun `批量派单把每张单都列在卡上，落了库的顺序与用户给的一致`() = runBlocking {
        val r = Rig()
        r.ds.orders = r.ds.orders +
            AiOrderRef(63, "SOTEST2026091300228", "城东水果批发", "PENDING_DISPATCH", "测试收货地址 1 号", null, "100.00")
        val card = ok(
            r.svc.preview(
                AiWrites.ORDERS_BATCH_ASSIGN,
                p("orders" to "SOTEST2026091100230, SOTEST2026091300228", "driver" to "王建国", "collect_cash" to "true"),
            ),
        )
        assertTrue(card.summary.contains("2 张"))
        // 逐行列出，用户才能核对"是不是这些"
        assertTrue(card.detailLines.any { it.contains("SOTEST2026091100230") })
        assertTrue(card.detailLines.any { it.contains("SOTEST2026091300228") })
        assertTrue(card.detailLines.any { it.contains("合计金额：420 元") })
        r.svc.execute(card.token)
        assertEquals("batchAssign:61,63:11:null:true", r.ds.orderCalls.single())
    }

    @Test
    fun `批量派单只有一张单就拒绝（那该走普通派单）`() = runBlocking<Unit> {
        val r = Rig()
        rejected(
            r.svc.preview(
                AiWrites.ORDERS_BATCH_ASSIGN,
                p("orders" to "SOTEST2026091100230", "driver" to "王建国"),
            ),
        )
    }

    @Test
    fun `批量派单超过上限就拒绝（一句话不许动几十单）`() = runBlocking<Unit> {
        val r = Rig()
        val many = (1..AiWrites.MAX_BATCH_ASSIGN + 1).joinToString(",") { "SOTEST202609110023$it" }
        val out = rejected(
            r.svc.preview(AiWrites.ORDERS_BATCH_ASSIGN, p("orders" to many, "driver" to "王建国")),
        )
        assertTrue(out.reason.contains("最多"))
    }

    @Test
    fun `批量派单里提到运费要如实说明不会写进去`() = runBlocking {
        val r = Rig()
        r.ds.orders = r.ds.orders +
            AiOrderRef(63, "SOTEST2026091300228", "城东水果批发", "PENDING_DISPATCH", "测试收货地址 1 号", null, "100.00")
        val card = ok(
            r.svc.preview(
                AiWrites.ORDERS_BATCH_ASSIGN,
                p("orders" to "SOTEST2026091100230,SOTEST2026091300228", "driver" to "王建国", "freight" to "80"),
            ),
        )
        assertTrue(
            "卡片必须说明运费不会生效，而不是悄悄丢掉：${card.detailLines}",
            card.detailLines.any { it.contains("不会写进去") },
        )
    }

    // ==================================================== 账本第二批（v3.17）
    //
    // 这一批的关键不是"能不能改"，而是**改的是不是用户说的那一行**：
    // 账本流水没有名字，只能靠摘要+日期+金额去对，对不上或对上多条都必须拒绝。

    @Test
    fun `改流水：卡片写清改前改后，落库只带改动的键`() = runBlocking {
        val r = Rig()
        val card = ok(
            r.svc.preview(
                AiWrites.LEDGER_UPDATE_ENTRY,
                p("product" to "红富士", "amount" to "320", "new_amount" to "288"),
            ),
        )
        assertTrue("卡片要写清是这一行：${card.summary}", card.summary.contains("红富士苹果"))
        assertTrue(card.detailLines.any { it.contains("320 → 288") })
        r.svc.execute(card.token)
        assertEquals("updateLedger:201:{\"entry_id\":201,\"total\":\"288.00\"}", r.ds.ledgerCalls.single())
    }

    @Test
    fun `改流水：摘要对上多条就拒绝并列候选，绝不挑一条`() = runBlocking<Unit> {
        val r = Rig()
        // 「皇冠梨」在 2026-09-12 那天有两条（不同货主）——必须要求用户补条件
        val out = rejected(r.svc.preview(AiWrites.LEDGER_UPDATE_ENTRY, p("product" to "皇冠梨", "new_amount" to "100")))
        assertTrue(out.reason.contains("对上了 2 条"))
        assertEquals(2, out.candidates.size)
        assertEquals(0, r.ds.ledgerCalls.size)
    }

    @Test
    fun `改流水：补上金额就能唯一定位`() = runBlocking {
        val r = Rig()
        val card = ok(
            r.svc.preview(
                AiWrites.LEDGER_UPDATE_ENTRY,
                p("product" to "皇冠梨", "amount" to "120", "new_product" to "皇冠梨（改）"),
            ),
        )
        r.svc.execute(card.token)
        assertTrue(r.ds.ledgerCalls.single().contains("\"product_name\":\"皇冠梨（改）\""))
    }

    @Test
    fun `改流水：一件都没说要改就拒绝`() = runBlocking<Unit> {
        val r = Rig()
        rejected(r.svc.preview(AiWrites.LEDGER_UPDATE_ENTRY, p("product" to "红富士")))
        assertEquals(0, r.ds.ledgerCalls.size)
    }

    @Test
    fun `改流水：摘要对不上就拒绝，并把这段时间的流水列出来`() = runBlocking<Unit> {
        val r = Rig()
        val out = rejected(r.svc.preview(AiWrites.LEDGER_UPDATE_ENTRY, p("product" to "香蕉", "new_amount" to "1")))
        assertTrue(out.reason.contains("没找到摘要像"))
        assertTrue("要给候选让用户挑：$($out.candidates)", out.candidates.isNotEmpty())
    }

    @Test
    fun `改流水：货主名对不上就拒绝（不许退化成「所有货主」）`() = runBlocking<Unit> {
        val r = Rig()
        val out = rejected(
            r.svc.preview(AiWrites.LEDGER_UPDATE_ENTRY, p("shipper" to "不存在的货主", "product" to "苹果", "new_amount" to "1")),
        )
        assertTrue(out.reason.contains("没找到"))
        assertEquals(0, r.ds.ledgerCalls.size)
    }

    @Test
    fun `删流水：卡片写清撤不回来，订单来源的要说明订单不受影响`() = runBlocking {
        val r = Rig()
        val card = ok(r.svc.preview(AiWrites.LEDGER_DELETE_ENTRY, p("product" to "皇冠梨", "amount" to "120", "date" to "2026-09-12", "shipper" to "城东水果批发")))
        assertTrue(card.detailLines.any { it.contains("撤不回来") })
        assertTrue("订单入账来的行要提醒订单不受影响", card.detailLines.any { it.contains("不会变") })
        r.svc.execute(card.token)
        assertEquals("deleteLedger:202", r.ds.ledgerCalls.single())
    }

    @Test
    fun `记客户收款：客户名解析成编号，金额必填`() = runBlocking<Unit> {
        val r = Rig()
        rejected(r.svc.preview(AiWrites.LEDGER_CREATE_RECEIPT, p("customer" to "老王果行")))
        rejected(r.svc.preview(AiWrites.LEDGER_CREATE_RECEIPT, p("customer" to "查无此人", "amount" to "100")))

        val card = ok(
            r.svc.preview(
                AiWrites.LEDGER_CREATE_RECEIPT,
                p("customer" to "老王果行", "amount" to "500", "method" to "wechat"),
            ),
        )
        assertTrue(card.detailLines.any { it.contains("先不核销") || it.contains("滚动收款") })
        val out = r.svc.execute(card.token)
        assertTrue("执行结果=$out，账本调用=${r.ds.ledgerCalls}", r.ds.ledgerCalls.isNotEmpty())
        val call = r.ds.ledgerCalls.single()
        assertTrue("要带客户编号与金额：$call", call.startsWith("receipt:301:500.00:wechat:"))
        // ⚠️ 不点名订单时必须发 rolling（滚动），发默认的 itemized 会被后端 400
        // 「逐单核销需绑定订单」——真机实测撞出来的。
        assertTrue("不点名订单要用滚动模式：$call", call.contains(":rolling:"))
    }

    @Test
    fun `记客户收款：不替用户猜核销哪几张单（没说就是空）`() = runBlocking {
        val r = Rig()
        val card = ok(
            r.svc.preview(AiWrites.LEDGER_CREATE_RECEIPT, p("customer" to "老王果行", "amount" to "500")),
        )
        r.svc.execute(card.token)
        assertTrue("orderIds 必须是空的：${r.ds.ledgerCalls}", r.ds.ledgerCalls.single().contains("::"))
    }

    @Test
    fun `收款卡的合计按欠款算，不按商品行金额（退过货的单）`() = runBlocking<Unit> {
        // ⛔ 2026-09-24 第 33 轮（第 24 轮 10 区 F1 的第二半）：后端整单核销**逐单按欠款算**，
        //    而退货只红冲账本、不改行金额 —— 退过货的单上两个数差一大截（本机 order 13：
        //    行 42.80 / 欠 21.40）。卡片原来拿行金额当判据 → 按 42.80 生成、后端按 21.40 判
        //    → 必 400；用户改口报 21.40 又被卡片自己那句"必须全额"挡回去 = **永久收不了款**。
        val r = Rig()
        r.ds.orders = listOf(
            AiOrderRef(
                id = 61, orderNo = "SOTEST2026091100230", shipper = "老王果行",
                status = "DELIVERED", address = "测试收货地址 65 号", driverLabel = null,
                amount = "42.80",           // 商品行金额（当时卖了多少）
                arrearsAmount = "21.40",    // 还欠（后端算的；差在退过货）
            ),
            AiOrderRef(
                id = 62, orderNo = "SOTEST2026091200229", shipper = "老王果行",
                status = "DELIVERED", address = "测试收货地址 4 号", driverLabel = null,
                amount = "192.60",
                arrearsAmount = "138.90",
            ),
        )

        // ① 按**欠款**合计（21.40 + 138.90 = 160.30）→ 应当能发卡
        val card = ok(
            r.svc.preview(
                AiWrites.LEDGER_CREATE_RECEIPT,
                p(
                    "customer" to "老王果行", "amount" to "160.30",
                    "orders" to "SOTEST2026091100230,SOTEST2026091200229",
                ),
            ),
        )
        val text = card.detailLines.joinToString("\n")
        // ⚠️ 卡上的钱走 `moneyText`（显示口径，末尾 0 全省）→ 是「欠 21.4」不是「欠 21.40」
        assertTrue("卡片要写清每张单**还欠**多少：$text", text.contains("欠 21.4"))
        assertTrue("第二张也要写：$text", text.contains("欠 138.9"))

        // ② 按**商品行金额**合计（42.80 + 192.60 = 235.40）→ 必须被拒（后端也会拒）
        val why = rejected(
            r.svc.preview(
                AiWrites.LEDGER_CREATE_RECEIPT,
                p(
                    "customer" to "老王果行", "amount" to "235.40",
                    "orders" to "SOTEST2026091100230,SOTEST2026091200229",
                ),
            ),
        ).reason
        assertTrue("要说清「还欠」多少、而不是「合计」多少：$why", why.contains("还欠"))
        assertTrue("要说清差在哪（还欠 160.3）：$why", why.contains("160.3"))
    }

    @Test
    fun `记客户收款：点名了订单就逐个解析并写进核销列表`() = runBlocking {
        val r = Rig()
        val card = ok(
            r.svc.preview(
                AiWrites.LEDGER_CREATE_RECEIPT,
                p("customer" to "老王果行", "amount" to "320", "orders" to "SOTEST2026091100230"),
            ),
        )
        assertTrue(card.detailLines.any { it.contains("SOTEST2026091100230") })
        assertTrue(card.detailLines.any { it.contains("已收") })
        r.svc.execute(card.token)
        assertTrue(r.ds.ledgerCalls.single().contains(":61:"))
    }

    @Test
    fun `记客户收款：逐单核销金额对不上就拒绝（后端也会拒，别让用户点了确认才吃 400）`() = runBlocking<Unit> {
        val r = Rig()
        val out = rejected(
            r.svc.preview(
                AiWrites.LEDGER_CREATE_RECEIPT,
                p("customer" to "老王果行", "amount" to "500", "orders" to "SOTEST2026091100230"),
            ),
        )
        assertTrue("要把两边金额都说清楚：${out.reason}", out.reason.contains("320 元") && out.reason.contains("500 元"))
        assertEquals(0, r.ds.ledgerCalls.size)
    }

    @Test
    fun `记客户收款：不认识的收款方式就拒绝（而不是硬塞一个）`() = runBlocking<Unit> {
        val r = Rig()
        val out = rejected(
            r.svc.preview(
                AiWrites.LEDGER_CREATE_RECEIPT,
                p("customer" to "老王果行", "amount" to "100", "method" to "刷卡"),
            ),
        )
        assertTrue(out.reason.contains("收款方式"))
    }

    @Test
    fun `补进账本：不填货主就是全部，填了就只补这个货主`() = runBlocking {
        val r = Rig()
        val all = ok(r.svc.preview(AiWrites.LEDGER_SYNC_DELIVERED, p()))
        assertTrue(all.detailLines.any { it.contains("所有货主") })
        r.svc.execute(all.token)
        assertEquals("sync:null", r.ds.ledgerCalls.single())

        val one = ok(r.svc.preview(AiWrites.LEDGER_SYNC_DELIVERED, p("shipper" to "城东水果批发")))
        assertTrue(one.detailLines.any { it.contains("城东水果批发") })
        r.svc.execute(one.token)
        assertEquals("sync:31", r.ds.ledgerCalls.last())
    }

    // ==================================================== 商品行 / 回收站（v3.18）
    //
    // 这一批的验收点：**金额会跟着变**。用户只说"少两件"，不会想到运费、账本、
    // 报表都跟着动，所以卡片必须把"金额从多少变成多少"算出来。

    @Test
    fun `加商品行：用商品库默认价，并算出新金额`() = runBlocking {
        val r = Rig()
        val card = ok(
            r.svc.preview(
                AiWrites.ORDERS_ADD_LINE,
                p("order" to "SOTEST2026091100230", "product" to "红富士苹果", "quantity" to "2"),
            ),
        )
        assertTrue(card.summary.contains("＋红富士苹果 × 2"))
        assertTrue("要说明单价是从商品库取的：${card.detailLines}", card.detailLines.any { it.contains("默认价") })
        assertTrue("要算金额：${card.detailLines}", card.detailLines.any { it.contains("320 → 330") })
        r.svc.execute(card.token)
        assertEquals("addLine:61:红富士苹果:2:5.00", r.ds.lineCalls.single())
    }

    @Test
    fun `加商品行：商品库里没有又没说价就拒绝（不许猜价）`() = runBlocking<Unit> {
        val r = Rig()
        val out = rejected(
            r.svc.preview(
                AiWrites.ORDERS_ADD_LINE,
                p("order" to "SOTEST2026091100230", "product" to "货主口头说的菜", "quantity" to "3"),
            ),
        )
        assertTrue(out.reason.contains("多少钱"))
        assertEquals(0, r.ds.lineCalls.size)
    }

    @Test
    fun `加商品行：已送达的单拒绝（后端也会拒，别让用户点了确认才知道）`() = runBlocking<Unit> {
        val r = Rig()
        r.ds.orders = r.ds.orders + AiOrderRef(63, "SOTEST2026091300228", "城东水果批发", "DELIVERED", "测试收货地址 1 号")
        rejected(
            r.svc.preview(
                AiWrites.ORDERS_ADD_LINE,
                p("order" to "SOTEST2026091300228", "product" to "红富士苹果", "quantity" to "1"),
            ),
        )
        assertEquals(0, r.ds.lineCalls.size)
    }

    @Test
    fun `改商品行：按商品名定位，卡片写改前改后与新金额`() = runBlocking {
        val r = Rig()
        val card = ok(
            r.svc.preview(
                AiWrites.ORDERS_UPDATE_LINE,
                p("order" to "SOTEST2026091100230", "product" to "红富士", "quantity" to "3"),
            ),
        )
        assertTrue(card.detailLines.any { it.contains("数量") && it.contains("5 → 3") })
        assertTrue(card.detailLines.any { it.contains("320 → 192") })
        r.svc.execute(card.token)
        assertTrue(r.ds.lineCalls.single().contains("\"quantity\":\"3\""))
    }

    @Test
    fun `改商品行：商品名对不上就拒绝，并把这张单的行列出来`() = runBlocking<Unit> {
        val r = Rig()
        val out = rejected(
            r.svc.preview(
                AiWrites.ORDERS_UPDATE_LINE,
                p("order" to "SOTEST2026091100230", "product" to "香蕉", "quantity" to "1"),
            ),
        )
        assertTrue(out.reason.contains("没有商品名像"))
        assertEquals(2, out.candidates.size)
    }

    @Test
    fun `改商品行：一件都没说要改就拒绝`() = runBlocking<Unit> {
        val r = Rig()
        rejected(
            r.svc.preview(
                AiWrites.ORDERS_UPDATE_LINE,
                p("order" to "SOTEST2026091100230", "product" to "红富士"),
            ),
        )
        assertEquals(0, r.ds.lineCalls.size)
    }

    @Test
    fun `删商品行：删最后一行要警告，且算清金额变化`() = runBlocking {
        val r = Rig()
        r.ds.lineRows = listOf(AiOrderLine(901, "红富士苹果", 5, "64.00", "320.00"))
        val card = ok(
            r.svc.preview(
                AiWrites.ORDERS_DELETE_LINE,
                p("order" to "SOTEST2026091100230", "product" to "红富士"),
            ),
        )
        assertTrue("要警告这是最后一行：${card.detailLines}", card.detailLines.any { it.contains("最后一行") })
        assertTrue(card.detailLines.any { it.contains("320 → 0") })
        r.svc.execute(card.token)
        assertEquals("deleteLine:901", r.ds.lineCalls.single())
    }

    @Test
    fun `移入回收站：卡片写清可恢复与到期清理`() = runBlocking {
        val r = Rig()
        val card = ok(r.svc.preview(AiWrites.ORDERS_SOFT_DELETE, p("order" to "SOTEST2026091100230")))
        assertTrue(card.detailLines.any { it.contains("所有人的列表") })
        assertTrue("要写清多少天内可恢复：${card.detailLines}", card.detailLines.any { it.contains("30 天内可以恢复") })
        r.svc.execute(card.token)
        assertEquals("softDelete:61", r.ds.lineCalls.single())
    }

    @Test
    fun `货主的 AI 只删已撤销的单，已送达的单不替他删`() = runBlocking<Unit> {
        // 用户 2026-09-21 口述：「他**不能删他的订单**……凡事有关订单信息，他的 AI 是不能做的。
        // 货主和批发商都一样，**除非是那个已撤销的订单信息，这个是可以删的**。」
        // ⚠️ AI 侧比界面严一档（界面那个「删除订单」按钮对已送达也还在，那是 2026-09-04 定的
        //    数据保留策略、由用户自己点）：已送达是**已经发生过的一趟生意**，
        //    账本流水/司机账单/库存都挂在它上面，用户对 AI 说"把这单删了"时多半没想到这一层。
        val delivered = AiOrderRef(65, "SOTEST2026091400227", "城东水果批发", "DELIVERED", "地址4", "李强", "200.00")
        val cancelled = AiOrderRef(71, "SOTEST2026090100220", "明辉食品商行", "CANCELLED", "地址9", null, "88.00")
        for (actor in listOf(AiActor.byRole(AiRole.SHIPPER)!!, AiActor.of(AiRole.SHIPPER, true)!!)) {
            val r = Rig(actor = actor)
            r.ds.roleKey = "shipper"
            r.ds.orders = r.ds.orders + delivered
            // 已送达 → 拒绝，且理由要说清"只能删已撤销的"
            val out = rejected(r.svc.preview(AiWrites.ORDERS_SOFT_DELETE, p("order" to delivered.orderNo)))
            assertTrue("理由要说清只能删已撤销的单：${out.reason}", out.reason.contains("已撤销"))
            assertEquals("没落库", 0, r.ds.lineCalls.size)
        }
        // 已撤销 → 可以删（那趟生意本来就没发生，删掉只是清一条废记录）
        val r = Rig(actor = AiActor.byRole(AiRole.SHIPPER)!!)
        r.ds.roleKey = "shipper"
        r.ds.orders = r.ds.orders + cancelled
        val card = ok(r.svc.preview(AiWrites.ORDERS_SOFT_DELETE, p("order" to cancelled.orderNo)))
        assertTrue("卡上要说明为什么只有这一种能删：${card.detailLines}",
            card.detailLines.any { it.contains("本来就没发生") })
        r.svc.execute(card.token)
        assertEquals("softDelete:71", r.ds.lineCalls.single())
        // 派单员那条路不受影响（任意状态都能删，原来就是）
        val rd = Rig()
        rd.ds.orders = rd.ds.orders + delivered
        ok(rd.svc.preview(AiWrites.ORDERS_SOFT_DELETE, p("order" to delivered.orderNo)))
    }

    @Test
    fun `从回收站恢复：只在回收站里找，普通单号找不到就说清楚`() = runBlocking<Unit> {
        val r = Rig()
        // 没删过的单（不在回收站）→ 拒绝，并说明"可能没被删过"
        val out = rejected(r.svc.preview(AiWrites.ORDERS_RESTORE, p("order" to "SOTEST2026091100230")))
        assertTrue(out.reason.contains("没被删过"))
        assertEquals(0, r.ds.lineCalls.size)
    }

    @Test
    fun `从回收站恢复：找到了就落库`() = runBlocking {
        val r = Rig()
        val card = ok(r.svc.preview(AiWrites.ORDERS_RESTORE, p("order" to "SOTEST2026090100220")))
        assertTrue(card.detailLines.any { it.contains("重新出现在各端的列表里") })
        r.svc.execute(card.token)
        assertEquals("restore:71", r.ds.lineCalls.single())
    }

    // ==================================================== 消息域（v3.19）

    @Test
    fun `发消息：收件人解析成编号，卡片摊开标题正文`() = runBlocking {
        val r = Rig()
        val card = ok(
            r.svc.preview(
                AiWrites.NOTIFICATIONS_SEND,
                p("to" to "张三", "title" to "明天送货车改时间", "content" to "改到上午十点"),
            ),
        )
        assertTrue(card.detailLines.any { it.contains("明天送货车改时间") })
        assertTrue(card.detailLines.any { it.contains("改到上午十点") })
        r.svc.execute(card.token)
        assertEquals("send:71:明天送货车改时间:改到上午十点:false", r.ds.msgCalls.single())
    }

    @Test
    fun `发消息：收件人对不上就拒绝（不许猜人）`() = runBlocking<Unit> {
        val r = Rig()
        rejected(
            r.svc.preview(
                AiWrites.NOTIFICATIONS_SEND,
                p("to" to "查无此人", "title" to "t", "content" to "c"),
            ),
        )
        assertEquals(0, r.ds.msgCalls.size)
    }

    @Test
    fun `价格变更通知：商品库找不到就拒绝（后端要商品编号）`() = runBlocking<Unit> {
        val r = Rig()
        val out = rejected(
            r.svc.preview(
                AiWrites.NOTIFICATIONS_PRICE_CHANGE,
                p("product" to "不存在的菜", "to" to "全部批发商", "new_price" to "9.9"),
            ),
        )
        assertTrue(out.reason.contains("商品库"))
    }

    @Test
    fun `价格变更通知：全部批发商＝名册里所有人，价格与类型都写进卡片`() = runBlocking {
        val r = Rig()
        val card = ok(
            r.svc.preview(
                AiWrites.NOTIFICATIONS_PRICE_CHANGE,
                p("product" to "红富士苹果", "to" to "全部批发商", "old_price" to "4.5", "new_price" to "5", "price_type" to "special"),
            ),
        )
        assertTrue(card.detailLines.any { it.contains("4.5 → 5") })
        assertTrue(card.detailLines.any { it.contains("专属价") })
        val joined = card.detailLines.joinToString("｜")
        assertTrue("两个批发商都要列出来：$joined", joined.contains("城东水果批发") && joined.contains("明辉食品商行"))
        r.svc.execute(card.token)
        // 商品编号必须是商品库里的那个；价格是规范化后的两位小数
        assertTrue(r.ds.msgCalls.single().startsWith("priceNotify:31,32:41:红富士苹果:special:5.00:4.50"))
    }

    @Test
    fun `标记已读：只挑未读的，已读的不重复处理`() = runBlocking<Unit> {
        val r = Rig()
        val card = ok(r.svc.preview(AiWrites.NOTIFICATIONS_MARK_READ, p("keyword" to "价格调整")))
        // 801 未读、803 未读，802 是"订单已送达"不含关键词
        assertEquals("标记已读：2 条消息", card.summary)
        r.svc.execute(card.token)
        assertEquals(2, r.ds.msgCalls.size)

        val r2 = Rig()
        r2.ds.notificationRows = r2.ds.notificationRows.map { if (it.id == 801L) it.copy(read = true) else it }
        r2.ds.notificationRows = listOf(r2.ds.notificationRows.first())
        val out = rejected(r2.svc.preview(AiWrites.NOTIFICATIONS_MARK_READ, p("keyword" to "红富士")))
        assertTrue(out.reason.contains("都已经读过了"))
    }

    @Test
    fun `改消息：关键词对上多条就拒绝（不许改错消息）`() = runBlocking<Unit> {
        val r = Rig()
        val out = rejected(
            r.svc.preview(
                AiWrites.NOTIFICATIONS_UPDATE,
                p("keyword" to "商品价格调整", "new_title" to "改一下"),
            ),
        )
        assertTrue(out.reason.contains("对上了 2 条"))
        assertEquals(2, out.candidates.size)
    }

    @Test
    fun `改消息：唯一命中才落库，并写清改前改后`() = runBlocking {
        val r = Rig()
        val card = ok(
            r.svc.preview(
                AiWrites.NOTIFICATIONS_UPDATE,
                p("keyword" to "订单已送达", "new_title" to "SO123 已送达（已核对）"),
            ),
        )
        assertTrue(card.detailLines.any { it.contains("SO123 已送达（已核对）") })
        r.svc.execute(card.token)
        assertEquals("update:802:SO123 已送达（已核对）:null", r.ds.msgCalls.single())
    }

    @Test
    fun `删消息：按关键词删几条`() = runBlocking {
        val r = Rig()
        val card = ok(r.svc.preview(AiWrites.NOTIFICATIONS_DELETE, p("keyword" to "价格调整")))
        assertEquals("删消息：2 条（含「价格调整」）", card.summary)
        r.svc.execute(card.token)
        assertEquals("delete:801,803:false", r.ds.msgCalls.single())
    }

    @Test
    fun `删消息：全部清空要写清条数（用户最后一道防线）`() = runBlocking {
        val r = Rig()
        val card = ok(r.svc.preview(AiWrites.NOTIFICATIONS_DELETE, p("all" to "true")))
        assertEquals("清空全部消息（3 条）", card.summary)
        r.svc.execute(card.token)
        assertEquals("delete::true", r.ds.msgCalls.single())
    }

    @Test
    fun `删消息：既没说关键词也没说全部就拒绝`() = runBlocking<Unit> {
        val r = Rig()
        rejected(r.svc.preview(AiWrites.NOTIFICATIONS_DELETE, p()))
        assertEquals(0, r.ds.msgCalls.size)
    }

    @Test
    fun `删消息：两个都给了就拒绝（避免顺手清空）`() = runBlocking<Unit> {
        val r = Rig()
        val out = rejected(r.svc.preview(AiWrites.NOTIFICATIONS_DELETE, p("keyword" to "价格", "all" to "true")))
        assertTrue(out.reason.contains("只能选一个"))
    }

    // ==================================== 5. 司机账单与结算（第四批·最后一批后端接口）
    //
    // 这一组的错误形状是**批量 + 撤不回来**：账单生成错了 App 里删不掉，
    // 结算单确认了作废不了，付款了没有反付款。所以测试集中在三件事：
    // ① 卡片上的**范围与金额**是不是真的（用户只能靠它核对）；
    // ② **状态门**有没有走对（草稿/已确认分得清，否则会锁错账单）；
    // ③ 定位不唯一时**拒绝**而不是挑一张。

    @Test
    fun `工资单：卡片把每个人和金额都算出来，不指定司机就是全部`() = runBlocking {
        val r = Rig()
        val card = ok(
            r.svc.preview(
                AiWrites.SETTLEMENTS_GENERATE_BILLS,
                p("month" to "2026-09", "type" to "salary"),
            ),
        )
        assertEquals("生成工资单：2026-09 · 2 人 · 合计 11000 元", card.summary)
        assertTrue(card.detailLines.any { it.contains("王建国：4500 元") })
        assertTrue(card.detailLines.any { it.contains("赵德海：6500 元") })
        // 卡片必须把"撤不回来"写在明面上（账单没有删除接口，这是读源码确认的事实）。
        assertTrue(card.detailLines.any { it.contains("没有删除入口") })

        r.svc.execute(card.token)
        // 不指定司机 → 不传 driver_id（后端语义：全部工资制司机）。
        assertEquals("generateBills:-:2026-09:salary", r.ds.settleCalls.single())
    }

    @Test
    fun `工资单：指定司机只算他一个`() = runBlocking {
        val r = Rig()
        val card = ok(
            r.svc.preview(
                AiWrites.SETTLEMENTS_GENERATE_BILLS,
                p("month" to "2026-09", "type" to "salary", "driver" to "赵德海"),
            ),
        )
        assertEquals("生成工资单：2026-09 · 1 人 · 合计 6500 元", card.summary)
        assertFalse(card.detailLines.any { it.contains("王建国") })
        r.svc.execute(card.token)
        assertEquals("generateBills:14:2026-09:salary", r.ds.settleCalls.single())
    }

    @Test
    fun `工资单：该月已有工资单的人会被跳过并写在卡片上`() = runBlocking {
        val r = Rig()
        // 王建国 2026-09 已有一张工资单
        r.ds.billRows = r.ds.billRows + AiDriverBill(
            905, 11, "王建国", "salary", "2026-09", "4500.00", "open",
        )
        val card = ok(
            r.svc.preview(
                AiWrites.SETTLEMENTS_GENERATE_BILLS,
                p("month" to "2026-09", "type" to "salary"),
            ),
        )
        assertEquals("生成工资单：2026-09 · 1 人 · 合计 6500 元", card.summary)
        assertTrue(card.detailLines.any { it.contains("已有工资单的 1 人会被跳过") })
    }

    @Test
    fun `工资单：该月全都建过了就拒绝（幂等，不许白跑一趟）`() = runBlocking<Unit> {
        val r = Rig()
        r.ds.billRows = r.ds.billRows + listOf(
            AiDriverBill(905, 11, "王建国", "salary", "2026-09", "4500.00", "open"),
            AiDriverBill(906, 14, "赵德海", "salary", "2026-09", "6500.00", "open"),
        )
        val out = rejected(
            r.svc.preview(
                AiWrites.SETTLEMENTS_GENERATE_BILLS,
                p("month" to "2026-09", "type" to "salary"),
            ),
        )
        assertTrue(out.reason.contains("已经全部生成过了"))
        assertEquals(0, r.ds.settleCalls.size)
    }

    @Test
    fun `工资单：按单计费的司机要给出真话（不许说系统里没这个人）`() = runBlocking<Unit> {
        val r = Rig()
        // 李强（13）在司机名册里，但不是工资制
        val out = rejected(
            r.svc.preview(
                AiWrites.SETTLEMENTS_GENERATE_BILLS,
                p("month" to "2026-09", "type" to "salary", "driver" to "李强"),
            ),
        )
        assertTrue("错误信息里不该出现「没有匹配」这种假话：${out.reason}", !out.reason.contains("没有匹配"))
        assertTrue(out.reason.contains("不是**工资制**司机"))
    }

    @Test
    fun `工资单：系统里一个工资制司机都没有就拒绝`() = runBlocking<Unit> {
        val r = Rig()
        r.ds.salaryDriverRows = emptyList()
        val out = rejected(
            r.svc.preview(
                AiWrites.SETTLEMENTS_GENERATE_BILLS,
                p("month" to "2026-09", "type" to "salary"),
            ),
        )
        assertTrue(out.reason.contains("工资制"))
        assertEquals(0, r.ds.settleCalls.size)
    }

    @Test
    fun `账单类型必填：不填就拒绝，绝不猜`() = runBlocking<Unit> {
        val r = Rig()
        val out = rejected(r.svc.preview(AiWrites.SETTLEMENTS_GENERATE_BILLS, p("month" to "2026-09")))
        // 运费单和工资单金额完全不同，猜错的后果是"给一个人建了另一种账单"，而账单删不掉。
        assertTrue(out.reason.contains("不要猜"))
        assertEquals(0, r.ds.settleCalls.size)
    }

    @Test
    fun `月份：多种写法归一成后端要的 YYYY-MM`() {
        assertEquals("2026-09", AiWriteArgs.parseMonth("2026-09", "month"))
        assertEquals("2026-09", AiWriteArgs.parseMonth("2026-9", "month"))
        assertEquals("2026-09", AiWriteArgs.parseMonth("2026/9", "month"))
        assertEquals("2026-09", AiWriteArgs.parseMonth("2026年9月", "month"))
        // 后端用 pattern=^\d{4}-\d{2}$ 卡这个参数，`2026-9` 会 422。
        assertEquals("2026-01", AiWriteArgs.parseMonth("2026.01", "month"))
    }

    @Test
    fun `月份：缺失或看不懂一律拒绝，不默认成这个月`() {
        for (bad in listOf(null, "", "九月", "2026", "2026-13", "2026-00", "26-9")) {
            var thrown = false
            try {
                AiWriteArgs.parseMonth(bad, "month")
            } catch (e: AiWriteArgException) {
                thrown = true
            }
            assertTrue("「$bad」应当被拒", thrown)
        }
    }

    @Test
    fun `运费单：卡片算出要补的金额（应结 − 已生成）`() = runBlocking {
        val r = Rig()
        // 王建国该月应结 70，已生成 30 → 补 40
        r.ds.billRows = listOf(
            AiDriverBill(901, 11, "王建国", "piece", "2026-09", "30.00", "open", "SOTEST2026091100230"),
        )
        val card = ok(
            r.svc.preview(
                AiWrites.SETTLEMENTS_GENERATE_BILLS,
                p("month" to "2026-09", "type" to "piece", "driver" to "王建国"),
            ),
        )
        assertEquals("生成运费账单：2026-09 · 王建国 · 补 40 元", card.summary)
        val row = card.detailLines.single { it.startsWith("· 王建国") }
        assertTrue(row.contains("应结 70 元"))
        assertTrue(row.contains("已生成 30 元"))
        assertTrue(row.contains("补 40 元"))
        // 张数只能给上界：未定价的单不会补。卡片必须写明，否则用户拿张数对账会对不上。
        assertTrue(row.contains("至多 3 张"))
        assertTrue(card.detailLines.any { it.contains("未定价") })

        r.svc.execute(card.token)
        assertEquals("generateBills:11:2026-09:piece", r.ds.settleCalls.single())
    }

    @Test
    fun `运费单：不指定司机就逐位列出来`() = runBlocking {
        val r = Rig()
        r.ds.billRows = emptyList()
        val card = ok(
            r.svc.preview(AiWrites.SETTLEMENTS_GENERATE_BILLS, p("month" to "2026-09", "type" to "piece")),
        )
        assertEquals("生成运费账单：2026-09 · 2 位司机 · 补 95 元", card.summary)
        assertTrue(card.detailLines.any { it.startsWith("· 王建国") })
        assertTrue(card.detailLines.any { it.startsWith("· 王建军") })
        assertTrue(card.detailLines.any { it.contains("本次共补：95 元") })
        r.svc.execute(card.token)
        assertEquals("generateBills:-:2026-09:piece", r.ds.settleCalls.single())
    }

    @Test
    fun `运费单：该月没有已送达计价的单就拒绝`() = runBlocking<Unit> {
        val r = Rig()
        r.ds.freightRows = emptyList()
        val out = rejected(
            r.svc.preview(AiWrites.SETTLEMENTS_GENERATE_BILLS, p("month" to "2026-09", "type" to "piece")),
        )
        assertTrue(out.reason.contains("已送达且计价"))
        assertEquals(0, r.ds.settleCalls.size)
    }

    @Test
    fun `运费单：已经生成齐了就拒绝（不重复建）`() = runBlocking<Unit> {
        val r = Rig()
        r.ds.freightRows = listOf(AiDriverFreight(11, "王建国", 3, "70.00"))
        r.ds.billRows = listOf(
            AiDriverBill(901, 11, "王建国", "piece", "2026-09", "70.00", "open", "SOTEST2026091100230"),
        )
        val out = rejected(
            r.svc.preview(
                AiWrites.SETTLEMENTS_GENERATE_BILLS,
                p("month" to "2026-09", "type" to "piece", "driver" to "王建国"),
            ),
        )
        assertTrue(out.reason.contains("已经生成齐了"))
        assertEquals(0, r.ds.settleCalls.size)
    }

    @Test
    fun `运费单：司机名对不上就拒绝（不许自己挑一个）`() = runBlocking<Unit> {
        val r = Rig()
        val out = rejected(
            r.svc.preview(
                AiWrites.SETTLEMENTS_GENERATE_BILLS,
                p("month" to "2026-09", "type" to "piece", "driver" to "张三丰"),
            ),
        )
        assertTrue("司机名对不上要说清楚：${out.reason}", out.reason.contains("没有匹配"))
        assertEquals(0, r.ds.settleCalls.size)
    }

    // ---------------------------------------------------------- 生成结算单

    @Test
    fun `结算单：卡片列出待结算账单与合计，金额不手改`() = runBlocking {
        val r = Rig()
        val card = ok(
            r.svc.preview(
                AiWrites.SETTLEMENTS_CREATE,
                p("driver" to "王建国", "month" to "2026-09"),
            ),
        )
        // 默认 type=piece：王建国该月两张 open 的运费单 30 + 40
        assertEquals("生成结算单：王建国 2026-09 运费单 70 元", card.summary)
        assertTrue(card.detailLines.any { it.contains("SOTEST2026091100230") })
        assertTrue(card.detailLines.any { it.contains("SOTEST2026091200229") })
        assertTrue(card.detailLines.any { it.contains("不能手改") })
        assertTrue(card.detailLines.any { it.contains("草稿") })

        r.svc.execute(card.token)
        // 后端允许手工传 amount，但传了之后**永远确认不了**（金额必须等于明细合计），
        // 所以这条路上的调用串里不该出现任何金额。
        assertEquals("createSettlement:11:piece:2026-09", r.ds.settleCalls.single())
    }

    @Test
    fun `结算单：没有待结算账单时指路「先生成账单」`() = runBlocking<Unit> {
        val r = Rig()
        r.ds.billRows = emptyList()
        val out = rejected(
            r.svc.preview(AiWrites.SETTLEMENTS_CREATE, p("driver" to "王建国", "month" to "2026-09")),
        )
        assertTrue(out.reason.contains("settlements.generate_bills"))
        assertEquals(0, r.ds.settleCalls.size)
    }

    @Test
    fun `结算单：只剩已结算的账单就拒绝（不重复结）`() = runBlocking<Unit> {
        val r = Rig()
        r.ds.billRows = listOf(
            AiDriverBill(903, 11, "王建国", "piece", "2026-09", "25.00", "settled", "SOTEST2026091300228"),
        )
        val out = rejected(
            r.svc.preview(AiWrites.SETTLEMENTS_CREATE, p("driver" to "王建国", "month" to "2026-09")),
        )
        assertTrue(out.reason.contains("已结算"))
        assertEquals(0, r.ds.settleCalls.size)
    }

    @Test
    fun `结算单：工资单类型的结算单走 salary`() = runBlocking {
        val r = Rig()
        val card = ok(
            r.svc.preview(
                AiWrites.SETTLEMENTS_CREATE,
                p("driver" to "王建国", "month" to "2026-08", "type" to "salary"),
            ),
        )
        assertEquals("生成结算单：王建国 2026-08 工资单 4500 元", card.summary)
        r.svc.execute(card.token)
        assertEquals("createSettlement:11:salary:2026-08", r.ds.settleCalls.single())
    }

    // ---------------------------------------------------------- 确认 / 付款 / 作废

    @Test
    fun `确认结算单：只认草稿，卡片写明锁哪几张账单`() = runBlocking {
        val r = Rig()
        val card = ok(
            r.svc.preview(
                AiWrites.SETTLEMENTS_CONFIRM,
                p("driver" to "王建国", "month" to "2026-09"),
            ),
        )
        assertEquals("确认结算单：王建国 2026-09 运费单 70 元", card.summary)
        assertTrue(card.detailLines.any { it.contains("锁住的账单（2 张）") })
        assertTrue(card.detailLines.any { it.contains("确认后不能作废") })
        assertTrue(card.detailLines.any { it.contains("付款是下一步") })
        // 卡片是普通 Text，不渲染 Markdown：文案里出现 `**` 会在屏幕上原样显示星号
        // （v3.20 真机实测抓到过这个域漏了 10 处）。红线脚本另有一道静态检查。
        assertTrue(
            "卡片文案里不该有 Markdown 星号",
            card.detailLines.none { it.contains("**") },
        )

        r.svc.execute(card.token)
        assertEquals("settlementAction:951:confirm:cash", r.ds.settleCalls.single())
    }

    @Test
    fun `确认结算单：已付款的单不能确认，并说出它现在是什么状态`() = runBlocking<Unit> {
        val r = Rig()
        val out = rejected(
            r.svc.preview(
                AiWrites.SETTLEMENTS_CONFIRM,
                p("driver" to "王建军", "month" to "2026-09"),
            ),
        )
        assertTrue(out.reason.contains("已付款"))
        assertEquals(0, r.ds.settleCalls.size)
    }

    @Test
    fun `付款：草稿不能付款，付款只认已确认`() = runBlocking<Unit> {
        val r = Rig()
        val out = rejected(
            r.svc.preview(
                AiWrites.SETTLEMENTS_PAY,
                p("driver" to "王建国", "month" to "2026-09"),
            ),
        )
        assertTrue(out.reason.contains("草稿"))
        assertTrue(out.reason.contains("已确认"))
        assertEquals(0, r.ds.settleCalls.size)
    }

    @Test
    fun `付款：已确认的单可以付款，默认现金并写在卡片上`() = runBlocking {
        val r = Rig()
        r.ds.settlementRows = listOf(
            AiSettlementRef(951, 11, "王建国", "piece", "2026-09", "70.00", "confirmed", 2),
        )
        val card = ok(
            r.svc.preview(
                AiWrites.SETTLEMENTS_PAY,
                p("driver" to "王建国", "month" to "2026-09"),
            ),
        )
        assertEquals("结算单付款：王建国 2026-09 运费单 70 元（现金）", card.summary)
        assertTrue(card.detailLines.any { it.contains("按默认现金") })
        assertTrue(card.detailLines.any { it.contains("资金流水（支出）") })
        assertTrue(card.detailLines.any { it.contains("撤不回来") })

        r.svc.execute(card.token)
        assertEquals("settlementAction:951:pay:cash", r.ds.settleCalls.single())
    }

    @Test
    fun `付款：方式非法就拒绝（不静默改成现金）`() = runBlocking<Unit> {
        val r = Rig()
        r.ds.settlementRows = listOf(
            AiSettlementRef(951, 11, "王建国", "piece", "2026-09", "70.00", "confirmed", 2),
        )
        val out = rejected(
            r.svc.preview(
                AiWrites.SETTLEMENTS_PAY,
                p("driver" to "王建国", "month" to "2026-09", "method" to "打白条"),
            ),
        )
        assertTrue(out.reason.contains("不认"))
        assertEquals(0, r.ds.settleCalls.size)
    }

    @Test
    fun `作废结算单：只认草稿，并说清不会解锁账单`() = runBlocking {
        val r = Rig()
        val card = ok(
            r.svc.preview(
                AiWrites.SETTLEMENTS_CANCEL,
                p("driver" to "王建国", "month" to "2026-09"),
            ),
        )
        assertEquals("作废结算单：王建国 2026-09 运费单 70 元", card.summary)
        assertTrue(card.detailLines.any { it.contains("不会解锁任何账单") })
        r.svc.execute(card.token)
        assertEquals("settlementAction:951:cancel:cash", r.ds.settleCalls.single())
    }

    @Test
    fun `结算单：同月两张草稿就拒绝并列候选（锁错单会锁错账单）`() = runBlocking<Unit> {
        val r = Rig()
        r.ds.settlementRows = listOf(
            AiSettlementRef(951, 11, "王建国", "piece", "2026-09", "70.00", "draft", 2),
            AiSettlementRef(953, 11, "王建国", "piece", "2026-09", "70.00", "draft", 2),
        )
        val out = rejected(
            r.svc.preview(
                AiWrites.SETTLEMENTS_CONFIRM,
                p("driver" to "王建国", "month" to "2026-09"),
            ),
        )
        assertTrue(out.reason.contains("对上了 2 张"))
        assertEquals(2, out.candidates.size)
        assertEquals(0, r.ds.settleCalls.size)
    }

    @Test
    fun `结算单：一张都没有就指路「先生成结算单」`() = runBlocking<Unit> {
        val r = Rig()
        r.ds.settlementRows = emptyList()
        val out = rejected(
            r.svc.preview(
                AiWrites.SETTLEMENTS_CONFIRM,
                p("driver" to "王建国", "month" to "2026-09"),
            ),
        )
        assertTrue(out.reason.contains("settlements.create"))
        assertEquals(0, r.ds.settleCalls.size)
    }

    @Test
    fun `结算域五个动作默认只给派单员（货主一律 fail-closed）`() = runBlocking<Unit> {
        val ids = listOf(
            AiWrites.SETTLEMENTS_GENERATE_BILLS,
            AiWrites.SETTLEMENTS_CREATE,
            AiWrites.SETTLEMENTS_CONFIRM,
            AiWrites.SETTLEMENTS_PAY,
            AiWrites.SETTLEMENTS_CANCEL,
        )
        for (id in ids) {
            assertTrue("$id 应当在派单员动作集里", AiWrites.allows(AiActor.byRole(AiRole.DISPATCHER), id))
            assertFalse("$id 不该给货主", AiWrites.allows(AiActor.byRole(AiRole.SHIPPER), id))
            assertFalse("$id 不该给未知角色", AiWrites.allows(null, id))
        }
        // 服务层是真正的门：越权调用必须被拒，而不是靠界面藏起来。
        val r = Rig(actor = AiActor.byRole(AiRole.SHIPPER))
        val out = rejected(
            r.svc.preview(
                AiWrites.SETTLEMENTS_GENERATE_BILLS,
                p("month" to "2026-09", "type" to "salary"),
            ),
        )
        assertTrue(out.reason.contains("没有"))
        assertEquals(0, r.ds.settleCalls.size)
    }

    @Test
    fun `账单生成失败（网络）不会写进去任何东西`() = runBlocking<Unit> {
        val r = Rig()
        val card = ok(
            r.svc.preview(
                AiWrites.SETTLEMENTS_GENERATE_BILLS,
                p("month" to "2026-09", "type" to "salary"),
            ),
        )
        r.ds.failWith = java.io.IOException("boom")
        val out = r.svc.execute(card.token)
        assertTrue(out is AiWriteOutcome.Rejected)
        assertEquals(0, r.ds.settleCalls.size)
    }

    // ============================== 6. 按表格调价（目标①的第四种用法：用户贴一张表）

    @Test
    fun `按表格调价：卡片逐行列出改前改后`() = runBlocking {
        val r = Rig()
        val card = ok(
            r.svc.preview(
                AiWrites.PRICE_RULES_APPLY_TABLE,
                p(
                    "rows" to """
                        红富士苹果	城东水果批发	-10%
                        皇冠梨	明辉食品商行	新价3.80
                    """.trimIndent(),
                ),
            ),
        )
        assertEquals("按表格调价：2 行 · 2 条价格", card.summary)
        // 红富士苹果在城东水果批发那里已有 4.50 的专属价 → -10% = 4.05
        assertTrue(card.detailLines.any { it.contains("城东水果批发 红富士苹果：4.5 → 4.05") })
        // 皇冠梨没写过专属价 → 按默认价 4.00
        assertTrue(card.detailLines.any { it.contains("明辉食品商行 皇冠梨：4 → 3.8") })
        assertTrue(card.detailLines.any { it.contains("降 10%") })

        val out = r.svc.execute(card.token)
        assertTrue(out is AiWriteOutcome.Done)
        assertEquals(2, r.ds.masterCalls.size)
        assertEquals("batchPrice:[31]:[41]:adjust:null:-10.00", r.ds.masterCalls[0])
        assertEquals("batchPrice:[32]:[42]:fixed:3.80:null", r.ds.masterCalls[1])
    }

    @Test
    fun `按表格调价：写「全部」的行只发一个请求（后端自己铺开）`() = runBlocking {
        val r = Rig()
        val card = ok(
            r.svc.preview(AiWrites.PRICE_RULES_APPLY_TABLE, p("rows" to "红富士苹果\t全部\t-3%")),
        )
        assertEquals("按表格调价：1 行 · 2 条价格", card.summary) // 2 个批发商 → 2 条
        r.svc.execute(card.token)
        // shipper_ids 留空 = 全部批发商（后端语义），所以只发一个请求
        assertEquals("batchPrice:[]:[41]:adjust:null:-3.00", r.ds.masterCalls.single())
    }

    @Test
    fun `按表格调价：一行读不出来就整张卡都不发`() = runBlocking<Unit> {
        val r = Rig()
        val out = rejected(
            r.svc.preview(
                AiWrites.PRICE_RULES_APPLY_TABLE,
                p("rows" to "红富士苹果\t城东水果批发\t-10%\n水蜜桃\t明辉食品商行\t-5%"),
            ),
        )
        assertTrue(out.reason.contains("第 2 行"))
        assertEquals(0, r.ds.masterCalls.size)
    }

    @Test
    fun `按表格调价：部分失败必须如实汇报（不许只说已完成）`() = runBlocking<Unit> {
        val r = Rig()
        val card = ok(
            r.svc.preview(
                AiWrites.PRICE_RULES_APPLY_TABLE,
                p(
                    "rows" to """
                        红富士苹果	城东水果批发	-10%
                        皇冠梨	明辉食品商行	-5%
                    """.trimIndent(),
                ),
            ),
        )
        r.ds.failBatchAtIndex = 1 // 第二行失败
        val out = r.svc.execute(card.token)
        assertTrue(out is AiWriteOutcome.Done)
        val msg = (out as AiWriteOutcome.Done).message
        // 这一条是**整个动作最要紧的反馈**：逐行执行就会部分成功，
        // 只回一句「已完成」等于把失败的那一行藏起来。
        assertTrue("应当汇报成功/失败行数：$msg", msg.contains("成功 1 行"))
        assertTrue("应当列出失败的是第几行：$msg", msg.contains("第 2 行"))
        assertTrue("应当说明失败的行没写进去：$msg", msg.contains("失败的行没写进去"))
    }

    @Test
    fun `按表格调价：全部成功时也要说清写完了`() = runBlocking<Unit> {
        val r = Rig()
        val card = ok(
            r.svc.preview(AiWrites.PRICE_RULES_APPLY_TABLE, p("rows" to "红富士苹果\t城东水果批发\t-10%")),
        )
        val out = r.svc.execute(card.token)
        val msg = (out as AiWriteOutcome.Done).message
        assertTrue(msg.contains("成功 1 行"))
        assertTrue(msg.contains("全部写完"))
    }

    @Test
    fun `按表格调价：执行结果那句话是一次性的（不许残留到下一次）`() = runBlocking<Unit> {
        val ds = FakeDs()
        val store = AiWritePreviewStore()
        val svc = AiWriteService(ds, store, actorProvider = { AiActor.byRole(AiRole.DISPATCHER) })
        val card = ok(
            svc.preview(AiWrites.PRICE_RULES_APPLY_TABLE, p("rows" to "红富士苹果\t城东水果批发\t-10%")),
        )
        val handler = ApplyPriceTableHandler(ds, store)
        handler.commit(card.payload, "k")
        assertNotNull(handler.commitNote())
        assertNull("取过一次之后必须为空，否则下一次执行会读到上一次的残留", handler.commitNote())
    }

    @Test
    fun `按表格调价：mode=fixed 时整列按绝对新价读`() = runBlocking {
        val r = Rig()
        val card = ok(
            r.svc.preview(
                AiWrites.PRICE_RULES_APPLY_TABLE,
                p("rows" to "红富士苹果\t城东水果批发\t4.05", "mode" to "fixed"),
            ),
        )
        // 每一行都标了「（新价）」，用户一眼能看出这一列是按价格读的
        assertTrue(card.detailLines.any { it.contains("（新价）") })
        r.svc.execute(card.token)
        assertEquals("batchPrice:[31]:[41]:fixed:4.05:null", r.ds.masterCalls.single())
    }

    @Test
    fun `按表格调价：缺 rows 就拒绝并说清为什么`() = runBlocking<Unit> {
        val r = Rig()
        val out = rejected(r.svc.preview(AiWrites.PRICE_RULES_APPLY_TABLE, p()))
        assertTrue(out.reason.contains("rows"))
        assertEquals(0, r.ds.masterCalls.size)
    }

    @Test
    fun `按表格调价：货主不能用（调价是派单员的权限）`() = runBlocking<Unit> {
        val r = Rig(actor = AiActor.byRole(AiRole.SHIPPER))
        val out = rejected(
            r.svc.preview(AiWrites.PRICE_RULES_APPLY_TABLE, p("rows" to "红富士苹果\t-10%")),
        )
        assertTrue(out.reason.contains("没有"))
        assertEquals(0, r.ds.masterCalls.size)
    }

    @Test
    fun `按表格调价：算出来是负数的行拒绝（降幅超 100% 的另一条路）`() = runBlocking<Unit> {
        val r = Rig()
        // 城东水果批发 红富士苹果 现价 4.50；默认价 5.00 → 用皇冠梨（4.00）× -150% 会被解析层拦下，
        // 这里走"涨价后为负"的另一条路：用 fixed 给负数会被解析层拦，所以测 adjust 的边界。
        val out = rejected(
            r.svc.preview(
                AiWrites.PRICE_RULES_APPLY_TABLE,
                p("rows" to "红富士苹果\t城东水果批发\t-120%"),
            ),
        )
        assertTrue(out.reason.contains("-100%"))
        assertEquals(0, r.ds.masterCalls.size)
    }

    // ============================== 7. 账号域：字段 key 覆盖不许读错（真机实测抓到的丢数据 bug）

    @Test
    fun `新建账号：姓名必须真的发出去（字段 key 是 full_name，不是 name）`() = runBlocking {
        val r = Rig()
        val card = ok(
            r.svc.preview(
                AiWrites.USERS_CREATE,
                p(
                    "phone" to "13900001234",
                    "password" to "test1234",
                    "role" to "shipper",
                    "name" to "AI测试账号",
                ),
            ),
        )
        assertTrue("卡片上要写姓名：${card.summary}", card.summary.contains("AI测试账号"))
        r.svc.execute(card.token)
        // ⚠️ 这一条是**真机实测抓到的 bug** 的回归网：字段规格是
        //    `textField("name", …).copy(key = "full_name")`，payload 里存的是 `full_name`；
        //    而 commit 读的是 `p.str("name")` → 永远是空。表现是"卡片上写着姓名、
        //    执行完还回「已完成」，而库里那条账号的姓名是空的"（用户只会在名册里看到「未命名」）。
        assertEquals(
            "createUser:13900001234:test1234:shipper:AI测试账号:false",
            r.ds.masterCalls.single(),
        )
    }

    @Test
    fun `新建账号：密码只进 payload，卡片上不回显`() = runBlocking {
        val r = Rig()
        val card = ok(
            r.svc.preview(
                AiWrites.USERS_CREATE,
                p("phone" to "13900001234", "password" to "test1234", "role" to "shipper"),
            ),
        )
        val shown = card.summary + "\n" + card.detailLines.joinToString("\n")
        assertFalse("卡片上不许出现密码值：$shown", shown.contains("test1234"))
        assertTrue(shown.contains("已设置"))
    }

    @Test
    fun `改账号资料：姓名按 full_name 发出去`() = runBlocking {
        val r = Rig()
        val card = ok(
            r.svc.preview(
                AiWrites.USERS_UPDATE_PROFILE,
                p("user" to "张三", "name" to "张三丰"),
            ),
        )
        r.svc.execute(card.token)
        val call = r.ds.masterCalls.single()
        assertTrue("应当按 payload 键 full_name 发：$call", call.contains("full_name"))
        assertTrue("值也要对：$call", call.contains("张三丰"))
    }

    // ================= 8. 商品分类名册 / 商品可见范围 / 改车辆（v3.43：用户点名的三件事）
    //
    // 用户 2026-09-18 原话：「在给 ai 的功能开放创建商品分组、管理商品分组的排序」，
    // 以及「甚至也可以直接叫 ai 操作（指定某个批发商/货主只能看到哪些商品）」。
    // 这一组钉的是**卡片能不能核对**：分类改名的波及范围、重排的新顺序、
    // 可见范围的模式与商品名——这三样只要有一样没写在卡上，用户就只能盲点。

    @Test
    fun `改分类：卡片写出这一类下有几个商品（改名会级联改过去）`() = runBlocking {
        val r = Rig()
        val card = ok(
            r.svc.preview(AiWrites.PRODUCT_CATEGORY_UPDATE, p("category" to "水果", "name" to "生鲜")),
        )
        assertEquals("改商品分类：水果", card.summary)
        assertTrue("卡片上要有商品数：${card.detailLines}", card.detailLines.any { it.contains("12 个商品") })
        assertTrue(card.detailLines.any { it.contains("一起改过去") })
        r.svc.execute(card.token)
        assertTrue(r.ds.masterCalls.single().contains("\"name\":\"生鲜\""))
    }

    @Test
    fun `改分类：空分类不说「会把 0 个商品改过去」`() = runBlocking {
        val r = Rig()
        // 干货 = 0 个商品：这时候那句级联提醒是废话（会让用户以为有商品要动）
        val card = ok(
            r.svc.preview(AiWrites.PRODUCT_CATEGORY_UPDATE, p("category" to "干货", "name" to "杂货")),
        )
        assertTrue(card.detailLines.none { it.contains("一起改过去") })
    }

    @Test
    fun `改分类顺序：卡片说第几位，换算成后端的 sort_order 差一位都不行`() = runBlocking {
        val r = Rig()
        val card = ok(
            r.svc.preview(AiWrites.PRODUCT_CATEGORY_UPDATE, p("category" to "干货", "position" to "1")),
        )
        assertTrue("卡片上要说人话（第几位）：${card.detailLines}", card.detailLines.any { it.contains("排到第 1 位") })
        r.svc.execute(card.token)
        // 这一层（数据源替身）看到的是**位置值**：换算在后端边界上做（见下一条断言）。
        assertTrue("位置值要原样传到边界：${r.ds.masterCalls}", r.ds.masterCalls.single().contains("\"sort_order\":\"1\""))
    }

    @Test
    fun `分类位置的换算只有一处实现：第 1 位 = sort_order 0（差一位就是排错地方）`() {
        // 后端按 (sort_order, id) 排序，`reorder` 写的也是这套值（ids[0] = 0），
        // 而卡片和用户说的是"第几位"。两边差一位**不会报错**，只会让分类排错地方，
        // 所以换算必须是纯函数、必须有一条断言钉着。
        assertEquals(0, positionToSortOrder(1))
        assertEquals(2, positionToSortOrder(3))
        // 反向那一半（撤回是"把快照原样写回 payload"，所以读回来要还原成**位置**）
        val row = com.tapmoay.sorders.data.remote.dto.ProductCategoryDto(
            id = 71, name = "水果", sortOrder = 0, productCount = 12,
        )
        assertEquals(1, AiRevertRead.productCategory(row)["sort_order"].toString().toInt())
    }

    @Test
    fun `新建分类：不填位置就排在最后（不发 sort_order）`() = runBlocking {
        val r = Rig()
        val card = ok(r.svc.preview(AiWrites.PRODUCT_CATEGORY_CREATE, p("name" to "冻品B")))
        assertTrue(card.detailLines.any { it.contains("排在最后") })
        r.svc.execute(card.token)
        val call = r.ds.masterCalls.single()
        assertTrue(call.startsWith("createProductCategory:"))
        assertFalse("不填位置就不该发 sort_order：$call", call.contains("sort_order"))
    }

    @Test
    fun `删分类：高危，并写明「还有商品挂着会被拒绝」`() = runBlocking {
        val r = Rig()
        val card = ok(r.svc.preview(AiWrites.PRODUCT_CATEGORY_DELETE, p("category" to "水果")))
        assertEquals(AiWriteRisk.HIGH, card.risk)
        assertTrue(card.detailLines.any { it.contains("12 个商品") })
        assertTrue(card.detailLines.any { it.contains("先把那些商品改成别的分类") })
        r.svc.execute(card.token)
        assertEquals("deleteProductCategory:71", r.ds.masterCalls.single())
    }

    @Test
    fun `删分类的撤回：按原名重建一格，而且不许照搬「行还在」那套假话`() = runBlocking {
        val r = Rig()
        r.ds.snapshots["product_category:71"] = buildJsonObject {
            put("name", "水果")
            put("sort_order", JsonPrimitive(1))
        }
        val card = ok(r.svc.preview(AiWrites.PRODUCT_CATEGORY_DELETE, p("category" to "水果")))
        val done = r.svc.execute(card.token) as AiWriteOutcome.Done
        assertNotNull("删分类必须带撤回入口（用户的原话是「不要删了就搞不回来了」）", done.undoToken)

        val undoCard = ok(r.svc.offerUndo(done.undoToken!!))
        val text = undoCard.detailLines.joinToString("\n")
        assertTrue("撤回卡要说清这是重建：$text", text.contains("重建"))
        assertFalse("分类是真删，不能照搬软删那两句：$text", text.contains("逐字段照搬"))

        r.svc.execute(undoCard.token)
        val call = r.ds.masterCalls.last()
        assertTrue("按原来的名字重建：$call", call.startsWith("createProductCategory:") && call.contains("水果"))
    }

    @Test
    fun `重排分类：漏了分类就整份拒绝，并点名少了谁`() = runBlocking<Unit> {
        val r = Rig()
        val out = rejected(
            r.svc.preview(AiWrites.PRODUCT_CATEGORY_REORDER, p("order" to "水果、冻品")),
        )
        assertTrue("要说清少了谁：${out.reason}", out.reason.contains("干货"))
        assertEquals(0, r.ds.masterCalls.size)
    }

    @Test
    fun `重排分类：卡片把新顺序整个列出来（不是一句「顺序已调整」）`() = runBlocking {
        val r = Rig()
        val card = ok(
            r.svc.preview(AiWrites.PRODUCT_CATEGORY_REORDER, p("order" to "干货、水果、冻品")),
        )
        assertEquals("重排商品分类：3 个分类", card.summary)
        val text = card.detailLines.joinToString("\n")
        assertTrue("要有改前那一份：$text", text.contains("改前的顺序：水果、冻品、干货"))
        assertTrue("新顺序要逐行列出来：$text", text.contains("1. 干货"))
        assertTrue(text.contains("2. 水果（12 个商品）"))
        r.svc.execute(card.token)
        assertEquals("reorderProductCategories:73,71,72", r.ds.masterCalls.single())
    }

    @Test
    fun `重排分类：同一个分类写两次就拒绝（后端会 400，卡片要先拦住）`() = runBlocking<Unit> {
        val r = Rig()
        val out = rejected(
            r.svc.preview(AiWrites.PRODUCT_CATEGORY_REORDER, p("order" to "水果、水果、冻品、干货")),
        )
        assertTrue(out.reason.contains("两次"))
        assertEquals(0, r.ds.masterCalls.size)
    }

    @Test
    fun `商品可见范围：custom 必须把商品名一个一个列出来`() = runBlocking {
        val r = Rig()
        val card = ok(
            r.svc.preview(
                AiWrites.USER_PRODUCT_VISIBILITY,
                p("user" to "城东水果批发", "scope" to "custom", "products" to "红富士苹果、皇冠梨"),
            ),
        )
        assertEquals("商品可见范围：城东水果批发 → 只给勾选的 2 个商品", card.summary)
        val text = card.summary + "\n" + card.detailLines.joinToString("\n")
        // 只写"N 个"，用户核对不了是哪几个——所以名字必须逐个列出来
        assertTrue("要列名字：$text", text.contains("1. 红富士苹果"))
        assertTrue("要列名字：$text", text.contains("2. 皇冠梨"))
        assertTrue("要写改前是什么样：$text", text.contains("现在：全部商品（不限制）"))
        r.svc.execute(card.token)
        assertEquals("setProductVisibility:31:custom:41,42|||", r.ds.masterCalls.single())
    }

    @Test
    fun `商品可见范围：custom 一个都没勾就拒绝（那样他打开选品页是空的）`() = runBlocking<Unit> {
        val r = Rig()
        val out = rejected(
            r.svc.preview(AiWrites.USER_PRODUCT_VISIBILITY, p("user" to "城东水果批发", "scope" to "custom")),
        )
        assertTrue(out.reason.contains("空的"))
        assertEquals(0, r.ds.masterCalls.size)
    }

    @Test
    fun `商品可见范围：改回全部商品会清掉旧白名单，卡片上写明`() = runBlocking {
        val r = Rig()
        r.ds.visibility = AiVisibility("custom", listOf(41, 42))
        val card = ok(
            r.svc.preview(AiWrites.USER_PRODUCT_VISIBILITY, p("user" to "城东水果批发", "scope" to "all")),
        )
        val text = card.detailLines.joinToString("\n")
        assertTrue("改前那一份也要列名字：$text", text.contains("红富士苹果"))
        assertTrue("清掉白名单这件事必须写在卡上：$text", text.contains("会被清掉"))
        r.svc.execute(card.token)
        assertEquals("setProductVisibility:31:all:|||", r.ds.masterCalls.single())
    }

    @Test
    fun `商品可见范围：撤回把开关和白名单整份写回去`() = runBlocking {
        val r = Rig()
        r.ds.visibility = AiVisibility("custom", listOf(41))
        val card = ok(
            r.svc.preview(AiWrites.USER_PRODUCT_VISIBILITY, p("user" to "城东水果批发", "scope" to "all")),
        )
        val done = r.svc.execute(card.token) as AiWriteOutcome.Done
        val undoCard = ok(r.svc.offerUndo(done.undoToken!!))
        assertTrue(
            "撤回卡要写清改回哪种模式：${undoCard.detailLines}",
            undoCard.detailLines.any { it.contains("撤回到 custom") },
        )
        r.svc.execute(undoCard.token)
        assertTrue("白名单要整份写回去：${r.ds.masterCalls}", r.ds.masterCalls.any { it == "setProductVisibility:31:custom:41|||" })
    }

    @Test
    fun `商品可见范围：只对货主和批发商有意义（拿派单员的名字会被拒绝）`() = runBlocking<Unit> {
        val r = Rig()
        r.ds.shippers = listOf(AiName(31, "城东水果批发"))
        val out = rejected(
            r.svc.preview(
                AiWrites.USER_PRODUCT_VISIBILITY,
                p("user" to "王建国", "scope" to "all"),
            ),
        )
        assertTrue("要说清它不是货主：${out.reason}", out.reason.contains("货主"))
        assertEquals(0, r.ds.masterCalls.size)
    }

    @Test
    fun `商品可见范围：按分类给（分类名按名册原文存，差一个字就存成空分类）`() = runBlocking {
        val r = Rig()
        val card = ok(
            r.svc.preview(
                AiWrites.USER_PRODUCT_VISIBILITY,
                p("user" to "城东水果批发", "scope" to "custom", "categories" to "水果"),
            ),
        )
        assertEquals("商品可见范围：城东水果批发 → 只给勾选的 1 个分类", card.summary)
        val text = card.summary + "\n" + card.detailLines.joinToString("\n")
        assertTrue("要列分类名：$text", text.contains("分类 1. 水果"))
        // 按分类给是"活的"：以后新建到这一类的商品自动也带上——这句必须写在卡上
        assertTrue("要说清是活的：$text", text.contains("以后新建到这一类里的商品"))
        r.svc.execute(card.token)
        assertEquals("setProductVisibility:31:custom:|水果||", r.ds.masterCalls.single())
    }

    @Test
    fun `商品可见范围：分类名对不上就拒绝（后端按名字存，差一个字会静默挂空）`() = runBlocking<Unit> {
        val r = Rig()
        val out = rejected(
            r.svc.preview(
                AiWrites.USER_PRODUCT_VISIBILITY,
                p("user" to "城东水果批发", "scope" to "custom", "categories" to "水果类"),
            ),
        )
        // 文案由 AiWriteArgs.strict 抛（本地那句兜底走不到）：要说清是**哪一个**名字对不上
        assertTrue("要说清对不上：${out.reason}", out.reason.contains("没有匹配「水果类」的商品分类"))
        assertEquals(0, r.ds.masterCalls.size)
    }

    @Test
    fun `商品可见范围：all 档单独关掉一件（在「全部商品」里挖洞，关掉优先于给看）`() = runBlocking {
        val r = Rig()
        val card = ok(
            r.svc.preview(
                AiWrites.USER_PRODUCT_VISIBILITY,
                p("user" to "城东水果批发", "scope" to "all", "hide_products" to "红富士苹果"),
            ),
        )
        assertEquals(
            "商品可见范围：城东水果批发 → 全部商品（不限制）（另单独关掉 1 个商品）",
            card.summary,
        )
        val text = card.detailLines.joinToString("\n")
        assertTrue("要写清关掉的是哪一件：$text", text.contains("另外关掉：红富士苹果"))
        assertTrue("关掉优先于给看这句话必须在卡上：$text", text.contains("关掉优先于给看"))
        r.svc.execute(card.token)
        assertEquals("setProductVisibility:31:all:||41|", r.ds.masterCalls.single())
    }

    @Test
    fun `商品可见范围：整类关掉（以后新建到这一类的商品也看不见）`() = runBlocking {
        val r = Rig()
        val card = ok(
            r.svc.preview(
                AiWrites.USER_PRODUCT_VISIBILITY,
                p(
                    "user" to "城东水果批发", "scope" to "custom",
                    "categories" to "水果", "hide_categories" to "冻品",
                ),
            ),
        )
        val text = card.detailLines.joinToString("\n")
        assertTrue("要写清关掉的是哪一类：$text", text.contains("另外关掉：冻品"))
        r.svc.execute(card.token)
        assertEquals("setProductVisibility:31:custom:|水果||冻品", r.ds.masterCalls.single())
    }

    @Test
    fun `商品可见范围：custom 给的又被关掉盖住就拒绝（配完一个都看不到）`() = runBlocking<Unit> {
        val r = Rig()
        val out = rejected(
            r.svc.preview(
                AiWrites.USER_PRODUCT_VISIBILITY,
                p(
                    "user" to "城东水果批发", "scope" to "custom",
                    "products" to "红富士苹果", "hide_products" to "红富士苹果",
                ),
            ),
        )
        assertTrue("要说清会被后端拒：${out.reason}", out.reason.contains("一个商品都看不到"))
        assertEquals(0, r.ds.masterCalls.size)
    }

    @Test
    fun `商品可见范围：撤回把四维整份写回去（少写一维就是静默清空那一维）`() = runBlocking {
        val r = Rig()
        r.ds.visibility = AiVisibility(
            scope = "custom",
            productIds = listOf(41),
            categoryNames = listOf("水果"),
            hiddenProductIds = listOf(42),
            hiddenCategoryNames = listOf("冻品"),
        )
        val card = ok(
            r.svc.preview(AiWrites.USER_PRODUCT_VISIBILITY, p("user" to "城东水果批发", "scope" to "all")),
        )
        val done = r.svc.execute(card.token) as AiWriteOutcome.Done
        val undoCard = ok(r.svc.offerUndo(done.undoToken!!))
        r.svc.execute(undoCard.token)
        assertEquals("setProductVisibility:31:custom:41|水果|42|冻品", r.ds.masterCalls.last())
    }

    @Test
    fun `改车辆：只发改的那几项（卡片逐字段写改前与改后）`() = runBlocking {
        val r = Rig()
        val card = ok(
            r.svc.preview(
                AiWrites.VEHICLE_UPDATE,
                p("vehicle" to "豫A12345", "plate" to "豫A00001", "vehicle_type" to "大货车"),
            ),
        )
        assertEquals("改车辆：豫A12345", card.summary)
        assertTrue(card.detailLines.any { it.contains("车牌改成：豫A00001") })
        assertTrue(card.detailLines.any { it.contains("车型改成：大货车") })
        r.svc.execute(card.token)
        val call = r.ds.masterCalls.single()
        assertTrue(call.startsWith("updateVehicle:21:"))
        assertTrue(call.contains("\"plate_no\":\"豫A00001\""))
        assertTrue(call.contains("\"vehicle_type\":\"large\""))
        // 没点名的项**不许**跟着发（后端是部分更新，多发一项就是多改一项）
        assertFalse("不该带上 active：$call", call.contains("active"))
        assertFalse("不该带上 driver_id：$call", call.contains("driver_id"))
    }

    @Test
    fun `换司机：填了人就是绑（卡片要写清现在归谁、改成谁）`() = runBlocking {
        val r = Rig()
        val card = ok(
            r.svc.preview(AiWrites.VEHICLE_SET_DRIVER, p("vehicle" to "豫A12345", "driver" to "王建国")),
        )
        assertEquals("给 豫A12345 配司机", card.summary)
        assertTrue("卡片必须写出现在归谁：${card.detailLines}", card.detailLines.any { it.contains("现在：李强") })
        assertTrue(card.detailLines.any { it.contains("改成：王建国") })
        r.svc.execute(card.token)
        assertEquals("setVehicleDriver:21:11", r.ds.masterCalls.single())
    }

    @Test
    fun `换司机：不填司机就是解绑（这条以前根本做不到）`() = runBlocking {
        // v3.44 之前：`driver_id=null` 被后端 `if ... is not None` 静默忽略，
        // 于是"把 A12345 从张三名下拿掉"没有任何表达方式，AI 只能在卡上写一句
        // 「这条接口解绑不了」。现在解绑是一等动作：**不填就是解绑**。
        val r = Rig()
        val card = ok(r.svc.preview(AiWrites.VEHICLE_SET_DRIVER, p("vehicle" to "豫A12345")))
        assertEquals("解绑司机：豫A12345", card.summary)
        assertTrue("解绑也要说清被拿掉的是谁：${card.detailLines}", card.detailLines.any { it.contains("现在：李强") })
        assertTrue(card.detailLines.any { it.contains("不绑司机") })
        r.svc.execute(card.token)
        assertEquals("setVehicleDriver:21:null", r.ds.masterCalls.single())
    }

    @Test
    fun `换司机：司机查不到就拒绝（不许静默把这个人丢掉）`() = runBlocking<Unit> {
        val r = Rig()
        val out = rejected(
            r.svc.preview(AiWrites.VEHICLE_SET_DRIVER, p("vehicle" to "豫A12345", "driver" to "张三不存在")),
        )
        assertTrue(out.reason.contains("司机"))
        assertEquals(0, r.ds.masterCalls.size)
    }

    @Test
    fun `换司机：车查不到就拒绝（解绑一辆不存在的车是最坏的一种成功）`() = runBlocking<Unit> {
        val r = Rig()
        val out = rejected(r.svc.preview(AiWrites.VEHICLE_SET_DRIVER, p("vehicle" to "豫Z00000")))
        assertTrue(out.reason.contains("车辆"))
        assertEquals(0, r.ds.masterCalls.size)
    }

    @Test
    fun `改车辆：司机不在这条动作里（两条路都叫换司机会让模型挑错）`() {
        val act = AiWrites.byId(AiWrites.VEHICLE_UPDATE) ?: error("动作不见了")
        val params = act.params.map { it.name }
        assertFalse("改车辆不该再有 driver 参数：$params", params.contains("driver"))
        assertTrue(params.contains("vehicle"))
    }

    @Test
    fun `名册别名：手机号也能对上人（真机实测：说手机号被答系统里没有这个人）`() {
        // 真机现象（v3.44 E2E）：用户说「把货主 13800000002 的商品可见范围改成…」，
        // 模型照说手机号 → 拿到「系统里没有匹配「13800000002」的货主/批发商」，
        // 而那个人明明在系统里（名册就是**按 `?q=` 搜出来的**，搜得到、认不出）。
        // 根因：匹配只看 `label`（姓名）。修法：`aliases` 与 label 一起参与两轮匹配。
        val pool = listOf(AiName(2, "Shipper", aliases = listOf("13800000002")))
        assertEquals(2L, AiWriteArgs.strict("13800000002", pool, "货主/批发商")!!.id)
        assertEquals(2L, AiWriteArgs.strict("Shipper", pool, "货主/批发商")!!.id)
        assertEquals(2L, AiWriteArgs.strict("1380000", pool, "货主/批发商")!!.id)   // 包含也算
        // ⚠️ 别名**不许进 label**：手机号会原样上确认卡，那是个人信息
        assertEquals("Shipper", pool.first().label)
    }

    @Test
    fun `名册别名：不存在的号照样拒绝（别名不是万能通行证）`() {
        val pool = listOf(AiName(2, "Shipper", aliases = listOf("13800000002")))
        val msg = try {
            AiWriteArgs.strict("13900000000", pool, "货主/批发商")
            ""
        } catch (e: AiWriteArgException) {
            e.message.orEmpty()
        }
        assertTrue("查不到时必须抛（而且要说人话）：$msg", msg.contains("没有匹配"))
    }

    @Test
    fun `改车辆：停用会写在卡上（列表里会出现「停用」标记）`() = runBlocking {
        val r = Rig()
        val card = ok(
            r.svc.preview(AiWrites.VEHICLE_UPDATE, p("vehicle" to "豫A12345", "active" to "false")),
        )
        assertTrue(card.detailLines.any { it.contains("停用") })
        r.svc.execute(card.token)
        assertTrue(r.ds.masterCalls.single().contains("\"active\":\"false\""))
    }

    @Test
    fun `目录域三个动作默认只给派单员（货主 fail-closed）`() {
        val ids = listOf(
            AiWrites.PRODUCT_CATEGORY_CREATE,
            AiWrites.PRODUCT_CATEGORY_UPDATE,
            AiWrites.PRODUCT_CATEGORY_DELETE,
            AiWrites.PRODUCT_CATEGORY_REORDER,
            AiWrites.USER_PRODUCT_VISIBILITY,
            AiWrites.VEHICLE_UPDATE,
            AiWrites.VEHICLE_SET_DRIVER,
        )
        for (id in ids) {
            assertTrue("$id 应当在派单员动作集里", AiWrites.allows(AiActor.byRole(AiRole.DISPATCHER), id))
            assertFalse("$id 不该给货主", AiWrites.allows(AiActor.byRole(AiRole.SHIPPER), id))
            assertFalse("$id 不该给未知角色", AiWrites.allows(null, id))
        }
        // 地点分组是**按人分区**的（每个人管自己地址库左栏那一列），所以货主**要能用** ——
        // 与「地点增删改」同一件事的两半。它和上面那批"只给派单员"的区别是刻意的，不是漏标。
        for (id in listOf(
            AiWrites.PLACE_CATEGORY_CREATE,
            AiWrites.PLACE_CATEGORY_UPDATE,
            AiWrites.PLACE_CATEGORY_DELETE,
            AiWrites.PLACE_CATEGORY_REORDER,
            // FEAT-0007：联系人分类与地点分组同一个道理（按人分区、改的是自己的名册），
            // 所以货主也**必须**能用 —— 与「联系人增删改」是同一件事的两半。
            AiWrites.CONTACT_CATEGORY_CREATE,
            AiWrites.CONTACT_CATEGORY_UPDATE,
            AiWrites.CONTACT_CATEGORY_DELETE,
            AiWrites.CONTACT_CATEGORY_REORDER,
            // FEAT-0009：线路分类与上面两份同一个道理（按人分区、改的是自己的名册），
            // 所以货主也**必须**能用 —— 与「线路增删改」是同一件事的两半。
            AiWrites.ROUTE_CATEGORY_CREATE,
            AiWrites.ROUTE_CATEGORY_UPDATE,
            AiWrites.ROUTE_CATEGORY_DELETE,
            AiWrites.ROUTE_CATEGORY_REORDER,
        )) {
            assertTrue("$id 货主也要能用（改的是他自己的地址库）", AiWrites.allows(AiActor.byRole(AiRole.SHIPPER), id))
            assertFalse("$id 不该给未知角色", AiWrites.allows(null, id))
        }
    }

    // ==================================================== 批量捷径（端到端：走**真的** AiWriteService）

    /**
     * 这一条与 `AiWriteBatchTest` 分工不同：那边测的是**装饰器本身**（假的处理器），
     * 这一条走**真的** [AiWriteService]（真的动作表、真的角色门、真的暂存区、真的派生幂等键），
     * 证明"接线接上了"——批量的 `items` 真的能从 `preview` 走到 `execute`，
     * 而不是只有单测里那个手工 new 出来的装饰器能用。
     */
    @Test
    fun `批量：一次调用写两条，一张卡确认一次、逐条落库`() = runBlocking {
        val r = Rig()
        val items = buildJsonObject {
            putJsonArray(BatchWriteHandler.BATCH_ITEMS) {
                add(expenseParams("note" to "第一趟"))
                add(expenseParams("amount" to "120", "note" to "补胎"))
            }
        }
        val card = ok(r.svc.preview(AiWrites.EXPENSES_CREATE, items))

        // 一张卡（内层那两张单条卡被取走了），卡上逐条列着，摘要写着真实条数
        assertEquals("批量记一笔支出：2 条", card.summary)
        assertEquals(1, r.store.list().size)
        assertTrue(card.detailLines.any { it.contains("第一趟") })
        assertTrue(card.detailLines.any { it.contains("补胎") })

        val done = r.svc.execute(card.token) as AiWriteOutcome.Done
        // 两条都落库，而且各自带**自己的**幂等键（不是同一条发两遍）
        assertEquals(2, r.ds.expenses.size)
        assertEquals(listOf("300.00", "120.00"), r.ds.expenses.map { it.first.amount })
        assertEquals(listOf("ai-${card.token}-0", "ai-${card.token}-1"), r.ds.expenses.map { it.second })
        // 逐条汇报写在最终答复里；批量不挂撤回（卡片上也这么写着）
        assertTrue("没汇报逐条结果：${done.message}", done.message.contains("这一批 2 条：成功 2 条"))
        assertNull("批量不该挂撤回按钮", done.undoToken)
        assertEquals(AiWrites.BATCH_UNDO_NOTE, card.detailLines.last())
    }

    @Test
    fun `批量：某一条名字对不上 → 整批不发，且指出是第几条`() = runBlocking {
        val r = Rig()
        val items = buildJsonObject {
            putJsonArray(BatchWriteHandler.BATCH_ITEMS) {
                add(p("product" to "红富士苹果", "price" to "10"))
                add(p("product" to "查无此物", "price" to "11"))
            }
        }
        val out = rejected(r.svc.preview(AiWrites.PRODUCTS_UPDATE, items))
        assertTrue("要指出第几条：${out.reason}", out.reason.contains("第 2 条"))
        assertEquals("一张卡都不许留", 0, r.store.list().size)
        assertEquals("一条都不许写", 0, r.ds.masterCalls.size)
    }

    @Test
    fun `批量：不用确认的那一档（消息全标已读）拒绝走批量`() = runBlocking {
        val r = Rig()
        val out = rejected(
            r.svc.preview(
                AiWrites.NOTIFICATIONS_READ_ALL,
                buildJsonObject { putJsonArray(BatchWriteHandler.BATCH_ITEMS) { add(p()) } },
            ),
        )
        assertTrue(out.reason.contains("不需要确认"))
        // ⚠️ 最要紧的是这一条：它在 `prepare` 里就会写库，放进来等于**预览阶段就写库**
        assertEquals("内层一次都不许被调用", 0, r.ds.readAllCalls)
    }


    // ==================================================== 我的下游价（CHG-0084 / 台账 L-53）

    /**
     * 「我能定价的商品」一条（`GET /shipper-prices/products`）的替身。
     *
     * 为什么不直接写 `AiMyPriceProduct(...)`：这一域要造十几条散据，字段名在调用处全都是位置参数，
     * 错一位就会把“默认价”和“上游给我的价”对调（那两个数字在卡片上都是钱，对调了也能过编译）。
     */
    private fun priceProductRow(
        id: Long = 41,
        name: String = "红富士苹果",
        supply: String? = "6.50",
        default: String? = null,
        contacts: Int = 0,
    ) = AiMyPriceProduct(id, name, supply, default, contacts)

    /** 「我定过的一条下游价」（`GET /shipper-prices`）的替身。 */
    private fun priceRow(
        id: Long,
        productId: Long = 41,
        product: String = "红富士苹果",
        contactId: Long? = null,
        contact: String? = null,
        unitPrice: String = "9.90",
        isDeleted: Boolean = false,
    ) = AiMyPriceRef(id, productId, product, contactId, contact, unitPrice, isDeleted)

    @Test
    fun `下游价：给所有下游定默认价 —— 卡上写明这是默认价，确认后按商品编号写一次`() = runBlocking<Unit> {
        // 货主里只有**批发商**有这本账（`memberOnly`）：普通货主连清单里都没有这三条。
        val r = Rig(actor = AiActor.of(AiRole.SHIPPER, true))
        r.ds.myPriceProductRows = mutableListOf(priceProductRow())

        val card = ok(
            r.svc.preview(AiWrites.SHIPPER_PRICE_SET, p("product" to "红富士苹果", "price" to "9.9")),
        )
        assertEquals("下游价：红富士苹果 → 9.9 元（所有下游）", card.summary)
        assertTrue(card.bodyLines.contains("商品：红富士苹果"))
        assertTrue(
            "不写联系人 = 默认价，卡上必须说清：${card.bodyLines}",
            card.bodyLines.contains("给谁：所有下游（这是默认价，没单独定价的人都按它算）"),
        )
        assertTrue(card.bodyLines.any { it.contains("这一档还没有定过价") })
        // 两句口径：只管以后新下的单 ＋ 只动他自己那本账
        assertTrue(card.bodyLines.any { it.contains("只管以后新下的单") })
        assertTrue(card.bodyLines.any { it.contains("公司（派单员）那边的账一个数字都不会变") })
        // 预览阶段一个字都不许写后端（写下去就没有“确认”这一步了）
        assertEquals(0, r.ds.myPriceCalls.size)

        val done = r.svc.execute(card.token) as AiWriteOutcome.Done
        // 定价那条**没有**一键撤回（后端是“有就改、没有就建”，写之前不知道该撤到哪一条）
        assertNull("改价不该挂一键撤回（要改回去就再说一句）", done.undoToken)
        assertEquals(listOf("set:41:0:9.90"), r.ds.myPriceCalls)
    }

    @Test
    fun `下游价：给某一位下游定价 —— 卡上写明盖过默认价、回收站里那条会被复活`() = runBlocking<Unit> {
        val r = Rig(actor = AiActor.of(AiRole.SHIPPER, true))
        r.ds.myPriceProductRows = mutableListOf(priceProductRow(default = "8.00", contacts = 1))
        // 回收站里已经有一条（同一个商品 × 同一位下游）—— 再设一次就是把它复活
        r.ds.myPriceRows = mutableListOf(
            priceRow(7, contactId = 93, contact = "赵六", unitPrice = "12.50", isDeleted = true),
        )

        val card = ok(
            r.svc.preview(
                AiWrites.SHIPPER_PRICE_SET,
                p("product" to "红富士苹果", "contact" to "赵六", "price" to "12.5"),
            ),
        )
        assertEquals("下游价：红富士苹果 → 12.5 元（赵六 13700000000）", card.summary)
        assertTrue(
            "给某一位下游定 = 盖过默认价：${card.bodyLines}",
            card.bodyLines.any { it.contains("赵六 13700000000") && it.contains("盖过默认价") },
        )
        // ⚠️ 最要紧的一句：后端是 upsert，这次写下去是**复活软删那一行**，不是新建
        assertTrue(
            "必须说清是复活：${card.bodyLines}",
            card.bodyLines.any { it.contains("复活") && it.contains("不是新建一条") },
        )
        // 参考行：这个商品的默认价（他没单独价时按它算）＋已经给几个下游定过价
        assertTrue("要给出参考价：${card.bodyLines}", card.bodyLines.any { it.contains("默认价是 8 元") })
        assertTrue(card.bodyLines.any { it.contains("已经单独给 1 个下游定过价") })

        assertTrue(r.svc.execute(card.token) is AiWriteOutcome.Done)
        assertEquals(listOf("set:41:93:12.50"), r.ds.myPriceCalls)
    }

    @Test
    fun `下游价：删掉某一位下游的价 —— 卡上写明回落口径，撤回能把那一行放回来`() = runBlocking<Unit> {
        val r = Rig(actor = AiActor.of(AiRole.SHIPPER, true))
        r.ds.myPriceRows = mutableListOf(
            priceRow(7, unitPrice = "9.90"),
            priceRow(9, contactId = 93, contact = "赵六", unitPrice = "12.50"),
        )

        val card = ok(
            r.svc.preview(
                AiWrites.SHIPPER_PRICE_DELETE,
                p("product" to "红富士苹果", "contact" to "赵六"),
            ),
        )
        assertEquals("删掉下游价：红富士苹果 → 12.5 元（赵六 13700000000）", card.summary)
        assertTrue(card.bodyLines.any { it.contains("要删的这条价：12.5 元") })
        // 删专属价必须说清他回落到哪一档（这句话没了，用户就不知道删完价算多少）
        assertTrue("要说清他回落到哪：${card.bodyLines}", card.bodyLines.any { it.contains("他回落你的默认价") })
        assertTrue("后台是伪装删除，卡上必须说：${card.bodyLines}", card.bodyLines.any { it.contains("伪装删除") })
        assertTrue(card.bodyLines.any { it.contains("只影响以后新下的单") })
        assertEquals(0, r.ds.myPriceCalls.size)

        val done = r.svc.execute(card.token) as AiWriteOutcome.Done
        assertEquals(listOf("delete:9"), r.ds.myPriceCalls)
        assertNotNull("删价必须带撤回入口", done.undoToken)

        // 撤回走的是“恢复”那个动作本身（成对动作），而且只用编号（不读现场）
        val undo = ok(r.svc.offerUndo(done.undoToken!!))
        assertTrue(r.svc.execute(undo.token) is AiWriteOutcome.Done)
        assertEquals(listOf("delete:9", "restore:9"), r.ds.myPriceCalls)
    }

    @Test
    fun `下游价：同一档留下两条时 —— 不说单价就拦住，说了才认`() = runBlocking<Unit> {
        val r = Rig(actor = AiActor.of(AiRole.SHIPPER, true))
        // 默认价那一档（`contact_id IS NULL`）唯一键管不住 —— 老数据里同一档真的可能留下两条，
        // 而后端 `find_row` 只认第一条。那种时候**不能替他挑一条**，必须用单价指认。
        r.ds.myPriceRows = mutableListOf(
            priceRow(7, unitPrice = "9.90"),
            priceRow(9, unitPrice = "11.00"),
        )

        val out = rejected(r.svc.preview(AiWrites.SHIPPER_PRICE_DELETE, p("product" to "红富士苹果")))
        assertTrue("要问清是哪一条：${out.reason}", out.reason.contains("说单价"))
        assertEquals("拦住的时候一个字都不许写", 0, r.ds.myPriceCalls.size)

        val card = ok(
            r.svc.preview(
                AiWrites.SHIPPER_PRICE_DELETE,
                p("product" to "红富士苹果", "price" to "11"),
            ),
        )
        assertEquals("删掉下游价：红富士苹果 → 11 元（所有下游）", card.summary)
        assertTrue(card.bodyLines.any { it.contains("删的是这个商品的默认价") })
        assertTrue(r.svc.execute(card.token) is AiWriteOutcome.Done)
        assertEquals(listOf("delete:9"), r.ds.myPriceCalls)
    }

    @Test
    fun `下游价：批发商资格没了 —— 当场拦住，并且告诉用户该找谁`() = runBlocking<Unit> {
        // 真事：资格被派单员取消了，而 App 里那个 actor 还是旧的（角色门分不出两种货主）。
        // “发一张点了必然 403 的卡”是本项目明确列为最坏的一类 bug —— 所以必须在 `prepare` 里当场拦。
        val r = Rig(actor = AiActor.of(AiRole.SHIPPER, true))
        r.ds.memberShipper = false
        r.ds.myPriceProductRows = mutableListOf(priceProductRow())

        val out = rejected(
            r.svc.preview(AiWrites.SHIPPER_PRICE_SET, p("product" to "红富士苹果", "price" to "9.9")),
        )
        assertTrue("要说清是哪本账没有：${out.reason}", out.reason.contains("普通货主"))
        assertEquals("拦住的时候一个字都不许写", 0, r.ds.myPriceCalls.size)
    }
    // ==================================================== 订单结构三条（CHG-0085，台账 L-54）
    //
    // 这三条各自有一个"名字很像、后果完全不同"的邻居，所以用例的重点都不是"参数有没有传下去"：
    //   · 转货 ↔ 撤销 / 派单：源单可能只剩几行、也可能被搬空作废，目标单可能并进别人名下那一张；
    //   · 静默退回 ↔ 撤回派单：同一个状态跃迁，**唯一**的差别是货主那边一个提醒都没有；
    //   · 补联系信息 ↔ 改单：同一张单，开的是货主那一扇门（后端 order:edit_contact），只动四个字段。
    // 于是每一条都断言同一组东西：① 卡片把差别写清楚了；② 拦得住的时候在**弹卡之前**就拦；
    // ③ 落库那一次调用，就是卡片上那一行。

    /** 转货的 lines：处理器认的是**商品名 + 件数**（不是行 id，行 id 只在落库 payload 里）。 */
    private fun transferLines(vararg items: Pair<String, Int>): JsonArray = buildJsonArray {
        for ((product, qty) in items) {
            add(
                buildJsonObject {
                    put("product", product)
                    put("quantity", qty)
                },
            )
        }
    }

    /** 转货入参：lines 是数组，p() 装不下，所以单独拼一份。 */
    private fun transferParams(
        vararg kv: Pair<String, String>,
        lines: JsonElement? = null,
        order: String = "SOTEST2026091100230",
    ): JsonObject = buildJsonObject {
        put("order", order)
        kv.forEach { (k, v) -> put(k, v) }
        if (lines != null) put("lines", lines)
    }

    @Test
    fun `转货：转给系统里的货主 —— 卡片写清两张单会变成什么，落库只有行 id 和件数`() = runBlocking<Unit> {
        val r = Rig()
        r.ds.orders = listOf(r.ds.orders[0].copy(shipperId = 31), r.ds.orders[1])
        r.ds.snapshots["order:61"] = buildJsonObject {
            put("contact_dongjia_name", "王老板")
            put("contact_dongjia_phone", "13700001111")
        }

        val card = ok(
            r.svc.preview(
                AiWrites.ORDERS_TRANSFER,
                transferParams("to_shipper" to "城东水果批发", lines = transferLines("红富士苹果" to 2)),
            ),
        )

        assertEquals("转货：SOTEST2026091100230 转 1 行给 城东水果批发", card.summary)
        assertTrue(card.bodyLines.any { it.contains("目标货主：城东水果批发") })
        // 转给同一个人时后端按「同货主并单」处理 —— 不说出来用户会以为新开了一张
        assertTrue(card.bodyLines.any { it.contains("就是这一单现在的货主") })
        assertTrue(card.bodyLines.any { it.contains("合计转出 2 件 / 128") })
        assertTrue("目标单沿用原来的单价，不能在这里按别的价重算", card.bodyLines.any { it.contains("原来的单价") })
        assertTrue("源单还剩多少要算给他看", card.bodyLines.any { it.contains("还剩 5 件（2 行）") })
        assertTrue(card.bodyLines.any { it.contains("撤不回来") })
        // 收货人有电话 ⇒ 那句"司机到了没有人可打"的警告不该出现
        assertFalse(card.bodyLines.any { it.contains("收货人姓名和电话都是空的") })
        assertFalse("这一单还没派出去，不该冒出「跟着司机走」那一段", card.bodyLines.any { it.contains("会跟着他一起派出去") })

        assertTrue(r.svc.execute(card.token) is AiWriteOutcome.Done)
        assertEquals(listOf("transfer:61:31:901x2"), r.ds.orderCalls)
    }

    @Test
    fun `转货：临时货主 —— 不去名册里找名字，卡片要写明他在系统里没有账号`() = runBlocking<Unit> {
        val r = Rig()
        r.ds.snapshots["order:61"] = buildJsonObject {
            put("contact_dongjia_name", "王老板")
            put("contact_dongjia_phone", "13700001111")
        }

        val card = ok(
            r.svc.preview(
                AiWrites.ORDERS_TRANSFER,
                transferParams("to_temp_name" to "老王", lines = transferLines("皇冠梨" to 1)),
            ),
        )
        assertTrue(card.bodyLines.any { it.contains("目标货主：老王") })
        assertTrue("临时货主没有账号这件事必须写在卡片上", card.bodyLines.any { it.contains("临时货主") })
        assertTrue("临时货主这条路一次都不该去查名册（他自己就是没有账号的那种）", r.ds.searchShipperCalls.isEmpty())

        assertTrue(r.svc.execute(card.token) is AiWriteOutcome.Done)
        assertEquals(listOf("transfer:61:老王:902x1"), r.ds.orderCalls)
    }

    @Test
    fun `转货：转给谁必须二选一 —— 两个都给、一个都不给都在弹卡之前拦住`() = runBlocking<Unit> {
        val r = Rig()
        val both = rejected(
            r.svc.preview(
                AiWrites.ORDERS_TRANSFER,
                transferParams("to_shipper" to "城东水果批发", "to_temp_name" to "老王"),
            ),
        )
        assertTrue("要说清这两个是二选一：${both.reason}", both.reason.contains("只能给一个"))

        val none = rejected(r.svc.preview(AiWrites.ORDERS_TRANSFER, transferParams()))
        assertTrue("要问出转给谁：${none.reason}", none.reason.contains("转给谁"))
        assertTrue("要告诉他两个参数都能用：${none.reason}", none.reason.contains("to_temp_name"))

        assertEquals("拦住的时候一个字都不许写", 0, r.ds.orderCalls.size)
    }

    @Test
    fun `转货：明细的形状 —— 不是数组、空数组、不是对象、超过 10 行、超过现有件数、同一行写两次`() = runBlocking<Unit> {
        val r = Rig()
        val to = "to_shipper" to "城东水果批发"

        // 不是数组：必须把"现在是什么形状"说出来，否则模型下一轮很可能照原样再传一次
        val notArray = rejected(
            r.svc.preview(
                AiWrites.ORDERS_TRANSFER,
                transferParams(to, lines = JsonPrimitive("红富士苹果 2 件")),
            ),
        )
        assertTrue("要说出现在是「一段文字」：${notArray.reason}", notArray.reason.contains("一段文字"))
        assertTrue("要给出路（整单转出就别传这个参数）：${notArray.reason}", notArray.reason.contains("完全不传 lines"))

        val empty = rejected(
            r.svc.preview(AiWrites.ORDERS_TRANSFER, transferParams(to, lines = buildJsonArray { })),
        )
        assertTrue("空数组 = 一件都不转，没有意义：${empty.reason}", empty.reason.contains("空数组"))

        val notObject = rejected(
            r.svc.preview(
                AiWrites.ORDERS_TRANSFER,
                transferParams(to, lines = buildJsonArray { add(JsonPrimitive("红富士苹果")) }),
            ),
        )
        assertTrue("要说清每一项都得是对象：${notObject.reason}", notObject.reason.contains("每一项都要是一个对象"))

        val tooMany = rejected(
            r.svc.preview(
                AiWrites.ORDERS_TRANSFER,
                transferParams(to, lines = transferLines(*Array(11) { "红富士苹果" to 1 })),
            ),
        )
        assertTrue("上限 10 行：${tooMany.reason}", tooMany.reason.contains("最多转 10 行"))

        val over = rejected(
            r.svc.preview(AiWrites.ORDERS_TRANSFER, transferParams(to, lines = transferLines("红富士苹果" to 6))),
        )
        assertTrue("要拿库里的现在值说事：${over.reason}", over.reason.contains("现在只有 5 件"))

        val twice = rejected(
            r.svc.preview(
                AiWrites.ORDERS_TRANSFER,
                transferParams(to, lines = transferLines("红富士苹果" to 1, "红富士苹果" to 1)),
            ),
        )
        assertTrue("同一行写两次要拒（否则件数会被算两次）：${twice.reason}", twice.reason.contains("写了两次"))

        val unknown = rejected(
            r.svc.preview(AiWrites.ORDERS_TRANSFER, transferParams(to, lines = transferLines("西瓜" to 1))),
        )
        assertTrue("查不到的商品名要拒：${unknown.reason}", unknown.reason.contains("没有匹配"))

        assertEquals("拦住的时候一个字都不许写", 0, r.ds.orderCalls.size)
    }

    @Test
    fun `转货：终态单不能转；已接单的单不许整单转空（要指出该走哪条路）`() = runBlocking<Unit> {
        val r = Rig()
        r.ds.orders = listOf(
            r.ds.orders[0].copy(status = "DELIVERED"),
            r.ds.orders[1].copy(status = "ACCEPTED", driverLabel = "李强"),
        )

        val done = rejected(
            r.svc.preview(AiWrites.ORDERS_TRANSFER, transferParams("to_shipper" to "城东水果批发")),
        )
        assertTrue("要说清是状态不对，并且要说明为什么：${done.reason}", done.reason.contains("已送达"))
        assertTrue(done.reason.contains("不能转货"))

        // 已接单 + 不传 lines（= 整单转出）⇒ 不能直接把这单作废，必须先撤回派单
        val accepted = rejected(
            r.svc.preview(
                AiWrites.ORDERS_TRANSFER,
                transferParams("to_shipper" to "城东水果批发", order = "SOTEST2026091200229"),
            ),
        )
        assertTrue("要给出路（先撤回派单，或者只转一部分）：${accepted.reason}", accepted.reason.contains("撤回派单"))
        assertTrue(accepted.reason.contains("只转一部分"))

        assertEquals("拦住的时候一个字都不许写", 0, r.ds.orderCalls.size)
    }

    @Test
    fun `转货：收货人姓名电话都是空的 —— 不拦，但卡片要警告司机到了没有人可打`() = runBlocking<Unit> {
        // 后端只在四个联系字段**全空**时才拦（contact_info_missing），而临时货主那一路后端会把
        // "下单人"写成这个临时名字自己 ⇒ 这里拦不住也不该拦：更严的门会把后端允许的转货挡在卡片外。
        // 所以这件事只能落在卡片上（用户有权知道，也有权不改）。
        val r = Rig()
        val card = ok(
            r.svc.preview(
                AiWrites.ORDERS_TRANSFER,
                transferParams("to_temp_name" to "老王", lines = transferLines("红富士苹果" to 1)),
            ),
        )
        assertTrue(card.bodyLines.any { it.contains("收货人姓名和电话都是空的") })
        assertTrue("要给出路：先补一个电话再转", card.bodyLines.any { it.contains("补联系信息") })
        assertTrue("要把后端的原话带上（让模型知道后端什么时候才拦）", card.bodyLines.any { it.contains("请填写收货人或下单人") })

        assertTrue(r.svc.execute(card.token) is AiWriteOutcome.Done)
        assertEquals(listOf("transfer:61:老王:901x1"), r.ds.orderCalls)
    }

    @Test
    fun `静默退回：卡片要写明货主那边没有任何变化，理由只进司机那条通知`() = runBlocking<Unit> {
        val r = Rig()
        val card = ok(
            r.svc.preview(
                AiWrites.ORDERS_RELEASE,
                p("order" to "SOTEST2026091200229", "reason" to "车辆临时故障"),
            ),
        )
        assertEquals("退回派单池：SOTEST2026091200229（原司机 李强）", card.summary)
        // 这一条的**定义**就是"货主那边什么都不知道"：少写一句，用户就会以为是撤回派单
        assertTrue(card.bodyLines.any { it.contains("不会有任何变化") })
        assertTrue(card.bodyLines.any { it.contains("也收不到任何提醒") })
        assertTrue(card.bodyLines.any { it.contains("与「撤回派单」唯一的区别") })
        assertTrue(card.bodyLines.any { it.contains("李强会收到一条撤回通知，原因：车辆临时故障") })
        assertTrue(card.bodyLines.any { it.contains("回到「待派单」") })
        assertTrue("司机计件费/提成会跟着清掉，这会影响他的钱", card.bodyLines.any { it.contains("计件费") })
        assertTrue(card.bodyLines.any { it.contains("撤不回来") })

        val done = r.svc.execute(card.token)
        assertTrue(done is AiWriteOutcome.Done)
        assertEquals(listOf("release:62:车辆临时故障"), r.ds.orderCalls)
        assertNull("退回派单池没有撤回（理由见 AiRevert.undoNoneOf）", (done as AiWriteOutcome.Done).undoToken)
    }

    @Test
    fun `静默退回：不写理由 —— 后端收到空串，卡片上写「没写原因」`() = runBlocking<Unit> {
        val r = Rig()
        val card = ok(r.svc.preview(AiWrites.ORDERS_RELEASE, p("order" to "SOTEST2026091200229")))
        assertTrue("理由可选，但卡片上要说清这次没写：${card.bodyLines}", card.bodyLines.any { it.contains("（没写原因）") })

        assertTrue(r.svc.execute(card.token) is AiWriteOutcome.Done)
        // 后端允许空理由（这个动作的语义不依赖它）⇒ 必须原样传空串，不能替他编一句"未填写"
        assertEquals(listOf("release:62:"), r.ds.orderCalls)
    }

    @Test
    fun `静默退回：待派单、已送达的单没有「退」这回事 —— 弹卡之前就拒`() = runBlocking<Unit> {
        val r = Rig()
        val out = rejected(r.svc.preview(AiWrites.ORDERS_RELEASE, p("order" to "SOTEST2026091100230")))
        assertTrue("要说清只有哪两种状态能做：${out.reason}", out.reason.contains("只有「已派单」或「司机已接单」"))
        assertEquals("拦住的时候一个字都不许写", 0, r.ds.orderCalls.size)
    }

    @Test
    fun `补联系信息：货主补自己那一单 —— 旧值写进卡片，撤回挂着（撤回要读得回旧值）`() = runBlocking<Unit> {
        val r = Rig(actor = AiActor.of(AiRole.SHIPPER, true))
        r.ds.snapshots["order:61"] = buildJsonObject {
            put("contact_dongjia_phone", "13700001111")
        }

        val card = ok(
            r.svc.preview(
                AiWrites.ORDERS_UPDATE_CONTACT,
                p("order" to "SOTEST2026091100230", "dongjia_phone" to "13911112222"),
            ),
        )
        assertEquals("补联系信息：SOTEST2026091100230（1 项）", card.summary)
        assertTrue("旧值 → 新值要写出来：${card.bodyLines}", card.bodyLines.any { it.contains("· 收货人电话：13700001111 → 13911112222") })
        assertTrue("要说明这一条只能补联系信息", card.bodyLines.any { it.contains("只能补联系信息") })
        assertTrue(card.bodyLines.any { it.contains("补错了可以撤回") })

        val done = r.svc.execute(card.token)
        assertTrue(done is AiWriteOutcome.Done)
        assertNotNull("旧值读得回来就该挂上撤回", (done as AiWriteOutcome.Done).undoToken)
        assertEquals(
            listOf(
                "contact:61:" + buildJsonObject {
                    put("order_id", 61)
                    put("contact_dongjia_phone", "13911112222")
                }.toString(),
            ),
            r.ds.orderCalls,
        )
    }

    @Test
    fun `补联系信息：一个字段都不给要拦住；派单员连这张卡都看不到`() = runBlocking<Unit> {
        val shipper = Rig(actor = AiActor.of(AiRole.SHIPPER, true))
        val empty = rejected(
            shipper.svc.preview(AiWrites.ORDERS_UPDATE_CONTACT, p("order" to "SOTEST2026091100230")),
        )
        assertTrue("要告诉他至少填一项：${empty.reason}", empty.reason.contains("至少填一项"))
        assertTrue("要把能补的四项列出来：${empty.reason}", empty.reason.contains("收货人名称"))
        assertTrue(empty.reason.contains("下单人电话"))
        assertEquals("拦住的时候一个字都不许写", 0, shipper.ds.orderCalls.size)

        // 派单员：他要改联系人走「改单」那一张卡（orders.update）；这一条开的是货主那一扇门
        // （后端 order:edit_contact ⇒ 命令层 update_order(contact_only=True)），给他等于多开一扇。
        val dispatcher = Rig()
        val denied = rejected(
            dispatcher.svc.preview(
                AiWrites.ORDERS_UPDATE_CONTACT,
                p("order" to "SOTEST2026091100230", "dongjia_phone" to "13911112222"),
            ),
        )
        assertTrue("拒绝理由要说明是权限问题：${denied.reason}", denied.reason.contains("权限"))
        assertEquals("拦住的时候一个字都不许写", 0, dispatcher.ds.orderCalls.size)
    }

    @Test
    fun `补联系信息：终态单也能补（这正是它存在的理由）—— 但不再推司机`() = runBlocking<Unit> {
        val r = Rig(actor = AiActor.of(AiRole.SHIPPER, true))
        r.ds.orders = listOf(
            r.ds.orders[0].copy(status = "DELIVERED", driverLabel = "李强"),
            r.ds.orders[1],
        )
        r.ds.snapshots["order:61"] = buildJsonObject { put("contact_dongjia_name", "王老板") }

        val card = ok(
            r.svc.preview(
                AiWrites.ORDERS_UPDATE_CONTACT,
                p("order" to "SOTEST2026091100230", "dongjia_name" to "张三"),
            ),
        )
        // 货送完了才发现号码写错，正是这一条存在的理由 ⇒ 终态单**不设状态门**（与「改单」正好相反）
        assertTrue(
            "终态单补完不该再推司机：${card.bodyLines}",
            card.bodyLines.any { it.contains("已经是「已送达」") && it.contains("给司机推提醒") },
        )
        assertFalse("终态单不该出现「他手上的电话可能已经换了」：${card.bodyLines}", card.bodyLines.any { it.contains("订单有改动") })

        assertTrue(r.svc.execute(card.token) is AiWriteOutcome.Done)
        assertEquals(1, r.ds.orderCalls.size)
    }

    @Test
    fun `订单结构三条的角色门：转货和静默退回只给派单员，补联系信息只给货主`() {
        val shipper = AiActor.of(AiRole.SHIPPER, true)
        val dispatcher = AiActor.byRole(AiRole.DISPATCHER)

        assertTrue(AiWrites.allows(dispatcher, AiWrites.ORDERS_TRANSFER))
        assertTrue(AiWrites.allows(dispatcher, AiWrites.ORDERS_RELEASE))
        assertFalse(
            "补联系信息开的是货主那一扇门（order:edit_contact），派单员走「改单」那张卡",
            AiWrites.allows(dispatcher, AiWrites.ORDERS_UPDATE_CONTACT),
        )
        assertFalse("转货会同时改两张单，货主只能发起退货申请", AiWrites.allows(shipper, AiWrites.ORDERS_TRANSFER))
        assertFalse(AiWrites.allows(shipper, AiWrites.ORDERS_RELEASE))
        assertTrue(AiWrites.allows(shipper, AiWrites.ORDERS_UPDATE_CONTACT))

        // 模型那份清单（= forRole 去掉 undoOnly）：三条都该在里面，但货主那份里没有转货和退回
        assertTrue(AiWrites.forModel(dispatcher).any { it.id == AiWrites.ORDERS_TRANSFER })
        assertTrue(AiWrites.forModel(dispatcher).any { it.id == AiWrites.ORDERS_RELEASE })
        assertFalse(AiWrites.forModel(shipper).any { it.id == AiWrites.ORDERS_TRANSFER })
        assertFalse(AiWrites.forModel(shipper).any { it.id == AiWrites.ORDERS_RELEASE })
        assertTrue(AiWrites.forModel(shipper).any { it.id == AiWrites.ORDERS_UPDATE_CONTACT })
    }

    // ==================================================== 发票台账（CHG-0086，台账 L-55）
    //
    // 六条动作都只给派单员（后端要 ledger:edit）。这组用例的重点不是"能不能落库"——
    // 而是四件**用户看不见却会吃亏**的事：
    // ① 认不出是哪一张票时绝不动手（一个都不给就反问、对不上列候选、撞多张拒绝，票号唯一除外）；
    // ② 回收站里的票要"找得到、但说清楚它在回收站"，不许装成"系统里没有这张票"；
    // ③ 税额与后端同一个算法（只给税率时倒推），且算出来的数**显式进 payload**；
    // ④ 登记 / 开具 / 作废撤不回来 —— 卡片当场说清，别等点完才发现没有后悔药。

    /** 台账里现成的一张票：默认「已登记 · 销项 · 含税 13% · 1130 元」。 */
    private fun invRow(
        id: Long = 901L,
        direction: String = AiInvoiceRef.DIR_OUTPUT,
        no: String = "INV2026090001",
        date: String = "2026-10-01",
        amount: String = "1130.00",
        rate: String? = "13",
        tax: String? = null,
        status: String = AiInvoiceRef.ST_REGISTERED,
        party: String = "老王果行",
        note: String = "",
        deleted: Boolean = false,
    ): AiInvoiceRef = AiInvoiceRef(
        id = id,
        direction = direction,
        invoiceNo = no,
        invoiceDate = date,
        amount = amount,
        taxRate = rate,
        taxAmount = tax,
        status = status,
        partyName = party,
        note = note,
        isDeleted = deleted,
    )

    @Test
    fun `发票·登记进项票：名册查名、采购单逐张核，卡片把五件事写全`() = runBlocking<Unit> {
        val r = Rig()
        r.ds.supplierRows = listOf(AiName(501, "城东农资"))
        r.ds.purchaseRows = listOf(
            PurchaseOrderDto(id = 12, supplierId = 501),
            PurchaseOrderDto(id = 15, supplierId = 501),
        )

        val card = ok(
            r.svc.preview(
                AiWrites.INVOICES_CREATE,
                p(
                    "direction" to "INPUT",
                    "invoice_no" to "INV001",
                    "date" to "2026-10-01",
                    "amount" to "1130",
                    "tax_rate" to "13",
                    "supplier" to "城东农资",
                    "purchase_orders" to "12、15",
                ),
            ),
        )
        assertEquals("登记进项票 INV001：1130 元（含税 13%）", card.summary)
        assertTrue(card.detailLines.any { it.contains("方向：进项（供应商开给我们）") })
        assertTrue(card.detailLines.any { it.contains("票号：INV001") })
        assertTrue(card.detailLines.any { it.contains("开票日期：2026-10-01") })
        assertTrue(card.detailLines.any { it.contains("价税合计：1130 元") })
        assertTrue(
            card.detailLines.any {
                it.contains("税率：13%；税额：130 元（按「合计 ÷ (1 + 税率)」倒推，与后端同一个算法）")
            },
        )
        assertTrue(card.detailLines.any { it.contains("不含税金额：1000 元") })
        assertTrue(card.detailLines.any { it.contains("供应商：城东农资") })
        assertTrue(card.detailLines.any { it.contains("挂的采购单：#12、#15") })
        assertTrue(card.detailLines.any { it.contains("票号一旦登记就唯一占号") })
        assertTrue(card.detailLines.any { it.contains("以后改不动税率") })

        assertTrue(r.svc.execute(card.token) is AiWriteOutcome.Done)
        // 落库的税额是**算出来的**那个数：卡片上给用户看的数与库里存的数是同一个。
        assertEquals(
            "createInvoice:INPUT:INV001:2026-10-01:1130.00:13.00:130.00:501:null:12+15:",
            r.ds.invoiceCalls.single(),
        )
    }

    @Test
    fun `发票·登记销项票：没给税率就是未税票（卡片当场说清它不进税汇）`() = runBlocking<Unit> {
        val r = Rig()
        // customerRows 默认就有「老王果行」（301）
        val card = ok(
            r.svc.preview(
                AiWrites.INVOICES_CREATE,
                p("direction" to "OUTPUT", "date" to "2026-10-02", "amount" to "300", "customer" to "老王果行"),
            ),
        )
        assertEquals("登记销项票（票号还没拿到）：300 元（未税）", card.summary)
        assertTrue(card.detailLines.any { it.contains("票号：还没拿到，先空着（登记之后可以在台账里补上）") })
        assertTrue(
            card.detailLines.any { it.contains("税率：没填 —— 这是一张未税票：它照常留在台账里，但不进税汇") },
        )
        assertTrue(card.detailLines.any { it.contains("客户：老王果行") })
        assertTrue(card.detailLines.any { it.contains("空票号不参与查重") })
        assertFalse("未税票不该出现税额那一行：`{card.detailLines}`", card.detailLines.any { it.contains("税额：") })

        assertTrue(r.svc.execute(card.token) is AiWriteOutcome.Done)
        assertEquals("createInvoice:OUTPUT::2026-10-02:300.00:null:null:null:301::", r.ds.invoiceCalls.single())
    }

    @Test
    fun `发票·登记参数门：方向、对方、采购单一处不对就当场说清，一条都不许写`() = runBlocking<Unit> {
        val r = Rig()
        r.ds.supplierRows = listOf(AiName(501, "城东农资"))
        val base = arrayOf("direction" to "OUTPUT", "date" to "2026-10-01", "amount" to "100")

        assertTrue(
            rejected(r.svc.preview(AiWrites.INVOICES_CREATE, p("date" to "2026-10-01", "amount" to "100")))
                .reason.contains("缺少 direction"),
        )
        assertTrue(
            rejected(
                r.svc.preview(
                    AiWrites.INVOICES_CREATE,
                    p("direction" to "OUTPUT", "amount" to "100", "customer" to "老王果行"),
                ),
            ).reason.contains("缺少 date"),
        )
        assertTrue(
            rejected(
                r.svc.preview(
                    AiWrites.INVOICES_CREATE,
                    p("direction" to "OUTPUT", "date" to "2026-10-01", "customer" to "老王果行"),
                ),
            ).reason.contains("缺少 amount"),
        )
        assertTrue(
            rejected(
                r.svc.preview(
                    AiWrites.INVOICES_CREATE,
                    p("direction" to "不知道往哪开", "date" to "2026-10-01", "amount" to "100"),
                ),
            ).reason.contains("direction 只能是 OUTPUT"),
        )
        assertTrue(
            rejected(
                r.svc.preview(
                    AiWrites.INVOICES_CREATE,
                    p(
                        "direction" to "INPUT",
                        "date" to "2026-10-01",
                        "amount" to "100",
                        "supplier" to "城东农资",
                        "customer" to "老王果行",
                        "purchase_orders" to "12",
                    ),
                ),
            ).reason.contains("不该填客户"),
        )
        assertTrue(
            rejected(
                r.svc.preview(
                    AiWrites.INVOICES_CREATE,
                    p("direction" to "INPUT", "date" to "2026-10-01", "amount" to "100", "purchase_orders" to "12"),
                ),
            ).reason.contains("缺少 supplier"),
        )
        assertTrue(
            rejected(
                r.svc.preview(
                    AiWrites.INVOICES_CREATE,
                    p(*base, "customer" to "老王果行", "supplier" to "城东农资"),
                ),
            ).reason.contains("不该填供应商"),
        )
        assertTrue(
            rejected(
                r.svc.preview(
                    AiWrites.INVOICES_CREATE,
                    p(*base),
                ),
            ).reason.contains("缺少 customer"),
        )
        assertTrue(
            rejected(
                r.svc.preview(
                    AiWrites.INVOICES_CREATE,
                    p(*base, "customer" to "老王果行", "purchase_orders" to "12"),
                ),
            ).reason.contains("销项票不该挂采购单"),
        )
        assertTrue(
            rejected(
                r.svc.preview(
                    AiWrites.INVOICES_CREATE,
                    p(
                        "direction" to "INPUT",
                        "date" to "2026-10-01",
                        "amount" to "100",
                        "supplier" to "城东农资",
                    ),
                ),
            ).reason.contains("缺少 purchase_orders"),
        )
        // 名册里没有的名字：列候选、不猜
        assertTrue(
            rejected(
                r.svc.preview(
                    AiWrites.INVOICES_CREATE,
                    p(
                        "direction" to "INPUT",
                        "date" to "2026-10-01",
                        "amount" to "100",
                        "supplier" to "张三的店",
                        "purchase_orders" to "12",
                    ),
                ),
            ).reason.contains("名册里没有这个供应商"),
        )
        assertTrue(
            rejected(
                r.svc.preview(
                    AiWrites.INVOICES_CREATE,
                    p(
                        "direction" to "INPUT",
                        "date" to "2026-10-01",
                        "amount" to "100",
                        "supplier" to "城东农资",
                        "purchase_orders" to "第一张",
                    ),
                ),
            ).reason.contains("不是数字"),
        )
        assertTrue(
            rejected(
                r.svc.preview(
                    AiWrites.INVOICES_CREATE,
                    p(
                        "direction" to "INPUT",
                        "date" to "2026-10-01",
                        "amount" to "100",
                        "supplier" to "城东农资",
                        "purchase_orders" to "12",
                    ),
                ),
            ).reason.contains("不在系统里"),
        )
        assertEquals("一次都不许写", 0, r.ds.invoiceCalls.size)
    }

    @Test
    fun `发票·税额：只给税率时按后端同一算法倒推，并把算出来的数写进 payload`() = runBlocking<Unit> {
        val r = Rig()
        val card = ok(
            r.svc.preview(
                AiWrites.INVOICES_CREATE,
                p(
                    "direction" to "OUTPUT",
                    "date" to "2026-10-01",
                    "amount" to "1130",
                    "tax_rate" to "13",
                    "customer" to "老王果行",
                ),
            ),
        )
        assertTrue(card.detailLines.any { it.contains("税额：130 元（按「合计 ÷ (1 + 税率)」倒推") })
        assertTrue(r.svc.execute(card.token) is AiWriteOutcome.Done)
        assertTrue("算出来的税额要显式进 payload：`{r.ds.invoiceCalls}`", r.ds.invoiceCalls.single().contains(":130.00:"))

        // 票面上印了税额就以票面为准（不再倒推）
        val printed = ok(
            r.svc.preview(
                AiWrites.INVOICES_CREATE,
                p(
                    "direction" to "OUTPUT",
                    "date" to "2026-10-01",
                    "amount" to "1130",
                    "tax_rate" to "13",
                    "tax_amount" to "155",
                    "customer" to "老王果行",
                ),
            ),
        )
        assertTrue(printed.detailLines.any { it.contains("税额：155 元（票面上印的数）") })

        // 只给税额不给税率：这张票到底算不算税？—— 这件事必须在登记那一刻问清
        assertTrue(
            rejected(
                r.svc.preview(
                    AiWrites.INVOICES_CREATE,
                    p(
                        "direction" to "OUTPUT",
                        "date" to "2026-10-01",
                        "amount" to "1130",
                        "tax_amount" to "155",
                        "customer" to "老王果行",
                    ),
                ),
            ).reason.contains("只给了税额、没给税率"),
        )
        // 税额比合计还大：这两个数填反了
        assertTrue(
            rejected(
                r.svc.preview(
                    AiWrites.INVOICES_CREATE,
                    p(
                        "direction" to "OUTPUT",
                        "date" to "2026-10-01",
                        "amount" to "1130",
                        "tax_rate" to "13",
                        "tax_amount" to "1300",
                        "customer" to "老王果行",
                    ),
                ),
            ).reason.contains("是不是填反了"),
        )
    }

    @Test
    fun `发票·定位门：一个能收窄的都不给、找不到、撞上多张，都不许动手`() = runBlocking<Unit> {
        val r = Rig()
        val none = rejected(r.svc.preview(AiWrites.INVOICES_UPDATE, p("new_amount" to "100")))
        assertTrue(none.reason.contains("要动的是哪一张票？"))
        assertTrue("要给出下一步：`{none.candidates}`", none.candidates.any { it.contains("发票台账") })

        val missing = rejected(
            r.svc.preview(AiWrites.INVOICES_UPDATE, p("invoice_no" to "INV-NOPE", "new_amount" to "100")),
        )
        assertTrue(missing.reason.contains("台账里没找到这样一张票"))
        assertTrue(missing.reason.contains("票号「INV-NOPE」"))
        assertTrue(missing.reason.contains("最近 100 张里"))

        r.ds.invoiceRows = listOf(
            invRow(id = 901, no = "A1", date = "2026-10-01", amount = "1130.00"),
            invRow(id = 902, no = "A2", date = "2026-10-01", amount = "1130.00", party = "明辉食品商行"),
        )
        val many = rejected(
            r.svc.preview(
                AiWrites.INVOICES_UPDATE,
                p("date" to "2026-10-01", "amount" to "1130", "new_amount" to "100"),
            ),
        )
        assertTrue("撞多张要说清张数：`{many.reason}`", many.reason.contains("对上了 2 张票"))
        assertEquals(2, many.candidates.size)
        assertTrue(many.candidates.all { it.contains("销项票") })

        // 票号是唯一精确的键：同号两行（历史脏数据）不拒绝、直接认第一行 —— 这条是**例外**，
        // 因为"同一个方向同一个票号"在后端本来就只允许存在一张。
        r.ds.invoiceRows = listOf(invRow(id = 901, no = "A1"), invRow(id = 902, no = "A1", deleted = true))
        val byNo = ok(r.svc.preview(AiWrites.INVOICES_UPDATE, p("invoice_no" to "A1", "new_amount" to "100")))
        assertTrue(byNo.detailLines.any { it.contains("销项票 A1") })
        assertEquals("拦住的时候一个字都不许写", 0, r.ds.invoiceCalls.count { !it.startsWith("invoices:") })
    }

    @Test
    fun `发票·回收站里的票：找得到，但要如实说它在回收站里（不是「没有这张票」）`() = runBlocking<Unit> {
        val r = Rig()
        r.ds.invoiceRows = listOf(invRow(id = 901, deleted = true))

        val upd = rejected(
            r.svc.preview(AiWrites.INVOICES_UPDATE, p("invoice_no" to "INV2026090001", "new_amount" to "100")),
        )
        assertTrue(upd.reason.contains("在回收站里"))
        assertTrue(upd.reason.contains("回收站里的票改不动"))
        assertTrue(upd.reason.contains("先到「发票台账」页顶部切到"))
        assertFalse(
            "卡片不许再教用户说「恢复这张票」（那是 undoOnly 的恢复动作，模型念了也做不到）",
            upd.reason.contains("恢复这张票"),
        )

        assertTrue(
            rejected(r.svc.preview(AiWrites.INVOICES_ISSUE, p("invoice_no" to "INV2026090001")))
                .reason.contains("先恢复出来，再开具"),
        )
        assertTrue(
            rejected(r.svc.preview(AiWrites.INVOICES_VOID, p("invoice_no" to "INV2026090001")))
                .reason.contains("作废一个已经在回收站里的票没有意义"),
        )
        assertTrue(
            rejected(r.svc.preview(AiWrites.INVOICES_DELETE, p("invoice_no" to "INV2026090001")))
                .reason.contains("已经在回收站里了"),
        )

        // 这一条同时钉住"必须带 includeDeleted = true"：不带就等于"台账里根本没这张票"，
        // 那时用户会得到一句彻头彻尾的假话。
        assertTrue("每次定位都要连回收站一起找：`{r.ds.invoiceCalls}`", r.ds.invoiceCalls.all { it.endsWith(":true") })
        assertEquals("一条都不许写", 0, r.ds.invoiceCalls.count { !it.startsWith("invoices:") })
    }

    @Test
    fun `发票·改票的三道门：已开具、已作废、未税票，三种都改不动`() = runBlocking<Unit> {
        val r = Rig()
        r.ds.invoiceRows = listOf(invRow(status = AiInvoiceRef.ST_ISSUED))
        val issued = rejected(
            r.svc.preview(AiWrites.INVOICES_UPDATE, p("invoice_no" to "INV2026090001", "new_amount" to "100")),
        )
        assertTrue(issued.reason.contains("已经是「已开具」了，改不动"))
        assertTrue(issued.reason.contains("作废重开一张"))

        r.ds.invoiceRows = listOf(invRow(status = AiInvoiceRef.ST_VOIDED))
        assertTrue(
            rejected(
                r.svc.preview(AiWrites.INVOICES_UPDATE, p("invoice_no" to "INV2026090001", "new_amount" to "100")),
            ).reason.contains("已经是「已作废」了，改不动"),
        )

        // 未税票：加不上税率、也不该有税额 ——「有没有税」在登记那一刻就定了
        r.ds.invoiceRows = listOf(invRow(rate = null, tax = null))
        assertTrue(
            rejected(
                r.svc.preview(AiWrites.INVOICES_UPDATE, p("invoice_no" to "INV2026090001", "new_tax_rate" to "13")),
            ).reason.contains("现在加不上税率"),
        )
        assertTrue(
            rejected(
                r.svc.preview(AiWrites.INVOICES_UPDATE, p("invoice_no" to "INV2026090001", "new_tax_amount" to "130")),
            ).reason.contains("不该有税额"),
        )
        assertEquals("一次都不许写", 0, r.ds.invoiceCalls.count { !it.startsWith("invoices:") })
    }

    @Test
    fun `发票·改票：逐字段写改前改后、税额跟着重算；「没说要改什么」与「说的和现在一样」是两句话`() =
        runBlocking<Unit> {
            val r = Rig()
            r.ds.invoiceRows = listOf(invRow(note = "先记一笔"))

            val card = ok(
                r.svc.preview(
                    AiWrites.INVOICES_UPDATE,
                    p("invoice_no" to "INV2026090001", "new_amount" to "2260", "note" to ""),
                ),
            )
            assertEquals("改销项票 INV2026090001：价税合计 1130 元 → 2260 元（共 3 处）", card.summary)
            assertTrue(
                card.detailLines.any {
                    it.contains("这张票现在是：销项票 INV2026090001 · 2026-10-01 · 1130 元 · 含税 13% · 已登记 · 老王果行")
                },
            )
            assertTrue(card.detailLines.any { it.contains("价税合计：1130 元 → 2260 元") })
            assertTrue(card.detailLines.any { it.contains("税额：（空） → 260 元") })
            assertTrue(card.detailLines.any { it.contains("备注：先记一笔 → （清空）") })
            assertTrue(card.detailLines.any { it.contains("改完这张票还是「已登记」") })
            assertTrue(card.detailLines.any { it.contains("票的「有没有税」改不了") })

            assertTrue(r.svc.execute(card.token) is AiWriteOutcome.Done)
            // ⚠️ 不能写 .single()：preview 里那次"定位"也是一次数据源调用（invoices(...)）。
            val call = r.ds.invoiceCalls.last()
            assertTrue(call.startsWith("updateInvoice:901:"))
            assertTrue("合计要按新值发：`{call}`", call.contains("\"amount\":\"2260.00\""))
            // 合计变了、用户没显式给新税额 ⇒ 按同一算法重算（后端在"改了合计"时也是这么干的）
            assertTrue("税额要跟着重算：`{call}`", call.contains("\"tax_amount\":\"260.00\""))
            assertTrue("备注空串 = 清空：`{call}`", call.contains("\"note\":\"\""))
            assertFalse("没点名的项不许跟着发：`{call}`", call.contains("invoice_date"))
            assertFalse("票号没改就不该出现：`{call}`", call.contains("invoice_no"))

            // 什么都没说
            assertTrue(
                rejected(r.svc.preview(AiWrites.INVOICES_UPDATE, p("invoice_no" to "INV2026090001")))
                    .reason.contains("你还没说要改成什么"),
            )
            // 说了、但和现在一样 ⇒ 要明确说"没什么可改的"，而不是"你还没说"
            val same = rejected(
                r.svc.preview(
                    AiWrites.INVOICES_UPDATE,
                    p("invoice_no" to "INV2026090001", "new_amount" to "1130"),
                ),
            )
            assertTrue("说了但没变，要如实说：`{same.reason}`", same.reason.contains("和现在一模一样"))
            assertEquals(
                "拒绝的时候一个字都不许写",
                1,
                r.ds.invoiceCalls.count { !it.startsWith("invoices:") },
            )
        }

    @Test
    fun `发票·开具：卡片要把「冻结」与「和进不进税汇无关」两件事说清`() = runBlocking<Unit> {
        val r = Rig()
        r.ds.invoiceRows = listOf(invRow())
        val card = ok(r.svc.preview(AiWrites.INVOICES_ISSUE, p("invoice_no" to "INV2026090001")))
        assertEquals("开具销项票 INV2026090001：1130 元", card.summary)
        assertTrue(card.detailLines.any { it.contains("开具之后这张票就冻结了：一个字都改不动") })
        assertTrue(card.detailLines.any { it.contains("登记那天起就已经在税汇里了") })
        assertTrue(r.svc.execute(card.token) is AiWriteOutcome.Done)
        assertEquals("issueInvoice:901", r.ds.invoiceCalls.last())

        // 未税票：开不开都不影响税汇（它本来就不在税汇里）
        r.ds.invoiceRows = listOf(invRow(id = 902, rate = null, tax = null))
        val untaxed = ok(r.svc.preview(AiWrites.INVOICES_ISSUE, p("invoice_no" to "INV2026090001")))
        assertTrue(untaxed.detailLines.any { it.contains("这张是未税票，一直不进税汇") })

        r.ds.invoiceRows = listOf(invRow(status = AiInvoiceRef.ST_ISSUED))
        assertTrue(
            rejected(r.svc.preview(AiWrites.INVOICES_ISSUE, p("invoice_no" to "INV2026090001")))
                .reason.contains("已经开具过了"),
        )
        r.ds.invoiceRows = listOf(invRow(status = AiInvoiceRef.ST_VOIDED))
        assertTrue(
            rejected(r.svc.preview(AiWrites.INVOICES_ISSUE, p("invoice_no" to "INV2026090001")))
                .reason.contains("作废的票不能再开具"),
        )
    }

    @Test
    fun `发票·作废：票留在台账里、票号一直占着、退出税汇，且与「撤票」不是一件事`() = runBlocking<Unit> {
        val r = Rig()
        r.ds.invoiceRows = listOf(invRow())
        val card = ok(r.svc.preview(AiWrites.INVOICES_VOID, p("invoice_no" to "INV2026090001")))
        assertEquals("作废销项票 INV2026090001：1130 元", card.summary)
        assertTrue(card.detailLines.any { it.contains("票号一直占着、退出税汇") })
        assertTrue(card.detailLines.any { it.contains("税账上的变化：销项 / 进项合计里不再算它") })
        assertTrue(card.detailLines.any { it.contains("作废撤不回来") })
        assertTrue(card.detailLines.any { it.contains("它和「撤票」不是一件事") })
        assertTrue(r.svc.execute(card.token) is AiWriteOutcome.Done)
        assertEquals("voidInvoice:901", r.ds.invoiceCalls.last())

        // 未税票：作废只影响一件事（从此不能再开具）
        r.ds.invoiceRows = listOf(invRow(id = 902, rate = null, tax = null))
        val untaxed = ok(r.svc.preview(AiWrites.INVOICES_VOID, p("invoice_no" to "INV2026090001")))
        assertTrue(untaxed.detailLines.any { it.contains("本来就是未税票（不进税汇）") })

        // 已开具的票：作废是它唯一的出路
        r.ds.invoiceRows = listOf(invRow(status = AiInvoiceRef.ST_ISSUED))
        val issued = ok(r.svc.preview(AiWrites.INVOICES_VOID, p("invoice_no" to "INV2026090001")))
        assertTrue(issued.detailLines.any { it.contains("作废是已开具的票唯一的出路") })

        r.ds.invoiceRows = listOf(invRow(status = AiInvoiceRef.ST_VOIDED))
        assertTrue(
            rejected(r.svc.preview(AiWrites.INVOICES_VOID, p("invoice_no" to "INV2026090001")))
                .reason.contains("已经作废过了"),
        )
    }

    @Test
    fun `发票·撤票：进回收站、票号还占着；撤回把它原样放回来`() = runBlocking<Unit> {
        val r = Rig()
        r.ds.invoiceRows = listOf(invRow())
        val card = ok(r.svc.preview(AiWrites.INVOICES_DELETE, p("invoice_no" to "INV2026090001")))
        assertEquals("撤票（进回收站）销项票 INV2026090001：1130 元", card.summary)
        assertTrue(card.detailLines.any { it.contains("但票号仍然占着") })
        assertTrue(card.detailLines.any { it.contains("放回去随时可以") })
        assertTrue(
            "撤票卡要把恢复办法写成聊天里那个「撤回」按钮",
            card.detailLines.any { it.contains("会有一个「撤回」") },
        )
        assertFalse(
            "撤票卡不许再说「恢复这张票」（L-57：那是 undoOnly，照念一遍只会白说）",
            card.detailLines.any { it.contains("恢复这张票") },
        )
        assertTrue(card.detailLines.any { it.contains("它和「作废」不是一件事") })

        val done = r.svc.execute(card.token) as AiWriteOutcome.Done
        assertEquals("deleteInvoice:901", r.ds.invoiceCalls.last())
        assertNotNull("撤票要能撤回", done.undoToken)

        val undoCard = ok(r.svc.offerUndo(done.undoToken!!))
        assertTrue(
            "恢复卡片要说清放回来的是哪一张：`{undoCard.detailLines}`",
            undoCard.detailLines.any { it.contains("把刚才撤掉的那张票放回来") },
        )
        assertTrue(undoCard.detailLines.any { it.contains("都和撤掉之前一模一样") })
        assertTrue(r.svc.execute(undoCard.token) is AiWriteOutcome.Done)
        assertEquals("restoreInvoice:901", r.ds.invoiceCalls.last())
    }

    @Test
    fun `发票·撤回改票：把改动过的字段按原值写回去`() = runBlocking<Unit> {
        val r = Rig()
        r.ds.invoiceRows = listOf(invRow(note = "先记一笔"))
        r.ds.snapshots["invoice:901"] = buildJsonObject {
            put("invoice_no", "INV2026090001")
            put("invoice_date", "2026-10-01")
            put("amount", "1130.00")
            put("tax_rate", "13.00")
            put("tax_amount", "130.00")
            put("note", "先记一笔")
        }
        val card = ok(
            r.svc.preview(AiWrites.INVOICES_UPDATE, p("invoice_no" to "INV2026090001", "new_amount" to "2260")),
        )
        val done = r.svc.execute(card.token) as AiWriteOutcome.Done
        assertNotNull("改票要能撤回", done.undoToken)

        val undoCard = ok(r.svc.offerUndo(done.undoToken!!))
        assertTrue(
            "撤回卡要写清撤回的是哪一项：`{undoCard.detailLines}`",
            undoCard.detailLines.any { it.contains("价税合计") },
        )
        assertTrue(r.svc.execute(undoCard.token) is AiWriteOutcome.Done)
        val call = r.ds.invoiceCalls.last()
        assertTrue("撤回要把原值写回去：`{call}`", call.contains("\"amount\":\"1130.00\""))
    }

    @Test
    fun `发票·六条动作的角色门：只有派单员，货主一条都看不到`() {
        val ids = listOf(
            AiWrites.INVOICES_CREATE,
            AiWrites.INVOICES_UPDATE,
            AiWrites.INVOICES_ISSUE,
            AiWrites.INVOICES_VOID,
            AiWrites.INVOICES_DELETE,
            AiWrites.INVOICES_RESTORE,
        )
        val dispatcher = AiActor.byRole(AiRole.DISPATCHER)
        val shipper = AiActor.of(AiRole.SHIPPER, true)
        ids.forEach { id ->
            assertTrue("派单员该有 $id", AiWrites.allows(dispatcher, id))
            assertFalse("货主不该有 $id（后端要 ledger:edit）", AiWrites.allows(shipper, id))
            assertFalse("货主那份清单里不该出现 $id", AiWrites.forModel(shipper).any { it.id == id })
            assertFalse("$id 不在货主动作清单里", AiWrites.SHIPPER_ACTIONS.contains(id))
            assertEquals("六条都归「发票」这一组", AiWrites.G_INVOICE, AiWrites.byId(id)!!.group)
        }
        // 恢复是**撤回专用**：模型那份清单里不该有它（它只能由撤回路径发起）
        assertTrue(AiWrites.byId(AiWrites.INVOICES_RESTORE)!!.undoOnly)
        assertFalse(AiWrites.forModel(dispatcher).any { it.id == AiWrites.INVOICES_RESTORE })
        assertTrue(AiWrites.forModel(dispatcher).any { it.id == AiWrites.INVOICES_CREATE })
    }

    @Test
    fun `发票·撤回口径：登记、开具、作废三条撤不回来，改票与撤票能撤回，恢复自己不能被撤回`() {
        // 三条不可逆的要**当场说清**（不是等用户点了才发现），并且都要给出"那该怎么办"
        val create = AiWrites.undoNoneOf(AiWrites.INVOICES_CREATE)
        assertNotNull(create)
        assertTrue("登记撤不回来要说清：`create`", create!!.contains("撤不回来"))
        assertTrue("还要给出出路：`create`", create.contains("作废这张票") && create.contains("把这张票撤掉"))
        val issue = AiWrites.undoNoneOf(AiWrites.INVOICES_ISSUE)
        assertNotNull(issue)
        assertTrue("开具不能反悔：`issue`", issue!!.contains("开具不能反悔"))
        val void = AiWrites.undoNoneOf(AiWrites.INVOICES_VOID)
        assertNotNull(void)
        assertTrue("作废也撤不回来：`void`", void!!.contains("作废也撤不回来"))

        // 改票 / 撤票都能撤回
        assertTrue(AiWrites.undoCapableOf(AiWrites.INVOICES_UPDATE))
        assertTrue(AiWrites.undoCapableOf(AiWrites.INVOICES_DELETE))
        assertNull("两边都写＝自相矛盾", AiWrites.undoNoneOf(AiWrites.INVOICES_UPDATE))
        assertNull(AiWrites.undoNoneOf(AiWrites.INVOICES_DELETE))
        // 恢复自己走 undoOnly 那条路：不需要"撤不回来"的理由（也不该有撤回入口）
        assertNull(AiWrites.undoNoneOf(AiWrites.INVOICES_RESTORE))
    }

    // ============================================================ 钱相关四条（CHG-0087）

    @Test
    fun `定价·给没定过价的单定价：金额分类都摆上卡，0 元也是合法的一个数`() = runBlocking<Unit> {
        val r = Rig(60_000)
        val card = ok(
            r.svc.preview(
                AiWrites.ORDERS_PRICE_FREIGHT,
                p("order" to "SOTEST2026091100230", "freight" to "80"),
            ),
        )
        assertEquals("给 SOTEST2026091100230 定运费：80 元", card.summary)
        val d = card.detailLines.toString()
        assertTrue(d, card.detailLines.any { it.contains("司机运费：80 元") })
        assertTrue(d, card.detailLines.any { it.contains("运费分类：（现在没有分类）（沿用现在的分类）") })
        assertTrue(d, card.detailLines.any { it.contains("这一步不顺手沉淀价目") })
        assertEquals("80.00", card.payload["freight_fee"]!!.jsonPrimitive.content)
        assertTrue("这一单现在没有分类 ⇒ 发 JsonNull（不是省略这个键）", card.payload["freight_category_id"] is JsonNull)
        // 撤回按钮给不出来：定价的常态就是给"从没定过价的单"定价，写之前没有旧运费可退
        assertTrue(
            card.detailLines.last(),
            card.detailLines.last().startsWith("⚠️ 这一步撤不回来：手动定价没有「撤回」按钮"),
        )
        assertTrue(r.svc.execute(card.token) is AiWriteOutcome.Done)
        assertEquals("priceFreight:61:80.00:null", r.ds.moneyCalls.single())

        // 0 元是合法的一个数（不收运费），卡片上要看得见
        val free = ok(
            r.svc.preview(
                AiWrites.ORDERS_PRICE_FREIGHT,
                p("order" to "SOTEST2026091100230", "freight" to "0"),
            ),
        )
        assertEquals("给 SOTEST2026091100230 定运费：0 元", free.summary)
        assertTrue(free.detailLines.toString(), free.detailLines.any { it.contains("司机运费：0 元（不收运费）") })
    }

    @Test
    fun `定价·没说分类＝沿用现在的分类（不是清空），说「不适用」才是清空`() = runBlocking<Unit> {
        val r = Rig(60_000)
        r.ds.orders = r.ds.orders + AiOrderRef(
            63, "SOTEST2026091100231", "城东水果批发", "PENDING_DISPATCH", "地址2", null, "320.00",
            freightFee = "50.00", freightCategory = "生鲜", freightCategoryId = 94,
        )

        // ① 没说 ⇒ 把**当前分类的编号**原样发回去
        //    （后端是"键不在请求体里 = category_id 是 None = 清空分类"，所以"不说"绝不能翻成"发 null"）
        val kept = ok(
            r.svc.preview(
                AiWrites.ORDERS_PRICE_FREIGHT,
                p("order" to "SOTEST2026091100231", "freight" to "80"),
            ),
        )
        assertTrue(kept.detailLines.toString(), kept.detailLines.any { it.contains("运费分类：生鲜（沿用现在的分类）") })
        r.svc.execute(kept.token)
        assertEquals("priceFreight:63:80.00:94", r.ds.moneyCalls.last())

        // ② 说「不适用」⇒ 清空分类
        val cleared = ok(
            r.svc.preview(
                AiWrites.ORDERS_PRICE_FREIGHT,
                p("order" to "SOTEST2026091100231", "freight" to "70", "category" to "不适用"),
            ),
        )
        assertTrue(cleared.detailLines.toString(), cleared.detailLines.any { it.contains("运费分类：不套分类") })
        r.svc.execute(cleared.token)
        assertEquals("priceFreight:63:70.00:null", r.ds.moneyCalls.last())

        // ③ 说了名字 ⇒ 去名册里对出编号（日杂 = 93）
        val named = ok(
            r.svc.preview(
                AiWrites.ORDERS_PRICE_FREIGHT,
                p("order" to "SOTEST2026091100231", "freight" to "70", "category" to "日杂"),
            ),
        )
        assertTrue(named.detailLines.toString(), named.detailLines.any { it.contains("运费分类：日杂") })
        r.svc.execute(named.token)
        assertEquals("priceFreight:63:70.00:93", r.ds.moneyCalls.last())
    }

    @Test
    fun `定价·已送达的单：定过价的锁死、没定过价的是补定，两种都当场说清`() = runBlocking<Unit> {
        val r = Rig(60_000)
        val delivered = AiOrderRef(
            65, "SOTEST2026091400227", "城东水果批发", "DELIVERED", "地址4", "李强", "200.00",
            freightFee = "50.00",
        )
        r.ds.orders = listOf(delivered)
        val locked = rejected(
            r.svc.preview(AiWrites.ORDERS_PRICE_FREIGHT, p("order" to "SOTEST2026091400227", "freight" to "80")),
        )
        assertTrue(locked.reason, locked.reason.contains("已经定过运费了"))
        assertTrue("要说清去哪儿改：${locked.reason}", locked.reason.contains("司机结算"))
        assertTrue("驳回＝一个字都不许写", r.ds.moneyCalls.isEmpty())

        // 没定过价 ⇒ 允许补定，卡片上要说清"那张还没结算的司机应付明细会跟着改"
        r.ds.orders = listOf(delivered.copy(freightFee = null))
        val backfill = ok(
            r.svc.preview(AiWrites.ORDERS_PRICE_FREIGHT, p("order" to "SOTEST2026091400227", "freight" to "80")),
        )
        assertTrue(
            backfill.detailLines.toString(),
            backfill.detailLines.any { it.contains("已经「已送达」、原先没定过运费 —— 这是补定：") },
        )
        r.svc.execute(backfill.token)
        assertEquals("priceFreight:65:80.00:null", r.ds.moneyCalls.single())
    }

    @Test
    fun `定价·已撤销的单一个字都不许写，卡片也不许弹`() = runBlocking<Unit> {
        val r = Rig(60_000)
        r.ds.orders = listOf(
            AiOrderRef(71, "SOTEST2026090100220", "明辉食品商行", "CANCELLED", "地址9", null, "88.00"),
        )
        val cancelled = rejected(
            r.svc.preview(AiWrites.ORDERS_PRICE_FREIGHT, p("order" to "SOTEST2026090100220", "freight" to "80")),
        )
        assertTrue(cancelled.reason, cancelled.reason.contains("这一单已经撤销了，不用再定价"))
        // 金额非法同样在弹卡前拦下（负数 / 不是数 / 多打了零）
        val negative = rejected(
            r.svc.preview(AiWrites.ORDERS_PRICE_FREIGHT, p("order" to "SOTEST2026090100220", "freight" to "-5")),
        )
        assertTrue(negative.reason, negative.reason.contains("不能是负数"))
        assertTrue("两次驳回都不许写任何东西", r.ds.moneyCalls.isEmpty())
    }

    @Test
    fun `让价·整单抹零：方式数值范围写全，第二次让价是整份替换不是叠加`() = runBlocking<Unit> {
        val r = Rig(60_000)
        val card = ok(
            r.svc.preview(
                AiWrites.ORDERS_DISCOUNT,
                p("order" to "SOTEST2026091100230", "kind" to "抹零", "value" to "3.5", "reason" to "老客户"),
            ),
        )
        assertEquals("给 SOTEST2026091100230 让价：抹零 ¥3.5", card.summary)
        val d = card.detailLines.toString()
        assertTrue(d, card.detailLines.any { it.contains("方式：抹零") })
        assertTrue(d, card.detailLines.any { it.contains("让价：抹零 ¥3.5") })
        assertTrue(d, card.detailLines.any { it.contains("范围：整单（每一行都按比例让）") })
        assertTrue(d, card.detailLines.any { it.contains("这一单现在没有让价。") })
        assertTrue(d, card.detailLines.any { it.contains("每一行的金额由后台重算") })
        assertTrue(d, card.detailLines.any { it.contains("不参与打折") })
        assertEquals("amount", card.payload["discount_kind"]!!.jsonPrimitive.content)
        assertEquals("3.5", card.payload["discount_value"]!!.jsonPrimitive.content)
        assertEquals("全部", card.payload["discount_line_ids"]!!.jsonPrimitive.content)
        assertEquals("老客户", card.payload["discount_reason"]!!.jsonPrimitive.content)
        assertTrue(
            card.detailLines.last(),
            card.detailLines.last().startsWith("⚠️ 这一步撤不回来：让价没有「撤回」按钮"),
        )
        assertTrue(r.svc.execute(card.token) is AiWriteOutcome.Done)
        assertEquals("applyOrderDiscount:61:amount:3.5::老客户", r.ds.moneyCalls.single())

        // 已经有让价 ⇒ 一张单只有一套让价：再让一次是**整份替换**，卡片上必须说清
        r.ds.orders = r.ds.orders.map {
            if (it.id == 61L) {
                it.copy(discountKind = "percent", discountTrace = "减 10% · 张三 · 2026-10-01 · 理由：老客户")
            } else {
                it
            }
        }
        val again = ok(
            r.svc.preview(
                AiWrites.ORDERS_DISCOUNT,
                p("order" to "SOTEST2026091100230", "kind" to "减百分比", "value" to "10"),
            ),
        )
        val t = again.detailLines.toString()
        assertTrue(t, again.detailLines.any { it.contains("已经有一套让价：") })
        assertTrue(t, again.detailLines.any { it.contains("整份替换掉") })
    }

    @Test
    fun `让价·点名的商品：按名字找行、同名多行全都要；找不到就列出这一单的商品名`() = runBlocking<Unit> {
        val r = Rig(60_000)
        r.ds.lineRows = listOf(
            AiOrderLine(901, "红富士苹果", 5, "12.00", "60.00"),
            AiOrderLine(902, "红富士苹果", 3, "12.00", "36.00"),
            AiOrderLine(903, "皇冠梨", 2, "20.00", "40.00"),
        )
        val card = ok(
            r.svc.preview(
                AiWrites.ORDERS_DISCOUNT,
                p(
                    "order" to "SOTEST2026091100230",
                    "kind" to "减百分比",
                    "value" to "10",
                    "lines" to "红富士苹果",
                ),
            ),
        )
        assertTrue(card.detailLines.toString(), card.detailLines.any { it.contains("范围：红富士苹果（共 2 行）") })
        assertEquals("同名多行全都要：901,902", "901,902", card.payload["discount_line_ids"]!!.jsonPrimitive.content)
        r.svc.execute(card.token)
        assertEquals("applyOrderDiscount:61:percent:10:901,902:null", r.ds.moneyCalls.single())

        // 名字对不上 ⇒ 驳回，并把这一单里**有**的商品名列出来（让用户从里面挑）
        val missing = rejected(
            r.svc.preview(
                AiWrites.ORDERS_DISCOUNT,
                p(
                    "order" to "SOTEST2026091100230",
                    "kind" to "减百分比",
                    "value" to "10",
                    "lines" to "香蕉",
                ),
            ),
        )
        assertTrue(missing.reason, missing.reason.contains("这一单里没有叫「香蕉」的商品"))
        assertTrue(missing.reason, missing.reason.contains("红富士苹果") && missing.reason.contains("皇冠梨"))
        assertEquals("驳回不许写", 1, r.ds.moneyCalls.size)
    }

    @Test
    fun `让价·值不对的四种：空、非数、零、百分比到 100，都在弹卡前拦下`() = runBlocking<Unit> {
        val r = Rig(60_000)
        val blank = rejected(
            r.svc.preview(
                AiWrites.ORDERS_DISCOUNT,
                p("order" to "SOTEST2026091100230", "kind" to "抹零", "value" to ""),
            ),
        )
        assertTrue(blank.reason, blank.reason.contains("缺少 value"))
        val notNumber = rejected(
            r.svc.preview(
                AiWrites.ORDERS_DISCOUNT,
                p("order" to "SOTEST2026091100230", "kind" to "抹零", "value" to "三块"),
            ),
        )
        assertTrue(notNumber.reason, notNumber.reason.contains("只能填数字"))
        val zero = rejected(
            r.svc.preview(
                AiWrites.ORDERS_DISCOUNT,
                p("order" to "SOTEST2026091100230", "kind" to "减百分比", "value" to "0"),
            ),
        )
        assertTrue(zero.reason, zero.reason.contains("要大于 0"))
        val full = rejected(
            r.svc.preview(
                AiWrites.ORDERS_DISCOUNT,
                p("order" to "SOTEST2026091100230", "kind" to "减百分比", "value" to "100"),
            ),
        )
        assertTrue(full.reason, full.reason.contains("百分比要小于 100%"))
        assertTrue("四种值不对都不许写", r.ds.moneyCalls.isEmpty())
    }

    @Test
    fun `让价·状态门：已送达的单动不了钱，一个字都不许写`() = runBlocking<Unit> {
        val r = Rig(60_000)
        r.ds.orders = listOf(
            AiOrderRef(65, "SOTEST2026091400227", "城东水果批发", "DELIVERED", "地址4", "李强", "200.00", true),
        )
        val discount = rejected(
            r.svc.preview(
                AiWrites.ORDERS_DISCOUNT,
                p("order" to "SOTEST2026091400227", "kind" to "抹零", "value" to "3.5"),
            ),
        )
        assertTrue(discount.reason, discount.reason.contains("只有待派单 / 派单中 / 已接单的单能让价"))
        assertTrue(discount.reason, discount.reason.contains("动不了钱"))
        val clear = rejected(r.svc.preview(AiWrites.ORDERS_DISCOUNT_CLEAR, p("order" to "SOTEST2026091400227")))
        assertTrue(clear.reason, clear.reason.contains("动不了钱"))
        assertTrue("状态门驳回了就不许写", r.ds.moneyCalls.isEmpty())
    }

    @Test
    fun `取消让价·本来就没有让价：按后台原话拦下；有让价时按快照还原，且这一条能撤回`() = runBlocking<Unit> {
        val r = Rig(60_000)
        val none = rejected(r.svc.preview(AiWrites.ORDERS_DISCOUNT_CLEAR, p("order" to "SOTEST2026091100230")))
        assertTrue("要原样引后台的话：${none.reason}", none.reason.contains("这一单本来就没有折扣。"))
        assertTrue("驳回不许写", r.ds.moneyCalls.isEmpty())

        r.ds.orders = r.ds.orders.map {
            if (it.id == 61L) {
                it.copy(discountKind = "amount", discountTrace = "抹零 ¥3.5 · 张三 · 2026-10-01 · 理由：老客户")
            } else {
                it
            }
        }
        val card = ok(r.svc.preview(AiWrites.ORDERS_DISCOUNT_CLEAR, p("order" to "SOTEST2026091100230")))
        assertEquals("取消 SOTEST2026091100230 的让价", card.summary)
        assertTrue(card.detailLines.toString(), card.detailLines.any { it.contains("现在这套让价：抹零 ¥3.5") })
        assertTrue(
            card.detailLines.toString(),
            card.detailLines.any { it.contains("按当时记下的快照精确还原，不是拿单价 × 数量重算") },
        )
        assertEquals("取消只带主键（撤回按同一把钥匙找回整份让价）", 1, card.payload.size)
        assertTrue(card.detailLines.last(), card.detailLines.last().startsWith("误操作了不要紧"))
        assertTrue(r.svc.execute(card.token) is AiWriteOutcome.Done)
        assertEquals("clearOrderDiscount:61", r.ds.moneyCalls.last())

        // 撤回口径：取消让价能撤回；让价本身撤不回来（第一次让价时旧值是空的）
        assertTrue(AiWrites.undoCapableOf(AiWrites.ORDERS_DISCOUNT_CLEAR))
        assertNull(AiWrites.undoNoneOf(AiWrites.ORDERS_DISCOUNT_CLEAR))
        assertFalse(AiWrites.undoCapableOf(AiWrites.ORDERS_DISCOUNT))
        assertNotNull(AiWrites.undoNoneOf(AiWrites.ORDERS_DISCOUNT))
    }

    @Test
    fun `额度·设一个数：卡片写「原来 → 改成」，payload 就是这两个键`() = runBlocking<Unit> {
        val r = Rig(60_000)
        r.ds.arrearsUnitRows = listOf(AiArrearsUnit(51, "明辉食品商行", "13800000002", "", "5000.00"))
        val card = ok(
            r.svc.preview(
                AiWrites.ARREARS_UNIT_SET_CREDIT_LIMIT,
                p("unit" to "明辉食品商行", "limit" to "8000"),
            ),
        )
        assertEquals("把挂账单位「明辉食品商行」的额度改成 8000 元", card.summary)
        val d = card.detailLines.toString()
        assertTrue(d, card.detailLines.any { it.contains("单位：明辉食品商行（电话 13800000002）") })
        assertTrue(d, card.detailLines.any { it.contains("额度上限：5000 元 → 8000 元") })
        assertTrue(d, card.detailLines.any { it.contains("「不限额」和「额度 0 元」是两件事") })
        assertTrue(d, card.detailLines.any { it.contains("会在后台留一条流水") })
        assertEquals("51", card.payload["unit_id"]!!.jsonPrimitive.content)
        assertEquals("8000.00", card.payload["credit_limit"]!!.jsonPrimitive.content)
        assertTrue(card.detailLines.last(), card.detailLines.last().startsWith("误操作了不要紧"))
        assertTrue(r.svc.execute(card.token) is AiWriteOutcome.Done)
        // 设之前先**单读一行**（名册里没有额度这一列），再写
        assertEquals(listOf("arrearsUnit:51", "setArrearsUnitCreditLimit:51:\"8000.00\""), r.ds.moneyCalls)
    }

    @Test
    fun `额度·说「不限额」＝把额度清空（不是 0）`() = runBlocking<Unit> {
        val r = Rig(60_000)
        r.ds.arrearsUnitRows = listOf(AiArrearsUnit(51, "明辉食品商行", "13800000002", "", "5000.00"))
        val unlimited = ok(
            r.svc.preview(
                AiWrites.ARREARS_UNIT_SET_CREDIT_LIMIT,
                p("unit" to "明辉食品商行", "limit" to "不限额"),
            ),
        )
        assertEquals("把挂账单位「明辉食品商行」的额度改成 不限额（清空额度）", unlimited.summary)
        assertTrue("清空额度只有 JsonNull 发得出去", unlimited.payload["credit_limit"] is JsonNull)
        assertTrue(r.svc.execute(unlimited.token) is AiWriteOutcome.Done)
        assertEquals("setArrearsUnitCreditLimit:51:null", r.ds.moneyCalls.last())

        // 反过来：现在是不限额，写 0 元 —— 这是"一分钱都不许赊"，不是"清空"
        r.ds.arrearsUnitRows = listOf(AiArrearsUnit(51, "明辉食品商行", "13800000002", "", null))
        val zero = ok(
            r.svc.preview(
                AiWrites.ARREARS_UNIT_SET_CREDIT_LIMIT,
                p("unit" to "明辉食品商行", "limit" to "0"),
            ),
        )
        assertEquals("把挂账单位「明辉食品商行」的额度改成 0 元", zero.summary)
        assertTrue(zero.detailLines.toString(), zero.detailLines.any { it.contains("额度上限：不限额 → 0 元") })
        assertTrue(r.svc.execute(zero.token) is AiWriteOutcome.Done)
        assertEquals("setArrearsUnitCreditLimit:51:\"0.00\"", r.ds.moneyCalls.last())
    }

    @Test
    fun `额度·原来就是这个数：如实说不用改，一条都不许写`() = runBlocking<Unit> {
        val r = Rig(60_000)
        r.ds.arrearsUnitRows = listOf(AiArrearsUnit(51, "明辉食品商行", "13800000002", "", "5000.00"))
        val same = rejected(
            r.svc.preview(
                AiWrites.ARREARS_UNIT_SET_CREDIT_LIMIT,
                p("unit" to "明辉食品商行", "limit" to "5000"),
            ),
        )
        assertTrue(same.reason, same.reason.contains("现在的额度就是 5000 元，不用改"))
        assertTrue("驳回＝一个字都不许写", r.ds.moneyCalls.count { !it.startsWith("arrearsUnit:") } == 0)

        // 不限额 vs 不限额 也算"就是它"（两者都 = 清空额度）
        r.ds.arrearsUnitRows = listOf(AiArrearsUnit(51, "明辉食品商行", "13800000002", "", null))
        val still = rejected(
            r.svc.preview(
                AiWrites.ARREARS_UNIT_SET_CREDIT_LIMIT,
                p("unit" to "明辉食品商行", "limit" to "不限额"),
            ),
        )
        assertTrue(still.reason, still.reason.contains("现在的额度就是 不限额"))
        assertTrue(r.ds.moneyCalls.count { !it.startsWith("arrearsUnit:") } == 0)
    }

    @Test
    fun `额度·名册里没有这个单位、额度读不到：两种都不许改去设别的单位`() = runBlocking<Unit> {
        val r = Rig(60_000)
        val ghost = rejected(
            r.svc.preview(
                AiWrites.ARREARS_UNIT_SET_CREDIT_LIMIT,
                p("unit" to "不存在商行", "limit" to "8000"),
            ),
        )
        assertTrue(ghost.reason, ghost.reason.contains("没有匹配"))
        assertTrue("名册里没有 = 一个字都不许写", r.ds.moneyCalls.isEmpty())

        // 名册里有、但单读那一行读不到（比如刚被删掉）⇒ 驳回，绝不改去设别的单位
        val gone = rejected(
            r.svc.preview(
                AiWrites.ARREARS_UNIT_SET_CREDIT_LIMIT,
                p("unit" to "明辉食品商行", "limit" to "8000"),
            ),
        )
        assertTrue(gone.reason, gone.reason.contains("它可能刚被删掉"))
        assertTrue(gone.reason, gone.reason.contains("不要改去设别的单位"))
        assertEquals("只读了一次，一次都没写", listOf("arrearsUnit:51"), r.ds.moneyCalls)
    }

    @Test
    fun `钱相关四条·角色与撤回口径：都是派单员档，两条有按钮两条没有`() = runBlocking<Unit> {
        val dispatcher = AiActor.byRole(AiRole.DISPATCHER)
        val shipper = AiActor.byRole(AiRole.SHIPPER)
        val ids = listOf(
            AiWrites.ORDERS_PRICE_FREIGHT,
            AiWrites.ORDERS_DISCOUNT,
            AiWrites.ORDERS_DISCOUNT_CLEAR,
            AiWrites.ARREARS_UNIT_SET_CREDIT_LIMIT,
        )
        ids.forEach { id ->
            assertTrue("派单员该有 $id", AiWrites.allows(dispatcher, id))
            assertFalse("货主不该有 $id（后端要的是派单/账本那两档权限）", AiWrites.allows(shipper, id))
            assertFalse("$id 不在货主动作清单里", AiWrites.SHIPPER_ACTIONS.contains(id))
        }

        // 撤回：取消让价 / 设额度能撤回；定价 / 让价撤不回来，且理由里要给出"那该怎么办"
        assertTrue(AiWrites.undoCapableOf(AiWrites.ORDERS_DISCOUNT_CLEAR))
        assertTrue(AiWrites.undoCapableOf(AiWrites.ARREARS_UNIT_SET_CREDIT_LIMIT))
        val price = AiWrites.undoNoneOf(AiWrites.ORDERS_PRICE_FREIGHT)
        assertNotNull(price)
        assertTrue(price!!, price.contains("手动定价没有「撤回」按钮"))
        assertTrue("要说清改怎么办：$price", price.contains("把 XXX 的运费改成 YYY"))
        val discount = AiWrites.undoNoneOf(AiWrites.ORDERS_DISCOUNT)
        assertNotNull(discount)
        assertTrue(discount!!, discount.contains("让价没有「撤回」按钮"))
        assertTrue("不让了也有出路：$discount", discount.contains("取消让价"))
        assertFalse(
            "设额度是普通写动作（不是撤回专用）",
            AiWrites.byId(AiWrites.ARREARS_UNIT_SET_CREDIT_LIMIT)!!.undoOnly,
        )
    }


}
