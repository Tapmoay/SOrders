from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.user import User


class ShipperAddress(Base, TimestampMixin):
    """货主常用地址"""

    __tablename__ = "shipper_addresses"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    shipper_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    receiver_name: Mapped[str] = mapped_column(String(128), default="")
    phone: Mapped[str] = mapped_column(String(32), default="")
    detail_address: Mapped[str] = mapped_column(String(512), default="")
    remark: Mapped[str] = mapped_column(String(256), default="")
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    address_lat: Mapped[Decimal | None] = mapped_column(Numeric(10, 7), nullable=True)
    address_lng: Mapped[Decimal | None] = mapped_column(Numeric(10, 7), nullable=True)

    shipper: Mapped["User"] = relationship(back_populates="addresses")


class ShipperContact(Base, TimestampMixin):
    """货主联系人库（如老板电话，首次输入后保存）"""

    __tablename__ = "shipper_contacts"
    __table_args__ = (UniqueConstraint("shipper_id", "phone", name="uq_shipper_contact_phone"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    shipper_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    phone: Mapped[str] = mapped_column(String(32), index=True)
    display_name: Mapped[str] = mapped_column(String(128), default="")

    shipper: Mapped["User"] = relationship(back_populates="contacts")
