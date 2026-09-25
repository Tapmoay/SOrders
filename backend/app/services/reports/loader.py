"""报表只读查询的**取数**（把给定窗口内已送达的订单行读出来）。


⛔ **只读**：本包下的模块只允许 SELECT / JOIN / GROUP BY —— 判据 _tools/qa/_check_report_boundary.py
在 AST 层面禁止落库写法与写服务依赖，而且它是**算出来的**（services/reports/** 由 glob 自动收）。
"""
from __future__ import annotations

from datetime import date
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm import selectinload
from app.core.business_time import business_date, business_range_utc
from app.models import Order
from app.models.enums import OrderStatus



def delivered_span_sql(start: date, end: date) -> tuple:
    """把「业务当地日闭区间」翻译成 `delivered_at`（UTC naive）的**半开区间**条件。

    ⚠️ 这不是第二套口径，而是 `business_date()` 那套判据在 SQL 侧的**等价前置过滤**：
    `core/business_time.business_range_utc(start, end)` 给出的 `[start 当地 00:00, end+1 当地 00:00)`
    与循环里那句 `ds < start or ds > end` 覆盖的是**同一批时刻**（半开 / 闭区间只是写法差别）。

    ### 为什么必须加它（2026-09-23 容量实测，见 `_tools/perf/`）
    `load_delivered` 原来是**无条件把全库已送达单连行一起读进内存**，再由函数体按窗口丢掉 ——
    也就是说**看一天的报表，也要把三年历史全查一遍**。实测（2 万单的副本库）：
    `mode=day` 与 `mode=month` 的耗时都是 **2.3 秒左右**（同一条 2.2~2.5s、看不出窗口差别），
    而数据保留策略是 **3 年** —— 这个代价随时间线性长，且页面与导出走的是同一段聚合。
    加了窗口过滤之后，读的行数只与窗口有关、与全库历史无关。
    """
    lo, hi = business_range_utc(start, end)
    return Order.delivered_at >= lo, Order.delivered_at < hi


def load_delivered(db: Session, *, span: tuple[date, date] | None = None) -> list[Order]:
    """全部已送达订单（按送达时间排序）；由各报表按窗口过滤，减少重复查询。

    [span] 非空 = 只读这一段业务日区间内的单（**调用方已经知道窗口时一定要传**，
    否则就是把全库历史读进内存再丢掉，见 [delivered_span_sql]）。
    循环里那句 `ds < start or ds > end` 仍然保留 —— 它才是权威判据，SQL 侧只是同口径的预过滤。

    ### 为什么必须排掉软删（隔离区）的单
    `DELETE /orders/{id}` 是**伪装删除**（进隔离区 30 天，可恢复），用户界面上已经看不到了。
    而报表这边以前**没有这个过滤**——只 grep 过 `deleted_at`：
    全后端只有 `orders.py` 与 `data_retention.py` 用到了它。
    后果是"删掉的那张单还在营业额、毛利、货损、司机应付里"：
    用户删掉一张错单，报表上的数字**一分都不减**，而他会以为删干净了。
    """
    q = (
        select(Order)
        .options(selectinload(Order.order_products))
        .where(
            Order.status == OrderStatus.DELIVERED,
            Order.delivered_at.isnot(None),
            # 隔离区里的单不算数（列可能不存在于极老的库里时由 schema_bootstrap 补齐）
            Order.deleted_at.is_(None),
        )
    )
    if span is not None:
        q = q.where(*delivered_span_sql(span[0], span[1]))
    return list(db.scalars(q.order_by(Order.delivered_at)))
