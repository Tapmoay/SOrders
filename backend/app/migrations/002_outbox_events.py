"""002_outbox_events：事务发件箱表（整改报告 §10「建立真正可靠的事件边界」）。

### 为什么要这张表
现在的推送是「业务写库成功 → background task → Socket.IO」，而 background task 是尽力而为的：
进程重启 / 任务抛异常 / worker 被回收，那条推送就没了 —— **而数据库里一切正常**，所以没人会发现。
发件箱把「要发什么」先写进**业务那个事务**，再由 worker 去发：

```text
事务
 ├─ 修改订单
 └─ 写 outbox_events   ← 同一个事务（业务回滚，事件也不存在）
        ↓
     worker（重试 + 退避）
        ↓
   推送 / 通知 / 统计
```

### 两条设计选择
1. **表结构直接取自模型**（`OutboxEvent.__table__.create`）：模型与迁移**不可能写成两样**，
   而「两边不一致」正是这类表最贵的缺陷（列名差一个字 → 上线当天才发现）；
2. `checkfirst=True` → 可以重跑（README 的硬要求：MySQL 的 DDL 隐式提交，一条迁移可能改了一半就失败）。
   本地 SQLite 与单测里 `create_all` 已经建过这张表，这里也必然跳过。

### 生产者改造是**下一步**（本轮只立边界与 worker）
切生产者的顺序：一次一条链路，每切一条都要跑该域的红线（`_check_notify_guardrails.py` 117 项等）。
换而言之：这张表先建好、worker 先跑起来，**不改变任何现有推送行为**。
"""

from __future__ import annotations

from sqlalchemy.engine import Engine

VERSION = 2
NAME = "outbox_events"
DESCRIPTION = "新增 outbox_events（事务发件箱）：业务事务里写事件，worker 负责派发与重试"


def upgrade(engine: Engine) -> None:
    from app.models.outbox import OutboxEvent

    OutboxEvent.__table__.create(bind=engine, checkfirst=True)
