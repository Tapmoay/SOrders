from decimal import Decimal

from sqlalchemy import ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, SoftDeleteMixin, TimestampMixin


class FreightTemplate(Base, TimestampMixin, SoftDeleteMixin):
    """运费价目 —— **挂在一条路线上的一条价目**（车/趟/回程各是一条）。

    ## 2026-09-19 改造（用户口述的三句话）
    > 「它那个模板不是初始名字然后后面终点名字是什么来创建的，它是**根据路线**来创建的。
    >   你说先要创建一个**路线**，然后才能根据这个路线来创建一个模板，然后我们才能根据这个
    >   模板来创建一个对应的订单的价格，因为订单也是按照这个路线来搞的。
    >   而且**同一个路线，我们可以配置多个价格**，比如价格一价格二价格三，都可以修改」。
    > 「一般这个价格是**会跟司机绑定**的…相同的路线不同的司机可能给不同的价格，
    >   所以下单的时候就不需要选择那个价格模板了，因为我们只要选了司机他是自动跟上的。
    >   所以创建的路线模板**是可以绑定司机的**，当然了，可以绑定多个司机」。

    于是这张表的形状变成：
    · `route_id` → 一条**路线**（`shipper_addresses` 那一行；复用「地址与联系人 → 常用线路」，
      也能在模板表单里现场新建一条）。它不再是"起点/终点两段手打文字"；
    · `from_place` / `to_place` 保留，但身份变成**路线快照**（老数据与显示都不用改口径）；
    · `price_name` = 这条价目叫什么（小车价 / 大车价 / 回程价…，用户自定义）；
    · 谁用这一档 → [FreightTemplateDriver]（一条价目绑多个司机）。

    ⛔ **一个司机在同一条路线上只属于一档**：否则"选了司机自动带价"就没有唯一答案，
    而那种歧义不会报错，只会默默取到另一条价目。判据在 `api/v1/freight_templates.py`。
    ⛔ 删除是**软删**（用户 2026-09-19：「这些所有功能的删（撤）销操作就是软删」）。
    """

    __tablename__ = "freight_templates"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), index=True)
    #: 哪条路线（`shipper_addresses.id`）。老数据可能是 NULL（迁移时按起点/终点补建路线）。
    route_id: Mapped[int | None] = mapped_column(
        ForeignKey("shipper_addresses.id"), nullable=True, index=True
    )
    #: 路线的**快照**（起点 / 终点）。路线改名不会追溯改这里 —— 历史价目要能独立复核。
    from_place: Mapped[str] = mapped_column(String(128), default="")
    to_place: Mapped[str] = mapped_column(String(128), default="")
    #: 这条价目叫什么（用户自定义，如「小车价」「大车价」「回程价」）
    price_name: Mapped[str] = mapped_column(String(32), default="")
    # small/large/trailer；空=通用（不限车型）。老字段，保留兼容
    vehicle_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    fee: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    remark: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)


class FreightTemplateDriver(Base, TimestampMixin):
    """**这条价目归哪些司机用**（一条价目可以绑多个司机）。

    用户 2026-09-19：「创建的路线模板是可以绑定司机的，当然了，可以绑定多个司机」。
    派单时选了司机 → 按"这一单的路线"找到唯一那条绑了他的价目 → 自动带出金额。

    ⚠️ 这张表**不软删**：解绑就是删行（绑定关系没有"历史价值"可言，
    而"这个司机曾经用过这一档"要查的是订单快照，不是这里）。
    """

    __tablename__ = "freight_template_drivers"
    __table_args__ = (
        UniqueConstraint("template_id", "driver_id", name="uq_freight_template_driver"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    template_id: Mapped[int] = mapped_column(
        ForeignKey("freight_templates.id"), index=True
    )
    driver_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)


class FreightTemplateCategory(Base, TimestampMixin):
    """**这条价目算哪几类货**（用户 2026-09-21：「一个模板可以有多个分类」）。

    派单时的匹配是「路线 + 分类 + 司机 → 唯一一条价目」（唯一实现
    `services/freight_pricing.py`）：所以一条价目挂多个分类 = "这几类货同价"。

    ⚠️ 按**编号**关联（不是名字）：分类改名之后这条线不会断。
    ⚠️ 这张表**不软删**：改绑定就是删行 —— 绑定关系没有"历史价值"，
      要查历史请看订单上的 `freight_category_id` / `freight_category` 快照。
    """

    __tablename__ = "freight_template_categories"
    __table_args__ = (
        UniqueConstraint("template_id", "category_id", name="uq_freight_template_category"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    template_id: Mapped[int] = mapped_column(ForeignKey("freight_templates.id"), index=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("freight_categories.id"), index=True)
