from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.product import Product
    from app.models.user import User


class UserProductVisibility(Base, TimestampMixin):
    """**商品可见白名单**：`users.product_scope == 'custom'` 时，只有这张表里的商品
    对该用户可见。

    ## 语义（用户 2026-09-18 选的）
    > 「派单员可以指定他只只能看到哪些商品」→ **白名单**：勾了的才给他看。

    ## 三条设计约束
    1. **开关在 `users.product_scope` 上，不在这张表上**：
       "白名单为空" 有两种可能的意思 —— "还没配" 和 "什么都不给看"。
       混在一起就会出事故（上线时老账号全变空白）。所以空表 + `scope='all'` = 不限制；
       空表 + `scope='custom'` = **真的什么都看不到**（用户明确选了自定义却没勾任何商品，
       这是他的意思，不是 bug）。
    2. **只对货主/批发商生效**：派单员自己不受限 —— 否则派单员把自己也挡在外面，
       连商品管理页都打不开（那就没人能改回来了）。判据写在 `products.py` 的
       `visible_product_ids()` 一处。
    3. **删除商品不用清理这张表**：商品是软删的，恢复后可见性应该还在
       （和"价格规则不随商品删除消失"同一个取向）。
    """

    __tablename__ = "user_product_visibility"
    __table_args__ = (
        UniqueConstraint("user_id", "product_id", name="uq_user_product_visibility"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)

    user: Mapped["User"] = relationship(foreign_keys=[user_id])
    product: Mapped["Product"] = relationship(foreign_keys=[product_id])
