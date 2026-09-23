"""开销单（油费/维修/过路/停车/罚款/保险/货损/其他）——账本 V2。"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.date_window import date_window
from app.core.rbac import user_role_key
from app.database import get_db
from app.deps import CurrentUser
from app.models import Expense, ExpenseCategory, Order, User, Vehicle
from app.models.enums import OperationAction, UserRole
from app.services.operation_log_service import write_log
from app.schemas.accounting_v2 import ExpenseCreate, ExpenseOut

router = APIRouter(prefix="/expenses", tags=["expenses"])


@router.get("", response_model=list[ExpenseOut])
def list_expenses(
    current: CurrentUser,
    db: Session = Depends(get_db),
    category: str | None = Query(None),
    driver_id: int | None = Query(None),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
) -> list[ExpenseOut]:
    if user_role_key(current) != UserRole.DISPATCHER.value:
        raise HTTPException(status_code=403, detail="仅派单员可查看")
    stmt = select(Expense).order_by(Expense.exp_date.desc(), Expense.id.desc())
    if category:
        stmt = stmt.where(Expense.category == category)
    if driver_id is not None:
        stmt = stmt.where(Expense.driver_id == driver_id)
    # ⚠️ 同 `cash_flows`：日期窗口的校验只有一处（`core.date_window`），顺序反了必须 400，
    #    不许安静地返回空集 —— 界面会显示「这段时间没有开销」，那是错的（2026-09-24 第 19 轮）。
    start, end = date_window(date_from, date_to)
    if start is not None:
        stmt = stmt.where(Expense.exp_date >= start)
    if end is not None:
        stmt = stmt.where(Expense.exp_date <= end)
    rows = list(db.scalars(stmt).all())
    names: dict[int, str] = {}
    order_nos: dict[int, str] = {}
    # 车牌：卡片上「突出车辆」那一项要显示的就是它（车辆的名字就是车牌号）。
    # 按 id 缓存、一次查完 —— 不要每行查一次。
    plates: dict[int, str] = {}
    # 分类 → 「卡片突出哪一项」：**一次查完**（名册最多两百行），别每行查一次。
    link_kinds = {
        (str(getattr(n, "value", n) or "")).strip(): (k or "none")
        for n, k in db.execute(
            select(ExpenseCategory.name, ExpenseCategory.link_kind)
        ).all()
    }
    out = []
    for r in rows:
        if r.driver_id and r.driver_id not in names:
            u = db.get(User, r.driver_id)
            names[r.driver_id] = (u.full_name or u.phone or "") if u else ""
        if r.order_id and r.order_id not in order_nos:
            o = db.get(Order, r.order_id)
            order_nos[r.order_id] = o.order_no if o else ""
        if r.vehicle_id and r.vehicle_id not in plates:
            v = db.get(Vehicle, r.vehicle_id)
            plates[r.vehicle_id] = (v.plate_no or "") if v else ""
        out.append(
            ExpenseOut(
                id=r.id, exp_date=r.exp_date, category=r.category, amount=r.amount,
                driver_id=r.driver_id, vehicle_id=r.vehicle_id, order_id=r.order_id,
                note=r.note, operator_id=r.operator_id,
                driver_name=names.get(r.driver_id, ""), order_no=order_nos.get(r.order_id, ""),
                vehicle_name=plates.get(r.vehicle_id, ""),
                link_kind=link_kinds.get(str(getattr(r.category, "value", r.category)).strip(), "none"),
                created_at=r.created_at,
            )
        )
    return out


@router.post("", response_model=ExpenseOut)
def create_expense(
    body: ExpenseCreate,
    current: CurrentUser,
    db: Session = Depends(get_db),
) -> ExpenseOut:
    if user_role_key(current) != UserRole.DISPATCHER.value:
        raise HTTPException(status_code=403, detail="仅派单员可操作")
    from app.services.accounting_service import create_expense as svc_create

    try:
        e = svc_create(db, body, current.id)
    except ValueError as ex:
        raise HTTPException(status_code=400, detail=str(ex)) from ex
    # 开销＝钱出去了（还会写一条 cash_flows OUT），必须留痕（2026-09-19 审计）
    write_log(
        db,
        operator_id=current.id,
        order_id=e.order_id,
        action=OperationAction.EXPENSE_CREATE,
        change_payload={
            "expense_id": e.id,
            "category": str(getattr(e.category, "value", e.category)),
            "amount": str(e.amount),
            "exp_date": str(e.exp_date),
            "driver_id": e.driver_id,
            "vehicle_id": e.vehicle_id,
        },
    )
    db.commit()
    db.refresh(e)
    return ExpenseOut(
        id=e.id, exp_date=e.exp_date, category=e.category, amount=e.amount,
        driver_id=e.driver_id, vehicle_id=e.vehicle_id, order_id=e.order_id,
        note=e.note, operator_id=e.operator_id, created_at=e.created_at,
    )
