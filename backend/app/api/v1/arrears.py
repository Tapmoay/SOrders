"""挂账单位管理（派单员）：订单可选择挂账到单位名下。"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.rbac import Permission
from app.database import get_db
from app.deps import require_permission
from app.models import ArrearsUnit, Order, User
from app.schemas.arrears import ArrearsUnitCreate, ArrearsUnitOut, ArrearsUnitUpdate

router = APIRouter(prefix="/arrears-units", tags=["arrears-units"])


@router.get("", response_model=list[ArrearsUnitOut])
def list_units(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.LEDGER_EDIT)),
) -> list[ArrearsUnit]:
    rows = db.scalars(select(ArrearsUnit).order_by(ArrearsUnit.id.desc()))
    return list(rows)


@router.post("", response_model=ArrearsUnitOut, status_code=status.HTTP_201_CREATED)
def create_unit(
    body: ArrearsUnitCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.LEDGER_EDIT)),
) -> ArrearsUnit:
    name = body.name.strip()
    if db.scalars(select(ArrearsUnit).where(ArrearsUnit.name == name)).first():
        raise HTTPException(status_code=400, detail="挂账单位名称已存在")
    u = ArrearsUnit(name=name, phone=body.phone.strip(), remark=body.remark.strip())
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


@router.patch("/{unit_id}", response_model=ArrearsUnitOut)
def update_unit(
    unit_id: int,
    body: ArrearsUnitUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.LEDGER_EDIT)),
) -> ArrearsUnit:
    u = db.get(ArrearsUnit, unit_id)
    if u is None:
        raise HTTPException(status_code=404, detail="挂账单位不存在")
    if body.name is not None:
        name = body.name.strip()
        dup = db.scalars(
            select(ArrearsUnit).where(ArrearsUnit.name == name, ArrearsUnit.id != unit_id)
        ).first()
        if dup:
            raise HTTPException(status_code=400, detail="挂账单位名称已存在")
        u.name = name
    if body.phone is not None:
        u.phone = body.phone.strip()
    if body.remark is not None:
        u.remark = body.remark.strip()
    db.commit()
    db.refresh(u)
    return u


@router.delete("/{unit_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_unit(
    unit_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.LEDGER_EDIT)),
) -> None:
    u = db.get(ArrearsUnit, unit_id)
    if u is None:
        raise HTTPException(status_code=404, detail="挂账单位不存在")
    used = db.scalar(
        select(func.count())
        .select_from(Order)
        .where(Order.arrears_unit_id == unit_id)
    )
    if used:
        raise HTTPException(status_code=400, detail=f"该单位名下已有 {used} 笔挂账订单，无法删除")
    db.delete(u)
    db.commit()
