"""库存自动联动：订单派送自动出库 → 送达最终确认 → 撤销/撤回自动回库。

规则（与业务约定一致）：
- 订单派送（DISPATCHED）→ 预占用：仅生成 RESERVED 流水（change=-qty），库存界面显示「-N」，
  **实际库存不动**。
- 订单送达（DELIVERED）→ 此时才真正减库存（RESERVED→COMMITTED，stock -= qty）。
- 订单撤销/撤回派单（CANCELLED / 撤回）→ 释放占用：原流水转 RELEASED，补一条 +qty
  「订单撤销自动回库」流水；实际库存不动（从未实扣）。
- 商品解析：优先明细行绑定 product_id；缺绑定时按「活跃商品唯一同名」兜底匹配；
  无同名/多同名 → 跳过（不占用）。
- 库存不足不拦截（先出后补），库存允许为负并在流水上如实记录。
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import InventoryMovement, Order, Product


def _order_rows(db: Session, order: Order) -> list:
    products = getattr(order, "order_products", None) or []
    if products:
        return products
    from app.models import OrderProduct

    return list(db.scalars(select(OrderProduct).where(OrderProduct.order_id == order.id)))


def _match_product_by_name(db: Session, name: str) -> Product | None:
    """按商品名唯一定位活跃商品（下单手输商品名时的自动出库兜底）；多个同名/无同名→不扣。"""
    n = (name or "").strip()
    if not n:
        return None
    rows = list(
        db.scalars(
            select(Product).where(Product.is_active.is_(True), Product.name == n)
        )
    )
    return rows[0] if len(rows) == 1 else None


def _resolve_product(db: Session, op) -> Product | None:
    """明细行商品解析：优先显式绑定；缺绑定按名称唯一匹配兜底。"""
    if op.product_id is not None:
        return db.get(Product, op.product_id)
    return _match_product_by_name(db, getattr(op, "product_name_snapshot", None))


def auto_stock_out(db: Session, order: Order, operator_id: int) -> int:
    """订单派送自动出库（预占）：不动实际库存，仅生成 RESERVED 占用流水，库存界面显示「-N」；
    真正减库存发生在订单送达（auto_stock_commit）。返回生成流水条数。"""
    n = 0
    for op in _order_rows(db, order):
        prod = _resolve_product(db, op)
        if prod is None:
            continue
        db.add(
            InventoryMovement(
                product_id=prod.id,
                change=-op.quantity,
                note="订单派送自动出库",
                operator_id=operator_id,
                source="ORDER",
                order_id=order.id,
                status="RESERVED",
            )
        )
        n += 1
    return n


def auto_stock_commit(db: Session, order: Order) -> int:
    """订单送达：此时才真正减库存（预占用转实扣，RESERVED → COMMITTED）。返回更新条数。"""
    rows = list(
        db.scalars(
            select(InventoryMovement).where(
                InventoryMovement.order_id == order.id,
                InventoryMovement.source == "ORDER",
                InventoryMovement.status == "RESERVED",
            )
        )
    )
    for m in rows:
        prod = db.get(Product, m.product_id)
        if prod is not None:
            prod.stock = (prod.stock or 0) + m.change  # change 为负 → 真正减库存
        m.status = "COMMITTED"
    return len(rows)


def auto_stock_release(db: Session, order: Order, operator_id: int) -> int:
    """订单撤销/撤回派单：释放预占用（不动实际库存——派单时未真正扣减），
    原流水转 RELEASED 并补一条「订单撤销自动回库」流水。返回释放条数。"""
    n = 0
    rows = list(
        db.scalars(
            select(InventoryMovement).where(
                InventoryMovement.order_id == order.id,
                InventoryMovement.source == "ORDER",
                InventoryMovement.status == "RESERVED",
            )
        )
    )
    for m in rows:
        m.status = "RELEASED"
        db.add(
            InventoryMovement(
                product_id=m.product_id,
                change=-m.change,
                note="订单撤销自动回库",
                operator_id=operator_id,
                source="ORDER",
                order_id=order.id,
                status="RELEASED",
            )
        )
        n += 1
    return n
