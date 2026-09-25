"""R3-04-A：`request_id` / `command_id` / `event_id` 是**三个**概念，不许混成一个。

指南的原话：

```text
request_id  →  command_id  →  OrderCompleted  →  event_id
一个 HTTP 请求可以触发：多个 command / 多个 event
所以不能假设：1 request = 1 event
```

这一组用例把三件事钉在真实接口上（不是读源码形状）：

1. 一次请求里的审计行，`request_id` 与 `command_id` **都非空且不相等**；
2. 一次**批量**请求 → **多个**不同的 `command_id`，但它们共用同一个 `request_id`；
3. 一次命令 → **多条**事件（发件箱），所以 `command_id` 与 `event_id` 也不是一对一。
"""
from __future__ import annotations

from sqlalchemy import select

from app.models.enums import OrderStatus
from app.models.operation_log import OperationLog
from app.models.order import Order
from app.models.outbox import OutboxEvent
from tests.conftest import auth_headers


def _mk_order(client, h) -> dict:
    r = client.post('/api/v1/orders', json={
        'shipper_id': 2,
        'lines': [{'product_name_snapshot': '探针货', 'quantity': 1,
                   'unit_price': '100', 'line_total': '100'}],
        'address_detail': '追踪探针路 1 号',
        'freight_fee': '1000',
    }, headers=h)
    assert r.status_code in (200, 201), r.text
    return r.json()


def test_审计行上_request_id_与_command_id_都非空且不相等(client, token_dispatcher, db_session):
    h = auth_headers(token_dispatcher)
    o = _mk_order(client, h)

    rows = list(db_session.scalars(
        select(OperationLog).where(OperationLog.order_id == o['id']).order_by(OperationLog.id)
    ))
    assert rows, '建单没有留下审计行 —— 那条断言本身就没意义了'
    for row in rows:
        assert row.request_id, '审计行没有 request_id'
        assert row.command_id, '审计行没有 command_id（R3-04-A 的中间那一层）'
        assert row.request_id != row.command_id, '两个 id 相等说明它们被当成同一个东西了'
        # 形如 order.create#3f2a1c9d —— 带命令名，排障时一眼看得出是哪条命令
        assert row.command_id.startswith('order.create#'), row.command_id


def test_一次批量请求产生多个_command_id_但只有一个_request_id(
    client, token_dispatcher, db_session, users
):
    h = auth_headers(token_dispatcher)
    a = _mk_order(client, h)
    b = _mk_order(client, h)
    driver_id = users['driver'].id

    r = client.post('/api/v1/orders/batch-assign',
                    json={'order_ids': [a['id'], b['id']], 'driver_id': driver_id}, headers=h)
    assert r.status_code == 200, r.text
    assert all(item['success'] for item in r.json()['results']), r.text

    # ⛔ 必须按**这两张单**过滤：整个用例会话共用一个库，别处（别的用例、fixture）也会写 ORDER_DISPATCH ——
    #    第一版没过滤，单跑通过、**整轮跑就红**（捞到了别的请求的审计行，request_id 自然不止一个）。
    #    这正是本仓库反复栽的那一类：判据被别处的数据满足/污染。
    rows = list(db_session.scalars(
        select(OperationLog).where(
            OperationLog.action == 'ORDER_DISPATCH',
            OperationLog.order_id.in_([a['id'], b['id']]),
        )
    ))
    ids = [row.command_id for row in rows if row.command_id]
    assert len(ids) >= 2, '两张单各派一次，至少两条命令'
    assert len(set(ids)) == len(ids), '两次派单的 command_id 不该相同（那就是 1 request = 1 command 了）'
    assert all(i.startswith('order.assign#') for i in ids), ids
    rids = {row.request_id for row in rows}
    assert len(rids) == 1, '同一次 HTTP 请求里所有审计行应当共用同一个 request_id'
    assert None not in rids


def test_一条命令可以产生多条事件_command_id_与_event_id_不是一对一(
    client, token_dispatcher, db_session
):
    h = auth_headers(token_dispatcher)

    # ⛔ 口径说清楚（第一版在这里判错过）：建单这条链路入队的是**两条性质不同**的事件 ——
    #    · `orders.created`：属于这张单（`aggregate_id` = 单号）；
    #    · `orders.pending_pool_changed`：**全局信号**，payload 是空的 `{}`，没有聚合根
    #      （`core/outbox.py` 的 NO_AGGREGATE 例外，写明了理由与退出条件）。
    #    所以「这条命令产生了几条事件」不能只按 aggregate_id 数 —— 那会漏掉第二条，
    #    把「1 命令 → N 事件」误判成不成立。这里用**请求前后的入队差值**数，两条都算得上。
    before = len(list(db_session.scalars(select(OutboxEvent))))
    o = _mk_order(client, h)
    after = list(db_session.scalars(select(OutboxEvent)))
    assert len(after) - before >= 2, (
        '建单这条命令预期至少入队两条事件（created + 池变化），实际 ' + str(len(after) - before)
    )
    types = {e.event_type for e in after}
    assert {'orders.created', 'orders.pending_pool_changed'} <= types, types
    # 每条事件有**自己的** id：命令与事件不是一对一
    assert len({e.id for e in after}) == len(after)
    mine = [e for e in after if e.aggregate_id == str(o['id'])]
    assert mine and mine[0].event_type == 'orders.created', 'orders.created 应当挂在单号上'
    # 而订单状态也确实是派单中（这条链路真的走通了，不是空断言）
    order = db_session.get(Order, o['id'])
    assert order is not None and order.status == OrderStatus.PENDING_DISPATCH.value

