from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field


class ShipperProductChartOut(BaseModel):
    granularity: Literal["month", "year"] = "month"
    metric: Literal["quantity", "amount"] = "quantity"
    categories: list[str] = Field(..., description="时间轴标签")
    series: list[dict[str, Any]] = Field(..., description="[{name: 商品名, data: [数值按 categories 对齐]}]")


class TopProductItem(BaseModel):
    product_name: str
    count: int
    amount: Decimal


class ShipperActivityOut(BaseModel):
    shipper_id: int
    shipper_name: str
    order_count: int
    delivered_count: int
    total_spent: Decimal
    avg_order_value: Decimal
    orders_per_week: Decimal
    top_products: list[TopProductItem]


class DrilldownOrderItem(BaseModel):
    id: int
    order_no: str
    order_date: date
    status: str
    shipper_name: str | None
    product_name: str
    quantity: int
    line_total: Decimal


class DriverPerformanceRow(BaseModel):
    driver_id: int
    driver_name: str
    completed_count: int
    on_time_rate: float | None = Field(None, description="0~1，无约定/无样本时为 null")
    avg_delivery_seconds: float | None = None
    photo_upload_rate: float = Field(..., description="0~1")
    billing_mode: str | None = Field(None, description="PIECE 计件 / SALARY 工资制")
    freight_owed: str | None = Field(None, description="计件司机待结运费(已结以外)字符串，工资制为 None")


class DriverPerformanceOut(BaseModel):
    period_label: str
    drivers: list[DriverPerformanceRow]


class ShipperPerformanceRow(BaseModel):
    shipper_id: int | None = Field(None, description="无系统账号的临时货主为 null（按 temp_shipper_name 归组）")
    shipper_name: str
    order_count: int = Field(..., description="已送达订单数")
    total_amount: Decimal = Field(..., description="订单明细金额合计（line_total 求和）")


class ShipperPerformanceOut(BaseModel):
    period_label: str
    shippers: list[ShipperPerformanceRow]


class ExceptionOrderItem(BaseModel):
    id: int
    order_no: str
    order_date: date
    status: str
    shipper_name: str | None
    driver_name: str | None
    exception_reason: str
    exception_resolution: str
    expected_deliver_before: datetime | None
    exception_resolved_at: datetime | None = None
    delivered_at: datetime | None


class StatsExportBody(BaseModel):
    date_from: date
    date_to: date
    include_shipper_chart: bool = True
    include_driver_perf: bool = True
    include_exceptions: bool = True
    chart_metric: Literal["quantity", "amount"] = "quantity"
    chart_granularity: Literal["month", "year"] = "month"