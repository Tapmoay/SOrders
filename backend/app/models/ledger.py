from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Date, Enum, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.enums import LedgerSource

if TYPE_CHECKING:
    from app.models.order import Order, OrderProduct
    from app.models.product import Product
    from app.models.user import User


class Ledger(Base, TimestampMixin):
    __tablename__ = "ledgers"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    shipper_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True, nullable=True)
    temp_shipper_name: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    entry_date: Mapped[date] = mapped_column(Date, index=True)
    product_name: Mapped[str] = mapped_column(String(256))
    quantity: Mapped[int] = mapped_column(default=1)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(14, 4))
    total: Mapped[Decimal] = mapped_column(Numeric(14, 4))
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"), nullable=True, index=True)
    order_product_id: Mapped[int | None] = mapped_column(
        ForeignKey("order_products.id"), nullable=True, index=True
    )
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"), nullable=True)
    source: Mapped[LedgerSource] = mapped_column(Enum(LedgerSource), index=True)
    note: Mapped[str] = mapped_column(Text, default="")
    # 商品成本快照（毛利率/利润用）；红冲行 cost_price_snapshot 为负数（COGS 冲减）
    cost_price_snapshot: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=Decimal("0"))
    # 客户档案（customers.id）；NULL=历史行（按名称兜底聚合）
    customer_id: Mapped[int | None] = mapped_column(nullable=True, index=True)

    shipper: Mapped["User | None"] = relationship(back_populates="ledgers")
    order: Mapped["Order | None"] = relationship()
    order_product: Mapped["OrderProduct | None"] = relationship()
    product: Mapped["Product | None"] = relationship()
