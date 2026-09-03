from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel


class ReportSeriesItem(BaseModel):
    label: str
    amount: Decimal = Decimal("0")
    orders: int = 0
    freight: Decimal = Decimal("0")


class TurnoverReportOut(BaseModel):
    period_label: str
    total_amount: Decimal
    total_orders: int
    total_freight: Decimal
    avg_order: Decimal = Decimal("0")
    series: list[ReportSeriesItem] = []


class ProductReportItem(BaseModel):
    product_name: str
    qty: int = 0
    amount: Decimal = Decimal("0")
    order_count: int = 0


class ProductReportOut(BaseModel):
    period_label: str
    total_qty: int = 0
    total_amount: Decimal = Decimal("0")
    items: list[ProductReportItem] = []
