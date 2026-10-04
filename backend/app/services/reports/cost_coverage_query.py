"""成本覆盖表：这一段窗口里，有多少收入因为「没有进货价」而算不出成本（FEAT-0013）。

这张表回答用户在五期计划里点名要的那个问题：

```text
我这段卖出去的钱里，有多少是算不出成本的？哪些商品压根没记过进货价？
```

## 口径：**只搬运，不重算**（与 `profit_query.py` 同一套）

```text
revenue_total / revenue_covered / revenue_uncovered / total_lines / covered_lines
    ← 全部取自 build_turnover（「算不出成本的收入」的唯一判据在那里：
      `cost_basis` 给出的成本 > 0 才算覆盖，算不出的那部分收入不进毛利）
```

⛔ 本模块**不碰 `cost_basis`**、不自己判「这个商品有没有成本价」、也不重算任何金额：
   把收入那一侧再算一遍，就又多出一处口径（本项目的报表历史上最贵的一类缺陷）。

## ⛔ 两件事不要混（页面文案也必须写清）

```text
「没记过进货价的商品」清单（按**商品**列：没有任何 change>0 且带 unit_cost 的入库流水）
        ≠
「算不出成本的收入」（按**订单行**算出来的钱）
```

两者相关但**不等价**：一笔算不出成本的收入，可能来自一个曾经有进价、但当期没进货的商品
（`cost_basis` 的 PERIOD 口径只看窗口内的入库）。所以本表把两块**并排摆**，
⛔ 不加、不相减、不写成比例 —— 那种「A 是因为 B」的因果是编出来的。

## 只读

本模块只有 SELECT（`_tools/qa/_check_report_boundary.py` 在 AST 层盯着）。
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import InventoryMovement, Product
from app.services.reports._common import _span_label
from app.services.reports.turnover_query import build_turnover

_ZERO = Decimal("0")

#: 页面上那几句口径说明（用户可见：⛔ 不许出现 markdown 星号，判据 `_check_hints.py` 同族规矩）。
_NOTES: tuple[str, ...] = (
    "「算不出成本的收入」只有一条判据：这一行的成本大于 0（入库流水的加权平均进货价；该商品没记过进货价时退回下单那一刻的成本快照）。算不出来的那部分收入不进毛利 —— 既不按 0 成本、也不按平均成本替它猜，就单列在这里。",
    "下面那份清单是「从来没记过进货价的商品」，按商品列；它不等于上面那笔收入的来源 —— 收入是按订单行算的，一笔算不出成本的收入也可能来自一个有进价、只是这一段没进货的商品。",
    "补进货价的入口有两个：下一次进货时在「采购单」里填上单价，或者到库存页做一次带进货价的入库。两处都会更新这个商品的成本价，之后的收入就进毛利了。",
    "清单里那一列「成本价」是商品台账上最近一次记过的进货价；报表算成本用的是入库流水的加权平均价，不是这一列。",
)


def _never_priced(db: Session) -> list[dict[str, Any]]:
    """从来没记过进货价的商品（没有任何 change>0 且带 unit_cost 的入库流水）。

    ⛔ 判据只看**流水**，不看 `products.cost_price`：成本价那一列是台账上的一个数，
    可能是手改的、也可能是上一次进货留下的；「有没有记过进货价」这件事只有流水说了算。
    ⛔ 也不看 `is_active`：停用的商品一样要能补录（补完之后历史报表才解释得通）。
    """
    priced = select(InventoryMovement.product_id).where(
        InventoryMovement.change > 0,
        InventoryMovement.unit_cost.isnot(None),
    )
    rows = db.scalars(
        select(Product)
        .where(Product.is_deleted.is_(False), Product.id.notin_(priced))
        .order_by(Product.name)
    )
    return [
        {
            "product_id": p.id,
            "name": p.name,
            "unit": p.unit or "",
            "stock": int(p.stock or 0),
            "cost_price": p.cost_price,
            "is_active": bool(p.is_active),
        }
        for p in rows
    ]


def build_cost_coverage(
    db: Session,
    mode: str,
    anchor: date,
    *,
    span: tuple[date, date] | None = None,
) -> dict[str, Any]:
    """成本覆盖：收入那一侧取营业纵览（同一 span），商品那一侧取「从没记过进货价」的清单。"""
    turnover = build_turnover(db, mode, anchor, span=span)
    start, end = turnover["_window"]
    revenue_total = turnover["total_amount"]
    revenue_covered = turnover["cost_covered_amount"]
    missing = _never_priced(db)
    return {
        "period_label": _span_label(start, end),
        "date_from": start.isoformat(),
        "date_to": end.isoformat(),
        "revenue_total": revenue_total,
        "revenue_covered": revenue_covered,
        # 「算不出成本的收入」= 收入 − 参与毛利的收入（与 profit_query 同一句，不另立口径）
        "revenue_uncovered": revenue_total - revenue_covered,
        "total_lines": int(turnover["total_lines"]),
        "covered_lines": int(turnover["cost_covered_lines"]),
        "cost_avg_lines": int(turnover["cost_avg_lines"]),
        "cost_snapshot_lines": int(turnover["cost_snapshot_lines"]),
        "missing_purchase_price_count": len(missing),
        "missing_purchase_price": missing,
        "notes": list(_NOTES),
        "_window": (start, end),
    }
