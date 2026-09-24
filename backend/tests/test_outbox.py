"""事务发件箱（`core/outbox.py` + `models/outbox.py`）—— 整改报告 §10「建立真正可靠的事件边界」。

## 这一批要钉住的（每条都有「不钉住会怎样」）

| 判据 | 不钉住会怎样 |
|---|---|
| 入队与业务**同一个事务**（`enqueue` 不 commit） | 业务回滚了事件还在 → 给一张不存在的单推消息；反过来"业务提交了事件没了"就是报告点名的"事件永远丢失" |
| `dedupe_key` 唯一 | 同一次业务动作重复入队 → 司机收到同一条推送两次（App 侧还得再兜一次） |
| 成功才标 `sent` | 没发出去也标成功 = 换了个地方丢事件 |
| 失败要记 `last_error` + 退避重试 | 失败静默 → 排查时只有"用户说没收到" |
| 尝试用满要**放弃**（`failed`） | 一条永远发不出去的事件会把队头堵死 |
| `payload` 读到 NULL/坏 JSON 不许炸 | 一条脏数据让整个 worker 循环停摆 |
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select

from app.core import outbox
from app.core.business_time import utc_now_naive
from app.models import OutboxEvent, OutboxStatus
from app.services import push_events
from tests.conftest import auth_headers


def _clear(db) -> None:
    """清掉本表（`dispatch_sync` 会 commit，fixture 的 rollback 收不走它）—— 只在**本表**内清。"""
    db.query(OutboxEvent).delete(synchronize_session=False)
    db.commit()


def _rows(db) -> list[OutboxEvent]:
    return list(db.scalars(select(OutboxEvent).order_by(OutboxEvent.id)))


def _count(db) -> int:
    return int(db.execute(select(func.count()).select_from(OutboxEvent)).scalar() or 0)


def test_enqueue_does_not_commit(db_session):
    """⛔ 核心性质：入队**不 commit** —— 业务回滚，事件也必须跟着消失。"""
    _clear(db_session)
    assert outbox.enqueue(db_session, "orders.assigned", {"order_id": 1, "driver_id": 2}) is True
    db_session.flush()   # ⚠️ 本项目 sessionmaker 是 autoflush=False：不 flush 就查不到刚入队那条
    assert len(_rows(db_session)) == 1, "前提：行已经在**事务里**了"
    db_session.rollback()
    assert _count(db_session) == 0, "业务回滚之后事件还在 —— 那不是同一个事务"


def test_enqueue_survives_the_business_commit(db_session):
    _clear(db_session)
    outbox.enqueue(db_session, "orders.delivered", {"order_id": 5, "payload": "中文也行"})
    db_session.commit()
    rows = _rows(db_session)
    assert len(rows) == 1
    assert rows[0].status == OutboxStatus.PENDING.value
    assert rows[0].payload_dict() == {"order_id": 5, "payload": "中文也行"}


def test_dedupe_key_writes_once(db_session):
    _clear(db_session)
    assert outbox.enqueue(db_session, "orders.assigned", {"order_id": 1}, dedupe_key="order:1:assigned") is True
    assert outbox.enqueue(db_session, "orders.assigned", {"order_id": 1}, dedupe_key="order:1:assigned") is False
    db_session.commit()
    assert _count(db_session) == 1, "同一个去重键入队了两次"


def test_dispatch_marks_sent_and_hands_over_the_payload(db_session):
    _clear(db_session)
    outbox.enqueue(db_session, "orders.assigned", {"order_id": 7, "driver_id": 9})
    db_session.commit()
    seen: list[outbox.Event] = []
    stats = outbox.dispatch_sync(db_session, seen.append)
    assert stats == {"sent": 1, "retry": 0, "given_up": 0}, stats
    assert seen and seen[0].event_type == "orders.assigned"
    assert seen[0].payload == {"order_id": 7, "driver_id": 9}
    row = _rows(db_session)[0]
    assert row.status == OutboxStatus.SENT.value and row.sent_at is not None


def test_failure_retries_with_backoff_then_gives_up(db_session):
    """失败 → 记 last_error + 退避；尝试用满 → 放弃（不再被取），别把队头堵死。"""
    _clear(db_session)
    outbox.enqueue(db_session, "orders.assigned", {"order_id": 1})
    db_session.commit()

    def boom(_ev):
        raise RuntimeError("推送服务不在了")

    out = {}
    for _ in range(outbox.MAX_ATTEMPTS):
        row = _rows(db_session)[0]
        row.next_attempt_at = utc_now_naive()   # 让退避不影响这条用例（退避本身另有断言）
        db_session.commit()
        out = outbox.dispatch_sync(db_session, boom)

    row = _rows(db_session)[0]
    assert row.status == OutboxStatus.FAILED.value, row.status
    assert row.attempts == outbox.MAX_ATTEMPTS
    assert "推送服务不在了" in (row.last_error or "")
    assert out["given_up"] == 1, out
    assert outbox.claim(db_session) == [], "放弃之后还被取出来 —— 会一直重试到天荒地老"


def test_backoff_grows_and_is_capped(db_session):
    assert outbox.backoff_seconds(1) < outbox.backoff_seconds(2) < outbox.backoff_seconds(3)
    assert outbox.backoff_seconds(99) == outbox.MAX_BACKOFF_SECONDS
    _clear(db_session)
    outbox.enqueue(db_session, "orders.assigned", {})
    db_session.commit()
    outbox.dispatch_sync(db_session, lambda _ev: (_ for _ in ()).throw(RuntimeError("x")))
    row = _rows(db_session)[0]
    assert row.next_attempt_at > utc_now_naive(), "失败之后没有退避：会立刻重试到把日志刷满"


def test_a_later_success_clears_the_error(db_session):
    _clear(db_session)
    outbox.enqueue(db_session, "orders.assigned", {"order_id": 3})
    db_session.commit()
    calls = {"n": 0}

    def flaky(_ev):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("第一次失败")

    outbox.dispatch_sync(db_session, flaky)
    row = _rows(db_session)[0]
    row.next_attempt_at = utc_now_naive()
    db_session.commit()
    stats = outbox.dispatch_sync(db_session, flaky)
    row = _rows(db_session)[0]
    assert stats["sent"] == 1, stats
    assert row.status == OutboxStatus.SENT.value
    assert row.last_error is None, "成功之后还留着上一次的错误 —— 排障时会把人带偏"


def test_payload_survives_null_and_bad_json(db_session):
    """一条脏数据不许让整个 worker 循环停摆（NULL 毒化在本项目栽过）。"""
    _clear(db_session)
    outbox.enqueue(db_session, "orders.assigned", {})
    db_session.commit()
    row = _rows(db_session)[0]
    row.payload = None  # type: ignore[assignment]
    assert row.payload_dict() == {}
    row.payload = "{这不是 JSON"
    assert row.payload_dict() == {}
    row.payload = "[1, 2]"   # 不是 dict 也不是
    assert row.payload_dict() == {}


def test_assigning_an_order_enqueues_the_event_in_the_same_transaction(
    client, token_dispatcher, token_shipper, users, db_session
):
    """**派单那条链路已经切成发件箱**（报告 §10 第一个生产者）。

    这里走真实接口：响应照旧 200；而那条推送不再是"提交之后 add_task"，而是与派单
    **同一个事务**写进 `outbox_events`（由 worker 派发、失败会重试）。
    """
    _clear(db_session)
    line = {
        "product_name_snapshot": "发件箱探针",
        "quantity": 1,
        "unit_price": "10.00",
        "line_total": "10.00",
    }
    created = client.post(
        "/api/v1/orders",
        headers=auth_headers(token_shipper),
        json={"lines": [line], "delivery_description": "发件箱地址", "address_detail": "发件箱地址"},
    )
    assert created.status_code == 201, created.text
    oid = int(created.json()["id"])

    assigned = client.post(
        f"/api/v1/orders/{oid}/assign",
        json={"driver_id": users["driver"].id},
        headers=auth_headers(token_dispatcher),
    )
    assert assigned.status_code == 200, assigned.text

    db_session.expire_all()
    rows = [x for x in _rows(db_session) if x.event_type == "orders.assigned"]
    assert len(rows) == 1, [x.event_type for x in _rows(db_session)]
    assert rows[0].payload_dict() == {"driver_id": users["driver"].id, "order_id": oid}
    # ⚠️ 响应发出后有一条**快速通道**会立刻 drain 一次（见 main.py 的 _outbox_fast_path）：
    #    所以这里多半已经是 sent；worker 仍然是兜底（进程重启/失败重试）。两者都算对。
    assert rows[0].status in (OutboxStatus.PENDING.value, OutboxStatus.SENT.value), rows[0].status


def test_completing_a_delivery_enqueues_both_events(
    client, token_dispatcher, token_shipper, token_driver, users, db_session
):
    """送达那条链路（第二个切过来的生产者）：一次送达 → 两条事件，都在**同一个事务**里。

    `orders.delivered`（推给货主 + 派单员）与 `ledger.updated`（账本有更新）——
    以前它们是 commit 之后的两个 background task；现在跟着业务一起落发件箱，由 worker 发。
    """
    _clear(db_session)
    line = {"product_name_snapshot": "送达探针", "quantity": 1, "unit_price": "10.00", "line_total": "10.00"}
    created = client.post(
        "/api/v1/orders",
        headers=auth_headers(token_shipper),
        json={"lines": [line], "delivery_description": "送达地址", "address_detail": "送达地址"},
    )
    assert created.status_code == 201, created.text
    oid = int(created.json()["id"])
    hd = auth_headers(token_dispatcher)
    hdrv = auth_headers(token_driver)

    assert client.post(
        f"/api/v1/orders/{oid}/assign", json={"driver_id": users["driver"].id}, headers=hd
    ).status_code == 200
    assert client.post(f"/api/v1/orders/{oid}/driver-ack", headers=hdrv).status_code == 200
    done = client.post(
        f"/api/v1/orders/{oid}/complete",
        json={"delivery_photo_urls": ["/static/uploads/delivery/probe.jpg"]},
        headers=hdrv,
    )
    assert done.status_code == 200, done.text

    db_session.expire_all()
    events = {x.event_type: x for x in _rows(db_session)}
    # 接单那一步也走发件箱（本轮最后一批切过来的）：收件人是货主，顺带推派单员
    assert "orders.driver_acked" in events, list(events)
    assert events["orders.driver_acked"].payload_dict() == {
        "shipper_id": users["shipper"].id, "order_id": oid,
    }, events["orders.driver_acked"].payload_dict()
    assert "orders.delivered" in events, list(events)
    assert events["orders.delivered"].payload_dict() == {"order_id": oid}
    assert "ledger.updated" in events, list(events)
    assert events["ledger.updated"].payload_dict() == {"shipper_id": users["shipper"].id}
    # 同上：快速通道可能已经发掉了（pending 与 sent 都是"这条事件在正确的位置上"）
    assert all(
        x.status in (OutboxStatus.PENDING.value, OutboxStatus.SENT.value) for x in events.values()
    ), {k: v.status for k, v in events.items()}


def test_cancelling_an_order_enqueues_cancelled_and_pool_events(
    client, token_shipper, users, db_session
):
    """撤销那条链路（第三个切过来的生产者）：一次撤销 → 两条事件。

    一条 `orders.cancelled`（收件人 = 货主 + 司机，未派单时就只有货主）、一条 `orders.pending_pool_changed`
    （派单员的待派池变了）。⚠️ 原来调两次助手 → 派单员会收到**两次**池刷新，现在合成一条事件。
    """
    _clear(db_session)
    line = {"product_name_snapshot": "撤销探针", "quantity": 1, "unit_price": "10.00", "line_total": "10.00"}
    created = client.post(
        "/api/v1/orders",
        headers=auth_headers(token_shipper),
        json={"lines": [line], "delivery_description": "撤销地址", "address_detail": "撤销地址"},
    )
    assert created.status_code == 201, created.text
    oid = int(created.json()["id"])

    cancelled = client.post(f"/api/v1/orders/{oid}/cancel", headers=auth_headers(token_shipper))
    assert cancelled.status_code == 200, cancelled.text

    db_session.expire_all()
    events = {x.event_type: x.payload_dict() for x in _rows(db_session)}
    assert events.get("orders.cancelled") == {"user_ids": [users["shipper"].id], "order_id": oid}, events
    assert "orders.pending_pool_changed" in events, list(events)


def test_dispatcher_maps_the_payload_to_push_args(monkeypatch):
    """派发表把**负载**翻成实参：`ledger.updated` 的三个收件人由负载决定。

    账本路由那几处带 `dispatchers: True`（它们一直推三类人），送达那条链路只带货主
    （与它切过来之前逐字一致）—— 这条用例把两种形状都钉住，免得以后"统一一下"就把收件人改窄。
    """
    import asyncio

    from app.core.outbox import Event
    from app.main import _outbox_deliver

    calls: list[tuple] = []

    async def fake_ledger(shipper_id=None, *, driver_id=None, dispatchers=False):
        calls.append((shipper_id, driver_id, dispatchers))

    monkeypatch.setattr(push_events, "push_ledger_updated", fake_ledger)
    asyncio.run(_outbox_deliver(Event(
        id=1, event_type="ledger.updated",
        payload={"shipper_id": 7, "driver_id": 9, "dispatchers": True}, attempts=0,
    )))
    asyncio.run(_outbox_deliver(Event(
        id=2, event_type="ledger.updated", payload={"shipper_id": 7}, attempts=0,
    )))
    assert calls == [(7, 9, True), (7, None, False)], calls


def test_dispatcher_refuses_an_unregistered_event_type():
    """没登记的事件类型**必须抛错**（发件箱要治的就是"静默丢事件"）。"""
    import asyncio

    from app.core.outbox import Event
    from app.main import _outbox_deliver

    raised = False
    try:
        asyncio.run(_outbox_deliver(Event(id=1, event_type="nobody.handles.this", payload={}, attempts=0)))
    except RuntimeError as exc:
        raised = "没有登记处理器" in str(exc)
    assert raised, "没人处理的事件类型被静默放过了"


def test_deleting_a_ledger_entry_enqueues_the_refresh(client, token_dispatcher, users, db_session):
    """账本路由那几处（本轮切过来）：删一条流水 → 一条 `ledger.updated`，收件人含派单员。"""
    from datetime import date

    from app.models import Ledger
    from app.models.enums import LedgerSource

    _clear(db_session)
    row = Ledger(
        shipper_id=users["shipper"].id,
        entry_date=date(2026, 9, 25),
        product_name="发件箱账本探针",
        quantity=1,
        unit_price=Decimal("10.0000"),
        total=Decimal("10.0000"),
        source=LedgerSource.MANUAL,
    )
    db_session.add(row)
    db_session.commit()

    gone = client.delete(f"/api/v1/ledger/entries/{row.id}", headers=auth_headers(token_dispatcher))
    assert gone.status_code in (200, 204), gone.text

    db_session.expire_all()
    events = [x for x in _rows(db_session) if x.event_type == "ledger.updated"]
    assert len(events) == 1, [x.event_type for x in _rows(db_session)]
    # ⚠️ 负载里**不带** driver_id：那一格交给派发表按缺省处理（None = 只推货主与派单员）——
    #    JSON 里塞一堆 null 只会让"这条事件到底推给谁"更难读。
    assert events[0].payload_dict() == {
        "shipper_id": users["shipper"].id, "dispatchers": True,
    }, events[0].payload_dict()


def test_marking_a_notification_read_enqueues_the_unread_event(
    client, token_shipper, users, db_session
):
    """消息中心那几处（本轮切过来）：标记已读 → `notifications.unread_changed`。

    事件只带**用户编号**，处理器按编号现算未读数 —— 不带"未读数是多少"的快照，
    否则同一件事会有两个数（发件箱里那份 vs 消息中心里那份）。
    """
    from app.models import Notification

    _clear(db_session)
    n = Notification(
        recipient_id=users["shipper"].id,
        category="order",
        type="order.assigned",
        title="发件箱消息探针",
        content="",
    )
    db_session.add(n)
    db_session.commit()

    read = client.post(
        f"/api/v1/notifications/{n.id}/read", headers=auth_headers(token_shipper)
    )
    assert read.status_code == 200, read.text

    db_session.expire_all()
    events = [x for x in _rows(db_session) if x.event_type == "notifications.unread_changed"]
    assert len(events) == 1, [x.event_type for x in _rows(db_session)]
    assert events[0].payload_dict() == {"user_id": users["shipper"].id}, events[0].payload_dict()


def test_outbox_stats_counts_by_status(db_session):
    _clear(db_session)
    outbox.enqueue(db_session, "orders.assigned", {})
    outbox.enqueue(db_session, "orders.assigned", {})
    db_session.commit()
    assert outbox.outbox_stats(db_session)["pending"] == 2
    outbox.dispatch_sync(db_session, lambda _ev: None)
    stats = outbox.outbox_stats(db_session)
    assert stats["sent"] == 2 and stats["pending"] == 0, stats

