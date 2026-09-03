"""开销单：油费/维修/过路/停车/罚款/保险/货损/其他，保存后自动生成资金流水。"""

from datetime import date
from decimal import Decimal

from sqlalchemy import Date, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin
from app.models.enums import ExpenseCategory


class Expense(Base, TimestampMixin):
    __tablename__ = "expenses"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    exp_date: Mapped[date] = mapped_column(Date, index=True)
    category: Mapped[ExpenseCategory] = mapped_column(String(16), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    driver_id: Mapped[int | None] = mapped_column(nullable=True, index=True)
    vehicle_id: Mapped[int | None] = mapped_column(nullable=True, index=True)
    order_id: Mapped[int | None] = mapped_column(nullable=True, index=True)
    note: Mapped[str] = mapped_column(String(256), default="")
    operator_id: Mapped[int | None] = mapped_column(nullable=True)
