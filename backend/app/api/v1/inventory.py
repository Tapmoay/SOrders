"""库存管理（派单员）：出入库流水自动维护商品库存。"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.rbac import Permission
from app.database import get_db
from app.deps import parse_date_range, require_permission
from app.models import InventoryMovement, Product, User
from app.schemas.inventory import MovementCreate, MovementOut

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
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/summary")
def inventory_summary(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.PRODUCT_MANAGE)),
) -> list[dict]:
    """库存概览：商品名 + 当前库存（低库存排前）。"""
    rows = db.scalars(
        select(Product).where(Product.is_active.is_(True)).order_by(Product.stock, Product.id)
    )
    return [
        {"product_id": p.id, "product_name": p.name, "stock": p.stock or 0, "unit": p.unit or "件", "low_stock_alert": p.low_stock_alert or 0}
        for p in rows
    ]
