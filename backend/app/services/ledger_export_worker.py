"""异步执行账本导出任务并写入消息中心。"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from starlette.concurrency import run_in_threadpool

from app.database import SessionLocal
from app.models import LedgerExportJob, Notification
from app.models.export_job import ExportFormat, ExportJobStatus
from app.schemas.notification import NotificationOut
from app.services.ledger_export import run_ledger_export_file
from app.services.ledger_export_paths import download_url
from app.services.message_center import emit_unread_count
from app.services.message_push import emit_to_user
from app.services.push_events import push_ledger_updated

logger = logging.getLogger(__name__)


def run_ledger_export_job_sync(job_id: int) -> dict[str, Any] | None:
    """**同步**部分：生成产物文件 + 落库「导出完成」通知，返回推送所需的纯数据。

    ⛔ 这个函数只允许在**线程**里跑（Starlette 用 `run_in_threadpool` 跑同步后台任务），
       所以它**绝不碰事件循环**：既不 `asyncio.run`，也不 await 任何东西。

    为什么单列出来（2026-09-19 审计，R14-7 高危）：原来整个任务是一个同步函数，
    它在**后台线程**里直接 `asyncio.run(emit_notification(n))` —— 那是新建一个事件循环，
    而 socket.io 的 Redis 连接是在**主事件循环**里建的。跨事件循环复用同一条连接必然抛
    `RuntimeError: ... attached to a different loop`，于是：
      ① 产物文件与「导出完成」通知**都已经 commit 了**；
      ② 紧接着的推送抛异常 → `except` 把任务翻成 `FAILED`。
    用户收到"导出完成"却在任务页看到失败；重试只会在 `exports/` 里堆随机名的孤儿文件。
    生产配了 Redis（`SOCKET_REDIS_URL`）→ 每一次导出都会这样，等于功能不可用。

    推送因此被拆到 `run_ledger_export_job_task`（async，主循环里 await）。
    """
    db = SessionLocal()
    try:
        job = db.get(LedgerExportJob, job_id)
        if job is None:
            return None
        job.status = ExportJobStatus.PROCESSING
        db.commit()
        fmt = "excel" if job.file_format == ExportFormat.EXCEL else "pdf"
        # ⚠️ 这里存的是**产物文件名**（不是 URL）：`file_path` 这个名字就该是"文件在哪"，
        #    而给用户/前端的下载地址由 `download_url(job.id)` 现算（2026-09-19 审计，R12-A1：
        #    原来把 URL 存进 file_path，下载端点却去读一个不存在的 `job.download_url` → 必然 500）。
        name = run_ledger_export_file(db, job.shipper_id, job.date_from, job.date_to, fmt, job.id)
        shipper_id = job.shipper_id
        job.status = ExportJobStatus.DONE
        job.file_path = name
        job.completed_at = datetime.now(timezone.utc)
        # ⚠️ **先**把"任务成功"落库再去做通知（2026-09-19 审计）：文件已经生成、任务事实上
        #    已经成功；通知只是"告诉用户一声"。若把两者塞进同一个 try，通知那一步的任何
        #    异常都会把一条成功的导出改成 FAILED —— 用户看到失败，文件却已经能下载。
        db.commit()
    except Exception as e:  # noqa: BLE001
        db.rollback()
        job = db.get(LedgerExportJob, job_id)
        if job:
            job.status = ExportJobStatus.FAILED
            job.error_message = str(e)[:2000]
            job.completed_at = datetime.now(timezone.utc)
            db.commit()
        return None

    # 到这里任务已成功。下面只做「发一条通知」，它失败不许回头改任务状态。
    try:
        n = Notification(
            recipient_id=job.created_by_id,
            category="reminder",
            type="ledger_export",
            title="账本导出完成",
            content="您在消息中心可查看下载链接（payload）。",
            speech_important=False,
            payload={
                "export_job_id": job.id,
                "download_url": download_url(job.id),
                "shipper_id": shipper_id,
                "format": fmt,
            },
        )
        db.add(n)
        db.commit()
        db.refresh(n)
        # 在这里就序列化成纯 JSON：线程结束时会话就关了，ORM 对象到了主循环里是 detached，
        # 再 `model_validate(n)` 只会 DetachedInstanceError。
        return {
            "job_id": job.id,
            "recipient_id": n.recipient_id,
            "notification": NotificationOut.model_validate(n).model_dump(mode="json"),
            "shipper_id": shipper_id,
        }
    except Exception:  # noqa: BLE001
        db.rollback()
        logger.warning("账本导出完成，但写「导出完成」通知失败：job_id=%s", job_id, exc_info=True)
        return None
    finally:
        db.close()


async def run_ledger_export_job_task(job_id: int) -> None:
    """后台任务入口：重活丢线程，推送回**主事件循环** await。

    必须是 `async def` —— Starlette 的 `BackgroundTasks` 对同步函数走线程池、
    对协程函数直接在事件循环里 await，只有后者能安全地使用主循环里建的 socket/redis 连接。
    """
    info = await run_in_threadpool(run_ledger_export_job_sync, job_id)
    if info is None:
        return
    # 推送失败只记日志：产物与通知都已经落库，用户刷新消息中心就能拿到下载链接。
    try:
        await emit_to_user(
            info["recipient_id"], "notification", {"notification": info["notification"]}
        )
        await emit_unread_count(info["recipient_id"])
        await push_ledger_updated(info["shipper_id"])
    except Exception:  # noqa: BLE001
        logger.warning("账本导出完成的 socket 推送失败（不影响下载）：job_id=%s", job_id, exc_info=True)
