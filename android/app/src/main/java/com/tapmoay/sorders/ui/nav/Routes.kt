package com.tapmoay.sorders.ui.nav

object Routes {
    const val LOGIN = "login"
    const val REGISTER = "register"
    const val HOME = "home"
    const val PROFILE = "profile"
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
    const val DISPATCH_DRIVERS = "dispatcher/drivers"
    const val DISPATCH_LEDGER = "dispatcher/ledger"
    const val MEMBERS = "dispatcher/members"
    const val SHIPPERS_MANAGE = "dispatcher/shippers"
    const val PRODUCTS = "dispatcher/products"
    const val INVENTORY = "dispatcher/inventory"
    const val ARREARS_UNITS = "dispatcher/arrears"
    const val FREIGHT_TEMPLATES = "dispatcher/freight-templates"
    const val FREIGHT_SETTLEMENT = "dispatcher/freight-settlement"
    const val DRIVER_FREIGHT = "driver/freight"
    const val WHOLESALE_PRICING = "dispatcher/pricing/{shipperId}"
    const val MODULE_GROUP = "moduleGroup"
    const val REPORT_TURNOVER = "report/turnover"
    const val REPORT_PRODUCT = "report/product"
    const val REPORT_DRIVER = "report/driver"
    const val REPORT_EXCEPTION = "report/exception"

    fun orderDetail(orderId: Long) = "order/$orderId/detail".replace("$orderId", orderId.toString())
    fun wholesalePricing(shipperId: Long) = "dispatcher/pricing/$shipperId"
}

enum class Role(val key: String, val label: String) {
    SHIPPER("shipper", "货主"),
    DRIVER("driver", "司机"),
    DISPATCHER("dispatcher", "派单员");

    companion object {
        fun fromKey(key: String): Role = entries.firstOrNull { it.key == key } ?: SHIPPER
    }
}
