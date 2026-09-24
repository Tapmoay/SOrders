"""异步执行账本导出任务并写入消息中心。"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import IO

from sqlalchemy import update
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.core import outbox
from app.core.business_time import utc_now_naive
from app.database import SessionLocal
from app.models import LedgerExportJob, Notification
from app.models.export_job import ExportFormat, ExportJobStatus
from app.services.ledger_export import run_ledger_export_file
from app.services.ledger_export_paths import download_url

logger = logging.getLogger(__name__)

#: 一个导出任务超过多少分钟还没进终态，就认为它**卡死了**（进程重启/被杀）。
#: 账本导出是"几十秒级"的活儿（本机实测最长几十秒），15 分钟足够宽 ——
#: 取值偏大只是让"卡住"这种异常状态多显示一会儿，不会误杀正在跑的任务。
STALE_AFTER_MINUTES = 15

#: 每个账号同时在跑的导出任务上限（靠 OS 文件锁实现，见 `acquire_export_slot`）。
EXPORT_SLOT_PATH = "/tmp/sorders_export_{user_id}.lock"


def acquire_export_slot(user_id: int) -> IO[str] | None:
    """占住"这个账号的导出槽位"；占不到（已经有一个在跑）返回 None。

    ⚠️ 为什么需要它（2026-09-19 外部完整检查 C-5）：导出是 fire-and-forget 的后台任务，
    任何货主都能连点几次把自己的导出排满 —— 实测能把**最廉价端点从 1ms 拖到 29.77 秒**
    （单任务 39.77s / 85,119 条 SQL / 峰值 RSS 469MB），因为重活跑在同一个进程的线程池里。

    ⚠️ 为什么用**文件锁**而不是"查库里的 PENDING/PROCESSING 行"：
    1. 查库要配一条"多久算卡死"的时间判据，而 `created_at` 是库端时钟（生产 +08:00）、
       Python 是 UTC —— 那条判据会**静默**偏 8 小时（本机 SQLite 测不出来，见 C-2）；
       偏严 = 上一次导出崩了以后好几小时不能导出，偏松 = 根本拦不住。
    2. **进程死了锁自动释放**（操作系统语义），不需要谁来清理"卡在 processing 的任务"。
    3. 多 worker 之间照样互斥（锁在文件系统上，不在进程内存里）。
    Windows 本机开发没有 `fcntl`（也只有一个进程），返回一个空句柄＝不拦。
    """
    try:
        import fcntl
    except ImportError:                    # pragma: no cover - Windows 本机开发
        return _NullSlot()
    handle = open(EXPORT_SLOT_PATH.format(user_id=user_id), "w")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None
    return handle


class _NullSlot:
    """没有 `fcntl` 时的占位句柄（`close()` 之后什么也不用做）。"""

    def close(self) -> None:  # pragma: no cover - 只在 Windows 走到
        return


def release_export_slot(handle: IO[str] | None) -> None:
    """放掉槽位（**必须**在所有路径上都调到，否则这个账号再也导不出东西）。"""
    if handle is None:
        return
    try:
        import fcntl

        fcntl.flock(handle, fcntl.LOCK_UN)
    except (ImportError, OSError):          # pragma: no cover - Windows / 句柄已失效
        pass
    finally:
        try:
            handle.close()
        except Exception:                   # noqa: BLE001
            pass


def reap_stale_job(db: Session, job) -> None:
    """把**卡住的**导出任务收敛成 FAILED（2026-09-24 第 32 轮；第 25 轮 08 区缺陷 1）。

    ### 为什么需要它
    `run_ledger_export_job_sync` 先 `status = PROCESSING` + **commit**，然后再干活：
    进程在两步之间被重启/杀掉（或异常路径绕过了它的 FAILED 分支），这一行就**永远停在
    PROCESSING** —— 全后端**没有任何收割者**（`PROCESSING` 的唯一写入点就是那个 worker）。
    客户端轮询 60 次 × 2 秒之后**静默放弃**：用户看到的是"一直在导出中"，而它永远不会完成。

    ### 判据为什么用**应用时钟**、不用库端时钟
    库端时钟在生产 MySQL 上未必是 UTC（`database.py` 设 `time_zone='+00:00'` 失败时只是
    warning），拿库端 `NOW()` 比会得出"还没超时"的错结论。这里用 `created_at`
    （应用写入的 UTC naive）与 `utc_now_naive()` 比 —— 与全项目其它超时判据同源。

    ### 为什么是"读时收敛"而不是后台定时任务
    这个模块**刻意不用**后台清理线程（见文件头：进程死了文件锁自动释放，不需要谁去清"卡住的任务"）；
    而"读的时候顺手把过期的收敛掉"不需要任何额外线程、也不会被多 worker 并发重复执行出问题
    （条件 UPDATE + rowcount，只有一个请求改得到）。
    """
    now = utc_now_naive()
    cutoff = now - timedelta(minutes=STALE_AFTER_MINUTES)
    created = getattr(job, "created_at", None)
    if created is None or created > cutoff:
        return
    changed = db.execute(
        update(LedgerExportJob)
        .where(
            LedgerExportJob.id == job.id,
            # 只动**非终态**的：DONE 永远不该被收敛，FAILED 不用再动
            LedgerExportJob.status.in_(
                [ExportJobStatus.PENDING.value, ExportJobStatus.PROCESSING.value]
            ),
        )
        .values(
            status=ExportJobStatus.FAILED.value,
            error_message=(
                f"导出任务超过 {STALE_AFTER_MINUTES} 分钟仍未完成（服务可能重启过），"
                "已自动标记为失败，请重新发起导出。"
            ),
            completed_at=now,
        )
    )
    if changed.rowcount:
        db.commit()
        db.refresh(job)


def run_ledger_export_job_sync(job_id: int) -> None:
    """**同步**部分：生成产物文件 + 落库「导出完成」通知 + 把要推的事件写进事务发件箱。

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

    ⚠️ **2026-09-25（整改报告 §10）**：这一层现在**不再直接推**了 —— 事件随通知一起写进
    事务发件箱，由 worker 在应用自己的事件循环里派发。「在地板这一侧推」与「在发件箱里推」
    是两件事：前者一旦进程在 commit 与推送之间重启就永远丢了（而库里一切正常、没人发现），
    后者至少一次重试（失败留 `last_error`，`/metrics` 的 `sorders_outbox_failed` 看得见）。
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
        # ⚠️ 先 flush 拿到 `n.id`：事件负载里**只带编号**（处理器按编号重新取当前那一行再推，
        #    塞快照就等于两处状态 —— 改了消息之后推出去的还是旧的，见
        #    `message_center.emit_notification_by_id` 的说明）。
        db.flush()
        # ⛔ 通知与它的事件**同一个事务**（整改报告 §10）：`outbox.enqueue` 自己不 commit，
        #    所以"通知写进去了、事件没写进去"这种半边状态不存在。
        #    2026-09-25 之前这里是**直接推**（`emit_to_user` + `emit_unread_count` +
        #    `push_ledger_updated`），而推送落在通知 commit **之后**：进程在这中间重启/被回收，
        #    用户就永远收不到「导出完成」（消息中心里那条还在，但没人会去翻），
        #    而库里一切正常、没有任何地方报错 —— 正是报告点名的
        #    「数据库成功 → 后台任务恰好挂了 → 事件永远丢失」。
        outbox.enqueue(db, "notifications.created", {"notification_id": n.id})
        # 账本页 / 司机运费页 / 派单员账本那一格都订阅这个信号（三个角色，
        # 见 `push_events.push_ledger_updated` 的说明）—— 导出会改变账本页能看到的东西。
        outbox.enqueue(db, "ledger.updated", {"shipper_id": shipper_id})
        db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()
        logger.warning("账本导出完成，但写「导出完成」通知失败：job_id=%s", job_id, exc_info=True)
    finally:
        db.close()


async def run_ledger_export_job_task(job_id: int) -> None:
    """后台任务入口：只把重活丢进线程，不做任何推送。

    必须是 `async def` —— Starlette 的 `BackgroundTasks` 对同步函数走线程池、
    对协程函数直接在事件循环里 await；这个纪律由 `_check_background_tasks.py` 钉着，
    **与本层推不推送无关**（推送已经搬进事务发件箱，由 worker 在应用自己的事件循环里派发）。
    """
    await run_in_threadpool(run_ledger_export_job_sync, job_id)


async def run_ledger_export_job_with_slot(job_id: int, slot: IO[str] | None) -> None:
    """带槽位的后台任务：跑完（或失败、或被取消）**一定**放锁。

    为什么不在 `create_export_job` 里放：任务在响应发出**之后**才跑，
    中间隔着整个导出过程（几十秒）。放锁必须发生在真正结束的那一刻。
    """
    try:
        await run_ledger_export_job_task(job_id)
    finally:
        release_export_slot(slot)
