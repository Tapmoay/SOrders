"""司机结算单（按月）——账本 V2：DRAFT→CONFIRMED→PAID→CANCELLED 状态机。"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.rbac import user_role_key
from app.database import get_db
from app.deps import CurrentUser
from app.models import DriverSettlement, User
from app.models.enums import OperationAction, UserRole
from app.schemas.accounting_v2 import (
    DriverSettlementCreate,
    DriverSettlementOut,
    SettlementActionBody,
)
from app.services.operation_log_service import write_log

router = APIRouter(prefix="/driver-settlements", tags=["driver-settlements"])


def _must_dispatcher(current: User) -> None:
    if user_role_key(current) != UserRole.DISPATCHER.value:
        raise HTTPException(status_code=403, detail="仅派单员可操作")


@router.get("", response_model=list[DriverSettlementOut])
def list_settlements(
    current: CurrentUser,
    db: Session = Depends(get_db),
    driver_id: int | None = Query(None),
    month: str | None = Query(None, pattern=r"^\d{4}-\d{2}$"),
    status: str | None = Query(None),
) -> list[DriverSettlementOut]:
    role = user_role_key(current)
    if role == UserRole.DRIVER.value:
        driver_id = current.id
    elif role != UserRole.DISPATCHER.value:
        raise HTTPException(status_code=403, detail="仅派单员/司机可查看")
    stmt = select(DriverSettlement).order_by(DriverSettlement.month.desc(), DriverSettlement.id.desc())
    if driver_id is not None:
        stmt = stmt.where(DriverSettlement.driver_id == driver_id)
    if month:
        stmt = stmt.where(DriverSettlement.month == month)
    if status:
        stmt = stmt.where(DriverSettlement.status == status)
    rows = list(db.scalars(stmt).all())
    names: dict[int, str] = {}
    out = []
    for r in rows:
        if r.driver_id not in names:
            u = db.get(User, r.driver_id)
            names[r.driver_id] = (u.full_name or u.phone or "") if u else ""
        out.append(
            DriverSettlementOut(
                **{
                    "id": r.id,
                    "driver_id": r.driver_id,
                    "settle_type": r.settle_type,
                    "month": r.month,
                    "period_from": r.period_from,
                    "period_to": r.period_to,
                    "amount": r.amount,
                    "status": r.status,
                    "order_ids": r.order_ids,
                    "paid_at": r.paid_at,
                    "method": r.method,
                    "operator_id": r.operator_id,
                    "note": r.note,
                    "driver_name": names[r.driver_id],
                    "created_at": r.created_at,
                }
            )
        )
    return out


@router.post("", response_model=DriverSettlementOut)
def create_settlement(
    body: DriverSettlementCreate,
    current: CurrentUser,
    db: Session = Depends(get_db),
) -> DriverSettlementOut:
    _must_dispatcher(current)
    from app.services.accounting_service import create_settlement as svc_create

    try:
        s = svc_create(db, body, current.id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    # 建结算单＝把一批「待结」明细锁进一张单子（钱虽未出，但已经不能再被第二张单占用），必须留痕。
    # ⚠️ 先 flush 拿到 id：`write_log` 里要写 `settlement_id`，不 flush 的话 `s.id` 还是 None
    #    （实测踩到：日志写成了 `{"settlement_id": null}`，等于这条痕迹查不回是哪张单）。
    db.flush()
    write_log(
        db,
        operator_id=current.id,
        order_id=None,
        action=OperationAction.SETTLEMENT_CREATE,
        change_payload={
            "settlement_id": s.id,
            "driver_id": s.driver_id,
            "month": s.month,
            "settle_type": str(getattr(s.settle_type, "value", s.settle_type)),
            "amount": str(s.amount),
            "bill_count": len(s.order_ids or []),
        },
    )
    db.commit()
    db.refresh(s)
    u = db.get(User, s.driver_id)
    out = DriverSettlementOut(
        id=s.id, driver_id=s.driver_id, settle_type=s.settle_type, month=s.month,
        period_from=s.period_from, period_to=s.period_to, amount=s.amount, status=s.status,
        order_ids=s.order_ids, paid_at=None, method="", operator_id=s.operator_id, note=s.note,
        driver_name=(u.full_name or u.phone or "") if u else "", created_at=s.created_at,
    )
    return out


@router.patch("/{settlement_id}", response_model=DriverSettlementOut)
def settlement_action(
    settlement_id: int,
    body: SettlementActionBody,
    current: CurrentUser,
    db: Session = Depends(get_db),
) -> DriverSettlementOut:
    _must_dispatcher(current)
    from app.services.accounting_service import (
        cancel_settlement,
        confirm_settlement,
        pay_settlement,
    )

    s = db.get(DriverSettlement, settlement_id)
    if s is None:
        raise HTTPException(status_code=404, detail="结算单不存在")
    try:
        if body.action == "confirm":
            confirm_settlement(db, s, current.id)
        elif body.action == "pay":
            pay_settlement(db, s, body.method, current.id)
        elif body.action == "cancel":
            cancel_settlement(db, s, current.id)
        else:
            raise HTTPException(status_code=400, detail="不支持的动作")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    # confirm / pay / cancel 三个动作都要留痕（2026-09-19 审计）：
    # 「付款」尤其重要——钱真的出去了，而原来审计页一个字都没有。
    write_log(
        db,
        operator_id=current.id,
        order_id=None,
        action=OperationAction.SETTLEMENT_STATUS,
        change_payload={
            "settlement_id": s.id,
            "driver_id": s.driver_id,
            "action": body.action,
            "amount": str(s.amount),
            "status": str(getattr(s.status, "value", s.status)),
            "method": body.method if body.action == "pay" else None,
        },
    )
    db.commit()
    db.refresh(s)
    u = db.get(User, s.driver_id)
    return DriverSettlementOut(
        id=s.id, driver_id=s.driver_id, settle_type=s.settle_type, month=s.month,
        period_from=s.period_from, period_to=s.period_to, amount=s.amount, status=s.status,
        order_ids=s.order_ids, paid_at=s.paid_at, method=s.method, operator_id=s.operator_id,
        note=s.note, driver_name=(u.full_name or u.phone or "") if u else "", created_at=s.created_at,
    )