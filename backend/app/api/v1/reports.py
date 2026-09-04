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
from app.schemas.reports import ProductReportItem, ProductReportOut, ReportArrearsUnitItem, ReportSeriesItem, TurnoverReportOut

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
    cost_total = Decimal("0")
    total_lines = 0
    cost_covered_lines = 0
    damage_qty = 0
    damage_amount = Decimal("0")
    collected = Decimal("0")
    arrears_total = Decimal("0")
    arrears_map: dict[str, Decimal] = {}
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
        # 成本/货损（仅 cost_price_snapshot>0 的行计入；老订单无成本快照不参与毛利）
        for lp in o.order_products:
            total_lines += 1
            cost = lp.cost_price_snapshot or Decimal("0")
            if cost > 0:
                cost_covered_lines += 1
                cost_total += cost * Decimal(lp.quantity)
            dq = lp.damage_quantity or 0
            if dq > 0:
                damage_qty += dq
                damage_amount += cost * Decimal(dq) if cost > 0 else Decimal("0")
        # 资金：cash+paid=已收；arrears 未 paid=挂账未收
        if (o.payment_method or "") == "cash" and o.paid:
            collected += amount
        elif (o.payment_method or "") == "arrears" and not o.paid:
            arrears_total += amount
            uname = (o.arrears_unit_name or "").strip() or "未分配挂账单位"
            arrears_map[uname] = arrears_map.get(uname, Decimal("0")) + amount
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
    # 周期内已撤销单数（口径说明用：营业金额=已送达未撤销订单）
    cancelled_orders = db.scalar(
        select(func.count(Order.id)).where(
            Order.status == OrderStatus.CANCELLED,
            Order.cancelled_at.isnot(None),
            func.date(Order.cancelled_at) >= start,
            func.date(Order.cancelled_at) <= end,
        )
    ) or 0
    return TurnoverReportOut(
        period_label=_label(d, mode),
        total_amount=total_amount,
        total_orders=total_orders,
        total_freight=total_freight,
        avg_order=avg,
        series=series,
        cost_total=cost_total,
        total_lines=total_lines,
        cost_covered_lines=cost_covered_lines,
        damage_qty=damage_qty,
        damage_amount=damage_amount,
        collected=collected,
        arrears_total=arrears_total,
        cancelled_orders=cancelled_orders,
        arrears_units=[
            ReportArrearsUnitItem(name=k, amount=v)
            for k, v in sorted(arrears_map.items(), key=lambda kv: -kv[1])[:5]
        ],
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
    cost_total = Decimal("0")
    damage_qty = 0
    damage_amount = Decimal("0")
    total_lines = 0
    cost_covered_lines = 0
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
            total_lines += 1
            cost = lp.cost_price_snapshot or Decimal("0")
            if cost > 0:
                cost_covered_lines += 1
                cost_total += cost * Decimal(lp.quantity)
                item.cost += cost * Decimal(lp.quantity)
            dq = lp.damage_quantity or 0
            if dq > 0:
                damage_qty += dq
                item.damage_qty += dq
                amt = cost * Decimal(dq) if cost > 0 else Decimal("0")
                damage_amount += amt
                item.damage_amount += amt
    items = sorted(agg.values(), key=lambda x: -x.amount)
    return ProductReportOut(
        period_label=_label(d, mode),
        total_qty=total_qty,
        total_amount=total_amount,
        items=items,
        cost_total=cost_total,
        damage_qty=damage_qty,
        damage_amount=damage_amount,
        total_lines=total_lines,
        cost_covered_lines=cost_covered_lines,
    )