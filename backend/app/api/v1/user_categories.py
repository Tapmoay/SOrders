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

## 两级（2026-10-11 CHG-0112）

用户 2026-10-11：「假如我的货主和批发商做了分类的话，然后我这个账户管理就会显示
2 级分类，也就会显示他们里面的子分类。这就方便我们去查角色嘛」。

**大类是一行、子类也是一行** —— 两级的区别只是子类的 `parent_id` 指向大类
（`NULL` = 大类本身）。所以这一层的形状**没有变成树**：出参仍是平铺的一列
（按 `sort_order, id` 排序），谁在谁下面由 `parent_id` 表达，树由界面画。

⛔ **只有两级**：父必须自己也是大类（`parent_id IS NULL`），「子类的子类」在建的时候
就 400 拒掉（`_parent_or_400`）—— 结构里不出现第三层。
⛔ `users.category` 存的仍然是**叶子名**（账号只认一个字符串），
所以下面这段改名级联一个字都不用动。
⛔ 大类**不能**在还有子类的时候删掉（子类会变成没有父的孤儿）。

⚠️ 「在用」**不含回收站里的账号**：删号时号码/用户名被加了 `_del{id}` 后缀
（`services/soft_delete.py`），如果把它也算成"挂着这个分类"，就会出现
"账号都删了，分类却怎么也删不掉"。口径只有 `has_del_suffix` 这一份。

⚠️ 名册里没有的分类名**不是错误**（老数据、别的路径写进去的）。名册页会把它
排在名册后面 —— 不许因为它不在名册里就把账号藏起来。

## 拆分（FEAT-0026，2026-10-12）：这是**账号名册**，各模块有它们自己的名册

用户 2026-10-12：「我批发商管理他那个分类啊，他那个分类是**跟账号管理不一样**的，他现在
**串在一起**了……也就如**司机管理**，还有其他的**批发商管理**，他们是有自己的分类的，
他们的分类基本上就是 **1 级**、不会有 2 级的。然后我们的**账号管理**，他的那个分类他是
**有 2 级的**，他是**主动拉取**的，而且我们分类**已经固定好了**的。」

⇒ 从这一轮起：
- **一级 = 固定的六类**（`services/user_category.py::AUTO_CATEGORIES`）：⛔ 这一页不能新建一级，
  一级也不能改名 / 删 / 排序 —— 账号的分类名是按身份自动推导的（CHG-0121），改了名它们就掉队；
- **二级 = 从模块名册拉取**（`services/module_category.py::pull_module_categories`）：
  批发商管理 / 司机管理 / 货主管理各自有一份**只有一级**的分类名册（`module_categories` 表），
  `GET` 把它们投影成二级行（编号是**负数**、`pulled=True`）。⛔ 拉取是**读**，不写库；
- **写路径**：模块名册的增 / 删 / 改 / 排序在 `/module-categories`（见
  `api/v1/module_categories.py` 开头）；这一份名册里只剩 `派单员` 下面那几格
  **历史遗留**的二级行（派单员没有模块名册），它们沿用 CHG-0112 的老行为。
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.rbac import Permission
from app.database import get_db
from app.deps import CurrentUser, require_permission
from app.models import ModuleCategory, User, UserCategory
from app.models.enums import OperationAction
from app.schemas.user_category import (
    UserCategoryCreate,
    UserCategoryOut,
    UserCategoryReorder,
    UserCategoryUpdate,
)
from app.services.category_order import ordered_ids
from app.services.module_category import (
    PulledCategory,
    is_pulled_id,
    module_of_level_one,
    module_title,
    pull_module_categories,
)
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


def _parent_name_of(db: Session, row: UserCategory) -> str:
    """这一格挂在哪一类下面（一级自己 ⇒ 空串；父已经不在了 ⇒ 空串）。"""
    if row.parent_id is None:
        return ""
    parent = db.get(UserCategory, row.parent_id)
    return parent.name if parent is not None else ""


def _out_pulled(p: PulledCategory) -> UserCategoryOut:
    """拉取来的一行 → 出参（编号是**负数**、`pulled=True`；见 `services/module_category.py`）。"""
    return UserCategoryOut(
        id=p.id,
        name=p.name,
        sort_order=p.sort_order,
        parent_id=p.parent_id,
        user_count=p.user_count,
        pulled=True,
        module=p.module,
    )


def _next_sort(db: Session) -> int:
    top = db.scalar(select(func.max(UserCategory.sort_order)))
    return (top or 0) + 1


def _parent_or_400(db: Session, parent_id: int | None) -> UserCategory | None:
    """校验「上层分类」这一格（2026-10-11 CHG-0112）：**只两级**，父必须自己也是大类。

    两条拒绝各自说清是哪一种，因为界面把这句话原样贴给用户：
    · 父不存在（并发删掉了）→ 让他重选一个；
    · 父自己是子类 → 「只能做两级」，别让他以为可以无限套下去。

    ⚠️ 这里**不**顺手把父改掉、也不自动降级成大类：用户点的是「建在 X 下面」，
    建到别处就是**悄悄改数据**（与本文件「删分类不顺手把账号改成未分类」同一条纪律）。
    """
    if parent_id is None:
        return None
    parent = db.get(UserCategory, parent_id)
    if parent is None:
        raise HTTPException(status_code=400, detail="上层分类不存在（可能刚被删掉了），换一个再试")
    if parent.parent_id is not None:
        raise HTTPException(
            status_code=400,
            detail=f"只能做两级：「{parent.name}」自己就是子分类，不能再往它下面挂",
        )
    return parent


def _in_module_roster(db: Session, name: str) -> bool:
    """这个名字是不是某个**模块自有名册**里的分类（批发商 / 司机 / 货主管理，FEAT-0026）。

    软删掉的那些**算数**：它们还被账号挂着、还能被撤销（这一格迟早会回来），
    此刻往账号册补一行一级，等于给同一格分类留了两条命。
    """
    return (
        db.scalars(
            select(ModuleCategory).where(ModuleCategory.name == name)
        ).first()
        is not None
    )


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
    # ── FEAT-0026：模块自有名册里的名字**不往账号册补行** ─────────────────────────
    # 账号那一格是**叶子名**（CHG-0112），而模块名册里的分类已经会以**拉取**的方式
    # 出现在账号册里（挂在对应的一级下面 = 二级）。这里再补一行，同一个名字就多出一个
    # 「一级」的身份（parent_id is None）—— 界面上它既在「批发商」下面、又自己独占一格，
    # 那正是用户说的"又串在一起了"。
    if _in_module_roster(db, clean):
        return None
    row = UserCategory(name=clean, sort_order=_next_sort(db))
    db.add(row)
    db.flush()
    return row


@router.get("", response_model=list[UserCategoryOut])
def list_categories(current: CurrentUser, db: Session = Depends(get_db)) -> list[UserCategoryOut]:
    """分类名册（按显示顺序）：**固定的六类一级 + 从各模块名册拉取来的二级**。

    一级是全局主数据（六类固定），二级由 `services/module_category.py::pull_module_categories`
    从各模块自己的名册**拉取**而来（读时投影，⛔ 一个字节都不写 `user_categories`）。
    """
    rows = db.scalars(select(UserCategory).order_by(UserCategory.sort_order, UserCategory.id)).all()
    counts = _counts(db)
    out = [_out(r, counts) for r in rows]
    for row in out:
        # 一级 = 固定的六类（见模块 docstring）；拉取来的行下面单独追加。
        row.fixed = row.parent_id is None
    # 「账号管理主动拉取」：把各模块名册（FEAT-0026）投影成本册的**二级**。
    # ⛔ 拉取行永远带 parent_id（parent_id 为空就是"拉成一级"，那正是用户说的"又串在一起"）。
    out.extend(_out_pulled(p) for p in pull_module_categories(db))
    return out


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
    parent = _parent_or_400(db, body.parent_id)
    # ── FEAT-0026：这一页是**账号名册**，只读 ────────────────────────────────────────
    # 一级不许新建：账号挂的分类名是按身份自动推导的（CHG-0121），凭空多一个一级没人会被挂上去。
    if parent is None:
        raise HTTPException(
            status_code=400,
            detail="账号分类的一级是固定的六类（派单员 / 货主 / 批发商 / 小车司机 / 大车司机 / "
                   "挂车司机），不能新建。批发商 / 司机 / 货主各自的分类请到对应模块的"
                   "「管理分类」里建 —— 建好之后这里会自动拉取成二级。",
        )
    # 二级挂在模块的一级下面 ⇒ 那是模块名册的地盘（拉取是**读**，写要去那一页）。
    # 只有「派单员」下面的历史遗留子分类还落在这张表上（派单员没有模块名册）。
    owner = module_of_level_one(parent.name)
    if owner is not None:
        raise HTTPException(
            status_code=400,
            detail=f"「{parent.name}」下面的子分类跟着「{module_title(owner)}」自己的名册走，"
                   "请到那一页的「管理分类」里新建（这里只读、自动拉取）。",
        )
    row = UserCategory(
        name=body.name,
        sort_order=body.sort_order if body.sort_order is not None else _next_sort(db),
        parent_id=parent.id if parent is not None else None,
    )
    db.add(row)
    db.flush()
    write_log(
        db,
        operator_id=current.id,
        order_id=None,
        action=OperationAction.USER_CATEGORY_UPSERT,
        change_payload={
            "category_id": row.id,
            "name": row.name,
            "sort_order": row.sort_order,
            # 归属也要留痕：两级之后「这一格挂在哪一类下面」是名册的一部分
            "parent_id": row.parent_id,
            "op": "create",
        },
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
    if is_pulled_id(category_id):
        raise HTTPException(
            status_code=400,
            detail="这是从模块名册拉取来的二级分类，改不在这里 —— 请到对应模块的「管理分类」里改。",
        )
    row = db.get(UserCategory, category_id)
    if row is None:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    parent_name = _parent_name_of(db, row)
    # 一级固定六类：改名会让按身份自动推导出来的那些账号掉队（CHG-0121）。
    if row.parent_id is None:
        raise HTTPException(
            status_code=400,
            detail="账号分类的一级是固定的六类，改不了：账号挂的分类名是按身份自动推导的"
                   "（CHG-0121），改了名它们就掉队。",
        )
    owner = module_of_level_one(parent_name)
    if owner is not None:
        raise HTTPException(
            status_code=400,
            detail=f"「{parent_name}」下面的子分类跟着「{module_title(owner)}」自己的名册走，"
                   "请到那一页的「管理分类」里改（这里只读、自动拉取）。",
        )
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
    # FEAT-0026：账号册里**能排序的只剩"没有模块归属"的那几格**（「派单员」下面的历史遗留
    # 子分类）—— 一级是固定的六类、二级跟随各模块名册自己的顺序，提交它们只会换来一句
    # "顺序里有不存在的分类编号"，所以先在这里说清楚（比让 ordered_ids 报编号更可读）。
    free = {
        r.id: r
        for r in rows
        if r.parent_id is not None and module_of_level_one(_parent_name_of(db, r)) is None
    }
    if any(i not in free for i in body.ids):
        raise HTTPException(
            status_code=400,
            detail="账号分类的一级是固定的六类、二级跟着各模块自己的名册，账号册里能排序的只有"
                   "「派单员」下面的历史子分类；其余请到批发商 / 司机 / 货主管理的「管理分类」里排。",
        )
    by_id = free
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
    if is_pulled_id(category_id):
        raise HTTPException(
            status_code=400,
            detail="这是从模块名册拉取来的二级分类，删不在这里 —— 请到对应模块的「管理分类」里删"
                   "（那边是软删，删错了能撤销）。",
        )
    row = db.get(UserCategory, category_id)
    if row is None:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    # ⛔ 还有子类时先拒（顺序在最前）：子类会变成没有父的孤儿 ——
    #    它仍然是一行、仍然能被点，但界面上再也说不清它属于哪一类。
    #    「派单员」这种既挂着子类、自己又是固定一级的行，先说子类那句更可操作。
    #    与「还有账号挂着不许删」同一条纪律：不顺手把子类挪到别处（那是悄悄改数据）。
    kids = db.scalars(
        select(UserCategory)
        .where(UserCategory.parent_id == row.id)
        .order_by(UserCategory.sort_order, UserCategory.id)
    ).all()
    if kids:
        shown = "、".join(k.name for k in kids[:5])
        more = "" if len(kids) <= 5 else f" 等 {len(kids)} 个"
        raise HTTPException(
            status_code=400,
            detail=f"「{row.name}」下面还有 {len(kids)} 个子分类（{shown}{more}），"
                   "先把它们删掉或改到别的大类下面再删",
        )
    parent_name = _parent_name_of(db, row)
    # 一级固定六类：删掉之后按身份自动推导的那些账号会变成「名册里没有的分类」。
    if row.parent_id is None:
        raise HTTPException(
            status_code=400,
            detail="账号分类的一级是固定的六类，删不了：删掉之后按身份自动推导的那些账号会变成"
                   "「名册里没有的分类」。",
        )
    owner = module_of_level_one(parent_name)
    if owner is not None:
        raise HTTPException(
            status_code=400,
            detail=f"「{parent_name}」下面的子分类跟着「{module_title(owner)}」自己的名册走，"
                   "请到那一页的「管理分类」里删（那边是软删，删错了能撤销）。",
        )
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
