"""已撤销订单保留期限：超过保留天数后物理删除（含明细、关联账本与操作日志）。"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, delete, or_, select
from sqlalchemy.orm import Session

from app.models.enums import OrderStatus
from app.models.ledger import Ledger
from app.models.operation_log import OperationLog
from app.models.order import Order, OrderProduct

logger = logging.getLogger(__name__)

CANCELLED_ORDER_RETENTION_DAYS = 10


def delete_orders_by_ids(db: Session, ids: list[int]) -> int:
    """物理删除订单及明细、关联账本与操作日志。返回删除的订单数量。"""
    if not ids:
        return 0
    ids = list(dict.fromkeys(int(i) for i in ids))
    op_ids_subq = select(OrderProduct.id).where(OrderProduct.order_id.in_(ids))

    db.execute(delete(Ledger).where(Ledger.order_product_id.in_(op_ids_subq)))
    db.execute(delete(Ledger).where(Ledger.order_id.in_(ids)))
    db.execute(delete(OperationLog).where(OperationLog.order_id.in_(ids)))
    db.execute(delete(OrderProduct).where(OrderProduct.order_id.in_(ids)))
    db.execute(delete(Order).where(Order.id.in_(ids)))
    return len(ids)


def purge_expired_cancelled_orders(db: Session) -> int:
    """删除「已撤销」且超过保留期的订单。返回删除的订单数量。"""
    cutoff = datetime.now(timezone.utc) - timedelta(days=CANCELLED_ORDER_RETENTION_DAYS)

    ids_rows = db.execute(
        select(Order.id).where(
            Order.status == OrderStatus.CANCELLED,
            or_(
                and_(Order.cancelled_at.isnot(None), Order.cancelled_at < cutoff),
                and_(Order.cancelled_at.is_(None), Order.updated_at < cutoff),
            ),
        )
    ).all()
    ids = [int(r[0]) for r in ids_rows]
    if not ids:
        return 0

    n = delete_orders_by_ids(db, ids)
    logger.info(
        "已删除 %s 条超过 %s 天的已撤销订单 id=%s",
        n,
        CANCELLED_ORDER_RETENTION_DAYS,
        ids[:20] + (["…"] if len(ids) > 20 else []),
    )
    return n
