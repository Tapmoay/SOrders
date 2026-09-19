package com.tapmoay.sorders.ai

import com.tapmoay.sorders.core.ApiClient
import com.tapmoay.sorders.data.remote.dto.ExpenseCreateRequest
import com.tapmoay.sorders.data.remote.dto.LedgerCreateRequest
import com.tapmoay.sorders.data.remote.dto.OrderCreateRequest
import com.tapmoay.sorders.data.remote.dto.OrderProductLine
import com.tapmoay.sorders.data.repo.AppRepository
import android.content.Context
import kotlinx.coroutines.CancellationException
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import java.math.BigDecimal
import java.math.RoundingMode

/**
 * 写操作要碰的那几个后端能力。
 *
 * ### 为什么要抽一层接口，而不是直接拿 [AppRepository]
 * 因为这层是**唯一有权限把名字换成编号的地方**，也是"确认卡上写的 = 真正发出去的"
 * 这条不变量的落点。它必须能被单测**完整地跑一遍**（含"查不到""查到多个""连点两次确认"
 * 这些真实场景），而 [AppRepository] 拖着 Retrofit/OkHttp/Android 那一串，
 * 在纯 JVM 单测里拉不起来。抽一个接口，生产实现就是十来行转发（[RepoWriteDataSource]），
 * 换来的是整条 preview→execute 链路可以被证明。
 */
interface AiWriteDataSource {
    // ---- 名册（名字 → 编号；模型只给名字）----
    suspend fun drivers(): List<AiName>
    suspend fun vehicles(): List<AiName>
    suspend fun searchShippers(query: String, limit: Int): List<AiName>
    suspend fun products(): List<AiName>
    suspend fun arrearsUnits(): List<AiName>

    /** 全量用户（按姓名/手机号筛），用于定位"改哪个账号"。 */
    suspend fun users(query: String): List<AiName>
    /**
     * 按**角色**取账号名册（`role` = `driver` / `shipper` / `dispatcher`）。
     *
     * ⚠️ 为什么必须有（2026-09-19 审计）：`users()` 是全角色名册，而
     * 「改司机收费规则」这类动作**只对司机有意义** —— 后端 `PATCH /users/{id}`
     * 的计费分支是 `if user_role_key(u) == DRIVER`，打给货主会**静默什么都不做**
     * （200、changes 空、不写日志），而卡片照样回「已完成」。
     * 名册按角色收窄之后，模型根本挑不到货主 → 当场如实报「系统里没有匹配的司机」。
     */
    suspend fun usersOfRole(query: String, role: String): List<AiName>

    /** 地址/线路、地点、联系人、批发商专属价——都是"要先找到那一条"。 */
    suspend fun addresses(): List<AiName>
    suspend fun locations(): List<AiName>
    suspend fun contacts(): List<AiName>
    suspend fun priceRules(): List<AiName>

    /**
     * 把一段地址文字换成坐标（高德地理编码）。
     *
     * 为什么数据源要暴露"地理编码"这么一件看起来不像数据的事：
     * App 自己的页面里坐标是**用户在地图上点出来的**，AI 没有人点地图，只有一句话。
     * 不补这一步，AI 建的地址/地点/订单就全都**没有坐标**，
     * 司机端的「高德导航」拿到空坐标会退化成"打开高德首页、自己再搜一遍地址"。
     *
     * **只读**：查的是高德，不碰 SOrders 后端（所以 `prepare` 里可以调）。
     * @return 纬度 to 经度；null = 没定位到（**调用方必须容忍**）。
     */
    suspend fun geocode(address: String): Pair<Double, Double>?

    /** 按关键词找订单（单号/货主/司机/地址，后端 `GET /orders?q=`）。 */
    suspend fun findOrders(query: String, limit: Int): List<AiOrderRef>

    // ---- 批量调价（需要"价格现状"，不只是名字）----

    /** 全部**批发商**（is_member=true 的账号）。批量调价留空 shipper 时就是它。 */
    suspend fun members(): List<AiName>

    /** 全部商品的（名字 + 默认价）。 */
    suspend fun productPrices(): List<AiPriceProduct>

    /** 已有的专属价三列，用来算"当前生效价"。 */
    suspend fun priceRuleRows(): List<AiPriceRuleRow>

    /** 批量写价。**一次原子提交**（后端一个事务）。 */
    suspend fun batchPriceRules(
        shipperIds: List<Long>,
        productIds: List<Long>,
        mode: String,
        value: String?,
        adjustPercent: String?,
    )

    // ---- 消息 / 账目 ----
    suspend fun readAllNotifications(): JsonObject
    suspend fun createExpense(req: ExpenseCreateRequest, idempotencyKey: String?)
    suspend fun createLedgerEntry(req: LedgerCreateRequest)

    // ---- 订单 ----
    suspend fun assignOrder(
        orderId: Long,
        driverId: Long,
        note: String?,
        freightFee: String?,
        collectCash: Boolean?,
        pieceAmount: String?,
        commissionRate: String?,
    )
    suspend fun recallOrder(orderId: Long, reason: String)
    suspend fun cancelOrder(orderId: Long)
    suspend fun updateFreight(orderId: Long, freightFee: String?)
    suspend fun payOrder(orderId: Long)
    suspend fun chargeOrder(orderId: Long, arrearsUnitId: Long)
    suspend fun createOrder(req: OrderCreateRequest)

    // ---- 订单（第二批：改单 / 异常 / 拆单 / 批量派单）----
    /** 部分更新订单（后端 PATCH 语义：**没带的键不会被改**）。 */
    suspend fun updateOrder(id: Long, fields: JsonObject)

    /**
     * 标记/解除异常（同一个端点，靠 `is_exception` 区分）。
     * `resolution` 只有解除时才写；`expectedBefore` 是"预计送达时间"。
     */
    suspend fun setOrderException(
        id: Long,
        isException: Boolean,
        reason: String?,
        resolution: String?,
        expectedBefore: String?,
    )

    // ---- 撤回（v3.26）：每个 delete 都有对应的 restore，删除一律是"伪装删除" ----

    /**
     * 把软删的记录恢复回来。**这是「撤回」这条路唯一的落点。**
     *
     * 为什么恢复一律走"后端软删 + restore"，而不是"App 按快照重建一条"：
     * 重建会换编号、会丢图片、会在同号/同名冲突时顶掉另一个人的记录；
     * 而软删恢复是**逐字段照搬**，用户拿回来的就是他删掉的那一条。
     * 用户的原话：系统会做备份，即使删了也可以从那里返回。
     */
    suspend fun restoreAddress(id: Long)
    suspend fun restoreLocation(id: Long)
    suspend fun restoreContact(id: Long)
    suspend fun restoreArrearsUnit(id: Long)
    suspend fun restoreFreightTemplate(id: Long)
    suspend fun restoreDriverRule(id: Long)
    suspend fun restoreProduct(id: Long)
    suspend fun restoreUser(id: Long)

    /** 解除异常（报表中心那个端点：写解决说明 + 解决时间；与页面上的按钮同一条路）。 */
    suspend fun resolveOrderException(id: Long, note: String?)

    /** 拆单。`parts` 是各份**比例**（后端按比例拆数量、余数归首份），不是绝对数量。 */
    suspend fun splitOrder(id: Long, parts: List<Int>)

    /** 批量派单：把多张待派单一次派给同一个司机。 */
    suspend fun batchAssignOrders(orderIds: List<Long>, driverId: Long, note: String?, collectCash: Boolean?)

    // ---- 账本（第二批：改/删流水、客户收款、补进账本）----

    /**
     * 找账本流水（改/删之前先"找到那一条"）。
     *
     * `from`/`to` 是**必须**带的：`GET /ledger/entries` 不传日期时后端返回全部流水
     * （派单员视角下是几万行），拿它做"找那一行"会又慢又容易撞。调用方一律给一个窗口。
     */
    suspend fun ledgerEntries(shipper: String?, from: String, to: String, limit: Int): List<AiLedgerRef>

    /** 客户名册（记收款时要先找到那个客户）。 */
    suspend fun customers(): List<AiName>

    /** 部分更新账本流水（后端 PATCH 语义：没带的键不改）。 */
    suspend fun updateLedgerEntry(id: Long, fields: JsonObject)

    suspend fun deleteLedgerEntry(id: Long)

    /**
     * 记一笔客户收款。
     *
     * `settleMode` 是后端的两档结算模式，**不是可选项而是规则**（见 [AiWrites.LEDGER_CREATE_RECEIPT]）：
     * `itemized`（逐单核销）要求绑订单且金额必须等于所选订单合计；`rolling`（滚动）不绑订单。
     */
    suspend fun createReceipt(
        customerId: Long,
        amount: String,
        method: String,
        receivedAt: String,
        orderIds: List<Long>,
        settleMode: String,
        note: String?,
    )

    /** 把已送达订单补进账本（幂等）。`shipperId` 为 null = 全部货主。 */
    suspend fun syncDeliveredOrders(shipperId: Long?)

    // ---- 订单商品行 / 回收站（第三批）----

    /** 一张订单的商品行（改/删之前先"找到那一行"）。 */
    suspend fun orderLines(orderId: Long): List<AiOrderLine>

    suspend fun addOrderLine(orderId: Long, product: String, quantity: Int, unitPrice: String)

    suspend fun updateOrderLine(lineId: Long, fields: JsonObject)

    suspend fun deleteOrderLine(lineId: Long)

    /** 在**回收站**里按单号找订单（普通查询查不到软删的单）。 */
    suspend fun findDeletedOrders(query: String, limit: Int): List<AiOrderRef>

    suspend fun softDeleteOrder(orderId: Long)

    suspend fun restoreOrder(orderId: Long)

    // ---- 消息（第三批）----

    /** 当前登录账号最近收到的消息（标记已读/改/删之前先"找到那几条"）。 */
    suspend fun myNotifications(limit: Int): List<AiNotificationRef>

    /** 发一条站内消息给某个人（会推送）。 */
    suspend fun sendNotification(recipientId: Long, title: String, content: String, important: Boolean)

    /** 价格变更通知：一次通知一批货主。 */
    suspend fun notifyPriceChange(
        shipperIds: List<Long>,
        productId: Long,
        productName: String,
        priceType: String,
        newPrice: String,
        oldPrice: String?,
    )

    suspend fun markNotificationRead(id: Long)

    suspend fun updateNotification(id: Long, title: String?, content: String?)

    /** 删消息：`ids` 指定一批，或 `all=true` 清空自己的全部消息。 */
    suspend fun deleteNotifications(ids: List<Long>, all: Boolean)

    // ---- 司机账单与结算（第四批：月末收口）----

    /**
     * **工资制**司机（`billing_mode=salary` 且月薪 > 0）。
     *
     * 为什么要单独一个方法：生成月薪单的卡片上必须写清"会给哪几个人建、合计多少"，
     * 而 [drivers] 只有名字——用户核对的就是那一串金额。
     */
    suspend fun salaryDrivers(): List<AiSalaryDriver>

    /** 司机账单（生成/结算之前先看"现在已经有什么"）。三个筛选都可为空。 */
    suspend fun driverBills(driverId: Long?, month: String?, billType: String?): List<AiDriverBill>

    /** 司机结算单（确认/付款/作废之前先"找到那一张"）。 */
    suspend fun driverSettlements(driverId: Long?, month: String?, status: String?): List<AiSettlementRef>

    /** 某月的**应结运费**（按司机聚合的已送达计价单；用来算"这次会补多少"）。 */
    suspend fun monthlyFreight(month: String): List<AiDriverFreight>

    /** 生成司机账单（幂等：已有的不会重复建）。`driverId` 为 null = 该范围内全部司机。 */
    suspend fun generateDriverBills(driverId: Long?, month: String, billType: String)

    /** 生成结算单（草稿）。`amount` 一律传 null——见 [CreateSettlementHandler] 的说明。 */
    suspend fun createSettlement(driverId: Long, settleType: String, month: String, note: String?)

    /** 结算单动作：`confirm` / `pay` / `cancel`。 */
    suspend fun settlementAction(id: Long, action: String, method: String)

    // ---- 商品 / 定价 / 库存 ----
    suspend fun createProduct(name: String, defaultUnitPrice: String, unit: String, stock: Int, lowStockAlert: Int)
    /** 部分更新：只带要改的键（`name` / `default_unit_price` / `unit` / `low_stock_alert` / `is_active`）。 */
    suspend fun updateProduct(id: Long, fields: JsonObject)
    suspend fun deleteProduct(id: Long)
    suspend fun createPriceRule(shipperId: Long, productId: Long, price: String)
    suspend fun updatePriceRule(ruleId: Long, price: String)
    suspend fun deletePriceRule(ruleId: Long)
    suspend fun createMovement(productId: Long, change: Int, note: String)

    // ---- 商品分类名册 + 商品可见范围（v3.43：用户要「AI 建分组、管排序、指定谁能看哪些商品」）----

    /**
     * 商品分类名册（建/改/删/重排之前先按**名字**找到那一格）。
     *
     * `note` 里带"这个分类下有几个在用的商品"：改名会级联改掉那些商品，
     * 所以那个数字必须在卡片上——它是用户判断"这一改会不会波及一片商品"的唯一依据。
     */
    suspend fun productCategories(): List<AiName>

    /** 某个货主/批发商**当前**的可见范围（卡片上写"现在是什么样"用它）。 */
    suspend fun productVisibility(userId: Long): AiVisibility

    suspend fun createProductCategory(fields: JsonObject)
    suspend fun updateProductCategory(id: Long, fields: JsonObject)
    suspend fun deleteProductCategory(id: Long)

    /** 整份顺序一次提交（`ids[0]` 排最前）。后端要求**一个不漏**，少了就 400。 */
    suspend fun reorderProductCategories(ids: List<Long>)

    /** 整份替换某个货主/批发商的可见范围（后端同一个事务里换开关 + 换明细）。 */
    suspend fun setProductVisibility(userId: Long, scope: String, productIds: List<Long>)

    // ---- 基础资料（地址/联系人/地点/挂账单位/运费模板/车辆/客户）----

    /** 运费模板名册（改/删模板时先找到那一条）。 */
    suspend fun freightTemplates(): List<AiName>

    suspend fun createAddress(fields: JsonObject)
    suspend fun updateAddress(id: Long, fields: JsonObject)
    suspend fun deleteAddress(id: Long)
    suspend fun setDefaultAddress(id: Long)
    suspend fun createContact(fields: JsonObject)
    suspend fun updateContact(id: Long, fields: JsonObject)
    suspend fun deleteContact(id: Long)
    suspend fun createLocation(fields: JsonObject)
    suspend fun updateLocation(id: Long, fields: JsonObject)
    suspend fun deleteLocation(id: Long)
    suspend fun createArrearsUnit(fields: JsonObject)
    suspend fun updateArrearsUnit(id: Long, fields: JsonObject)
    suspend fun deleteArrearsUnit(id: Long)
    suspend fun createFreightTemplate(fields: JsonObject)
    suspend fun updateFreightTemplate(id: Long, fields: JsonObject)
    suspend fun deleteFreightTemplate(id: Long)

    // ---- 司机计费规则（v3.36）----

    /** 计费规则名册（改/删规则、给司机挂规则时先按**名字**找到那一条）。 */
    suspend fun driverRules(): List<AiName>
    suspend fun createDriverRule(fields: JsonObject)
    suspend fun updateDriverRule(id: Long, fields: JsonObject)
    suspend fun deleteDriverRule(id: Long)

    /** 把规则挂给司机；`ruleId = null` = 解挂（他退回老口径）。 */
    suspend fun attachDriverRule(driverId: Long, ruleId: Long?)
    suspend fun createVehicle(fields: JsonObject)
    suspend fun updateVehicle(id: Long, fields: JsonObject)
    /** 换/解绑司机；`driverId = null` = 解绑（专用接口，见实现处的说明）。 */
    suspend fun setVehicleDriver(id: Long, driverId: Long?)
    suspend fun createCustomer(fields: JsonObject)

    // ---- 账号 ----
    suspend fun createUser(phone: String, password: String, role: String, fullName: String, isMember: Boolean)
    /**
     * 部分更新账号：只带要改的键。
     * 键名与后端字段一致：`full_name` / `phone` / `password` / `is_active` / `is_member` /
     * `billing_mode` / `vehicle_type` / `salary`。**没带的键不会被改**（后端 PATCH 语义）。
     */
    suspend fun updateUser(id: Long, fields: JsonObject)
    suspend fun swapUserRole(id: Long)
    suspend fun deleteUser(id: Long)

    // ------------------------------------------------------------ 撤回（v3.27）

    /**
     * 读回**这一条记录现在长什么样**——撤回的原料。
     *
     * ### 为什么放在数据源这一层
     * 因为"怎么把一条记录读回来"是数据源的知识：有的资源有 `GET /{id}`（订单、账本流水、
     * 商品…），有的只能拉列表再挑（联系人、地点、挂账单位、运费模板）。
     * 上层（[AiRevert]）只关心"给我一个主键，还我一份**键名与 payload 一致**的值"。
     *
     * ### 为什么要有默认实现（返回 null）
     * 单测的替身不必为每个动作都写一份读回。**null = 读不到 = 这一条撤不回来**，
     * 是 fail-closed 的方向（宁可不给撤回按钮，也不给一个点下去打偏的按钮）。
     * ⚠️ 生产实现 [RepoWriteDataSource] **必须**覆盖它——红线 §20 断言了这一点，
     * 否则"读不到现场"会变成静默的：所有撤回按钮一起消失，而没有任何报错。
     *
     * @param resourceKey 资源标识（见 [AiResources.TABLE]）
     * @param id 主键
     * @return null = 这条读不到（已经删了 / 没权限 / 这个资源没有读回实现）
     */
    suspend fun snapshot(resourceKey: String, id: Long): AiBefore? = null
}

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
) : AiWriteDataSource {

    override suspend fun geocode(address: String): Pair<Double, Double>? =
        AiGeocode.lookup(context, address)

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
                status = d.status,
                address = d.addressDetail.trim(),
                driverLabel = d.driverName?.trim()?.takeIf { it.isNotEmpty() },
                amount = d.orderProducts.fold(BigDecimal.ZERO) { acc, p ->
                    acc.add(p.lineTotal?.toBigDecimalOrNull() ?: BigDecimal.ZERO)
                }.setScale(2, RoundingMode.HALF_UP).toPlainString(),
                collectCash = d.collectCash,
                isException = d.isException,
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

    override suspend fun updateOrder(id: Long, fields: JsonObject) {
        // 只把 handler 明确要改的键搬进 DTO——DTO 的默认值全是 null，等于"不改这一项"。
        repo.updateOrder(
            id,
            com.tapmoay.sorders.data.remote.dto.OrderUpdateRequest(
                deliveryDescription = fields.str("delivery_description"),
                addressDetail = fields.str("address_detail"),
                contactDongjiaPhone = fields.str("contact_dongjia_phone"),
                contactBossPhone = fields.str("contact_boss_phone"),
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
        return repo.ledgerEntries(shipperId = sid, from = from, to = to).take(limit).map { d ->
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
                status = d.status,
                address = d.addressDetail.trim(),
                driverLabel = d.driverName?.trim()?.takeIf { it.isNotEmpty() },
                amount = d.orderProducts.fold(BigDecimal.ZERO) { acc, p ->
                    acc.add(p.lineTotal?.toBigDecimalOrNull() ?: BigDecimal.ZERO)
                }.setScale(2, RoundingMode.HALF_UP).toPlainString(),
                collectCash = d.collectCash,
                isException = d.isException,
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

    override suspend fun contacts(): List<AiName> =
        repo.contacts().map { AiName(it.id, listOf(it.displayName.trim(), it.phone.trim()).filter { s -> s.isNotEmpty() }.joinToString(" ")) }

    override suspend fun priceRules(): List<AiName> = repo.priceRules().map {
        val who = it.shipperName?.trim().orEmpty().ifBlank { "（未命名批发商）" }
        val what = it.productName?.trim().orEmpty().ifBlank { "（未命名商品）" }
        // ⚠️ 价格必须**格式化**再拼进标签：后端把 `Numeric(12,2)` 序列化成字符串时带四位小数，
        //    于是确认卡上出现了「城东水果批发 AI测试果篮 = 11.5000」——金额栏里出现四位小数，
        //    用户会怀疑这个数是不是没对齐（真机实测看到的）。
        //    这里只格式化**展示**用的那一份；批量调价算 before→after 用的原始值不动。
        val price = it.specialUnitPrice.toBigDecimalOrNull()?.let { v -> AiWriteArgs.money(v) }
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
        // ⚠️ cost_price 刻意不传（用 DTO 默认 "0"）：成本是红线，不许进模型上下文，
        // 也就不许由模型来设。要填成本请在「商品管理」页面上填。
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
                // cost_price 同样不传：见 createProduct 的注释
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

    override suspend fun createMovement(productId: Long, change: Int, note: String) {
        repo.createMovement(
            com.tapmoay.sorders.data.remote.dto.InventoryMovementCreateRequest(
                productId = productId,
                change = change,
                note = note,
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
        repo.updateLocation(
            id,
            com.tapmoay.sorders.data.remote.dto.LocationCreateRequest(
                name = fields.str("name") ?: cur.name,
                detailAddress = newText ?: cur.detailAddress,
                remark = fields.str("remark") ?: cur.remark,
                addressLat = lat ?: cur.addressLat,
                addressLng = lng ?: cur.addressLng,
                imageUrls = cur.imageUrls,
            ),
        )
    }

    override suspend fun deleteLocation(id: Long) = repo.deleteLocation(id)

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

    override suspend fun reorderProductCategories(ids: List<Long>) {
        repo.reorderProductCategories(ids)
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
            "contact" -> repo.contacts().firstOrNull { it.id == id }?.let { AiBefore(id, AiRevertRead.contact(it)) }
            "arrears_unit" -> repo.arrearsUnits().firstOrNull { it.id == id }?.let { AiBefore(id, AiRevertRead.arrearsUnit(it)) }
            "freight_template" ->
                repo.freightTemplates().firstOrNull { it.id == id }?.let { AiBefore(id, AiRevertRead.freightTemplate(it)) }
            "driver_rule" ->
                repo.driverBillingRules().firstOrNull { it.id == id }?.let { AiBefore(id, AiRevertRead.driverRule(it)) }
            // 认不出的资源标识 = **撤不回来**（不是"不需要撤"）。
            // 静默返回一份空现场会让撤回卡弹出来却什么都没写回去——那比没有撤回更糟。
            else -> null
        }
    }

    private companion object {
        /** 查账号名册时一次拉多少条。 */
        const val USER_PROBE_LIMIT = 20
    }
}

/**
 * 写操作的**派发器**：把一次申请交给对应的 [AiWriteHandler]，把确认后的执行也交给它。
 *
 * ```
 * 模型调 preview_write(action, params)
 *        ↓  AiTools.previewWrite
 *   AiWriteService.preview(...)   →  handlers[action].prepare(...)
 *        ↓  store.offer(...)            等用户
 *   界面点「确认」→ AiWriteService.execute(token)  →  handlers[action].commit(payload)
 * ```
 *
 * ### 这个类里**故意什么都不干**
 * 它不校验参数、不查名字、不拼摘要——那些全在各自的 handler 里。
 * 它只做三件必须集中做的事：
 * 1. 把 token **取走并删除**（一次性，见 [AiWritePreviewStore.take]）；
 * 2. 兜住所有异常转成 [AiWriteOutcome.Rejected]（**绝不抛**，抛出去会打断 agent 循环）；
 * 3. 给每个请求带上**由 token 派生的幂等键**。
 */
class AiWriteService(
    /**
     * 数据源。**必须是属性**（而不是只当构造参数用）：撤回要在 `execute` 里
     * 读一眼"这条记录写之前长什么样"（[AiRevert.plan]），那发生在成员函数里。
     */
    private val ds: AiWriteDataSource,
    private val store: AiWritePreviewStore,
    /**
     * 当前登录角色。**动作集按它裁剪**（见 [AiWrites.forRole]）。
     *
     * 为什么在这里再查一次而不是只靠界面隐藏：界面藏起来的动作，
     * 模型仍然能从提示词里知道它存在；更糟的是它可以被越权调用。
     * 所以这一层是**真正的门**，界面只是"不给你看"。
     */
    private val roleProvider: () -> AiRole? = { AiRole.DISPATCHER },
    /** 撤回方案的暂存区（App 本地内存）。 */
    private val undos: AiUndoStore = AiUndoStore(),
) {
    /**
     * 动作 id → 处理器。
     *
     * ⚠️ 这里的键必须和 [AiWrites.ALL] 的 id **一一对应**，一个不多一个不少：
     * 少了 → 模型看得到某个动作、调了却报"暂未实现"（最坏的一种 bug：能看见但用不了）；
     * 多了 → 死代码。红线检查会断言两边完全相等，所以那份清单不可能和实现走散。
     *
     * 两条实现路径（见 [AiWriteAction.crud]）：
     * - **手写**：需要"先查单/核对状态/多步解析"的动作（订单那批）；
     * - **声明式**：规格里描述清楚就能跑的动作（主数据那批，26 个）。
     *   它们共用同一套校验和名字→编号，所以不会出现"某个动作忘了写金额上限"。
     */
    private val handlers: Map<String, AiWriteHandler> = buildMap {
        listOf(
            NotificationsReadAllHandler(ds),
            ExpenseWriteHandler(ds, store),
            LedgerEntryWriteHandler(ds, store),
            AssignOrderHandler(ds, store),
            RecallOrderHandler(ds, store),
            CancelOrderHandler(ds, store),
            CreateOrderHandler(ds, store),
            FreightWriteHandler(ds, store),
            PayOrderHandler(ds, store),
            ChargeOrderHandler(ds, store),
            UpdateOrderHandler(ds, store),
            MarkOrderExceptionHandler(ds, store),
            ResolveOrderExceptionHandler(ds, store),
            SplitOrderHandler(ds, store),
            BatchAssignOrderHandler(ds, store),
            UpdateLedgerEntryHandler(ds, store),
            DeleteLedgerEntryHandler(ds, store),
            CreateReceiptHandler(ds, store),
            SyncDeliveredLedgerHandler(ds, store),
            AddOrderLineHandler(ds, store),
            UpdateOrderLineHandler(ds, store),
            DeleteOrderLineHandler(ds, store),
            SoftDeleteOrderHandler(ds, store),
            RestoreOrderHandler(ds, store),
            SendNotificationHandler(ds, store),
            PriceChangeNotifyHandler(ds, store),
            MarkNotificationsReadHandler(ds, store),
            UpdateNotificationHandler(ds, store),
            DeleteNotificationsHandler(ds, store),
            BatchPriceHandler(ds, store),
            ApplyPriceTableHandler(ds, store),
            ApplyProductTableHandler(ds, store),
            GenerateDriverBillsHandler(ds, store),
            CreateSettlementHandler(ds, store),
            ConfirmSettlementHandler(ds, store),
            PaySettlementHandler(ds, store),
            CancelSettlementHandler(ds, store),
            ReorderProductCategoriesHandler(ds, store),
            ProductVisibilityHandler(ds, store),
        ).forEach { put(it.actionId, it) }

        // 声明式：凡是带 crud 规格的动作，一律由通用处理器执行
        AiWrites.ALL.forEach { a ->
            val spec = a.crud ?: return@forEach
            put(a.id, CrudWriteHandler(a, spec, ds, store))
        }
    }

    /** 供红线检查与设置页确认「声明了这么多动作，就真的实现了这么多」。 */
    val implementedActionIds: Set<String> get() = handlers.keys

    // ================================================================= 预览

    /**
     * 申请一次写操作。三种返回见 [AiWriteOutcome]。
     *
     * **绝不抛异常**（[CancellationException] 除外）：失败一律转成 [AiWriteOutcome.Rejected]，
     * 好让工具层变成一句人话还给模型，而不是打断整个 agent 循环。
     */
    suspend fun preview(actionId: String, params: JsonObject): AiWriteOutcome {
        val action = AiWrites.byId(actionId)
            ?: return AiWriteOutcome.Rejected(
                "没有叫「$actionId」的操作。可用操作：${AiWrites.ids.joinToString("、")}。",
            )
        val role = roleProvider()
        if (!AiWrites.allows(role, action.id)) {
            return AiWriteOutcome.Rejected(
                "当前账号是「${role?.cn ?: "未知角色"}」，没有「${action.title}」这个操作的权限。" +
                    "请如实告诉用户他做不了这件事，并告诉他该找派单员、还是去页面上做。" +
                    "**不要换一个操作去凑**。",
            )
        }
        val handler = handlers[action.id]
            ?: return AiWriteOutcome.Rejected("操作「${action.title}」暂未实现。")

        return try {
            handler.prepare(params)
        } catch (e: CancellationException) {
            throw e
        } catch (e: AiWriteArgException) {
            // 候选名单要**结构化**地带出去（不是埋在 reason 那段话里）：
            // 工具返回值里有一个独立的 candidates 数组，模型照着那个问用户更不容易漏。
            AiWriteOutcome.Rejected(e.message ?: "参数不正确。", e.candidates)
        } catch (e: Exception) {
            AiWriteOutcome.Rejected(humanError(e, action.title))
        }
    }

    // ================================================================= 执行

    /**
     * 用户点了聊天里那个「撤回」→ 把撤回方案**变成一张普通的确认卡**。
     *
     * ### 为什么撤回也要弹卡（而不是直接执行）
     * 因为整套设计只有一条写入口：造卡 → 用户点确认 → `execute` → `commit`。
     * 撤回如果能自己写库，就等于开了第二条写入口——那条路上没有角色门、没有风险档、
     * 也没有一次性 token。代价是撤回要两次点击，换来的是"撤回这条路和别的事一样安全"。
     *
     * ### 撤回 token 也是**一次性**的
     * [AiUndoStore.take] 取走即删除：连点两下不会弹两张卡、也不会撤两次。
     * 拿不到（过期 / App 重启过 / 已经用过）时**如实说**，不假装撤了。
     *
     * ### 为什么是 suspend（v3.27）
     * 因为弹卡之前要**再读一次现状**（[AiUndoPlan.probe]）：撤回卡上写的"改回 X"
     * 是几十分钟前的快照，中间这条记录可能已经被改过。再读一次才能告诉用户
     * "撤回会把后来那些改动一起盖掉"——**在他点确认之前**。
     */
    suspend fun offerUndo(undoToken: String): AiWriteOutcome {
        val plan = undos.take(undoToken)
            ?: return AiWriteOutcome.Rejected(
                "这个撤回入口已经失效了（撤回只保留 ${AiUndoStore.DEFAULT_TTL_MS / 60000} 分钟，" +
                    "App 重启后也会清掉）。请把要撤回的那件事告诉我，我重新申请一次。",
            )
        val action = AiWrites.byId(plan.actionId)
            ?: return AiWriteOutcome.Rejected("撤回入口指向了一个不存在的操作（${plan.actionId}）。")
        // 三处门一个都不能少：撤回也是**写**，角色门照走（用户可能在两次点击之间换了账号）。
        if (!AiWrites.allows(roleProvider(), plan.actionId)) {
            return AiWriteOutcome.Rejected("当前账号没有「${action.title}」的权限，这次撤回已取消。")
        }
        // 再读一次现状。读失败（网络/权限）不影响撤回本身，所以只是少一行提示。
        val fresh = try {
            plan.probe?.invoke()
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            null
        }.orEmpty()
        return AiWriteOutcome.NeedConfirm(
            store.offer(
                actionId = plan.actionId,
                title = action.title,
                risk = action.risk,
                summary = plan.summary,
                detailLines = plan.detailLines + fresh,
                payload = plan.payload,
                // ⚠️ 告诉暂存区"这是一张撤回卡"：最后一行要说的是"撤回本身能不能再反悔"，
                //    而不是被撤回那个动作的性质（真机上出现过自相矛盾的卡片）。
                isUndo = true,
            ),
        )
    }

    /**
     * 用户在界面上点了确认 → 真正写。
     *
     * [AiWritePreviewStore.take] 是**取走并删除**，所以同一个 token 调第二次一定拿不到
     * （返回 Rejected），不可能写两遍。这是"连点两下确认"的防线——
     * 靠界面禁用按钮是不够的（连点、状态竞争都能绕过去），必须由数据层保证。
     */
    suspend fun execute(token: String): AiWriteOutcome {
        val p = store.take(token)
            ?: return AiWriteOutcome.Rejected(
                "这次操作已经执行过、或者已经过期（确认卡 ${AiWritePreviewStore.DEFAULT_TTL_MS / 60000} 分钟内有效）。请重新发起。",
            )
        val handler = handlers[p.actionId]
            ?: return AiWriteOutcome.Rejected("操作「${p.title}」没有执行入口。")
        // 预览时查过一次，执行时**再查一次**：角色可能在两次之间变了
        // （用户登出换账号），而这条路是真正写库的那条。
        if (!AiWrites.allows(roleProvider(), p.actionId)) {
            return AiWriteOutcome.Rejected("当前账号没有「${p.title}」的权限，这次操作已取消。")
        }

        return try {
            // ---- 撤回快照：必须在 commit **之前**抓 ----
            // 删除类动作一写下去那条记录就没了，事后再想"它原来长什么样"已经没有机会。
            // 改类动作也一样：这次会改的那几个键的旧值，只能在这一刻读。
            //
            // ⚠️ v3.27 起这里**不再问处理器**（`handler.prepareUndo` 已删除）：
            //    撤回方案的推导只有一处（[AiRevert]），它按资源算——
            //    "改类"= 同一个动作写回旧值、"删除"= 恢复动作、"成对"= 另一个动作。
            //    处理器那一层只要管好"怎么写下去"，不用再管"怎么退回来"。
            //    它只**读**现状、不写任何东西，所以不影响"prepare 不写库"那条红线。
            val undo = try {
                AiRevert.plan(ds, p.actionId, p.payload, p.summary)
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                null
            }
            // 由 token 派生出稳定幂等键：OkHttp 在连接失败时会自动重试 POST，
            // 带上它，后端将来实现幂等时才能识别出"这是同一次操作"而不是两笔。
            // 后端现在忽略它，无害。
            handler.commit(p.payload, "ai-" + token)
            // 批量动作（按表格调价）会在这里补一句**逐行结果**；其余动作返回 null，行为不变。
            // 少了这一句，20 行里失败的 2 行会被"已完成"盖住——那正是最坏的一种反馈。
            val note = handler.commitNote()
            // 卡片上答应过"会出现撤回"，结果没挂上——**必须说**。
            // 不然用户回头去点一个不存在的按钮，或者更糟：以为事情撤掉了。
            // 出现这种情况只有一个原因：写之前读不到那条记录（已被别人删掉/没权限）。
            val broken = AiRevert.canRevert(p.actionId) && undo == null
            AiWriteOutcome.Done(
                p.actionId,
                p.title,
                buildString {
                    append(if (note.isNullOrBlank()) "已完成：${p.summary}" else "已完成：${p.summary}\n$note")
                    if (broken) {
                        // ⚠️ 这句是**给用户看的**（Done 消息直接渲染成 Text），不能写 Markdown 星号
                        append("\n⚠️ 这次没能挂上「撤回」：写之前读不到这条记录现在的样子")
                        append("（可能已经被删掉，或者这个账号看不到它）。要退回去请告诉我，我按编号再试一次。")
                    }
                },
                // 只有**真的写成功了**才挂撤回按钮；写失败时没有东西可撤。
                undoToken = undo?.let { undos.offer(it) },
                undoLabel = undo?.label,
            )
        } catch (e: CancellationException) {
            // 取消时**不**把 token 放回去：用户主动中止的操作不该"恢复"成还能点。
            throw e
        } catch (e: Exception) {
            AiWriteOutcome.Rejected(humanError(e, p.title))
        }
    }

    /**
     * 把后端异常翻成**用户能照着做点什么**的话。
     *
     * 写操作和读操作在这点上不一样：读失败大不了重试，写失败必须让用户知道
     * **到底写没写进去**——所以超时/断网这两句都明确写了"没有写成功"。
     */
    private fun humanError(e: Throwable, what: String): String {
        val ax = ApiClient.toApiException(e)
        return when (ax.code) {
            403 -> "当前登录账号没有权限做「$what」。"
            401 -> "登录已过期，请重新登录后再试。"
            400, 422 -> ax.message ?: "后端不接受这次的参数，请核对后重试。"
            404, 405 -> "该操作依赖的接口不可用（$what）。请把这一步告诉用户，让他在页面上做。"
            -2 -> "连接后端超时，**没有写成功**，请确认后重试。"
            -3 -> "网络连接失败，**没有写成功**，请检查网络后重试。"
            else -> "「$what」没写成：" + (ax.message ?: e.javaClass.simpleName)
        }
    }
}

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
