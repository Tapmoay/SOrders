"""报表聚合的**旧路径**（第二轮 R2-05 下半：已搬进 `app/services/reports/`）。

指南 §九：「先做 Query Boundary」。搬完之后**实现**在包里；这里只**转出**名字
（与 `api/v1/reports.py` 当年 re-export 同一条规矩：搬迁不改引用点）。

⛔ 本文件里**一行实现都没有**。**什么时候删掉这一份**：等引用点都指到 `app.services.reports.*` 之后。
"""

from __future__ import annotations

from app.services.reports._common import (  # noqa: F401
    _label,
    _money,
    _range_dates,
    _span,
    _span_label,
    _window,
)
from app.services.reports.arrears_query import build_arrears_summary  # noqa: F401
from app.services.reports.loader import delivered_span_sql, load_delivered  # noqa: F401
from app.services.reports.product_query import _cost_basis_note, build_products  # noqa: F401
from app.services.reports.turnover_query import build_turnover  # noqa: F401

__all__ = [
    "build_arrears_summary", "build_products", "build_turnover",
    "delivered_span_sql", "load_delivered",
    "_cost_basis_note", "_label", "_money", "_range_dates", "_span", "_span_label", "_window",
]
