"""商品成本价的**生效区间**维护 —— 改成本价只有这一个入口（用户 2026-09-19 要求）。

## 用户原话

> 「那个成本价去做一个保留…这个保留是跟着他的账本走的。假如他的账本是一直保留着，
>   那他这个成本价就一直保留着。如果成本价发生了变化，就直接变化成本价就可以了，
>   这样子我们就好溯源。而且我们保留的时候不仅保留成本价，还保留这个成本价存在的时间，
>   比如说他是从什么时候开始变的、从什么时候结束的，精确到小时和分钟。」

表结构与"为什么是区间而不是事件日志"写在 `models/product.py::ProductCostHistory`。

## ⛔ 这个文件是 `products.cost_price` 的**唯一写入口**

改成本价的地方一共三处，全部走 [record_cost]：

| 入口 | source | 说明 |
|---|---|---|
| `POST /products`（建商品） | `CREATE` | 建的时候填的那个价就是第一段区间的起点 |
| `POST /inventory/movements`（带 `unit_cost`） | `PURCHASE` | 进货带进来的价，顺带记下是哪条流水 |
| `PATCH /products/{id}`（改 `cost_price`） | `MANUAL` | 有人在商品编辑里手填 |

绕开它直接 `product.cost_price = x` 的后果是**静默的**：价格变了、区间表没变，
于是"这段时间的成本价"从此对不上账 —— 而界面上一切正常。
红线 `_tools/qa/_check_cost_history.py` 盯着这件事。

## 和毛利口径的关系（别搞混）

**毛利不用这张表取数**。毛利成本 = 入库流水的加权平均进货价
（`services/cost_basis.py`，用户上一轮定的口径：进货价一涨，用"最新一次进货价"算
会让旧库存的毛利偏低）。这张区间表是**溯源与复核**用的：任何一单的成本争议，
都能查出"那一刻商品的成本价是多少、从什么时候到什么时候"。
"""

from __future__ import annotations

from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.business_time import utc_now_naive
from app.models import Product, ProductCostHistory

#: 这一段的来源（写进 `ProductCostHistory.source`，也是前端分组显示的依据）
SOURCE_CREATE = "CREATE"
SOURCE_PURCHASE = "PURCHASE"
SOURCE_MANUAL = "MANUAL"

_Q = Decimal("0.0001")  # 与 `products.cost_price` 的 Numeric(14,4) 同精度


def record_cost(
    db: Session,
    product: Product,
    new_cost: Decimal | str | None,
    *,
    source: str,
    operator_id: int | None = None,
    movement_id: int | None = None,
    when: datetime | None = None,
) -> bool:
    """把成本价改成 [new_cost] 并**同时**维护生效区间。→ 价格是否真的变了。

    ⚠️ **价没变就什么都不做**（不写一行零长度区间）：否则每次编辑商品、每次不带价的入库
    都会往这张表里塞一段"价格没变"的记录，"这个价用了多久"就查不出来了。

    ⚠️ 调用方**不需要**自己 `product.cost_price = x` —— 这里会设。
    """
    new_cost = Decimal(new_cost or 0).quantize(_Q, rounding=ROUND_HALF_UP)
    old_cost = Decimal(product.cost_price or 0)
    at = when or utc_now_naive()

    # 当前生效的那一行（正常恰好一行；一行都没有 = 这个商品还没被回填过）
    open_row = db.scalars(
        select(ProductCostHistory)
        .where(
            ProductCostHistory.product_id == product.id,
            ProductCostHistory.effective_to.is_(None),
        )
        .order_by(ProductCostHistory.effective_from.desc())
    ).first()

    if open_row is not None:
        if old_cost == new_cost:
            return False
        # 旧区间到此为止；新的一行从这一刻开始 —— 半开区间，不留缝也不重叠
        open_row.effective_to = at
    db.add(
        ProductCostHistory(
            product_id=product.id,
            cost_price=new_cost,
            effective_from=at,
            effective_to=None,
            source=source,
            operator_id=operator_id,
            movement_id=movement_id,
        )
    )
    product.cost_price = new_cost
    return True


def cost_at(db: Session, product_id: int, when: datetime) -> Decimal | None:
    """某个时刻生效的成本价；那一刻没有记录（或还没开始记）→ None。

    读法就是那个半开区间：`effective_from <= t < effective_to`（`effective_to` 为 NULL = 至今）。
    """
    return db.scalars(
        select(ProductCostHistory.cost_price)
        .where(
            ProductCostHistory.product_id == product_id,
            ProductCostHistory.effective_from <= when,
            (ProductCostHistory.effective_to.is_(None)) | (ProductCostHistory.effective_to > when),
        )
        .order_by(ProductCostHistory.effective_from.desc())
    ).first()
