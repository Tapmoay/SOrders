"""司机计费规则模板：一份**可以命名**的规则 = 固定工资 + 每单固定 + 提成（三件可任意组合）。

用户 2026-09-18 的原话：「普通车司机是按固定工资的…我们还可以再加一个按计件提成或者车辆提成…
挂车司机则就是两种，一个是计件（一趟货多少钱），一个是固定工资加提成（抽多少提成，
可能是运费的提成，也可能是走商品的提成）…可以创建固定的模板…给司机挂上我们已经配置好的模板，
那规则可能是命好了一个名称」。

所以这个表不是"一种计费方式"，而是**一张规则表**：
- 规则可以被命名（`name`），AI 和界面都按名字找它、把它挂给司机；
- 规则可以标适用车型（`vehicle_type`，空=通用），挂错车型会被拦下来（见 `api/v1/driver_billing_rules.py`）；
- 规则的**参数**怎么变成钱，只有一处实现：`services/driver_pay.py`。

⚠️ 改规则的参数**不会**改变历史账单：派单时会把当时的规则**快照**到订单上
（`orders.driver_rule_snapshot`），送达生成账单用的是快照。这和 `driver_billing_mode_snapshot`
是同一个道理——司机后来换了规则，已经送完的单不能跟着变。
"""

from decimal import Decimal

from sqlalchemy import JSON, ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, SoftDeleteMixin, TimestampMixin


class DriverBillingRule(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "driver_billing_rules"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), index=True)
    # small/large/trailer；空 = 通用（不限车型）
    vehicle_type: Mapped[str | None] = mapped_column(String(16), nullable=True)

    # ① 固定工资（元/月）——走月度工资单，不进"按单账单"
    salary: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    # ② 每单/每车（或每件）固定金额
    piece_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    piece_unit: Mapped[str] = mapped_column(String(8), default="order")  # order / item
    #: 每单金额怎么定：`uniform` = 所有单统一（用下面的 `piece_amount` / `commission_rate`）；
    #: `category` = **按运费分类**逐类定价（金额在 `driver_billing_rule_categories` 里）。
    #: 用户 2026-09-21：「按单计费有两种规则：所有单统一价/统一提成，或者按分类匹配」。
    piece_mode: Mapped[str] = mapped_column(String(16), default="uniform")
    # ③ 提成 = 基数 × 比例
    commission_base: Mapped[str] = mapped_column(String(16), default="none")  # none/freight/goods
    commission_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0"))
    # **只对哪些商品抽成**（商品 id 列表，空 = 不限）。用户 2026-09-18：
    # 「配置……哪些商品是要抽成的」——所以抽成不只是比例，还有范围。
    # 只对"按商品金额抽成"有意义（按整单运费抽时没有"哪些商品"这回事，校验会拦）。
    commission_product_ids: Mapped[list | None] = mapped_column(JSON, nullable=True, default=list)

    remark: Mapped[str] = mapped_column(Text, default="")
    # ⚠️ 这里**故意不加外键**：`users.driver_rule_id` 已经指向本表，如果这一列也指向 users，
    #    两张表就形成外键环——SQLAlchemy 排不出删除顺序（实测会在 drop_all 时告警，
    #    某些库上直接建不出来）。谁建的只是一条备注性的信息，不值得为它引入一个环。
    created_by: Mapped[int | None] = mapped_column(nullable=True)

    #: 按分类定价的那些行（`piece_mode=category` 时才有内容）。
    #  ⚠️ `lazy="selectin"`：`driver_pay.rule_of_user()` 只拿得到规则对象、没有 session，
    #     它必须能直接读到这张表；改成 lazy 查询的话，五个消费点里会有一半拿到空表
    #     （提成静默变 0，而界面上规则看着配好了）。
    #  ⚠️ `cascade="all, delete-orphan"`：删规则时这张表的行跟着走（关联表没有历史价值）。
    category_rows: Mapped[list["DriverBillingRuleCategory"]] = relationship(
        "DriverBillingRuleCategory",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    #: 这份规则**用哪几条运费价目**（用户 2026-09-21：「规则也就是取运费模板吧，也就是价目……
    #  它就像匹配商品一样，勾选的时候就像是一个商品界面，可以全选本分类，也可以单独勾」）。
    #  ⛔ 价目**不匹配车型也不匹配司机**：那条线上只有"这份规则勾了它"。
    #     派单选了司机 → 他的规则 → 规则勾的价目里，路线/分类对得上这一单的那一条就是运费。
    template_rows: Mapped[list["DriverBillingRuleTemplate"]] = relationship(
        "DriverBillingRuleTemplate",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def params(self) -> dict:
        """规则的参数（给"改前/改后"的审计日志和确认卡用）。"""
        return {
            "name": self.name,
            "vehicle_type": self.vehicle_type,
            "salary": str(self.salary),
            "piece_amount": str(self.piece_amount),
            "piece_unit": self.piece_unit,
            "piece_mode": self.piece_mode or "uniform",
            "template_ids": [int(x.template_id) for x in (self.template_rows or [])],
            "categories": [
                {
                    "category_id": int(r.category_id),
                    "piece_amount": str(r.piece_amount),
                    "commission_rate": str(r.commission_rate),
                }
                for r in (self.category_rows or [])
            ],
            "commission_base": self.commission_base,
            "commission_rate": str(self.commission_rate),
            "commission_product_ids": list(self.commission_product_ids or []),
            "remark": self.remark,
        }


class DriverBillingRuleCategory(Base, TimestampMixin):
    """**按分类的每单金额/比例**（用户 2026-09-21：「按单计费有两种规则：所有单统一，
    或者按分类匹配」）。

    一种规则现在有两种形态，二者**互斥**（`piece_mode` ∈ uniform/category）：

    | 形态 | 每单给司机多少 | 存在哪 |
    | --- | --- | --- |
    | `uniform`（统一） | 所有单一个数 | `driver_billing_rules.piece_amount` / `commission_rate` |
    | `category`（按分类） | 看这一单属于哪一类货 | **本表**（一类一行） |

    ⚠️ 分类之外的单（或者这一单没定分类）在 `category` 形态下**没有价**：
    `driver_pay` 会如实退回"这一单没算出来的那部分"（而不是拿统一价兜底 ——
    那会让"按分类定价"看起来生效了，实际所有单都拿到了同一个数）。
    """

    __tablename__ = "driver_billing_rule_categories"
    __table_args__ = (
        UniqueConstraint("rule_id", "category_id", name="uq_driver_rule_category"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    rule_id: Mapped[int] = mapped_column(ForeignKey("driver_billing_rules.id"), index=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("freight_categories.id"), index=True)
    #: 这一类货每单给司机多少钱（`piece_unit=item` 时按件乘数量）
    piece_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    #: 这一类货的提成比例（口径跟规则上的 `commission_base` 走）
    commission_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0"))


class DriverBillingRuleTemplate(Base, TimestampMixin):
    """**这份规则用哪几条运费价目**（价目 ↔ 规则，多对多）。

    用户 2026-09-21：「运费模板不会去匹配车型也不会匹配司机，匹配车型和匹配司机在计费规则中……
    这一目录就归这个计费规则，而这个规则在匹配对应的司机」。

    所以链子是：**价目（路线 + 分类 + 价格）** →（规则勾选）→ **规则（车型 + 多少钱）**
    →（挂在司机身上）→ **司机**。派单时选了司机，运费就从"他的规则勾的那几条价目"里按
    路线 + 分类挑一条。

    ⚠️ 按**编号**关联（价目改名/改价都不影响这份绑定）。
    ⚠️ 不软删：换绑定就是删行（绑定关系没有"历史价值"，要查历史看订单上的运费快照）。
    """

    __tablename__ = "driver_billing_rule_templates"
    __table_args__ = (
        UniqueConstraint("rule_id", "template_id", name="uq_driver_rule_template"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    rule_id: Mapped[int] = mapped_column(ForeignKey("driver_billing_rules.id"), index=True)
    template_id: Mapped[int] = mapped_column(ForeignKey("freight_templates.id"), index=True)
