from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, SoftDeleteMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.user import User


class FreightTemplate(Base, TimestampMixin, SoftDeleteMixin):
    """订单运费模板：路线×车型 ×一车价，派单员维护，派单选价一键带出。"""

    __tablename__ = "freight_templates"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), index=True)
    from_place: Mapped[str] = mapped_column(String(128), default="")
    to_place: Mapped[str] = mapped_column(String(128), default="")
    # small/large/trailer；空=通用（不限车型）
    vehicle_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    fee: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    remark: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    creator: Mapped["User | None"] = relationship(foreign_keys=[created_by])
