"""业务指标（`core/metrics.py` + `GET /metrics`）—— 整改报告 §15 ② 的可观测性第二件小事。

## 为什么单独立一条
指标错了**不会有人报障**：它不参与任何业务判断，页面上也看不见它。等真出事（比如"今天只建了 3 单"
而实际是 30 单）时，人只会怀疑业务，不会怀疑指标。所以这里把四件事钉死：

1. **没配口令一律 403**（fail-closed）—— 一个"默认打开"的指标端点等于把业务量白送给任何扫到它的人
   （本仓库是公开的）；
2. 口令对了才是 Prometheus 文本（外部监控要能直接抓）；
3. **计数与库里的行数一致**，窗口是**业务当地日**（不是 UTC 日 —— 差 8 小时就是"日报显示昨天的数"）；
4. 回收站里的单（软删）不算；
5. 报告点名但当前算不出来的指标必须**如实列出来**，而不是悄悄少几个数；
6. **反过来也要钉**：一旦前置条件做完了，它就必须从「算不出来」挪进真指标 ——
   `push_success` / `push_failure` 原来挂在那边，理由是「要等 §10 的事务发件箱落地」；
   发件箱 2026-09-25 落地，于是它们成了 `sorders_push_success_today` / `sorders_push_failure_today`。
   一条**过期的「算不出来」**，轻则让人以为还缺东西，重则有人照着它去凑一个假数。

⚠️ 断言一律用"前后差值"，不用绝对值：同一个 worker 的测试库是共享的，别的前置用例留下的行会漂。
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.business_time import business_today
from app.core.metrics import NOT_TRACKED, render_prometheus, snapshot
from app.main import fastapi_app, settings
from app.models.enums import OrderStatus
from app.models.order import Order
from app.models.outbox import OutboxEvent, OutboxStatus
from tests.conftest import iter_api_routes


def _values(db: Session) -> dict[str, int]:
    return {m.name: m.value for m in snapshot(db)}


def _seed(db: Session, *, status: OrderStatus = OrderStatus.PENDING_DISPATCH,
          delivered: bool = False, deleted: bool = False) -> Order:
    """造一张今天的单（只填 NOT NULL 的列；其余走模型默认值）。"""
    now = datetime.now(timezone.utc).replace(tzinfo=None)   # 库里一律 UTC naive
    order = Order(
        order_no="M" + uuid4().hex[:12],
        status=status,
        order_date=business_today(),
        dispatched_at=None if status == OrderStatus.PENDING_DISPATCH else now,
        delivered_at=now if delivered else None,
        deleted_at=now if deleted else None,
    )
    db.add(order)
    db.flush()
    return order


def test_metrics_endpoint_is_closed_when_no_token_is_configured(client, monkeypatch):
    """⛔ 默认关闭：没配 METRICS_TOKEN 就是 403（不是"空口令通过"）。"""
    monkeypatch.setattr(settings, "metrics_token", "")
    assert client.get("/metrics").status_code == 403


def test_metrics_endpoint_needs_the_right_token(client, monkeypatch):
    monkeypatch.setattr(settings, "metrics_token", "scrape-me-2026")
    assert client.get("/metrics").status_code == 403
    assert client.get("/metrics", headers={"X-Metrics-Token": "wrong"}).status_code == 403
    ok = client.get("/metrics", headers={"X-Metrics-Token": "scrape-me-2026"})
    assert ok.status_code == 200
    assert ok.headers["content-type"].startswith("text/plain")
    assert "sorders_orders_created_today" in ok.text
    assert "# TYPE sorders_orders_created_today gauge" in ok.text


def test_counts_track_the_database(db_session: Session):
    before = _values(db_session)
    _seed(db_session)
    _seed(db_session, status=OrderStatus.DELIVERED, delivered=True)
    after = _values(db_session)
    assert after["sorders_orders_created_today"] - before["sorders_orders_created_today"] == 2
    assert after["sorders_orders_delivered_today"] - before["sorders_orders_delivered_today"] == 1
    assert after["sorders_orders_assigned_today"] - before["sorders_orders_assigned_today"] == 1
    assert after["sorders_orders_pending_dispatch"] - before["sorders_orders_pending_dispatch"] == 1


def test_soft_deleted_orders_are_not_counted(db_session: Session):
    """回收站里的单不该出现在指标上（它是"删了但能恢复"，不是"今天真建了这么多"）。"""
    before = _values(db_session)["sorders_orders_created_today"]
    _seed(db_session)
    _seed(db_session, deleted=True)
    after = _values(db_session)["sorders_orders_created_today"]
    assert after - before == 1


def _seed_outbox(db: Session, *, status: str, sent: bool = False) -> OutboxEvent:
    """造一条发件箱事件（`mark_failed` 不写 sent_at —— 拿 sent_at 去数失败永远是 0）。"""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    row = OutboxEvent(
        event_type="orders.created",
        payload="{}",
        status=status,
        attempts=1,
        sent_at=now if sent else None,
        next_attempt_at=now,
    )
    db.add(row)
    db.flush()
    return row


def test_push_metrics_come_from_the_outbox(db_session: Session):
    """报告点名、原来「算不出来」的两个：§10 发件箱落地后它们成了真指标。

    两个窗口的口径不一样（见 `metrics.snapshot` 的注释）：success 看 sent_at、failure 看 created_at。
    """
    before = _values(db_session)
    _seed_outbox(db_session, status=OutboxStatus.SENT.value, sent=True)
    _seed_outbox(db_session, status=OutboxStatus.FAILED.value)
    after = _values(db_session)
    assert after["sorders_push_success_today"] - before["sorders_push_success_today"] == 1
    assert after["sorders_push_failure_today"] - before["sorders_push_failure_today"] == 1
    assert "push_success" not in NOT_TRACKED, "它已经能算了 —— 还挂在「算不出来」表里就是过期说明"
    assert "push_failure" not in NOT_TRACKED, "同上"


def test_metrics_are_rendered_for_scrapers(db_session: Session):
    text = render_prometheus(snapshot(db_session), business_today())
    assert text.endswith("\n")
    for name in NOT_TRACKED:
        assert "未采集 " + name in text, name + " 没有如实列出来 —— 悄悄少一个数比空着更糟"
        assert name + " " not in text.replace("未采集 " + name, "")   # 不许编一个值出来


def test_metrics_route_is_registered():
    # ⚠️ 用 `iter_api_routes`（递归拍平）而不是直接遍历 `fastapi_app.routes`：
    #    starlette 1.7.0 下 `.routes` 里是 `_IncludedRouter`，没有 `.path` →
    #    `AttributeError`（CI 上就是这么红的）。见 `conftest.iter_api_routes` 的说明。
    paths = [r.path for r in iter_api_routes(fastapi_app)]
    assert "/metrics" in paths

