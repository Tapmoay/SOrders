package com.tapmoay.sorders.ui.nav

object Routes {
    const val LOGIN = "login"
    const val HOME = "home"
    /** 消息提醒设置（语音提醒/念几遍/关掉 App 也收单） */
    const val ALERT_SETTINGS = "settings/alerts"
    /**
     * 基础设置（2026-09-21 新增）：「我的」页的**第二层** —— 随日落 / 夜间模式 / 提示，
     * 三个**纯显示偏好**。用户原话：「我们按钮太多了，哪些是不怎么重要的，我们就放到基础设置当中」。
     */
    const val BASIC_SETTINGS = "settings/basic"
    const val MESSAGES = "messages"

    // 货主
    const val SHIPPER_ORDERS = "shipper/orders"
    const val ORDER_CREATE = "shipper/order/create"
    const val DISPATCH_ORDER_CREATE = "dispatcher/order/create"
    /**
     * 「预订单」管理页（2026-09-22 用户要求：「专门去管理预设的订单」）。
     *
     * ⛔ 这一页**不生成订单**：点「用这张下单」只是带参跳 `DISPATCH_ORDER_CREATE?template={id}`，
     * 最后由下单页那个按钮走 `POST /orders`（与手工下单同一条路）。
     */
    const val DISPATCH_ORDER_TEMPLATES = "dispatcher/order-templates"
    const val ORDER_DETAIL = "order/{orderId}/detail"
    const val ADDRESSES = "shipper/addresses"
    const val SHIPPER_LEDGER = "shipper/ledger"
    /**
     * 「我的退货申请」（2026-09-21）：货主在订单上提的退货申请在这里看进展、可以撤回。
     *
     * ⛔ 货主**只能申请**（申请阶段库存与账本一分不动）；真正执行退货的是派单端的
     * [DISPATCH_RETURN_REQUESTS]（用户口径：「批发商只是一个申请，派单员才是实际性的操作」）。
     */
    const val SHIPPER_RETURN_REQUESTS = "shipper/return-requests"

    // 司机
    const val DRIVER_ORDERS = "driver/orders"

    // 派单员
    const val DISPATCH_ORDERS = "dispatcher/orders"
    /**
     * 「退货申请」待办页（派单端，2026-09-21）：货主提的申请排队在这里。
     *
     * ★ **办理就是真的退货**：库存、账本、退款、订单状态都在点下去那一刻才变；
     * 数量**锁死**（照申请单退），要改只能驳回让货主重提。驳回必须写理由。
     */
    const val DISPATCH_RETURN_REQUESTS = "dispatcher/return-requests"
    const val ACCOUNTS = "dispatcher/accounts"
    const val DISPATCH_DRIVERS = "dispatcher/drivers"
    const val DISPATCH_LEDGER = "dispatcher/ledger"
    /**
     * 「账本管理」**入口页**（报表中心那种形式，2026-09-20 第二轮）：
     * 工作台网格上那一格点进来是它，里面 6 件事（司机账/订单账/货主账/批发商账/客户收款/开销管理）。
     * 它是**入口**，不是账本页本身（账本页仍然是 `DISPATCH_LEDGER`，只管看账）。
     */
    const val LEDGER_HOME = "dispatcher/ledger/home"
    /**
     * 账本**某一类**的直达路由（账本管理入口页里的 4 格用它）。
     *
     * 4 类账是同一页的四个档位（`?tab=`），所以那 4 格不是四个页面 ——
     * 各自建一个页面就会出现"同一套数据四份实现"。
     */
    fun dispatcherLedger(tab: Int): String = DISPATCH_LEDGER + "?tab=" + tab

    /** 一个供应商的账（`?supplierId=`）—— 编号拼进查询串只有这一处，别在页面里手拼。 */
    fun supplierDetail(supplierId: Long): String = DISPATCH_SUPPLIER_DETAIL + "?supplierId=" + supplierId
    /**
     * 账本「**记一笔账**」= 单独一页（用户 2026-09-20 第七轮）。
     *
     * 为什么不是弹窗：这一页要**从商品库选商品**（全屏底部弹层）——
     * 套进 `AlertDialog` 就是两层 modal 窗口叠着；而且一共 7 项要填。
     */
    const val LEDGER_CREATE = "dispatcher/ledger/create"
    const val MEMBERS = "dispatcher/members"
    const val SHIPPERS_MANAGE = "dispatcher/shippers"
    const val PRODUCTS = "dispatcher/products"
    /** 商品分类管理（新建/改名/调顺序）——下单页左侧那一列的顺序就是它。 */
    const val PRODUCT_CATEGORIES = "dispatcher/product-categories"

    /**
     * **新增 / 编辑商品 = 单独一页**（2026-09-21，商品管理改版第 1 期）。
     *
     * 为什么不是原来那个底部抽屉：① 参考图（POS 的新增商品）就是整页；
     * ② 用户自己后来定了「新增开销 = 单独一页，「就相当于新增订单一样」」；
     * ③ 这一页要进**二级选择页**（单位 / 分组），抽屉里再叠弹层就是两层 modal 压着。
     *
     * `?productId=` 缺省 = 新增。参数名的拼法**只有 [productForm] 这一处**
     * （`NavGraph.kt` 的 `navArgument("productId")` 认的就是它）。
     */
    const val PRODUCT_FORM = "dispatcher/products/form"

    /** `productId = null` → 新增；非空 → 编辑那一个。 */
    fun productForm(productId: Long? = null): String =
        if (productId != null && productId > 0L) "$PRODUCT_FORM?productId=$productId" else PRODUCT_FORM

    const val INVENTORY = "dispatcher/inventory"
    /**
     * **批量操作**（2026-09-21，底栏第三格 —— 用户原话：「右边那个**批量操作**」）。
     *
     * 只做商品管理里真有的动作：**改分组 / 沽清 / 上架 / 删除**；执行是**逐条**调已有接口
     * （不新增后端端点），结果逐条汇报。⛔ 没有"批量改库存"（库存只能走出入库流水）。
     */
    const val PRODUCT_BATCH = "dispatcher/products/batch"

    /**
     * **商品排序**（2026-09-21，用户：「那个排序你没加啊」）。
     *
     * 从上到下 = 商品管理页里的顺序；拖动或「置顶↑」调，点「完成」逐条写
     * `PATCH /products/{id} {sort_order}`（第 1 行写 1、第 2 行写 2 …；0 保留给"没排过"）。
     */
    const val PRODUCT_SORT = "dispatcher/products/sort"
    const val ARREARS_UNITS = "dispatcher/arrears"
    const val FREIGHT_TEMPLATES = "dispatcher/freight-templates"
    /** 运费分类管理（2026-09-21）：运费模板与计费规则**共用**的一套分类。 */
    const val FREIGHT_CATEGORIES = "dispatcher/freight-categories"
    /**
     * **运费待定价**（2026-09-21）：已经派出去、但没有运费的单。
     *
     * 「没有匹配到就没有计费、没有定价……这个订单就得派单员手动去给他定价」——
     * 那种单在这里排队，定价时可以顺手把路线 + 价目沉淀下来。
     */
    const val FREIGHT_UNPRICED = "dispatcher/freight-unpriced"
    /** 司机计费规则模板（"给司机定怎么算钱"的规则库，挂载在司机编辑页）。 */
    const val DRIVER_BILLING_RULES = "dispatcher/driver-billing-rules"
    const val FREIGHT_SETTLEMENT = "dispatcher/freight-settlement"
    // 账本 V2：收款/结算/开销/车辆
    const val DISPATCH_RECEIPTS = "dispatcher/receipts"
    const val DISPATCH_SETTLEMENTS = "dispatcher/settlements"
    const val DISPATCH_EXPENSES = "dispatcher/expenses"
    /**
     * 「收支」（2026-09-22 用户要求）：账本管理入口页那一格 —— 收入按**来源**、支出按**去路**，
     * 各一路一行（客户收款/挂账结清/油费/司机运费/付供应商…），点一行进那一类的流水明细。
     *
     * ⛔ 「开销管理」不再与它并列占一格（用户：「干脆把我们两个**整合在一起**」）：
     *    支出那张卡底部就是去 `DISPATCH_EXPENSES` 的入口，功能一个没少。
     */
    const val DISPATCH_CASH = "dispatcher/cash"
    /**
     * 「供应商 / 厂商」档案页（2026-09-22 用户要求「给供应商付尾款」「采购设备」「邮费」）。
     *
     * 拍板口径是**跟客户一个量级的档案**：可挂账、可查还欠多少、可分次付款。
     * 它在账本管理入口页上占一格（支出那一块），「收支」页支出卡底部也有一条入口。
     */
    const val DISPATCH_SUPPLIERS = "dispatcher/suppliers"
    /**
     * 一个供应商的账（`?supplierId=`）：几笔应付、每笔付了多少、每笔付款什么时候付的。
     *
     * ⚠️ 编号走**查询参数**而不是路径段（与 `DISPATCH_LEDGER + "?tab="` 同一条约定）：
     *    这一页没有"只有编号才能进来"的意思，查询串也让 `Routes.supplierDetail(id)` 一处拼得出来。
     */
    const val DISPATCH_SUPPLIER_DETAIL = "dispatcher/suppliers/detail"
    /**
     * 「收支」里点某一路进来的**流水明细**（`?direction=&biz=&from=&to=`）。
     *
     * ⚠️ 四个都是**查询参数**、且**窗口由总览页带过来**：在这里重新挑一次时间，
     *    看到的明细会与刚才那一路的合计对不上，用户只会以为账错了。
     * ⚠️ 查询串本身在 `NavGraph` 里拼（与 `DISPATCH_LEDGER + "?tab="` 同一条约定）。
     */
    const val DISPATCH_CASH_DETAIL = "dispatcher/cash/detail"
    /** 新增开销：**单独一页**（用户 2026-09-20：「就相当于新增订单一样」）。 */
    const val EXPENSE_CREATE = "dispatcher/expenses/create"
    /** 开销分类管理（与商品分类管理同一套规矩）。 */
    const val EXPENSE_CATEGORIES = "dispatcher/expenses/categories"
    const val DISPATCH_VEHICLES = "dispatcher/vehicles"
    const val DRIVER_FREIGHT = "driver/freight"
    /**
     * 价格矩阵（一个商品 × 一个批发商 = 一个专属价）的**两个方向**。
     * 两个入口、同一页实现 —— 见 `PriceMatrixScreen` 的注释。
     */
    const val PRICE_BY_SHIPPER = "dispatcher/pricing/shipper/{shipperId}"
    const val PRICE_BY_PRODUCT = "dispatcher/pricing/product/{productId}"
    // ⛔ `MODULE_GROUP`（工作台分组二级页）2026-09-20 删除：三端都没有带 children 的格子，
    //    那条路由没有任何入口点得到（见 `ModuleEntry` 的注释）。

    // AI 助手（派单员端）
    const val AI_CHAT = "ai/chat"
    const val AI_SETTINGS = "ai/settings"

    const val REPORT_HOME = "report/home"
const val REPORT_TURNOVER = "report/turnover"
    const val REPORT_PRODUCT = "report/product"
    const val REPORT_DRIVER = "report/driver"
const val REPORT_CUSTOMER = "report/customer"
const val REPORT_FINANCE = "report/finance"
    const val REPORT_EXCEPTION = "report/exception"

    fun orderDetail(orderId: Long) = "order/$orderId/detail".replace("$orderId", orderId.toString())
    fun priceByShipper(shipperId: Long) = "dispatcher/pricing/shipper/$shipperId"
    fun priceByProduct(productId: Long) = "dispatcher/pricing/product/$productId"

    // ---- 退货申请的**定位直达**（2026-09-21 用户要求：「到消息中心哦。其实本来就要做到直达的」）----
    //
    // 消息中心点那条通知 → 打开对应那一端的退货申请页，并**定位到那一张**（`?focus=`）。
    // 两页各自只有一条路由：参数是**可选的查询串**（`defaultValue = 0L`），
    // 所以工作台网格那种"不带 focus"的进入方式照旧用 `SHIPPER_RETURN_REQUESTS` 本身，不要另建路由。
    //
    // ⚠️ 为什么要一个构造函数而不是让调用方自己拼字符串：`?focus=` 的键名在
    //    `NavGraph.kt` 的 `navArgument` 与这两处各写一遍就会分叉（改了这边忘了那边 =
    //    点了通知静默落在列表顶部、定位不到 —— 而界面上完全看不出来是路由参数写错了）。
    fun shipperReturnRequests(focusRequestId: Long? = null): String =
        withFocus(SHIPPER_RETURN_REQUESTS, focusRequestId)

    fun dispatcherReturnRequests(focusRequestId: Long? = null): String =
        withFocus(DISPATCH_RETURN_REQUESTS, focusRequestId)

    /** `focus` 的键名**只有这一处**（`NavGraph.kt` 的 `navArgument("focus")` 认的就是它）。 */
    private fun withFocus(base: String, focusRequestId: Long?): String =
        if (focusRequestId != null && focusRequestId > 0L) "$base?focus=$focusRequestId" else base
}

enum class Role(val key: String, val label: String) {
    SHIPPER("shipper", "货主"),
    DRIVER("driver", "司机"),
    DISPATCHER("dispatcher", "派单员");

    companion object {
        fun fromKey(key: String): Role = entries.firstOrNull { it.key == key } ?: SHIPPER
    }
}