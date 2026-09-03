from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.core.rbac import user_role_key
from app.models import Order, User
from app.models.order import OrderProduct
from app.models.user import resolve_billing_mode
from app.models.enums import OperationAction, OrderStatus, UserRole
from app.services.accounting_service import post_delivery_accounting
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
    order.status = OrderStatus.DISPATCHED
    order.driver_id = driver.id
    order.dispatched_at = _now()
    # 司机计费方式快照：司机换类型后，历史订单可见性仍按派单当时判定
    order.driver_billing_mode_snapshot = resolve_billing_mode(driver.vehicle_type, driver.billing_mode)
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




def split_order(
    db: Session,
    order: Order,
    parts: list[int],
    operator: User,
) -> list[Order]:
    """待派单拆分为 N 个子单（parts 为各份比例，数量按比例拆分，余数归首份）；
    原单撤销留痕并可追溯。返回新建子单列表。"""
    if order.status != OrderStatus.PENDING_DISPATCH:
        raise ValueError("仅「待派单」订单可拆分")
    if len(parts) < 2:
        raise ValueError("请至少拆分为 2 单")
    total_w = sum(parts)
    lines = list(order.order_products)
    if not lines:
        raise ValueError("订单无商品明细，无法拆分")
    created: list[Order] = []
    for idx, wgt in enumerate(parts):
        child = Order(
            order_no=order.order_no + "-" + str(idx + 1),
            status=OrderStatus.PENDING_DISPATCH,
            shipper_id=order.shipper_id,
            temp_shipper_name=order.temp_shipper_name,
            order_date=order.order_date,
            delivery_description=order.delivery_description,
            address_detail=order.address_detail,
            address_lat=order.address_lat,
            address_lng=order.address_lng,
            address_image_url=order.address_image_url,
            contact_dongjia_phone=order.contact_dongjia_phone,
            contact_boss_phone=order.contact_boss_phone,
            remark=order.remark,
            internal_notes=f"[拆分 {idx + 1}/{len(parts)}] 由 {order.order_no} 拆分",
            driver_remark=order.driver_remark,
            payment_method=order.payment_method,
            arrears_unit_id=order.arrears_unit_id,
            arrears_unit_name=order.arrears_unit_name,
            parent_order_id=order.id,
        )
        for lp in lines:
            qty = max(1, round(lp.quantity * wgt / total_w))
            child.order_products.append(
                OrderProduct(
                    product_id=lp.product_id,
                    product_name_snapshot=lp.product_name_snapshot,
                    quantity=qty,
                    unit_price=lp.unit_price,
                    line_total=lp.unit_price * qty,
                )
            )
        db.add(child)
        created.append(child)
    order.status = OrderStatus.CANCELLED
    order.cancelled_at = _now()
    order.internal_notes = (order.internal_notes or "").strip() + chr(10) + "[拆分] 已拆分为 " + str(len(parts)) + " 单"
    write_log(
        db,
        operator_id=operator.id,
        order_id=order.id,
        action=OperationAction.ORDER_SPLIT,
        change_payload={"parts": parts, "children": [c.order_no for c in created]},
    )
    db.flush()
    return created



def complete_delivery(
    db: Session,
    order: Order,
    driver: User,
    delivery_photo_urls: list[str],
    driver_remark: str = "",
    damage_items: list | None = None,
    damage_note: str = "",
) -> None:
    """将订单置为已送达；同步货主账本（与明细行幂等）并执行账务钩子（司机应付明细+货损记账）。

    damage_items: [{order_product_id, quantity}] 商品行级货损（选填，公司自担）；damage_note 订单级备注。
    """
    if order.status != OrderStatus.ACCEPTED:
        raise ValueError("仅「已接单」订单可完成配送")
    if order.driver_id != driver.id:
        raise ValueError("非本单指派司机，无法操作")
    if not delivery_photo_urls:
        mode = order.driver_billing_mode_snapshot or resolve_billing_mode(driver.vehicle_type, driver.billing_mode)
        if mode != "PIECE":
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
    # 货损录入（选填）：写商品行/订单备注，随后统一账务钩子
    from decimal import Decimal as _Dec

    if damage_items:
        for item in damage_items:
            op = next((x for x in order.order_products if x.id == item.order_product_id), None)
            if op is None:
                raise ValueError("货损商品行不存在")
            qty = int(item.quantity or 0)
            if qty < 0:
                raise ValueError("货损数量不能为负")
            if qty > op.quantity:
                raise ValueError(f"货损数量超过该行数量（{op.quantity}）")
            op.damage_quantity = qty
        order.damage_note = (damage_note or "").strip()
    # 账务钩子：PIECE 应付明细 + 货损 LOSS/COGS 冲回（幂等）
    post_delivery_accounting(db, order, operator_id=driver.id)


def cancel_pending(
    db: Session,
    order: Order,
    operator: User,
) -> None:
    if order.status not in (OrderStatus.PENDING_DISPATCH, OrderStatus.DISPATCHED):
        raise ValueError("仅「待派单/已派单（司机未接单）」订单可按此流程撤销")
    order.status = OrderStatus.CANCELLED
    order.cancelled_at = _now()
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
    if order.status not in (OrderStatus.DISPATCHED, OrderStatus.ACCEPTED):
        raise ValueError("仅「已派单/已接单」订单可撤回派单")
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
    db: Session,
    lines: list[Any],
) -> list:
    """按下单行构建 OrderProduct；商品成本快照在下单时定格（货损/毛利率按此时成本）。"""
    from app.models import OrderProduct, Product

    out = []
    for line in lines:
        lt = getattr(line, "line_total", None)
        qty = line.quantity
        up = line.unit_price
        if lt is None or lt == Decimal("0"):
            lt = up * qty
        pid = getattr(line, "product_id", None)
        cost_snap = Decimal("0")
        if pid is not None:
            prod = db.get(Product, pid)
            if prod is not None:
                cost_snap = prod.cost_price or Decimal("0")
        out.append(
            OrderProduct(
                product_id=pid,
                product_name_snapshot=line.product_name_snapshot,
                quantity=qty,
                unit_price=up,
                line_total=lt,
                cost_price_snapshot=cost_snap,
            )
        )
    return out