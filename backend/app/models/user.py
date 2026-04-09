from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Enum, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.enums import UserRole

if TYPE_CHECKING:
    from app.models.ledger import Ledger
    from app.models.notification import Notification
    from app.models.operation_log import OperationLog
    from app.models.order import Order
    from app.models.shipper import ShipperAddress, ShipperContact


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    phone: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(128), default="")
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    orders_as_shipper: Mapped[list["Order"]] = relationship(
        back_populates="shipper", foreign_keys="Order.shipper_id"
    )
    orders_as_driver: Mapped[list["Order"]] = relationship(
        back_populates="driver", foreign_keys="Order.driver_id"
    )
    ledgers: Mapped[list["Ledger"]] = relationship(back_populates="shipper")
    notifications: Mapped[list["Notification"]] = relationship(back_populates="recipient")
    operation_logs: Mapped[list["OperationLog"]] = relationship(back_populates="operator")
    addresses: Mapped[list["ShipperAddress"]] = relationship(back_populates="shipper")
    contacts: Mapped[list["ShipperContact"]] = relationship(back_populates="shipper")
