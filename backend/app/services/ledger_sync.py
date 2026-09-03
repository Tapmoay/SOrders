"""账本与订单明细一致性：关联订单的账本行变更时同步 OrderProduct；送达时由订单明细生成账本。"""

from datetime import date
from decimal import Decimal

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from app.models import Ledger, Order, OrderProduct
from app.models.enums import LedgerSource, OrderStatus


def sync_ledger_from_delivered_order(db: Session, order: Order) -> None:
    """订单变为已送达且存在归属（系统货主或临时货主名）时，按订单明细自动写入/更新账本（来源 order，按 order_product_id 幂等）。"""
    if order.status != OrderStatus.DELIVERED:
        return
    has_user_shipper = order.shipper_id is not None
    temp_name = (order.temp_shipper_name or "").strip()
    has_temp = bool(temp_name)
    if not has_user_shipper and not has_temp:
        return
    entry_date: date
    if order.delivered_at is not None:
        entry_date = order.delivered_at.date()
    else:
        entry_date = order.order_date
    shipper_id = order.shipper_id
    temp_shipper_name = temp_name if not has_user_shipper else None
    for op in order.order_products:
        lt = op.line_total if op.line_total is not None else (op.unit_price * Decimal(op.quantity))
        existing = db.scalars(
            select(Ledger).where(
                Ledger.order_product_id == op.id,
                Ledger.source == LedgerSource.ORDER,
            )
        ).first()
        if existing is not None:
            existing.shipper_id = shipper_id
            existing.temp_shipper_name = temp_shipper_name
            existing.entry_date = entry_date
            existing.product_name = op.product_name_snapshot
            existing.quantity = op.quantity
            existing.unit_price = op.unit_price
            existing.total = lt
            existing.order_id = order.id
            existing.product_id = op.product_id
            existing.cost_price_snapshot = op.cost_price_snapshot or Decimal("0")
            if not (existing.note or "").strip():
                existing.note = "订单送达自动记账"
            continue
        db.add(
            Ledger(
                shipper_id=shipper_id,
                temp_shipper_name=temp_shipper_name,
                entry_date=entry_date,
                product_name=op.product_name_snapshot,
                quantity=op.quantity,
                unit_price=op.unit_price,
                total=lt,
                order_id=order.id,
                order_product_id=op.id,
                product_id=op.product_id,
                source=LedgerSource.ORDER,
                note="订单送达自动记账",
                cost_price_snapshot=op.cost_price_snapshot or Decimal("0"),
            )
        )


def sync_order_product_from_ledger(db: Session, ledger: Ledger) -> None:
    if ledger.source == LedgerSource.MANUAL:
        return
    if ledger.order_id is None:
        return
    op: OrderProduct | None = None
    if ledger.order_product_id is not None:
        cand = db.get(OrderProduct, ledger.order_product_id)
        if cand is not None and cand.order_id == ledger.order_id:
            op = cand
    if op is None and ledger.product_id is not None:
        op = db.scalars(
            select(OrderProduct).where(
                OrderProduct.order_id == ledger.order_id,
                OrderProduct.product_id == ledger.product_id,
            )
        ).first()
    if op is None:
        name = (ledger.product_name or "").strip()
        op = db.scalars(
            select(OrderProduct).where(
                OrderProduct.order_id == ledger.order_id,
                OrderProduct.product_name_snapshot == name,
            )
        ).first()
    if op is None:
        return
    op.quantity = ledger.quantity
    op.unit_price = ledger.unit_price
    op.line_total = ledger.total
    if ledger.product_name and op.product_name_snapshot != ledger.product_name:
        op.product_name_snapshot = ledger.product_name


def sync_delivered_orders_to_ledger(
    db: Session,
    shipper_id: int | None = None,
    temp_shipper_name: str | None = None,
) -> tuple[int, set[int]]:
    """对已送达订单批量执行账本同步（与送达时逻辑相同，用于历史补全）。返回 (订单数, 涉及系统货主 id 集合，用于消息推送)。"""
    stmt = (
        select(Order)
        .where(Order.status == OrderStatus.DELIVERED)
        .where(or_(Order.shipper_id.isnot(None), Order.temp_shipper_name.isnot(None)))
        .options(selectinload(Order.order_products))
    )
    if shipper_id is not None:
        stmt = stmt.where(Order.shipper_id == shipper_id)
    elif temp_shipper_name is not None and temp_shipper_name.strip():
        stmt = stmt.where(Order.shipper_id.is_(None)).where(Order.temp_shipper_name == temp_shipper_name.strip())
    orders = list(db.scalars(stmt).unique().all())
    affected_shippers: set[int] = set()
    for order in orders:
        sync_ledger_from_delivered_order(db, order)
        if order.shipper_id is not None:
            affected_shippers.add(order.shipper_id)
    return len(orders), affected_shippers