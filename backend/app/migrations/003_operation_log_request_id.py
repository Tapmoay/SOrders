"""003_operation_log_request_id：给 operation_logs 加 request_id（整改报告 §15 ① 的**最后一跳**）。

### 为什么加它
报告 §15 ① 画的链条是：

    HTTP → request_id → service → DB/log → operation_log

前四跳早就通了：中间件发/收 X-Request-ID（core/request_id.py）、ContextVar 让业务代码拿得到、
日志 filter 给**每一条**日志带上 rid=、访问日志一行一条。**只有最后一跳是断的** ——
审计表里没有这一列。后果很具体：用户报障说「10:31 那笔账不对」，你拿得到那条 HTTP 日志行，
却接不到 operation_logs 里对应的那一行，而**审计表才是「谁改了什么」的权威记录**。

### 两条设计选择
1. **列宽 64 与 core/request_id.MAX_ID_LEN 对齐**（客户端给的 id 只截断、不校验格式）；
2. **加索引**：这一列存在的唯一理由就是「拿一个 id 去查」，没索引等于白加。

### 为什么走迁移而不是 schema_bootstrap
migrations/README.md 的分工：**正式变更**走本目录、**运行时自愈**走 bootstrap。
加一列是正式变更（老库要 ALTER、新库已经有了），所以是一条迁移，不是往 bootstrap 里再塞一段 DDL。
"""

from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

VERSION = 3
NAME = "operation_log_request_id"
DESCRIPTION = "operation_logs 加 request_id：把一次 HTTP 请求与它写下的审计行接起来（报告 §15 ①）"

#: 与 core/request_id.MAX_ID_LEN 对齐（那边是「客户端给的 id 只截断不校验」）。
COLUMN_LEN = 64
INDEX_NAME = "ix_operation_logs_request_id"


def upgrade(engine: Engine) -> None:
    insp = inspect(engine)
    if "operation_logs" not in insp.get_table_names():
        # 全新库由 create_all 按模型建表（模型里已经有这一列），这里没什么可做的。
        return
    cols = {c["name"] for c in insp.get_columns("operation_logs")}
    if "request_id" not in cols:
        with engine.begin() as conn:
            # ⛔ 必须能重跑（README 硬要求：MySQL 的 DDL 隐式提交，一条迁移可能改了一半才失败）。
            conn.execute(text(f"ALTER TABLE operation_logs ADD COLUMN request_id VARCHAR({COLUMN_LEN}) NULL"))
    # 索引单独判：ALTER 成功、建索引失败时，重跑要把缺的那一步补上（而不是因为「列已在」整条跳过）。
    idx = {i["name"] for i in inspect(engine).get_indexes("operation_logs")}
    if INDEX_NAME not in idx:
        with engine.begin() as conn:
            conn.execute(text(f"CREATE INDEX {INDEX_NAME} ON operation_logs (request_id)"))
