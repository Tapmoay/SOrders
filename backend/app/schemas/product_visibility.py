"""商品可见范围（白名单）的入参 / 出参，以及**唯一一处**可见性判据。

## 为什么判据要单独放一个函数
"这个商品对他可见吗"会被好几处问（商品列表、商品详情、下单校验、AI 读目录）。
散着写几遍的后果是"列表里看不到、但接口还收他的单"——
**看起来限制了、其实没有**，而这种漏洞在界面上完全看不出来。
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Product, User, UserProductVisibility
from app.models.enums import UserRole

#: 可见范围的两档取值（`users.product_scope`）
SCOPE_ALL = "all"
SCOPE_CUSTOM = "custom"

#: 白名单最多几条（挡住"整表勾选"这种误操作；也挡住畸形请求）
MAX_VISIBLE = 2000


class ProductVisibilityOut(BaseModel):
    scope: str = SCOPE_ALL
    product_ids: list[int] = Field(default_factory=list)


class ProductVisibilityIn(BaseModel):
    # ⚠️ 长度上界要显式写：枚举取值由下面的 `scope_ok` 管，但"长度"是另一回事 ——
    #    没有上界时，`scope="all"+8000 个空格` 这种输入会一路走到 `scope_ok` 才被拒，
    #    而文本审计（`_tools/qa/_audit_text_fields.py`）会如实报"这个字段多长都收"。
    #    与列宽一致：`users.product_scope` 是 VARCHAR(16)。
    scope: str = Field(..., max_length=16)
    product_ids: list[int] = Field(default_factory=list, max_length=MAX_VISIBLE)

    @field_validator("scope")
    @classmethod
    def scope_ok(cls, v: str) -> str:
        s = (v or "").strip().lower()
        if s not in (SCOPE_ALL, SCOPE_CUSTOM):
            raise ValueError("可见范围只能是 all（全部）或 custom（只给勾选的）")
        return s

    @field_validator("product_ids")
    @classmethod
    def ids_dedup(cls, v: list[int]) -> list[int]:
        # 去重（保持首次出现的顺序）：重复编号会让"勾了 3 个"显示成"勾了 5 个"
        seen: list[int] = []
        for i in v:
            if i not in seen:
                seen.append(i)
        return seen


def visibility_applies_to(user: User | None) -> bool:
    """可见性只对**货主/批发商**生效。

    为什么派单员不受限：派单员要能进商品管理页改回去。把自己也挡在外面 =
    "设错了就没人能改回来"（这是这个仓库反复强调的一类后果）。
    司机完全没有商品目录入口，也就无所谓。
    """
    if user is None:
        return False
    role = getattr(user, "role", None)
    role_key = role.value if hasattr(role, "value") else str(role or "")
    return role_key.lower() == UserRole.SHIPPER.value


def visible_product_ids(db: Session, user: User | None) -> set[int] | None:
    """当前用户**可见**的商品编号集合；`None` = 不受限（全部可见）。

    调用方一律写成 `if ids is not None and p.id not in ids: 过滤掉` ——
    用 `None` 而不是"空集合"表示不受限，是因为空集合还有另一个意思
    （`scope=custom` 但一个都没勾 = 真的什么都看不到），两者绝不能混。
    """
    if not visibility_applies_to(user):
        return None
    if (getattr(user, "product_scope", None) or SCOPE_ALL) != SCOPE_CUSTOM:
        return None
    rows = db.scalars(
        select(UserProductVisibility.product_id).where(UserProductVisibility.user_id == user.id)
    ).all()
    return set(rows)


def product_visible_to(db: Session, user: User | None, product_id: int | None) -> bool:
    """单个商品对他可见吗（下单校验用）。不受限时恒 True。"""
    if product_id is None:
        return True
    ids = visible_product_ids(db, user)
    return ids is None or product_id in ids


def visibility_of(db: Session, user_id: int) -> ProductVisibilityOut:
    """读某个用户的可见范围（给"用户编辑页"回显）。"""
    user = db.get(User, user_id)
    scope = (getattr(user, "product_scope", None) or SCOPE_ALL) if user else SCOPE_ALL
    ids = db.scalars(
        select(UserProductVisibility.product_id)
        .where(UserProductVisibility.user_id == user_id)
        .order_by(UserProductVisibility.product_id)
    ).all()
    return ProductVisibilityOut(scope=scope, product_ids=list(ids))


def replace_visibility(db: Session, user: User, body: ProductVisibilityIn) -> ProductVisibilityOut:
    """整份替换某个用户的可见范围（**同一事务**里换开关 + 换明细）。

    ⚠️ 只勾选了不在商品库里的编号时**不报错也不写**（那些商品可能刚被删）——
    但会原样回读，所以调用方能看出"我勾的没进去"。真正需要拒绝的是
    "scope=custom 且一个商品都不存在"，那会让用户以为配好了、其实什么都看不到 ——
    这种情况由 API 层挡（见 users.py）。
    """
    user.product_scope = body.scope
    db.execute(
        UserProductVisibility.__table__.delete().where(UserProductVisibility.user_id == user.id)
    )
    if body.scope == SCOPE_CUSTOM and body.product_ids:
        alive = set(
            db.scalars(
                select(Product.id).where(
                    Product.id.in_(body.product_ids), Product.is_deleted.is_(False)
                )
            ).all()
        )
        for pid in body.product_ids:
            if pid in alive:
                db.add(UserProductVisibility(user_id=user.id, product_id=pid))
    db.flush()
    return visibility_of(db, user.id)
