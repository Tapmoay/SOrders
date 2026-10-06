"""商品可见范围（白名单）的入参 / 出参，以及**唯一一处**可见性判据。

## 为什么判据要单独放一个函数
"这个商品对他可见吗"会被好几处问（商品列表、商品详情、下单校验、AI 读目录）。
散着写几遍的后果是"列表里看不到、但接口还收他的单"——
**看起来限制了、其实没有**，而这种漏洞在界面上完全看不出来。

## 从「只认单品」扩成「分类 + 单品、授权 + 排除」（CHG-0062 / 台账 L-23）
用户 2026-10-06 的两句话定了这一版的语义：

> 「假如以后有其他商品增加到这个分类，**它自动是显示的**」
> 「**这个分类是要全部显示的，但是某个商品我们不让它显示**，就把它直接关闭……
>   以后其他新商品增加到这个分类，**他也会正常显示**」

⇒ **分类行是"授权"、不是"快照"**：解析时按分类名现查商品库
（`resolve_visible_product_ids`）。⛔ 绝不能把"这一类下现有的商品编号"抄一份存起来 ——
那样以后新增到这一类的商品不会出现，正是用户明确否掉的那种做法。

四种行（见 `models/product_visibility.py`）：

| 行 | product_id | category_name | mode | 意思 |
|---|---|---|---|---|
| 单品授权 | 有值 | NULL | allow | 这一个给他看 |
| 单品排除 | 有值 | NULL | deny | 这一个不给他看（**这一类给他看时也能单独关掉一个**）|
| 分类授权 | NULL | 有值（空串 = 未分类）| allow | 这一类（含**以后新增**的）都给他看 |
| 分类排除 | NULL | 有值（空串 = 未分类）| deny | 这一类都不给他看 |

`scope='all'` 时仍然"不受限"，但**排除行照样生效**（"全给他看，就这一个不给"）。
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Product, User, UserProductVisibility
from app.models.enums import UserRole
from app.models.product_visibility import MODE_ALLOW, MODE_DENY

#: 可见范围的两档取值（`users.product_scope`）
SCOPE_ALL = "all"
SCOPE_CUSTOM = "custom"

#: 商品编号最多几条（挡住"整表勾选"这种误操作；也挡住畸形请求）
MAX_VISIBLE = 2000

#: 分类最多几个（与 `api/v1/product_categories.py` 的 `MAX_CATEGORIES` 同一个量级：
#: 分类名册本身就限了那么多，授权里能出现的分类不可能更多）
MAX_CATEGORIES = 200

#: 分类名长度上界（与 `products.category` / `product_categories.name` 的列宽一致）
MAX_CATEGORY_LEN = 32

#: 分类名（**元素自己**也带上界）：只给列表写 `max_length=` 限的是"最多几条"，
#: 不限"每一条多长" —— 一条 10 万字的分类名照样能被收下。
#: `_tools/qa/_audit_text_fields.py` 的「列表元素没有长度上界」查的就是这一层。
CategoryName = Annotated[str, StringConstraints(max_length=MAX_CATEGORY_LEN)]


class ProductVisibilityOut(BaseModel):
    scope: str = SCOPE_ALL
    #: 授权的单品（scope='custom' 时有意义）
    product_ids: list[int] = Field(default_factory=list)
    #: 授权的分类；**空串 = 「未分类」那一类**（与 `products.category` 同一套写法）
    category_names: list[CategoryName] = Field(default_factory=list)
    #: 关掉的单品（两档 scope 都生效）
    hidden_product_ids: list[int] = Field(default_factory=list)
    #: 关掉的分类；空串 = 「未分类」
    hidden_category_names: list[CategoryName] = Field(default_factory=list)


class ProductVisibilityIn(BaseModel):
    # ⚠️ 长度上界要显式写：枚举取值由下面的 `scope_ok` 管，但"长度"是另一回事 ——
    #    没有上界时，`scope="all"+8000 个空格` 这种输入会一路走到 `scope_ok` 才被拒，
    #    而文本审计（`_tools/qa/_audit_text_fields.py`）会如实报"这个字段多长都收"。
    #    与列宽一致：`users.product_scope` 是 VARCHAR(16)。
    scope: str = Field(..., max_length=16)
    product_ids: list[int] = Field(default_factory=list, max_length=MAX_VISIBLE)
    category_names: list[CategoryName] = Field(default_factory=list, max_length=MAX_CATEGORIES)
    hidden_product_ids: list[int] = Field(default_factory=list, max_length=MAX_VISIBLE)
    hidden_category_names: list[CategoryName] = Field(default_factory=list, max_length=MAX_CATEGORIES)

    @field_validator("scope")
    @classmethod
    def scope_ok(cls, v: str) -> str:
        s = (v or "").strip().lower()
        if s not in (SCOPE_ALL, SCOPE_CUSTOM):
            raise ValueError("可见范围只能是 all（全部）或 custom（只给勾选的）")
        return s

    @field_validator("product_ids", "hidden_product_ids")
    @classmethod
    def ids_dedup(cls, v: list[int]) -> list[int]:
        # 去重（保持首次出现的顺序）：重复编号会让"勾了 3 个"显示成"勾了 5 个"
        seen: list[int] = []
        for i in v:
            if i not in seen:
                seen.append(i)
        return seen

    @field_validator("category_names", "hidden_category_names")
    @classmethod
    def names_clean(cls, v: list[str]) -> list[str]:
        # 去空格 + 去重（保持首次出现的顺序）。
        # ⚠️ **空串要留着**：它表示「未分类」那一类（`products.category` 也是空串），
        #    这里顺手把空串丢掉的话，"给未分类整类授权"就会静默变成"什么都没配"。
        out: list[str] = []
        for raw in v:
            name = (raw or "").strip()
            if len(name) > MAX_CATEGORY_LEN:
                raise ValueError(f"分类名最长 {MAX_CATEGORY_LEN} 个字，收到的是「{name[:12]}…」")
            if name not in out:
                out.append(name)
        return out


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


def resolve_visible_product_ids(
    db: Session,
    scope: str,
    allow_ids: Iterable[int] = (),
    allow_categories: Iterable[str] = (),
    deny_ids: Iterable[int] = (),
    deny_categories: Iterable[str] = (),
) -> set[int] | None:
    """**唯一一处解析规则**：给一份"打算怎么配"的四元组，算出他到底能看见哪些商品。

    `None` = 不受限（全部可见）；空集合 = **真的什么都看不到**（两者绝不能混，
    见 `visible_product_ids` 的说明）。

    读端点（`visible_product_ids`）与写端点（`api/v1/users.py` 保存前的闸门）
    都走这一个函数 —— 各写一份的后果是"保存时算出来的"和"读的时候给出来的"不是一个答案。

    规则（⛔ 顺序就是语义，别合并）：
    1. `scope='all'` 且**一条排除行都没有** ⇒ `None`（不受限，最省事也最安全的那条路）；
    2. `scope='custom'` ⇒ 授权分类名下的商品（**现查**，含以后新增的）∪ 授权的单品；
       `scope='all'` ⇒ 全部在架商品；
    3. 再减去排除分类名下的商品与排除的单品（**排除优先**：两边都配了就按排除）。
    """
    allow_ids = set(allow_ids)
    allow_categories = set(allow_categories)
    deny_ids = set(deny_ids)
    deny_categories = set(deny_categories)

    if scope != SCOPE_CUSTOM and not deny_ids and not deny_categories:
        return None

    if scope == SCOPE_CUSTOM:
        picked: set[int] = set()
        if allow_ids:
            picked |= set(
                db.scalars(
                    select(Product.id).where(
                        Product.id.in_(allow_ids), Product.is_deleted.is_(False)
                    )
                ).all()
            )
        if allow_categories:
            # ⭐ 这一句就是"按分类授权"的全部：分类名现查，不是一个快照。
            picked |= set(
                db.scalars(
                    select(Product.id).where(
                        Product.category.in_(allow_categories), Product.is_deleted.is_(False)
                    )
                ).all()
            )
    else:
        picked = set(
            db.scalars(select(Product.id).where(Product.is_deleted.is_(False))).all()
        )

    hidden: set[int] = set(deny_ids)
    if deny_categories:
        hidden |= set(
            db.scalars(
                select(Product.id).where(
                    Product.category.in_(deny_categories), Product.is_deleted.is_(False)
                )
            ).all()
        )
    return picked - hidden


def _split_rows(
    rows: Iterable[UserProductVisibility],
) -> tuple[set[int], set[str], set[int], set[str]]:
    """把明细行拆成 (授权单品, 授权分类, 排除单品, 排除分类) 四份。

    ⚠️ 同名的分类行**以 deny 为准**（写入端已经归一，这里再挡一手：
    手写进库的历史数据、或者将来有人绕过 `replace_visibility` 直接插行时，
    "两边都配了"必须有一个确定的答案 —— 确定地偏向**不给看**）。
    """
    allow_ids: set[int] = set()
    deny_ids: set[int] = set()
    allow_cats: set[str] = set()
    deny_cats: set[str] = set()
    for r in rows:
        if r.product_id is not None:
            (deny_ids if r.mode == MODE_DENY else allow_ids).add(r.product_id)
        elif r.category_name is not None:
            (deny_cats if r.mode == MODE_DENY else allow_cats).add(r.category_name)
    return allow_ids - deny_ids, allow_cats - deny_cats, deny_ids, deny_cats


def visible_product_ids(db: Session, user: User | None) -> set[int] | None:
    """当前用户**可见**的商品编号集合；`None` = 不受限（全部可见）。

    调用方一律写成 `if ids is not None and p.id not in ids: 过滤掉` ——
    用 `None` 而不是"空集合"表示不受限，是因为空集合还有另一个意思
    （`scope=custom` 但什么都没配 = 真的什么都看不到），两者绝不能混。
    """
    if not visibility_applies_to(user):
        return None
    scope = getattr(user, "product_scope", None) or SCOPE_ALL
    rows = db.scalars(
        select(UserProductVisibility).where(UserProductVisibility.user_id == user.id)
    ).all()
    allow_ids, allow_cats, deny_ids, deny_cats = _split_rows(rows)
    return resolve_visible_product_ids(
        db, scope, allow_ids, allow_cats, deny_ids, deny_cats
    )


def product_visible_to(db: Session, user: User | None, product_id: int | None) -> bool:
    """单个商品对他可见吗（下单校验用）。不受限时恒 True。"""
    if product_id is None:
        return True
    ids = visible_product_ids(db, user)
    return ids is None or product_id in ids


def visibility_of(db: Session, user_id: int) -> ProductVisibilityOut:
    """读某个用户的可见范围（给"用户编辑页"回显，也给 AI 写卡片的"改之前"）。"""
    user = db.get(User, user_id)
    scope = (getattr(user, "product_scope", None) or SCOPE_ALL) if user else SCOPE_ALL
    rows = db.scalars(
        select(UserProductVisibility).where(UserProductVisibility.user_id == user_id)
    ).all()
    allow_ids, allow_cats, deny_ids, deny_cats = _split_rows(rows)
    return ProductVisibilityOut(
        scope=scope,
        product_ids=sorted(allow_ids),
        category_names=sorted(allow_cats),
        hidden_product_ids=sorted(deny_ids),
        hidden_category_names=sorted(deny_cats),
    )


def replace_visibility(db: Session, user: User, body: ProductVisibilityIn) -> ProductVisibilityOut:
    """整份替换某个用户的可见范围（**同一事务**里换开关 + 换明细）。

    ⚠️ 只勾选了不在商品库里的编号时**不报错也不写**（那些商品可能刚被删）——
    但会原样回读，所以调用方能看出"我勾的没进去"。真正需要拒绝的是
    "配完以后一个商品都看不到"，那会让他以为配好了、其实选品页是空的 ——
    这种情况由 API 层挡（见 `api/v1/users.py`）。

    ⚠️ **分类名不做"存不存在"的校验**：分类名可以指向一个**还没有商品**的分类
    （甚至还没建的分类名册条目）—— 用户的语义是"以后增加到这个分类的商品自动可见"，
    在这里拦住就等于把那条语义废掉。分类名册的错别字由 API 层/AI 层各自提示。
    """
    user.product_scope = body.scope
    db.execute(
        UserProductVisibility.__table__.delete().where(UserProductVisibility.user_id == user.id)
    )

    alive = set(
        db.scalars(
            select(Product.id).where(
                Product.id.in_(set(body.product_ids) | set(body.hidden_product_ids)),
                Product.is_deleted.is_(False),
            )
        ).all()
    )
    allow_ids = [pid for pid in body.product_ids if pid in alive] if body.scope == SCOPE_CUSTOM else []
    deny_ids = [pid for pid in body.hidden_product_ids if pid in alive and pid not in allow_ids]

    if body.scope == SCOPE_CUSTOM:
        # 分类授权：同一个分类名只留一行；与排除项重名时**排除优先**（写入端归一）
        for name in body.category_names:
            if name not in body.hidden_category_names:
                db.add(
                    UserProductVisibility(
                        user_id=user.id, category_name=name, mode=MODE_ALLOW
                    )
                )
    for name in body.hidden_category_names:
        db.add(UserProductVisibility(user_id=user.id, category_name=name, mode=MODE_DENY))
    for pid in allow_ids:
        db.add(UserProductVisibility(user_id=user.id, product_id=pid, mode=MODE_ALLOW))
    for pid in deny_ids:
        db.add(UserProductVisibility(user_id=user.id, product_id=pid, mode=MODE_DENY))
    db.flush()
    return visibility_of(db, user.id)
