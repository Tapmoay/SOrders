"""005_ai_call_daily：AI 调用计数的日表（整改报告 §15 ② 的 AI_calls）。

### 为什么需要一张新表
AI_calls 长期躺在 core/metrics.py 的 NOT_TRACKED 里，理由是「模型跑在 App 里，
后端看不到这次调用」。要让后端看得到，只有「App 报一个数上来」这一条路 ——
而这个数总得有个地方放。

### 为什么不用 operation_logs
⛔ AI 调用不是一次业务操作：写进审计表会让「谁改了什么」那张权威记录里混进几百行
「模型被调用了一次」，而审计页的价值恰恰在于它只有操作。所以另起一张日表。

### 两条设计选择
1. 一天一行、累加（主键 = 业务当地日）：这个数只用来看趋势，不需要逐条留痕；
   逐条存会让它比审计表还长得快，而信息量只有「今天 N 次」；
2. 两种方言都写（VERSION_TABLE 那张表同样的做法）：本机 SQLite、生产 MySQL。
"""

from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

VERSION = 5
NAME = "ai_call_daily"
DESCRIPTION = "ai_call_daily：AI 调用计数的日表（报告 §15 ② 的 AI_calls，由 App 上报）"

_CREATE = {
    "mysql": (
        "CREATE TABLE IF NOT EXISTS ai_call_daily ("
        "  day VARCHAR(10) NOT NULL,"
        "  calls INT NOT NULL DEFAULT 0,"
        "  updated_at DATETIME NOT NULL,"
        "  PRIMARY KEY (day)"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    ),
    "sqlite": (
        "CREATE TABLE IF NOT EXISTS ai_call_daily ("
        "  day TEXT NOT NULL PRIMARY KEY,"
        "  calls INTEGER NOT NULL DEFAULT 0,"
        "  updated_at TEXT NOT NULL"
        ")"
    ),
}


def upgrade(engine: Engine) -> None:
    insp = inspect(engine)
    if "ai_call_daily" in insp.get_table_names():
        return                                  # ⛔ 必须能重跑（README 硬要求）
    ddl = _CREATE.get(engine.dialect.name, _CREATE["sqlite"])
    with engine.begin() as conn:
        conn.execute(text(ddl))