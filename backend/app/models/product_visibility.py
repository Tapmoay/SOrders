from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.product import Product
    from app.models.user import User

#: 这一行是「给他看」还是「不给他看」（CHG-0062 加的维度）
MODE_ALLOW = "allow"
MODE_DENY = "deny"
MODES = (MODE_ALLOW, MODE_DENY)


class UserProductVisibility(Base, TimestampMixin):
    """**商品可见范围**的明细行：一件商品一行，或者一个分类一行。

    ## 语义（用户 2026-09-18 选的，2026-10-06 扩成分类维）
    > 「派单员可以指定他只只能看到哪些商品」→ **白名单**：勾了的才给他看。
    > 「假如以后有其他商品增加到这个分类，**它自动是显示的**」→ 分类行是**授权**，
    >   不是一个快照；解析时按分类现算（规则在 `schemas/product_visibility.py` 一处）。

    ## 四种行（两个新列 `category_name` / `mode` 的取值组合）
    | 行 | product_id | category_name | mode |
    |---|---|---|---|
    | 单品授权 | 有值 | NULL | allow |
    | 单品排除 | 有值 | NULL | deny |
    | 分类授权 | NULL | 有值（**空串 = 未分类**） | allow |
    | 分类排除 | NULL | 有值（**空串 = 未分类**） | deny |

    ⛔ `category_name` 的空串是**有意义的**（未分类那一类），与 `products.category`
    同一套写法；不另造哨兵值，两套写法会让"未分类"在授权与解析时对不上。

    ## 四条设计约束
    1. **开关在 `users.product_scope` 上，不在这张表上**：
       "明细为空" 有两种可能的意思 —— "还没配" 和 "什么都不给看"。
       混在一起就会出事故（上线时老账号全变空白）。所以空表 + `scope='all'` = 不限制；
       空表 + `scope='custom'` = **真的什么都看不到**（用户明确选了自定义却没配任何东西，
       这是他的意思，不是 bug）。
    2. **只对货主/批发商生效**：派单员自己不受限 —— 否则派单员把自己也挡在外面，
       连商品管理页都打不开（那就没人能改回来了）。判据写在
       `schemas/product_visibility.py` 的 `visible_product_ids()` 一处。
    3. **删除商品不用清理这张表**：商品是软删的，恢复后可见性应该还在
       （和"价格规则不随商品删除消失"同一个取向）。
    4. **一条明细只指一个目标**（`product_id` 与 `category_name` 恰有一个非空）：
       `ck_upv_one_target` 只对**新建的库**生效 —— SQLite 的 `ALTER TABLE` 加不了 CHECK，
       老库靠写入端归一（`replace_visibility` 永远是"先清后写"，只写一种目标）。
    """

    __tablename__ = "user_product_visibility"
    __table_args__ = (
        # 单品仍然是"一个商品一行"：SQLite/MySQL 里 NULL 互不相等，分类行（product_id 为 NULL）
        # 不受这条约束管 —— 分类行归下一条唯一约束管。
        UniqueConstraint("user_id", "product_id", name="uq_user_product_visibility"),
        # 一个用户的同一分类、同一模式只留一行（allow 与 deny 是两行，各自唯一）
        UniqueConstraint("user_id", "category_name", "mode", name="uq_upv_category"),
        CheckConstraint(
            "(product_id IS NULL) <> (category_name IS NULL)", name="ck_upv_one_target"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    #: 单品行才有值
    product_id: Mapped[int | None] = mapped_column(
        ForeignKey("products.id"), nullable=True, index=True
    )
    #: 分类行才有值；**空串 = 「未分类」**（与 `products.category` 同一套写法）
    category_name: Mapped[str | None] = mapped_column(String(32), nullable=True)
    #: allow = 给他看 / deny = 不给他看（排除优先，见 `resolve_visible_product_ids`）
    mode: Mapped[str] = mapped_column(String(8), default=MODE_ALLOW)

    user: Mapped["User"] = relationship(foreign_keys=[user_id])
    product: Mapped["Product | None"] = relationship(foreign_keys=[product_id])
