"""事务发件箱（Outbox）的行 —— 整改报告 §10「建立真正可靠的事件边界」。

报告点名的病是：**数据库成功 → 后台任务恰好挂了 → 事件永远丢失**（现在的形状是
「业务操作 → 数据库 → background task → Socket.IO」，而 background task 是尽力而为的）。

## 为什么状态列用 `String(12)` 而不是 `SAEnum`
本项目在 MySQL 的 ENUM 列上栽过（`backend/tests/test_enum_repair_ddl.py` 记着：生产库的枚举值比模型
少一个 → 那一档状态一写就 500，还得靠 `schema_bootstrap` 专门去「补枚举」）。发件箱的状态只有三档、
而且**不外露**（不进任何 API 出参、不给用户看），所以用普通字符串列 + Python 枚举：把「补枚举」这类
事故从根上避免，而代价只是 Python 侧要自己校验。

## 为什么 payload 用 TEXT 存 JSON 字符串
与 `products.tier_prices` / `orders.image_urls` 同一条路：跨 SQLite / MySQL 都不用管 JSON 列差异。
⚠️ 读回来一律把 `None` 归一成 `{}`（本项目栽过 NULL 毒化：`default_factory` 兜不住 NULL）。
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from sqlalchemy import DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.business_time import utc_now_naive
from app.models.base import Base, TimestampMixin


class OutboxStatus(str, Enum):
    """待发 / 已发 / 放弃。"""

    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"


class OutboxEvent(Base, TimestampMixin):
    """一条待发事件（与业务写在**同一个事务**里）。"""

    __tablename__ = "outbox_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    #: 事件类型（orders.assigned / orders.delivered / ledger.updated …）—— 派发方按它选处理器
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    #: JSON 字符串（见模块说明：不用 JSON 列）
    payload: Mapped[str] = mapped_column(Text, default="{}")
    #: 去重键：同一次业务动作重复入队只会有一条（None 表示不去重，允许重复入队）
    dedupe_key: Mapped[str | None] = mapped_column(String(128), unique=True, nullable=True)
    status: Mapped[str] = mapped_column(String(12), default=OutboxStatus.PENDING.value, index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: 下一次可以尝试的时间（失败退避用）；新建的行 = 立刻可发
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now_naive, index=True
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=None)

    #: 派发方的取数索引：待发 + 到点，按 id 先入先发
    __table_args__ = (Index("ix_outbox_status_next", "status", "next_attempt_at"),)

    def payload_dict(self) -> dict:
        """读回来的 payload **一律**是 dict（NULL / 坏 JSON 都不许让派发方炸）。"""
        import json

        raw = self.payload
        if not raw:
            return {}
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}
