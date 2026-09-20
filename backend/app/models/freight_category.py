"""运费分类名册（派单员维护；决定**运费模板**与**计费规则**按哪一类货定价）。

## 为什么单独一套分类，而不是复用商品分类

用户 2026-09-21 的答复（问的就是这件事）：
> 「复用商品管理的**那样子的形式**，因为我们好多版本都是复用他那种形式。也就是说，
>  **他那个运费模板是有自己的一套分类的**，只是我们复用他那个**代码和方法**。」

也就是说：**形制照抄商品分类**（一张 `name + sort_order` 的名册 + 一个"分类管理"页，
改名/排序/删除拒绝都同一套规矩），但**内容各管各的** —— 商品分类是"店里怎么摆货"，
运费分类是"这类货怎么收运费/怎么给司机算钱"。两者名字常常相同（蔬菜/水果/冻品），
但允许不同，也不能互相改。

## 它被谁用（两条线，都是 m:n，都按**编号**关联）

| 用它的地方 | 关联表 | 作用 |
| --- | --- | --- |
| 运费模板（一条价目） | `freight_template_categories` | 这类货走这条价目（用户：「一个模板可以有多个分类」） |
| 司机计费规则（按单计费） | `driver_billing_rule_categories` | 这类货每单给司机多少钱/抽多少（另一种是"所有单统一"） |

⛔ 关联一律走**编号**：分类改名之后两条线都不会断（商品/开销那两套是用**名字**当键的，
所以它们必须级联改名；这里用编号，改名天然安全）。
⚠️ 而**订单上存的是"编号 + 名字快照"**（`orders.freight_category_id` / `freight_category`）：
编号用于算钱（分类改名/软删都不影响历史单），名字快照用于显示与复核 ——
与 `driver_rule_id` + `driver_rule_snapshot` 同一个道理：**历史单据要能独立看懂**。
"""

from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class FreightCategory(Base, TimestampMixin):
    __tablename__ = "freight_categories"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    #: 分类名（≤32 字，唯一）。**与商品分类同口径**，但两张表各管各的。
    name: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    #: 显示顺序：**小的在前**（新建的排到最后，不是 0 —— 排到 0 会抢在第一个前面）
    sort_order: Mapped[int] = mapped_column(Integer, default=0, index=True)
