"""司机应付明细：PIECE（按单计费）与 SALARY（按月薪）统一表，按月归属。"""

from decimal import Decimal

from sqlalchemy import Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin
from app.models.enums import DriverBillStatus, DriverBillType


class DriverBill(Base, TimestampMixin):
    __tablename__ = "driver_bills"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    driver_id: Mapped[int] = mapped_column(index=True)
    bill_type: Mapped[DriverBillType] = mapped_column(String(8), index=True)
    order_id: Mapped[int | None] = mapped_column(nullable=True, index=True)
    month: Mapped[str] = mapped_column(String(7), index=True)  # YYYY-MM
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    status: Mapped[DriverBillStatus] = mapped_column(String(12), default=DriverBillStatus.OPEN, index=True)
    settled_doc_id: Mapped[int | None] = mapped_column(nullable=True)
    note: Mapped[str] = mapped_column(String(256), default="")
