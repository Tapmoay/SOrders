from datetime import date, datetime
from enum import Enum

from sqlalchemy import Date, DateTime, Enum as SAEnum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class ExportFormat(str, Enum):
    EXCEL = "excel"
    PDF = "pdf"


class ExportJobStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    DONE = "done"
    FAILED = "failed"


class LedgerExportJob(Base, TimestampMixin):
    """账本导出异步任务（生成完成后通过消息中心通知下载）。"""

    __tablename__ = "ledger_export_jobs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    shipper_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    file_format: Mapped[ExportFormat] = mapped_column(
        "format",
        SAEnum(ExportFormat),
        default=ExportFormat.EXCEL,
    )
    date_from: Mapped[date] = mapped_column(Date, index=True)
    date_to: Mapped[date] = mapped_column(Date, index=True)
    status: Mapped[ExportJobStatus] = mapped_column(
        SAEnum(ExportJobStatus), default=ExportJobStatus.PENDING, index=True
    )
    file_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # 导出类型：ledger(货主账本，默认) | driver_bills | cash_flows | pnl | ...
    kind: Mapped[str] = mapped_column(String(16), default="ledger")
