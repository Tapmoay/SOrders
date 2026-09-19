from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Ledger, Order
from app.schemas.ledger import LedgerOut


def _to_out(row: Ledger, order: Order | None) -> LedgerOut:
    """把一行账本 + 它关联的订单（可能没有）拼成出参。**唯一**拼装处。"""
    order_no: str | None = None
    order_delivery_description: str | None = None
    if order is not None:
        order_no = order.order_no
        d = (order.delivery_description or "").strip()
        order_delivery_description = d or None
    return LedgerOut(
        id=row.id,
        shipper_id=row.shipper_id,
        temp_shipper_name=row.temp_shipper_name,
        entry_date=row.entry_date,
        product_name=row.product_name,
        quantity=row.quantity,
        unit_price=row.unit_price,
        total=row.total,
        order_id=row.order_id,
        order_product_id=row.order_product_id,
        product_id=row.product_id,
        order_no=order_no,
        order_delivery_description=order_delivery_description,
        source=row.source,
        note=row.note,
        created_at=row.created_at,
    )


def ledger_to_out(row: Ledger, db: Session) -> LedgerOut:
    """单行版（`GET/PATCH/DELETE /ledger/entries/{id}` 这类只处理一行的端点用）。"""
    return _to_out(row, db.get(Order, row.order_id) if row.order_id else None)


def ledger_rows_to_out(rows: list[Ledger], db: Session) -> list[LedgerOut]:
    """**列表版**：一次 `IN` 查询把所有关联订单取回来。

    ⚠️ 为什么不能用逐行 `ledger_to_out`（2026-09-19 外部完整检查 C-4 / PERF-02 / R2B-2）：
    原来列表端点就是 `[ledger_to_out(r, db) for r in rows]`，而 `db.get()` **每次都真发一条 SQL**
    —— Session 的身份映射对已加载对象持**弱引用**，行对象被回收后缓存就没了，"靠 identity map
    兜着"这个假设不成立（实测同一个 id 连取 10 次 = 10 条 SQL）。
    于是 `GET /ledger/entries` 的 SQL 条数 ≈ 行数：实测 85,474 行 → **85,476 条 SQL / 27.75 秒**。
    批量化之后 SQL 条数变成**常数 2**（1 条取流水 + 1 条取订单），与行数无关。
    """
    order_ids = {int(r.order_id) for r in rows if r.order_id}
    orders: dict[int, Order] = {}
    if order_ids:
        for o in db.scalars(select(Order).where(Order.id.in_(order_ids))).all():
            orders[int(o.id)] = o
    return [
        _to_out(r, orders.get(int(r.order_id)) if r.order_id else None)
        for r in rows
    ]

