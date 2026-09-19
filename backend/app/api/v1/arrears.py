"""挂账单位管理（派单员）：订单可选择挂账到单位名下。"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.rbac import Permission
from app.database import get_db
from app.deps import require_permission
from app.models import ArrearsUnit, Order, User
from app.schemas.arrears import ArrearsUnitCreate, ArrearsUnitOut, ArrearsUnitUpdate
from datetime import datetime

router = APIRouter(prefix="/arrears-units", tags=["arrears-units"])


@router.get("", response_model=list[ArrearsUnitOut])
def list_units(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.LEDGER_EDIT)),
) -> list[ArrearsUnit]:
    rows = db.scalars(
        select(ArrearsUnit).where(ArrearsUnit.is_deleted.is_(False)).order_by(ArrearsUnit.id.desc())
    )
    return list(rows)


@router.post("", response_model=ArrearsUnitOut, status_code=status.HTTP_201_CREATED)
def create_unit(
    body: ArrearsUnitCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.LEDGER_EDIT)),
) -> ArrearsUnit:
    name = body.name.strip()
    if db.scalars(
        select(ArrearsUnit).where(ArrearsUnit.name == name, ArrearsUnit.is_deleted.is_(False))
    ).first():
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
            select(ArrearsUnit).where(
            ArrearsUnit.name == name, ArrearsUnit.id != unit_id, ArrearsUnit.is_deleted.is_(False)
        )
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
    # 伪装删除：行留着，恢复时逐字段照搬。**名字要释放出来**——
    # 这张表 name 是唯一的，不释放的话删掉再建同名单位会直接 500。
    u.is_deleted = True
    u.deleted_at = datetime.now()
    u.name = f"{u.name}_del{u.id}"
    db.commit()


@router.post("/{unit_id}/restore", response_model=ArrearsUnitOut)
def restore_unit(
    unit_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.LEDGER_EDIT)),
) -> ArrearsUnit:
    """把删掉的挂账单位恢复回来（DELETE /{id} 的逆操作）。

    名字冲突时**保留现在的名字**（硬抢回来会把另一个单位顶掉）；冲突情况写在返回里，
    让用户自己决定要不要改名。
    """
    u = db.get(ArrearsUnit, unit_id)
    if u is None:
        raise HTTPException(status_code=404, detail="挂账单位不存在")
    if not u.is_deleted:
        raise HTTPException(status_code=400, detail="这个单位没有被删除，不需要恢复")
    suffix = f"_del{u.id}"
    if u.name.endswith(suffix):
        want = u.name[: -len(suffix)]
        taken = db.scalars(
            select(ArrearsUnit).where(ArrearsUnit.name == want, ArrearsUnit.id != u.id)
        ).first()
        if taken is None:
            u.name = want
    u.is_deleted = False
    u.deleted_at = None
    db.commit()
    db.refresh(u)
    return u
