"""滚动收款（不绑订单的那种收款）的**预收归集**：按债务人算「这笔钱该冲谁的应收」。

## 为什么单独一个模块（2026-10-10，BUG-0036 / 测试台账 TB-14）

滚动收款只写现金流水，欠款表一分不冲 —— 客户已经付过钱，催收名单上还是全款，会被重复催收。
冲减本身是**读侧**的事（不动任何金额算法），但它要按债务人归集，而"钱怎么算"这件事**不许在报表层再写一遍**
（_tools/qa/_check_customer_balances.py 明令 services/reports/balance_query.py 里 func.sum( 出现 0 次）。
所以归集落在这个 service 里，报表层只做"取回来、加上去"。

## 口径（与 services/reports/balance_query.py::_debtor_of 一致）

- 只认**未撤销**（is_deleted=False）、**截止报表日**（received_at <= as_of）的 settle_mode=rolling 收款；
- 归集键：收款单只有 customer_id，所以走 customers 的 arrears_unit_id → ("unit", str(id))、
  user_id → ("shipper", str(id)) —— 与订单侧的债务人划分同一套键；
- **认不出来的（散客、既没单位也没账号）不猜**：那笔预收就留在现金流水与收款记录里。
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Customer, ShipperReceipt
from app.models.enums import ReceiptSettleMode

ZERO = Decimal("0")


def rolling_receipt_credit_map(db: Session, as_of: date) -> dict[tuple[str, str], Decimal]:
    """未指定订单的收款按债务人归集：{(kind, key): 金额}。

    kind / key 与 services/reports/balance_query.py::_debtor_of 完全同源：
    ("unit", str(arrears_unit_id)) / ("shipper", str(user_id))。
    """
    rows = db.execute(
        select(ShipperReceipt.customer_id, func.sum(ShipperReceipt.amount))
        .where(
            ShipperReceipt.settle_mode == ReceiptSettleMode.ROLLING,
            ShipperReceipt.is_deleted.is_(False),
            ShipperReceipt.received_at <= as_of,
        )
        .group_by(ShipperReceipt.customer_id)
    ).all()
    ids = [int(cid) for cid, _amt in rows if cid is not None]
    if not ids:
        return {}
    customers = {c.id: c for c in db.scalars(select(Customer).where(Customer.id.in_(ids)))}
    out: dict[tuple[str, str], Decimal] = {}
    for cid, amount in rows:
        c = customers.get(int(cid)) if cid is not None else None
        if c is None or amount is None:
            continue
        if c.arrears_unit_id is not None:
            key = ("unit", str(c.arrears_unit_id))
        elif c.user_id is not None:
            key = ("shipper", str(c.user_id))
        else:
            continue  # 散客：认不出债务人，宁可让这笔预收留在现金流水里
        out[key] = out.get(key, ZERO) + Decimal(amount)
    return out
