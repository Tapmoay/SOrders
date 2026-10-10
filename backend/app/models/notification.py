from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.user import User


#: —— 严重度三档（FEAT-0019）——
#: 用户口径（2026-10-11，逐字）：「文字也要按风险程度着色……按风险程度分红 / 橙 / …」，
#: 而且「**只有未读状态才有这个样式**」（已读整条灰调、连高亮一起去掉）。
#: ⚠️ 这里只是**词汇表**（合法取值 + 列默认值）。「哪个 type 算哪一档」的**判定只有一处**：
#:    `app/services/message_center.py::severity_for()`。⛔ 别在调用点各写一套，也别拿
#:    `speech_important` 顶替它 —— 那是"要不要念出来"，与危险程度是两件事。
SEVERITY_INFO = "info"
SEVERITY_WARN = "warn"
SEVERITY_DANGER = "danger"
SEVERITY_VALUES: tuple[str, ...] = (SEVERITY_INFO, SEVERITY_WARN, SEVERITY_DANGER)


def severity_default(context: Any) -> str:
    """列默认值 = **按 type 现算**，而不是在这里再写一张 type→档 的表。

    为什么要一个"聪明"的默认值：本表有 6 条构造路径**不经过**消息中心的工厂
    （`services/data_retention.py` ×3、`services/ledger_export_worker.py`、
    `api/v1/notifications.py` 的 `POST /price-notify` 与 `POST /notifications`）。
    规则挂在列默认值上，它们即使"忘了写 severity"也拿到**正确的那一档** ——
    否则「只有一个判定来源」就只是句口号，绕过工厂的那几条会安静地掉进 info。

    ⚠️ 为什么是**延迟导入**：`app.services.message_center` 反过来 import 本模块的
    `Notification`，模块级导入会成环；默认值只在 flush 时求值，那时两个模块都已加载完。
    ⚠️ 取不到当前行参数时（多行 INSERT 等）返回 info：默认值**绝不抛** ——
    建一条消息这条路不该因为一个装饰性字段炸掉。
    """
    from app.services.message_center import severity_for  # 延迟导入：见上（避免成环）

    try:
        params = context.get_current_parameters() or {}
    except Exception:  # pragma: no cover - 多行 INSERT 等拿不到当前行的上下文
        return SEVERITY_INFO
    return severity_for(params.get("type"))


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
    #: 严重度（FEAT-0019）：`info` | `warn` | `danger`，默认 `info`。
    #: 客户端据此给**未读**卡的正文上色（danger 红 / warn 橙 / info 不上色）。
    #: 值由 `severity_default` 按 type 现算（→ `message_center.severity_for`），调用点不用管。
    severity: Mapped[str] = mapped_column(
        String(8),
        index=True,
        default=severity_default,
        server_default=text("'info'"),
        doc="严重度：info | warn | danger（FEAT-0019）",
    )
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
