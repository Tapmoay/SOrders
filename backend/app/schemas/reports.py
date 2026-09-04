from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel


class ReportSeriesItem(BaseModel):
    label: str
    amount: Decimal = Decimal("0")
    orders: int = 0
    freight: Decimal = Decimal("0")


class ReportArrearsUnitItem(BaseModel):
    name: str
    amount: Decimal = Decimal("0")


class TurnoverReportOut(BaseModel):
    period_label: str
    total_amount: Decimal
    total_orders: int
    total_freight: Decimal
    avg_order: Decimal = Decimal("0")
    series: list[ReportSeriesItem] = []
    # ---- 报表中心 v2：成本/毛利/货损/资金/撤销 ----
    cost_total: Decimal = Decimal("0")          # 有成本快照订单行的成本合计（毛利基数）
    total_lines: int = 0                        # 订单行总数（覆盖率分母）
    cost_covered_lines: int = 0                 # cost_price_snapshot>0 的行数（覆盖率分子）
    damage_qty: int = 0                         # 货损件数合计
    damage_amount: Decimal = Decimal("0")       # 货损金额 = Σ(成本快照×货损件数)
    collected: Decimal = Decimal("0")           # 现金已收（payment_method=cash 且 paid）
    arrears_total: Decimal = Decimal("0")       # 挂账未收（payment_method=arrears 且未 paid）
    cancelled_orders: int = 0                   # 周期内已撤销订单数
    arrears_units: list[ReportArrearsUnitItem] = []   # 挂账未收按单位 TOP5


class ProductReportItem(BaseModel):
    product_name: str
    qty: int = 0
    amount: Decimal = Decimal("0")
    order_count: int = 0
    # ---- 报表中心 v2 ----
    cost: Decimal = Decimal("0")                # 该商品成本合计（有快照行）
    damage_qty: int = 0
    damage_amount: Decimal = Decimal("0")


class ProductReportOut(BaseModel):
    period_label: str
    total_qty: int = 0
    total_amount: Decimal = Decimal("0")
    items: list[ProductReportItem] = []
    # ---- 报表中心 v2 ----
    cost_total: Decimal = Decimal("0")
    damage_qty: int = 0
    damage_amount: Decimal = Decimal("0")
    total_lines: int = 0
    cost_covered_lines: int = 0