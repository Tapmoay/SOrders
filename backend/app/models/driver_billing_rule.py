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

from sqlalchemy import JSON, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

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

    def params(self) -> dict:
        """规则的参数（给"改前/改后"的审计日志和确认卡用）。"""
        return {
            "name": self.name,
            "vehicle_type": self.vehicle_type,
            "salary": str(self.salary),
            "piece_amount": str(self.piece_amount),
            "piece_unit": self.piece_unit,
            "commission_base": self.commission_base,
            "commission_rate": str(self.commission_rate),
            "commission_product_ids": list(self.commission_product_ids or []),
            "remark": self.remark,
        }
