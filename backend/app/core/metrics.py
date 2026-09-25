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

能算的 **9 个** → 真指标（每个都写明数据来源，可复核）；算不出的 **2 个**（都是 AI 那两个）
**不编数**，在 `NOT_TRACKED` 里写清"为什么现在算不出来、它该长在哪里"。
**宁可空着并说明，也不要给一个看起来正常的假数** —— 假数会让"外部监控"从保障变成误报源。

⚠️ **"算不出来"这句话是会过期的**：`push_success` / `push_failure` 原来就挂在这张表上，
理由是"要等 §10 的事务发件箱落地"；发件箱 2026-09-25 落地（`outbox_events`）之后它们
**就成了真指标**（`sorders_push_success_today` / `sorders_push_failure_today`）。
每做完一个前置条件都要回头看这张表一眼：一条过期的"算不出来"，轻则让下一个人以为还缺东西，
重则有人照着它去**凑一个假数**（那正是本模块最反对的事）。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.business_time import business_day_start_utc, business_today
from app.core.outbox import outbox_stats
from app.models.driver_settlement import DriverSettlement
from app.models.enums import OrderStatus
from app.models.ledger import Ledger
from app.models.ai_call_daily import AiCallDaily
from app.models.operation_log import OperationLog
from app.models.notification import Notification
from app.models.order import Order
from app.models.outbox import OutboxEvent, OutboxStatus


@dataclass(frozen=True)
class Metric:
    """一个指标：名字、说明、当前值，以及这个数**从哪来**（可复核是硬要求）。"""

    name: str
    help: str
    value: int
    source: str


#: 报告点名、但**当前算不出来**的指标 —— 每条都写清原因与它该有的位置。
#: ⛔ 不要用"近似值"填空：push_success 与"发出去的通知条数"不是一回事。
#: 报告点名、但**当前算不出来**的指标 —— 每条都写清原因与它该有的位置。
#: ⛔ 不要用"近似值"填空。
#:
#: 2026-09-25：**空了**。`AI_write_confirmed` 与 `AI_calls` 两个都已落地：
#:   · 前者 = `operation_logs.origin = ai`（**后端从库里数**，能对回审计表）；
#:   · 后者 = `ai_call_daily`（**App 上报**，见 `api/v1/ai_telemetry.py` 里的口径说明）。
#: 这张表留着不删：它是"报告点名、当前算不出"的正式去处，下一条缺口该进这里。
NOT_TRACKED: dict[str, str] = {
    # ---- R3-04-B：指南点名、但**现在算不出来**的（每条写清为什么 + 它该长在哪）----
    "orders_accepted": (
        "orders 表**没有 accepted_at 列**（只有 dispatched_at / delivered_at / cancelled_at），"
        "而 ACCEPTED 是**过程态**：单子很快就进 DELIVERED，事后没法从状态列回推‘今天接了几单’。"
        "该长在哪：给 orders 补一列 accepted_at（要动核心区 + 一条迁移），下一轮的选择。"
    ),
    "commands_failed": (
        "失败的命令**没有落库**：审计行只在成功写入时产生，而命令失败走的是 `CommandError` → 4xx，"
        "那一层不写审计（写它要先想清楚‘拒绝也要留痕吗’）。"
        "该长在哪：要么让它变成 ‘operation_logs 加 result 列’，要么由访问日志按状态码聚合。"
    ),
    "notifications_deduplicated": (
        "被幂等键挡下的重投**没有计数**：唯一索引冲突后是回查已有那条，不写任何一行。"
        "⛔ 不要拿‘事件重投次数’去近似它 —— 那是另一个量。"
        "该长在哪：真要它就要一个计数器（那正是本模块反对的打点），先用 events_retried 看趋势。"
    ),
    "migration_failure": (
        "迁移失败**不写版本表**（故意的：没跑成就不许记账），所以查库查不到失败。"
        "它现在只出现在日志里（`迁移 NNN_xxx 失败`）。该长在哪：迁移运行记录表（一次一行）。"
    ),
    "scheduler_acquired": (
        "数据治理的选主结果没有落库：它写在**日志**与**标记文件**里（`sorders_retention.last`）。"
        "该长在哪：`data_retention_runs` 一次运行一行（谁跑的、拿到没拿到、各步结果）。"
    ),
    "scheduler_skipped": (
        "同上：跳过只打一行日志（‘本轮跳过’），没有计数的地方。"
    ),
    "request_latency": (
        "每次请求的耗时**只在访问日志里**（`GET /x → 200（12.3 ms）`），没有聚合。"
        "⛔ 也不该在这里现算：聚合时延要直方图，而现算只能给‘某一刻的均值’，那个数会误导人。"
        "该长在哪：由外部按日志聚合，或者上指标库（指南 §R3-04-C 说这一轮**先不上**）。"
    ),
}


def _count_day(db: Session, model: type) -> int:
    """日表里**今天那一行**的计数（表里一天一行；没有那一行就是 0）。

    ⚠️ 为什么不是 `_count`：日表存的是**累计值**不是事件行，数行数只会得到 0 或 1。
    """
    row = db.get(model, business_today().isoformat())
    return int(getattr(row, "calls", 0) or 0)


def _count(db: Session, model: type, *where: object) -> int:
    stmt = select(func.count()).select_from(model)
    if where:
        stmt = stmt.where(*where)
    return int(db.execute(stmt).scalar() or 0)


def _count_distinct(db: Session, column: object, *where: object) -> int:
    """去重计数（命令条数用：同一条命令写多行审计只算一条）。"""
    return int(db.scalar(select(func.count(func.distinct(column))).where(*where)) or 0)


def _last_migration_ms(db: Session) -> int:
    """最近一次迁移的耗时 —— ⛔ 走 `app.migrations` 的**只读**读法，不自己写那张表的名字：
    表名与只读纪律都归迁移模块管（判据 `_check_migrations.py` 会红在「谁又写了一遍那张表」）。
    """
    from app.migrations import last_migration_duration_ms

    return last_migration_duration_ms(db.get_bind())


def snapshot(db: Session) -> list[Metric]:
    """算"此刻"的业务指标（窗口 = 业务当地日的今天 00:00 起）。"""
    day = business_today()
    start = business_day_start_utc(day)   # UTC naive，与库里存的时间同形，可直接比
    live = Order.deleted_at.is_(None)     # 软删的单不算（回收站里的单不该出现在指标上）

    def orders(*where: object) -> int:
        return _count(db, Order, live, *where)

    # 发件箱（报告 §10）：新的事件边界必须**自己可见** —— 否则它只是换了个地方丢事件。
    outbox = outbox_stats(db)

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
        # ---- 报告点名的 push_success / push_failure（2026-09-25：§10 发件箱落地后**能算了**）----
        # ⚠️ 两个窗口的口径**不一样**，这里写明免得被当成"同一件事两个数"：
        #    success 看 sent_at（今天**发出去**的），failure 看 created_at（今天**产生**、且已被放弃的）——
        #    `mark_failed` 不写 sent_at（它压根没发出去），拿 sent_at 去数失败永远是 0。
        Metric(
            "sorders_push_success_today",
            "今天推送成功的事件数（原报告的 push_success；来源＝发件箱已发状态）",
            _count(db, OutboxEvent, OutboxEvent.status == OutboxStatus.SENT.value,
                   OutboxEvent.sent_at >= start),
            "outbox_events.sent_at",
        ),
        Metric(
            "sorders_push_failure_today",
            "今天被放弃的推送事件数（原报告的 push_failure；≠0 就是有人得去看 last_error）",
            _count(db, OutboxEvent, OutboxEvent.status == OutboxStatus.FAILED.value,
                   OutboxEvent.created_at >= start),
            "outbox_events.created_at",
        ),
        Metric(
            "sorders_outbox_pending",
            "发件箱里待发的事件数（一直 >0 不降 = worker 卡了或处理器在失败）",
            outbox.get("pending", 0),
            "outbox_events.status",
        ),
        Metric(
            "sorders_outbox_failed",
            "发件箱里已放弃的事件数（≠0 就是要人去看 last_error）",
            outbox.get("failed", 0),
            "outbox_events.status",
        ),
        # ---- R3-04-B：指南点名的业务指标里**能算**的那几个（算不出的进 NOT_TRACKED，不编数）----
        Metric(
            "sorders_commands_today",
            "今天执行过的**命令**条数（按 operation_logs.command_id 去重；R3-04-A 加的那一列）",
            _count_distinct(db, OperationLog.command_id, OperationLog.created_at >= start),
            "operation_logs.command_id",
        ),
        Metric(
            "sorders_notifications_created_today",
            "今天创建的站内信条数（事件重投被幂等键挡下的不计在内）",
            _count(db, Notification, Notification.created_at >= start),
            "notifications.created_at",
        ),
        Metric(
            "sorders_outbox_retried_today",
            "今天**重试过**的事件数（attempts>1；≠0 说明有处理器在失败后恢复）",
            _count(db, OutboxEvent, OutboxEvent.attempts > 1, OutboxEvent.created_at >= start),
            "outbox_events.attempts",
        ),
        Metric(
            "sorders_last_migration_duration_ms",
            "最近一次迁移耗时（毫秒）；迁移变慢（大表 ALTER）时这里先看得出来",
            _last_migration_ms(db),
            "app.migrations.last_migration_duration_ms()",
        ),
        Metric(
            "sorders_driver_settlements_today",
            "今天生成的司机结算单数（含草稿）",
            _count(db, DriverSettlement, DriverSettlement.created_at >= start),
            "driver_settlements.created_at",
        ),
        # ---- 报告 §15 ② 的 AI_write_confirmed（2026-09-25：origin 列落地后**能算了**）----
        # ⛔ 它是**后端从库里数出来的**，不是 App 报上来的：AI 写入走的仍是普通业务端点，
        #    但 App 在「用户点过确认卡」时带 `X-SOrders-Origin: ai`，中间件记进 operation_logs.origin。
        #    这样它与审计表**是同一个事实**（能逐行对回去），而不是一个孤立的计数器。
        Metric(
            "sorders_ai_write_confirmed_today",
            "今天由 AI 确认卡**真的写进库**的操作数（原报告的 AI_write_confirmed；来源＝operation_logs.origin=ai）",
            _count(db, OperationLog, OperationLog.origin == "ai", OperationLog.created_at >= start),
            "operation_logs.origin",
        ),
        # ⚠️ 这一条与上一条**不同源**，help 里必须说清：模型跑在 App 里，后端看不到调用本身，
        #    只能由 App 上报（`POST /ai/telemetry` → `ai_call_daily`）。
        #    ⛔ 别把它们当成"同一件事的两个数"：上一条能逐行对回审计表，这一条只能信客户端。
        Metric(
            "sorders_ai_calls_today",
            "今天 App 上报的 AI 对话次数（原报告的 AI_calls；**客户端上报**，与 ai_write_confirmed 不同源）",
            _count_day(db, AiCallDaily),
            "ai_call_daily.calls",
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
