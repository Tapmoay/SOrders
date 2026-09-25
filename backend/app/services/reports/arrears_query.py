"""欠款汇总那一份**只读**查询（指南 §九 点名的 arrears_query）。


⛔ **只读**：本包下的模块只允许 SELECT / JOIN / GROUP BY —— 判据 _tools/qa/_check_report_boundary.py
在 AST 层面禁止落库写法与写服务依赖，而且它是**算出来的**（services/reports/** 由 glob 自动收）。
"""
from __future__ import annotations

from app.services.reports.loader import delivered_span_sql
from datetime import date
from decimal import Decimal
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm import selectinload
from app.core.business_time import business_date
from app.models import Order
from app.models.enums import OrderStatus
from app.services.money_contract import money_map



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
                # ⚠️ 与 `load_delivered` 同一个窗口预过滤（2026-09-23 容量实测）：
                #    这一段原来也是全库读进内存再按窗口丢。挂账页与营业纵览共用同一批单，
                #    两边的窗口口径必须一模一样（下面循环里那句 `ds < start or ds > end` 仍是权威判据）。
                *delivered_span_sql(start, end),
            )
        )
    )
    unit_map: dict[str, dict] = {}
    # 金额改成**这一单还欠多少**（`order_money.arrears`），不是"当时卖了多少"：
    # 收了一半的单、退了一部分的单，欠款都不等于 `line_total` 之和。
    money = money_map(db, rows)
    for o in rows:
        ds = business_date(o.delivered_at)
        if ds is None or ds < start or ds > end:
            continue
        mm = money[o.id]
        if mm.arrears == 0:
            # `paid=False` 但一分钱都不欠了（比如整单被收干净了、或货全退了）→ 不算挂账。
            # 把它算进去会得到一条"0 元欠款"的挂账单位行，看的人只会以为系统坏了。
            continue
        name = (o.arrears_unit_name or "").strip() or "未分配挂账单位"
        g = unit_map.setdefault(name, {"name": name, "count": 0, "amount": Decimal("0")})
        g["count"] += 1
        g["amount"] += mm.arrears
    return sorted(unit_map.values(), key=lambda x: -x["amount"])
