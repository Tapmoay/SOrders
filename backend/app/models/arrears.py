"""挂账单位：赊账客户（临时货主/单位），订单可选择挂账到该单位。"""

from decimal import Decimal

from sqlalchemy import Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, SoftDeleteMixin, TimestampMixin


class ArrearsUnit(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "arrears_units"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    phone: Mapped[str] = mapped_column(String(32), default="")
    remark: Mapped[str] = mapped_column(String(256), default="")
    # 信用额度（FEAT-0015 第五期）：这一家最多能赊多少。**可空**，NULL = **不限额**
    # ——⛔ 不是 0（0 的含义是「一分钱都不许赊」，与"没设额度"是两件事）。
    # ⚠️ 额度不参与任何金额计算：它只在欠款报表上算出「还能赊多少 / 超了没有」，
    #    超限只是**提示**，不挡下单、不挡发货（金额的唯一口径仍只有 order_money 一处）。
    credit_limit: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
