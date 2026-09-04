"""报表（派单员）：营业额/商品明细 按日/周/月聚合，供折线图与条形图使用。"""

from datetime import date, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
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


def load_delivered(db: Session) -> list[Order]:
    """全部已送达订单（按送达时间排序）；由各报表按窗口过滤，减少重复查询。"""
    return list(
        db.scalars(
            select(Order)
            .options(selectinload(Order.order_products))
            .where(
                Order.status == OrderStatus.DELIVERED,
                Order.delivered_at.isnot(None),
            )
            .order_by(Order.delivered_at)
        )
    )


def build_turnover(db: Session, mode: str, anchor: date) -> dict:
    """营业纵览聚合（含成本/毛利/货损/资金/撤销/挂账单位），供接口与导出复用。"""
    d = anchor
    start, end = _window(mode, anchor)
    days = _range_dates(start, end)
    orders = load_delivered(db)
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
        if (o.payment_method or "") == "cash" and o.paid:
            collected += amount
        elif (o.payment_method or "") == "arrears" and not o.paid:
            arrears_total += amount
            uname = (o.arrears_unit_name or "").strip() or "未分配挂账单位"
            arrears_map[uname] = arrears_map.get(uname, Decimal("0")) + amount
    if mode == "day":
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
    cancelled_orders = db.scalar(
        select(func.count(Order.id)).where(
            Order.status == OrderStatus.CANCELLED,
            Order.cancelled_at.isnot(None),
            func.date(Order.cancelled_at) >= start,
            func.date(Order.cancelled_at) <= end,
        )
    ) or 0
    return {
        "period_label": _label(d, mode),
        "total_amount": total_amount,
        "total_orders": total_orders,
        "total_freight": total_freight,
        "avg_order": avg,
        "series": series,
        "cost_total": cost_total,
        "total_lines": total_lines,
        "cost_covered_lines": cost_covered_lines,
        "damage_qty": damage_qty,
        "damage_amount": damage_amount,
        "collected": collected,
        "arrears_total": arrears_total,
        "cancelled_orders": cancelled_orders,
        "arrears_units": [
            ReportArrearsUnitItem(name=k, amount=v)
            for k, v in sorted(arrears_map.items(), key=lambda kv: -kv[1])[:5]
        ],
        "_window": (start, end),
    }


def build_products(db: Session, mode: str, anchor: date) -> dict:
    """商品经营聚合（含成本/货损），供接口与导出复用。"""
    d = anchor
    start, end = _window(mode, anchor)
    agg: dict[str, ProductReportItem] = {}
    total_qty = 0
    total_amount = Decimal("0")
    cost_total = Decimal("0")
    damage_qty = 0
    damage_amount = Decimal("0")
    total_lines = 0
    cost_covered_lines = 0
    for o in load_delivered(db):
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
    return {
        "period_label": _label(d, mode),
        "total_qty": total_qty,
        "total_amount": total_amount,
        "items": items,
        "cost_total": cost_total,
        "damage_qty": damage_qty,
        "damage_amount": damage_amount,
        "total_lines": total_lines,
        "cost_covered_lines": cost_covered_lines,
        "_window": (start, end),
    }


@router.get("/turnover", response_model=TurnoverReportOut)
def turnover_report(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.ORDER_DISPATCH)),
    mode: str = Query("day", pattern="^(day|week|month)$"),
    anchor: str = Query(..., alias="date", description="YYYY-MM-DD 锚点日期"),
) -> TurnoverReportOut:
    d = date.fromisoformat(anchor)
    data = build_turnover(db, mode, d)
    data.pop("_window", None)
    return TurnoverReportOut(**{**data, "period_label": data["period_label"]})


@router.get("/products", response_model=ProductReportOut)
def product_report(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.ORDER_DISPATCH)),
    mode: str = Query("day", pattern="^(day|week|month)$"),
    anchor: str = Query(..., alias="date", description="YYYY-MM-DD 锚点日期"),
) -> ProductReportOut:
    d = date.fromisoformat(anchor)
    data = build_products(db, mode, d)
    data.pop("_window", None)
    return ProductReportOut(**data)


def build_arrears_summary(db: Session, start: date, end: date) -> list[dict]:
    """挂账单位欠款汇总（按未付挂账订单聚合），供客户经营页与导出复用。"""
    from app.models import CashFlow

    rows = list(
        db.scalars(
            select(Order)
            .options(selectinload(Order.order_products))
            .where(
                Order.status == OrderStatus.DELIVERED,
                Order.delivered_at.isnot(None),
                Order.payment_method == "arrears",
                Order.paid.is_(False),
            )
        )
    )
    unit_map: dict[str, dict] = {}
    for o in rows:
        ds = o.delivered_at.date()
        if ds < start or ds > end:
            continue
        name = (o.arrears_unit_name or "").strip() or "未分配挂账单位"
        g = unit_map.setdefault(name, {"name": name, "count": 0, "amount": Decimal("0")})
        amount = sum((lp.line_total or Decimal("0")) for lp in o.order_products)
        g["count"] += 1
        g["amount"] += amount
    return sorted(unit_map.values(), key=lambda x: -x["amount"])


@router.get("/arrears-summary")
def arrears_summary(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.ORDER_DISPATCH)),
    date_from: str = Query(..., description="YYYY-MM-DD"),
    date_to: str = Query(..., description="YYYY-MM-DD"),
) -> list[dict]:
    start = date.fromisoformat(date_from)
    end = date.fromisoformat(date_to)
    return build_arrears_summary(db, start, end)


def _xlsx_sheet(ws, title_rows: list[list], header: list, rows: list[list]):
    ws.append([title_rows[0] if title_rows else ""])
    if len(title_rows) > 1:
        ws.append(title_rows[1])
    ws.append(header)
    for r in rows:
        ws.append(r)


@router.get("/export")
def export_report(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.ORDER_DISPATCH)),
    kind: str = Query(..., pattern="^(turnover|products|drivers|customers|finance|audit)$"),
    mode: str = Query("day", pattern="^(day|week|month)$"),
    anchor: str = Query(..., alias="date", description="YYYY-MM-DD 锚点日期"),
    date_from: str | None = Query(None, description="YYYY-MM-DD（finance/customers 可用，优先于 mode+anchor）"),
    date_to: str | None = Query(None, description="YYYY-MM-DD"),
) -> StreamingResponse:
    """报表 Excel 导出（内存流 xlsx）。"""
    from io import BytesIO
    from openpyxl import Workbook

    from app.models import CashFlow, DriverSettlement, Expense, Ledger
    from app.models.enums import SettlementStatus

    d = date.fromisoformat(anchor)
    wb = Workbook()

    def next_sheet(title: str):
        if wb.active.title == "Sheet" and wb.active.max_row == 1 and wb.active.max_column == 1:
            ws = wb.active
            ws.title = title
            return ws
        return wb.create_sheet(title)

    if kind == "turnover":
        data = build_turnover(db, mode, d)
        ws = next_sheet("营业纵览")
        ws.append(["营业纵览", f"{mode} {_label(d, mode)}", f"金额口径：已送达未撤销"])
        ws.append(["营业金额", str(data["total_amount"]), "订单数", data["total_orders"], "单均价", str(data["avg_order"])])
        ws.append(["司机运费支出", str(data["total_freight"]), "商品毛利(仅计成本快照行)", str(data["total_amount"] - data["cost_total"]), f"成本覆盖率 {data['cost_covered_lines']}/{data['total_lines']}"])
        ws.append(["货损件数", data["damage_qty"], "货损金额", str(data["damage_amount"]), "现金已收", str(data["collected"])])
        ws.append(["挂账未收", str(data["arrears_total"]), "已撤销订单", data["cancelled_orders"]])
        ws.append([])
        ws.append(["时间", "单数", "金额", "运费"])
        for s in data["series"]:
            ws.append([s.label, s.orders, str(s.amount), str(s.freight)])
        ws.append([])
        ws.append(["挂账未收单位TOP"])
        for u in data["arrears_units"]:
            ws.append([u.name, str(u.amount)])
    elif kind == "products":
        data = build_products(db, mode, d)
        ws = next_sheet("商品经营")
        ws.append(["商品经营", f"{mode} {_label(d, mode)}"])
        ws.append(["销售总额", str(data["total_amount"]), "总件数", data["total_qty"], "商品毛利", str(data["total_amount"] - data["cost_total"])])
        ws.append(["货损件数", data["damage_qty"], "货损金额", str(data["damage_amount"]), f"成本覆盖率 {data['cost_covered_lines']}/{data['total_lines']}"])
        ws.append([])
        ws.append(["商品", "件数", "单数", "金额", "毛利", "货损件数", "货损金额"])
        for it in data["items"]:
            ws.append([it.product_name, it.qty, it.order_count, str(it.amount), str(it.amount - it.cost), it.damage_qty, str(it.damage_amount)])
    elif kind in ("drivers", "customers", "finance", "audit"):
        # 需要 date_from/date_to：缺省用窗口
        if date_from and date_to:
            s = date.fromisoformat(date_from)
            e = date.fromisoformat(date_to)
        else:
            s, e = _window(mode, d)

        if kind == "drivers":
            from app.models import User

            ws = next_sheet("司机绩效")
            orders = [o for o in load_delivered(db) if s <= o.delivered_at.date() <= e]
            by_driver: dict[int, list[Order]] = {}
            for o in orders:
                if o.driver_id:
                    by_driver.setdefault(o.driver_id, []).append(o)
            ws.append(["司机绩效", f"{s} ~ {e}"])
            ws.append(["司机", "完成单量", "准时率", "拍照率", "平均送达分钟", "计费方式", "待结运费"])
            for did, os in sorted(by_driver.items(), key=lambda kv: -len(kv[1])):
                du = db.get(User, did)
                name = (du.full_name or du.phone or str(did)) if du else str(did)
                ot_valid = [1 for x in os if x.delivered_at and x.expected_deliver_before and x.delivered_at <= x.expected_deliver_before]
                ot_total = [x for x in os if x.delivered_at and x.expected_deliver_before]
                ot = (sum(ot_valid) / len(ot_total)) if ot_total else ""
                photo_ok = sum(1 for x in os if x.delivery_photo_urls)
                mode_snap = ""
                fre = ""
                for x in os:
                    if x.driver_billing_mode_snapshot:
                        mode_snap = x.driver_billing_mode_snapshot
                    if x.freight_fee is not None:
                        fre = str(x.freight_fee)
                        break
                ws.append([name, len(os), ot, (photo_ok / len(os)) if os else "", "", mode_snap, fre])
        elif kind == "customers":
            from app.models import User

            ws = next_sheet("客户经营")
            ws.append(["客户账汇总", f"{s} ~ {e}"])
            # 货主账/批发商账（复用 ledger accounts 逻辑的简化：按流水聚合）
            rows = list(db.scalars(select(Ledger)))
            users: dict[int, User | None] = {}
            shipper_buckets: dict[int, dict] = {}
            member_buckets: dict[int, dict] = {}
            temp_bucket: dict[str, dict] = {}
            for r in rows:
                if r.entry_date < s or r.entry_date > e:
                    continue
                if r.shipper_id is not None:
                    if r.shipper_id not in users:
                        u = db.get(User, r.shipper_id)
                        users[r.shipper_id] = u
                    u = users[r.shipper_id]
                    b = (member_buckets if (u is not None and getattr(u, "is_member", False)) else shipper_buckets).setdefault(
                        r.shipper_id, {"name": (u.full_name or u.phone or f"货主#{r.shipper_id}") if u else f"货主#{r.shipper_id}", "count": 0, "total": Decimal("0")}
                    )
                else:
                    name = (r.temp_shipper_name or "").strip() or "临时货主"
                    b = temp_bucket.setdefault(name, {"name": name, "count": 0, "total": Decimal("0")})
                b["count"] += 1
                b["total"] += r.total or Decimal("0")
            ws.append(["类别", "客户", "笔数", "总额"])
            for b in sorted(shipper_buckets.values(), key=lambda x: -x["total"]):
                ws.append(["货主", b["name"], b["count"], str(b["total"])])
            for b in sorted(temp_bucket.values(), key=lambda x: -x["total"]):
                ws.append(["临时货主", b["name"], b["count"], str(b["total"])])
            for b in sorted(member_buckets.values(), key=lambda x: -x["total"]):
                ws.append(["批发商", b["name"], b["count"], str(b["total"])])
            ws.append([])
            ws.append(["挂账未收 TOP"])
            ws.append(["单位", "笔数", "金额"])
            for g in build_arrears_summary(db, s, e):
                ws.append([g["name"], g["count"], str(g["amount"])])
        elif kind == "finance":
            ws = next_sheet("资金收支")
            flows = list(
                db.scalars(
                    select(CashFlow)
                    .where(CashFlow.flow_date >= s, CashFlow.flow_date <= e)
                    .order_by(CashFlow.flow_date.desc())
                )
            )
            income = sum(f.amount for f in flows if f.direction == "IN")
            expense = sum(f.amount for f in flows if f.direction == "OUT")
            ws.append(["资金收支", f"{s} ~ {e}"])
            ws.append(["流入", str(income), "流出", str(expense), "净额", str(income - expense)])
            ws.append([])
            ws.append(["日期", "方向", "金额", "对象", "渠道", "类型", "备注"])
            for f in flows:
                ws.append([f.flow_date.isoformat(), "收入" if f.direction == "IN" else "支出", str(f.amount), f.party_name or "", f.channel, f.biz_type, f.note])
            ws.append([])
            ws.append(["开销分类"])
            ws.append(["分类", "金额"])
            exp_rows = list(db.scalars(select(Expense).where(Expense.exp_date >= s, Expense.exp_date <= e)))
            cat_map: dict[str, Decimal] = {}
            for x in exp_rows:
                cat_map[x.category] = cat_map.get(x.category, Decimal("0")) + x.amount
            for cat, amt in sorted(cat_map.items(), key=lambda kv: -kv[1]):
                ws.append([cat, str(amt)])
        elif kind == "audit":
            from app.models import OperationLog

            ws = next_sheet("异常与审计")
            from app.services import stats_service
            ex = stats_service.exception_orders(db, s, e)
            ws.append(["异常订单", f"{s} ~ {e}"])
            ws.append(["订单号", "货主", "司机", "异常原因", "处理结果", "解决时间"])
            for o in ex:
                ws.append([
                    o["order_no"], o["shipper_name"] or "", o["driver_name"] or "",
                    o["exception_reason"], o["exception_resolution"],
                    o["exception_resolved_at"].isoformat() if o["exception_resolved_at"] else "",
                ])
            ws.append([])
            ws.append(["敏感操作日志"])
            logs = list(db.scalars(select(OperationLog).order_by(OperationLog.id.desc()).limit(200)))
            ws.append(["时间", "操作", "内容"])
            for log in logs:
                ws.append([log.created_at.isoformat() if log.created_at else "", log.action, log.change_content or ""])

    buf = BytesIO()
    wb.save(buf)
    fn = f"{kind}-report-{anchor}.xlsx"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{fn}"'},
    )