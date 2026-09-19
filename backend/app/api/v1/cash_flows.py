"""资金流水总账查询——账本 V2（所有收付的唯一写入点由各业务钩子保证）。"""

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from app.core.pagination import finish_page
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.core.rbac import user_role_key
from app.database import get_db
from app.deps import CurrentUser
from app.models import CashFlow, User
from app.models.enums import UserRole
from app.schemas.accounting_v2 import CashFlowOut

router = APIRouter(prefix="/cash-flows", tags=["cash-flows"])


def _scoped_stmt(
    current: User, direction: str | None, biz_type: str | None,
    party_type: str | None, party_id: int | None,
    date_from: date | None, date_to: date | None,
):
    """列表与汇总**共用**同一套筛选（两处各写一遍必然走散）。"""
    stmt = select(CashFlow)
    if direction:
        # 大小写不敏感（枚举是小写 in/out）：写死大写会让这一页的流入恒为 0
        stmt = stmt.where(func.lower(CashFlow.direction) == direction.lower())
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
    return stmt


@router.get("", response_model=list[CashFlowOut])
def list_cash_flows(
    current: CurrentUser,
    response: Response,
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
    stmt = (
        _scoped_stmt(current, direction, biz_type, party_type, party_id, date_from, date_to)
        .order_by(CashFlow.flow_date.desc(), CashFlow.id.desc())
        # 多取一行：拿到 limit+1 行就说明还有更多（`finish_page` 据此写 X-Truncated）
        .limit(limit + 1)
    )
    return finish_page(list(db.scalars(stmt).all()), limit, response)


@router.get("/summary")
def cash_flow_summary(
    current: CurrentUser,
    db: Session = Depends(get_db),
    direction: str | None = Query(None),
    biz_type: str | None = Query(None),
    party_type: str | None = Query(None),
    party_id: int | None = Query(None),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
) -> dict:
    """**服务端**汇总流入/流出/净额（与列表同一套筛选）。

    ⚠️ 为什么必须有这个端点（2026-09-19 审计）：客户端原来是"拉一页流水、自己求和"，
    而 `GET /cash-flows` 有 `limit`（默认 200）。实测同一窗口：默认 limit 只拿到 200 条、
    求和流入 **¥18,842**；limit=1000 拿到 273 条、流入 **¥48,905.50** —— 页面少算 62%，
    而同一页的 Excel 导出是**在 SQL 侧全窗口求和**的（真值）。于是"页面一个数、导出一个数"。
    金额必须在数据库里算完再给客户端，客户端的 limit 只影响"看得见几行明细"。
    """
    if user_role_key(current) != UserRole.DISPATCHER.value:
        raise HTTPException(status_code=403, detail="仅派单员可查看")
    stmt = _scoped_stmt(current, direction, biz_type, party_type, party_id, date_from, date_to)
    scoped = stmt.subquery()
    row = db.execute(
        select(
            func.coalesce(
                func.sum(case((func.lower(scoped.c.direction) == "in", scoped.c.amount), else_=0)),
                0,
            ),
            func.coalesce(
                func.sum(case((func.lower(scoped.c.direction) == "out", scoped.c.amount), else_=0)),
                0,
            ),
            func.count(),
        ).select_from(scoped)
    ).one()
    income = Decimal(str(row[0] or 0))
    expense = Decimal(str(row[1] or 0))
    return {
        "income": str(income),
        "expense": str(expense),
        "net": str(income - expense),
        "count": int(row[2] or 0),
    }
