"""商品分类名册（派单员维护；决定下单页左侧分类的顺序）。

## 这一层解决什么
v3.42 的分类顺序是**推出来的**（按商品数倒序）—— 那是"现在哪类货多"，不是
"店家想让人先看哪类"。用户 2026-09-18 要的是「派单端可以创建商品分类，
甚至可以更改商品分类的显示顺序」，所以顺序必须能**人指定**。

名册只存 `name + sort_order`；商品仍然用 `products.category` 这个字符串归属于某一类。
两者的关系写死成三条：
1. **改名要级联**：名册改名时，同一事务里把所有 `products.category` 从旧名改成新名
   —— 不级联的话，改完名商品全变成"未分类"，而且**不报错**；
2. **新建商品时带了名册里没有的分类名 → 自动补进名册**（排到最后）。
   否则派单员要先建分类、再建商品，两步做完才能用；
3. **删除有名册在用的分类 → 拒绝**（告诉还有几个商品挂着）。
   不提供"顺手把商品改成未分类"的便利：那是**悄悄改数据**，而且改完看不出来。

⚠️ 名册里没有的分类名**不是错误**（老数据、别的路径写进去的）。选品页会把它排在
名册后面 —— 不许因为它不在名册里就把商品藏起来。
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.rbac import Permission
from app.database import get_db
from app.deps import CurrentUser, require_permission
from app.models import Product, ProductCategory, User
from app.models.enums import OperationAction
from app.schemas.product_category import (
    ProductCategoryCreate,
    ProductCategoryOut,
    ProductCategoryReorder,
    ProductCategoryUpdate,
)
from app.services.operation_log_service import write_log

router = APIRouter(prefix="/product-categories", tags=["product-categories"])

MAX_CATEGORIES = 200


def _counts(db: Session) -> dict[str, int]:
    """分类名 → 在用商品数（**一次查完**，不要每个分类查一遍）。"""
    rows = db.execute(
        select(Product.category, func.count(Product.id))
        .where(Product.is_deleted.is_(False))
        .group_by(Product.category)
    ).all()
    return {(name or "").strip(): n for name, n in rows if (name or "").strip()}


def _out(row: ProductCategory, counts: dict[str, int]) -> ProductCategoryOut:
    o = ProductCategoryOut.model_validate(row)
    o.product_count = counts.get(row.name, 0)
    return o


def _next_sort(db: Session) -> int:
    top = db.scalar(select(func.max(ProductCategory.sort_order)))
    return (top or 0) + 1


def ensure_category(db: Session, name: str) -> ProductCategory | None:
    """确保这个分类名在名册里（不在就补到最后）。给商品创建/修改复用。

    返回被新建的名册行；已经在名册里则返回 None（调用方据此决定要不要记日志）。
    """
    clean = (name or "").strip()[:32]
    if not clean:
        return None
    exists = db.scalars(select(ProductCategory).where(ProductCategory.name == clean)).first()
    if exists is not None:
        return None
    row = ProductCategory(name=clean, sort_order=_next_sort(db))
    db.add(row)
    db.flush()
    return row


@router.get("", response_model=list[ProductCategoryOut])
def list_categories(current: CurrentUser, db: Session = Depends(get_db)) -> list[ProductCategoryOut]:
    """分类名册（按显示顺序）。**任何登录角色都能读** —— 下单页要用它排左侧那一列。"""
    rows = db.scalars(
        select(ProductCategory).order_by(ProductCategory.sort_order, ProductCategory.id)
    ).all()
    counts = _counts(db)
    return [_out(r, counts) for r in rows]


@router.post("", response_model=ProductCategoryOut, status_code=status.HTTP_201_CREATED)
def create_category(
    body: ProductCategoryCreate,
    current: User = Depends(require_permission(Permission.PRODUCT_MANAGE)),
    db: Session = Depends(get_db),
) -> ProductCategoryOut:
    exists = db.scalars(select(ProductCategory).where(ProductCategory.name == body.name)).first()
    if exists is not None:
        raise HTTPException(status_code=409, detail=f"分类「{body.name}」已经存在了")
    total = db.scalar(select(func.count(ProductCategory.id))) or 0
    if total >= MAX_CATEGORIES:
        raise HTTPException(status_code=400, detail=f"分类最多 {MAX_CATEGORIES} 个，请先清理一些")
    row = ProductCategory(
        name=body.name,
        sort_order=body.sort_order if body.sort_order is not None else _next_sort(db),
    )
    db.add(row)
    db.flush()
    write_log(
        db,
        operator_id=current.id,
        order_id=None,
        action=OperationAction.PRODUCT_CATEGORY_UPSERT,
        change_payload={"category_id": row.id, "name": row.name, "sort_order": row.sort_order, "op": "create"},
    )
    db.commit()
    db.refresh(row)
    return _out(row, _counts(db))


@router.patch("/{category_id}", response_model=ProductCategoryOut)
def update_category(
    category_id: int,
    body: ProductCategoryUpdate,
    current: User = Depends(require_permission(Permission.PRODUCT_MANAGE)),
    db: Session = Depends(get_db),
) -> ProductCategoryOut:
    """改名 / 改顺序。**改名会级联改掉挂在它下面的商品**（同一事务，见模块注释）。"""
    row = db.get(ProductCategory, category_id)
    if row is None:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    changes: list[dict] = []
    if body.name is not None and body.name != row.name:
        clash = db.scalars(
            select(ProductCategory).where(
                ProductCategory.name == body.name, ProductCategory.id != row.id
            )
        ).first()
        if clash is not None:
            raise HTTPException(status_code=409, detail=f"分类「{body.name}」已经存在了")
        old_name = row.name
        moved = db.execute(
            # ⚠️ 必须带上 `is_deleted=False` 之外的**全部**行：软删的商品也一起改名，
            #    否则恢复那个商品时它挂的是一个已经不存在的分类名（选品页会多出一格）。
            Product.__table__.update().where(Product.category == old_name).values(category=body.name)
        ).rowcount
        row.name = body.name
        changes.append({"field": "name", "from": old_name, "to": body.name, "products_moved": moved})
    if body.sort_order is not None and body.sort_order != row.sort_order:
        changes.append({"field": "sort_order", "from": row.sort_order, "to": body.sort_order})
        row.sort_order = body.sort_order
    if changes:
        write_log(
            db,
            operator_id=current.id,
            order_id=None,
            action=OperationAction.PRODUCT_CATEGORY_UPSERT,
            change_payload={"category_id": row.id, "op": "update", "changes": changes},
        )
    db.commit()
    db.refresh(row)
    return _out(row, _counts(db))


@router.post("/reorder", response_model=list[ProductCategoryOut])
def reorder_categories(
    body: ProductCategoryReorder,
    current: User = Depends(require_permission(Permission.PRODUCT_MANAGE)),
    db: Session = Depends(get_db),
) -> list[ProductCategoryOut]:
    """整份顺序一次提交：`ids[0]` 排最前。

    ⚠️ **必须整份提交**（ids 要覆盖全部现存分类）：只传一部分的话，"没提到的那些"
    该排哪儿是没有答案的 —— 而按"没提到的保持原序"实现，会在两端各错一次而且看不出来。
    所以这里明确拒绝，并告诉用户少了哪些。
    """
    rows = db.scalars(select(ProductCategory)).all()
    by_id = {r.id: r for r in rows}
    ids = list(body.ids)
    if len(set(ids)) != len(ids):
        raise HTTPException(status_code=400, detail="顺序里有重复的分类，请重新排一次")
    unknown = [i for i in ids if i not in by_id]
    if unknown:
        raise HTTPException(status_code=400, detail=f"顺序里有不存在的分类编号：{unknown}")
    missing = [i for i in by_id if i not in set(ids)]
    if missing:
        names = "、".join(by_id[i].name for i in missing[:5])
        raise HTTPException(
            status_code=400,
            detail=f"顺序里少了 {len(missing)} 个分类（{names}…）。请提交**完整**的分类顺序。",
        )
    for idx, cid in enumerate(ids):
        by_id[cid].sort_order = idx
    write_log(
        db,
        operator_id=current.id,
        order_id=None,
        action=OperationAction.PRODUCT_CATEGORY_REORDER,
        change_payload={"order": [{"id": i, "name": by_id[i].name} for i in ids]},
    )
    db.commit()
    counts = _counts(db)
    return [_out(by_id[i], counts) for i in ids]


@router.delete("/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_category(
    category_id: int,
    current: User = Depends(require_permission(Permission.PRODUCT_MANAGE)),
    db: Session = Depends(get_db),
) -> None:
    """删除分类名册里的一行。**还有商品挂着时拒绝**（告诉有几个）。

    为什么不"顺手把那些商品改成未分类"：那是**悄悄改数据** —— 用户点的是"删掉这个分类"，
    不是"把 37 个商品的分类清掉"，而且清完在界面上看不出来（它们只是散进「未分类」）。
    """
    row = db.get(ProductCategory, category_id)
    if row is None:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    used = db.scalar(
        select(func.count(Product.id)).where(
            Product.category == row.name, Product.is_deleted.is_(False)
        )
    ) or 0
    if used:
        raise HTTPException(
            status_code=400,
            detail=f"还有 {used} 个商品挂在这个分类下，先把它们改成别的分类（或改个名）再删",
        )
    write_log(
        db,
        operator_id=current.id,
        order_id=None,
        action=OperationAction.PRODUCT_CATEGORY_DELETE,
        change_payload={"category_id": row.id, "name": row.name},
    )
    db.delete(row)
    db.commit()
