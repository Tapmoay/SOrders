"""异步执行账本导出任务并写入消息中心。"""

import asyncio
from datetime import datetime, timezone

from app.database import SessionLocal
from app.models import LedgerExportJob, Notification
from app.models.export_job import ExportFormat, ExportJobStatus
from app.services.ledger_export import run_ledger_export_file
from app.services.message_center import emit_notification
from app.services.push_events import push_ledger_updated


def run_ledger_export_job_task(job_id: int) -> None:
    db = SessionLocal()
    try:
        job = db.get(LedgerExportJob, job_id)
        if job is None:
            return
        job.status = ExportJobStatus.PROCESSING
        db.commit()
        fmt = "excel" if job.file_format == ExportFormat.EXCEL else "pdf"
        url = run_ledger_export_file(db, job.shipper_id, job.date_from, job.date_to, fmt, job.id)
        job.status = ExportJobStatus.DONE
        job.file_path = url
        job.completed_at = datetime.now(timezone.utc)
        n = Notification(
            recipient_id=job.created_by_id,
            category="reminder",
            type="ledger_export",
            title="账本导出完成",
            content="您在消息中心可查看下载链接（payload）。",
            speech_important=False,
            payload={
                "export_job_id": job.id,
                "download_url": url,
                "shipper_id": job.shipper_id,
                "format": fmt,
            },
        )
        db.add(n)
        db.commit()
        db.refresh(n)
        asyncio.run(emit_notification(n))
        asyncio.run(push_ledger_updated(job.shipper_id))
    except Exception as e:  # noqa: BLE001
        db.rollback()
        job = db.get(LedgerExportJob, job_id)
        if job:
            job.status = ExportJobStatus.FAILED
            job.error_message = str(e)[:2000]
            job.completed_at = datetime.now(timezone.utc)
            db.commit()
    finally:
        db.close()
