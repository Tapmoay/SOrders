"""运费分类名册（派单员维护）——增 / 改名 / 排序 / 删除（照商品分类、开销分类同一套规矩）。

## 三条硬规矩（与商品分类、开销分类一字不差）

1. **改名不级联任何东西**：两条线（运费模板、计费规则）都是按**编号**关联的，
   改名天然安全。⚠️ 但**订单上的名字快照**（`orders.freight_category`）**有意不追改** ——
   历史单据要能独立复核（"当时按哪一类货算的"）。
2. **删除还有人在用 → 拒绝**，并告诉用户"几条价目 / 几份规则挂着它"。
   不提供"顺手解绑"的便利：那是悄悄改数据，改完在界面上看不出来。
3. **顺序整份提交**（`POST /reorder`）：只传一部分的话，"没提到的那些排哪儿"没有答案。

⛔ 权限一律 `ORDER_DISPATCH`（派单员）：这是**内部定价口径**的分类，
   货主/司机不需要看到（与商品分类不同 —— 那个下单页要用，所以对所有人可读）。
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.rbac import Permission
from app.database import get_db
from app.deps import require_permission
from app.models import DriverBillingRule, DriverBillingRuleCategory, FreightCategory
from app.models import FreightTemplate, FreightTemplateCategory, User
from app.models.enums import OperationAction
from app.schemas.freight_category import (
    FreightCategoryCreate,
    FreightCategoryOut,
    FreightCategoryReorder,
    FreightCategoryUpdate,
)
from app.services.category_order import ordered_ids
from app.services.operation_log_service import write_log

router = APIRouter(prefix="/freight-categories", tags=["freight-categories"])

MAX_CATEGORIES = 200


def _counts(db: Session) -> tuple[dict[int, int], dict[int, int]]:
    """两个计数（一次查完，别按行查）：分类 → 几条价目 / 几份规则。"""
    t_rows = db.execute(
        select(FreightTemplateCategory.category_id, func.count(FreightTemplateCategory.id))
        .join(FreightTemplate, FreightTemplate.id == FreightTemplateCategory.template_id)
        .where(FreightTemplate.is_deleted.is_(False))
        .group_by(FreightTemplateCategory.category_id)
    ).all()
    r_rows = db.execute(
        select(DriverBillingRuleCategory.category_id, func.count(DriverBillingRuleCategory.id))
        .join(DriverBillingRule, DriverBillingRule.id == DriverBillingRuleCategory.rule_id)
        .where(DriverBillingRule.is_deleted.is_(False))
        .group_by(DriverBillingRuleCategory.category_id)
    ).all()
    return {cid: n for cid, n in t_rows}, {cid: n for cid, n in r_rows}


def _out(row: FreightCategory, t: dict[int, int], r: dict[int, int]) -> FreightCategoryOut:
    o = FreightCategoryOut.model_validate(row)
    o.template_count = t.get(row.id, 0)
    o.rule_count = r.get(row.id, 0)
    return o


def _next_sort(db: Session) -> int:
    top = db.scalar(select(func.max(FreightCategory.sort_order)))
    return (top or 0) + 1


@router.get("", response_model=list[FreightCategoryOut])
def list_categories(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.ORDER_DISPATCH)),
) -> list[FreightCategoryOut]:
    """运费分类名册（按显示顺序）。运费模板页与计费规则页共用这一份。"""
    rows = db.scalars(
        select(FreightCategory).order_by(FreightCategory.sort_order, FreightCategory.id)
    ).all()
    t, r = _counts(db)
    return [_out(row, t, r) for row in rows]


@router.post("", response_model=FreightCategoryOut, status_code=status.HTTP_201_CREATED)
def create_category(
    body: FreightCategoryCreate,
    current: User = Depends(require_permission(Permission.ORDER_DISPATCH)),
    db: Session = Depends(get_db),
) -> FreightCategoryOut:
    exists = db.scalars(select(FreightCategory).where(FreightCategory.name == body.name)).first()
    if exists is not None:
        raise HTTPException(status_code=409, detail=f"分类「{body.name}」已经存在了")
    total = db.scalar(select(func.count(FreightCategory.id))) or 0
    if total >= MAX_CATEGORIES:
        raise HTTPException(status_code=400, detail=f"分类最多 {MAX_CATEGORIES} 个，请先清理一些")
    row = FreightCategory(
        name=body.name,
        sort_order=body.sort_order if body.sort_order is not None else _next_sort(db),
    )
    db.add(row)
    db.flush()
    write_log(
        db,
        operator_id=current.id,
        order_id=None,
        action=OperationAction.FREIGHT_CATEGORY_UPSERT,
        change_payload={"category_id": row.id, "name": row.name, "sort_order": row.sort_order, "op": "create"},
    )
    db.commit()
    db.refresh(row)
    t, r = _counts(db)
    return _out(row, t, r)


@router.patch("/{category_id}", response_model=FreightCategoryOut)
def update_category(
    category_id: int,
    body: FreightCategoryUpdate,
    current: User = Depends(require_permission(Permission.ORDER_DISPATCH)),
    db: Session = Depends(get_db),
) -> FreightCategoryOut:
    """改名 / 改顺序。**不需要级联**：两条线都按编号关联（见模块注释第 1 条）。"""
    row = db.get(FreightCategory, category_id)
    if row is None:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    changes: list[dict] = []
    if body.name is not None and body.name != row.name:
        clash = db.scalars(
            select(FreightCategory).where(
                FreightCategory.name == body.name, FreightCategory.id != row.id
            )
        ).first()
        if clash is not None:
            raise HTTPException(status_code=409, detail=f"分类「{body.name}」已经存在了")
        changes.append({"field": "name", "from": row.name, "to": body.name})
        row.name = body.name
    if body.sort_order is not None and body.sort_order != row.sort_order:
        changes.append({"field": "sort_order", "from": row.sort_order, "to": body.sort_order})
        row.sort_order = body.sort_order
    if changes:
        write_log(
            db,
            operator_id=current.id,
            order_id=None,
            action=OperationAction.FREIGHT_CATEGORY_UPSERT,
            change_payload={"category_id": row.id, "op": "update", "changes": changes},
        )
    db.commit()
    db.refresh(row)
    t, r = _counts(db)
    return _out(row, t, r)


@router.post("/reorder", response_model=list[FreightCategoryOut])
def reorder_categories(
    body: FreightCategoryReorder,
    current: User = Depends(require_permission(Permission.ORDER_DISPATCH)),
    db: Session = Depends(get_db),
) -> list[FreightCategoryOut]:
    """整份顺序一次提交：`ids[0]` 排最前（**必须覆盖全部现存分类**，见模块注释第 3 条）。"""
    rows = db.scalars(select(FreightCategory)).all()
    by_id = {r.id: r for r in rows}
    # 整份顺序的校验四个名册共用一份（理由见 services/category_order.py）
    ids = ordered_ids(by_id, body.ids)
    for idx, cid in enumerate(ids):
        by_id[cid].sort_order = idx
    write_log(
        db,
        operator_id=current.id,
        order_id=None,
        action=OperationAction.FREIGHT_CATEGORY_REORDER,
        change_payload={"order": [{"id": i, "name": by_id[i].name} for i in ids]},
    )
    db.commit()
    t, r = _counts(db)
    return [_out(by_id[i], t, r) for i in ids]


@router.delete("/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_category(
    category_id: int,
    current: User = Depends(require_permission(Permission.ORDER_DISPATCH)),
    db: Session = Depends(get_db),
) -> None:
    """删除分类名册里的一行。**还有价目/规则挂着它时拒绝**（告诉各有几处）。"""
    row = db.get(FreightCategory, category_id)
    if row is None:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    t, r = _counts(db)
    used_t, used_r = t.get(row.id, 0), r.get(row.id, 0)
    if used_t or used_r:
        parts = []
        if used_t:
            parts.append(f"{used_t} 条运费价目")
        if used_r:
            parts.append(f"{used_r} 份计费规则")
        raise HTTPException(
            status_code=400,
            detail="还有 " + "、".join(parts) + f"挂在这个分类下，先改到别的分类（或改个名）再删",
        )
    write_log(
        db,
        operator_id=current.id,
        order_id=None,
        action=OperationAction.FREIGHT_CATEGORY_DELETE,
        change_payload={"category_id": row.id, "name": row.name},
    )
    db.delete(row)
    db.commit()
