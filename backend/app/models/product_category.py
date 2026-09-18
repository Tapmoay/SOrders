from typing import TYPE_CHECKING

from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    pass


class ProductCategory(Base, TimestampMixin):
    """**商品分类名册**（派单员维护，决定下单页左侧分类的顺序）。

    ## 为什么需要一张表，而不是继续用 `products.category` 的字符串
    v3.42 的分类是"每个商品自己带一个分类名"，选品页左侧的顺序只能**按商品数倒序**
    推出来 —— 推出来的顺序是"现在哪个分类货多"，不是"店家想让人先看哪个"。
    用户 2026-09-18 明确要：「派单单元可以创建商品分类，甚至可以更改商品分类的显示顺序」。

    所以：**名册管顺序**，`products.category` 仍然是"这个商品属于哪一类"（一个字符串）。
    为什么不在 products 上加外键：改名/删除会牵动一堆行，而分类名本来就是给人看的短词，
    字符串匹配够用；代价是**改名必须级联更新 products**（见 `api/v1/product_categories.py`
    的 rename，它和名册改在同一事务里）。

    ⚠️ 名册里没有的分类名**不是错误**（老数据、或别处直接写库），
    选品页会把它排在名册后面 —— 不许因为它不在名册里就把商品藏起来。
    """

    __tablename__ = "product_categories"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # 分类名（与 `products.category` 同一个口径：strip 过、≤32 字）
    name: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    # 显示顺序：**小的在前**。新建的排到最后（不是 0 —— 排到 0 会抢在第一个前面）
    sort_order: Mapped[int] = mapped_column(Integer, default=0, index=True)
