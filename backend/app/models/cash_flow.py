"""资金流水总账：所有实际收付（客户收款/司机付款/开销/退款/调账）的唯一写入点。"""

from datetime import date
from decimal import Decimal

from sqlalchemy import Date, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin
from app.models.enums import CashFlowBizType, CashFlowDirection


class CashFlow(Base, TimestampMixin):
    __tablename__ = "cash_flows"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    flow_date: Mapped[date] = mapped_column(Date, index=True)
    direction: Mapped[CashFlowDirection] = mapped_column(String(3), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    party_type: Mapped[str] = mapped_column(String(8), index=True)  # customer/driver/supplier/expense/other
    party_id: Mapped[int | None] = mapped_column(nullable=True, index=True)
    party_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    channel: Mapped[str] = mapped_column(String(16), default="cash")
    biz_type: Mapped[CashFlowBizType] = mapped_column(String(20), index=True)
    order_id: Mapped[int | None] = mapped_column(nullable=True, index=True)
    doc_id: Mapped[int | None] = mapped_column(nullable=True, index=True)
    note: Mapped[str] = mapped_column(String(256), default="")
    operator_id: Mapped[int | None] = mapped_column(nullable=True)
