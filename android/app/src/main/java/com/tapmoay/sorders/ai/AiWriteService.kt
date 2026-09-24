package com.tapmoay.sorders.ai

import com.tapmoay.sorders.core.ApiClient
import com.tapmoay.sorders.data.remote.dto.ExpenseCreateRequest
import com.tapmoay.sorders.data.remote.dto.LedgerCreateRequest
import com.tapmoay.sorders.data.remote.dto.OrderCreateRequest
import com.tapmoay.sorders.data.remote.dto.OrderProductLine
import com.tapmoay.sorders.data.remote.dto.PlaceDto
import com.tapmoay.sorders.data.remote.dto.PlaceUpdateRequest
import com.tapmoay.sorders.data.repo.AppRepository
import com.tapmoay.sorders.ui.dispatcher.centsToMoney
import com.tapmoay.sorders.ui.dispatcher.lineReceivableCents
import com.tapmoay.sorders.ui.shipper.customerNameOf
import com.tapmoay.sorders.ui.shipper.customerPhoneOf
import com.tapmoay.sorders.ui.shipper.settledByLineCents
import com.tapmoay.sorders.util.goodsTotalText
import android.content.Context
import kotlinx.coroutines.CancellationException
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.put
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

    /**
     * 共享地点库（**全库共用**那一张表）的名字名册 —— 「改/撤销/删除共享地点」的目标池。
     *
     * ⚠️ 与 [locations] 不是一回事：那个是**当前登录人自己**的地点库。
     * 两者都能叫「地点」，但一个是私有、一个是所有人共用 —— 卡片上必须写清楚，
     * 否则「删掉这个地点」会被理解成"删我自己的"，而它动的是所有人的选点。
     */
    suspend fun places(): List<AiName>
    suspend fun contacts(): List<AiName>
    suspend fun priceRules(): List<AiName>

    /**
     * 单位换算表（**全库共用**那一份，"1 车 = 8 方"）—— 改/删换算时的目标池。
     *
     * 它的"名字"就是那行等式本身（`1 车 = 8 方`）：换算没有别的自然名字，
     * 而用户嘴里说的正是这行等式（「把一车八方改成十方」）。
     */
    suspend fun unitConversions(): List<AiName>

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

    /**
     * 把**地址类输入**解析成「要写进 payload 的地址文字 + 精确坐标」。
     *
     * ### 为什么在 `geocode` 之外还要有它（2026-09-21）
     * 用户说「送到**我现在的位置**」时，模型手里没有地址 —— 它只有四个字 [AiLocation.HERE]。
     * 而这条路上有两件事必须由 App 做完：
     * 1. **取一次手机定位**（高德 GCJ-02 + 逆地理），拿到真实地址文字；
     * 2. 把**精确坐标**一起写进 payload —— ⛔ **不许**走"文字→再地理编码"
     *    （[geocode]）那一趟：地址文字是逆地理出来的，再正向查一次会**漂点**，
     *    而用户要的是"和手动在地图上选点一样准"。
     *
     * 默认实现＝老行为（把文字交给高德换坐标），所以所有既有替身与调用方都不用改；
     * 唯一多认一个句柄的是 [RepoWriteDataSource]（它手里才有定位提供者）。
     *
     * **只读**：查的是高德与本机定位，不碰 SOrders 后端（所以 `prepare` 里可以调）。
     *
     * @return null = 没解析出来（地址太模糊/没网/超时）。⚠️ 但「当前位置」拿不到时
     *   **不返回 null，而是抛一句能照着改的中文**（见 [AiLocation.requireHere]）——
     *   两种失败给用户的话完全不同：一个是"地址说得更完整些"，一个是"去开定位权限"。
     *
     * 默认实现**没有定位提供者**（单测的替身走这一条）：普通地址照常解析，
     * 而「当前位置」会被当场拒掉 —— 这是 fail-closed 的方向（宁可说"读不到"，也不写四个字进去）。
     */
    suspend fun resolveAddress(text: String): AiPlace? =
        AiLocation.resolveAddress(text, provider = null, geocode = { geocode(it) })

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

    /**
     * 这一单**可退的商品行**（退货动作的核对依据）。
     *
     * ⚠️ 必须问后端/仓库要，不能在卡片里凭 `AiOrderRef.amount` 推算：
     *    "能不能退、还能退几件"取决于 `quantity − damage_quantity − returned_quantity`
     *    三个字段，而 `AiOrderRef` 一个都没有。
     */
    suspend fun returnableLines(orderId: Long): List<AiReturnableLine>

    /** 退货（整单/部分都走这一条）。 */
    suspend fun returnOrder(orderId: Long, items: List<Pair<Long, Int>>, note: String)

    suspend fun updateFreight(orderId: Long, freightFee: String?)
    suspend fun payOrder(orderId: Long)
    suspend fun chargeOrder(orderId: Long, arrearsUnitId: Long)
    suspend fun createOrder(req: OrderCreateRequest)

    /**
     * 补导航信息（2026-09-20）：把**共享地点库里已有**的坐标写到这单上。
     *
     * ⚠️ 坐标由 App 从库里取（[placeById]），**不是**模型给的 —— 这个端点以前被列在
     * `_write_coverage` 的"坐标类：永久不做"里，就是因为"让模型传经纬度"本身是错的。
     */
    suspend fun fillOrderNavigation(orderId: Long, lat: String, lng: String, name: String, detail: String)

    /** 共享地点库里那一条（补导航要它的坐标）。 */
    suspend fun placeById(id: Long): PlaceDto?

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

    // ---- 货主自己那一本账（批发商给下游货主核销，2026-09-20）----
    //
    // ⛔ 与上面那几个 `ledger*` 方法**不是同一本账**：那些读写的是公司账
    // （`/ledger/entries`、`/ledger/receipts`，只有派单员能动），
    // 这几个走 `/shipper-ledger/...`，写的是"我向我的货主收钱"。

    /** 这个账号是不是**批发商货主**（`users.is_member`）——只有他有核销那一段。 */
    suspend fun isMemberShipper(): Boolean

    /**
     * 当前登录角色 key（`dispatcher` / `shipper` / `driver`）；认不出返回 null。
     *
     * ⚠️ 为什么数据源要暴露它（2026-09-20 实测的坑）：「下单」这条路**按角色分叉** ——
     *    派单员代理下单要先查"这单是谁的"（`GET /users?q=`），而**货主是给自己下单**，
     *    后端 `create_order` 对货主是 `target_shipper_id = current.id`，连 `shipper_id`
     *    都不许传。那一步查名册对货主是 **403**（真后端实测：`GET /users` 的角色门是
     *    `USER_MANAGE`＝派单员），于是货主的 AI「帮我下一单」**永远发不出卡** ——
     *    手机上他自己明明能下单。
     */
    suspend fun currentRoleKey(): String?

    /**
     * 当前登录人的编号（认不出返回 null）。
     *
     * ⚠️ 为什么光有 [currentRoleKey] 不够（2026-09-22）：**货主给自己下单**时后端不收 `shipper_id`
     *    （`create_order` 对他就是 `target_shipper_id = current.id`），而专属价挂在**他本人**这个编号下。
     *    只认角色不认人，批发商自己下单时 AI 就只能按商品默认价报价 —— 他谈好的那套专属价被整条跳过。
     *    界面那条同源口径正是这么写的：`OrderCreateViewModel` 的 `subject = shipperId ?: myShipperId`。
     */
    suspend fun currentUserId(): Long?

    /**
     * 我账本上的一张单（按**完整单号**查）：带逐行"还可核销多少"。
     *
     * 为什么按单号而不是"给一串候选让模型挑"：核销是**钱**，挑错单就是记到别人头上，
     * 而这件事要到对账那天才会被发现。单号写全了才是**确定的**那一张。
     */
    suspend fun mySettleOrder(orderNo: String): AiSettleOrder?

    /** 这一单我记过哪些核销（含已撤销的；撤销/恢复都要按它认人）。 */
    suspend fun mySettlements(orderId: Long): List<AiMySettlementRef>

    /** 核销一笔（`lines` 留空 = 整单）。 */
    suspend fun createMySettlement(
        orderId: Long,
        lines: List<Pair<Long, String>>,
        method: String,
        note: String,
    )

    /** 撤销一笔核销（**软删**：记录还在，能恢复）。 */
    suspend fun revokeMySettlement(id: Long)

    /** 把撤掉的那一笔放回来。 */
    suspend fun restoreMySettlement(id: Long)

    // ---------------------------------------------------------------- 退货申请（2026-09-21）
    //
    // 用户原话：「批发商**只是一个申请**，派单员才是实际性的操作」＋
    // 「同时**货主的 AI 可以代替货主进行申请退货**」。
    // ⚠️ 前两个是**货主**的（写申请单/撤回，什么都不动）；
    //    后两个是**派单员的**（驳回 / 真的退货）。角色越权由后端鉴权兜底，清单是第一道门。

    /** **我的**退货申请（`orderId` 非空 = 只看这一张单的）。 */
    suspend fun myReturnRequests(orderId: Long? = null): List<AiReturnRequest>

    /** 货主提交退货申请（⛔ 只写申请单：账本、库存、订单状态一个都不动）。 */
    suspend fun applyReturnRequest(orderId: Long, items: List<Pair<Long, Int>>, note: String)

    /** 货主撤回自己的申请（不是删除：记录留着）。 */
    suspend fun withdrawReturnRequest(id: Long)

    /** 派单员的待办退货申请（`orderId` 非空 = 只看这一张单的）。 */
    suspend fun pendingReturnRequests(orderId: Long? = null): List<AiReturnRequest>

    /** 派单员驳回（理由必填：那是货主唯一能拿到的答复）。 */
    suspend fun rejectReturnRequest(id: Long, reason: String)

    /**
     * 派单员**照这张申请实际退货** —— 库存与账本在这一刻才变。
     *
     * ⛔ 没有数量参数（用户拍板"数量锁死"）：数量只能来自申请单本身。
     */
    suspend fun fulfillReturnRequest(id: Long)

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
    /**
     * 部分更新：只带要改的键（`name` / `default_unit_price` / `unit` / `low_stock_alert` / `is_active`）。
     *
     * ⚠️ `cost_price` 也在里面，但它**只有在用户打开了「允许 AI 查看成本与毛利」时才放行**
     * （见 [AiWriteService] 的 `allowCost`）：成本价一旦进模型上下文就会留在聊天记录里，
     * 所以这是用户的数据外发决定，默认不做。
     */
    suspend fun updateProduct(id: Long, fields: JsonObject)
    suspend fun deleteProduct(id: Long)
    suspend fun createPriceRule(shipperId: Long, productId: Long, price: String)
    suspend fun updatePriceRule(ruleId: Long, price: String)
    suspend fun deletePriceRule(ruleId: Long)

    /**
     * 库存调整。[unitCost] = 这批货的**进货价**（选填，只在入库时有意义）。
     *
     * 填了后端做两件事：记在流水上（毛利率的加权平均进货价从它算）+ 更新商品成本价
     * 并往成本价时间轴里开一段新区间。
     * ⚠️ 与 `updateProduct` 的 `cost_price` 同一条门：**开关关着就不许传**。
     */
    suspend fun createMovement(productId: Long, change: Int, note: String, unitCost: String?)

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

    // ---- 地点分组名册（**按人分区**：读到的、能改的都只是当前登录人自己那一份）----

    /**
     * 我自己的地点分组（建/改/删/重排之前先按**名字**找到那一格，也给"把地点归到某一组"当候选）。
     *
     * `note` 带"这一组下有几个地点"：删/改名会波及它们，那个数字是用户判断影响面的唯一依据。
     */
    suspend fun placeCategories(): List<AiName>

    suspend fun createPlaceCategory(fields: JsonObject)
    suspend fun updatePlaceCategory(id: Long, fields: JsonObject)
    suspend fun deletePlaceCategory(id: Long)
    suspend fun reorderPlaceCategories(ids: List<Long>)

    // ---- 另外三张**配置名册**：开销分类 / 运费分类 / 预订单分类（2026-09-23 补齐能力覆盖）----
    //
    // 这三张原来挂着「不做」的理由（"分类名册是界面配置，用户在分类管理页上调"）。
    // 按用户那条硬规矩「人能操作、AI 就要能操作」收回来：界面上分类管理页能做的四件事
    // （建 / 改名 / 排序 / 删），AI 都要有。
    //
    // ⚠️ 三张的 `note` 都带"这一类下挂着多少东西"：**改名会级联改掉它们**、
    //    **删除会被后端拒绝**（数量就写在报错里）—— 那个数字必须上卡。

    /** 开销分类名册；`note` = 这一类下有几笔开销 + 卡片突出哪一项。 */
    suspend fun expenseCategories(): List<AiName>

    suspend fun createExpenseCategory(fields: JsonObject)
    suspend fun updateExpenseCategory(id: Long, fields: JsonObject)
    suspend fun deleteExpenseCategory(id: Long)
    suspend fun reorderExpenseCategories(ids: List<Long>)

    /** 运费分类名册；`note` = 这一类下挂着几条价目、几份计费规则。 */
    suspend fun freightCategories(): List<AiName>

    suspend fun createFreightCategory(fields: JsonObject)
    suspend fun updateFreightCategory(id: Long, fields: JsonObject)
    suspend fun deleteFreightCategory(id: Long)
    suspend fun reorderFreightCategories(ids: List<Long>)

    /** 预订单分类名册；`note` = 这一类下有几张预设单。 */
    suspend fun orderTemplateCategories(): List<AiName>

    suspend fun createOrderTemplateCategory(fields: JsonObject)
    suspend fun updateOrderTemplateCategory(id: Long, fields: JsonObject)
    suspend fun deleteOrderTemplateCategory(id: Long)
    suspend fun reorderOrderTemplateCategories(ids: List<Long>)

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
    suspend fun updatePlace(id: Long, fields: JsonObject)
    suspend fun deletePlace(id: Long)
    suspend fun demotePlace(id: Long)
    suspend fun publishLocation(id: Long)
    suspend fun restorePlace(id: Long)
    suspend fun createArrearsUnit(fields: JsonObject)
    suspend fun updateArrearsUnit(id: Long, fields: JsonObject)
    suspend fun deleteArrearsUnit(id: Long)

    // ---- 单位换算（2026-09-24：一车 = 8 方）----
    // 判据在后端 `services/unit_conversion.py`：这里的四个方法只负责转发
    // （客户端再写一遍"能不能建"就会与后端走散，而两个数都不报错）。
    suspend fun createUnitConversion(fields: JsonObject)
    suspend fun updateUnitConversion(id: Long, fields: JsonObject)
    suspend fun deleteUnitConversion(id: Long)
    suspend fun restoreUnitConversion(id: Long)

    // ---- 预订单 / 订单模板（2026-09-22）----

    /** 预设单名册（改/删预设单时先按**名字**找到那一张；编号不进模型上下文）。 */
    suspend fun orderTemplates(): List<AiName>
    suspend fun createOrderTemplate(fields: JsonObject)
    suspend fun updateOrderTemplate(id: Long, fields: JsonObject)
    suspend fun deleteOrderTemplate(id: Long)
    suspend fun restoreOrderTemplate(id: Long)
    suspend fun createFreightTemplate(fields: JsonObject)
    suspend fun updateFreightTemplate(id: Long, fields: JsonObject)
    suspend fun deleteFreightTemplate(id: Long)

    // ---- 供应商 / 厂商档案 + 应付款（2026-09-22）----
    //
    // ⚠️ 三个名册的用途各不相同，别互相顶：
    // · [suppliers] = 档案名册（改/删供应商、付款时先认人）；
    // · [supplierPayables] = 应付单名册。`supplierId = null` 是**全部**（声明式那条路
    //   只能给一个参数，所以靠「供应商名 · 事由」拼出来的 label 去匹配），
    //   给了编号就是"这一个供应商名下"（付款那条路，语义更准）；
    // · [supplierPayments] = **已有的付款记录**（撤销付款时先找到那一笔）。

    /** 供应商档案名册（按名字找那一个档案；编号不进模型上下文）。 */
    suspend fun suppliers(): List<AiName>

    /** 应付单名册：`null` = 全部（label 是「供应商名 · 事由」）。 */
    suspend fun supplierPayables(supplierId: Long?): List<AiSupplierPayable>

    /** 付款记录名册（撤销付款用；label 是「供应商 · 事由 · 金额（日期）」）。 */
    suspend fun supplierPayments(): List<AiName>

    suspend fun createSupplier(fields: JsonObject)
    suspend fun updateSupplier(id: Long, fields: JsonObject)
    suspend fun deleteSupplier(id: Long)
    suspend fun restoreSupplier(id: Long)
    suspend fun createSupplierPayable(fields: JsonObject)
    suspend fun updateSupplierPayable(id: Long, fields: JsonObject)
    suspend fun deleteSupplierPayable(id: Long)
    suspend fun restoreSupplierPayable(id: Long)
    /** **付一笔款**（钱真的出去：会写一行资金流水）。 */
    suspend fun paySupplierPayable(fields: JsonObject)

    /** **撤销一笔付款**（软删那一行流水，可恢复）。参数是**资金流水的编号**。 */
    suspend fun cancelSupplierPayment(flowId: Long)
    suspend fun restoreSupplierPayment(flowId: Long)

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
    /**
     * 「当前位置」句柄的定位提供者（[AiLocation]）。
     *
     * null = 没有本机定位能力（单测）：这时用户在地址里写「当前位置」会**当场被拒**并拿到
     * 一句"让他把地址说完整"，而不是写进去一个字面量「当前位置」。
     */
    private val locationProvider: () -> AiLocationProvider? = { null },
) : AiWriteDataSource {

    override suspend fun geocode(address: String): Pair<Double, Double>? =
        AiGeocode.lookup(context, address)

    /**
     * 「当前位置」句柄的**唯一解析点**（模型全程只写那四个字，见 [AiLocation.HERE]）。
     *
     * ⚠️ 放在数据源这一层而不是每个处理器里：地址类动作有三个入口（声明式的 `geocodeFrom`
     * 那一族、下单、改单），各写一遍"认不认句柄"必然会漏掉一个 ——
     * 漏掉的那个会把字面量「当前位置」写进地址库，**不报错**，而司机导航到一个叫"当前位置"的地方。
     */
    override suspend fun resolveAddress(text: String): AiPlace? =
        AiLocation.resolveAddress(text, locationProvider(), geocode = { geocode(it) })

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
                // 报价要绑这个货主（专属价优先）——只有名字查不出专属价，所以编号必须带上
                shipperId = d.shipperId,
                status = d.status,
                address = d.addressDetail.trim(),
                driverLabel = d.driverName?.trim()?.takeIf { it.isNotEmpty() },
                // 商品行合计只有一处实现（`util/Money.kt::goodsTotalText`）——它也是收款页的判据
                amount = d.goodsTotalText(),
                collectCash = d.collectCash,
                isException = d.isException,
                hasNav = !d.addressLat.isNullOrBlank() && !d.addressLng.isNullOrBlank(),
                paid = d.paid,
                settledAmount = d.settledAmount,
                arrearsAmount = d.arrearsAmount,
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

    override suspend fun returnableLines(orderId: Long): List<AiReturnableLine> =
        repo.order(orderId).orderProducts.map { p ->
            AiReturnableLine(
                id = p.id,
                name = p.productNameSnapshot,
                quantity = p.quantity,
                returned = p.returnedQuantity,
                damaged = p.damageQuantity,
                unitPrice = p.unitPrice ?: "0",
            )
        }

    override suspend fun returnOrder(orderId: Long, items: List<Pair<Long, Int>>, note: String) {
        repo.returnOrder(
            orderId,
            items.map { com.tapmoay.sorders.data.remote.dto.OrderReturnItem(it.first, it.second) },
            note,
        )
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

    override suspend fun fillOrderNavigation(
        orderId: Long,
        lat: String,
        lng: String,
        name: String,
        detail: String,
    ) {
        repo.fillOrderNavigation(
            orderId,
            com.tapmoay.sorders.data.remote.dto.OrderNavigationBody(
                addressLat = lat,
                addressLng = lng,
                name = name,
                detailAddress = detail,
            ),
        )
    }

    override suspend fun placeById(id: Long): PlaceDto? = repo.placesAll().firstOrNull { it.id == id }

    override suspend fun updateOrder(id: Long, fields: JsonObject) {
        // 只把 handler 明确要改的键搬进 DTO——DTO 的默认值全是 null，等于"不改这一项"。
        repo.updateOrder(
            id,
            com.tapmoay.sorders.data.remote.dto.OrderUpdateRequest(
                deliveryDescription = fields.str("delivery_description"),
                addressDetail = fields.str("address_detail"),
                contactDongjiaPhone = fields.str("contact_dongjia_phone"),
                contactBossPhone = fields.str("contact_boss_phone"),
                contactDongjiaName = fields.str("contact_dongjia_name"),
                contactBossName = fields.str("contact_boss_name"),
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
        return repo.ledgerEntries(shipperId = sid, from = from, to = to).rows.take(limit).map { d ->
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

    // ---------------- 货主自己那一本账 ----------------

    override suspend fun isMemberShipper(): Boolean = repo.me().isMember

    override suspend fun currentRoleKey(): String? = repo.me().role

    /** 与 [currentRoleKey] 同一个来源（`users/me`），只是要的是编号（报价绑货主时用它）。 */
    override suspend fun currentUserId(): Long? = repo.me().id

    override suspend fun mySettleOrder(orderNo: String): AiSettleOrder? {
        val want = AiWriteArgs.normCode(orderNo)
        if (want.length < MIN_ORDER_NO_LEN) return null
        // 用自己的订单名册找那一张（`GET /orders?q=` 对货主是**只搜自己的单**，
        // 作用域由后端保证），再**精确比单号**——模糊命中一堆时不许挑一个。
        val hit = repo.orders(q = orderNo.trim())
            .firstOrNull { AiWriteArgs.normCode(it.orderNo) == want }
            ?: return null

        val order = repo.order(hit.id)
        val settled = settledByLineCents(repo.mySettlements(orderId = order.id).rows)
        return AiSettleOrder(
            id = order.id,
            orderNo = order.orderNo,
            customer = customerNameOf(order),
            customerPhone = customerPhoneOf(order),
            status = order.status,
            lines = order.orderProducts.map { line ->
                AiSettleLine(
                    id = line.id,
                    name = line.productNameSnapshot.ifBlank { "（未命名商品）" },
                    // 逐行口径只有一处：`lineReceivableCents`（与界面、与后端同一个式子）
                    receivable = BigDecimal(centsToMoney(lineReceivableCents(line))),
                    settled = BigDecimal(centsToMoney(settled[line.id] ?: 0L)),
                )
            },
        )
    }

    override suspend fun mySettlements(orderId: Long): List<AiMySettlementRef> =
        repo.mySettlements(orderId = orderId, includeDeleted = true, limit = MY_SETTLE_PROBE)
            .rows
            .map { s ->
                AiMySettlementRef(
                    id = s.id,
                    orderId = s.orderId,
                    orderNo = s.orderNo ?: "",
                    customer = s.customerName,
                    amount = s.amount,
                    method = s.method,
                    settledAt = s.settledAt.take(16).replace("T", " "),
                    isDeleted = s.isDeleted,
                    products = s.lines.map { it.productName },
                )
            }

    override suspend fun createMySettlement(
        orderId: Long,
        lines: List<Pair<Long, String>>,
        method: String,
        note: String,
    ) {
        repo.createMySettlement(
            com.tapmoay.sorders.data.remote.api.ShipperSettlementCreateRequest(
                orderId = orderId,
                lines = lines.map {
                    com.tapmoay.sorders.data.remote.api.ShipperSettlementLineRequest(
                        orderProductId = it.first,
                        amount = it.second,
                    )
                },
                method = method,
                note = note,
                // 这笔核销是 AI 确认卡提交的：审计与列表上会如实标出来
                source = "ai",
            ),
        )
    }

    override suspend fun revokeMySettlement(id: Long) = repo.revokeMySettlement(id)

    override suspend fun restoreMySettlement(id: Long) {
        repo.restoreMySettlement(id)
    }

    // ---------------------------------------------------------------- 退货申请（2026-09-21）

    /**
     * DTO → 模型看得见的形状。
     *
     * ⚠️ `id` 留着（撤回/办理都要按它认人），但**不进候选名单文案** ——
     * [AiReturnRequest.label] 里只有单号、商品名和中文状态（模型第一条硬规矩：不给编号）。
     */
    private fun toAiReturnRequest(dto: com.tapmoay.sorders.data.remote.dto.ReturnRequestDto) =
        AiReturnRequest(
            id = dto.id,
            orderId = dto.orderId,
            orderNo = dto.orderNo,
            status = dto.status,
            statusLabel = dto.statusLabel,
            shipperName = dto.shipperName,
            note = dto.note,
            rejectReason = dto.rejectReason,
            handledByName = dto.handledByName,
            lines = dto.lines.map { it.productName to it.quantity },
        )

    override suspend fun myReturnRequests(orderId: Long?): List<AiReturnRequest> =
        repo.myReturnRequests(orderId = orderId).items.map { toAiReturnRequest(it) }

    override suspend fun applyReturnRequest(orderId: Long, items: List<Pair<Long, Int>>, note: String) {
        repo.applyReturnRequest(
            orderId = orderId,
            items = items.map {
                com.tapmoay.sorders.data.remote.dto.OrderReturnItem(
                    orderProductId = it.first,
                    quantity = it.second,
                )
            },
            note = note,
        )
    }

    override suspend fun withdrawReturnRequest(id: Long) {
        repo.withdrawReturnRequest(id)
    }

    override suspend fun pendingReturnRequests(orderId: Long?): List<AiReturnRequest> =
        repo.returnRequestTodo(status = "pending", orderId = orderId).items.map { toAiReturnRequest(it) }

    override suspend fun rejectReturnRequest(id: Long, reason: String) {
        repo.rejectReturnRequest(id, reason)
    }

    override suspend fun fulfillReturnRequest(id: Long) {
        repo.fulfillReturnRequest(id)
    }

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
                // 报价要绑这个货主（专属价优先）——只有名字查不出专属价，所以编号必须带上
                shipperId = d.shipperId,
                status = d.status,
                address = d.addressDetail.trim(),
                driverLabel = d.driverName?.trim()?.takeIf { it.isNotEmpty() },
                // 商品行合计只有一处实现（`util/Money.kt::goodsTotalText`）——它也是收款页的判据
                amount = d.goodsTotalText(),
                collectCash = d.collectCash,
                isException = d.isException,
                paid = d.paid,
                settledAmount = d.settledAmount,
                arrearsAmount = d.arrearsAmount,
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

    override suspend fun places(): List<AiName> = repo.placesAll().map {
        AiName(
            it.id,
            listOf(it.name.trim(), it.detailAddress.trim()).filter { s -> s.isNotEmpty() }.joinToString(" "),
        )
    }

    override suspend fun contacts(): List<AiName> =
        repo.contacts().map { AiName(it.id, listOf(it.displayName.trim(), it.phone.trim()).filter { s -> s.isNotEmpty() }.joinToString(" ")) }

    override suspend fun priceRules(): List<AiName> = repo.priceRules().map {
        val who = it.shipperName?.trim().orEmpty().ifBlank { "（未命名批发商）" }
        val what = it.productName?.trim().orEmpty().ifBlank { "（未命名商品）" }
        // ⚠️ 价格必须**格式化**再拼进标签：后端把 `Numeric(12,2)` 序列化成字符串时带四位小数，
        //    于是确认卡上出现了「城东水果批发 AI测试果篮 = 11.5000」——金额栏里出现四位小数，
        //    用户会怀疑这个数是不是没对齐（真机实测看到的）。
        //    这里只格式化**展示**用的那一份；批量调价算 before→after 用的原始值不动。
        val price = it.specialUnitPrice.toBigDecimalOrNull()?.let { v -> AiWriteArgs.moneyText(v) }
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
        // ⚠️ **新建**商品时不带 cost_price（用 DTO 默认 "0"）：新商品通常还没进过货，
        //    成本价是"还不知道"的状态，硬要模型填一个只会逼它编。
        //    成本价之后有两个**真实**入口：改商品（`products.update` 的 cost_price 字段）
        //    与进货入库（`inventory.adjust` 的 unit_cost），两者都要过 `allowCost` 那道门。
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
                // ⚠️ cost_price **不在这里判**：门开在 `AiWriteService`（所有动作的唯一入口）。
                //    分散到各个数据源方法里迟早漏一个，而漏掉的后果是"成本价被写进去了"。
                costPrice = fields.str("cost_price"),
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

    override suspend fun createMovement(productId: Long, change: Int, note: String, unitCost: String?) {
        repo.createMovement(
            com.tapmoay.sorders.data.remote.dto.InventoryMovementCreateRequest(
                productId = productId,
                change = change,
                note = note,
                // 同一个门：进货价也是成本，见上面那段注释
                unitCost = unitCost,
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
                // 地点绑定的联系人（2026-09-24）：下单选中这个地点时会自动带出收货人两栏
                contactName = fields.str("contact_name").orEmpty(),
                contactPhone = fields.str("contact_phone").orEmpty(),
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
        // 「把这个地点归到那一类」：**严格对名册**。
        // ⛔ 不许让它顺手新建：用户说的"那一类"如果库里没有，多半是名字记错了（错别字会**静默**
        //    多出一格分组），所以这里对不上就拒绝、并把现有分组名列出来。
        val wantCat = fields.str("category")?.trim()?.takeIf { it.isNotEmpty() }
        var cat = cur.category
        if (wantCat != null && wantCat != cur.category) {
            val pool = repo.placeCategories()
            val hit = pool.firstOrNull { it.name == wantCat }
                ?: throw AiWriteArgException(
                    "你的地点分组里没有「$wantCat」。现有分组：" +
                        (if (pool.isEmpty()) "（还没有分组，先用「新建地点分组」建一个）"
                        else pool.joinToString("、") { it.name }) +
                        "。要么用上面某个名字，要么先新建这个分组。"
                )
            cat = hit.name
        }
        repo.updateLocation(
            id,
            com.tapmoay.sorders.data.remote.dto.LocationCreateRequest(
                name = fields.str("name") ?: cur.name,
                detailAddress = newText ?: cur.detailAddress,
                remark = fields.str("remark") ?: cur.remark,
                addressLat = lat ?: cur.addressLat,
                addressLng = lng ?: cur.addressLng,
                // ⛔ 分类与仓库标记必须**回填原值**（没点名分组时就是原值）：
                //    `LocationCreateRequest` 走的是"整体替换"语义，不回填就等于
                //    "AI 改个地点名把它从分组里踢出去 / 顺手取消仓库标记"——
                //    而界面上只会显示「已改地点」，用户看不出分组没了。
                category = cat,
                isWarehouse = cur.isWarehouse,
                // ⛔ 地点绑定的联系人同样要**回填原值**（理由与上面分类、仓库标记一模一样）：
                //    AI 只说了"改个地点名"，不回填就等于把收货人绑定**静默清掉** ——
                //    而界面上只会显示「已改地点」。
                contactName = fields.str("contact_name") ?: cur.contactName,
                contactPhone = fields.str("contact_phone") ?: cur.contactPhone,
                imageUrls = cur.imageUrls,
            ),
        )
    }

    override suspend fun deleteLocation(id: Long) = repo.deleteLocation(id)

    // ---- 共享地点（全库共用那张表）：改 / 删 / 撤销 / 设为共享 ----
    //
    // 四个都是**转发**，没有一处自己算业务：
    // 合并判据（1 米/同名 30 米）与"名字地址不能都空"都在后端 `services/place_service.py`，
    // 客户端的任何一处再写一遍就会与它走散（而两边都不报错）。

    override suspend fun updatePlace(id: Long, fields: JsonObject) {
        require(fields.isNotEmpty()) { "updatePlace 的部分更新体是空的（规格 key 写错了）" }
        repo.updatePlace(
            id,
            PlaceUpdateRequest(
                name = fields.str("name"),
                detailAddress = fields.str("detail_address"),
            ),
        )
    }

    override suspend fun deletePlace(id: Long) = repo.deletePlace(id)

    override suspend fun restorePlace(id: Long) {
        repo.restorePlace(id)
    }

    override suspend fun demotePlace(id: Long) {
        repo.demotePlace(id)
    }

    override suspend fun publishLocation(id: Long) {
        repo.shareLocation(id)
    }

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

    // ---- 单位换算（2026-09-24：一车 = 8 方）----
    //
    // ⚠️ 换算率按**字符串**进出（后端是 `Numeric(14,4)`）：走 Double 会让 `0.1` 变成
    //    `0.1000000000000000055…`，而它是印在订单上的数（与金额同一个理由）。

    override suspend fun unitConversions(): List<AiName> =
        // "名字"就是那行等式本身：换算没有别的自然名字，用户嘴里说的也正是它
        // （「把一车八方改成十方」）。被删掉的换成 `deletedOnly` 那一份（撤回时要读现场）。
        repo.unitConversions().map { AiName(it.id, "1 ${it.fromUnit} = ${it.factor} ${it.toUnit}") }

    override suspend fun createUnitConversion(fields: JsonObject) {
        repo.createUnitConversion(
            com.tapmoay.sorders.data.remote.api.UnitConversionCreateRequest(
                fromUnit = fields.req("from_unit"),
                toUnit = fields.req("to_unit"),
                factor = fields.req("factor"),
                remark = fields.str("remark").orEmpty(),
            ),
        )
    }

    override suspend fun updateUnitConversion(id: Long, fields: JsonObject) {
        require(fields.isNotEmpty()) { "updateUnitConversion 的部分更新体是空的（规格 key 写错了）" }
        repo.updateUnitConversion(
            id,
            com.tapmoay.sorders.data.remote.api.UnitConversionUpdateRequest(
                fromUnit = fields.str("from_unit"),
                toUnit = fields.str("to_unit"),
                factor = fields.str("factor"),
                remark = fields.str("remark"),
            ),
        )
    }

    override suspend fun deleteUnitConversion(id: Long) = repo.deleteUnitConversion(id)

    // ---- 预订单 / 订单模板（2026-09-22）----

    override suspend fun orderTemplates(): List<AiName> =
        repo.orderTemplates().map { AiName(it.id, it.name) }

    override suspend fun createOrderTemplate(fields: JsonObject) {
        repo.createOrderTemplate(
            com.tapmoay.sorders.data.remote.dto.OrderTemplateCreateRequest(
                name = fields.req("name"),
                shipperId = fields.str("shipper_id")?.toLongOrNull(),
                address = fields.str("address").orEmpty(),
                receiverName = fields.str("receiver_name").orEmpty(),
                receiverPhone = fields.str("receiver_phone").orEmpty(),
                freightFee = fields.str("freight_fee"),
                remark = fields.str("remark").orEmpty(),
                lines = fields.orderTemplateLines(),
            ),
        )
    }

    override suspend fun updateOrderTemplate(id: Long, fields: JsonObject) {
        require(fields.isNotEmpty()) { "updateOrderTemplate 的部分更新体是空的（规格 key 写错了）" }
        repo.updateOrderTemplate(
            id,
            com.tapmoay.sorders.data.remote.dto.OrderTemplateUpdateRequest(
                name = fields.str("name"),
                shipperId = fields.str("shipper_id")?.toLongOrNull(),
                address = fields.str("address"),
                receiverName = fields.str("receiver_name"),
                receiverPhone = fields.str("receiver_phone"),
                // ⚠️ 空串（＝"不预设"）**不要**当成一个值发出去：后端把空串也当"不预设"，
                //    但发出去会覆盖掉原有的预设运费 —— 模型没提这一项时就不该动它。
                freightFee = fields.str("freight_fee")?.takeIf { it.isNotBlank() },
                remark = fields.str("remark"),
                // 只有 payload 里真给了 lines 才换（给了就整份换掉）
                lines = if (fields.containsKey("lines")) fields.orderTemplateLines() else null,
                // ⚠️ **非空默认值字段必须显式回填**（判据 `_check_ai_dto_defaults.py`）：
                //    漏掉它，Kotlin 的默认值会被序列化成"要清空货主"发出去 ——
                //    而模型只是想改个备注。默认 false = 不动货主。
                clearShipper = false,
            ),
        )
    }

    override suspend fun deleteOrderTemplate(id: Long) = repo.deleteOrderTemplate(id)

    override suspend fun restoreOrderTemplate(id: Long) {
        // 返回值（恢复后的那条）这一层用不上：撤回走的是"同一条写路径，把旧值塞回去"
        repo.restoreOrderTemplate(id)
    }

    /**
     * payload 里的 `lines` → DTO 行。
     *
     * ⚠️ 这里的键名是**处理器拼好的 payload 键**（`product_id`/`qty`），不是模型参数名
     * （模型传的是 `product`/`quantity`，那一步在 `OrderTemplateWriteHandler` 里做完了）。
     * 两套名字混用的后果是"卡片上写着 6 样货、请求里一行都没有"。
     */
    private fun JsonObject.orderTemplateLines(): List<com.tapmoay.sorders.data.remote.dto.OrderTemplateLineDto> =
        (this["lines"] as? kotlinx.serialization.json.JsonArray)?.mapNotNull { el ->
            val o = el as? JsonObject ?: return@mapNotNull null
            com.tapmoay.sorders.data.remote.dto.OrderTemplateLineDto(
                productId = o.str("product_id")?.toLongOrNull(),
                name = o.str("name").orEmpty(),
                unit = o.str("unit").orEmpty(),
                qty = o.str("qty")?.toIntOrNull() ?: 1,
            )
        } ?: emptyList()

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

    // ---- 供应商 / 厂商档案 + 应付款（2026-09-22）----

    override suspend fun suppliers(): List<AiName> = repo.suppliers().map { AiName(it.id, it.name) }

    /**
     * 应付单名册。
     *
     * `supplierId = null` 时 label 拼成 **「供应商名 · 事由」**：声明式那条路（改/删应付单）
     * 只能给一个参数，而事由是用户自己写的（「9 月货款」），所以必须把供应商名一起拼进去
     * 才认得出用户说的是哪一张。给了编号时（付款那条路）就只用事由 ——
     * 那时候"哪一个供应商"已经由供应商参数确定了。
     *
     * `note` 带上"还差多少"：用户核对时真正要看的就是这个数。
     */
    override suspend fun supplierPayables(supplierId: Long?): List<AiSupplierPayable> {
        val rows = if (supplierId == null) repo.allSupplierPayables() else repo.supplierPayables(supplierId)
        return rows.map {
            AiSupplierPayable(
                id = it.id,
                supplierId = it.supplierId,
                title = if (supplierId == null && it.supplierName.isNotBlank()) {
                    "${it.supplierName} · ${it.title}"
                } else {
                    it.title
                },
                amount = it.amount,
                paid = it.paid,
                unpaid = it.unpaid,
                paymentCount = it.paymentCount,
            )
        }
    }

    /**
     * 付款记录名册：label 拼「供应商 · 事由 · 金额（日期）」。
     *
     * 付款记录**没有天然名字** —— 用户嘴里的说法就是这几项，所以 label 就是那几项。
     * 拼成一条之后 `AiWriteArgs.strict` 的"包含"匹配才认得出「永盛那笔 800」。
     */
    override suspend fun supplierPayments(): List<AiName> = repo.supplierPayments().map {
        AiName(
            id = it.id,
            label = listOf(it.supplierName, it.payableTitle, "${it.amount} 元")
                .filter { s -> s.isNotBlank() }.joinToString(" · ") +
                if (it.payDate.isNotBlank()) "（${it.payDate}）" else "",
            note = if (it.remark.isNotBlank()) "备注：${it.remark}" else null,
        )
    }

    override suspend fun createSupplier(fields: JsonObject) {
        repo.createSupplier(
            com.tapmoay.sorders.data.remote.dto.SupplierCreateRequest(
                name = fields.req("name"),
                contactName = fields.str("contact_name").orEmpty(),
                phone = fields.str("phone").orEmpty(),
                address = fields.str("address").orEmpty(),
                remark = fields.str("remark").orEmpty(),
            ),
        )
    }

    override suspend fun updateSupplier(id: Long, fields: JsonObject) {
        require(fields.isNotEmpty()) { "updateSupplier 的部分更新体是空的（规格 key 写错了）" }
        repo.updateSupplier(
            id,
            com.tapmoay.sorders.data.remote.dto.SupplierUpdateRequest(
                name = fields.str("name"),
                contactName = fields.str("contact_name"),
                phone = fields.str("phone"),
                address = fields.str("address"),
                remark = fields.str("remark"),
            ),
        )
    }

    override suspend fun deleteSupplier(id: Long) = repo.deleteSupplier(id)

    override suspend fun restoreSupplier(id: Long) {
        // 返回值（恢复后的那条）这一层用不上：撤回走的是"同一条写路径，把旧值塞回去"
        repo.restoreSupplier(id)
    }

    override suspend fun createSupplierPayable(fields: JsonObject) {
        repo.createSupplierPayable(
            fields.reqLong("supplier_id"),
            com.tapmoay.sorders.data.remote.dto.SupplierPayableCreateRequest(
                supplierId = fields.reqLong("supplier_id"),
                title = fields.req("title"),
                category = fields.str("category") ?: "货款",
                amount = fields.req("amount"),
                docDate = fields.str("doc_date") ?: java.time.LocalDate.now().toString(),
                remark = fields.str("remark").orEmpty(),
            ),
        )
    }

    override suspend fun updateSupplierPayable(id: Long, fields: JsonObject) {
        require(fields.isNotEmpty()) { "updateSupplierPayable 的部分更新体是空的（规格 key 写错了）" }
        repo.updateSupplierPayable(
            id,
            com.tapmoay.sorders.data.remote.dto.SupplierPayableUpdateRequest(
                title = fields.str("title"),
                category = fields.str("category"),
                amount = fields.str("amount"),
                docDate = fields.str("doc_date"),
                remark = fields.str("remark"),
            ),
        )
    }

    override suspend fun deleteSupplierPayable(id: Long) = repo.deleteSupplierPayable(id)

    override suspend fun restoreSupplierPayable(id: Long) {
        repo.restoreSupplierPayable(id)
    }

    /**
     * 付一笔款。
     *
     * ⚠️ `channel` 与 `pay_date` **必须回填**：`SupplierPaymentCreateRequest` 的默认值
     * （`cash` / 今天是 Kotlin 侧默认）在 `explicitNulls=false` 的序列化下会被**发出去**
     * —— 那样"模型没提付款方式"就会静默变成"现金"。这里的两项都是
     * `SupplierPaymentWriteHandler` **显式算好**放进 payload 的（缺一个就是漏了一处）。
     */
    override suspend fun paySupplierPayable(fields: JsonObject) {
        repo.paySupplierPayable(
            fields.reqLong("payable_id"),
            com.tapmoay.sorders.data.remote.dto.SupplierPaymentCreateRequest(
                amount = fields.req("amount"),
                payDate = fields.req("pay_date"),
                channel = fields.str("channel") ?: "cash",
                remark = fields.str("remark").orEmpty(),
            ),
        )
    }

    override suspend fun cancelSupplierPayment(flowId: Long) = repo.cancelSupplierPayment(flowId)

    override suspend fun restoreSupplierPayment(flowId: Long) {
        repo.restoreSupplierPayment(flowId)
    }

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

    /** 我自己的地点分组（按人分区：`repo.placeCategories()` 读的就是当前登录人那一份）。 */
    override suspend fun placeCategories(): List<AiName> = repo.placeCategories().map {
        AiName(it.id, it.name, note = if (it.locationCount > 0) "${it.locationCount} 个地点" else null)
    }

    override suspend fun createPlaceCategory(fields: JsonObject) {
        val created = repo.createPlaceCategory(
            name = fields.req("name"),
            // 先按"排在最后"建出来；有位置要求时再用 reorder 挪过去（与商品分类同一套理由）。
            sortOrder = null,
        )
        fields.str("sort_order")?.toIntOrNull()?.let { movePlaceCategoryTo(created.id, it) }
    }

    /**
     * 把某个分组挪到「第 N 位」（**从 1 数**）。走 reorder 而不是写绝对值 ——
     * 理由与商品分类那份一字不差（绝对值会与现有第 1 位撞车、按 id 排后落到别处）。
     */
    private suspend fun movePlaceCategoryTo(id: Long, position1Based: Int) {
        val ids = repo.placeCategories().sortedBy { it.sortOrder }.map { it.id }.toMutableList()
        ids.remove(id)
        val idx = (position1Based - 1).coerceIn(0, ids.size)
        ids.add(idx, id)
        repo.reorderPlaceCategories(ids)
    }

    override suspend fun updatePlaceCategory(id: Long, fields: JsonObject) {
        require(fields.isNotEmpty()) { "updatePlaceCategory 的部分更新体是空的（规格 key 写错了）" }
        repo.updatePlaceCategory(id, name = fields.str("name"), sortOrder = null)
        fields.str("sort_order")?.toIntOrNull()?.let { movePlaceCategoryTo(id, it) }
    }

    override suspend fun deletePlaceCategory(id: Long) {
        repo.deletePlaceCategory(id)
    }

    override suspend fun reorderPlaceCategories(ids: List<Long>) {
        repo.reorderPlaceCategories(ids)
    }

    override suspend fun reorderProductCategories(ids: List<Long>) {
        repo.reorderProductCategories(ids)
    }

    // ---- 另外三张配置名册（开销 / 运费 / 预订单分类，2026-09-23 补齐 AI 能力覆盖）----
    //
    // ⚠️ 三张的 `note` 都带"这一类下挂着多少东西"：**改名会级联改掉它们**、
    //    **删除会被后端拒绝**（数量就写在报错里）—— 那是用户判断影响面的唯一依据。
    // ⚠️ 位置（第 N 位）与商品/地点分组同一条规矩：**先按"排在最后"建出来，再走 reorder 挪过去**。
    //    直接写 `sort_order = N-1` 是绝对值：后端不会把别人往后挤，于是"排第 1 位"会与
    //    现有第 1 位撞值、按 id 排序后落到别处，而卡片上明确承诺了「1 = 最前面」。

    override suspend fun expenseCategories(): List<AiName> = repo.expenseCategories().map {
        AiName(
            it.id, it.name,
            note = buildString {
                append(if (it.expenseCount > 0) "${it.expenseCount} 笔开销" else "还没有开销")
                append("，卡片突出显示：").append(linkKindCn(it.linkKind))
            },
        )
    }

    override suspend fun freightCategories(): List<AiName> = repo.freightCategories().map {
        AiName(
            it.id, it.name,
            note = if (it.templateCount > 0 || it.ruleCount > 0) {
                "${it.templateCount} 条价目、${it.ruleCount} 份计费规则"
            } else {
                "这一类下还没有价目/规则"
            },
        )
    }

    override suspend fun orderTemplateCategories(): List<AiName> =
        repo.orderTemplateCategories().map {
            AiName(it.id, it.name, note = if (it.templateCount > 0) "${it.templateCount} 张预设单" else null)
        }

    override suspend fun createExpenseCategory(fields: JsonObject) {
        val created = repo.createExpenseCategory(
            name = fields.req("name"),
            // ⚠️ 不传 = 后端默认 "none"（不突出任何一项）；这个仓储方法**没有** sortOrder，
            //    位置要走 reorder 挪（与商品/地点分组同一条规矩，见 moveExpenseCategoryTo）。
            linkKind = fields.str("link_kind") ?: "none",
        )
        fields.str("sort_order")?.toIntOrNull()?.let { moveExpenseCategoryTo(created.id, it) }
    }

    private suspend fun moveExpenseCategoryTo(id: Long, position1Based: Int) {
        val ids = repo.expenseCategories().sortedBy { it.sortOrder }.map { it.id }.toMutableList()
        ids.remove(id)
        ids.add((position1Based - 1).coerceIn(0, ids.size), id)
        repo.reorderExpenseCategories(ids)
    }

    override suspend fun updateExpenseCategory(id: Long, fields: JsonObject) {
        require(fields.isNotEmpty()) { "updateExpenseCategory 的部分更新体是空的（规格 key 写错了）" }
        repo.updateExpenseCategory(
            id,
            name = fields.str("name"),
            linkKind = fields.str("link_kind"),
        )
        fields.str("sort_order")?.toIntOrNull()?.let { moveExpenseCategoryTo(id, it) }
    }

    override suspend fun deleteExpenseCategory(id: Long) {
        repo.deleteExpenseCategory(id)
    }

    override suspend fun reorderExpenseCategories(ids: List<Long>) {
        repo.reorderExpenseCategories(ids)
    }

    override suspend fun createFreightCategory(fields: JsonObject) {
        val created = repo.createFreightCategory(
            com.tapmoay.sorders.data.remote.dto.FreightCategoryCreateRequest(
                name = fields.req("name"),
                sortOrder = null,
            ),
        )
        fields.str("sort_order")?.toIntOrNull()?.let { moveFreightCategoryTo(created.id, it) }
    }

    private suspend fun moveFreightCategoryTo(id: Long, position1Based: Int) {
        val ids = repo.freightCategories().sortedBy { it.sortOrder }.map { it.id }.toMutableList()
        ids.remove(id)
        ids.add((position1Based - 1).coerceIn(0, ids.size), id)
        repo.reorderFreightCategories(ids)
    }

    override suspend fun updateFreightCategory(id: Long, fields: JsonObject) {
        require(fields.isNotEmpty()) { "updateFreightCategory 的部分更新体是空的（规格 key 写错了）" }
        repo.updateFreightCategory(
            id,
            com.tapmoay.sorders.data.remote.dto.FreightCategoryUpdateRequest(
                name = fields.str("name"),
                sortOrder = null,
            ),
        )
        fields.str("sort_order")?.toIntOrNull()?.let { moveFreightCategoryTo(id, it) }
    }

    override suspend fun deleteFreightCategory(id: Long) {
        repo.deleteFreightCategory(id)
    }

    override suspend fun reorderFreightCategories(ids: List<Long>) {
        repo.reorderFreightCategories(ids)
    }

    override suspend fun createOrderTemplateCategory(fields: JsonObject) {
        val created = repo.createOrderTemplateCategory(
            com.tapmoay.sorders.data.remote.dto.OrderTemplateCategoryCreateRequest(
                name = fields.req("name"),
                sortOrder = null,
            ),
        )
        fields.str("sort_order")?.toIntOrNull()?.let { moveOrderTemplateCategoryTo(created.id, it) }
    }

    private suspend fun moveOrderTemplateCategoryTo(id: Long, position1Based: Int) {
        val ids = repo.orderTemplateCategories().sortedBy { it.sortOrder }.map { it.id }.toMutableList()
        ids.remove(id)
        ids.add((position1Based - 1).coerceIn(0, ids.size), id)
        repo.reorderOrderTemplateCategories(ids)
    }

    override suspend fun updateOrderTemplateCategory(id: Long, fields: JsonObject) {
        require(fields.isNotEmpty()) { "updateOrderTemplateCategory 的部分更新体是空的（规格 key 写错了）" }
        repo.updateOrderTemplateCategory(
            id,
            com.tapmoay.sorders.data.remote.dto.OrderTemplateCategoryUpdateRequest(
                name = fields.str("name"),
                sortOrder = null,
            ),
        )
        fields.str("sort_order")?.toIntOrNull()?.let { moveOrderTemplateCategoryTo(id, it) }
    }

    override suspend fun deleteOrderTemplateCategory(id: Long) {
        repo.deleteOrderTemplateCategory(id)
    }

    override suspend fun reorderOrderTemplateCategories(ids: List<Long>) {
        repo.reorderOrderTemplateCategories(ids)
    }

    /** 「卡片上突出哪一项」的中文（开销分类专用，与后端 `LINK_KINDS` 逐值对齐）。 */
    private fun linkKindCn(kind: String): String = when (kind) {
        "vehicle" -> "车辆"
        "driver" -> "司机"
        "order" -> "订单"
        else -> "不突出"
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

    override suspend fun restoreUnitConversion(id: Long) {
        repo.restoreUnitConversion(id)
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
            "place_category" ->
                repo.placeCategories().firstOrNull { it.id == id }?.let { AiBefore(id, AiRevertRead.placeCategory(it)) }
            // 另外三张配置名册（2026-09-23）：与上面两张同一种做法（拉列表再挑，后端没有单取）。
            "expense_category" ->
                repo.expenseCategories().firstOrNull { it.id == id }
                    ?.let { AiBefore(id, AiRevertRead.expenseCategory(it)) }
            "freight_category" ->
                repo.freightCategories().firstOrNull { it.id == id }
                    ?.let { AiBefore(id, AiRevertRead.freightCategory(it)) }
            "order_template_category" ->
                repo.orderTemplateCategories().firstOrNull { it.id == id }
                    ?.let { AiBefore(id, AiRevertRead.orderTemplateCategory(it)) }
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
            "place" -> repo.placesAll().firstOrNull { it.id == id }?.let { AiBefore(id, AiRevertRead.place(it)) }
            "contact" -> repo.contacts().firstOrNull { it.id == id }?.let { AiBefore(id, AiRevertRead.contact(it)) }
            "arrears_unit" -> repo.arrearsUnits().firstOrNull { it.id == id }?.let { AiBefore(id, AiRevertRead.arrearsUnit(it)) }
            // 单位换算：拉列表再挑（后端没有单取端点）。
            // ⚠️ 撤回一个"恢复"要读的正是那条已经从名册里消失的记录，所以**两份都查**：
            //    活着的读不到就去回收站里找（`deletedOnly = true`）。
            "unit_conversion" ->
                (repo.unitConversions() + repo.unitConversions(deletedOnly = true))
                    .firstOrNull { it.id == id }
                    ?.let { AiBefore(id, AiRevertRead.unitConversion(it)) }
            // 预设单：拉列表再挑（后端没有单取端点）。挑不到 = null，**不编造**。
            "order_template" ->
                repo.orderTemplates().firstOrNull { it.id == id }?.let { AiBefore(id, AiRevertRead.orderTemplate(it)) }
            // 供应商 / 应付款 / 付款记录（2026-09-22）：同样拉列表再挑。
            // ⚠️ 三张都**必须包含回收站里的行**（`includeDeleted = true`）：
            //    撤回一个"恢复"动作时要读的正是那条已经从名册里消失的记录 ——
            //    不带上它，撤回链的第二步会读不到现场而退化成"撤不回来"。
            "supplier" ->
                repo.suppliers(includeDeleted = true).firstOrNull { it.id == id }
                    ?.let { AiBefore(id, AiRevertRead.supplier(it)) }
            "supplier_payable" ->
                repo.allSupplierPayables(includeDeleted = true).firstOrNull { it.id == id }
                    ?.let { AiBefore(id, AiRevertRead.supplierPayable(it)) }
            "supplier_payment" ->
                repo.supplierPayments(includeDeleted = true).firstOrNull { it.id == id }
                    ?.let { AiBefore(id, AiRevertRead.supplierPayment(it)) }
            "freight_template" ->
                repo.freightTemplates().firstOrNull { it.id == id }?.let { AiBefore(id, AiRevertRead.freightTemplate(it)) }
            "driver_rule" ->
                repo.driverBillingRules().firstOrNull { it.id == id }?.let { AiBefore(id, AiRevertRead.driverRule(it)) }
            // 我自己那一本账上的核销记录：**按 id 拉列表再挑**（后端没有单取端点）。
            // 它只被"改类"撤回用到，而撤销/恢复是一对**成对动作**（不需要读现场），
            // 所以这条分支存在的意义是"这条资源真有读法"——红线会逐个资源对账，缺一个就红。
            "shipper_settlement" ->
                repo.mySettlements(includeDeleted = true, limit = SETTLE_SNAPSHOT_PROBE)
                    .rows.firstOrNull { it.id == id }
                    ?.let { AiBefore(id, buildJsonObject { put("settlement_id", it.id) }) }
            // 认不出的资源标识 = **撤不回来**（不是"不需要撤"）。
            // 静默返回一份空现场会让撤回卡弹出来却什么都没写回去——那比没有撤回更糟。
            else -> null
        }
    }

    private companion object {
        /** 查账号名册时一次拉多少条。 */
        const val USER_PROBE_LIMIT = 20

        /**
         * 单号短于这个长度**直接拒绝**（核销/撤销都按单号认单）。
         *
         * 与订单域同一条理由：`GET /orders?q=` 是模糊匹配，两三个字符会命中一堆单，
         * 而"挑一个最像的"在钱上是不可接受的。
         */
        const val MIN_ORDER_NO_LEN = 6

        /** 一笔订单最多列几笔核销记录（撤销时要全摆出来让用户自己指认）。 */
        const val MY_SETTLE_PROBE = 50

        /** 撤回快照最多在多少笔核销里找那一条（后端这个端点一次最多 2000）。 */
        const val SETTLE_SNAPSHOT_PROBE = 300
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
     * 当前登录角色 + **他是不是批发商货主**。**动作集按它裁剪**（见 [AiWrites.forRole]）。
     *
     * 为什么在这里再查一次而不是只靠界面隐藏：界面藏起来的动作，
     * 模型仍然能从提示词里知道它存在；更糟的是它可以被越权调用。
     * 所以这一层是**真正的门**，界面只是"不给你看"。
     *
     * ⚠️ 第二维（`memberShipper`）不能省：普通货主与批发商货主的**手机上界面就不一样**，
     *    工具清单会按它裁；但"清单裁过"不等于"调不到" —— 模型可以凭上一轮的记忆
     *    写一个 `my_ledger.settle` 出来，所以执行前这一道必须同样按 member 判。
     *
     * ⚠️ 默认值是 `null`（**fail-closed**，2026-09-23 改）——原来是 `{ AiActor.byRole(AiRole.DISPATCHER) }`。
     *    那是个 fail-**open** 的默认：任何忘了传 `actorProvider` 的装配点，拿到的是
     *    **派单员**（权限最大的角色）的动作集，而且不会报错、也没有任何检查会发现。
     *    "认不出角色 = 什么都不给"才是这门该有的缺省行为（与 [allowCost] 的 `false`、
     *    以及 `AiReadCatalog` 那条"认不出角色＝一张表都不给"完全同一纪律）。
     *    生产装配点 `AiContainer` 一直是显式传的；单测里要用哪个角色，就显式写哪个角色 ——
     *    顺带把"这条测试其实依赖缺省值"这件事变成看得见的代码。
     */
    private val actorProvider: () -> AiActor? = { null },
    /**
     * 用户是否打开了「允许 AI 查看成本与毛利」（`AiKeyStore::costVisible`，**派单员默认开**、其余角色默认关）。
     *
     * 这是成本那两扇门**唯一**的开关：`updateProduct` 的 `cost_price` 与
     * `createMovement` 的 `unit_cost` 都要过它。
     * ⛔ 门必须开在**数据源这一层**，不能只靠"动作清单里不列这两个字段"——
     * 模型仍然能从提示词知道它们存在，而且可以被越权调用（与 [actorProvider] 同一条纪律）。
     */
    private val allowCost: () -> Boolean = { false },
    /** 撤回方案的暂存区（App 本地内存）。 */
    private val undos: AiUndoStore = AiUndoStore(),
) {
    /**
     * 参数里带没带**成本类**字段（`cost_price` / `unit_cost`）；带了解释为什么现在不能用。
     *
     * ⚠️ 这两个键与 `AiWriteMasterData` 里那两个字段的 `key` **必须一致**（写错了门就形同虚设，
     *    而且不会有任何报错）。判据钉在 `_check_ai_guardrails.py` 里。
     */
    private fun costFieldIn(params: JsonObject): String? =
        if (allowCost()) null else COST_PARAMS.firstOrNull { params.containsKey(it) }

    /** 成本类字段的键名（见 [costFieldIn]）。改这里必须同时改 `AiWriteMasterData` 里那两个 `key`。 */
    private val COST_PARAMS = listOf("cost_price", "unit_cost")
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
    private val rawHandlers: Map<String, AiWriteHandler> = buildMap {
        listOf(
            NotificationsReadAllHandler(ds),
            ExpenseWriteHandler(ds, store),
            LedgerEntryWriteHandler(ds, store),
            AssignOrderHandler(ds, store),
            RecallOrderHandler(ds, store),
            CancelOrderHandler(ds, store),
            ReturnOrderHandler(ds, store),
            // 退货申请（2026-09-21）：货主申请/撤回 + 派单员驳回/办理。
            // ⚠️ 顺序与 `AiWrites.ACTIONS` 无关（那张表管设置页的显示顺序），这里只管"谁能跑"。
            ApplyReturnRequestHandler(ds, store),
            WithdrawReturnRequestHandler(ds, store),
            RejectReturnRequestHandler(ds, store),
            FulfillReturnRequestHandler(ds, store),
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
            FillNavigationHandler(ds, store),
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
            ReorderPlaceCategoriesHandler(ds, store),
            // 三张配置名册的重排（2026-09-23 补齐）：与上面两个**共用同一份实现**
            // （`AiWriteCatalogHandlers.kt::reorderRoster`），各自只提供名词/名册/往哪提交。
            ReorderExpenseCategoriesHandler(ds, store),
            ReorderFreightCategoriesHandler(ds, store),
            ReorderOrderTemplateCategoriesHandler(ds, store),
            ProductVisibilityHandler(ds, store),
            // 货主自己那一本账（批发商核销 / 撤销；恢复走声明式那个 restoreAction）
            SettleMyLedgerHandler(ds, store),
            RevokeMySettlementHandler(ds, store),
            // 预订单（2026-09-22）：create / update 要收一组"商品 + 数量"，声明式的字段类型里
            // 没有数组，所以这两个是手写处理器（与 `orders.create` 同一个处境、同一个解法）。
            // ⛔ delete 与 restore 走声明式（`crud` 那两个），不要在这里再注册一遍。
            OrderTemplateWriteHandler(AiWrites.ORDER_TEMPLATE_CREATE, ds, store),
            OrderTemplateWriteHandler(AiWrites.ORDER_TEMPLATE_UPDATE, ds, store),
            // 供应商付款（2026-09-22）：**唯一一个把钱写出去的动作**，所以是手写处理器
            // （卡片要写"还差多少 → 付完还差多少"，声明式拿不到这两个数）。
            // ⛔ 其余十个（档案/应付单的增改删、撤销付款、三个 restore）走声明式。
            SupplierPaymentWriteHandler(ds, store),
        ).forEach { put(it.actionId, it) }

        // 声明式：凡是带 crud 规格的动作，一律由通用处理器执行
        AiWrites.ALL.forEach { a ->
            val spec = a.crud ?: return@forEach
            put(a.id, CrudWriteHandler(a, spec, ds, store))
        }
    }

    /**
     * **真正对外的那张表**：每个处理器外面套一层「批量装饰器」（`AiWriteBatch.kt`）。
     *
     * ### 为什么是"包一层"，而不是在每个处理器里加批量分支
     * 用户 2026-09-21 定的准则：「**核心逻辑不要乱动**，其他的以插件的形式 ——
     * **能调方法调方法、能继承就继承、能调 API 就调 API**」（`docs/CORE_AND_EXTENSION.md`）。
     * 批量正好是外面那一层：它的 `prepare` 与 `commit` 都只是**逐条调用内层**，
     * 50 多个处理器一行都不用改，以后新加的动作也自动有批量。
     *
     * ⚠️ 这一层**不动**"谁能调哪个动作"（那是 [AiWrites.allows]）、不动风险档、不动 token 链，
     *    也不改单条那条路（payload 里没有批量标记时原样转发）。它只多认一个参数键：
     *    `items`（见 [BatchWriteHandler.BATCH_ITEMS]）。
     */
    private val handlers: Map<String, AiWriteHandler> = rawHandlers.mapValues { (id, h) ->
        AiWrites.byId(id)?.let { a -> BatchWriteHandler(a, h, store) } ?: h
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
        val actor = actorProvider()
        if (!AiWrites.allows(actor, action.id)) {
            return AiWriteOutcome.Rejected(
                "当前账号是「${actor?.role?.cn ?: "未知角色"}」，没有「${action.title}」这个操作的权限。" +
                    "请如实告诉用户他做不了这件事，并告诉他该找派单员、还是去页面上做。" +
                    "**不要换一个操作去凑**。",
            )
        }
        val handler = handlers[action.id]
            ?: return AiWriteOutcome.Rejected("操作「${action.title}」暂未实现。")

        // ---- 成本那道门（唯一一处）----
        // 用户 2026-09-19：「我们改过、新加的功能 AI 都要能操作」。成本这一块本来是拦死的
        // （成本价一旦进模型上下文就留在聊天记录里、可能被截图外发），现在改成**用户自己的开关**
        // （`AiKeyStore::costVisible`，**派单员默认开**、其余角色默认关）。开关关着时：**不发卡、直接说清楚**，
        // 而不是"发一张卡、点了什么都不发生"——后者是本项目最贵的一类坑。
        costFieldIn(params)?.let { field ->
            return AiWriteOutcome.Rejected(
                "「$field」（成本/进货价）现在是关着的：打开它之后我才能读成本、毛利，" +
                    "也才能帮你改成本价或记进货价。\n" +
                    "位置：AI 助手 → 设置 → 「允许 AI 查看成本与毛利」。\n" +
                    "在此之前，成本价请在「商品管理 → 编辑」里改，进货价在「库存管理 → 入库」里填。",
            )
        }

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
        if (!AiWrites.allows(actorProvider(), plan.actionId)) {
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
            store.card(
                plan.actionId,
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
        if (!AiWrites.allows(actorProvider(), p.actionId)) {
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
            //
            // ⚠️ 2026-09-21（批量）：**批量卡不挂撤回**（一批 N 条要 N 份"改前长什么样"的快照，
            //    一张卡上放不下）。[AiRevert.plan] 只认**一条** payload，拿一批进去只会得到一个
            //    错的方案或 null —— 所以这里根本不该问它。卡片最后一行早就写明了没有撤回
            //    （[AiWrites.BATCH_UNDO_NOTE]），下面那句 `broken` 也因此不适用。
            val batched = isBatchPayload(p.payload)
            val undo = if (batched) {
                null
            } else {
                try {
                    AiRevert.plan(ds, p.actionId, p.payload, p.summary)
                } catch (e: CancellationException) {
                    throw e
                } catch (e: Exception) {
                    null
                }
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
            // ⚠️ 批量不适用：它**本来就不提供撤回**（卡片上写着），那不是"没挂上"。
            val broken = !batched && AiRevert.canRevert(p.actionId) && undo == null
            AiWriteOutcome.Done(
                p.actionId,
                p.title,
                buildString {
                    append(if (note.isNullOrBlank()) "已完成：${p.summary}" else "已完成：${p.summary}\n$note")
                    if (broken) {
                        // ⚠️ 这句是**给用户看的**（Done 消息直接渲染成 Text），不能写 Markdown 星号
                        // ⛔ 2026-09-24 第 34 轮（第 25 轮 01 区 F2）：原来这里把成因**写死成一种**
                        //    ——「写之前读不到这条记录现在的样子（可能已经被删掉）」——而另一半成因
                        //    是"这次改的那几项**原来就是空的**，而这个接口写不回空值"
                        //    （`AiRevert` 里 `old == null` 与「空串」两条分支，命中时它返回 null）。
                        //    写死一种的后果：用户按提示"按编号再试一次"，**必然再失败**（成因根本不同），
                        //    而且他会以为是自己把记录删坏了。两种成因都说出来，出路才成立。
                        append("\n⚠️ 这次没能挂上「撤回」。两种常见原因：")
                        append("① 写之前读不到这条记录现在的样子（可能已经被删掉，或者这个账号看不到它）；")
                        append("② 这次改的那几项原来就是空的，而这个接口写不回空值——它们本来就没什么可退回的。")
                        append("要退回去请告诉我，我按编号再试一次（若是②，试也不会成功，我会如实说）。")
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
