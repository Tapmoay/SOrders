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
    freight_templates,
    inventory,
    ledger,
    notifications,
    operation_logs,
    order_products,
    orders,
    places,
    price_rules,
    product_categories,
    products,
    reports,
    shipper,
    stats,
    users,
)

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(files.router)
api_router.include_router(freight_templates.router)
api_router.include_router(freight_settlement.router)
api_router.include_router(shipper.router)
api_router.include_router(orders.router)
api_router.include_router(places.router)
api_router.include_router(order_products.router)
api_router.include_router(products.router)
api_router.include_router(product_categories.router)
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