"""库存管理（派单员）：出入库流水自动维护商品库存。"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.rbac import Permission
from app.database import get_db
from app.deps import parse_date_range, require_permission
from app.models import InventoryMovement, Product, User
from app.models.enums import OperationAction
from app.schemas.inventory import MovementCreate, MovementOut
from app.services.operation_log_service import write_log

router = APIRouter(prefix="/inventory", tags=["inventory"])


@router.get("/movements", response_model=list[MovementOut])
def list_movements(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.PRODUCT_MANAGE)),
    product_id: int | None = Query(None),
    limit: int = Query(100, le=500),
    offset: int = Query(0),
    date_from: str | None = Query(None, description="YYYY-MM-DD（含当天）"),
    date_to: str | None = Query(None, description="YYYY-MM-DD（含当天）"),
) -> list[InventoryMovement]:
    q = select(InventoryMovement).order_by(InventoryMovement.id.desc()).offset(offset).limit(limit)
    if product_id is not None:
        q = q.where(InventoryMovement.product_id == product_id)
    if date_from or date_to:
        df, dt = parse_date_range(date_from, date_to)
        if df is not None:
            q = q.where(InventoryMovement.created_at >= df)
        if dt is not None:
            q = q.where(InventoryMovement.created_at <= dt)
    return list(db.scalars(q))


@router.post("/movements", response_model=MovementOut, status_code=status.HTTP_201_CREATED)
def create_movement(
    body: MovementCreate,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(Permission.PRODUCT_MANAGE)),
) -> InventoryMovement:
    if body.change == 0:
        raise HTTPException(status_code=400, detail="变动数量不能为 0")
    product = db.get(Product, body.product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="商品不存在")
    new_stock = (product.stock or 0) + body.change
    if new_stock < 0:
        raise HTTPException(
            status_code=400,
            detail=f"库存不足：当前库存 {product.stock or 0}，出库 {abs(body.change)} 超出",
        )
    product.stock = new_stock
    row = InventoryMovement(
        product_id=body.product_id,
        change=body.change,
        note=body.note.strip(),
        operator_id=current.id,
        source="MANUAL",
        status="COMMITTED",
    )
    db.add(row)
    # ⚠️ 库存调整**必须留痕**：它和改价是同一类事（改了钱/货的账，月底对不上要能回查）。
    #    这一条以前漏了——审计页上永远看不到谁把库存改了多少。
    #    与流水在**同一个事务**里提交，不会出现"货动了、日志没写"。
    write_log(
        db,
        operator_id=current.id,
        order_id=None,
        action=OperationAction.INVENTORY_ADJUST,
        change_payload={
            "product_id": product.id,
            "name": product.name,
            "change": body.change,
            "stock_after": new_stock,
            "note": body.note.strip(),
        },
    )
    db.commit()
    db.refresh(row)
    return row


@router.get("/summary")
def inventory_summary(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.PRODUCT_MANAGE)),
    below_alert: bool = Query(False, description="只返回库存已达报警阈值的商品"),
) -> list[dict]:
    """库存概览：商品名 + 当前库存 + 在途占用量（派单中未送达，低库存排前）。"""
    from sqlalchemy import func

    q = select(Product).where(Product.is_active.is_(True)).order_by(Product.stock, Product.id)
    if below_alert:
        # 与 Android InventoryScreen 标红判断一致：阈值 > 0 且 库存 <= 阈值
        q = q.where(Product.low_stock_alert > 0).where(Product.stock <= Product.low_stock_alert)
    rows = db.scalars(q)
    reserved_rows = db.execute(
        select(InventoryMovement.product_id, func.sum(InventoryMovement.change))
        .where(
            InventoryMovement.source == "ORDER",
            InventoryMovement.status == "RESERVED",
        )
        .group_by(InventoryMovement.product_id)
    ).all()
    reserved_map = {pid: abs(int(total or 0)) for pid, total in reserved_rows}
    return [
        {
            "product_id": p.id,
            "product_name": p.name,
            "stock": p.stock or 0,
            "unit": p.unit or "件",
            "low_stock_alert": p.low_stock_alert or 0,
            "reserved": reserved_map.get(p.id, 0),
        }
        for p in rows
    ]
