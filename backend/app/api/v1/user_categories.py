"""账号分类名册（派单员维护；账户 / 司机 / 货主 / 批发商四个名册页左侧那一列）。

## 这一层解决什么
用户 2026-10-05：「还有我们的账户管理司机管理货主管理批发商管理。车辆管理……
在这个位置也加个分类，默认是显示，全部，同样也是左边侧边栏，
然后左边侧边栏同样也是可以新增分类的」。

分类名本身仍然是 `users.category` 这个字符串（空串 = 未分类），名册只存
`name + sort_order` —— **名册管顺序与"有哪些类"**，与商品分类同一套三条关系：
1. **改名要级联**：名册改名时，同一事务里把所有 `users.category` 从旧名改成新名
   —— 不级联的话，改完名账号全变成"未分类"，而且**不报错**；
2. **建号/改号时带了名册里没有的分类名 → 自动补进名册**（排到最后）。
   否则派单员要先建分类、再建账号，两步做完才能用；
3. **删除有名册在用的分类 → 拒绝**（告诉还有几个账号挂着）。
   不提供"顺手把账号改成未分类"的便利：那是**悄悄改数据**。

⚠️ 「在用」**不含回收站里的账号**：删号时号码/用户名被加了 `_del{id}` 后缀
（`services/soft_delete.py`），如果把它也算成"挂着这个分类"，就会出现
"账号都删了，分类却怎么也删不掉"。口径只有 `has_del_suffix` 这一份。

⚠️ 名册里没有的分类名**不是错误**（老数据、别的路径写进去的）。名册页会把它
排在名册后面 —— 不许因为它不在名册里就把账号藏起来。
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.rbac import Permission
from app.database import get_db
from app.deps import CurrentUser, require_permission
from app.models import User, UserCategory
from app.models.enums import OperationAction
from app.schemas.user_category import (
    UserCategoryCreate,
    UserCategoryOut,
    UserCategoryReorder,
    UserCategoryUpdate,
)
from app.services.category_order import ordered_ids
from app.services.operation_log_service import write_log
from app.services.soft_delete import has_del_suffix

router = APIRouter(prefix="/user-categories", tags=["user-categories"])

MAX_CATEGORIES = 200


def _counts(db: Session) -> dict[str, int]:
    """分类名 → 在用账号数（**一次查完**，不要每个分类查一遍）。

    "在用" = 不在回收站里的账号。停用（`is_active=False`）**仍然算在用** ——
    它照样挂着这个分类，删分类就会把它变成未分类。
    """
    rows = db.execute(
        select(User.id, User.phone, User.username, User.category).where(User.category != "")
    ).all()
    counts: dict[str, int] = {}
    for uid, phone, username, name in rows:
        if has_del_suffix(uid, phone, username):
            continue
        key = (name or "").strip()
        if key:
            counts[key] = counts.get(key, 0) + 1
    return counts


def _out(row: UserCategory, counts: dict[str, int]) -> UserCategoryOut:
    o = UserCategoryOut.model_validate(row)
    o.user_count = counts.get(row.name, 0)
    return o


def _next_sort(db: Session) -> int:
    top = db.scalar(select(func.max(UserCategory.sort_order)))
    return (top or 0) + 1


def ensure_user_category(db: Session, name: str) -> UserCategory | None:
    """确保这个分类名在名册里（不在就补到最后）。给账号的新建/修改复用。

    返回被新建的名册行；已经在名册里则返回 None（调用方据此决定要不要记日志）。
    """
    clean = (name or "").strip()[:32]
    if not clean:
        return None
    exists = db.scalars(select(UserCategory).where(UserCategory.name == clean)).first()
    if exists is not None:
        return None
    row = UserCategory(name=clean, sort_order=_next_sort(db))
    db.add(row)
    db.flush()
    return row


@router.get("", response_model=list[UserCategoryOut])
def list_categories(current: CurrentUser, db: Session = Depends(get_db)) -> list[UserCategoryOut]:
    """分类名册（按显示顺序）。四个名册页共用这一份 —— 账号是全局主数据，不按人分区。"""
    rows = db.scalars(select(UserCategory).order_by(UserCategory.sort_order, UserCategory.id)).all()
    counts = _counts(db)
    return [_out(r, counts) for r in rows]


@router.post("", response_model=UserCategoryOut, status_code=status.HTTP_201_CREATED)
def create_category(
    body: UserCategoryCreate,
    current: User = Depends(require_permission(Permission.USER_MANAGE)),
    db: Session = Depends(get_db),
) -> UserCategoryOut:
    exists = db.scalars(select(UserCategory).where(UserCategory.name == body.name)).first()
    if exists is not None:
        raise HTTPException(status_code=409, detail=f"分类「{body.name}」已经存在了")
    total = db.scalar(select(func.count(UserCategory.id))) or 0
    if total >= MAX_CATEGORIES:
        raise HTTPException(status_code=400, detail=f"分类最多 {MAX_CATEGORIES} 个，请先清理一些")
    row = UserCategory(
        name=body.name,
        sort_order=body.sort_order if body.sort_order is not None else _next_sort(db),
    )
    db.add(row)
    db.flush()
    write_log(
        db,
        operator_id=current.id,
        order_id=None,
        action=OperationAction.USER_CATEGORY_UPSERT,
        change_payload={"category_id": row.id, "name": row.name, "sort_order": row.sort_order, "op": "create"},
    )
    db.commit()
    db.refresh(row)
    return _out(row, _counts(db))


@router.patch("/{category_id}", response_model=UserCategoryOut)
def update_category(
    category_id: int,
    body: UserCategoryUpdate,
    current: User = Depends(require_permission(Permission.USER_MANAGE)),
    db: Session = Depends(get_db),
) -> UserCategoryOut:
    """改名 / 改顺序。**改名会级联改掉挂在这一类下的账号**（同一事务，见模块注释）。"""
    row = db.get(UserCategory, category_id)
    if row is None:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    changes: list[dict] = []
    if body.name is not None and body.name != row.name:
        clash = db.scalars(
            select(UserCategory).where(UserCategory.name == body.name, UserCategory.id != row.id)
        ).first()
        if clash is not None:
            raise HTTPException(status_code=409, detail=f"分类「{body.name}」已经存在了")
        old_name = row.name
        moved = db.execute(
            # ⚠️ 回收站里的账号也一起改名：它们迟早会被"恢复"，恢复出来挂的必须还是一个
            #    存在的分类名（否则名册页会凭空多出一格"名册里没有的分类"）。
            User.__table__.update().where(User.category == old_name).values(category=body.name)
        ).rowcount
        row.name = body.name
        changes.append({"field": "name", "from": old_name, "to": body.name, "users_moved": moved})
    if body.sort_order is not None and body.sort_order != row.sort_order:
        changes.append({"field": "sort_order", "from": row.sort_order, "to": body.sort_order})
        row.sort_order = body.sort_order
    if changes:
        write_log(
            db,
            operator_id=current.id,
            order_id=None,
            action=OperationAction.USER_CATEGORY_UPSERT,
            change_payload={"category_id": row.id, "op": "update", "changes": changes},
        )
    db.commit()
    db.refresh(row)
    return _out(row, _counts(db))


@router.post("/reorder", response_model=list[UserCategoryOut])
def reorder_categories(
    body: UserCategoryReorder,
    current: User = Depends(require_permission(Permission.USER_MANAGE)),
    db: Session = Depends(get_db),
) -> list[UserCategoryOut]:
    """整份顺序一次提交：`ids[0]` 排最前（必须覆盖全部现存分类，理由见 `services/category_order`）。"""
    rows = db.scalars(select(UserCategory)).all()
    by_id = {r.id: r for r in rows}
    ids = ordered_ids(by_id, body.ids)
    for idx, cid in enumerate(ids):
        by_id[cid].sort_order = idx
    write_log(
        db,
        operator_id=current.id,
        order_id=None,
        action=OperationAction.USER_CATEGORY_REORDER,
        change_payload={"order": [{"id": i, "name": by_id[i].name} for i in ids]},
    )
    db.commit()
    counts = _counts(db)
    return [_out(by_id[i], counts) for i in ids]


@router.delete("/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_category(
    category_id: int,
    current: User = Depends(require_permission(Permission.USER_MANAGE)),
    db: Session = Depends(get_db),
) -> None:
    """删除分类名册里的一行。**还有账号挂着时拒绝**（告诉有几个）。

    为什么不"顺手把那些账号改成未分类"：那是**悄悄改数据** —— 用户点的是"删掉这个分类"，
    不是"把 37 个账号的分类清掉"，而且清完在界面上看不出来（它们只是散进「未分类」）。
    """
    row = db.get(UserCategory, category_id)
    if row is None:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    used = _counts(db).get(row.name, 0)
    if used:
        raise HTTPException(
            status_code=400,
            detail=f"还有 {used} 个账号挂在这个分类下，先把它们改成别的分类（或改个名）再删",
        )
    write_log(
        db,
        operator_id=current.id,
        order_id=None,
        action=OperationAction.USER_CATEGORY_DELETE,
        change_payload={"category_id": row.id, "name": row.name},
    )
    db.delete(row)
    db.commit()
