"""软删/恢复在途单的**实时推送** + 软删单详情页的「人话」文案（测试台账 TA-05 / TA-06 → BUG-0027）。

## 这一批要钉住的（每条都有「不钉住会怎样」）

| 判据 | 不钉住会怎样 |
|---|---|
| 软删一张单要入队 `orders.deleted` | 司机端「进行中」列表在推送前毫无变化、手动刷新后被删的单**静默消失**，全程没有一句话（TA-05：`DELETE /orders/{id}` 里一个 `outbox.enqueue` 都没有） |
| 恢复要入队 `orders.restored` | 恢复后**静默回归**：司机不知道这单又回来了，也不知道是哪一单 |
| 派发表把这两条翻成对**当事人**的推送 | 没人处理的事件会进 failed 队列（`/metrics` 的 `sorders_outbox_failed` 涨），而司机端仍然一条提示都没有 |
| 软删单的详情 404 要对**当事人**说人话 | 司机点开旧卡片只有「订单不存在」+「重试」——不说是谁删的、也不说能不能找回（TA-06） |
| ⛔ 非当事人仍然只说「订单不存在」 | 文案差异会把"有一张我看不到的已删除单"泄露出去（`orders_common.py:82-98` 的口径：读侧对所有非派单员一视同仁） |
| 收件人 = 这一单的**司机 + 货主** | 少一个就是"另一边静默"；多一个就是把别人的单抖给不相干的人 |

⚠️ 状态码一律保持 **404**（不改 410）：写路径的 `_order_not_deleted_or_404` 与既有用例
（`test_audit_round13_guards.py`、`test_write_gate_cancel_and_pay.py`）都按 404 钉着。
"""
from __future__ import annotations

import asyncio

from sqlalchemy import select

from app.models import Notification, OutboxEvent, OutboxStatus
from app.services import message_center, push_events
from tests.conftest import auth_headers

LINE = {
    "product_name_snapshot": "软删推送探针",
    "quantity": 1,
    "unit_price": "10.00",
    "line_total": "10.00",
}


def _clear(db) -> None:
    """清掉发件箱（只在**本表**内清）。"""
    db.query(OutboxEvent).delete(synchronize_session=False)
    db.commit()


def _rows(db) -> list[OutboxEvent]:
    return list(db.scalars(select(OutboxEvent).order_by(OutboxEvent.id)))


def _mk_order(client, token_shipper, name: str) -> int:
    created = client.post(
        "/api/v1/orders",
        headers=auth_headers(token_shipper),
        json={
            "contact_dongjia_name": "收货人甲",
            "lines": [LINE],
            "delivery_description": name,
            "address_detail": name,
        },
    )
    assert created.status_code == 201, created.text
    return int(created.json()["id"])


def _assign(client, token_dispatcher, oid: int, driver_id: int) -> None:
    assigned = client.post(
        f"/api/v1/orders/{oid}/assign",
        json={"driver_id": driver_id},
        headers=auth_headers(token_dispatcher),
    )
    assert assigned.status_code == 200, assigned.text


def test_deleting_an_in_flight_order_enqueues_the_deleted_event(
    client, token_shipper, token_dispatcher, users, db_session
):
    """**软删那条链路**：一次 DELETE → 一条 `orders.deleted`，与业务写在**同一个事务**里。

    收件人是这一单的两个当事人（司机 + 货主）——负载里只带编号，谁收由派发表决定。
    """
    _clear(db_session)
    oid = _mk_order(client, token_shipper, "软删在途单")
    _assign(client, token_dispatcher, oid, users["driver"].id)

    gone = client.delete(f"/api/v1/orders/{oid}", headers=auth_headers(token_dispatcher))
    assert gone.status_code == 204, gone.text

    db_session.expire_all()
    rows = [x for x in _rows(db_session) if x.event_type == "orders.deleted"]
    assert len(rows) == 1, [x.event_type for x in _rows(db_session)]
    assert rows[0].payload_dict() == {
        "order_id": oid,
        "user_ids": [users["driver"].id, users["shipper"].id],
    }, rows[0].payload_dict()
    # 响应发出后有一条快速通道会立刻 drain（main.py 的 _outbox_fast_path）：pending / sent 都算对
    assert rows[0].status in (OutboxStatus.PENDING.value, OutboxStatus.SENT.value), rows[0].status


def test_restoring_an_order_enqueues_the_restored_event(
    client, token_shipper, token_dispatcher, users, db_session
):
    """**恢复那条链路**：删除（丢掉那条）之后 restore → 一条 `orders.restored`。"""
    oid = _mk_order(client, token_shipper, "软删恢复单")
    _assign(client, token_dispatcher, oid, users["driver"].id)
    assert client.delete(
        f"/api/v1/orders/{oid}", headers=auth_headers(token_dispatcher)
    ).status_code == 204
    _clear(db_session)

    back = client.post(f"/api/v1/orders/{oid}/restore", headers=auth_headers(token_dispatcher))
    assert back.status_code == 200, back.text

    db_session.expire_all()
    rows = [x for x in _rows(db_session) if x.event_type == "orders.restored"]
    assert len(rows) == 1, [x.event_type for x in _rows(db_session)]
    assert rows[0].payload_dict() == {
        "order_id": oid,
        "user_ids": [users["driver"].id, users["shipper"].id],
    }, rows[0].payload_dict()
    assert back.json()["id"] == oid


def test_dispatcher_maps_the_soft_delete_events_to_push_args(monkeypatch):
    """派发表把**负载**翻成实参：两条新事件的收件人来自 `user_ids`。

    ⛔ 这一条同时也是「有人入队、有人处理」的活证据：没登记的事件类型会抛
    `RuntimeError("发件箱没有登记处理器：…")`（`_tools/qa/_check_outbox.py` 第 8 条扫的就是这件事）。
    """
    from app.core.outbox import Event
    from app.main import _outbox_deliver

    calls: list[tuple] = []

    async def fake_deleted(recipients, order_id):
        calls.append(("deleted", list(recipients), order_id))

    async def fake_restored(recipients, order_id):
        calls.append(("restored", list(recipients), order_id))

    # raising=False：实现之前这两个名字还不存在，红法应当是下面的 RuntimeError（而不是 AttributeError）
    monkeypatch.setattr(push_events, "push_order_deleted", fake_deleted, raising=False)
    monkeypatch.setattr(push_events, "push_order_restored", fake_restored, raising=False)

    asyncio.run(_outbox_deliver(Event(
        id=1, event_type="orders.deleted", payload={"order_id": 12, "user_ids": [3, 4]}, attempts=0,
    )))
    asyncio.run(_outbox_deliver(Event(
        id=2, event_type="orders.restored", payload={"order_id": 12, "user_ids": [3, 4]}, attempts=0,
    )))

    assert calls == [("deleted", [3, 4], 12), ("restored", [3, 4], 12)], calls


def test_driver_detail_of_a_deleted_in_flight_order_names_the_dispatcher(
    client, token_shipper, token_dispatcher, token_driver, users, db_session
):
    """TA-06：软删的**在途**单，当事人点开详情要看得懂。

    状态码仍然是 404（不改），但文案必须说清：谁删的、还能不能找回 —— 而不是「订单不存在」。
    在途单只有派单员能删（货主那一支要求状态是已撤销），所以这一格说「派单员删除」是**准的**。
    """
    oid = _mk_order(client, token_shipper, "软删详情单")
    _assign(client, token_dispatcher, oid, users["driver"].id)
    assert client.delete(
        f"/api/v1/orders/{oid}", headers=auth_headers(token_dispatcher)
    ).status_code == 204

    seen = client.get(f"/api/v1/orders/{oid}", headers=auth_headers(token_driver))
    assert seen.status_code == 404, seen.text
    detail = seen.json()["detail"]
    assert detail != "订单不存在", "司机点开旧卡片仍然只看到「订单不存在」—— 那正是 TA-06"
    assert "派单员删除" in detail, detail
    assert "回收站" in detail, detail

    # 货主是另一个当事人：同一句话也该给他（他那一页同样会少一行）
    seen_shipper = client.get(f"/api/v1/orders/{oid}", headers=auth_headers(token_shipper))
    assert seen_shipper.status_code == 404, seen_shipper.text
    assert "订单已被" in seen_shipper.json()["detail"], seen_shipper.json()


def test_a_driver_who_is_not_on_the_order_still_gets_plain_not_found(
    client, token_shipper, token_dispatcher, token_driver, users, db_session
):
    """⛔ 反向对照：**没有司机**的一张待派单被删 → 别对司机说"这张单被派单员删了"。

    读侧对所有非派单员本来一视同仁（`orders_common.py:82-98` 写了理由：状态码/文案的差异会
    泄露"有一张你看不到的已删除单"）。这条钉住"人话文案只给当事人"。
    """
    oid = _mk_order(client, token_shipper, "未派单被删")
    assert client.delete(
        f"/api/v1/orders/{oid}", headers=auth_headers(token_dispatcher)
    ).status_code == 204

    seen = client.get(f"/api/v1/orders/{oid}", headers=auth_headers(token_driver))
    assert seen.status_code == 404, seen.text
    assert seen.json()["detail"] == "订单不存在", seen.json()


def test_the_deleted_notice_reaches_both_parties(monkeypatch, client, token_shipper, users, db_session):
    """**不许静默**：站内信 + 实时信号，两个当事人各一份。

    站内信是"回过头还能查到"的那一份；实时信号（`order.deleted`）是让司机端列表当场刷新的那一份。
    """
    oid = _mk_order(client, token_shipper, "软删推送内容")
    sent: list[tuple[int, str]] = []

    async def fake_realtime(user_id: int, payload: dict) -> None:
        sent.append((int(user_id), str(payload.get("type"))))

    async def fake_notification(_n) -> None:
        return None

    monkeypatch.setattr(message_center, "emit_realtime", fake_realtime)
    monkeypatch.setattr(message_center, "emit_notification", fake_notification)

    asyncio.run(message_center.publish_order_deleted(
        db_session, [users["driver"].id, users["shipper"].id], oid
    ))

    assert {uid for uid, _t in sent} == {users["driver"].id, users["shipper"].id}, sent
    assert {t for _uid, t in sent} == {"order.deleted"}, sent

    rows = list(db_session.scalars(select(Notification).where(Notification.type == "order.deleted")))
    assert {n.recipient_id for n in rows} == {users["driver"].id, users["shipper"].id}, [
        (n.recipient_id, n.type) for n in rows
    ]
    body = rows[0].content or ""
    assert "已被派单员删除" in body and "回收站" in body, body
