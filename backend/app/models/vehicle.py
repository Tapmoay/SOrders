"""车辆台账：车牌/车型/挂靠司机（货损油费维修按车归属）。"""

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Vehicle(Base, TimestampMixin):
    __tablename__ = "vehicles"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    plate_no: Mapped[str] = mapped_column(String(16), unique=True)
    vehicle_type: Mapped[str] = mapped_column(String(16), default="")
    driver_id: Mapped[int | None] = mapped_column(nullable=True, index=True)
    is_active: Mapped[bool] = mapped_column(default=True)
