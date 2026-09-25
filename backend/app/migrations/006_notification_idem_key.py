"""006_notification_idem_key：站内信的**幂等键**（第二轮 R2-04「幂等消费」）。

### 为什么需要它
指南 §七 点名了事件边界的第二种失败方式：事件发两次，不能导致记两次账 / 发两次结算 / 退两次库存。

本系统里「事件」真正驱动的是**推送与站内信**（钱与库存都在业务事务里同步落，不经过发件箱）。
而发件箱的口径是**至少一次**（失败退避重试，快速通道与 worker 两条路都在跑），
所以「同一条事件被派发两次」是**设计内的正常情况**，不是故障。

实测（2026-09-25 盘点 18 条事件 / 39 个入队点）：**13 条事件的处理器不幂等** ——
重投一次就多一条站内信，而且**没有任何地方会报错**（用户只会觉得「怎么又发了一遍」）。

### 为什么加在站内信上，而不是逐个处理器去改
13 条处理器里每一处都自己判一遍「我是不是已经发过了」，就是 13 份各写各的幂等，
必然有的写对有的写错（本仓库最贵的一类错）。而**站内信的创建只有一处实现**
（message_center.create_message）—— 把幂等键加在那里，13 条一次性都有。

### 三条设计选择
1. **键由业务事实算，不由事件号算**（order.assigned:12:7 这种）。用事件号的话，
   同一个事实被两条不同事件推两次就还是两条 —— 那正是要防的；
2. **键里带收件人**（create_message 内部拼 #recipient_id）：同一条事实要发给司机与派单员两个人，
   那是两条**该发**的消息；
3. **唯一索引由数据库保证**，不是「先查再插」：两个 worker 同时派同一条事件时，
   「先查再插」挡不住重复（本项目在库存与计数的 lost update 上栽过同一个形状）。
   ⚠️ 用独立的 CREATE UNIQUE INDEX，而不是 ALTER 里带 UNIQUE：
   **SQLite 不支持 ALTER TABLE ADD COLUMN 带 UNIQUE**，两种方言只有分开建索引才都能跑。
   MySQL 与 SQLite 对「唯一索引里的多个 NULL」语义一致（都不算冲突）—— 不传键的消息照旧随便发。
"""

from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

VERSION = 6
NAME = "notification_idem_key"
DESCRIPTION = "notifications 加 idem_key：站内信的幂等键（事件重投不再多出一条消息）"


def upgrade(engine: Engine) -> None:
    insp = inspect(engine)
    if "notifications" not in insp.get_table_names():
        return                                   # 必须能重跑（README 硬要求）
    if "idem_key" not in {c["name"] for c in insp.get_columns("notifications")}:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE notifications ADD COLUMN idem_key VARCHAR(160) NULL"))
    # 重新看一眼：上面那条 ALTER 是刚提交的，旧 inspector 的快照里还没有这一列。
    insp = inspect(engine)
    if "uq_notifications_idem_key" not in {i["name"] for i in insp.get_indexes("notifications")}:
        with engine.begin() as conn:
            conn.execute(text(
                "CREATE UNIQUE INDEX uq_notifications_idem_key ON notifications (idem_key)"
            ))
