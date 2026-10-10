"""开销单（油费/维修/过路/停车/罚款/保险/货损/其他）——账本 V2。

## 撤销与恢复（2026-10-10，BUG-0034 / 台账 TA-16）

台账原文是「开销（expenses）全系统没有任何删除或修改入口：**记错一笔永久留在账上**」。
用户 2026-09-20 定的硬规矩是「**所有删除一律软删 ＋ 必须有恢复路径 ＋ 界面要有手边的撤销入口**」，
所以这里补两条端点：

* `DELETE /expenses/{id}`（204）＝ 把这条开销**与它写下的那条资金流水**一起打标记
  （`is_deleted=1` / `deleted_at=now`），两边的合计当场各自少这一笔；
* `POST /expenses/{id}/restore`（200）＝ **原样放回来**（金额/分类/司机/车辆/订单一个字节都不动）。

⛔ 一个字节都不许改金额算法（`services/accounting_service.py` 是核心区）：撤销只是给已有的行
打标记，恢复只是把标记抹掉 —— 所以"删掉一笔之后合计正好少这一笔"这个等式是天生的，
不是靠重算凑出来的。判据：`_tools/finance/_check_expense_soft_delete.py`。
"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.business_time import utc_now_naive
from app.core.date_window import date_window
from app.database import get_db
from app.deps import DispatcherUser
from app.models import CashFlow, Expense, ExpenseCategory, Order, User, Vehicle
from app.models.enums import OperationAction
from app.services.operation_log_service import write_log
from app.schemas.accounting_v2 import ExpenseCreate, ExpenseOut

router = APIRouter(prefix="/expenses", tags=["expenses"])


def _expense_flows(db: Session, expense_id: int) -> list[CashFlow]:
    """这条开销写下的资金流水。

    **唯一判据**：`party_type='expense'` + `party_id=expenses.id` —— 与
    `services/accounting_service.py::write_expense_cash_flow` 的写入形状是同一处事实的两面。
    ⛔ 不许改成"按金额 + 日期猜"：同一天同金额的两笔油费会被配错，那比不撤更糟。
    """
    return list(
        db.scalars(
            select(CashFlow).where(
                CashFlow.party_type == "expense",
                CashFlow.party_id == expense_id,
            )
        ).all()
    )


def _link_kinds(db: Session) -> dict[str, str]:
    """分类 → 「卡片突出哪一项」。一次查完（名册最多两百行），别每行查一次。"""
    return {
        (str(getattr(n, "value", n) or "")).strip(): (k or "none")
        for n, k in db.execute(select(ExpenseCategory.name, ExpenseCategory.link_kind)).all()
    }


def _to_out(
    db: Session,
    r: Expense,
    link_kinds: dict[str, str],
    names: dict[int, str],
    order_nos: dict[int, str],
    plates: dict[int, str],
) -> ExpenseOut:
    """一行开销 → 出参（名字/车牌/单号按 id 缓存，一次查完）。"""
    if r.driver_id and r.driver_id not in names:
        u = db.get(User, r.driver_id)
        names[r.driver_id] = (u.full_name or u.phone or "") if u else ""
    if r.order_id and r.order_id not in order_nos:
        o = db.get(Order, r.order_id)
        order_nos[r.order_id] = o.order_no if o else ""
    if r.vehicle_id and r.vehicle_id not in plates:
        v = db.get(Vehicle, r.vehicle_id)
        plates[r.vehicle_id] = (v.plate_no or "") if v else ""
    return ExpenseOut(
        id=r.id, exp_date=r.exp_date, category=r.category, amount=r.amount,
        driver_id=r.driver_id, vehicle_id=r.vehicle_id, order_id=r.order_id,
        note=r.note, operator_id=r.operator_id,
        driver_name=names.get(r.driver_id, ""), order_no=order_nos.get(r.order_id, ""),
        vehicle_name=plates.get(r.vehicle_id, ""),
        link_kind=link_kinds.get(str(getattr(r.category, "value", r.category)).strip(), "none"),
        created_at=r.created_at,
        is_deleted=bool(r.is_deleted), deleted_at=r.deleted_at,
    )


@router.get("", response_model=list[ExpenseOut])
def list_expenses(
    current: DispatcherUser,
    db: Session = Depends(get_db),
    category: str | None = Query(None),
    driver_id: int | None = Query(None),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    deleted_only: bool = Query(
        False,
        description=(
            "true = 只看**已撤销**的（界面顶上那颗「显示已撤销」档）。"
            "默认 false = 只看还活着的（软删的行默认不出现）。"
        ),
    ),
) -> list[ExpenseOut]:
    stmt = select(Expense).order_by(Expense.exp_date.desc(), Expense.id.desc())
    # ⛔ 软删的行默认**不出现**（2026-10-10 BUG-0034）：少了这一句，撤销过的开销照样列在
    #    「开销管理」里，用户会以为撤销没生效、然后再撤一次。
    #    档位是"二选一"而不是"含已撤销"：这一页顶上的合计是客户端按列出来的行求和的，
    #    两档混在一起那笔数就说不清是"这段时间的开销"还是"连撤销的也算"。
    stmt = stmt.where(Expense.is_deleted.is_(deleted_only))
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
    link_kinds = _link_kinds(db)
    names: dict[int, str] = {}
    order_nos: dict[int, str] = {}
    plates: dict[int, str] = {}
    return [_to_out(db, r, link_kinds, names, order_nos, plates) for r in rows]


@router.post("", response_model=ExpenseOut)
def create_expense(
    body: ExpenseCreate,
    current: DispatcherUser,
    db: Session = Depends(get_db),
) -> ExpenseOut:
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


@router.delete("/{expense_id}", status_code=status.HTTP_204_NO_CONTENT)
def cancel_expense(
    expense_id: int,
    current: DispatcherUser,
    db: Session = Depends(get_db),
) -> Response:
    """**撤销**一笔开销（软删；可 `POST /expenses/{id}/restore` 原样放回）。

    ## 撤销同时做两件事（少一件账上就是两个答案）
    ① 这条开销写下的资金流水打标记（`is_deleted=1`、记 `deleted_at`）——
       「收支」页的流出、资金流水明细里的这一笔当场不算数；
    ② 开销单本身打标记 —— 它默认从「开销管理」里消失，只在回收站档
       （`deleted_only=true`）里看得见，那一档就是「恢复」的落点。

    ⛔ **不是物理删除**（用户定的硬规矩）：两处的行都还在，restore 原样放回来。
    ⛔ 已经撤销过的不能再撤（400）—— 那会把账上的数改第二遍。
    ⛔ 金额算法一个字节都没动：这里只打标记，`services/accounting_service.py` 不被调用。
    """
    e = db.scalar(select(Expense).where(Expense.id == expense_id).with_for_update())
    if e is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="这笔开销不存在")
    if e.is_deleted:
        raise HTTPException(status_code=400, detail=f"这笔开销（#{e.id}）已经撤销过了，不用再撤一次")
    flows = _expense_flows(db, e.id)
    now = utc_now_naive()
    for f in flows:
        f.is_deleted = True
        f.deleted_at = now
    e.is_deleted = True
    e.deleted_at = now
    write_log(
        db,
        operator_id=current.id,
        order_id=e.order_id,
        action=OperationAction.EXPENSE_DELETE,
        change_payload={
            "expense_id": e.id,
            "category": str(getattr(e.category, "value", e.category)),
            "amount": str(e.amount),
            "exp_date": str(e.exp_date),
            "driver_id": e.driver_id,
            "vehicle_id": e.vehicle_id,
            "order_id": e.order_id,
            "flow_ids": [f.id for f in flows],
            "note": "撤销开销（伪装删除）：开销单与它写下的流水都只打标记，可 restore 原样放回",
        },
    )
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{expense_id}/restore", response_model=ExpenseOut)
def restore_expense(
    expense_id: int,
    current: DispatcherUser,
    db: Session = Depends(get_db),
) -> ExpenseOut:
    """**恢复**一笔被撤销的开销（开销单 + 它写下的流水，两处原样放回）。

    只有**已撤销**的才能恢复（没撤过 → 400）：第二次恢复不许把数改回来第二遍。
    ⛔ 一个字段都不动 —— 金额/分类/司机/车辆/订单就是撤销前那一份；
       恢复靠的是 `is_deleted=0` + `deleted_at=NULL`，不是"按出参重建一条"。
    """
    e = db.scalar(select(Expense).where(Expense.id == expense_id).with_for_update())
    if e is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="这笔开销不存在")
    if not e.is_deleted:
        raise HTTPException(status_code=400, detail=f"这笔开销（#{e.id}）没有被撤销，不需要恢复")
    flows = _expense_flows(db, e.id)
    for f in flows:
        f.is_deleted = False
        f.deleted_at = None
    e.is_deleted = False
    e.deleted_at = None
    write_log(
        db,
        operator_id=current.id,
        order_id=e.order_id,
        action=OperationAction.EXPENSE_RESTORE,
        change_payload={
            "expense_id": e.id,
            "category": str(getattr(e.category, "value", e.category)),
            "amount": str(e.amount),
            "exp_date": str(e.exp_date),
            "driver_id": e.driver_id,
            "vehicle_id": e.vehicle_id,
            "order_id": e.order_id,
            "flow_ids": [f.id for f in flows],
            "note": "恢复开销：开销单与它写下的流水原样放回（金额/分类/关联一个字节都没改）",
        },
    )
    db.commit()
    db.refresh(e)
    return _to_out(db, e, _link_kinds(db), {}, {}, {})
