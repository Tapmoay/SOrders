"""资金流水总账查询——账本 V2（所有收付的唯一写入点由各业务钩子保证）。"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.rbac import user_role_key
from app.database import get_db
from app.deps import CurrentUser
from app.models import CashFlow, User
from app.models.enums import UserRole
from app.schemas.accounting_v2 import CashFlowOut

router = APIRouter(prefix="/cash-flows", tags=["cash-flows"])


@router.get("", response_model=list[CashFlowOut])
def list_cash_flows(
    current: CurrentUser,
    db: Session = Depends(get_db),
    direction: str | None = Query(None),
    biz_type: str | None = Query(None),
    party_type: str | None = Query(None),
    party_id: int | None = Query(None),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    limit: int = Query(200, ge=1, le=1000),
) -> list[CashFlowOut]:
    if user_role_key(current) != UserRole.DISPATCHER.value:
        raise HTTPException(status_code=403, detail="仅派单员可查看")
    stmt = select(CashFlow).order_by(CashFlow.flow_date.desc(), CashFlow.id.desc()).limit(limit)
    if direction:
        stmt = stmt.where(CashFlow.direction == direction)
    if biz_type:
        stmt = stmt.where(CashFlow.biz_type == biz_type)
    if party_type:
        stmt = stmt.where(CashFlow.party_type == party_type)
    if party_id is not None:
        stmt = stmt.where(CashFlow.party_id == party_id)
    if date_from:
        stmt = stmt.where(CashFlow.flow_date >= date_from)
    if date_to:
        stmt = stmt.where(CashFlow.flow_date <= date_to)
    return list(db.scalars(stmt).all())
