"""司机应付明细（按月）——账本 V2：送达自动生成 PIECE 单；月薪单手工/定时生成。"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.rbac import user_role_key
from app.database import get_db
from app.deps import CurrentUser
from app.models import DriverBill, User
from app.models.enums import DriverBillStatus, DriverBillType, UserRole
from app.schemas.accounting_v2 import DriverBillGenerateBody, DriverBillOut

router = APIRouter(prefix="/driver-bills", tags=["driver-bills"])


def _can_view_or_raise(current: User, db: Session, driver_id: int) -> None:
    role = user_role_key(current)
    if role == UserRole.DISPATCHER.value:
        return
    if role == UserRole.DRIVER.value and driver_id == current.id:
        return
    raise HTTPException(status_code=403, detail="无权操作")


@router.get("", response_model=list[DriverBillOut])
def list_driver_bills(
    current: CurrentUser,
    db: Session = Depends(get_db),
    driver_id: int | None = Query(None),
    month: str | None = Query(None, pattern=r"^\d{4}-\d{2}$"),
    status: str | None = Query(None),
    bill_type: str | None = Query(None),
) -> list[DriverBillOut]:
    role = user_role_key(current)
    if role != UserRole.DISPATCHER.value and role != UserRole.DRIVER.value:
        raise HTTPException(status_code=403, detail="仅派单员/司机可查看")
    if role == UserRole.DRIVER.value:
        driver_id = current.id
    stmt = select(DriverBill).order_by(DriverBill.month.desc(), DriverBill.id.desc())
    if driver_id is not None:
        stmt = stmt.where(DriverBill.driver_id == driver_id)
    if month:
        stmt = stmt.where(DriverBill.month == month)
    if status:
        stmt = stmt.where(DriverBill.status == status)
    if bill_type:
        stmt = stmt.where(DriverBill.bill_type == bill_type)
    rows = list(db.scalars(stmt).all())
    names: dict[int, str] = {}
    out = []
    for r in rows:
        if r.driver_id not in names:
            u = db.get(User, r.driver_id)
            names[r.driver_id] = (u.full_name or u.phone or "") if u else ""
        from app.models import Order

        order_no = ""
        if r.order_id:
            o = db.get(Order, r.order_id)
            order_no = o.order_no if o else ""
        out.append(
            DriverBillOut(
                **{
                    "id": r.id,
                    "driver_id": r.driver_id,
                    "bill_type": r.bill_type,
                    "order_id": r.order_id,
                    "month": r.month,
                    "amount": r.amount,
                    "status": r.status,
                    "settled_doc_id": r.settled_doc_id,
                    "note": r.note,
                    "driver_name": names[r.driver_id],
                    "order_no": order_no,
                }
            )
        )
    return out


@router.post("/generate", response_model=list[DriverBillOut])
def generate_bills(
    body: DriverBillGenerateBody,
    current: CurrentUser,
    db: Session = Depends(get_db),
) -> list[DriverBillOut]:
    """SALARY：对指定司机（或全部在职薪资司机）生成当月月薪单（幂等）；PIECE：该月已送达未生成的补单（幂等）。"""
    if user_role_key(current) != UserRole.DISPATCHER.value:
        raise HTTPException(status_code=403, detail="仅派单员可操作")
    from decimal import Decimal

    if body.bill_type == DriverBillType.SALARY:
        stmt = select(User).where(User.role == UserRole.DRIVER.value, User.billing_mode == "salary")
        if body.driver_id is not None:
            stmt = stmt.where(User.id == body.driver_id)
        drivers = list(db.scalars(stmt))
        created = []
        for d in drivers:
            exists = db.scalars(
                select(DriverBill).where(
                    DriverBill.driver_id == d.id,
                    DriverBill.bill_type == DriverBillType.SALARY,
                    DriverBill.month == body.month,
                )
            ).first()
            if exists is not None:
                continue
            sal = d.salary or Decimal("0")
            if sal <= 0:
                continue
            b = DriverBill(
                driver_id=d.id,
                bill_type=DriverBillType.SALARY,
                month=body.month,
                amount=sal,
                status=DriverBillStatus.OPEN,
                note="月度工资单（自动生成）",
            )
            db.add(b)
            created.append(b)
        db.commit()
        return created
    else:
        # PIECE 补单：该月送达、PIECE、运费非空的订单
        from app.models import Order
        from app.models.enums import OrderStatus

        stmt = (
            select(Order)
            .where(Order.status == OrderStatus.DELIVERED)
            .where(Order.driver_billing_mode_snapshot == "PIECE")
            .where(Order.freight_fee.isnot(None))
        )
        if body.driver_id is not None:
            stmt = stmt.where(Order.driver_id == body.driver_id)
        orders = list(db.scalars(stmt))
        created = []
        for o in orders:
            if o.delivered_at is None or o.delivered_at.strftime("%Y-%m") != body.month:
                continue
            exists = db.scalars(
                select(DriverBill).where(
                    DriverBill.order_id == o.id,
                    DriverBill.bill_type == DriverBillType.PIECE,
                )
            ).first()
            if exists is not None:
                continue
            b = DriverBill(
                driver_id=o.driver_id or 0,
                bill_type=DriverBillType.PIECE,
                order_id=o.id,
                month=body.month,
                amount=o.freight_fee,
                status=DriverBillStatus.OPEN,
                note="订单运费（补单）",
            )
            db.add(b)
            created.append(b)
        db.commit()
        return created