"""开销分类名册（派单员维护；决定开销页左侧那一列与卡片上突出哪一项）。

与 `product_categories.py` **同一套规矩**（改名前先读那边顶部的说明）：

1. **改名要级联**：同一事务里把 `expenses.category` 从旧名改成新名 —— 不级联的话那些开销
   会变成"名册外的分类"，而且**不报错**（用户只会觉得"我的开销跑哪去了"）；
2. **新建开销时带了名册里没有的分类名 → 自动补进名册**（排到最后），
   否则派单员要先建分类再记开销，两步做完才能用；
3. **删除还有开销挂着的分类 → 拒绝**（告诉还有几笔）。
   不提供"顺手把那些开销改成别的分类"的便利：那是**悄悄改数据**，改完看不出来。

⚠️ 名册里没有的分类名**不是错误**（老数据、别的路径写进去的）。列表接口把它排在名册后面
（见 `_out` 的调用方与 `list_categories`），**不许因为它不在名册里就把开销藏起来**。
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.rbac import user_role_key
from app.database import get_db
from app.deps import CurrentUser
from app.models import Expense, ExpenseCategory
from app.models.enums import OperationAction, UserRole
from app.schemas.expense_category import (
    ExpenseCategoryCreate,
    ExpenseCategoryOut,
    ExpenseCategoryReorder,
    ExpenseCategoryUpdate,
)
from app.services.category_order import ordered_ids
from app.services.operation_log_service import write_log

router = APIRouter(prefix="/expense-categories", tags=["expense-categories"])

MAX_CATEGORIES = 200


def _counts(db: Session) -> dict[str, int]:
    """分类名 → 在用开销笔数（**一次查完**，不要每个分类查一遍）。"""
    rows = db.execute(
        select(Expense.category, func.count(Expense.id)).group_by(Expense.category)
    ).all()
    return {(str(getattr(name, "value", name) or "")).strip(): n for name, n in rows if str(name or "").strip()}


def _out(row: ExpenseCategory, counts: dict[str, int]) -> ExpenseCategoryOut:
    o = ExpenseCategoryOut.model_validate(row)
    o.expense_count = counts.get(row.name, 0)
    return o


def _next_sort(db: Session) -> int:
    top = db.scalar(select(func.max(ExpenseCategory.sort_order)))
    return (top or 0) + 1


def ensure_category(db: Session, name: str, link_kind: str = "none") -> ExpenseCategory | None:
    """确保这个分类名在名册里（不在就补到最后）。给新开销复用。

    返回被新建的名册行；已经在名册里则返回 None（调用方据此决定要不要记日志）。
    """
    clean = (name or "").strip()[:32]
    if not clean:
        return None
    exists = db.scalars(select(ExpenseCategory).where(ExpenseCategory.name == clean)).first()
    if exists is not None:
        return None
    row = ExpenseCategory(name=clean, sort_order=_next_sort(db), link_kind=link_kind or "none")
    db.add(row)
    db.flush()
    return row


def _legacy_names(db: Session, known: set[str]) -> list[str]:
    """在库里出现过、但名册里没有的分类名（老数据 / 别的路径写进去的）。

    ⚠️ 必须排在名册**后面**且**不能丢**：不在名册里不等于这笔开销不存在。
    """
    rows = db.execute(select(Expense.category, func.count(Expense.id)).group_by(Expense.category)).all()
    names = [
        ((str(getattr(n, "value", n) or "")).strip(), c)
        for n, c in rows
        if (str(getattr(n, "value", n) or "")).strip()
    ]
    return [n for n, _ in sorted(names, key=lambda x: -x[1]) if n not in known]


@router.get("", response_model=list[ExpenseCategoryOut])
def list_categories(current: CurrentUser, db: Session = Depends(get_db)) -> list[ExpenseCategoryOut]:
    """开销分类名册（按显示顺序）。**仅派单员**（开销这一块本来就只有他能看）。"""
    if user_role_key(current) != UserRole.DISPATCHER.value:
        raise HTTPException(status_code=403, detail="仅派单员可查看")
    rows = db.scalars(
        select(ExpenseCategory).order_by(ExpenseCategory.sort_order, ExpenseCategory.id)
    ).all()
    counts = _counts(db)
    out = [_out(r, counts) for r in rows]
    # 名册外的分类名（老数据）排在最后：卡片上仍然能按它筛，只是没得排序/改名
    used = {r.name for r in rows}
    for name in _legacy_names(db, used):
        out.append(
            ExpenseCategoryOut(
                id=0, name=name, sort_order=10_000, link_kind="none",
                expense_count=counts.get(name, 0),
            )
        )
    return out


@router.post("", response_model=ExpenseCategoryOut, status_code=status.HTTP_201_CREATED)
def create_category(
    body: ExpenseCategoryCreate,
    current: CurrentUser,
    db: Session = Depends(get_db),
) -> ExpenseCategoryOut:
    if user_role_key(current) != UserRole.DISPATCHER.value:
        raise HTTPException(status_code=403, detail="仅派单员可操作")
    exists = db.scalars(select(ExpenseCategory).where(ExpenseCategory.name == body.name)).first()
    if exists is not None:
        raise HTTPException(status_code=409, detail=f"分类「{body.name}」已经存在了")
    total = db.scalar(select(func.count(ExpenseCategory.id))) or 0
    if total >= MAX_CATEGORIES:
        raise HTTPException(status_code=400, detail=f"分类最多 {MAX_CATEGORIES} 个，请先清理一些")
    row = ExpenseCategory(
        name=body.name,
        sort_order=body.sort_order if body.sort_order is not None else _next_sort(db),
        link_kind=body.link_kind,
    )
    db.add(row)
    db.flush()
    write_log(
        db,
        operator_id=current.id,
        order_id=None,
        action=OperationAction.EXPENSE_CATEGORY_UPSERT,
        change_payload={
            "category_id": row.id, "name": row.name,
            "sort_order": row.sort_order, "link_kind": row.link_kind, "op": "create",
        },
    )
    db.commit()
    db.refresh(row)
    return _out(row, _counts(db))


@router.patch("/{category_id}", response_model=ExpenseCategoryOut)
def update_category(
    category_id: int,
    body: ExpenseCategoryUpdate,
    current: CurrentUser,
    db: Session = Depends(get_db),
) -> ExpenseCategoryOut:
    if user_role_key(current) != UserRole.DISPATCHER.value:
        raise HTTPException(status_code=403, detail="仅派单员可操作")
    """改名 / 改顺序 / 改"突出哪一项"。**改名会级联改掉挂在它下面的开销**（同一事务）。"""
    row = db.get(ExpenseCategory, category_id)
    if row is None:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    changes: list[dict] = []
    if body.name is not None and body.name != row.name:
        clash = db.scalars(
            select(ExpenseCategory).where(
                ExpenseCategory.name == body.name, ExpenseCategory.id != row.id
            )
        ).first()
        if clash is not None:
            raise HTTPException(status_code=409, detail=f"分类「{body.name}」已经存在了")
        old_name = row.name
        moved = db.execute(
            Expense.__table__.update().where(Expense.category == old_name).values(category=body.name)
        ).rowcount
        row.name = body.name
        changes.append({"field": "name", "from": old_name, "to": body.name, "expenses_moved": moved})
    if body.sort_order is not None and body.sort_order != row.sort_order:
        changes.append({"field": "sort_order", "from": row.sort_order, "to": body.sort_order})
        row.sort_order = body.sort_order
    if body.link_kind is not None and body.link_kind != row.link_kind:
        changes.append({"field": "link_kind", "from": row.link_kind, "to": body.link_kind})
        row.link_kind = body.link_kind
    if changes:
        write_log(
            db,
            operator_id=current.id,
            order_id=None,
            action=OperationAction.EXPENSE_CATEGORY_UPSERT,
            change_payload={"category_id": row.id, "op": "update", "changes": changes},
        )
    db.commit()
    db.refresh(row)
    return _out(row, _counts(db))


@router.post("/reorder", response_model=list[ExpenseCategoryOut])
def reorder_categories(
    body: ExpenseCategoryReorder,
    current: CurrentUser,
    db: Session = Depends(get_db),
) -> list[ExpenseCategoryOut]:
    if user_role_key(current) != UserRole.DISPATCHER.value:
        raise HTTPException(status_code=403, detail="仅派单员可操作")
    """整份顺序一次提交：`ids[0]` 排最前。

    ⚠️ **必须整份提交**（ids 要覆盖全部现存分类）：只传一部分的话，"没提到的那些该排哪儿"
    是没有答案的 —— 按"没提到的保持原序"实现，会在两端各错一次而且看不出来。
    """
    rows = db.scalars(select(ExpenseCategory)).all()
    by_id = {r.id: r for r in rows}
    # 整份顺序的校验四个名册共用一份（理由见 services/category_order.py）
    ids = ordered_ids(by_id, body.ids)
    for idx, cid in enumerate(ids):
        by_id[cid].sort_order = idx
    write_log(
        db,
        operator_id=current.id,
        order_id=None,
        action=OperationAction.EXPENSE_CATEGORY_REORDER,
        change_payload={"order": [{"id": i, "name": by_id[i].name} for i in ids]},
    )
    db.commit()
    counts = _counts(db)
    return [_out(by_id[i], counts) for i in ids]


@router.delete("/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_category(
    category_id: int,
    current: CurrentUser,
    db: Session = Depends(get_db),
) -> None:
    if user_role_key(current) != UserRole.DISPATCHER.value:
        raise HTTPException(status_code=403, detail="仅派单员可操作")
    """删除名册里的一行。**还有开销挂着时拒绝**（告诉有几笔）。"""
    row = db.get(ExpenseCategory, category_id)
    if row is None:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    used = db.scalar(select(func.count(Expense.id)).where(Expense.category == row.name)) or 0
    if used:
        raise HTTPException(
            status_code=400,
            detail=f"还有 {used} 笔开销挂在这个分类下，先把它们改成别的分类（或改个名）再删",
        )
    write_log(
        db,
        operator_id=current.id,
        order_id=None,
        action=OperationAction.EXPENSE_CATEGORY_DELETE,
        change_payload={"category_id": row.id, "name": row.name},
    )
    db.delete(row)
    db.commit()
