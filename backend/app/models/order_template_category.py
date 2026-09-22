"""预订单分类名册（派单员维护；决定「预订单」页左栏那一列叫什么、按什么顺序）。

## 为什么单开一套分类（照运费分类那次的口径）
用户 2026-09-22 对**预订单**说的是：「这个模板我们是要**做一个分类**的 —— 也是一样的，
**左边是分类管理**，就是**复用**嘛，复用那些**商品管理**的形式；**我右边就是订单**」。
也就是：**形制照抄商品分类**（一张 `name + sort_order` 的名册 + 一个「分类管理」页，
改名级联 / 排序整份 / 删除有挂账拒绝都同一套规矩），**内容各管各的** ——
商品分类是"店里怎么摆货"、运费分类是"这类货怎么收运费"，而这个是
"我这几张常用的单分成哪几类"（周单 / 月单 / 固定客户…）。

## 与名册的关系只有一条：**名字**
`order_templates.category` 存的是**分类名**（与 `products.category` 同一套做法，不是编号），
所以：
1. **改名必须级联**（同一事务里 `UPDATE order_templates SET category = 新名`）——
   不级联的话那些预设单会全变成"未分类"，而且**不报错**；
2. **删除还有预设单挂着 → 拒绝**并报数（⛔ 不"顺手把它们改成未分类"：那是悄悄改数据，
   改完在界面上看不出来 —— 与商品分类、开销分类一字不差）；
3. **空串 = 未分类**（老数据全在这一档），名册里没有的分类名**不是错误**，
   左栏会把它排在名册后面（`ProductPicker.categoryTabsOf` 那一份判据，全项目共用）。
"""
from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class OrderTemplateCategory(Base, TimestampMixin):
    __tablename__ = "order_template_categories"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    #: 分类名（≤32 字，唯一）。与商品/开销/运费分类同口径，但四张表各管各的。
    name: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    #: 显示顺序：**小的在前**（新建的排到最后，不是 0 —— 排到 0 会抢在第一个前面）
    sort_order: Mapped[int] = mapped_column(Integer, default=0, index=True)
