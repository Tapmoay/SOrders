from typing import TYPE_CHECKING

from decimal import Decimal

from sqlalchemy import Boolean, Enum, Numeric, String
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
    # 司机画像（仅司机有意义）：small小车/large大车/trailer挂车
    vehicle_type: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    # 计费方式：salary固定工资/piece按单计费（挂车默认按单，可独立设置）
    billing_mode: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # 固定工资司机月薪（仅派单员可见；司机端接口一律隐藏）
    salary: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    # 会员标记：货主中的高级货主（仅对货主有意义）
    is_member: Mapped[bool] = mapped_column(Boolean, default=False)

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


def resolve_billing_mode(vehicle_type: str | None, billing_mode: str | None) -> str:
    """计费方式解析：显式值优先；挂车默认按单计费，其余默认固定工资。"""
    if billing_mode:
        return billing_mode
    return "PIECE" if vehicle_type == "trailer" else "SALARY"
