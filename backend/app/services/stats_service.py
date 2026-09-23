"""派单员看板聚合（基于订单与明细；数据量较大时可改为 SQL 聚合）。"""

from collections import defaultdict
from datetime import date, datetime, timedelta, time, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.core.business_time import business_day_start_utc, business_range_utc
from app.models import DriverSettlement, Order, OrderProduct, User
from app.models.enums import OrderStatus, SettlementStatus
from app.services.driver_pay import has_per_order_pay, pay_for_order, snapshot_mode


def _end_of_order_date(od: date) -> datetime:
    """下单日**当天的当地日末**（转成库里那个 UTC naive 口径）。

    ⛔ 原来是 `datetime.combine(od, time(23,59,59), tzinfo=timezone.utc)` —— 那是**UTC 日末**，
    而 `order_date` 是**业务当地日**（`business_today`）：两者差 8 小时，于是"当天送达"的兜底
    SLA 实际给到了**当地次日 07:59:59**，每天白送 8 小时宽限。
    本机实测（356 张已送达单、100% 走这条兜底）：准时率 **82.3%**，按当地日末算只有 **30.9%**
    （差 183 单）—— 而这个数字直接进司机绩效与导出（2026-09-23 第 18 轮并行渗透 A2-1 抓到）。

    修法与全项目其它窗口同源：`business_day_start_utc(次日)` 就是当地日末的 UTC 时刻。
    """
    return business_day_start_utc(od + timedelta(days=1))


def _on_time_delivered(o: Order) -> bool | None:
    if o.status != OrderStatus.DELIVERED or not o.delivered_at or not o.dispatched_at:
        return None
    sla = o.expected_deliver_before or _end_of_order_date(o.order_date)
    if sla.tzinfo is not None:
        sla = sla.replace(tzinfo=None)
    return o.delivered_at.replace(tzinfo=None) <= sla


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
        # 隔离区（软删）的单不算数：用户删掉一张错单，报表上的数字必须跟着少
        .where(Order.deleted_at.is_(None))
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
    """按送达时间筛选（司机绩效）。

    ⚠️ 区间是**业务当地日**，要换算成 UTC 再去比（2026-09-19 审计 R12-M11）：
    原来把当地日期直接当 UTC 用（`datetime.combine(d, time.min, tzinfo=utc)`），
    于是东八区当地 00:00~08:00 送达的单被排除在"今天"之外 ——
    绩效页少算一截，而账面上没有任何异常。
    """
    start, end_exclusive = business_range_utc(date_from, date_to)
    q = (
        select(Order)
        .where(Order.status == OrderStatus.DELIVERED)
        .where(Order.delivered_at.is_not(None))
        .where(Order.delivered_at >= start)
        .where(Order.delivered_at < end_exclusive)
        # 同上：软删的单不进司机绩效
        .where(Order.deleted_at.is_(None))
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
        # 软删的单不进"货主活跃度"（用户已经把它删了，不该还算他下过这单）
        .where(Order.deleted_at.is_(None))
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

        # 计费方式：**只有一处实现**（`driver_pay.snapshot_mode`，2026-09-19 审计第十七轮）。
        # ⛔ 原来先读 `users.billing_mode`、只有它为空才回落订单快照 —— 于是：
        #    给一个 `billing_mode='SALARY'` 的司机挂上"每单 300 + 运费 5%"的计费规则
        #    （车型对上、能挂上），新单照出账单、结算页照列出应得、结算单照收，
        #    而**绩效与导出仍然说他是工资制、待结运费印"—"**（同一件事四句话）。
        #    而"按不按单拿钱"的判据在 `snapshot_mode` 里已经写过一次（挂了规则看规则，
        #    没挂规则看车型+模式），这里再抄一遍必然走散。
        #
        # ⚠️ 也不许"从窗口里的订单快照里随便取一个"：同一个窗口里他可能既有工资制时期的单、
        #    又有挂上规则之后的单，取集合里任意一个都是**掷骰子**（实测：先跑一个工资制司机
        #    的用例、再跑挂规则的用例，同一个断言时绿时红）。这里只答"他**现在**怎么算钱"，
        #    历史单归历史单；而"有没有按单应付"由**每张单自己**的 `has_per_order_pay` 判。
        du_billing = (snapshot_mode(du) if du is not None else "").upper()
        has_piece_orders = any(has_per_order_pay(ode) for ode in os)
        # 计件司机：应结 = Σ**按规则算出来的**应付；已结 = 该司机已确认结算单(PAID)金额合计
        #
        # ⚠️ v3.36 起"应结"不再等于 Σ freight_fee：司机可能挂计费规则（每单固定/运费提成/商品提成），
        #    所以和账单、结算页共用 `pay_for_order` 一处实现。
        #    顺带修掉一个老口径不一致：这里原来把该司机**所有**已送达单的运费都算进去，
        #    而结算页是按**每张单的快照**筛的——他中途从工资制转成计件时，两边金额就对不上。
        freight_owed = None
        if du_billing == "PIECE" or has_piece_orders:
            total_freight = sum(
                (pay_for_order(ode).total for ode in os if has_per_order_pay(ode)), Decimal("0")
            )
            settled = db.scalar(
                select(func.coalesce(func.sum(DriverSettlement.amount), 0)).where(
                    DriverSettlement.driver_id == did,
                    DriverSettlement.status == SettlementStatus.PAID,
                )
            ) or Decimal("0")
            owed = total_freight - settled
            freight_owed = str(max(owed, Decimal("0")))

        rows.append(
            {
                "driver_id": did,
                "driver_name": name,
                "completed_count": completed,
                "on_time_rate": on_time_rate,
                "avg_delivery_seconds": avg_sec,
                "photo_upload_rate": photo_rate,
                "billing_mode": du_billing or None,
                "freight_owed": freight_owed,
            }
        )
    rows.sort(key=lambda x: x["completed_count"], reverse=True)
    return rows


def shipper_performance(
    db: Session,
    date_from: date,
    date_to: date,
) -> list[dict]:
    """按货主聚合订单数与订单金额（口径同 load_delivered_orders：status=DELIVERED 且 order_date 在区间内）。
    无系统账号的货主（orders.shipper_id IS NULL）按 temp_shipper_name 归组，不丢单。"""
    orders = load_delivered_orders(db, date_from, date_to)
    by_shipper: dict[tuple[str, int | str], list[Order]] = defaultdict(list)
    for o in orders:
        if o.shipper_id is not None:
            by_shipper[("u", o.shipper_id)].append(o)
        else:
            by_shipper[("t", (o.temp_shipper_name or "").strip() or "临时货主")].append(o)

    rows = []
    for key, os in by_shipper.items():
        kind, k = key
        if kind == "u":
            sid: int | None = int(k)
            su = os[0].shipper or db.get(User, sid)
            name = (su.full_name or su.phone or f"货主#{sid}") if su else f"货主#{sid}"
        else:
            sid = None
            name = str(k)
        total_amount = sum(
            (lp.line_total for o in os for lp in o.order_products),
            Decimal("0"),
        )
        rows.append(
            {
                "shipper_id": sid,
                "shipper_name": name,
                "order_count": len(os),
                "total_amount": total_amount,
            }
        )
    rows.sort(key=lambda x: x["order_count"], reverse=True)
    return rows


def auto_exception_reason(o, now):
    """自动异常规则：任何环节出问题都会被标记。
    返回原因字符串（不满足返回 None）；已解决的订单不再自动复现。"""
    if o.exception_resolved_at is not None:
        return None
    if o.status == OrderStatus.CANCELLED:
        return "已撤销/撤回订单"
    if o.status == OrderStatus.PENDING_DISPATCH:
        ct = o.created_at or o.updated_at
        if ct is not None and now - ct > timedelta(hours=4):
            return "待派超时（超过4小时未派单）"
        return None
    if o.status in (OrderStatus.DISPATCHED, OrderStatus.ACCEPTED):
        if o.expected_deliver_before is not None and o.expected_deliver_before < now:
            return "超时未送（超过预计送达时间）"
        return None
    if o.status == OrderStatus.DELIVERED:
        if o.expected_deliver_before is not None and o.delivered_at is not None and o.delivered_at > o.expected_deliver_before:
            return "逾期送达（超过预计送达时间）"
        return None
    return None

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
        # 隔离区里的单不再显示在异常列表（派单员已经删了它）
        .where(Order.deleted_at.is_(None))
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
                "exception_resolved_at": o.exception_resolved_at,
            }
        )
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    auto_q = (
        select(Order)
        .where(Order.is_exception.is_(False))
        .where(Order.order_date >= date_from)
        .where(Order.order_date <= date_to)
        # 隔离区里的单不该被自动判成"超时未派"之类的异常（用户已经删了它）
        .where(Order.deleted_at.is_(None))
        .options(joinedload(Order.shipper), joinedload(Order.driver))
    )
    seen = {o["id"] for o in out}
    for o in db.scalars(auto_q).unique().all():
        if o.id in seen:
            continue
        reason = auto_exception_reason(o, now)
        if not reason:
            continue
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
                "exception_reason": reason,
                "exception_resolution": "",
                "expected_deliver_before": o.expected_deliver_before,
                "delivered_at": o.delivered_at,
                "exception_resolved_at": None,
            }
        )
    out.sort(key=lambda x: x["id"], reverse=True)
    return out