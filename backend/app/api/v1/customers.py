"""客户档案（注册用户/散客）——账本 V2：收款、欠款、挂账均需客户档案。"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.rbac import user_role_key
from app.database import get_db
from app.deps import CurrentUser
from app.models import Customer, User
from app.models.enums import CustomerKind, UserRole
from app.schemas.accounting_v2 import CustomerCreate, CustomerMergeBody, CustomerOut

router = APIRouter(prefix="/customers", tags=["customers"])


def _require_dispatcher(current: User) -> None:
    if user_role_key(current) != UserRole.DISPATCHER.value:
        raise HTTPException(status_code=403, detail="无权操作")


@router.get("", response_model=list[CustomerOut])
def list_customers(
    current: CurrentUser,
    db: Session = Depends(get_db),
    kind: str | None = Query(None, pattern="^(registered|tmp)$"),
    q: str | None = Query(None, description="名称/电话模糊"),
) -> list[CustomerOut]:
    _require_dispatcher(current)
    stmt = select(Customer).order_by(Customer.id.desc())
    if kind:
        stmt = stmt.where(Customer.kind == kind)
    if q and q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(Customer.name.like(like) | Customer.phone.like(like))
    return list(db.scalars(stmt).all())


@router.post("", response_model=CustomerOut)
def create_customer(
    body: CustomerCreate,
    current: CurrentUser,
    db: Session = Depends(get_db),
) -> CustomerOut:
    _require_dispatcher(current)
    if body.kind == "tmp" and body.phone and body.phone.strip():
        dup = db.scalars(
            select(Customer).where(
                Customer.kind == CustomerKind.TMP,
                Customer.phone == body.phone.strip(),
            )
        ).first()
        if dup is not None:
            return dup  # 电话一致视为同一散客，复用档案
    if body.user_id is not None:
        dup = db.scalars(select(Customer).where(Customer.user_id == body.user_id)).first()
        if dup is not None:
            return dup
    c = Customer(
        kind=body.kind,
        user_id=body.user_id,
        name=body.name.strip(),
        phone=(body.phone or "").strip() or None,
        is_member=body.is_member,
        arrears_unit_id=body.arrears_unit_id,
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


@router.post("/merge", response_model=CustomerOut)
def merge_customers(
    body: CustomerMergeBody,
    current: CurrentUser,
    db: Session = Depends(get_db),
) -> CustomerOut:
    _require_dispatcher(current)
    keep = db.get(Customer, body.keep_id)
    if keep is None:
        raise HTTPException(status_code=404, detail="保留客户不存在")
    for mid in body.merge_ids:
        m = db.get(Customer, mid)
        if m is None:
            continue
        from app.models import Ledger

        ledgers = list(db.scalars(select(Ledger).where(Ledger.customer_id == mid)))
        for lg in ledgers:
            lg.customer_id = keep.id
        db.delete(m)
    db.commit()
    db.refresh(keep)
    return keep
