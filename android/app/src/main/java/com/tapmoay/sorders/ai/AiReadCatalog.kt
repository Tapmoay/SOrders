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
    /**
     * 只有**批发商货主**（`users.is_member=1`）能读这张表。
     *
     * 判据来自生成脚本的 `MEMBER_ONLY_READS`（与写侧 `AiWriteAction.memberOnly` 对称）：
     * 普通货主手机上**没有这一段界面** —— 给他的 AI 列出来，只会让它去解释
     * 一件他做不了的事。**空集 roles 之外的第二个维度，别混。**
     */
    val memberOnly: Boolean,
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
        ReadAction("arrears.list_units", "挂账单位列表", "/api/v1/arrears-units", "", setOf("dispatcher"), false, listOf(
        )),
        ReadAction("cash_flows.cash_flow_breakdown", "收支分项（收入按来源、支出按去路，每路带金额与笔数）", "/api/v1/cash-flows/breakdown", "date_from、date_to", setOf("dispatcher"), false, listOf(
            ReadParam("date_from", "date", false, emptyList(), false),
            ReadParam("date_to", "date", false, emptyList(), false),
        )),
        ReadAction("cash_flows.cash_flow_summary", "现金收支汇总（按期合计流入/流出）", "/api/v1/cash-flows/summary", "direction、biz_type、party_type、party_id、date_from、date_to", setOf("dispatcher"), false, listOf(
            ReadParam("direction", "str", false, emptyList(), false),
            ReadParam("biz_type", "str", false, emptyList(), false),
            ReadParam("party_type", "str", false, emptyList(), false),
            ReadParam("party_id", "int", false, emptyList(), true),
            ReadParam("date_from", "date", false, emptyList(), false),
            ReadParam("date_to", "date", false, emptyList(), false),
        )),
        ReadAction("cash_flows.list_cash_flows", "现金流水", "/api/v1/cash-flows", "direction、biz_type、party_type、party_id、date_from、date_to、limit", setOf("dispatcher"), false, listOf(
            ReadParam("direction", "str", false, emptyList(), false),
            ReadParam("biz_type", "str", false, emptyList(), false),
            ReadParam("party_type", "str", false, emptyList(), false),
            ReadParam("party_id", "int", false, emptyList(), true),
            ReadParam("date_from", "date", false, emptyList(), false),
            ReadParam("date_to", "date", false, emptyList(), false),
            ReadParam("limit", "int", false, emptyList(), false),
        )),
        ReadAction("customers.list_customers", "客户列表", "/api/v1/customers", "kind、q", setOf("dispatcher"), false, listOf(
            ReadParam("kind", "str", false, emptyList(), false),
            ReadParam("q", "str", false, emptyList(), false),
        )),
        ReadAction("driver_billing_rules.list_rules", "司机计费规则（固定工资/每单金额/提成，可挂给司机）", "/api/v1/driver-billing-rules", "vehicle_type、deleted_only", setOf("dispatcher"), false, listOf(
            ReadParam("vehicle_type", "str", false, emptyList(), false),
            ReadParam("deleted_only", "bool", false, emptyList(), false),
        )),
        ReadAction("driver_bills.list_driver_bills", "司机账单", "/api/v1/driver-bills", "driver_id、month、status、bill_type、include_deleted", setOf("dispatcher", "driver"), false, listOf(
            ReadParam("driver_id", "int", false, emptyList(), true),
            ReadParam("month", "str", false, emptyList(), false),
            ReadParam("status", "str", false, emptyList(), false),
            ReadParam("bill_type", "str", false, emptyList(), false),
            ReadParam("include_deleted", "bool", false, emptyList(), false),
        )),
        ReadAction("driver_settlements.list_settlements", "司机结算记录", "/api/v1/driver-settlements", "driver_id、month、status", setOf("dispatcher", "driver"), false, listOf(
            ReadParam("driver_id", "int", false, emptyList(), true),
            ReadParam("month", "str", false, emptyList(), false),
            ReadParam("status", "str", false, emptyList(), false),
        )),
        ReadAction("expense_categories.list_categories", "开销分类名册（「开销管理」左栏那一列的名字与顺序，带每类下有**几笔开销**；⚠️ 改名会级联改掉挂在这一类下的开销记录）", "/api/v1/expense-categories", "", setOf("dispatcher"), false, listOf(
        )),
        ReadAction("expenses.list_expenses", "支出记录", "/api/v1/expenses", "category、driver_id、date_from、date_to", setOf("dispatcher"), false, listOf(
            ReadParam("category", "str", false, emptyList(), false),
            ReadParam("driver_id", "int", false, emptyList(), true),
            ReadParam("date_from", "date", false, emptyList(), false),
            ReadParam("date_to", "date", false, emptyList(), false),
        )),
        ReadAction("freight_categories.list_categories", "运费分类名册（「哪几类货」那张配置表：名字、顺序，带每类下挂着**几条价目**与**几份计费规则**；⚠️ 还有价目/规则挂着时不许删）", "/api/v1/freight-categories", "", setOf("dispatcher"), false, listOf(
        )),
        ReadAction("freight_settlement.freight_settlement", "司机运费结算（按司机聚合，含订单明细）", "/api/v1/freight-settlement", "month、from、to", setOf("dispatcher", "driver"), false, listOf(
            ReadParam("month", "str", false, emptyList(), false),
            ReadParam("from", "str", false, emptyList(), false),
            ReadParam("to", "str", false, emptyList(), false),
        )),
        ReadAction("freight_templates.list_templates", "运费模板", "/api/v1/freight-templates", "vehicle_type", setOf("dispatcher"), false, listOf(
            ReadParam("vehicle_type", "str", false, emptyList(), false),
        )),
        ReadAction("inventory.inventory_summary", "库存汇总（可只看低于报警线的）", "/api/v1/inventory/summary", "below_alert", setOf("dispatcher"), false, listOf(
            ReadParam("below_alert", "bool", false, emptyList(), false),
        )),
        ReadAction("inventory.list_movements", "库存流水（入库/出库/盘点记录）", "/api/v1/inventory/movements", "product_id、limit、offset、date_from、date_to", setOf("dispatcher"), false, listOf(
            ReadParam("product_id", "int", false, emptyList(), true),
            ReadParam("limit", "int", false, emptyList(), false),
            ReadParam("offset", "int", false, emptyList(), false),
            ReadParam("date_from", "str", false, emptyList(), false),
            ReadParam("date_to", "str", false, emptyList(), false),
        )),
        ReadAction("ledger.list_accounts", "按货主/批发商汇总的账目（谁欠多少、结了多少）", "/api/v1/ledger/accounts", "date_from、date_to、kind", setOf("dispatcher"), false, listOf(
            ReadParam("date_from", "str", false, emptyList(), false),
            ReadParam("date_to", "str", false, emptyList(), false),
            ReadParam("kind", "str", false, emptyList(), false),
        )),
        ReadAction("ledger.list_entries", "订单账流水（手动记账 + 订单产生的收支）", "/api/v1/ledger/entries", "shipper_id、temp_shipper_name、date_from、date_to、limit、offset", setOf("dispatcher", "shipper"), false, listOf(
            ReadParam("shipper_id", "int", false, emptyList(), true),
            ReadParam("temp_shipper_name", "str", false, emptyList(), false),
            ReadParam("date_from", "str", false, emptyList(), false),
            ReadParam("date_to", "str", false, emptyList(), false),
            ReadParam("limit", "int", false, emptyList(), false),
            ReadParam("offset", "int", false, emptyList(), false),
        )),
        ReadAction("ledger.list_receipts", "收款记录", "/api/v1/ledger/receipts", "customer_id、date_from、date_to", setOf("dispatcher"), false, listOf(
            ReadParam("customer_id", "int", false, emptyList(), true),
            ReadParam("date_from", "str", false, emptyList(), false),
            ReadParam("date_to", "str", false, emptyList(), false),
        )),
        ReadAction("ledger.list_temp_shipper_names", "临时货主名清单", "/api/v1/ledger/temp-shipper-names", "", setOf("dispatcher"), false, listOf(
        )),
        ReadAction("notifications.list_notifications", "消息中心列表", "/api/v1/notifications", "category、days、limit、before_id", setOf("dispatcher", "driver", "shipper"), false, listOf(
            ReadParam("category", "str", false, emptyList(), false),
            ReadParam("days", "int", false, emptyList(), false),
            ReadParam("limit", "int", false, emptyList(), false),
            ReadParam("before_id", "int", false, emptyList(), true),
        )),
        ReadAction("notifications.unread_count", "未读消息数", "/api/v1/notifications/unread-count", "", setOf("dispatcher", "driver", "shipper"), false, listOf(
        )),
        ReadAction("operation_logs.list_operation_logs", "操作日志（谁在什么时候改了什么）", "/api/v1/operation-logs", "order_id、operator_id、skip、limit", setOf("dispatcher"), false, listOf(
            ReadParam("order_id", "int", false, emptyList(), true),
            ReadParam("operator_id", "int", false, emptyList(), true),
            ReadParam("skip", "int", false, emptyList(), false),
            ReadParam("limit", "int", false, emptyList(), false),
        )),
        ReadAction("order_products.list_order_products", "订单商品行（按订单或商品查）", "/api/v1/order-products", "order_id", setOf("dispatcher"), false, listOf(
            ReadParam("order_id", "int", true, emptyList(), true),
        )),
        ReadAction("order_template_categories.list_categories", "预订单分类名册（预订单页左侧那一列的分组与显示顺序，带每类下挂着几张预设单）", "/api/v1/order-template-categories", "", setOf("dispatcher"), false, listOf(
        )),
        ReadAction("order_templates.list_templates", "预订单（预设好的订单：货主/地址/运费/商品与数量）", "/api/v1/order-templates", "", setOf("dispatcher"), false, listOf(
        )),
        ReadAction("orders.list_orders", "订单列表（可按状态/日期/货主名/司机名筛选）", "/api/v1/orders", "status(PENDING_DISPATCH|DISPATCHED|ACCEPTED|DELIVERED|CANCELLED|RETURNED)、q、shipper_id、temp_shipper_name、unpri", setOf("dispatcher", "driver", "shipper"), false, listOf(
            ReadParam("status", "Literal", false, listOf("PENDING_DISPATCH", "DISPATCHED", "ACCEPTED", "DELIVERED", "CANCELLED", "RETURNED"), false),
            ReadParam("q", "str", false, emptyList(), false),
            ReadParam("shipper_id", "int", false, emptyList(), true),
            ReadParam("temp_shipper_name", "str", false, emptyList(), false),
            ReadParam("unpriced", "bool", false, emptyList(), false),
            ReadParam("date_from", "str", false, emptyList(), false),
            ReadParam("date_to", "str", false, emptyList(), false),
            ReadParam("delivered_from", "str", false, emptyList(), false),
            ReadParam("delivered_to", "str", false, emptyList(), false),
            ReadParam("limit", "int", false, emptyList(), false),
            ReadParam("include_deleted", "bool", false, emptyList(), false),
            ReadParam("deleted_only", "bool", false, emptyList(), false),
        )),
        ReadAction("orders.pending_dispatch_count", "待派单池还有多少单", "/api/v1/orders/pending-dispatch-count", "", setOf("dispatcher"), false, listOf(
        )),
        ReadAction("place_categories.list_categories", "地点分类名册（**当前登录人自己那份**：地点库左侧那一列的名字与顺序）", "/api/v1/place-categories", "", setOf("dispatcher", "shipper"), false, listOf(
        )),
        ReadAction("places.list_places", "共享地点库（司机/货主标过的导航坐标，不分人、大家共用；可按地点名或地址搜）", "/api/v1/places", "q、limit", setOf("dispatcher", "driver", "shipper"), false, listOf(
            ReadParam("q", "str", false, emptyList(), false),
            ReadParam("limit", "int", false, emptyList(), false),
        )),
        ReadAction("price_rules.list_price_rules", "批发商专属定价规则", "/api/v1/price-rules", "", setOf("dispatcher", "shipper"), false, listOf(
        )),
        ReadAction("product_categories.list_categories", "商品分类名册（下单页左侧那一列的分组与显示顺序，带每类下有几个商品）", "/api/v1/product-categories", "", setOf("dispatcher", "driver", "shipper"), false, listOf(
        )),
        ReadAction("products.list_products", "商品列表（含库存、单位、分类、售价；⚠️ 不含批发商专属价，那是另一张表）", "/api/v1/products", "include_inactive", setOf("dispatcher", "shipper"), false, listOf(
            ReadParam("include_inactive", "bool", false, emptyList(), false),
        )),
        ReadAction("products.product_cost_history", "商品成本价的历史（某段时间的成本价是多少、从什么时候到什么时候、是进货录的还是手改的）", "/api/v1/products/cost-history", "product_id、limit", setOf("dispatcher"), false, listOf(
            ReadParam("product_id", "int", false, emptyList(), true),
            ReadParam("limit", "int", false, emptyList(), false),
        )),
        ReadAction("reports.arrears_summary", "挂账/欠款汇总报表", "/api/v1/reports/arrears-summary", "date_from、date_to", setOf("dispatcher"), false, listOf(
            ReadParam("date_from", "date", true, emptyList(), false),
            ReadParam("date_to", "date", true, emptyList(), false),
        )),
        ReadAction("reports.product_report", "商品报表（销量、货损）", "/api/v1/reports/products", "mode、date、date_from、date_to", setOf("dispatcher"), false, listOf(
            ReadParam("mode", "str", false, emptyList(), false),
            ReadParam("date", "date", true, emptyList(), false),
            ReadParam("date_from", "date", false, emptyList(), false),
            ReadParam("date_to", "date", false, emptyList(), false),
        )),
        ReadAction("reports.turnover_report", "营业报表（营业额/成本/毛利，按日期范围）", "/api/v1/reports/turnover", "mode、date、date_from、date_to", setOf("dispatcher"), false, listOf(
            ReadParam("mode", "str", false, emptyList(), false),
            ReadParam("date", "date", true, emptyList(), false),
            ReadParam("date_from", "date", false, emptyList(), false),
            ReadParam("date_to", "date", false, emptyList(), false),
        )),
        ReadAction("return_requests.list_my_return_requests", "我（货主）自己提过的退货申请：待派单员处理的、已办完的、被驳回的（含驳回原因）", "/api/v1/return-requests/mine", "order_id、status、limit", setOf("shipper"), false, listOf(
            ReadParam("order_id", "int", false, emptyList(), true),
            ReadParam("status", "str", false, emptyList(), false),
            ReadParam("limit", "int", false, emptyList(), false),
        )),
        ReadAction("return_requests.list_return_requests", "待派单员处理的退货申请（货主提的、还没办的）：谁提的、要退哪几样、各几件", "/api/v1/return-requests", "order_id、status、limit", setOf("dispatcher"), false, listOf(
            ReadParam("order_id", "int", false, emptyList(), true),
            ReadParam("status", "str", false, emptyList(), false),
            ReadParam("limit", "int", false, emptyList(), false),
        )),
        ReadAction("shipper.list_addresses", "地址与线路库", "/api/v1/shipper/addresses", "", setOf("dispatcher", "shipper"), false, listOf(
        )),
        ReadAction("shipper.list_contacts", "联系人库", "/api/v1/shipper/contacts", "", setOf("dispatcher", "shipper"), false, listOf(
        )),
        ReadAction("shipper.list_locations", "地点库", "/api/v1/shipper/locations", "", setOf("dispatcher", "shipper"), false, listOf(
        )),
        ReadAction("shipper_ledger.ledger_summary", "我的收支统计（这一段我该付给公司的：货款/已付/还欠；批发商另有一边：我该向下游货主收的货款/已收/待收）", "/api/v1/shipper-ledger/summary", "delivered_from、delivered_to、customer_name、customer_phone", setOf("shipper"), false, listOf(
            ReadParam("delivered_from", "str", false, emptyList(), false),
            ReadParam("delivered_to", "str", false, emptyList(), false),
            ReadParam("customer_name", "str", false, emptyList(), false),
            ReadParam("customer_phone", "str", false, emptyList(), false),
        )),
        ReadAction("shipper_ledger.list_settlements", "我（批发商）给下游货主收钱的核销记录 —— **自己那一本账**，与派单员记录的公司账是两笔钱；可按订单、按送达日窗口查，`include_deleted=true` 能看到已撤销的那些", "/api/v1/shipper-ledger/settlements", "order_id、delivered_from、delivered_to、include_deleted、limit、offset", setOf("shipper"), true, listOf(
            ReadParam("order_id", "int", false, emptyList(), true),
            ReadParam("delivered_from", "str", false, emptyList(), false),
            ReadParam("delivered_to", "str", false, emptyList(), false),
            ReadParam("include_deleted", "bool", false, emptyList(), false),
            ReadParam("limit", "int", false, emptyList(), false),
            ReadParam("offset", "int", false, emptyList(), false),
        )),
        ReadAction("stats.get_driver_performance", "司机跑货统计（单量、准时率、待结运费）", "/api/v1/stats/driver-performance", "date_from、date_to", setOf("dispatcher"), false, listOf(
            ReadParam("date_from", "date", true, emptyList(), false),
            ReadParam("date_to", "date", true, emptyList(), false),
        )),
        ReadAction("stats.get_exception_orders", "异常订单（货损、超时等）", "/api/v1/stats/exception-orders", "date_from、date_to", setOf("dispatcher"), false, listOf(
            ReadParam("date_from", "date", true, emptyList(), false),
            ReadParam("date_to", "date", true, emptyList(), false),
        )),
        ReadAction("stats.get_product_drilldown", "某商品的明细下钻", "/api/v1/stats/product-drilldown", "product_name、date_from、date_to", setOf("dispatcher"), false, listOf(
            ReadParam("product_name", "str", true, emptyList(), false),
            ReadParam("date_from", "date", true, emptyList(), false),
            ReadParam("date_to", "date", true, emptyList(), false),
        )),
        ReadAction("stats.get_shipper_activity", "货主下单活跃度统计", "/api/v1/stats/shipper-activity", "shipper_id、date_from、date_to", setOf("dispatcher"), false, listOf(
            ReadParam("shipper_id", "int", true, emptyList(), true),
            ReadParam("date_from", "date", true, emptyList(), false),
            ReadParam("date_to", "date", true, emptyList(), false),
        )),
        ReadAction("stats.get_shipper_performance", "货主跑货统计（下单量、金额、异常等）", "/api/v1/stats/shipper-performance", "date_from、date_to", setOf("dispatcher"), false, listOf(
            ReadParam("date_from", "date", true, emptyList(), false),
            ReadParam("date_to", "date", true, emptyList(), false),
        )),
        ReadAction("stats.get_shipper_product_chart", "某货主的商品维度图表数据", "/api/v1/stats/shipper-product-chart", "date_from、date_to、granularity(month|year)、metric(quantity|amount)", setOf("dispatcher"), false, listOf(
            ReadParam("date_from", "date", true, emptyList(), false),
            ReadParam("date_to", "date", true, emptyList(), false),
            ReadParam("granularity", "Literal", false, listOf("month", "year"), false),
            ReadParam("metric", "Literal", false, listOf("quantity", "amount"), false),
        )),
        ReadAction("suppliers.list_payables", "应付单（欠某个供应商的每一笔钱：事由、应付总额、已付、还差、付过几次）", "/api/v1/supplier-payables", "supplier_id、include_deleted、only_open", setOf("dispatcher"), false, listOf(
            ReadParam("supplier_id", "int", false, emptyList(), true),
            ReadParam("include_deleted", "bool", false, emptyList(), false),
            ReadParam("only_open", "bool", false, emptyList(), false),
        )),
        ReadAction("suppliers.list_payments", "付款记录（给供应商付过的每一笔：金额、日期、方式，以及它挂在哪张应付单上）", "/api/v1/supplier-payments", "supplier_id、payable_id、date_from、date_to、include_deleted", setOf("dispatcher"), false, listOf(
            ReadParam("supplier_id", "int", false, emptyList(), true),
            ReadParam("payable_id", "int", false, emptyList(), true),
            ReadParam("date_from", "date", false, emptyList(), false),
            ReadParam("date_to", "date", false, emptyList(), false),
            ReadParam("include_deleted", "bool", false, emptyList(), false),
        )),
        ReadAction("suppliers.list_suppliers", "供应商/厂商名册（含各自还欠多少、累计应付与已付）", "/api/v1/suppliers", "include_deleted", setOf("dispatcher"), false, listOf(
            ReadParam("include_deleted", "bool", false, emptyList(), false),
        )),
        ReadAction("users.list_users", "账号/人员列表（货主、司机、批发商、内部账号，可按角色与关键词筛）", "/api/v1/users", "role(shipper|driver|dispatcher)、is_member、q、skip、limit", setOf("dispatcher"), false, listOf(
            ReadParam("role", "Literal", false, listOf("shipper", "driver", "dispatcher"), false),
            ReadParam("is_member", "bool", false, emptyList(), false),
            ReadParam("q", "str", false, emptyList(), false),
            ReadParam("skip", "int", false, emptyList(), false),
            ReadParam("limit", "int", false, emptyList(), false),
        )),
        ReadAction("users.read_me", "当前登录账号自己的资料", "/api/v1/users/me", "", setOf("dispatcher", "driver", "shipper"), false, listOf(
        )),
        ReadAction("vehicles.list_vehicles", "车辆列表", "/api/v1/vehicles", "", setOf("dispatcher"), false, listOf(
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
        "expense_categories" to "开销分类",
        "expenses" to "费用",
        "freight_categories" to "运费分类",
        "freight_settlement" to "司机运费结算",
        "freight_templates" to "订单/运费模板",
        "inventory" to "库存管理",
        "ledger" to "账本",
        "notifications" to "消息通知",
        "operation_logs" to "操作日志",
        "order_products" to "订单商品行",
        "order_template_categories" to "预订单分类",
        "order_templates" to "预订单",
        "orders" to "订单/派单",
        "place_categories" to "地点分类",
        "places" to "共享地点库",
        "price_rules" to "批发商定价",
        "product_categories" to "商品分类",
        "products" to "商品管理",
        "reports" to "报表中心",
        "return_requests" to "退货申请",
        "shipper" to "地址与联系人",
        "shipper_ledger" to "我的账本",
        "stats" to "统计口径",
        "suppliers" to "供应商/应付款",
        "users" to "司机/货主/批发商/账号",
        "vehicles" to "车辆管理",
    )

    /** 某个模块下有哪些表（设置页那句说明用）。 */
    fun actionsOf(module: String): List<ReadAction> = ACTIONS.filter { it.action.startsWith(module + ".") }
}
