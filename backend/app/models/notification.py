from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.user import User


class Notification(Base, TimestampMixin):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    recipient_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    category: Mapped[str] = mapped_column(
        String(32),
        index=True,
        default="order",
        doc="system | order | reminder",
    )
    type: Mapped[str] = mapped_column(String(64), index=True, default="system")
    speech_important: Mapped[bool] = mapped_column(default=False, doc="前端语音播报")
    title: Mapped[str] = mapped_column(String(256), default="")
    content: Mapped[str] = mapped_column(Text, default="")
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: **幂等键**（第二轮 R2-04）：同一条业务事实重复投递时，同一收件人只留一条。
    #: 形如 `order.assigned:12:7#5`（事实 + 收件人，`create_message` 内部拼）。
    #: None = 不做幂等（直接调用创建的消息，行为与以前一字不差）。
    #: ⚠️ 唯一性由**数据库**保证（下面那条索引），不是「先查再插」—— 后者挡不住两个 worker 同时投。
    idem_key: Mapped[str | None] = mapped_column(String(160), nullable=True)

    recipient: Mapped["User"] = relationship(back_populates="notifications")

    __table_args__ = (Index("uq_notifications_idem_key", "idem_key", unique=True),)
