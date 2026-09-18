from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.rbac import Permission
from app.database import get_db
from app.deps import require_permission
from app.models import Order, OrderProduct, Product, User
from app.models.enums import OperationAction, OrderStatus
from app.schemas.order import OrderProductCreate, OrderProductOut, OrderProductUpdate
from app.services.operation_log_service import write_log
from app.services.order_flow import resolve_line_total

router = APIRouter(prefix="/order-products", tags=["order-products"])


def _check_product_ref(db: Session, product_id: int | None) -> None:
    """行上带的商品编号必须真的在商品库里、且没被删（否则成本快照按 0 记、送达不扣库存）。"""
    if product_id is None:
        return
    p = db.get(Product, product_id)
    if p is None:
        raise HTTPException(
            status_code=400,
            detail=f"商品编号 {product_id} 不在商品库里。请重新选一个商品，或改成不填编号的手输商品行。",
        )
    if p.is_deleted:
        raise HTTPException(status_code=400, detail=f"商品「{p.name}」已经删除了，请重新选一个。")


def _order_allows_line_edit(order: Order) -> bool:
    """派单员修正明细：待派单与已接单（运输中）均可编辑；已送达/已撤销不可。"""
    return order.status in (OrderStatus.PENDING_DISPATCH, OrderStatus.DISPATCHED, OrderStatus.ACCEPTED)


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
    try:
        lt = resolve_line_total(body.unit_price, body.quantity, body.line_total)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    _check_product_ref(db, body.product_id)
    # 单位：客户端给了就用，没给则回退商品库里的单位（人工加的行回退"件"）
    unit = (body.unit or "").strip()
    if not unit and body.product_id is not None:
        p = db.get(Product, body.product_id)
        unit = (p.unit or "件").strip() if p else "件"
    op = OrderProduct(
        order_id=body.order_id,
        product_id=body.product_id,
        product_name_snapshot=body.product_name_snapshot,
        quantity=body.quantity,
        unit_price=body.unit_price,
        line_total=lt,
        unit_snapshot=(unit or "件")[:32],
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
        _check_product_ref(db, body.product_id)
    # ⚠️ 只改数量或只改单价时，行金额必须**跟着重算**；两个都给了也要核对一致性
    #    （原来客户端可以塞一个和"单价×数量"无关的 line_total，账本就跟着错）。
    new_up = body.unit_price if body.unit_price is not None else op.unit_price
    new_qty = body.quantity if body.quantity is not None else op.quantity
    if body.line_total is not None or body.quantity is not None or body.unit_price is not None:
        try:
            op.line_total = resolve_line_total(new_up, new_qty, body.line_total)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
    if body.product_id is not None:
        op.product_id = body.product_id
    if body.product_name_snapshot is not None:
        op.product_name_snapshot = body.product_name_snapshot
    if body.quantity is not None:
        op.quantity = body.quantity
    if body.unit_price is not None:
        op.unit_price = body.unit_price
    if body.unit is not None:
        op.unit_snapshot = body.unit.strip()[:32]
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
