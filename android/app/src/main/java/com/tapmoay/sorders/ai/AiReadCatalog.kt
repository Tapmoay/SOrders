package com.tapmoay.sorders.ai

// ⚠️ 本文件由 `_tools/ai/_gen_ai_read_catalog.py` **机器生成**，不要手改。
// 重新生成：python _tools/ai/_gen_ai_read_catalog.py
// 校验是否过期：python _tools/ai/_gen_ai_read_catalog.py --check

/** AI 能读的一条只读列表/查询接口（来自后端 AST，见生成脚本）。 */
data class ReadAction(
    /** `模块.动作`，模型在工具参数里写的就是它。 */
    val action: String,
    /** 中文名（模块中文名 + 说明），模型据此选工具。 */
    val cn: String,
    val path: String,
    /** 「这张表能按什么筛」——直接写进工具说明，模型不用猜参数名。 */
    val filterHint: String,
    /**
     * 谁能调这个端点（后端角色键：dispatcher / driver / shipper）。
     *
     * 来自后端端点索引生成器对**源码**的解析（权限点 → 角色、体内 raise 403 的角色门槛），
     * 不是手抄的：权限点改名、端点换守卫，这里会跟着变。**空集 = 谁也不给**（fail-closed）。
     */
    val roles: Set<String>,
    /** 该端点声明的查询参数（白名单：只转这些，别的参数一律不转）。 */
    val params: List<ReadParam>,
)

/** 一个可用的查询参数。 */
data class ReadParam(
    val name: String,
    val type: String,
    val required: Boolean,
    val enum: List<String>,
    /** 是不是内部编号类参数（AI 不许看到编号，但可以按**名字**让工具自己解析）。 */
    val isId: Boolean,
)

object AiReadCatalog {

    val ACTIONS: List<ReadAction> = listOf(
        ReadAction("arrears.list_units", "挂账单位列表", "/api/v1/arrears-units", "", setOf("dispatcher"), listOf(
        )),
        ReadAction("cash_flows.list_cash_flows", "现金流水", "/api/v1/cash-flows", "direction、biz_type、party_type、party_id、date_from、date_to、limit", setOf("dispatcher"), listOf(
            ReadParam("direction", "str", false, emptyList(), false),
            ReadParam("biz_type", "str", false, emptyList(), false),
            ReadParam("party_type", "str", false, emptyList(), false),
            ReadParam("party_id", "int", false, emptyList(), true),
            ReadParam("date_from", "date", false, emptyList(), false),
            ReadParam("date_to", "date", false, emptyList(), false),
            ReadParam("limit", "int", false, emptyList(), false),
        )),
        ReadAction("customers.list_customers", "客户列表", "/api/v1/customers", "kind、q", setOf("dispatcher"), listOf(
            ReadParam("kind", "str", false, emptyList(), false),
            ReadParam("q", "str", false, emptyList(), false),
        )),
        ReadAction("driver_billing_rules.list_rules", "司机计费规则（固定工资/每单金额/提成，可挂给司机）", "/api/v1/driver-billing-rules", "vehicle_type、deleted_only", setOf("dispatcher"), listOf(
            ReadParam("vehicle_type", "str", false, emptyList(), false),
            ReadParam("deleted_only", "bool", false, emptyList(), false),
        )),
        ReadAction("driver_bills.list_driver_bills", "司机账单", "/api/v1/driver-bills", "driver_id、month、status、bill_type", setOf("dispatcher", "driver"), listOf(
            ReadParam("driver_id", "int", false, emptyList(), true),
            ReadParam("month", "str", false, emptyList(), false),
            ReadParam("status", "str", false, emptyList(), false),
            ReadParam("bill_type", "str", false, emptyList(), false),
        )),
        ReadAction("driver_settlements.list_settlements", "司机结算记录", "/api/v1/driver-settlements", "driver_id、month、status", setOf("dispatcher", "driver"), listOf(
            ReadParam("driver_id", "int", false, emptyList(), true),
            ReadParam("month", "str", false, emptyList(), false),
            ReadParam("status", "str", false, emptyList(), false),
        )),
        ReadAction("expenses.list_expenses", "支出记录", "/api/v1/expenses", "category、driver_id、date_from、date_to", setOf("dispatcher"), listOf(
            ReadParam("category", "str", false, emptyList(), false),
            ReadParam("driver_id", "int", false, emptyList(), true),
            ReadParam("date_from", "date", false, emptyList(), false),
            ReadParam("date_to", "date", false, emptyList(), false),
        )),
        ReadAction("freight_settlement.freight_settlement", "司机运费结算（按司机聚合，含订单明细）", "/api/v1/freight-settlement", "month、from、to", setOf("dispatcher", "driver"), listOf(
            ReadParam("month", "str", false, emptyList(), false),
            ReadParam("from", "str", false, emptyList(), false),
            ReadParam("to", "str", false, emptyList(), false),
        )),
        ReadAction("freight_templates.list_templates", "运费模板", "/api/v1/freight-templates", "vehicle_type", setOf("dispatcher"), listOf(
            ReadParam("vehicle_type", "str", false, emptyList(), false),
        )),
        ReadAction("inventory.inventory_summary", "库存汇总（可只看低于报警线的）", "/api/v1/inventory/summary", "below_alert", setOf("dispatcher"), listOf(
            ReadParam("below_alert", "bool", false, emptyList(), false),
        )),
        ReadAction("inventory.list_movements", "库存流水（入库/出库/盘点记录）", "/api/v1/inventory/movements", "product_id、limit、offset、date_from、date_to", setOf("dispatcher"), listOf(
            ReadParam("product_id", "int", false, emptyList(), true),
            ReadParam("limit", "int", false, emptyList(), false),
            ReadParam("offset", "int", false, emptyList(), false),
            ReadParam("date_from", "str", false, emptyList(), false),
            ReadParam("date_to", "str", false, emptyList(), false),
        )),
        ReadAction("ledger.list_accounts", "按货主/批发商汇总的账目（谁欠多少、结了多少）", "/api/v1/ledger/accounts", "date_from、date_to、kind", setOf("dispatcher"), listOf(
            ReadParam("date_from", "str", false, emptyList(), false),
            ReadParam("date_to", "str", false, emptyList(), false),
            ReadParam("kind", "str", false, emptyList(), false),
        )),
        ReadAction("ledger.list_entries", "订单账流水（手动记账 + 订单产生的收支）", "/api/v1/ledger/entries", "shipper_id、temp_shipper_name、date_from、date_to", setOf("dispatcher", "shipper"), listOf(
            ReadParam("shipper_id", "int", false, emptyList(), true),
            ReadParam("temp_shipper_name", "str", false, emptyList(), false),
            ReadParam("date_from", "str", false, emptyList(), false),
            ReadParam("date_to", "str", false, emptyList(), false),
        )),
        ReadAction("ledger.list_receipts", "收款记录", "/api/v1/ledger/receipts", "customer_id、date_from、date_to", setOf("dispatcher"), listOf(
            ReadParam("customer_id", "int", false, emptyList(), true),
            ReadParam("date_from", "str", false, emptyList(), false),
            ReadParam("date_to", "str", false, emptyList(), false),
        )),
        ReadAction("ledger.list_temp_shipper_names", "临时货主名清单", "/api/v1/ledger/temp-shipper-names", "", setOf("dispatcher"), listOf(
        )),
        ReadAction("notifications.list_notifications", "消息中心列表", "/api/v1/notifications", "category、days、limit、before_id", setOf("dispatcher", "driver", "shipper"), listOf(
            ReadParam("category", "str", false, emptyList(), false),
            ReadParam("days", "int", false, emptyList(), false),
            ReadParam("limit", "int", false, emptyList(), false),
            ReadParam("before_id", "int", false, emptyList(), true),
        )),
        ReadAction("notifications.unread_count", "未读消息数", "/api/v1/notifications/unread-count", "", setOf("dispatcher", "driver", "shipper"), listOf(
        )),
        ReadAction("operation_logs.list_operation_logs", "操作日志（谁在什么时候改了什么）", "/api/v1/operation-logs", "order_id、operator_id、limit", setOf("dispatcher"), listOf(
            ReadParam("order_id", "int", false, emptyList(), true),
            ReadParam("operator_id", "int", false, emptyList(), true),
            ReadParam("limit", "int", false, emptyList(), false),
        )),
        ReadAction("order_products.list_order_products", "订单商品行（按订单或商品查）", "/api/v1/order-products", "order_id", setOf("dispatcher"), listOf(
            ReadParam("order_id", "int", true, emptyList(), true),
        )),
        ReadAction("orders.list_orders", "订单列表（可按状态/日期/货主名/司机名筛选）", "/api/v1/orders", "status(PENDING_DISPATCH|DISPATCHED|ACCEPTED|DELIVERED|CANCELLED)、q、shipper_id、temp_shipper_name、date_from、date", setOf("dispatcher", "driver", "shipper"), listOf(
            ReadParam("status", "Literal", false, listOf("PENDING_DISPATCH", "DISPATCHED", "ACCEPTED", "DELIVERED", "CANCELLED"), false),
            ReadParam("q", "str", false, emptyList(), false),
            ReadParam("shipper_id", "int", false, emptyList(), true),
            ReadParam("temp_shipper_name", "str", false, emptyList(), false),
            ReadParam("date_from", "str", false, emptyList(), false),
            ReadParam("date_to", "str", false, emptyList(), false),
            ReadParam("limit", "int", false, emptyList(), false),
            ReadParam("include_deleted", "bool", false, emptyList(), false),
            ReadParam("deleted_only", "bool", false, emptyList(), false),
        )),
        ReadAction("orders.pending_dispatch_count", "待派单池还有多少单", "/api/v1/orders/pending-dispatch-count", "", setOf("dispatcher"), listOf(
        )),
        ReadAction("places.list_places", "共享地点库（司机/货主标过的导航坐标，不分人、大家共用；可按地点名或地址搜）", "/api/v1/places", "q、limit", setOf("dispatcher", "driver", "shipper"), listOf(
            ReadParam("q", "str", false, emptyList(), false),
            ReadParam("limit", "int", false, emptyList(), false),
        )),
        ReadAction("price_rules.list_price_rules", "批发商专属定价规则", "/api/v1/price-rules", "", setOf("dispatcher", "shipper"), listOf(
        )),
        ReadAction("product_categories.list_categories", "商品分类名册（下单页左侧那一列的分组与显示顺序，带每类下有几个商品）", "/api/v1/product-categories", "", setOf("dispatcher", "driver", "shipper"), listOf(
        )),
        ReadAction("products.list_products", "商品列表（含库存、批发价档位）", "/api/v1/products", "include_inactive", setOf("dispatcher", "shipper"), listOf(
            ReadParam("include_inactive", "bool", false, emptyList(), false),
        )),
        ReadAction("reports.arrears_summary", "挂账/欠款汇总报表", "/api/v1/reports/arrears-summary", "date_from、date_to", setOf("dispatcher"), listOf(
            ReadParam("date_from", "date", true, emptyList(), false),
            ReadParam("date_to", "date", true, emptyList(), false),
        )),
        ReadAction("reports.product_report", "商品报表（销量、货损）", "/api/v1/reports/products", "mode、date", setOf("dispatcher"), listOf(
            ReadParam("mode", "str", false, emptyList(), false),
            ReadParam("date", "date", true, emptyList(), false),
        )),
        ReadAction("reports.turnover_report", "营业报表（营业额/成本/毛利，按日期范围）", "/api/v1/reports/turnover", "mode、date", setOf("dispatcher"), listOf(
            ReadParam("mode", "str", false, emptyList(), false),
            ReadParam("date", "date", true, emptyList(), false),
        )),
        ReadAction("shipper.list_addresses", "地址与线路库", "/api/v1/shipper/addresses", "", setOf("dispatcher", "shipper"), listOf(
        )),
        ReadAction("shipper.list_contacts", "联系人库", "/api/v1/shipper/contacts", "", setOf("dispatcher", "shipper"), listOf(
        )),
        ReadAction("shipper.list_locations", "地点库", "/api/v1/shipper/locations", "", setOf("dispatcher", "shipper"), listOf(
        )),
        ReadAction("stats.get_driver_performance", "司机跑货统计（单量、准时率、待结运费）", "/api/v1/stats/driver-performance", "date_from、date_to", setOf("dispatcher"), listOf(
            ReadParam("date_from", "date", true, emptyList(), false),
            ReadParam("date_to", "date", true, emptyList(), false),
        )),
        ReadAction("stats.get_exception_orders", "异常订单（货损、超时等）", "/api/v1/stats/exception-orders", "date_from、date_to", setOf("dispatcher"), listOf(
            ReadParam("date_from", "date", true, emptyList(), false),
            ReadParam("date_to", "date", true, emptyList(), false),
        )),
        ReadAction("stats.get_product_drilldown", "某商品的明细下钻", "/api/v1/stats/product-drilldown", "product_name、date_from、date_to", setOf("dispatcher"), listOf(
            ReadParam("product_name", "str", true, emptyList(), false),
            ReadParam("date_from", "date", true, emptyList(), false),
            ReadParam("date_to", "date", true, emptyList(), false),
        )),
        ReadAction("stats.get_shipper_activity", "货主下单活跃度统计", "/api/v1/stats/shipper-activity", "shipper_id、date_from、date_to", setOf("dispatcher"), listOf(
            ReadParam("shipper_id", "int", true, emptyList(), true),
            ReadParam("date_from", "date", true, emptyList(), false),
            ReadParam("date_to", "date", true, emptyList(), false),
        )),
        ReadAction("stats.get_shipper_performance", "货主跑货统计（下单量、金额、异常等）", "/api/v1/stats/shipper-performance", "date_from、date_to", setOf("dispatcher"), listOf(
            ReadParam("date_from", "date", true, emptyList(), false),
            ReadParam("date_to", "date", true, emptyList(), false),
        )),
        ReadAction("stats.get_shipper_product_chart", "某货主的商品维度图表数据", "/api/v1/stats/shipper-product-chart", "date_from、date_to、granularity(month|year)、metric(quantity|amount)", setOf("dispatcher"), listOf(
            ReadParam("date_from", "date", true, emptyList(), false),
            ReadParam("date_to", "date", true, emptyList(), false),
            ReadParam("granularity", "Literal", false, listOf("month", "year"), false),
            ReadParam("metric", "Literal", false, listOf("quantity", "amount"), false),
        )),
        ReadAction("users.list_users", "账号/人员列表（货主、司机、批发商、内部账号，可按角色与关键词筛）", "/api/v1/users", "role(shipper|driver|dispatcher)、is_member、q、limit", setOf("dispatcher"), listOf(
            ReadParam("role", "Literal", false, listOf("shipper", "driver", "dispatcher"), false),
            ReadParam("is_member", "bool", false, emptyList(), false),
            ReadParam("q", "str", false, emptyList(), false),
            ReadParam("limit", "int", false, emptyList(), false),
        )),
        ReadAction("users.read_me", "当前登录账号自己的资料", "/api/v1/users/me", "", setOf("dispatcher", "driver", "shipper"), listOf(
        )),
        ReadAction("vehicles.list_vehicles", "车辆列表", "/api/v1/vehicles", "", setOf("dispatcher"), listOf(
        )),
    )

    private val BY_ACTION: Map<String, ReadAction> = ACTIONS.associateBy { it.action }

    fun find(action: String): ReadAction? = BY_ACTION[action.trim()]

    /** 按模块分组（设置页按模块列开关用）。 */
    fun modules(): List<String> = ACTIONS.map { it.action.substringBefore('.') }.distinct().sorted()

    /** 模块的中文名（来自后端模块表，设置页显示用）。 */
    val MODULE_CN: Map<String, String> = mapOf(
        "arrears" to "挂账单位",
        "cash_flows" to "现金流水",
        "customers" to "客户",
        "driver_billing_rules" to "司机计费规则",
        "driver_bills" to "司机账单",
        "driver_settlements" to "司机结算单",
        "expenses" to "费用",
        "freight_settlement" to "司机运费结算",
        "freight_templates" to "订单/运费模板",
        "inventory" to "库存管理",
        "ledger" to "账本",
        "notifications" to "消息通知",
        "operation_logs" to "操作日志",
        "order_products" to "订单商品行",
        "orders" to "订单/派单",
        "places" to "共享地点库",
        "price_rules" to "批发商定价",
        "product_categories" to "商品分类",
        "products" to "商品管理",
        "reports" to "报表中心",
        "shipper" to "地址与联系人",
        "stats" to "统计口径",
        "users" to "司机/货主/批发商/账号",
        "vehicles" to "车辆管理",
    )

    /** 某个模块下有哪些表（设置页那句说明用）。 */
    fun actionsOf(module: String): List<ReadAction> = ACTIONS.filter { it.action.startsWith(module + ".") }
}
