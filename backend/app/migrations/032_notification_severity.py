"""032_notification_severity：站内信的**严重度**（FEAT-0019 消息分级）。

### 为什么需要它
用户口径（2026-10-11，逐字）：「消息（底部 Tab）……要按消息类型做颜色区别」，
且「文字也要按风险程度着色……按风险程度分红 / 橙 / …（重要程度不同 → 文字颜色不同）」。
App 那一侧按 `severity` 给**未读**卡的正文上色（danger 红 / warn 橙 / info 不上色），
所以这个字段必须真的落到库里，并且出现在 `GET /notifications` 的出参（`NotificationOut`）上。

### 为什么走迁移而不是 schema_bootstrap
`schema_bootstrap` 是**运行时自愈**：它只补那些"缺了就会 500"的列（每次启动跑一遍）。
severity 缺了不会 500 —— 它会让**所有消息安静地退回"普通消息"**，正是那种没人报错的坏法。
这正是"正式变更走 `migrations/NNN_*.py`（每版本只跑一次）、自愈走 bootstrap"那条分工里
前者的形状（`_tools/qa/_check_silent_release.py` 第 5 条：建表不许偷偷塞进 bootstrap）。

### 为什么不回填
存量消息（升级前投递的）一律 `info`：拿今天的 `type`→档位表去追认历史，等于把
"当时发出的那条消息"改写成"今天的判断"。`DEFAULT 'info'` 顺带把已有行一次填好；
升级之后的新行由模型现算（`models/notification.py::severity_default` → `message_center.severity_for`）。

⚠️ 与 `006_notification_idem_key.py` 同一条写法：**ALTER 与索引分开建** ——
   SQLite 不支持 `ALTER TABLE ... ADD COLUMN` 带 UNIQUE/索引，两种方言只有分开才都能跑；
   列已存在就跳过（本文件可重跑，README 硬要求）。
"""

from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

VERSION = 32
NAME = "notification_severity"
DESCRIPTION = "notifications 加 severity：站内信严重度 info/warn/danger（FEAT-0019）"


def upgrade(engine: Engine) -> None:
    insp = inspect(engine)
    if "notifications" not in insp.get_table_names():
        return                                   # 必须能重跑（README 硬要求）
    if "severity" not in {c["name"] for c in insp.get_columns("notifications")}:
        with engine.begin() as conn:
            # NOT NULL + DEFAULT：存量行一次填成 info（不回填历史判断，见模块 docstring）
            conn.execute(text(
                "ALTER TABLE notifications ADD COLUMN severity VARCHAR(8) "
                "NOT NULL DEFAULT 'info'"
            ))
    # 重新看一眼：上面那条 ALTER 是刚提交的，旧 inspector 的快照里还没有这一列。
    insp = inspect(engine)
    if "ix_notifications_severity" not in {i["name"] for i in insp.get_indexes("notifications")}:
        with engine.begin() as conn:
            conn.execute(text(
                "CREATE INDEX ix_notifications_severity ON notifications (severity)"
            ))
