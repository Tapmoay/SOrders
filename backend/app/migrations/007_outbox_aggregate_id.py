"""007_outbox_aggregate_id：发件箱事件的**聚合根编号**（第二轮 R2-04）。

### 为什么需要它
指南 §七 把事件的字段列全了：event_id / event_type / aggregate_id / created_at / payload / status / retry_count。

逐项对照现状（2026-09-25 实测）：id（= event_id）✅、event_type ✅、created_at ✅（TimestampMixin）、
payload ✅、status ✅、attempts（= retry_count）✅ —— **只差 aggregate_id**。

它解决的是**排障**问题：「这一单到底发了哪些事件、哪条没发出去」现在只能去 payload 那个
JSON 字符串里找键名，而键名每条事件都不一样（order_id / request_id / notification_id …）。
有了这一列，按聚合根编号一查就能把一条链路上的事件全捞出来。

### 怎么填：不从 39 个入队点各写一遍
⛔ 让每个生产者自己写 aggregate_id 就是第二份「事件类型 → 聚合根」的映射，而且必然有人漏
（漏了不报错、只是查不到）。改成在 core/outbox.py 里按一张**声明的映射表**从 payload 取：
表只有一处，判据钉着「每种事件类型都有聚合根来源」。
"""

from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

VERSION = 7
NAME = "outbox_aggregate_id"
DESCRIPTION = "outbox_events 加 aggregate_id：事件的聚合根编号（按单号/申请号排障）"


def upgrade(engine: Engine) -> None:
    insp = inspect(engine)
    if "outbox_events" not in insp.get_table_names():
        return                                   # 必须能重跑（README 硬要求）
    if "aggregate_id" not in {c["name"] for c in insp.get_columns("outbox_events")}:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE outbox_events ADD COLUMN aggregate_id VARCHAR(64) NULL"))
            conn.execute(text(
                # 名字与 create_all 的默认名一致（index=True）—— 两处建的是同一张索引，别建两条。
                "CREATE INDEX ix_outbox_events_aggregate_id ON outbox_events (aggregate_id)"
            ))
