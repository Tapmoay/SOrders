"""按商品的聚合那一份**只读**查询（指南 §九 点名的 product_query）。


⛔ **只读**：本包下的模块只允许 SELECT / JOIN / GROUP BY —— 判据 _tools/qa/_check_report_boundary.py
在 AST 层面禁止落库写法与写服务依赖，而且它是**算出来的**（services/reports/** 由 glob 自动收）。
"""
from __future__ import annotations

from app.services.reports._common import _label, _span_label, _window
from app.services.reports.loader import load_delivered
from datetime import date
from decimal import Decimal
from sqlalchemy.orm import Session
from app.core.business_time import business_date
from app.schemas.reports import ProductReportItem
from app.services.cost_basis import SNAPSHOT, CostBasis
from app.services.money_contract import line_receivable



def build_products(db: Session, mode: str, anchor: date, *, span: tuple[date, date] | None = None) -> dict:
    """商品经营聚合（含成本/货损），供接口与导出复用。

    [span] 的含义与 [build_turnover] 一致（两页必须**同一个窗口口径**）。
    """
    d = anchor
    start, end = span if span else _window(mode, anchor)
    # 成本口径与营业纵览**同一处**（`services/cost_basis.py`）：两页的毛利必须对得上
    basis = CostBasis(db, start, end)
    agg: dict[str, ProductReportItem] = {}
    total_qty = 0
    total_amount = Decimal("0")
    cost_total = Decimal("0")
    damage_qty = 0
    damage_amount = Decimal("0")
    total_lines = 0
    cost_covered_lines = 0
    cost_covered_amount = Decimal("0")
    cost_avg_lines = 0
    cost_snapshot_lines = 0
    for o in load_delivered(db, span=(start, end)):
        ds = business_date(o.delivered_at)
        if ds is None or ds < start or ds > end:
            continue
        for lp in o.order_products:
            name = lp.product_name_snapshot or "未命名商品"
            item = agg.setdefault(name, ProductReportItem(product_name=name))
            # ⛔ **数量与金额一律按净额**（2026-09-23 第 17 轮并行渗透抓到：这里原来是**毛额**，
            #    于是"商品毛利"这个词在同一份导出里有两个数 —— 营业纵览 sheet ¥4,896.60、
            #    商品经营 sheet ¥4,911.10，差额随退货量线性放大，老板按哪个都对不上）。
            #    两条口径必须与 `build_turnover` 的循环**逐行同源**：
            #    · 整行退完且无货损 → `continue`（那一行不进商品经营，也不进毛利）；
            #    · 数量取 `quantity − returned_quantity`、金额取 `line_receivable`（行金额 − 退掉那部分）、
            #      成本按净件数算 —— 与那边第 217/228/232 行一字不差。
            #    判据：`tests/test_report_gross_profit_one_source.py`（两个端点同窗口逐项相等）。
            net_qty = int(lp.quantity or 0) - int(lp.returned_quantity or 0)
            if net_qty <= 0 and (lp.damage_quantity or 0) <= 0:
                continue
            net_amount = line_receivable(lp)
            item.qty += max(0, net_qty)
            item.amount += net_amount
            item.order_count += 1
            total_qty += max(0, net_qty)
            total_amount += net_amount
            total_lines += 1
            cost, basis_src = basis.of(lp.product_id, lp.cost_price_snapshot)
            if cost > 0:
                cost_covered_lines += 1
                item.covered_lines += 1
                # ⚠️ 毛利的两侧必须是**同一批行**（2026-09-19 审计第十七轮）：
                #    只累计成本、收入侧却用全额，等于"没成本的行按 0 成本、100% 毛利进账"。
                #    本机实测：商品页/导出的表头毛利 11,071.00，而营业纵览（正确口径）是 10,789.00；
                #    唯一那个混合组 ttt 印出 327.50（正确 45.50，差 7.2 倍）。
                item.covered_amount += net_amount
                cost_covered_amount += net_amount
                cost_total += cost * Decimal(max(0, net_qty))
                item.cost += cost * Decimal(max(0, net_qty))
                if basis_src == SNAPSHOT:
                    cost_snapshot_lines += 1
                else:
                    cost_avg_lines += 1
            dq = lp.damage_quantity or 0
            if dq > 0:
                item.damage_qty += dq
                damage_qty += dq
                # 货损与营业纵览同口径（快照，理由见那边）
                snap = lp.cost_price_snapshot or Decimal("0")
                amt = snap * Decimal(dq) if snap > 0 else Decimal("0")
                damage_amount += amt
                item.damage_amount += amt
    items = sorted(agg.values(), key=lambda x: -x.amount)
    return {
        "period_label": _span_label(start, end) if span else _label(d, mode),
        "total_qty": total_qty,
        "total_amount": total_amount,
        "items": items,
        "cost_total": cost_total,
        "damage_qty": damage_qty,
        "damage_amount": damage_amount,
        "total_lines": total_lines,
        "cost_covered_lines": cost_covered_lines,
        "cost_covered_amount": cost_covered_amount,
        "cost_avg_lines": cost_avg_lines,
        "cost_snapshot_lines": cost_snapshot_lines,
        "_window": (start, end),
    }


def _cost_basis_note(data: dict) -> str:
    """导出里的"成本怎么算的"说明行。

    ⛔ 营业纵览与商品经营两个 sheet **必须用这同一份文字**：两边各写一句，
       改口径时漏改一处，导出里就出现两个互相矛盾的口径说明
       （而"两个表对不上"正是这份报表历史上最贵的一类缺陷）。
    """
    return (
        f"成本口径：入库流水的加权平均进货价（{data['cost_avg_lines']} 行）；"
        f"另有 {data['cost_snapshot_lines']} 行该商品没记过进货价、按下单时的成本快照算；"
        f"共 {data['cost_covered_lines']}/{data['total_lines']} 行算得出成本，其余行不进毛利；"
        f"参与毛利的收入 {data['cost_covered_amount']}／未参与 {data['total_amount'] - data['cost_covered_amount']}"
    )
