from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.rbac import Permission
from app.database import get_db
from app.deps import require_permission
from app.models import Order, OrderProduct, User
from app.models.enums import OperationAction, OrderStatus
from app.schemas.order import OrderProductCreate, OrderProductOut, OrderProductUpdate
from app.services.operation_log_service import write_log

router = APIRouter(prefix="/order-products", tags=["order-products"])


def _order_allows_line_edit(order: Order) -> bool:
    """派单员修正明细：待派单与已接单（运输中）均可编辑；已送达/已撤销不可。"""
    return order.status in (OrderStatus.PENDING_DISPATCH, OrderStatus.ACCEPTED)


@router.get("", response_model=list[OrderProductOut])
def list_order_products(
    order_id: int = Query(..., description="按订单筛选明细"),
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(Permission.ORDER_READ_ALL)),
) -> list[OrderProduct]:
    order = db.get(Order, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="订单不存在")
    rows = db.scalars(select(OrderProduct).where(OrderProduct.order_id == order_id)).all()
    return list(rows)


@router.post("", response_model=OrderProductOut, status_code=status.HTTP_201_CREATED)
def create_order_product(
    body: OrderProductCreate,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(Permission.ORDER_PRODUCT_EDIT)),
) -> OrderProduct:
    order = db.get(Order, body.order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="订单不存在")
    if not _order_allows_line_edit(order):
        raise HTTPException(status_code=400, detail="当前订单状态不可编辑商品明细")
    lt: Decimal | None = body.line_total
    if lt is None or lt == Decimal("0"):
        lt = body.unit_price * body.quantity
    op = OrderProduct(
        order_id=body.order_id,
        product_id=body.product_id,
        product_name_snapshot=body.product_name_snapshot,
        quantity=body.quantity,
        unit_price=body.unit_price,
        line_total=lt,
    )
    db.add(op)
    db.flush()
    write_log(
        db,
        operator_id=current.id,
        order_id=order.id,
        action=OperationAction.ORDER_LINE_ADD,
        change_payload={"line_id": op.id},
    )
    db.commit()
    db.refresh(op)
    return op


@router.get("/{line_id}", response_model=OrderProductOut)
def get_order_product(line_id: int, db: Session = Depends(get_db), current: User = Depends(require_permission(Permission.ORDER_READ_ALL))) -> OrderProduct:
    op = db.get(OrderProduct, line_id)
    if op is None:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    return op


@router.patch("/{line_id}", response_model=OrderProductOut)
def update_order_product(
    line_id: int,
    body: OrderProductUpdate,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(Permission.ORDER_PRODUCT_EDIT)),
) -> OrderProduct:
    op = db.get(OrderProduct, line_id)
    if op is None:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    order = db.get(Order, op.order_id)
    if order is None:
        raise HTTPException(status_code=400, detail="订单数据异常")
    if not _order_allows_line_edit(order):
        raise HTTPException(status_code=400, detail="当前订单状态不可编辑商品明细")
    if body.product_id is not None:
        op.product_id = body.product_id
    if body.product_name_snapshot is not None:
        op.product_name_snapshot = body.product_name_snapshot
    if body.quantity is not None:
        op.quantity = body.quantity
    if body.unit_price is not None:
        op.unit_price = body.unit_price
    if body.line_total is not None:
        op.line_total = body.line_total
    elif body.quantity is not None or body.unit_price is not None:
        op.line_total = op.unit_price * op.quantity
    write_log(
        db,
        operator_id=current.id,
        order_id=order.id,
        action=OperationAction.ORDER_LINE_UPDATE,
        change_payload={"line_id": op.id},
    )
    db.commit()
    db.refresh(op)
    return op


@router.delete("/{line_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_order_product(
    line_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(Permission.ORDER_PRODUCT_EDIT)),
) -> None:
    op = db.get(OrderProduct, line_id)
    if op is None:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    order = db.get(Order, op.order_id)
    if order is None:
        raise HTTPException(status_code=400, detail="订单数据异常")
    if not _order_allows_line_edit(order):
        raise HTTPException(status_code=400, detail="当前订单状态不可编辑商品明细")
    oid = op.order_id
    db.delete(op)
    if order:
        write_log(
            db,
            operator_id=current.id,
            order_id=oid,
            action=OperationAction.ORDER_LINE_DELETE,
            change_payload={"line_id": line_id},
        )
    db.commit()
