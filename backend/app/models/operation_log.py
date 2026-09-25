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
    #: 整改报告 §15 ① 的**最后一跳**：产生这一行的那次 HTTP 请求的 id（`core/request_id.py`）。
    #: 由 `services/operation_log_service.write_log` 一处填 —— 不在请求上下文里（后台任务、
    #: 脚本、保留期治理）时是 NULL，那正是「不是某个人点出来的」这个事实。
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    #: 整改报告 §15 ②：**这一行是谁发起的** —— `human`（默认）/ `ai`（用户在 AI 确认卡上点过）。
    #: 由 `services/operation_log_service.write_log` 一处填（`core/client_origin.py` 的上下文变量）。
    #: ⛔ 它不是「AI 能不能写」的闸门（那道闸门在 App 的确认卡上，模型永远只能"申请"）——
    #:    它只回答一个问题：`sorders_ai_write_confirmed_today` 这个数从哪儿来。
    origin: Mapped[str] = mapped_column(
        String(16), nullable=False, default="human", server_default="human", index=True
    )
    # 与 `TimestampMixin` 同一口径：**Python 写 UTC**（审计页的日期、3 年保留期都拿它比）。
    # 原来是 `server_default=func.now()`（库端时钟）→ 生产 +08:00，与本项目"库里存 UTC"
    # 的口径差 8 小时（2026-09-19 外部完整检查 C-2）。`server_default` 只留作原生 SQL 的兜底，
    # 而 `database.py` 已把 MySQL 会话时区钉成 UTC，所以那条路径也是 UTC。
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now_naive, server_default=func.now()
    )

    operator: Mapped["User"] = relationship(back_populates="operation_logs")
    order: Mapped["Order | None"] = relationship(back_populates="operation_logs")
