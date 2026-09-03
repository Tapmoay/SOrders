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
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    method: Mapped[str] = mapped_column(String(16), default="")
    operator_id: Mapped[int | None] = mapped_column(nullable=True)
    note: Mapped[str] = mapped_column(String(256), default="")
