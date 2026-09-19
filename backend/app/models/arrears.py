"""挂账单位：赊账客户（临时货主/单位），订单可选择挂账到该单位。"""

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, SoftDeleteMixin, TimestampMixin


class ArrearsUnit(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "arrears_units"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    phone: Mapped[str] = mapped_column(String(32), default="")
    remark: Mapped[str] = mapped_column(String(256), default="")
