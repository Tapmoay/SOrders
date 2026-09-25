#!/usr/bin/env python3
"""_trace_order.py —— **订单全链路**一条命令查完（第二轮 R2-06 · 指南 §十五）。

## 它解决什么
指南 §十五 的原话：

> 这样你遇到：「为什么这笔订单的钱不对？」可以直接查完整链路。

链路是：

```text
  订单 #10086
   ↓ 命令 / 状态跃迁   orders.status + operation_logs.action
   ↓ 是哪一条命令       operation_logs.command_id   ← R3-04-A 的中间那一层
   ↓ 是哪一次请求       operation_logs.request_id
   ↓ 账本               ledgers.order_id
   ↓ 司机账单           driver_bills.order_id
   ↓ 事件               outbox_events.aggregate_id（含 event_id = 事件行自己的 id）
   ↓ 通知               notifications.payload

⛔ **三个 id 不是一个东西**（指南 §R3-04-A）：一次请求可以跑多条命令（批量派单就是），
   一条命令又可以产生多条事件。所以这里**并排打出来**，而不是合成一个「追踪号」。
```

## 用法

```bash
python _tools/ops/_trace_order.py S20260925001     # 按单号
python _tools/ops/_trace_order.py --latest          # 最近一张单（排障时最常用）
python _tools/ops/_trace_order.py S2026... --json    # 给别的脚本用
```

⛔ **只读**：全篇没有一个写语句（判据 `_tools/qa/_check_traceability.py` 盯着这件事，
以及「每一段链路是否真的被查了」）。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

#: 链路的七段。判据按这张表核对「每一段的表与列真的存在」+「这个工具真的查了它」。
LINKS: tuple[tuple[str, str, str], ...] = (
    ("订单与状态", "orders", "order_no, status, created_at, dispatched_at, driver_acknowledged_at, delivered_at, cancelled_at"),
    ("命令与审计", "operation_logs",
     "order_id, action, command_id, request_id, origin, operator_id, created_at"),
    ("账本", "ledgers", "order_id, source, total, entry_date"),
    ("司机账单", "driver_bills", "order_id, driver_id, amount, status, rule_name"),
    ("事件", "outbox_events", "aggregate_id, event_type, status, attempts, sent_at"),
    ("通知", "notifications", "payload, idem_key, recipient_id, type, created_at"),
)


def _d(v) -> str:
    return "-" if v is None else str(v)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python _tools/ops/_trace_order.py")
    ap.add_argument("order_no", nargs="?", help="单号（不传就配 --latest）")
    ap.add_argument("--latest", action="store_true", help="取最近一张单")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--url", help="数据库 URL（缺省读 settings.database_url；本机排障给 sqlite:///./backend/sorders.db）")
    a = ap.parse_args(argv)

    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import sessionmaker

    from app.models import DriverBill, Ledger, Notification, OperationLog, Order
    from app.models.outbox import OutboxEvent

    # ⛔ **不 import `app.database`**：那个模块在导入时就 `bootstrap_schema(engine)`（建表 + 全部自愈）——
    #    一个**只读**的排障工具不该在别人的库上跑 DDL。这里自己按 URL 建引擎。
    url = a.url
    if not url:
        from app.config import get_settings

        url = get_settings().database_url
    db = sessionmaker(bind=create_engine(url, future=True))()
    try:
        stmt = select(Order).order_by(Order.id.desc())
        if a.order_no:
            stmt = select(Order).where(Order.order_no == a.order_no).order_by(Order.id.desc())
        order = db.scalars(stmt.limit(1)).first()
        if order is None:
            print("没有这张单：" + (a.order_no or "（库里一张单都没有）"))
            return 1

        logs = db.scalars(
            select(OperationLog).where(OperationLog.order_id == order.id).order_by(OperationLog.id)
        ).all()
        rows = db.scalars(select(Ledger).where(Ledger.order_id == order.id).order_by(Ledger.id)).all()
        bills = db.scalars(select(DriverBill).where(DriverBill.order_id == order.id).order_by(DriverBill.id)).all()
        # ⚠️ `aggregate_id` 是 R2-04（2026-09-25）才加的列，**历史事件不回填** ——
        #    所以按聚合根查不到时，回退到"payload 里写着这个单号或这个 id"，并如实标出来是哪种来源。
        events = list(db.scalars(
            select(OutboxEvent).where(OutboxEvent.aggregate_id == str(order.id)).order_by(OutboxEvent.id)
        ).all())
        event_src = "aggregate_id"
        if not events:
            events = [e for e in db.scalars(
                select(OutboxEvent).order_by(OutboxEvent.id.desc()).limit(2000)
            ).all() if _has_order(e.payload_dict(), order)]
            event_src = "payload（历史事件没有 aggregate_id）"
        # ⚠️ 通知的 payload 是 JSON 列，两种方言的 LIKE 行为不一致 —— 取最近一批**在 Python 里筛**，
        #    并如实说明「只看最近 N 条」（排障要的是"有没有、长什么样"，不是全量对账）。
        # ⛔ 筛法必须是**按键精确比**，不能是"字符串里出现过这个数字"：
        #    第一版就是这么写的，结果把 9 月 16 日别的单的通知也捞进来了（金额里恰好有那几个数字）——
        #    排障工具给出假阳性比给不出结论更糟：人会照着它去查错的地方。
        recent = db.scalars(select(Notification).order_by(Notification.id.desc()).limit(2000)).all()
        notes = [n for n in recent if _has_order(n.payload or {}, order)]

        if a.json:
            print(json.dumps({
                "order_no": order.order_no,
                "status": _d(getattr(order.status, "value", order.status)),
                "logs": [{"action": x.action, "command_id": x.command_id, "request_id": x.request_id,
                      "origin": x.origin} for x in logs],
                "ledger_rows": len(rows),
                "driver_bills": len(bills),
                "events": [{"event_id": e.id, "type": e.event_type, "status": e.status} for e in events],
                "notifications": [{"id": n.id, "type": n.type} for n in notes],
                "notifications_scanned": len(recent),
            }, ensure_ascii=False, indent=2));
            return 0

        print("订单 " + order.order_no + "  状态=" + _d(getattr(order.status, "value", order.status))
              + "  id=" + str(order.id))
        print("  下单 " + _d(order.created_at) + "  派单 " + _d(order.dispatched_at)
              + "  接单 " + _d(order.driver_acknowledged_at) + "  送达 " + _d(order.delivered_at)
              + "  撤销 " + _d(order.cancelled_at))
        print()
        print("[命令与审计] " + str(len(logs)) + " 行（命令 command_id + 请求 request_id 并排）")
        for x in logs:
            print("   " + _d(x.created_at) + "  " + x.action
                  + "  命令=" + _d(x.command_id) + "  请求=" + _d(x.request_id)
                  + "  来源=" + _d(x.origin))
        print("[账本] " + str(len(rows)) + " 行")
        for r in rows:
            print("   " + _d(r.entry_date) + "  " + _d(getattr(r.source, "value", r.source))
                  + "  " + _d(r.product_name) + "  " + _d(r.total))
        print("[司机账单] " + str(len(bills)) + " 行")
        for b in bills:
            print("   " + _d(b.amount) + "  " + _d(b.status) + "  规则=" + _d(b.rule_name))
        print("[事件] " + str(len(events)) + " 行（来源：" + event_src + "）")
        for e in events:
            print("   " + _d(e.created_at) + "  事件#" + _d(e.id) + "  " + e.event_type
                  + "  " + e.status + "  尝试=" + _d(e.attempts))
        print("[通知] " + str(len(notes)) + " 条（在最近 " + str(len(recent)) + " 条里筛出）")
        for n in notes[:20]:
            print("   " + _d(n.created_at) + "  " + n.type + "  → 收件人 " + str(n.recipient_id))
        return 0
    finally:
        db.close()


def _has_order(payload, order) -> bool:
    """这份 payload 说的是不是**这一张单**（按键精确比，不做字符串包含）。"""
    if not isinstance(payload, dict):
        return False
    for key in ("order_id", "orderId"):
        v = payload.get(key)
        if v is not None and str(v) == str(order.id):
            return True
    for key in ("order_no", "orderNo"):
        if payload.get(key) == order.order_no:
            return True
    return False


if __name__ == "__main__":
    raise SystemExit(main())
