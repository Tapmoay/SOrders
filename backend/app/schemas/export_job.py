from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.export_job import ExportFormat, ExportJobStatus


class LedgerExportJobCreate(BaseModel):
    shipper_id: int
    date_from: date
    date_to: date
    export_format: ExportFormat = Field(default=ExportFormat.EXCEL, description="excel 或 pdf")


class LedgerExportJobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: int
    created_by_id: int
    shipper_id: int
    file_format: ExportFormat
    date_from: date
    date_to: date
    status: ExportJobStatus
    file_path: str | None
    error_message: str | None
    completed_at: datetime | None
    created_at: datetime
