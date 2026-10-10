from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    pass


class UserCategory(Base, TimestampMixin):
    """**账号分类名册**（派单员维护，决定账户/司机/货主/批发商四个名册页左侧那一列的顺序）。

    ## 为什么需要一张表，而不是只留 `users.category` 那个字符串
    分类名本身是一个字符串（`users.category`，空串 = 未分类），与 `products.category`
    完全同一口径；但**左侧那一列的顺序**必须是"人指定的"，不能按数量推出来 ——
    推出来的顺序是"现在哪类人多"，不是"店家想让人先看哪类"。所以**名册管顺序**。

    改名必须级联更新 `users.category`（见 `api/v1/user_categories.py` 的 rename，
    与名册改在同一事务里），否则改完名账号全变成"未分类"而且**不报错**。

    ## 为什么全店一份（不按人分区）
    账号是**全局主数据**：`Permission.USER_MANAGE` 的口径写着「账号、司机名册、货主名册
    都是全局主数据，不分归属」，司机的账号也不属于某个货主。
    所以这里没有 `shipper_id`，与商品分类（`product_categories`）同一套；
    地点/联系人/线路那三份**按人分区**的名册（`place_categories` 等）是另一种情况。

    ⚠️ 名册里没有的分类名**不是错误**（老数据、或别处直接写库），
    名册页会把它排在名册后面 —— 不许因为它不在名册里就把账号藏起来。

    ## 两级（2026-10-11 CHG-0112）
    用户 2026-10-11：「假如我的货主和批发商做了分类的话，然后我这个账户管理就会显示
    2 级分类，也就会显示他们里面的子分类」。**大类是一行、子类也是一行**，
    区别只在子类的 [parent_id] 指向大类（`NULL` = 大类本身）。

    ⛔ **只有两级**：父必须自己也是大类（`parent_id IS NULL`）—— 这条由写入路径
    （`api/v1/user_categories.py::_parent_or_400`）拦，所以结构里不出现第三层。
    `users.category` 存的仍然是**叶子名**（账号只认一个字符串），
    所以改名级联那段语义一个字都不用动。
    """

    __tablename__ = "user_categories"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # 分类名（与 `users.category` 同一个口径：strip 过、≤32 字）
    name: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    # 显示顺序：**小的在前**。新建的排到最后（不是 0 —— 排到 0 会抢在第一个前面）
    sort_order: Mapped[int] = mapped_column(Integer, default=0, index=True)
    # 上层分类（NULL = 大类本身）。`index=True` 的默认索引名 `ix_user_categories_parent_id`
    # 与迁移 030 里那句 CREATE INDEX **必须同名** —— 两处建的是同一张索引，别建两条。
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("user_categories.id"), nullable=True, index=True
    )
