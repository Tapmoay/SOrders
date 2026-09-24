from fastapi import APIRouter

from app.api.v1 import (
    arrears,
    auth,
    cash_flows,
    vehicles,
    customers,
    driver_bills,
    driver_billing_rules,
    driver_settlements,
    expenses,
    files,
    freight_settlement,
    freight_categories,
    freight_templates,
    inventory,
    expense_categories,
    ledger,
    notifications,
    operation_logs,
    order_products,
    order_templates,
    order_template_categories,
    suppliers,
    orders,
    place_categories,
    places,
    price_rules,
    product_categories,
    products,
    reports,
    return_requests,
    shipper,
    shipper_ledger,
    stats,
    system,
    unit_conversions,
    usage,
    users,
)

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(files.router)
api_router.include_router(freight_templates.router)
# 运费分类名册（2026-09-21）：运费模板与计费规则**共用**的一套分类，见 `api/v1/freight_categories.py` 开头
api_router.include_router(freight_categories.router)
api_router.include_router(freight_settlement.router)
api_router.include_router(shipper.router)
# 批发商自己那一本账（他给下游货主核销）：与 `ledger.router`（派单员开的账）是两本账，
# 谁都不写谁 —— 见 `api/v1/shipper_ledger.py` 开头。
api_router.include_router(shipper_ledger.router)
api_router.include_router(orders.router)
# 预订单 / 订单模板（2026-09-22 用户要求：「预设好的订单，参数没有变直接下单」）。
# 它自己不生成订单 —— 真下单仍走上面那条 `orders.router`。
api_router.include_router(order_templates.router)
# 预订单分类名册（2026-09-22）：预订单页左栏那一列（用户：「左边是分类管理…右边就是订单」），
# 与商品/开销/运费分类同一套规矩，见 `api/v1/order_template_categories.py` 开头。
api_router.include_router(order_template_categories.router)
# 供应商 / 厂商档案 + 应付款（2026-09-22 用户要求：「给供应商付尾款」「采购设备」「邮费」）。
# 付款不是新表 —— 它就是 `cash_flows` 里 `biz_type=PAYMENT_SUPPLIER` 的一行，见 `api/v1/suppliers.py` 开头。
api_router.include_router(suppliers.router)
# 退货申请（2026-09-21）：货主**申请** → 派单员**实际执行**。与 `orders.router` 里那条
# `POST /orders/{id}/return`（唯一的执行路径）是两件事，见 `api/v1/return_requests.py` 开头。
api_router.include_router(return_requests.router)
api_router.include_router(places.router)
api_router.include_router(place_categories.router)
api_router.include_router(order_products.router)
api_router.include_router(products.router)
api_router.include_router(product_categories.router)
# 开销分类名册（2026-09-20）：与商品分类同一套规矩，见 `api/v1/expense_categories.py` 开头
api_router.include_router(expense_categories.router)
api_router.include_router(price_rules.router)
api_router.include_router(reports.router)
api_router.include_router(ledger.router)
api_router.include_router(arrears.router)
api_router.include_router(inventory.router)
api_router.include_router(notifications.router)
api_router.include_router(operation_logs.router)
api_router.include_router(stats.router)
api_router.include_router(customers.router)
api_router.include_router(driver_bills.router)
api_router.include_router(driver_billing_rules.router)
api_router.include_router(driver_settlements.router)
api_router.include_router(expenses.router)
api_router.include_router(cash_flows.router)
api_router.include_router(vehicles.router)
# 系统级运行期配置（测试账号的默认 AI 配置，2026-09-21）：见 `api/v1/system.py`
api_router.include_router(system.router)
api_router.include_router(usage.router)
# 单位换算（用户 2026-09-24：一车 = 8 方）—— 新表，`create_all` 自动建
api_router.include_router(unit_conversions.router)