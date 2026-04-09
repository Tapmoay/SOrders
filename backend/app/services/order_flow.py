from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.core.rbac import user_role_key
from app.models import Order, User
from app.models.enums import OperationAction, OrderStatus, UserRole
from app.services.ledger_sync import sync_ledger_from_delivered_order
from app.services.operation_log_service import write_log


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _dec_for_json(x: Any) -> Any:
    if x is None:
        return None
    if isinstance(x, Decimal):
        return str(x)
    return x


def order_snapshot_for_log(db: Session, order: Order) -> dict[str, Any]:
    """撤回派单等场景写入操作日志的订单快照（派单前状态）。"""
    shipper = db.get(User, order.shipper_id) if order.shipper_id is not None else None
    driver = db.get(User, order.driver_id) if order.driver_id else None
    lines: list[dict[str, Any]] = []
    for op in order.order_products:
        lines.append(
            {
                "product_name_snapshot": op.product_name_snapshot,
                "quantity": op.quantity,
                "unit_price": str(op.unit_price),
                "line_total": str(op.line_total),
            }
        )
    st = order.status.value if hasattr(order.status, "value") else str(order.status)
    return {
        "order_no": order.order_no,
        "status": st,
        "shipper_id": order.shipper_id,
        "shipper_name": (shipper.full_name or shipper.phone) if shipper else None,
        "driver_id": order.driver_id,
        "driver_name": (driver.full_name or driver.phone) if driver else None,
        "delivery_description": order.delivery_description,
        "address_detail": order.address_detail,
        "address_lat": _dec_for_json(order.address_lat),
        "address_lng": _dec_for_json(order.address_lng),
        "contact_dongjia_phone": order.contact_dongjia_phone,
        "contact_boss_phone": order.contact_boss_phone,
        "remark": order.remark,
        "internal_notes": order.internal_notes,
        "dispatched_at": order.dispatched_at.isoformat() if order.dispatched_at else None,
        "order_products": lines,
    }


def assign_driver(
    db: Session,
    order: Order,
    driver: User,
    operator: User,
    internal_note: str | None = None,
) -> None:
    if order.status != OrderStatus.PENDING_DISPATCH:
        raise ValueError("仅「待派单」状态可派单")
    if user_role_key(driver) != UserRole.DRIVER.value:
        raise ValueError("派单目标须为司机账号")
    order.status = OrderStatus.ACCEPTED
    order.driver_id = driver.id
    order.dispatched_at = _now()
    order.driver_acknowledged_at = None
    if internal_note and internal_note.strip():
        ts = _now().strftime("%m-%d %H:%M")
        prefix = f"[派单指派 {ts}] "
        order.internal_notes = (order.internal_notes or "").strip()
        if order.internal_notes:
            order.internal_notes += "\n"
        order.internal_notes += prefix + internal_note.strip()
    write_log(
        db,
        operator_id=operator.id,
        order_id=order.id,
        action=OperationAction.ORDER_DISPATCH,
        change_payload={"driver_id": driver.id, "internal_note": (internal_note or "").strip() or None},
    )


def complete_delivery(
    db: Session,
    order: Order,
    driver: User,
    delivery_photo_urls: list[str],
    driver_remark: str = "",
) -> None:
    """将订单置为已送达；若有货主则同步货主账本（与明细行幂等）。"""
    if order.status != OrderStatus.ACCEPTED:
        raise ValueError("仅「已接单」订单可完成配送")
    if order.driver_id != driver.id:
        raise ValueError("非本单指派司机，无法操作")
    if not delivery_photo_urls:
        raise ValueError("请至少上传一张送达照片")
    order.status = OrderStatus.DELIVERED
    order.delivery_photo_urls = delivery_photo_urls
    order.driver_remark = driver_remark
    order.delivered_at = _now()
    write_log(
        db,
        operator_id=driver.id,
        order_id=order.id,
        action=OperationAction.ORDER_COMPLETE,
        change_payload={"photos": len(delivery_photo_urls)},
    )
    sync_ledger_from_delivered_order(db, order)


def cancel_pending(
    db: Session,
    order: Order,
    operator: User,
) -> None:
    if order.status != OrderStatus.PENDING_DISPATCH:
        raise ValueError("仅「待派单」订单可按此流程撤销")
    order.status = OrderStatus.CANCELLED
    write_log(
        db,
        operator_id=operator.id,
        order_id=order.id,
        action=OperationAction.ORDER_CANCEL,
        change_payload={"by": "shipper_or_dispatcher"},
    )


def recall_dispatch(
    db: Session,
    order: Order,
    operator: User,
    reason: str,
) -> None:
    if order.status != OrderStatus.ACCEPTED:
        raise ValueError("仅「已接单」订单可撤回派单")
    snapshot = order_snapshot_for_log(db, order)
    recalled_driver_id = order.driver_id
    order.status = OrderStatus.PENDING_DISPATCH
    order.driver_id = None
    order.dispatched_at = None
    order.driver_acknowledged_at = None
    write_log(
        db,
        operator_id=operator.id,
        order_id=order.id,
        action=OperationAction.ORDER_RECALL,
        change_payload={
            "reason": reason,
            "recalled_driver_id": recalled_driver_id,
            "order_snapshot": snapshot,
            "recalled_at": _now().isoformat(),
        },
    )


def ensure_order_date(d: date | None) -> date:
    return d or date.today()


def build_order_products(
    lines: list[Any],
) -> list:
    from app.models import OrderProduct

    out = []
    for line in lines:
        lt = getattr(line, "line_total", None)
        qty = line.quantity
        up = line.unit_price
        if lt is None or lt == Decimal("0"):
            lt = up * qty
        out.append(
            OrderProduct(
                product_id=line.product_id,
                product_name_snapshot=line.product_name_snapshot,
                quantity=qty,
                unit_price=up,
                line_total=lt,
            )
        )
    return out
