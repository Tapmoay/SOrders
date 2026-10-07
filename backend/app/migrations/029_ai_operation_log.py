"""029_ai_operation_log：建一张「AI 操作流水」表（CHG-0082 / 台账 L-52）。

### 为什么需要一张新表

用户 2026-10-08 要的是「每次 AI 动作都落一行（谁、何时、什么动作、**成没成、失败原因**）」。
`operation_logs` 答不上来：它只在**业务写入成功之后**才有一行（还要真的改了数据），
AI 被 403/422 挡回来的那些请求在库里一行都没有。理由全文见
`app/models/ai_operation_log.py` 开头那段（⛔ 别在这里抄第二份，两份必然有一天不一致）。

### 为什么走迁移而不是 schema_bootstrap

与 `005_ai_call_daily` / `019_purchase_orders` / `020_invoices` / `027_shipper_prices` 同一条：
建表是**正式变更**（老库要建表、新库由 `create_all` 按模型建）。
⛔ `core/schema_bootstrap.py` 里**没有**这张表，本次也不新开
（`_tools/qa/_check_silent_release.py` 第 5 条钉着这条纪律）。

### 为什么用模型建表

`AiOperationLog.__table__.create` 让两种方言（本机 SQLite / 生产 MySQL）落到**同一个形状**上
（三个索引 `user_id` / `ok` / `created_at` 与 `action` / `request_id` 都跟着模型走），
不会出现「迁移建的表少一条索引」这种只在生产才发作的偏差 —— 同 `024` / `027` 的 `table.create` 手法。
"""

from __future__ import annotations

from sqlalchemy import inspect
from sqlalchemy.engine import Engine

VERSION = 29
NAME = "ai_operation_log"
DESCRIPTION = (
    "ai_operation_logs：AI 每一次动作一行（谁 / 何时 / 哪个动作 / 哪条接口 / 成没成 / 失败原因）。"
    "请求级、含 4xx-5xx；与 operation_logs 用 request_id 对得上，两者不互相替代"
)

TABLE = "ai_operation_logs"


def upgrade(engine: Engine) -> None:
    """建这张表；已经在了就什么都不做（⛔ 必须能重跑）。"""
    if TABLE in set(inspect(engine).get_table_names()):
        return
    from app.models.ai_operation_log import AiOperationLog

    AiOperationLog.__table__.create(bind=engine, checkfirst=True)
