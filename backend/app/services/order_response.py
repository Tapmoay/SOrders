from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.rbac import user_role_key
from app.models import Order, User
from app.models.enums import OrderStatus, UserRole
from app.models.user import resolve_billing_mode
from app.schemas.order import OrderOut
from app.services.order_money import OrderMoney, money_map, money_of


def apply_driver_view_gating(data: dict, order: Order, driver: User) -> None:
    """司机视角门控（列表/详情共用）：
    1) 剥离订单明细的货款（单价/小计，司机无需看到货主货款）；
    2) 运费仅按单计费（PIECE）司机可见；固定工资/未分类司机一律置 None。
    可见性按派单时快照判定，司机换类型不影响历史订单。"""
    mode = order.driver_billing_mode_snapshot or resolve_billing_mode(
        driver.vehicle_type, driver.billing_mode
    )
    for lp in data.get("order_products", []):
        lp["unit_price"] = None
        lp["line_total"] = None
    data["freight_visible"] = mode == "PIECE"
    if mode != "PIECE":
        data["freight_fee"] = None


def enrich_order_out(
    order: Order, db: Session, viewer: User | None = None, money: OrderMoney | None = None
) -> OrderOut:
    """出参装配。**列表请传 `money`**（用 `money_map` 一次算好一页的钱）。

    ⚠️ 不传 `money` 时这里会为**这一张**单发 4 条分组查询（`money_of`）。
       单张详情无所谓，但列表里逐单调用就是 4×N 条 SQL —— 而
       `enrich_order_out` 本来已经在逐单 `db.get(User, …)` 了（同类问题的实测代价
       见 `ledger_response.py`：85,474 行 → 27.75 秒）。所以列表端点走批次。
    """
    data = OrderOut.model_validate(order).model_dump()
    if order.driver_id:
        du = db.get(User, order.driver_id)
        if du:
            data["driver_phone"] = du.phone
            data["driver_name"] = du.full_name or ""
            data["driver_billing_mode"] = order.driver_billing_mode_snapshot or resolve_billing_mode(
                du.vehicle_type, du.billing_mode
            )
    su = db.get(User, order.shipper_id) if order.shipper_id is not None else None
    if su is not None:
        data["shipper_name"] = su.full_name or su.phone or ""
    else:
        tn = (order.temp_shipper_name or "").strip()
        data["shipper_name"] = tn or None
    data["is_new_for_driver"] = bool(
        order.status in (OrderStatus.DISPATCHED, OrderStatus.ACCEPTED)
        and order.driver_id is not None
        and order.driver_acknowledged_at is None
    )
    # 这一单的钱：口径只有 `services/order_money.py` 一处（退货红冲、部分核销、现场收现金
    # 三件事都在这三个数里体现，客户端不许自己再加一遍）
    m = money or money_of(db, order)
    data["returned_amount"] = m.returned
    data["settled_amount"] = m.settled
    data["refunded_amount"] = m.refunded
    data["arrears_amount"] = m.arrears
    if viewer is not None:
        if user_role_key(viewer) == UserRole.SHIPPER.value:
            data["internal_notes"] = ""
            data["freight_visible"] = True
        elif user_role_key(viewer) == UserRole.DISPATCHER.value:
            data["freight_visible"] = True
        elif user_role_key(viewer) == UserRole.DRIVER.value and order.driver_id is not None:
            # 司机视角统一门控：剥离货款；运费按计费快照（回退当前模式）门控
            du = du if du else db.get(User, order.driver_id)
            if du is not None:
                apply_driver_view_gating(data, order, du)
    return OrderOut(**data)


def load_order_for_response(db: Session, order_id: int) -> Order | None:
    return db.scalars(
        select(Order).options(selectinload(Order.order_products)).where(Order.id == order_id)
    ).first()
