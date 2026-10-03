"""司机结算单：按月结算凭证，DRAFT→CONFIRMED→PAID→CANCELLED。"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, JSON, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin
from app.models.enums import DriverBillType, SettlementStatus


class DriverSettlement(Base, TimestampMixin):
    __tablename__ = "driver_settlements"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    driver_id: Mapped[int] = mapped_column(index=True)
    settle_type: Mapped[DriverBillType] = mapped_column(String(8))
    month: Mapped[str] = mapped_column(String(7), index=True)  # YYYY-MM
    period_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    period_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    status: Mapped[SettlementStatus] = mapped_column(String(12), default=SettlementStatus.DRAFT, index=True)
    order_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    #: 建单当刻锁定的明细行（`driver_bills.id` 清单）——**含 `order_id` 为空的历史孤儿账单**。
    #: `confirm` / `pay` / `cancel` 一律按它认「这一单覆盖哪几笔」：`create` 与 `confirm`
    #: 各写一套取数条件正是「结算单金额 970.00 与明细合计 940.00」（2026-10-03 BUG-0007）的病根。
    #: 可空只为兼容老单（老草稿没有这份清单，确认时走老路）。
    bill_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    #: 手工改额时记下的差额（`amount − 建单时明细合计`）。恒等式
    #: `amount == 明细合计 + adjustment` 在确认与付款两处都成立；老单 / 没改过 = 0。
    adjustment: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), default=Decimal("0"), server_default="0"
    )
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    method: Mapped[str] = mapped_column(String(16), default="")
    operator_id: Mapped[int | None] = mapped_column(nullable=True)
    note: Mapped[str] = mapped_column(String(256), default="")
