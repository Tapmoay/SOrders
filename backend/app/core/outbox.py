"""事务发件箱（Outbox）—— 整改报告 §10「建立真正可靠的事件边界」。

## 报告点名的病

```text
数据库成功 → 后台任务恰好挂了 → 事件永远丢失
```

现在的形状是「业务操作 → 数据库 → background task → Socket.IO」，而 background task 是**尽力而为**的：
进程重启、任务抛异常、worker 被回收，那条推送就没了 —— 数据库里一切正常，所以**没人会发现**。

## 报告给的形状（本模块照着做）

```text
事务
 ├─ 修改订单
 └─ 写 outbox_events
        ↓
     worker
        ↓
   推送 / 通知 / 统计
```

⛔ 不急着上 Kafka；仍然是 MySQL + FastAPI + Redis。

## 四条口径

1. **入队与业务写同一个事务**：`enqueue()` **不 commit** —— 业务回滚了，事件也不该存在。
   这是整个模式的要点（"发出去了但库里没有"和"库里改了但没发"都是错的）；
2. **至少一次**：派发成功才标 `sent`；失败记 `last_error` + `attempts` 并按退避重试，用满次数就放弃（`failed`）；
   `dedupe_key` 唯一索引保证「同一次业务动作重复入队只会有一条」；**重复派发**由消费方自己幂等
   （App 侧已有「按 order_id 去重」那条）；
3. **处理器是注入的**（`deliver(event)`）：这一层不认识 socketio / 消息中心 —— 否则核心模块会把整条推送链路
   拖进来，单测也没法在不连 Redis 的情况下跑；处理器没登记就**抛错**（静默丢事件正是要治的病）；
4. **取数与标记只有一份**（`claim` / `mark_sent` / `mark_failed`）：同步版（`dispatch_sync`，单测与人工补发用）
   与生产版（`run_forever`）共用它们 —— 退避与放弃的语义因此只有一处。
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.business_time import utc_now_naive
from app.models.outbox import OutboxEvent, OutboxStatus

logger = logging.getLogger(__name__)

#: 同一条事件最多尝试几次（之后放弃并留 last_error 给人看）。
MAX_ATTEMPTS = 5
#: 一次取多少条。
BATCH = 50
#: 退避：5s、10s、20s、40s…（封顶 10 分钟）。
BASE_BACKOFF_SECONDS = 5
MAX_BACKOFF_SECONDS = 600
#: 生产循环的间隔（秒）。
POLL_INTERVAL = 2.0


@dataclass(frozen=True)
class Event:
    """交给处理器的形状（处理器不认识 ORM）。"""

    id: int
    event_type: str
    payload: dict
    attempts: int


def enqueue(
    db: Session,
    event_type: str,
    payload: dict | None = None,
    *,
    dedupe_key: str | None = None,
) -> bool:
    """写一条待发事件。⛔ **不 commit** —— 调用方与业务写在同一个事务里（见模块说明第 1 条）。

    返回 False 表示去重键命中已有事件（这次没有新写；调用方不必当失败处理）。
    """
    if dedupe_key:
        # ⚠️ 先 flush：本项目的 sessionmaker 是 **autoflush=False**（`app/database.py` 与本仓库的收尾规矩），
        #    不 flush 的话**同一次事务里刚入队那一条查不到** → 同一个键会写进去两行，
        #    而唯一索引要到提交前才炸（`IntegrityError` 把整个业务事务带下去）。
        #    这条是本模块的第一批用例当场抓出来的（`test_dedupe_key_writes_once`）。
        db.flush()
        exists = db.scalar(select(OutboxEvent.id).where(OutboxEvent.dedupe_key == dedupe_key).limit(1))
        if exists is not None:
            return False
    db.add(
        OutboxEvent(
            event_type=event_type,
            payload=json.dumps(payload or {}, ensure_ascii=False, default=str),
            dedupe_key=dedupe_key,
            status=OutboxStatus.PENDING.value,
            attempts=0,
            next_attempt_at=utc_now_naive(),
        )
    )
    return True


def backoff_seconds(attempts: int) -> int:
    """第 n 次失败之后等多久（指数退避，封顶）。"""
    return min(MAX_BACKOFF_SECONDS, BASE_BACKOFF_SECONDS * (2 ** max(0, attempts - 1)))


def claim(db: Session, *, limit: int = BATCH) -> list[OutboxEvent]:
    """取一批到点的待发事件（按 id 先入先发）。"""
    rows = db.scalars(
        select(OutboxEvent)
        .where(
            OutboxEvent.status == OutboxStatus.PENDING.value,
            OutboxEvent.next_attempt_at <= utc_now_naive(),
        )
        .order_by(OutboxEvent.id)
        .limit(limit)
    )
    return list(rows)


def mark_sent(db: Session, row: OutboxEvent) -> None:
    row.status = OutboxStatus.SENT.value
    row.sent_at = utc_now_naive()
    row.last_error = None


def mark_failed(db: Session, row: OutboxEvent, error: str) -> bool:
    """记一次失败。返回是否已经放弃（尝试次数用满）。

    ⚠️ `attempts` 用**数据库自增**（`attempts = attempts + 1`），不是"读出来 +1 再写回"：
    后者在并发下必然丢更新（本项目红线 `_check_counter_updates.py` 盯着这种写法，
    顺手就把这一版抓了出来）—— 而"尝试次数少算一次"的后果是**该放弃的没放弃**，一直重试。
    """
    db.execute(
        update(OutboxEvent)
        .where(OutboxEvent.id == row.id)
        .values(attempts=OutboxEvent.attempts + 1, last_error=(error or "")[:500])
    )
    db.refresh(row)
    if int(row.attempts or 0) >= MAX_ATTEMPTS:
        row.status = OutboxStatus.FAILED.value
        return True
    row.next_attempt_at = utc_now_naive() + timedelta(seconds=backoff_seconds(row.attempts))
    return False


def to_event(row: OutboxEvent) -> Event:
    return Event(
        id=int(row.id),
        event_type=row.event_type,
        payload=row.payload_dict(),
        attempts=int(row.attempts or 0),
    )


def dispatch_sync(db: Session, deliver: Callable[[Event], None], *, limit: int = BATCH) -> dict[str, int]:
    """同步派发一批（单测与"人工补发"用；生产走 `run_forever`）。"""
    out = {"sent": 0, "retry": 0, "given_up": 0}
    for row in claim(db, limit=limit):
        try:
            deliver(to_event(row))
        except Exception as exc:  # noqa: BLE001 —— 任何异常都要留痕并退避，不许把事件吞掉
            gave_up = mark_failed(db, row, type(exc).__name__ + ": " + str(exc))
            out["given_up" if gave_up else "retry"] += 1
            logger.warning("发件箱派发失败 id=%s type=%s attempts=%s: %s", row.id, row.event_type, row.attempts, exc)
            continue
        mark_sent(db, row)
        out["sent"] += 1
    db.commit()
    return out


def outbox_stats(db: Session) -> dict[str, int]:
    """待发 / 已发 / 放弃 各多少（`/metrics` 与排障用）。"""
    rows = db.execute(
        select(OutboxEvent.status, func.count()).group_by(OutboxEvent.status)
    ).all()
    out = {s.value: 0 for s in OutboxStatus}
    for status, n in rows:
        out[str(status)] = int(n)
    return out
async def run_forever(
    deliver: Callable[[Event], Awaitable[None]],
    *,
    session_factory: Callable[[], Session] | None = None,
    interval: float = POLL_INTERVAL,
) -> None:
    """生产循环：取一批 → 逐个 `await deliver(event)` → 标 sent / 记失败。

    ⚠️ 处理器**在应用自己的事件循环里 await**（与现有推送同源）—— 现有推送函数是 async 的，
    而 socketio 的 emit 要在这个进程的循环里跑；把处理器丢进别的线程/循环是"看起来能跑、偶发丢事件"的路。
    只有 DB 那三步（取数 / 标成功 / 记失败）丢进线程，不让同步查询卡住事件循环。
    """
    while True:
        try:
            events = await asyncio.to_thread(_claim_sync, session_factory)
            for ev in events:
                try:
                    await deliver(ev)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001 —— 任何异常都要留痕并退避，不许把事件吞掉
                    detail = type(exc).__name__ + ": " + str(exc)
                    gave_up = await asyncio.to_thread(_fail_sync, session_factory, ev.id, detail)
                    logger.warning(
                        "发件箱派发失败 id=%s type=%s%s: %s",
                        ev.id, ev.event_type, "（已放弃）" if gave_up else "（稍后重试）", exc,
                    )
                else:
                    await asyncio.to_thread(_sent_sync, session_factory, ev.id)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 —— 一轮出错不该让整个循环退出（下一轮继续）
            logger.exception("发件箱循环出错（下一轮继续）")
        await asyncio.sleep(interval)


def _factory(session_factory: Callable[[], Session] | None) -> Callable[[], Session]:
    if session_factory is not None:
        return session_factory
    from app.database import SessionLocal  # 延迟导入：别让核心模块在导入期依赖整个应用装配

    return SessionLocal


def _claim_sync(session_factory: Callable[[], Session] | None) -> list[Event]:
    """取一批到点的事件（返回纯数据，不带 ORM 对象 —— 它们要跨线程/跨事务用）。"""
    db = _factory(session_factory)()
    try:
        return [to_event(row) for row in claim(db)]
    finally:
        db.close()


def _sent_sync(session_factory: Callable[[], Session] | None, event_id: int) -> None:
    db = _factory(session_factory)()
    try:
        row = db.get(OutboxEvent, event_id)
        if row is None:
            return
        mark_sent(db, row)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _fail_sync(session_factory: Callable[[], Session] | None, event_id: int, detail: str) -> bool:
    """记一次失败；返回是否已经放弃。"""
    db = _factory(session_factory)()
    try:
        row = db.get(OutboxEvent, event_id)
        if row is None:
            return False
        gave_up = mark_failed(db, row, detail)
        db.commit()
        return gave_up
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
