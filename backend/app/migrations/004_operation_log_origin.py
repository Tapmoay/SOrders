"""004_operation_log_origin：给 operation_logs 加 origin（整改报告 §15 ② 的 AI 指标）。

### 为什么加它
报告 §15 ② 点名要 `AI_write_confirmed`，而它长期躺在 `core/metrics.py` 的 `NOT_TRACKED` 里，
理由是「后端看不到」：AI 写入走的是**普通业务端点**，与人工写入**完全同形**
（那是当初刻意的设计，见 AI 写操作架构）—— 从审计表里分不出来。

现在 App 在「这张卡是用户确认过的 AI 写入」时带一个请求头（`core/client_origin.py`，白名单只认 ai），
中间件把归一后的值放进上下文变量，`operation_log_service.write_log` 一处落库。

### 两条设计选择
1. **`NOT NULL DEFAULT human`**：老库里的历史数据全部是人工操作（AI 写入在此之前不可区分），
   默认值就是它们的事实，而且这一列从此不需要在查询里判 NULL；
2. **加索引**：这一列存在的唯一理由就是「按 origin 数今天的条数」。

### 为什么走迁移而不是 schema_bootstrap
migrations/README.md 的分工：**正式变更**走本目录、**运行时自愈**走 bootstrap。
加一列是正式变更（老库要 ALTER、新库由 create_all 按模型建），所以是一条迁移。
"""

from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

VERSION = 4
NAME = "operation_log_origin"
DESCRIPTION = "operation_logs 加 origin：把「AI 确认的写入」与人工写入分开（报告 §15 ②）"

#: 与 core/client_origin.MAX_LEN 对齐（只可能装白名单里的短词）。
COLUMN_LEN = 16
INDEX_NAME = "ix_operation_logs_origin"


def upgrade(engine: Engine) -> None:
    insp = inspect(engine)
    if "operation_logs" not in insp.get_table_names():
        # 全新库由 create_all 按模型建表（模型里已经有这一列），这里没什么可做的。
        return
    cols = {c["name"] for c in inspect(engine).get_columns("operation_logs")}
    if "origin" not in cols:
        with engine.begin() as conn:
            # ⛔ 必须能重跑（README 硬要求：MySQL 的 DDL 隐式提交，一条迁移可能改了一半才失败）。
            # ⛔ NOT NULL 必须带 DEFAULT：老库里已经有行，没有默认值这条 ALTER 会直接失败。
            conn.execute(text(
                f"ALTER TABLE operation_logs ADD COLUMN origin VARCHAR({COLUMN_LEN}) "
                "NOT NULL DEFAULT 'human'"
            ))
    # 索引单独判：ALTER 成功、建索引失败时，重跑要把缺的那一步补上（而不是因为「列已在」整条跳过）。
    idx = {i["name"] for i in inspect(engine).get_indexes("operation_logs")}
    if INDEX_NAME not in idx:
        with engine.begin() as conn:
            conn.execute(text(f"CREATE INDEX {INDEX_NAME} ON operation_logs (origin)"))