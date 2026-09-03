"""报表（派单员）：营业额/商品明细 按日/周/月聚合，供折线图与条形图使用。"""

from datetime import date, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sqlalchemy.orm import selectinload

from app.core.rbac import Permission
from app.database import get_db
from app.deps import require_permission
from app.models import Order, OrderProduct, User
from app.models.enums import OrderStatus
from app.schemas.reports import ProductReportItem, ProductReportOut, ReportSeriesItem, TurnoverReportOut

router = APIRouter(prefix="/reports", tags=["reports"])


def _window(mode: str, anchor: date) -> tuple[date, date]:
    d = anchor
    if mode == "week":
        start = d - timedelta(days=d.weekday())
        return start, start + timedelta(days=6)
    if mode == "month":
        return d.replace(day=1), (d.replace(day=1) + timedelta(days=32)).replace(day=1)
    return d, d


def _label(d: date, mode: str) -> str:
    if mode == "week":
        start = d - timedelta(days=d.weekday())
        return f"{start.month}-{start.day}~{start + timedelta(days=6):%m-%d}"
    if mode == "month":
        return f"{d.year}-{d.month:02d}月"
    return f"{d.month}-{d.day}"


def _range_dates(start: date, end: date) -> list[date]:
    out, cur = [], start
    while cur <= end:
        out.append(cur)
        cur += timedelta(days=1)
    return out


@router.get("/turnover", response_model=TurnoverReportOut)
def turnover_report(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.ORDER_DISPATCH)),
    mode: str = Query("day", pattern="^(day|week|month)$"),
    anchor: str = Query(..., alias="date", description="YYYY-MM-DD 锚点日期"),
) -> TurnoverReportOut:
    d = date.fromisoformat(anchor)
    start, end = _window(mode, d)
    days = _range_dates(start, end)
    q = (
        select(Order)
        .options(selectinload(Order.order_products))
        .where(
            Order.status == OrderStatus.DELIVERED,
            Order.delivered_at.isnot(None),
        )
        .order_by(Order.delivered_at)
    )
    orders = list(db.scalars(q))
    day_map: dict[str, ReportSeriesItem] = {}
    hour_amount: dict[int, Decimal] = {}
    hour_orders: dict[int, int] = {}
    total_amount = Decimal("0")
    total_freight = Decimal("0")
    total_orders = 0
    for o in orders:
        ds = o.delivered_at.date()
        if ds < start or ds > end:
            continue
        key = f"{ds.month}-{ds.day}"
        amount = sum((lp.line_total or Decimal("0")) for lp in o.order_products)
        item = day_map.setdefault(key, ReportSeriesItem(label=key))
        item.amount += amount
        item.orders += 1
        item.freight += o.freight_fee or Decimal("0")
        h = o.delivered_at.hour
        hour_amount[h] = hour_amount.get(h, Decimal("0")) + amount
        hour_orders[h] = hour_orders.get(h, 0) + 1
        total_amount += amount
        total_freight += o.freight_fee or Decimal("0")
        total_orders += 1
    if mode == "day":
        # 按日统计图：x 轴=时间（按实际送达时刻聚合），仅显示有订单的小时，无订单时段不展示
        series = [
            ReportSeriesItem(
                label=f"{h:02d}时",
                amount=hour_amount.get(h, Decimal("0")),
                orders=hour_orders.get(h, 0),
            )
            for h in sorted(hour_orders)
        ]
    else:
        series = [day_map.get(f"{x.month}-{x.day}", ReportSeriesItem(label=f"{x.month}-{x.day}")) for x in days]
    avg = (total_amount / total_orders) if total_orders else Decimal("0")
    return TurnoverReportOut(
        period_label=_label(d, mode),
        total_amount=total_amount,
        total_orders=total_orders,
        total_freight=total_freight,
        avg_order=avg,
        series=series,
    )


@router.get("/products", response_model=ProductReportOut)
def product_report(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.ORDER_DISPATCH)),
    mode: str = Query("day", pattern="^(day|week|month)$"),
    anchor: str = Query(..., alias="date", description="YYYY-MM-DD 锚点日期"),
) -> ProductReportOut:
    d = date.fromisoformat(anchor)
    start, end = _window(mode, d)
    q = (
        select(Order)
        .options(selectinload(Order.order_products))
        .where(Order.status == OrderStatus.DELIVERED, Order.delivered_at.isnot(None))
    )
    agg: dict[str, ProductReportItem] = {}
    total_qty = 0
    total_amount = Decimal("0")
    for o in db.scalars(q):
        if o.delivered_at.date() < start or o.delivered_at.date() > end:
            continue
        for lp in o.order_products:
            name = lp.product_name_snapshot or "未命名商品"
            item = agg.setdefault(name, ProductReportItem(product_name=name))
            item.qty += lp.quantity
            item.amount += lp.line_total or Decimal("0")
            item.order_count += 1
            total_qty += lp.quantity
            total_amount += lp.line_total or Decimal("0")
    items = sorted(agg.values(), key=lambda x: -x.amount)
    return ProductReportOut(
        period_label=_label(d, mode),
        total_qty=total_qty,
        total_amount=total_amount,
        items=items,
    )