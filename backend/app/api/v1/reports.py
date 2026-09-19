"""报表（派单员）：营业额/商品明细 按日/周/月聚合，供折线图与条形图使用。"""

from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sqlalchemy.orm import selectinload

from app.core.business_time import business_date, business_local, business_range_utc
from app.services.ledger_scope import visible_ledger_select
from app.core.rbac import Permission
from app.database import get_db
from app.deps import require_permission
from app.models import Order, OrderProduct, User
from app.models.enums import OrderStatus
from app.schemas.reports import ProductReportItem, ProductReportOut, ReportArrearsUnitItem, ReportSeriesItem, TurnoverReportOut
from app.services.driver_pay import has_per_order_pay, pay_for_order

router = APIRouter(prefix="/reports", tags=["reports"])


def _window(mode: str, anchor: date) -> tuple[date, date]:
    """[mode] 对应的时间窗口，**两端都是闭区间里的最后一天**。

    ⚠️ 月窗口的上界以前是"下月 1 日"（`day=1 + 32 天 → day=1`），而调用方用的是
    **闭区间** `ds <= end`（见 `build_turnover`），于是**下个月 1 号的单会被算进本月**。
    报表上的表现很隐蔽：本月最后一天的日报是对的，月报却多了一天的数据。
    现在统一返回"本月最后一天"，与周/日两种模式一致。
    """
    d = anchor
    if mode == "week":
        start = d - timedelta(days=d.weekday())
        return start, start + timedelta(days=6)
    if mode == "month":
        first = d.replace(day=1)
        return first, (first + timedelta(days=32)).replace(day=1) - timedelta(days=1)
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
    """全部已送达订单（按送达时间排序）；由各报表按窗口过滤，减少重复查询。

    ### 为什么必须排掉软删（隔离区）的单
    `DELETE /orders/{id}` 是**伪装删除**（进隔离区 30 天，可恢复），用户界面上已经看不到了。
    而报表这边以前**没有这个过滤**——只 grep 过 `deleted_at`：
    全后端只有 `orders.py` 与 `data_retention.py` 用到了它。
    后果是"删掉的那张单还在营业额、毛利、货损、司机应付里"：
    用户删掉一张错单，报表上的数字**一分都不减**，而他会以为删干净了。
    """
    return list(
        db.scalars(
            select(Order)
            .options(selectinload(Order.order_products))
            .where(
                Order.status == OrderStatus.DELIVERED,
                Order.delivered_at.isnot(None),
                # 隔离区里的单不算数（列可能不存在于极老的库里时由 schema_bootstrap 补齐）
                Order.deleted_at.is_(None),
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
    cost_covered_amount = Decimal("0")
    total_lines = 0
    cost_covered_lines = 0
    damage_qty = 0
    damage_amount = Decimal("0")
    collected = Decimal("0")
    arrears_total = Decimal("0")
    arrears_map: dict[str, Decimal] = {}
    for o in orders:
        # ⚠️ 按**业务当地日**分桶（2026-09-19 审计 R12-M11）：`delivered_at` 存的是 UTC，
        #    直接用 `.date()` 会让东八区当地 00:00~08:00 送达的单落进**前一天**
        #    ——"早上看今天的日报是 0"就是这么来的，而两个页面都不报错。
        ds = business_date(o.delivered_at)
        if ds is None or ds < start or ds > end:
            continue
        key = f"{ds.month}-{ds.day}"
        amount = sum((lp.line_total or Decimal("0")) for lp in o.order_products)
        item = day_map.setdefault(key, ReportSeriesItem(label=key))
        item.amount += amount
        item.orders += 1
        # ⚠️ 「司机运费支出」= **司机应得的钱**，不是订单上那个运费（2026-09-19 审计 R12-M2）：
        #    v3.36 起"司机拿多少"由计费规则决定（每单固定／运费提成／商品金额提成／工资+提成），
        #    而 `orders.freight_fee` 只是**提成基数**。原来这里直接累加它，于是同一个词
        #    在「营业纵览」和「司机运费结算」页是两个数（同一天实测：47870.00 vs 24770.00，
        #    虚高 93%），而两个页面都不报错——老板照这一格判断车费成本会系统性高估。
        #    口径现在与账单/结算页/司机绩效导出**同源**：`pay_for_order` 一处实现。
        pay = pay_for_order(o).total if has_per_order_pay(o) else Decimal("0")
        item.freight += pay
        # ⚠️ 小时桶也按**业务当地时刻**（2026-09-19 审计 R13-R3）：`delivered_at` 是 UTC，
        #    直接取 `.hour` 会把当地凌晨 0~3 点送达的单标成「16~18时」——
        #    日报的时段分布整段错位，而数字看起来很正常。
        h = business_local(o.delivered_at).hour
        hour_amount[h] = hour_amount.get(h, Decimal("0")) + amount
        hour_orders[h] = hour_orders.get(h, 0) + 1
        total_amount += amount
        total_freight += pay
        total_orders += 1
        for lp in o.order_products:
            total_lines += 1
            cost = lp.cost_price_snapshot or Decimal("0")
            if cost > 0:
                cost_covered_lines += 1
                cost_total += cost * Decimal(lp.quantity)
                # 收入侧**只收有成本快照的行**（见 schemas/reports.py 里 cost_covered_amount 的注释）：
                # 不这么写，没快照的行会以"0 成本"全额变成毛利。
                cost_covered_amount += lp.line_total or Decimal("0")
            dq = lp.damage_quantity or 0
            if dq > 0:
                damage_qty += dq
                damage_amount += cost * Decimal(dq) if cost > 0 else Decimal("0")
        # ⚠️ 这笔钱**只有两个去处**：已收 / 还没收（挂账）。必须写成完整划分。
        #
        # 原来是两条带条件的判据（`cash 且已收` / `arrears 且未收`），于是
        # **挂账结清**（收款方式 `arrears_settle`：payment_method 还是 arrears，但 paid=True）
        # 和 `cash 且未收` 这两种组合**两边都不算**——营业额 200、已收 100、挂账 0，
        # 差出来的 100 在报表上哪一列都不属于（v3.39 探针实测：挂账结清后
        # "已收 +0 / 挂账 -100"，钱凭空消失）。
        if o.paid:
            collected += amount
        else:
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
    # ⚠️ 单均价先量化到两位（2026-09-19 审计 R13-R7）：`Decimal/Decimal` 会给出
    #    28 位商（实测导出的单元格是 `193.4895418326693227091633466`），
    #    Excel 里既难看又和界面上显示的"¥193.49"对不上。
    avg = (total_amount / total_orders).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) if total_orders else Decimal("0")
    # ⚠️ 撤销数按**业务当地日**筛（2026-09-19 审计 R13-R3）：`func.date(cancelled_at)` 取的是
    #    UTC 日期，东八区当地 00:00~08:00 撤销的单会被算到前一天 ——
    #    实测「今天撤销 0 单」而当天其实有 125 张（该行只在 >0 时渲染，于是整行消失）。
    #    `business_range_utc` 把当地日区间换成库里的 UTC 时刻，SQL 侧直接比时间列。
    c_start, c_end = business_range_utc(start, end)
    cancelled_orders = db.scalar(
        select(func.count(Order.id)).where(
            Order.status == OrderStatus.CANCELLED,
            Order.cancelled_at.isnot(None),
            Order.cancelled_at >= c_start,
            Order.cancelled_at < c_end,
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
        "cost_covered_amount": cost_covered_amount,
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
    cost_covered_amount = Decimal("0")
    for o in load_delivered(db):
        ds = business_date(o.delivered_at)
        if ds is None or ds < start or ds > end:
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
                item.covered_lines += 1
                # ⚠️ 毛利的两侧必须是**同一批行**（2026-09-19 审计第十七轮）：
                #    只累计成本、收入侧却用全额，等于"没成本快照的行按 0 成本、100% 毛利进账"。
                #    本机实测：商品页/导出的表头毛利 11,071.00，而营业纵览（正确口径）是 10,789.00；
                #    唯一那个混合组 ttt 印出 327.50（正确 45.50，差 7.2 倍）。
                item.covered_amount += lp.line_total or Decimal("0")
                cost_covered_amount += lp.line_total or Decimal("0")
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
        "cost_covered_amount": cost_covered_amount,
        "_window": (start, end),
    }


@router.get("/turnover", response_model=TurnoverReportOut)
def turnover_report(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.ORDER_DISPATCH)),
    mode: str = Query("day", pattern="^(day|week|month)$"),
    anchor: date = Query(..., alias="date", description="YYYY-MM-DD 锚点日期"),
) -> TurnoverReportOut:
    d = anchor
    data = build_turnover(db, mode, d)
    data.pop("_window", None)
    return TurnoverReportOut(**{**data, "period_label": data["period_label"]})


@router.get("/products", response_model=ProductReportOut)
def product_report(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.ORDER_DISPATCH)),
    mode: str = Query("day", pattern="^(day|week|month)$"),
    anchor: date = Query(..., alias="date", description="YYYY-MM-DD 锚点日期"),
) -> ProductReportOut:
    d = anchor
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
                # ⚠️ 隔离区（软删）的单不算欠款（2026-09-19 审计）：这个查询与 `load_delivered`
                #    是同一批口径，但当初只给 `load_delivered` 加了这一条 → 删掉一张挂账单之后，
                #    「营业纵览·挂账未收」减了、而这一份（客户经营页 + kind=customers 导出）没减，
                #    同一个页面两个"挂账未收"。实测本机差 ¥500。
                Order.deleted_at.is_(None),
                # ⚠️ **只按 `paid=False` 划"还没收"**，不再加 `payment_method == "arrears"`
                #    （2026-09-19 审计 R13-R4）：营业纵览那一份用的是 `paid=False` 一条判据，
                #    这里多一条 `payment_method == "arrears"` → 只要库里有一张
                #    `cash + paid=0 + collect_cash=0` 的已送达单（老数据/导库/直接改库都可能），
                #    两个"挂账未收"就永久分叉（实测 63,006.00 vs 62,920.50，差 ¥85.50 / 7 张单）。
                #    schema 里 `arrears_total` 的注释写的就是"挂账未收（paid=False）"——
                #    判据只有一处实现，才不会再走散。
                Order.paid.is_(False),
            )
        )
    )
    unit_map: dict[str, dict] = {}
    for o in rows:
        ds = business_date(o.delivered_at)
        if ds is None or ds < start or ds > end:
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
    date_from: date = Query(..., description="YYYY-MM-DD"),
    date_to: date = Query(..., description="YYYY-MM-DD"),
) -> list[dict]:
    start = date_from
    end = date_to
    return build_arrears_summary(db, start, end)


def _xlsx_sheet(ws, title_rows: list[list], header: list, rows: list[list]):
    ws.append([title_rows[0] if title_rows else ""])
    if len(title_rows) > 1:
        ws.append(title_rows[1])
    ws.append(header)
    for r in rows:
        ws.append(r)


def _money(v) -> float:
    """导出里的金额写成**数字**（不是文本），保留两位小数。

    2026-09-19 审计 R13-R7：原来一律 `str(decimal)` 写进单元格，openpyxl 存成**文本**
    （实测 `B2='97131.7500' type=s`）——用户在 Excel 里 `SUM` 选一列金额，
    得到的是 0（或只把"单数/件数"这种真数字加起来），账要自己拿计算器重算。
    金额是给人算的，必须能被 Excel 当数用。

    ⚠️ 进位方式必须显式写 `ROUND_HALF_UP`（2026-09-19 审计 F7）：`.quantize()` 的默认是
    **ROUND_HALF_EVEN**（银行家舍入），而全项目的 `driver_pay.money()` 是 ROUND_HALF_UP ——
    金额正好落在半分位上时（如 0.125）两处差 1 分，而"导出与页面差 1 分"是对账时最难查的那种。
    同族的货损两处已在第十五轮改过，这里是最后一处。
    """
    if v is None or v == "":
        return ""
    return float(Decimal(str(v)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


@router.get("/export")
def export_report(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.ORDER_DISPATCH)),
    kind: str = Query(..., pattern="^(turnover|products|drivers|customers|finance|audit)$"),
    mode: str = Query("day", pattern="^(day|week|month)$"),
    anchor: date = Query(..., alias="date", description="YYYY-MM-DD 锚点日期"),
    date_from: date | None = Query(None, description="YYYY-MM-DD（finance/customers 可用，优先于 mode+anchor）"),
    date_to: date | None = Query(None, description="YYYY-MM-DD"),
) -> StreamingResponse:
    """报表 Excel 导出（内存流 xlsx）。"""
    from io import BytesIO
    from openpyxl import Workbook

    from app.models import CashFlow, DriverSettlement, Expense, Ledger
    from app.models.enums import SettlementStatus

    d = anchor
    # 文件名的日期段：默认用锚点日；按区间导出时用**真实区间**（见下面 `range_label = ...`）。
    # ⛔ 原来文件名一律写 `{anchor}`，于是 `?date_from=2026-09-01&date_to=2026-09-01` 导出的文件
    #    叫 `finance-report-2026-09-18.xlsx`、内容却是 09-01~09-01 —— 对账/存档时按文件名找回来
    #    会拿到一份"名字与内容不符"的凭证（2026-09-19 审计第十一轮记录，第十五轮修）。
    range_label = str(d)
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
        ws.append(["营业金额", _money(data["total_amount"]), "订单数", data["total_orders"], "单均价", _money(data["avg_order"])])
        ws.append([
            # 口径同「司机运费结算」页：按计费规则应付（不是订单上的运费）——审计 R12-M2
            "司机运费支出(按计费规则应付)", _money(data["total_freight"]),
            "商品毛利(仅计成本快照行)",
            # 毛利 = 参与计算的收入 − 那些行的成本。**两侧必须是同一批行**（见 schemas/reports.py 的注释）
            _money(data["cost_covered_amount"] - data["cost_total"]),
            f"成本覆盖率 {data['cost_covered_lines']}/{data['total_lines']}；"
            f"参与毛利的收入 {data['cost_covered_amount']}／未参与 {data['total_amount'] - data['cost_covered_amount']}",
        ])
        ws.append(["货损件数", data["damage_qty"], "货损金额", _money(data["damage_amount"]), "已收", _money(data["collected"])])
        ws.append(["挂账未收", _money(data["arrears_total"]), "已撤销订单", data["cancelled_orders"]])
        ws.append([])
        ws.append(["时间", "单数", "金额", "运费"])
        for s in data["series"]:
            ws.append([s.label, s.orders, _money(s.amount), _money(s.freight)])
        ws.append([])
        ws.append(["挂账未收单位TOP"])
        for u in data["arrears_units"]:
            ws.append([u.name, _money(u.amount)])
    elif kind == "products":
        data = build_products(db, mode, d)
        ws = next_sheet("商品经营")
        ws.append(["商品经营", f"{mode} {_label(d, mode)}"])
        # ⚠️ 毛利的两侧必须**同一批行**（2026-09-19 审计第十七轮）：这里原来用
        #    "Σ 有成本行的**全额**金额 − cost_total" 当表头毛利 → 与营业纵览
        #    （cost_covered_amount − cost_total）差 ¥282（本机 11,071.00 vs 10,789.00），
        #    而逐行列更离谱：用的是 `amount − cost` 老公式，合计回到修复前那个错数 72,177.75。
        ws.append(["销售总额", _money(data["total_amount"]), "总件数", data["total_qty"],
                   "商品毛利(仅计成本快照行)",
                   _money((data["cost_covered_amount"] or Decimal("0")) - (data["cost_total"] or Decimal("0")))])
        ws.append(["货损件数", data["damage_qty"], "货损金额", _money(data["damage_amount"]), f"成本覆盖率 {data['cost_covered_lines']}/{data['total_lines']}"])
        ws.append([])
        ws.append(["商品", "件数", "单数", "金额", "参与毛利的金额", "毛利", "货损件数", "货损金额"])
        for it in data["items"]:
            cov = it.covered_amount or Decimal("0")
            # 没有成本快照的行**不进毛利**（写"—"，不是写一个看起来像毛利的大数）
            gross = _money(cov - it.cost) if (it.covered_lines or 0) > 0 else "—"
            ws.append([it.product_name, it.qty, it.order_count, _money(it.amount), _money(cov), gross, it.damage_qty, _money(it.damage_amount)])
    elif kind in ("drivers", "customers", "finance", "audit"):
        # 需要 date_from/date_to：缺省用窗口
        if date_from and date_to:
            s = date_from
            e = date_to
        else:
            s, e = _window(mode, d)
        # 文件名跟着**真实取数区间**走（不是锚点日）
        range_label = f"{s}_{e}" if s != e else str(s)

        if kind == "drivers":
            from app.services.stats_service import driver_performance

            ws = next_sheet("司机绩效")
            ws.append(["司机绩效", f"{s} ~ {e}"])
            ws.append(["司机", "完成单量", "准时率", "拍照率", "平均送达分钟", "计费方式", "待结运费"])
            # ⚠️ 这一块原来自己又写了一遍算法，于是三处与页面不是同一件事（2026-09-19 审计 R13-R5）：
            #    ① 「平均送达分钟」写死 `""` → 所有行、所有月份恒空；
            #    ② 准时率分母只算**有 `expected_deliver_before`** 的单，而页面按 models 的口径
            #       **空则按订单日末**（本库 637 张已送达单里 419 张没有 SLA → 导出恒空、页面有值）；
            #    ③ 工资制司机这里印 0，页面印"工资制"。
            #    现在**直接复用页面那一个服务**（`stats_service.driver_performance`）：
            #    一个指标只有一处实现，导出与页面不可能再走散。
            for row in driver_performance(db, s, e):
                rate = row["on_time_rate"]
                avg_sec = row["avg_delivery_seconds"]
                ws.append(
                    [
                        row["driver_name"],
                        row["completed_count"],
                        "" if rate is None else round(rate, 4),
                        round(row["photo_upload_rate"] or 0.0, 4),
                        "" if avg_sec is None else round(avg_sec / 60, 1),
                        row["billing_mode"] or "",
                        # 工资制司机这一格是 None（页面显示"工资制"）——导出也不许印 0，
                        # 那会被读成"这个月一分钱都不用付给他"
                        "工资制" if row["billing_mode"] == "SALARY" else (row["freight_owed"] or "0"),
                    ]
                )
        elif kind == "customers":
            from app.models import User

            ws = next_sheet("客户经营")
            ws.append(["客户账汇总", f"{s} ~ {e}"])
            # 货主账/批发商账（复用 ledger accounts 逻辑的简化：按流水聚合）
            # ⚠️ 隔离区（软删）订单的那份账不算（R13-R6）：与营业纵览同一句，否则
            #    "客户经营"的订货总额会比"营业额"多出一张已删单的钱（本机差 ¥4,600）。
            rows = list(db.scalars(visible_ledger_select()))
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
                ws.append(["货主", b["name"], b["count"], _money(b["total"])])
            for b in sorted(temp_bucket.values(), key=lambda x: -x["total"]):
                ws.append(["临时货主", b["name"], b["count"], _money(b["total"])])
            for b in sorted(member_buckets.values(), key=lambda x: -x["total"]):
                ws.append(["批发商", b["name"], b["count"], _money(b["total"])])
            ws.append([])
            ws.append(["挂账未收 TOP"])
            ws.append(["单位", "笔数", "金额"])
            for g in build_arrears_summary(db, s, e):
                ws.append([g["name"], g["count"], _money(g["amount"])])
        elif kind == "finance":
            ws = next_sheet("资金收支")
            flows = list(
                db.scalars(
                    select(CashFlow)
                    .where(CashFlow.flow_date >= s, CashFlow.flow_date <= e)
                    .order_by(CashFlow.flow_date.desc())
                )
            )
            income = sum((f.amount for f in flows if str(f.direction).lower() == "in"), Decimal("0"))
            expense = sum((f.amount for f in flows if str(f.direction).lower() == "out"), Decimal("0"))
            ws.append(["资金收支", f"{s} ~ {e}"])
            ws.append(["流入", _money(income), "流出", _money(expense), "净额", _money(income - expense)])
            ws.append([])
            ws.append(["日期", "方向", "金额", "对象", "渠道", "类型", "备注"])
            for f in flows:
                ws.append([f.flow_date.isoformat(),
                           "收入" if str(f.direction).lower() == "in" else "支出",
                           _money(f.amount), f.party_name or "", f.channel, f.biz_type, f.note])
            ws.append([])
            ws.append(["开销分类"])
            ws.append(["分类", "金额"])
            exp_rows = list(db.scalars(select(Expense).where(Expense.exp_date >= s, Expense.exp_date <= e)))
            cat_map: dict[str, Decimal] = {}
            for x in exp_rows:
                cat_map[x.category] = cat_map.get(x.category, Decimal("0")) + x.amount
            for cat, amt in sorted(cat_map.items(), key=lambda kv: -kv[1]):
                ws.append([cat, _money(amt)])
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
            # ⛔ 「敏感操作日志」原来**完全不看区间**（就是 `order_by(id.desc()).limit(200)`）：
            #    导出一份"09-01 的审计报告"，里面躺着的却是**库里最新**的 200 条日志（可能是 09-18 的）。
            #    审计凭证"名字写着 A、内容是 B"比"少给几条"严重得多——看的人会以为那就是当天的全部动作。
            #    现在按**业务当地日区间**过滤（与保留任务同一个 UTC 换算），并且如实说清有没有被截断。
            lo, hi = business_range_utc(s, e)
            in_range = (OperationLog.created_at >= lo, OperationLog.created_at < hi)
            total = db.scalar(
                select(func.count()).select_from(OperationLog).where(*in_range)
            ) or 0
            logs = list(
                db.scalars(
                    select(OperationLog).where(*in_range).order_by(OperationLog.id.desc()).limit(200)
                )
            )
            note = f"{s} ~ {e}"
            if total > len(logs):
                note += f"（区间内共 {total} 条，这里只列了最近 {len(logs)} 条）"
            else:
                note += f"（共 {total} 条）"
            ws.append(["敏感操作日志", note])
            ws.append(["时间", "操作", "内容"])
            for log in logs:
                ws.append([log.created_at.isoformat() if log.created_at else "", log.action, log.change_content or ""])

    buf = BytesIO()
    wb.save(buf)
    fn = f"{kind}-report-{range_label}.xlsx"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{fn}"'},
    )