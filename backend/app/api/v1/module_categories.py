# -*- coding: utf-8 -*-
"""模块自有分类名册（批发商管理 / 司机管理 / 货主管理各一份；FEAT-0026，2026-10-12）。

用户 2026-10-12：「我批发商管理他那个分类啊，他那个分类是**跟账号管理不一样**的，他现在
**串在一起**了。他那个分类是**可以新建的、另外建的**。……也就如**司机管理**，还有其他的
**批发商管理**，他们是有自己的分类的，他们的分类基本上就是 **1 级**、不会有 2 级的。
然后我们的**账号管理**，他的那个分类他是有 2 级的，他是**主动拉取**的。」

## 与账号名册（`/user-categories`）的分工
- **写**（新建 / 改名 / 排序 / 删除 / 撤销删除）只落在 `module_categories` 这一张表上；
- **读**：账号册 `GET /user-categories` 把本表**拉取**成二级行，实现只有一份
  （`services/module_category.py::pull_module_categories`）—— 在模块名册里新建一格，
  **不会**往 `user_categories` 写一个字节。

## 三条老规矩（与商品 / 车辆 / 账号分类同一套）
1. **改名要级联**：模块名册改名时，同一事务里把挂在这一类下的账号 `users.category` 从旧名
   改成新名 —— 不级联的话，改完名那些账号会散进"未分类"，而且**不报错**；
2. **删除是软删**（用户 2026-09-20 的硬规矩「所有删除一律软删 + 必须有恢复路径」）：
   `is_deleted=True` + `deleted_at`，列表里马上看不见，`POST /module-categories/restore`
   （界面上就是那条「撤销」）原样放回来。软删之后允许重建同名（唯一性只按未删行判）；
3. **还有账号挂着的分类 → 拒绝删除**（告诉还有几个），⛔ 不"顺手把那些账号改成未分类"
   —— 那是**悄悄改数据**。

## 为什么 `module` 是查询参数而不是路径参数
AI 的读目录（`_tools/ai/_gen_ai_read_catalog.py`）明确排除**路径里带花括号**的端点
（"模型看不到内部编号"），而 `module` 是个词、不是编号 —— 放查询参数里，这份名册 AI 才读得到。
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.business_time import utc_now_naive
from app.core.rbac import Permission
from app.database import get_db
from app.deps import CurrentUser, require_permission
from app.models import ModuleCategory, User
from app.models.enums import OperationAction
from app.schemas.module_category import (
    ModuleCategoryCreate,
    ModuleCategoryOut,
    ModuleCategoryReorder,
    ModuleCategoryRestore,
    ModuleCategoryUpdate,
)
from app.services.category_order import ordered_ids
from app.services.module_category import (
    MODULES,
    level_one_counts,
    level_ones_of,
    module_title,
)
from app.services.operation_log_service import write_log
from app.services.user_category import auto_category_of

router = APIRouter(prefix="/module-categories", tags=["module-categories"])

#: 一份模块名册最多几格（与账号 / 车辆分类同一口径：名册是给人扫一眼的短列，不是数据库）。
MAX_CATEGORIES = 200


def _module_or_400(module: str) -> str:
    """认不出的模块名 → 400 说清有哪几个（界面上这句话原样贴给用户）。"""
    key = (module or "").strip().lower()
    if key not in MODULES:
        raise HTTPException(
            status_code=400,
            detail=f"不认识这个模块：{module}（只有 {'、'.join(MODULES)}）",
        )
    return key


def _live_rows(db: Session, module: str) -> list[ModuleCategory]:
    """这一份名册里**没被删**的行（软删的行只在恢复时用，⛔ 不许漏掉这个过滤）。"""
    return list(
        db.scalars(
            select(ModuleCategory)
            .where(ModuleCategory.module == module, ModuleCategory.is_deleted.is_(False))
            .order_by(ModuleCategory.sort_order, ModuleCategory.id)
        ).all()
    )


def _counts(db: Session, module: str) -> dict[str, int]:
    """分类名 → 在用账号数（**一次查完**；跨这一份名册喂的所有一级分类求和）。

    司机那份名册喂三个一级（小车 / 大车 / 挂车），所以按身份推出来的一级分组后再相加 ——
    同一格分类挂在不同车型下时各自算各自的（口径见 `services/module_category.py`）。
    """
    per_level = level_one_counts(db)
    out: dict[str, int] = {}
    for level_one in level_ones_of(module):
        for name, n in per_level.get(level_one, {}).items():
            out[name] = out.get(name, 0) + n
    return out


def _out(row: ModuleCategory, counts: dict[str, int]) -> ModuleCategoryOut:
    o = ModuleCategoryOut.model_validate(row)
    o.user_count = counts.get(row.name, 0)
    return o


def _next_sort(db: Session, module: str) -> int:
    top = db.scalar(
        select(func.max(ModuleCategory.sort_order)).where(ModuleCategory.module == module)
    )
    return (top or 0) + 1


def _row_or_404(db: Session, category_id: int) -> ModuleCategory:
    """编号 → 活着的行（**软删掉的行在这里就是"不存在"**：它只认恢复，不认改名 / 删除）。"""
    row = db.get(ModuleCategory, category_id)
    if row is None or row.is_deleted:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    return row


def _clash_or_409(db: Session, module: str, name: str, exclude_id: int | None = None) -> None:
    """同一份名册里**活着的行**不许重名（软删的行不算 —— 删掉之后可以重建同名）。"""
    stmt = select(ModuleCategory).where(
        ModuleCategory.module == module,
        ModuleCategory.name == name,
        ModuleCategory.is_deleted.is_(False),
    )
    if exclude_id is not None:
        stmt = stmt.where(ModuleCategory.id != exclude_id)
    if db.scalars(stmt).first() is not None:
        raise HTTPException(status_code=409, detail=f"分类「{name}」已经存在了")


@router.get("", response_model=list[ModuleCategoryOut])
def list_categories(
    current: CurrentUser,
    module: str = Query(
        ...,
        description="哪一份名册：members=批发商管理 / shippers=货主管理 / drivers=司机管理",
    ),
    db: Session = Depends(get_db),
) -> list[ModuleCategoryOut]:
    """某个模块**自己的**分类名册（按显示顺序）。

    只有一级 —— 模块名册没有父子；账号册那边看到的二级是从这里**拉取**的（只读投影）。
    """
    key = _module_or_400(module)
    counts = _counts(db, key)
    return [_out(r, counts) for r in _live_rows(db, key)]


@router.post("", response_model=ModuleCategoryOut, status_code=status.HTTP_201_CREATED)
def create_category(
    body: ModuleCategoryCreate,
    current: User = Depends(require_permission(Permission.USER_MANAGE)),
    db: Session = Depends(get_db),
) -> ModuleCategoryOut:
    """在某一份模块名册里新建一格。

    ⛔ 只写 `module_categories`：账号册那边是**拉取**（读时投影），不是同步写。
    """
    key = _module_or_400(body.module)
    _clash_or_409(db, key, body.name)
    total = (
        db.scalar(
            select(func.count(ModuleCategory.id)).where(
                ModuleCategory.module == key, ModuleCategory.is_deleted.is_(False)
            )
        )
        or 0
    )
    if total >= MAX_CATEGORIES:
        raise HTTPException(
            status_code=400,
            detail=f"「{module_title(key)}」最多 {MAX_CATEGORIES} 个分类，请先清理一些",
        )
    row = ModuleCategory(
        module=key,
        name=body.name,
        sort_order=body.sort_order if body.sort_order is not None else _next_sort(db, key),
    )
    db.add(row)
    db.flush()
    write_log(
        db,
        operator_id=current.id,
        order_id=None,
        action=OperationAction.MODULE_CATEGORY_UPSERT,
        change_payload={
            "module": key,
            "category_id": row.id,
            "name": row.name,
            "sort_order": row.sort_order,
            "op": "create",
        },
    )
    db.commit()
    db.refresh(row)
    return _out(row, _counts(db, key))


@router.patch("/{category_id}", response_model=ModuleCategoryOut)
def update_category(
    category_id: int,
    body: ModuleCategoryUpdate,
    current: User = Depends(require_permission(Permission.USER_MANAGE)),
    db: Session = Depends(get_db),
) -> ModuleCategoryOut:
    """改名 / 改顺序。**改名会级联改掉挂在这一类下的账号**（同一事务，见模块注释）。"""
    row = _row_or_404(db, category_id)
    changes: list[dict] = []
    if body.name is not None and body.name != row.name:
        _clash_or_409(db, row.module, body.name, exclude_id=row.id)
        old_name = row.name
        level_ones = level_ones_of(row.module)
        moved = 0
        for user in db.scalars(select(User).where(User.category == old_name)).all():
            # ⚠️ 只改**身份属于这个模块那几个一级**的账号：同名分类可能同时挂在别的模块下面
            #    （比如"食堂客户"在批发商册与货主册各有一格），无差别改名会串册。
            if auto_category_of(user) not in level_ones:
                continue
            # ⚠️ 回收站里的账号也一起改名：它们迟早会被"恢复"，恢复出来挂的必须还是一个
            #    存在的分类名（否则名册页会凭空多出一格"名册里没有的分类"）。
            user.category = body.name
            moved += 1
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
            action=OperationAction.MODULE_CATEGORY_UPSERT,
            change_payload={
                "module": row.module,
                "category_id": row.id,
                "op": "update",
                "changes": changes,
            },
        )
    db.commit()
    db.refresh(row)
    return _out(row, _counts(db, row.module))


@router.post("/reorder", response_model=list[ModuleCategoryOut])
def reorder_categories(
    body: ModuleCategoryReorder,
    current: User = Depends(require_permission(Permission.USER_MANAGE)),
    db: Session = Depends(get_db),
) -> list[ModuleCategoryOut]:
    """整份顺序一次提交：`ids[0]` 排最前（必须覆盖**这一份名册**的全部现存分类）。

    理由见 `services/category_order.py`：整份提交是幂等的，而且能一次查出"少了哪几格"。
    """
    key = _module_or_400(body.module)
    rows = _live_rows(db, key)
    by_id = {r.id: r for r in rows}
    ids = ordered_ids(by_id, body.ids)
    for idx, cid in enumerate(ids):
        by_id[cid].sort_order = idx
    write_log(
        db,
        operator_id=current.id,
        order_id=None,
        action=OperationAction.MODULE_CATEGORY_REORDER,
        change_payload={
            "module": key,
            "order": [{"id": i, "name": by_id[i].name} for i in ids],
        },
    )
    db.commit()
    counts = _counts(db, key)
    return [_out(by_id[i], counts) for i in ids]


@router.delete("/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_category(
    category_id: int,
    current: User = Depends(require_permission(Permission.USER_MANAGE)),
    db: Session = Depends(get_db),
) -> None:
    """**软删**一格（行留着，`POST /module-categories/restore` 能放回来）。

    **还有账号挂着时拒绝**（告诉有几个）。为什么不"顺手把那些账号改成未分类"：
    那是**悄悄改数据** —— 用户点的是"删掉这个分类"，不是"把 37 个账号的分类清掉"，
    而且清完在界面上看不出来（它们只是散进「未分类」）。
    """
    row = _row_or_404(db, category_id)
    used = _counts(db, row.module).get(row.name, 0)
    if used:
        raise HTTPException(
            status_code=400,
            detail=f"还有 {used} 个账号挂在这个分类下，先把它们改成别的分类（或改个名）再删",
        )
    row.is_deleted = True
    row.deleted_at = utc_now_naive()
    write_log(
        db,
        operator_id=current.id,
        order_id=None,
        action=OperationAction.MODULE_CATEGORY_DELETE,
        change_payload={"module": row.module, "category_id": row.id, "name": row.name},
    )
    db.commit()


@router.post("/restore", response_model=ModuleCategoryOut)
def restore_category(
    body: ModuleCategoryRestore,
    current: User = Depends(require_permission(Permission.USER_MANAGE)),
    db: Session = Depends(get_db),
) -> ModuleCategoryOut:
    """把软删掉的一格放回来（`DELETE` 的逆操作；界面上就是那条「撤销」）。

    ⚠️ 按**名字**恢复，而不是按编号：App 的撤销条走的是名册 VM 共用的
    `restoreRow(name, sortOrder, parentId)`（那个签名在
    `android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/CategoryRostersViewModel.kt`
    里被 `_tools/qa/_check_account_category_two_level.py` 钉着，不为了这一格去改它），
    它手里只有被删那一格的名字与顺序。同名多行时取**最后建的那一行**。

    ⚠️ 恢复时**要重新过一遍重名判据**：这一格被删掉之后，用户可能已经建了一格同名分类
    （那是允许的 —— 判据只看活着的行）。硬放回来会让名册里出现两格同名，界面上分不清谁是谁。
    """
    key = _module_or_400(body.module)
    gone = db.scalars(
        select(ModuleCategory)
        .where(
            ModuleCategory.module == key,
            ModuleCategory.name == body.name,
            ModuleCategory.is_deleted.is_(True),
        )
        .order_by(ModuleCategory.id.desc())
    ).first()
    if gone is None:
        raise HTTPException(status_code=404, detail="这个名字没有被删掉的分类，不需要恢复")
    _clash_or_409(db, key, body.name)
    gone.is_deleted = False
    gone.deleted_at = None
    if body.sort_order is not None:
        gone.sort_order = body.sort_order
    write_log(
        db,
        operator_id=current.id,
        order_id=None,
        action=OperationAction.MODULE_CATEGORY_RESTORE,
        change_payload={"module": key, "category_id": gone.id, "name": gone.name},
    )
    db.commit()
    db.refresh(gone)
    return _out(gone, _counts(db, key))
