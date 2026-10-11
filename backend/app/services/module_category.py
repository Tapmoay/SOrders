# -*- coding: utf-8 -*-
"""模块自有分类名册的**唯一一份**映射与「拉取」实现（FEAT-0026，2026-10-12）。

## 谁用这份文件
- `api/v1/module_categories.py`：模块名册的增 / 删 / 改 / 排序（**写**只落在那张表上）；
- `api/v1/user_categories.py`：账号册 `GET` 时**拉取**（**读**）—— 「账号管理主动拉取」
  只有这一份实现，判据 `_tools/qa/_check_category_rosters_split.py` 盯着。

## 映射（用户口径：司机管理 / 批发商管理各有自己的分类，账号管理把它们拉成二级）
| 模块（`ModuleCategory.module`） | 模块管理页 | 对应账号册里的一级分类 |
|---|---|---|
| `members` | 批发商管理 | 批发商 |
| `shippers` | 货主管理 | 货主 |
| `drivers` | 司机管理 | 小车司机 / 大车司机 / 挂车司机（**一对三**） |

`派单员` **没有模块**（没有"派单员管理"这一页）⇒ 它下面那几格留在账号册里、不参与拉取
（见 `api/v1/user_categories.py` 的写路径与 `docs/changes/FEAT-0026.md` 的 Known Limitations）。

## 「拉取」是读时投影，不是往账号册写行
拉取出来的每一行是**算出来的**（`PulledCategory`），**编号是负数**（真实行永远是正数）：
- App 侧 `ui/common/CategoryRoster.kt::submittableIds` 只提交 `id > 0` 的行 ⇒ 拉取行天然
  不会被塞进任何"排序/改名"请求里；
- 一个模块分类可能挂在**多个**一级下面（司机那一份喂三个），所以编号含**槽位**，
  同一格分类在三个一级下是三个不同编号（不会撞 key）。

⛔ 拉取行**永远**带 `parent_id`（指向一级的真实编号）：把模块分类拉成一级，
就是用户说的"又串在一起了"。
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ModuleCategory, User, UserCategory
from app.services.soft_delete import has_del_suffix
from app.services.user_category import (
    DRIVER_LARGE_CATEGORY,
    DRIVER_SMALL_CATEGORY,
    DRIVER_TRAILER_CATEGORY,
    MEMBER_CATEGORY,
    SHIPPER_CATEGORY,
    auto_category,
)

#: 三份模块名册（与 App `ui/dispatcher/UsersManageViewModel.kt::UserPool.key` 同名）。
MODULES: tuple[str, ...] = ("members", "shippers", "drivers")

#: 模块 → 那一页的中文名（拒绝文案与界面提示都从这里取一份）。
MODULE_TITLES: dict[str, str] = {
    "members": "批发商管理",
    "shippers": "货主管理",
    "drivers": "司机管理",
}

#: 模块 → 它在账号册里对应的**一级**分类（司机是一对三）。
MODULE_LEVEL_ONES: dict[str, tuple[str, ...]] = {
    "members": (MEMBER_CATEGORY,),
    "shippers": (SHIPPER_CATEGORY,),
    "drivers": (DRIVER_SMALL_CATEGORY, DRIVER_LARGE_CATEGORY, DRIVER_TRAILER_CATEGORY),
}

#: 拉取行编号的步长：`-(模块分类编号 * SLOT_STRIDE + 槽位)`。
SLOT_STRIDE = 10


def is_module(module: str) -> bool:
    return (module or "").strip().lower() in MODULES


def module_title(module: str) -> str:
    """模块的中文名（认不出就原样返回 —— 拒绝文案里要能看见用户发来的那个词）。"""
    return MODULE_TITLES.get((module or "").strip().lower(), module)


def level_ones_of(module: str) -> tuple[str, ...]:
    """这个模块在账号册里对应哪几个一级分类（司机是三个）。"""
    return MODULE_LEVEL_ONES.get((module or "").strip().lower(), ())


def module_of_level_one(name: str) -> str | None:
    """一级分类名 → 它归哪个模块（`派单员` 没有模块 ⇒ None）。"""
    clean = (name or "").strip()
    for module, names in MODULE_LEVEL_ONES.items():
        if clean in names:
            return module
    return None


def pulled_id(module_category_id: int, slot: int) -> int:
    """拉取行的编号（**负数**，见模块 docstring）。"""
    return -(module_category_id * SLOT_STRIDE + slot)


def is_pulled_id(row_id: int) -> bool:
    return row_id < 0


@dataclass(frozen=True)
class PulledCategory:
    """拉取出来的一行（**不是数据库里的行** —— 每次 GET 现算）。"""

    id: int
    name: str
    sort_order: int
    parent_id: int
    parent_name: str
    module: str
    user_count: int


def level_one_counts(db: Session) -> dict[str, dict[str, int]]:
    """一级分类名 → {叶子分类名: 账号数}（**只数直接挂在它下面的**；回收站不算）。

    拉取行要显示"这一类下有几个账号"，而账号册自己那套 `_counts` 只按**分类名**分组 ——
    同一格模块分类挂在三个司机一级下面时它会重复计数。所以这里按**身份推出来的一级**再分一次组，
    口径与 `services/user_category.py::auto_category` 同一份实现（⛔ 不写第二份推导）。
    """
    rows = db.execute(
        select(
            User.id,
            User.phone,
            User.username,
            User.category,
            User.role,
            User.is_member,
            User.vehicle_type,
        ).where(User.category != "")
    ).all()
    out: dict[str, dict[str, int]] = {}
    for uid, phone, username, category, role, is_member, vehicle_type in rows:
        if has_del_suffix(uid, phone, username):
            continue
        name = (category or "").strip()
        if not name:
            continue
        level_one = auto_category(role, is_member, vehicle_type)
        bucket = out.setdefault(level_one, {})
        bucket[name] = bucket.get(name, 0) + 1
    return out


def pull_module_categories(db: Session) -> list[PulledCategory]:
    """账号管理「主动拉取」：把各模块的名册投影成账号册里的**二级**行。

    ⛔ 只读：一个字节都不写 `user_categories`（账号册的一级固定六类，二级由这里拉出来）。
    ⛔ 一级行找不到（被别的路径删了/改了名）就**少拉一格**，绝不凭空造一个一级出来。
    """
    tops = db.scalars(
        select(UserCategory)
        .where(UserCategory.parent_id.is_(None))
        .order_by(UserCategory.sort_order, UserCategory.id)
    ).all()
    top_by_name = {t.name: t for t in tops}
    rows = db.scalars(
        select(ModuleCategory)
        .where(ModuleCategory.is_deleted.is_(False))
        .order_by(ModuleCategory.sort_order, ModuleCategory.id)
    ).all()
    counts = level_one_counts(db)
    out: list[PulledCategory] = []
    for module in MODULES:
        for slot, level_one in enumerate(MODULE_LEVEL_ONES[module]):
            top = top_by_name.get(level_one)
            if top is None:
                continue
            for row in rows:
                if row.module != module:
                    continue
                out.append(
                    PulledCategory(
                        id=pulled_id(row.id, slot),
                        name=row.name,
                        sort_order=row.sort_order,
                        parent_id=top.id,
                        parent_name=top.name,
                        module=module,
                        user_count=counts.get(level_one, {}).get(row.name, 0),
                    )
                )
    return out
