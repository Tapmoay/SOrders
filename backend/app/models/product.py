from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.order import OrderProduct
    from app.models.user import User


class Product(Base, TimestampMixin):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(256), index=True)
    name_color: Mapped[str | None] = mapped_column(String(32), nullable=True, default=None)
    default_unit_price: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=Decimal("0"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    image_url: Mapped[str | None] = mapped_column(String(512), nullable=True, default=None)

    price_rules: Mapped[list["PriceRule"]] = relationship(back_populates="product")
    order_products: Mapped[list["OrderProduct"]] = relationship(back_populates="product")


class PriceRule(Base, TimestampMixin):
    """货主特殊定价：货主 + 商品 + 特殊单价。"""

    __tablename__ = "price_rules"
    __table_args__ = (UniqueConstraint("shipper_id", "product_id", name="uq_price_rule_shipper_product"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    shipper_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    special_unit_price: Mapped[Decimal] = mapped_column(Numeric(14, 4))

    shipper: Mapped["User"] = relationship(foreign_keys=[shipper_id])
    product: Mapped["Product"] = relationship(back_populates="price_rules")
