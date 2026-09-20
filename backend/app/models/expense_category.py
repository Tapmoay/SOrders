"""开销分类名册（派单员维护；决定开销页左侧那一列叫什么、按什么顺序、卡片上突出哪一项）。

## 为什么需要一张表，而不是继续用 `ExpenseCategory` 那个枚举

`expenses.category` 原来是一个**写死的枚举**（fuel/repair/toll/parking/fine/insurance/loss/other）。
用户 2026-09-20 要的是「开销分类……也有个分类管理」——也就是**店家自己加分类**
（比如"违章罚款""装卸费""水电"），并且能改顺序。枚举做不到这件事，而且枚举一旦缺项，
后端读接口直接 500（本项目踩过：`ExpenseOut.category` 是枚举，库里存了中文名就 500）。

所以照**商品分类名册**（`models/product_category.py`）那一套来：
名册管"有什么分类、什么顺序、卡片突出什么"，`expenses.category` 仍然是一个自由字符串。

## `link_kind`：卡片上"突出哪一项"由分类决定（用户点名不许一刀切）

原话：「燃油或者说维修这些主要是车辆，所以关联的是车辆，首要突出的是车辆；
如果是其他的成本的话，可能关联的就是其他的……**要具体问题具体判断，不能一刀切**」。

所以每个分类带一列 `link_kind` ∈ {vehicle, driver, order, none}：
· 燃油 / 维修 / 过路 / 停车 / 保险 → `vehicle`（这一笔是**哪台车**花的）；
· 货损 → `order`（这一笔挂在**哪一单**上）；
· 其他 / 说不清 → `none`（卡片只显示分类 + 金额 + 日期）。
⛔ 这一列是**用户在「分类管理」里自己设的**，不是代码里的 `when(分类名)` —— 他新加一个
   「违章罚款」并选"关联车辆"就能用，不需要改代码。
"""

from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

#: `link_kind` 的取值（卡片上突出哪一项）。字符串入库，方便以后加（比如挂账单位）。
LINK_KINDS = ("vehicle", "driver", "order", "none")


class ExpenseCategory(Base, TimestampMixin):
    __tablename__ = "expense_categories"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # 分类名（与 `expenses.category` 同一个口径：strip 过、≤32 字）
    name: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    # 显示顺序：**小的在前**。新建的排到最后（不是 0 —— 排到 0 会抢在第一个前面）
    sort_order: Mapped[int] = mapped_column(Integer, default=0, index=True)
    # 卡片上突出哪一项（见模块头注释）。默认 none = 只显示分类/金额/日期
    link_kind: Mapped[str] = mapped_column(String(16), default="none")
