# -*- coding: utf-8 -*-
"""模块分类名册（FEAT-0026，2026-10-12）：批发商管理 / 司机管理 / 货主管理**各自**的一份名册。

## 用户的口径（逐字）
用户 2026-10-12：「我批发商管理他那个分类啊，他那个分类是**跟账号管理不一样**的，
**他现在串在一起了**。他那个分类是**可以新建的、另外建的**。只不过我们**账号管理拉取他们的
分类的时候是搞 2 级分类**；当然，我们这些**子分类是不会拉取主分类**的。也就如**司机管理**，
还有其他的**批发商管理**，**他们是有自己的分类的**，他们的分类基本上就是 **1 级**、不会有 2 级的。
然后我们的**账号管理**，他的那个分类他是**有 2 级的**，他是**主动拉取**的，而且我们分类
**已经固定好了**的。」

⇒ 这就是"两张表、两件事"，⛔ 不许再合成一张：

| 表 | 是什么 | 谁能改 | 几级 |
|---|---|---|---|
| `user_categories`（`models/user_category.py`） | **账号分类名册** | 一级是固定的六类（`services/user_category.py` 的常量）；二级由本表**拉取**而来 | 两级 |
| `module_categories`（本文件） | **模块自己的分类名册** | 各模块自己的「管理分类」入口 | **一级**（没有 parent_id） |

为什么合表不行：合了之后在「批发商管理」新建一格分类会**同时**出现在账号册里，
而用户的口径是账号管理**主动拉取** —— 拉取是**读**，不是写。

## 形状
`module` 分区（取值 `members` / `shippers` / `drivers`，与 App 的 `UserPool.key` 同名），
每个模块一份**平表**名册（没有 parent_id：用户明说模块自己的分类「基本上就是 1 级」）。

`(module, name)` 的唯一性**在代码里按未删行判**，不建数据库唯一索引 ——
用户 2026-09-20 的硬规矩是「所有删除一律软删 + 必须有恢复路径」，
软删之后要能重建同名（唯一索引会把"删了再建同名"变成 500）。
"""

from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, SoftDeleteMixin, TimestampMixin


class ModuleCategory(Base, TimestampMixin, SoftDeleteMixin):
    """模块自有分类名册的一行（平表；`module` 分区，没有父子）。"""

    __tablename__ = "module_categories"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    #: 哪一份名册：`members`=批发商管理 / `shippers`=货主管理 / `drivers`=司机管理
    module: Mapped[str] = mapped_column(String(16), index=True)
    name: Mapped[str] = mapped_column(String(32), index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, index=True)
