"""预订单分类名册（派单员维护）——增 / 改名 / 排序 / 删除（照商品分类、开销分类同一套规矩）。

## 三条硬规矩（与商品分类一字不差，第 1 条尤其）
1. **改名必须级联**：`order_templates.category` 存的是**名字**，所以同一事务里把旧名
   全改成新名 —— 不级联的话那些预设单全变成"未分类"，而且**不报错**
   （与商品分类那次同一个坑）。⚠️ **软删的预设单也一起改**：不然后端把它们恢复回来时，
   它们挂的是一个名册里已经没有的分类名（左栏会凭空多出一格）。
2. **删除还有预设单挂着 → 拒绝**，并告诉用户有几张。⛔ 不提供"顺手把它们改成未分类"：
   那是悄悄改数据，改完在界面上看不出来。
3. **顺序整份提交**（`POST /reorder`）：只传一部分的话，"没提到的那些排哪儿"没有答案。
   判据只有一份 —— `services/category_order.py::ordered_ids`（五个名册共用）。
4. **建预设单时带了一个名册外的分类名 → 自动补进名册**（[ensure_category]，排到最后）：
   否则派单员要先建分类、再建预设单，两步做完才能用（与商品那一侧同一条）。

⛔ 权限一律 `ORDER_EDIT`（只有派单员管预设单）：这一套分类是**内部管理口径**，
货主/司机那一侧连预订单页都没有（与商品分类不同 —— 那个下单页要用，所以对所有人可读）。
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.rbac import Permission
from app.database import get_db
from app.deps import require_permission
from app.models import OrderTemplate, OrderTemplateCategory, User
from app.models.enums import OperationAction
from app.schemas.order_template_category import (
    OrderTemplateCategoryCreate,
    OrderTemplateCategoryOut,
    OrderTemplateCategoryReorder,
    OrderTemplateCategoryUpdate,
)
from app.services.category_order import ordered_ids
from app.services.operation_log_service import write_log

router = APIRouter(prefix="/order-template-categories", tags=["order-template-categories"])

MAX_CATEGORIES = 200


def _counts(db: Session) -> dict[str, int]:
    """分类名 → 在用的预设单数（**一次查完**，不要每个分类查一遍）。

    ⚠️ 只数**没进回收站**的：软删那张已经不在列表上了，它不该拦住"删掉这个分类"
    （而它的 `category` 仍然留着，恢复回来照样归在这一类下 —— 只要名册还在）。
    """
    rows = db.execute(
        select(OrderTemplate.category, func.count(OrderTemplate.id))
        .where(OrderTemplate.is_deleted.is_(False))
        .group_by(OrderTemplate.category)
    ).all()
    return {(name or "").strip(): n for name, n in rows if (name or "").strip()}


def _out(row: OrderTemplateCategory, counts: dict[str, int]) -> OrderTemplateCategoryOut:
    o = OrderTemplateCategoryOut.model_validate(row)
    o.template_count = counts.get(row.name, 0)
    return o


def _next_sort(db: Session) -> int:
    top = db.scalar(select(func.max(OrderTemplateCategory.sort_order)))
    return (top or 0) + 1


def ensure_category(db: Session, name: str) -> OrderTemplateCategory | None:
    """确保这个分类名在名册里（不在就补到最后）。给预设单创建/修改复用。

    返回被新建的名册行；已经在名册里（或名字是空的）则返回 None。
    """
    clean = (name or "").strip()[:32]
    if not clean:
        return None
    exists = db.scalars(
        select(OrderTemplateCategory).where(OrderTemplateCategory.name == clean)
    ).first()
    if exists is not None:
        return None
    row = OrderTemplateCategory(name=clean, sort_order=_next_sort(db))
    db.add(row)
    db.flush()
    return row


@router.get("", response_model=list[OrderTemplateCategoryOut])
def list_categories(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.ORDER_EDIT)),
) -> list[OrderTemplateCategoryOut]:
    """预订单分类名册（按显示顺序）。预订单页左栏与分类管理页共用这一份。"""
    rows = db.scalars(
        select(OrderTemplateCategory).order_by(
            OrderTemplateCategory.sort_order, OrderTemplateCategory.id
        )
    ).all()
    counts = _counts(db)
    return [_out(r, counts) for r in rows]


@router.post("", response_model=OrderTemplateCategoryOut, status_code=status.HTTP_201_CREATED)
def create_category(
    body: OrderTemplateCategoryCreate,
    current: User = Depends(require_permission(Permission.ORDER_EDIT)),
    db: Session = Depends(get_db),
) -> OrderTemplateCategoryOut:
    exists = db.scalars(
        select(OrderTemplateCategory).where(OrderTemplateCategory.name == body.name)
    ).first()
    if exists is not None:
        raise HTTPException(status_code=409, detail=f"分类「{body.name}」已经存在了")
    total = db.scalar(select(func.count(OrderTemplateCategory.id))) or 0
    if total >= MAX_CATEGORIES:
        raise HTTPException(status_code=400, detail=f"分类最多 {MAX_CATEGORIES} 个，请先清理一些")
    row = OrderTemplateCategory(
        name=body.name,
        sort_order=body.sort_order if body.sort_order is not None else _next_sort(db),
    )
    db.add(row)
    db.flush()
    write_log(
        db,
        operator_id=current.id,
        order_id=None,
        action=OperationAction.ORDER_TEMPLATE_CATEGORY_UPSERT,
        change_payload={
            "category_id": row.id,
            "name": row.name,
            "sort_order": row.sort_order,
            "op": "create",
        },
    )
    db.commit()
    db.refresh(row)
    return _out(row, _counts(db))


@router.patch("/{category_id}", response_model=OrderTemplateCategoryOut)
def update_category(
    category_id: int,
    body: OrderTemplateCategoryUpdate,
    current: User = Depends(require_permission(Permission.ORDER_EDIT)),
    db: Session = Depends(get_db),
) -> OrderTemplateCategoryOut:
    """改名 / 改顺序。**改名会级联改掉挂在它下面的预设单**（同一事务，见模块注释第 1 条）。"""
    row = db.get(OrderTemplateCategory, category_id)
    if row is None:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    changes: list[dict] = []
    if body.name is not None and body.name != row.name:
        clash = db.scalars(
            select(OrderTemplateCategory).where(
                OrderTemplateCategory.name == body.name, OrderTemplateCategory.id != row.id
            )
        ).first()
        if clash is not None:
            raise HTTPException(status_code=409, detail=f"分类「{body.name}」已经存在了")
        old_name = row.name
        moved = db.execute(
            # ⚠️ 级联**不带 `is_deleted=False`**：回收站里那几张也一起改名 ——
            #    否则把它们恢复回来时，它们挂的是一个名册里已经没有的分类名。
            OrderTemplate.__table__.update()
            .where(OrderTemplate.category == old_name)
            .values(category=body.name)
        ).rowcount
        row.name = body.name
        changes.append({"field": "name", "from": old_name, "to": body.name, "templates_moved": moved})
    if body.sort_order is not None and body.sort_order != row.sort_order:
        changes.append({"field": "sort_order", "from": row.sort_order, "to": body.sort_order})
        row.sort_order = body.sort_order
    if changes:
        write_log(
            db,
            operator_id=current.id,
            order_id=None,
            action=OperationAction.ORDER_TEMPLATE_CATEGORY_UPSERT,
            change_payload={"category_id": row.id, "op": "update", "changes": changes},
        )
    db.commit()
    db.refresh(row)
    return _out(row, _counts(db))


@router.post("/reorder", response_model=list[OrderTemplateCategoryOut])
def reorder_categories(
    body: OrderTemplateCategoryReorder,
    current: User = Depends(require_permission(Permission.ORDER_EDIT)),
    db: Session = Depends(get_db),
) -> list[OrderTemplateCategoryOut]:
    """整份顺序一次提交：`ids[0]` 排最前（**必须覆盖全部现存分类**，见模块注释第 3 条）。"""
    rows = db.scalars(select(OrderTemplateCategory)).all()
    by_id = {r.id: r for r in rows}
    # 整份顺序的校验五个名册共用一份（理由见 services/category_order.py）
    ids = ordered_ids(by_id, body.ids)
    for idx, cid in enumerate(ids):
        by_id[cid].sort_order = idx
    write_log(
        db,
        operator_id=current.id,
        order_id=None,
        action=OperationAction.ORDER_TEMPLATE_CATEGORY_REORDER,
        change_payload={"order": [{"id": i, "name": by_id[i].name} for i in ids]},
    )
    db.commit()
    counts = _counts(db)
    return [_out(by_id[i], counts) for i in ids]


@router.delete("/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_category(
    category_id: int,
    current: User = Depends(require_permission(Permission.ORDER_EDIT)),
    db: Session = Depends(get_db),
) -> None:
    """删除分类名册里的一行。**还有预设单挂着时拒绝**（告诉有几张）。"""
    row = db.get(OrderTemplateCategory, category_id)
    if row is None:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    used = db.scalar(
        select(func.count(OrderTemplate.id)).where(
            OrderTemplate.category == row.name, OrderTemplate.is_deleted.is_(False)
        )
    ) or 0
    if used:
        raise HTTPException(
            status_code=400,
            detail=f"还有 {used} 张预设单挂在这个分类下，先把它们改成别的分类（或改个名）再删",
        )
    write_log(
        db,
        operator_id=current.id,
        order_id=None,
        action=OperationAction.ORDER_TEMPLATE_CATEGORY_DELETE,
        change_payload={"category_id": row.id, "name": row.name},
    )
    db.delete(row)
    db.commit()
