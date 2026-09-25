package com.tapmoay.sorders.ai

import com.tapmoay.sorders.core.ApiClient
import com.tapmoay.sorders.core.ClientOrigin
import com.tapmoay.sorders.data.remote.dto.ExpenseCreateRequest
import com.tapmoay.sorders.data.remote.dto.LedgerCreateRequest
import com.tapmoay.sorders.data.remote.dto.OrderCreateRequest
import com.tapmoay.sorders.data.remote.dto.PlaceDto
import kotlinx.coroutines.CancellationException
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.put

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

// ---------------------------------------------------------------------------
// 2026-09-25（整改报告 §11 第 3 步）：数据源（RepoWriteDataSource）搬去 AiWriteDataSource.kt 了 ——
//    它是独立的一块职责（真去调 AppRepository 的那一层），与写闸门的判定逻辑没有耦合。
//    判据读的是这一族的**并集**（_airepo.ai_write_source() 读 ai/AiWrite*.kt），所以搬文件不该让红线变红。
// ---------------------------------------------------------------------------


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
            //
            // ⛔ 外面这层 `asAi` 是报告 §15 ② 的最后一跳：它让这一段里发出去的请求都带
            //    `X-SOrders-Origin: ai`，后端据此把审计行记成 `origin=ai`，
            //    `sorders_ai_write_confirmed_today` 就是从那儿数出来的。
            //    ⚠️ 只包**写**这一句 —— 预览（preview_write）不写库，包进去只会让后端
            //    多记一堆没发生的事。
            //    ⚠️ 它必须是 ThreadLocal 级的作用域（见 `core/ClientOrigin.kt`）：
            //    用一个普通全局变量开关的话，这个窗口里**任何别的请求**都会被标成 ai。
            ClientOrigin.asAi { handler.commit(p.payload, "ai-" + token) }
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
// ⚠️ 2026-09-25（整改报告 §11 第 2 步）：这一层**搬去 `AiWriteJson.kt`** 了（同一块职责：payload JSON → 请求 DTO）。
// 判据读的是这一族的**并集**（`_airepo.ai_write_source()` 读 `ai/AiWrite*.kt`）—— 所以搬文件不该让任何红线变红；
// 反向验证的锚点如果还指着这里，`_check_reverse_verify_anchors.py` 会当场点出来（那时**只改锚点，不动判据**）。
