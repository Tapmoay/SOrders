"""008_operation_log_command_id：审计行带上**命令 id**（R3-04-A 的中间那一层）。

### 为什么需要它

指南 §R3-04-A 要的是三层追踪：`request_id → command_id → event_id`，并明说**不能混成一个** ——
一次请求可以触发多条命令（批量派单就是），一条命令又可以产生多条事件。

第二轮已经有 `request_id`（迁移 003）。但「这次请求改了几张单」在批量动作下答不了：
审计行只说是**哪次请求**写的，看不出其中第几条命令。这一条迁移补上中间那层。

### 为什么加在 `operation_logs` 上

它是**全库唯一**写审计行的地方（`services/operation_log_service.write_log`），
而 `command_id` 由命令层用 `ContextVar` 提供（`core/command_id.py`）——
和 `request_id` 一样，**一处填、处处有**，业务代码一个字都不用改。

### 可空

老行没有它（那时还没有这个字段），而且**不走命令层的路径**本来就没有 command_id ——
所以是 NULL 而不是空串：排障时「这一行不是命令写的」与「命令 id 是空」是两件事。
"""

from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

VERSION = 8
NAME = 'operation_log_command_id'
DESCRIPTION = 'operation_logs 加 command_id：审计行接上「是哪一条命令」'


def upgrade(engine: Engine) -> None:
    insp = inspect(engine)
    if 'operation_logs' not in insp.get_table_names():
        return                                   # 必须能重跑（README 硬要求）
    if 'command_id' in {c['name'] for c in insp.get_columns('operation_logs')}:
        return
    with engine.begin() as conn:
        conn.execute(text('ALTER TABLE operation_logs ADD COLUMN command_id VARCHAR(64) NULL'))
        # 与 request_id 一样建索引：排障是「给我这个 command_id 的全部审计行」，那是等值查。
        conn.execute(text('CREATE INDEX ix_operation_logs_command_id ON operation_logs (command_id)'))
