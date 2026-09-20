package com.tapmoay.sorders.ui.nav

object Routes {
    const val LOGIN = "login"
    const val HOME = "home"
    const val PROFILE = "profile"
    /** 消息提醒设置（语音提醒/念几遍/关掉 App 也收单） */
    const val ALERT_SETTINGS = "settings/alerts"
    const val MESSAGES = "messages"

    // 货主
    const val SHIPPER_ORDERS = "shipper/orders"
    const val ORDER_CREATE = "shipper/order/create"
const val DISPATCH_ORDER_CREATE = "dispatcher/order/create"
    const val ORDER_DETAIL = "order/{orderId}/detail"
    const val ADDRESSES = "shipper/addresses"
    const val SHIPPER_LEDGER = "shipper/ledger"

    // 司机
    const val DRIVER_ORDERS = "driver/orders"

    // 派单员
    const val DISPATCH_POOL = "dispatcher/pool"
    const val DISPATCH_ORDERS = "dispatcher/orders"
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
    const val MEMBERS = "dispatcher/members"
    const val SHIPPERS_MANAGE = "dispatcher/shippers"
    const val PRODUCTS = "dispatcher/products"
    /** 商品分类管理（新建/改名/调顺序）——下单页左侧那一列的顺序就是它。 */
    const val PRODUCT_CATEGORIES = "dispatcher/product-categories"

    const val INVENTORY = "dispatcher/inventory"
    const val ARREARS_UNITS = "dispatcher/arrears"
    const val FREIGHT_TEMPLATES = "dispatcher/freight-templates"
    /** 司机计费规则模板（"给司机定怎么算钱"的规则库，挂载在司机编辑页）。 */
    const val DRIVER_BILLING_RULES = "dispatcher/driver-billing-rules"
    const val FREIGHT_SETTLEMENT = "dispatcher/freight-settlement"
    // 账本 V2：收款/结算/开销/车辆
    const val DISPATCH_RECEIPTS = "dispatcher/receipts"
    const val DISPATCH_SETTLEMENTS = "dispatcher/settlements"
    const val DISPATCH_EXPENSES = "dispatcher/expenses"
    const val DISPATCH_VEHICLES = "dispatcher/vehicles"
    const val DRIVER_FREIGHT = "driver/freight"
    /**
     * 价格矩阵（一个商品 × 一个批发商 = 一个专属价）的**两个方向**。
     * 两个入口、同一页实现 —— 见 `PriceMatrixScreen` 的注释。
     */
    const val PRICE_BY_SHIPPER = "dispatcher/pricing/shipper/{shipperId}"
    const val PRICE_BY_PRODUCT = "dispatcher/pricing/product/{productId}"
    const val MODULE_GROUP = "moduleGroup"

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
}

enum class Role(val key: String, val label: String) {
    SHIPPER("shipper", "货主"),
    DRIVER("driver", "司机"),
    DISPATCHER("dispatcher", "派单员");

    companion object {
        fun fromKey(key: String): Role = entries.firstOrNull { it.key == key } ?: SHIPPER
    }
}