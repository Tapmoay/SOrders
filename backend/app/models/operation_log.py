from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.business_time import utc_now_naive
from app.models.base import Base

if TYPE_CHECKING:
    from app.models.order import Order
    from app.models.user import User


class OperationLog(Base):
    __tablename__ = "operation_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    operator_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(64), index=True)
    change_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 与 `TimestampMixin` 同一口径：**Python 写 UTC**（审计页的日期、3 年保留期都拿它比）。
    # 原来是 `server_default=func.now()`（库端时钟）→ 生产 +08:00，与本项目"库里存 UTC"
    # 的口径差 8 小时（2026-09-19 外部完整检查 C-2）。`server_default` 只留作原生 SQL 的兜底，
    # 而 `database.py` 已把 MySQL 会话时区钉成 UTC，所以那条路径也是 UTC。
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now_naive, server_default=func.now()
    )

    operator: Mapped["User"] = relationship(back_populates="operation_logs")
    order: Mapped["Order | None"] = relationship(back_populates="operation_logs")
