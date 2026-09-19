"""客户收款单：逐单核销（默认 itemized），绑定 orders 并标记 paid。"""

from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, Boolean, Date, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin
from app.models.enums import ReceiptSettleMode


class ShipperReceipt(Base, TimestampMixin):
    __tablename__ = "shipper_receipts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    method: Mapped[str] = mapped_column(String(16))  # cash/transfer/wechat/arrears_settle
    received_at: Mapped[date] = mapped_column(Date, index=True)
    order_ids: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)  # 逐单核销绑定
    settle_mode: Mapped[ReceiptSettleMode] = mapped_column(String(12), default=ReceiptSettleMode.ITEMIZED)
    arrears_unit_id: Mapped[int | None] = mapped_column(nullable=True)
    invoiced: Mapped[bool] = mapped_column(Boolean, default=False)
    note: Mapped[str] = mapped_column(String(256), default="")
    operator_id: Mapped[int | None] = mapped_column(nullable=True)
