"""业务指标（整改报告 §15 ②）—— 只读、**抓的时候现算**、不在业务路径上打点。

## 口径：为什么是「抓的时候算」而不是「业务路径上打点」

1. **同一件事只有一个数**。本项目最贵的一类缺陷是"同一件事两个数"（司机账单 vs 运费结算页、
   货主账 vs 核销）：打点等于在真实数据之外**再造一份计数**，两者必然会漂移（漏打一处就永久少一份，
   而且没人会发现）；从 `orders` / `ledgers` 现算只有一份真相 —— 库里有几行就是几行。
2. **不动核心区**（用户 2026-09-21 定的准则）：钱与状态机那几个文件一行不碰。
3. 代价是每次抓取几条 `COUNT` —— 只有监控在抓（分钟级），且都走在已有索引上。

## 窗口一律用**业务当地日**（`core/business_time.py`）

用 UTC 分桶会让每天有 8 小时算进前一天 —— 那正是 2026-09-19 审计里"日报显示昨天的数"的成因。
指标的"今天"必须与报表、账单是同一个今天。

## 报告点名 10 个指标，这里如实分成两类

能算的 7 个 → 真指标（每个都写明数据来源，可复核）；算不出的 4 个**不编数**，
在 `NOT_TRACKED` 里写清"为什么现在算不出来、它该长在哪里"。
**宁可空着并说明，也不要给一个看起来正常的假数** —— 假数会让"外部监控"从保障变成误报源。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.business_time import business_day_start_utc, business_today
from app.models.driver_settlement import DriverSettlement
from app.models.enums import OrderStatus
from app.models.ledger import Ledger
from app.models.order import Order


@dataclass(frozen=True)
class Metric:
    """一个指标：名字、说明、当前值，以及这个数**从哪来**（可复核是硬要求）。"""

    name: str
    help: str
    value: int
    source: str


#: 报告点名、但**当前算不出来**的指标 —— 每条都写清原因与它该有的位置。
#: ⛔ 不要用"近似值"填空：push_success 与"发出去的通知条数"不是一回事。
NOT_TRACKED: dict[str, str] = {
    "push_success": "推送成败没有落点 —— socketio.emit 之后谁也不记录结果；"
    "它该补在报告 §10 的 Outbox（事务发件箱）里，而不是在这里凑一个近似值",
    "push_failure": "同上：emit 失败只在日志里一闪而过，没有可数的落点（Outbox 落地后补）",
    "AI_calls": "模型跑在 App 里（后端没有 AI 代理端点），服务端只看到普通业务请求 ——"
    "要采它得先加一条客户端上报（阶段 7 / 8 的后续）",
    "AI_write_confirmed": "AI 写入走的是普通业务端点 + App 侧确认卡；后端动作码里"
    "只有 AI_UNDO 一个与 AI 直接相关 —— 现在算不出「AI 确认了几次写入」",
}


def _count(db: Session, model: type, *where: object) -> int:
    stmt = select(func.count()).select_from(model)
    if where:
        stmt = stmt.where(*where)
    return int(db.execute(stmt).scalar() or 0)


def snapshot(db: Session) -> list[Metric]:
    """算"此刻"的业务指标（窗口 = 业务当地日的今天 00:00 起）。"""
    day = business_today()
    start = business_day_start_utc(day)   # UTC naive，与库里存的时间同形，可直接比
    live = Order.deleted_at.is_(None)     # 软删的单不算（回收站里的单不该出现在指标上）

    def orders(*where: object) -> int:
        return _count(db, Order, live, *where)

    return [
        Metric(
            "sorders_orders_created_today",
            "今天新建的订单数（业务当地日 00:00 起，不含回收站里的）",
            orders(Order.created_at >= start),
            "orders.created_at",
        ),
        Metric(
            "sorders_orders_assigned_today",
            "今天派单出去的订单数",
            orders(Order.dispatched_at.is_not(None), Order.dispatched_at >= start),
            "orders.dispatched_at",
        ),
        Metric(
            "sorders_orders_delivered_today",
            "今天送达的订单数",
            orders(Order.delivered_at.is_not(None), Order.delivered_at >= start),
            "orders.delivered_at",
        ),
        Metric(
            "sorders_orders_cancelled_today",
            "今天撤销的订单数",
            orders(Order.cancelled_at.is_not(None), Order.cancelled_at >= start),
            "orders.cancelled_at",
        ),
        Metric(
            "sorders_orders_pending_dispatch",
            "此刻待派池里的订单数（积压到几万时这里一眼可见）",
            orders(Order.status == OrderStatus.PENDING_DISPATCH),
            "orders.status",
        ),
        Metric(
            "sorders_ledger_entries_today",
            "今天入账的账本流水条数",
            _count(db, Ledger, Ledger.created_at >= start),
            "ledgers.created_at",
        ),
        Metric(
            "sorders_driver_settlements_today",
            "今天生成的司机结算单数（含草稿）",
            _count(db, DriverSettlement, DriverSettlement.created_at >= start),
            "driver_settlements.created_at",
        ),
    ]


def render_prometheus(metrics: list[Metric], day: date) -> str:
    """渲染成 Prometheus 文本格式（`text/plain; version=0.0.4`）。"""
    lines = [
        "# SOrders 业务指标（整改报告 §15 ②）—— 每个数都是抓取时现算的，不是打点累计",
        "# 窗口：业务当地日（东八区）；今天 = " + day.isoformat(),
        "# 口径与「算不出来」的那 4 个指标见 backend/app/core/metrics.py",
        "",
    ]
    for m in metrics:
        lines.append("# HELP " + m.name + " " + m.help)
        lines.append("# TYPE " + m.name + " gauge")
        lines.append("# 来源：" + m.source)
        lines.append(m.name + " " + str(m.value))
        lines.append("")
    lines.append("# ---- 报告点名、但当前算不出来的指标（不编数）----")
    for name, why in NOT_TRACKED.items():
        lines.append("#   未采集 " + name + "：" + why)
    return "\n".join(lines) + "\n"
