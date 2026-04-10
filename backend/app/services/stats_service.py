"""派单员看板聚合（基于订单与明细；数据量较大时可改为 SQL 聚合）。"""

from collections import defaultdict
from datetime import date, datetime, time, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.models import Order, OrderProduct, User
from app.models.enums import OrderStatus


def _end_of_order_date(od: date) -> datetime:
    return datetime.combine(od, time(23, 59, 59), tzinfo=timezone.utc)


def _on_time_delivered(o: Order) -> bool | None:
    if o.status != OrderStatus.DELIVERED or not o.delivered_at or not o.dispatched_at:
        return None
    sla = o.expected_deliver_before or _end_of_order_date(o.order_date)
    return o.delivered_at <= sla


def _delivery_seconds(o: Order) -> float | None:
    if not o.delivered_at or not o.dispatched_at:
        return None
    return (o.delivered_at - o.dispatched_at).total_seconds()


def _has_photos(o: Order) -> bool:
    u = o.delivery_photo_urls
    return bool(u and isinstance(u, list) and len(u) > 0)


def load_delivered_orders(
    db: Session,
    date_from: date,
    date_to: date,
) -> list[Order]:
    q = (
        select(Order)
        .where(Order.status == OrderStatus.DELIVERED)
        .where(Order.order_date >= date_from)
        .where(Order.order_date <= date_to)
        .options(
            selectinload(Order.order_products),
            joinedload(Order.shipper),
            joinedload(Order.driver),
        )
    )
    return list(db.scalars(q).unique().all())


def load_orders_by_delivered_at(
    db: Session,
    date_from: date,
    date_to: date,
) -> list[Order]:
    """按送达时间筛选（司机绩效）。"""
    start = datetime.combine(date_from, time.min, tzinfo=timezone.utc)
    end = datetime.combine(date_to, time(23, 59, 59), tzinfo=timezone.utc)
    q = (
        select(Order)
        .where(Order.status == OrderStatus.DELIVERED)
        .where(Order.delivered_at.is_not(None))
        .where(Order.delivered_at >= start)
        .where(Order.delivered_at <= end)
        .options(selectinload(Order.order_products), joinedload(Order.driver))
    )
    return list(db.scalars(q).unique().all())


def shipper_product_chart(
    db: Session,
    date_from: date,
    date_to: date,
    granularity: Literal["month", "year"],
    metric: Literal["quantity", "amount"],
) -> tuple[list[str], list[dict]]:
    orders = load_delivered_orders(db, date_from, date_to)
    # (period, product_name) -> accumulate
    acc: dict[tuple[str, str], Decimal] = defaultdict(lambda: Decimal("0"))
    for o in orders:
        if granularity == "month":
            period = f"{o.order_date.year}-{o.order_date.month:02d}"
        else:
            period = str(o.order_date.year)
        for line in o.order_products:
            key = (period, line.product_name_snapshot)
            if metric == "quantity":
                acc[key] += Decimal(line.quantity)
            else:
                acc[key] += line.line_total

    # top products by total metric
    product_totals: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    for (period, pname), val in acc.items():
        product_totals[pname] += val
    top_names = sorted(product_totals.keys(), key=lambda x: product_totals[x], reverse=True)[:12]

    periods = sorted({p for (p, _) in acc.keys()})
    if not periods:
        return [], []

    series = []
    for pname in top_names:
        data = [float(acc.get((per, pname), Decimal("0"))) for per in periods]
        series.append({"name": pname, "data": data})
    return periods, series


def shipper_activity(
    db: Session,
    shipper_id: int,
    date_from: date,
    date_to: date,
) -> dict:
    q = (
        select(Order)
        .where(Order.shipper_id == shipper_id)
        .where(Order.order_date >= date_from)
        .where(Order.order_date <= date_to)
        .options(selectinload(Order.order_products), joinedload(Order.shipper))
    )
    orders = list(db.scalars(q).unique().all())
    su = db.get(User, shipper_id)
    shipper_name = (su.full_name or su.phone or str(shipper_id)) if su else str(shipper_id)

    order_count = len(orders)
    delivered = [o for o in orders if o.status == OrderStatus.DELIVERED]
    delivered_count = len(delivered)
    total_spent = sum(
        (lp.line_total for o in delivered for lp in o.order_products),
        Decimal("0"),
    )
    avg_order_value = (total_spent / delivered_count) if delivered_count else Decimal("0")
    days = max((date_to - date_from).days + 1, 1)
    weeks = max(days / 7, 0.01)
    orders_per_week = (Decimal(order_count) / Decimal(str(weeks))).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )

    prod_count: dict[str, int] = defaultdict(int)
    prod_amt: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    for o in delivered:
        for lp in o.order_products:
            prod_count[lp.product_name_snapshot] += lp.quantity
            prod_amt[lp.product_name_snapshot] += lp.line_total
    top_sorted = sorted(prod_count.keys(), key=lambda x: prod_count[x], reverse=True)[:8]
    top_products = [
        {
            "product_name": n,
            "count": prod_count[n],
            "amount": prod_amt[n],
        }
        for n in top_sorted
    ]

    return {
        "shipper_id": shipper_id,
        "shipper_name": shipper_name,
        "order_count": order_count,
        "delivered_count": delivered_count,
        "total_spent": total_spent,
        "avg_order_value": avg_order_value,
        "orders_per_week": orders_per_week,
        "top_products": top_products,
    }


def product_drilldown(
    db: Session,
    product_name: str,
    date_from: date,
    date_to: date,
) -> list[dict]:
    orders = load_delivered_orders(db, date_from, date_to)
    # pre-load shipper names
    out: list[dict] = []
    for o in orders:
        if o.status != OrderStatus.DELIVERED:
            continue
        for lp in o.order_products:
            if lp.product_name_snapshot != product_name:
                continue
            sn = None
            if o.shipper:
                sn = o.shipper.full_name or o.shipper.phone
            out.append(
                {
                    "id": o.id,
                    "order_no": o.order_no,
                    "order_date": o.order_date,
                    "status": o.status.value,
                    "shipper_name": sn,
                    "product_name": lp.product_name_snapshot,
                    "quantity": lp.quantity,
                    "line_total": lp.line_total,
                }
            )
    return out


def driver_performance(
    db: Session,
    date_from: date,
    date_to: date,
) -> list[dict]:
    orders = load_orders_by_delivered_at(db, date_from, date_to)
    by_driver: dict[int, list[Order]] = defaultdict(list)
    for o in orders:
        if o.driver_id:
            by_driver[o.driver_id].append(o)

    rows = []
    for did, os in by_driver.items():
        du = db.get(User, did)
        name = (du.full_name or du.phone or str(did)) if du else str(did)
        completed = len(os)
        on_time_flags = [_on_time_delivered(x) for x in os]
        ot_valid = [x for x in on_time_flags if x is not None]
        on_time_rate = (sum(1 for x in ot_valid if x) / len(ot_valid)) if ot_valid else None

        durs = [_delivery_seconds(x) for x in os]
        durs_valid = [x for x in durs if x is not None]
        avg_sec = sum(durs_valid) / len(durs_valid) if durs_valid else None

        photo_ok = sum(1 for x in os if _has_photos(x))
        photo_rate = photo_ok / completed if completed else 0.0

        rows.append(
            {
                "driver_id": did,
                "driver_name": name,
                "completed_count": completed,
                "on_time_rate": on_time_rate,
                "avg_delivery_seconds": avg_sec,
                "photo_upload_rate": photo_rate,
            }
        )
    rows.sort(key=lambda x: x["completed_count"], reverse=True)
    return rows


def exception_orders(
    db: Session,
    date_from: date,
    date_to: date,
) -> list[dict]:
    q = (
        select(Order)
        .where(Order.is_exception.is_(True))
        .where(Order.order_date >= date_from)
        .where(Order.order_date <= date_to)
        .options(joinedload(Order.shipper), joinedload(Order.driver))
        .order_by(Order.id.desc())
    )
    orders = list(db.scalars(q).unique().all())
    out = []
    for o in orders:
        sn = None
        if o.shipper:
            sn = o.shipper.full_name or o.shipper.phone
        dn = None
        if o.driver:
            dn = o.driver.full_name or o.driver.phone
        out.append(
            {
                "id": o.id,
                "order_no": o.order_no,
                "order_date": o.order_date,
                "status": o.status.value,
                "shipper_name": sn,
                "driver_name": dn,
                "exception_reason": o.exception_reason,
                "exception_resolution": o.exception_resolution,
                "expected_deliver_before": o.expected_deliver_before,
                "delivered_at": o.delivered_at,
            }
        )
    return out
