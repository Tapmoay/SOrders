from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.rbac import user_role_key
from app.models import Order, User
from app.models.enums import OrderStatus, UserRole
from app.schemas.order import OrderOut


def enrich_order_out(order: Order, db: Session, viewer: User | None = None) -> OrderOut:
    data = OrderOut.model_validate(order).model_dump()
    if order.driver_id:
        du = db.get(User, order.driver_id)
        if du:
            data["driver_phone"] = du.phone
            data["driver_name"] = du.full_name or ""
    su = db.get(User, order.shipper_id) if order.shipper_id is not None else None
    if su is not None:
        data["shipper_name"] = su.full_name or su.phone or ""
    else:
        tn = (order.temp_shipper_name or "").strip()
        data["shipper_name"] = tn or None
    data["is_new_for_driver"] = bool(
        order.status == OrderStatus.ACCEPTED
        and order.driver_id is not None
        and order.driver_acknowledged_at is None
    )
    if viewer is not None:
        if user_role_key(viewer) == UserRole.SHIPPER.value:
            data["internal_notes"] = ""
    return OrderOut(**data)


def load_order_for_response(db: Session, order_id: int) -> Order | None:
    return db.scalars(
        select(Order).options(selectinload(Order.order_products)).where(Order.id == order_id)
    ).first()
