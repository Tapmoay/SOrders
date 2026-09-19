"""并发重复提交的**钱**不变式：同一张单无论被点几次，只许生成一条司机账单。

## 现场（2026-09-18 实测复现过，不是假想）
两个并发的 `complete` 都读到「已接单」→ 各自往下走 → 订单 620 拿到**两条 60 元账单**（合计 120）。
根因：SQLite **不支持 `SELECT … FOR UPDATE`**，SQLAlchemy 直接忽略它，
所以"只靠行锁"的保护**在本地是空的**（MySQL 上行锁能挡，但"只在生产有效"的保护本地测不出来）。

修法：状态跃迁改成**条件 UPDATE 占位**（`WHERE status='ACCEPTED'`）——
改到 1 行的请求继续，改到 0 行的立刻出局。这条判据在 SQLite / MySQL 上都成立。

## 为什么这里不写"多线程打同一个 app"
试过了：pytest 的 `client` fixture 给**所有请求共用同一个 Session**（`override_get_db` yield 同一个
session），多线程下 SQLite 连接直接 `InterfaceError: bad parameter or other API misuse`——
那是测试脚手架的形态，不是被测代码的问题（生产每个请求一个 session）。
所以这一层拆成两条，各测各能测的：
1. **机制**：条件 UPDATE 在本机数据库上确实是"只有一个赢家"（`test_conditional_claim_*`）；
2. **端到端**：串行重复提交只产生一条账单（`test_double_complete_*`）。
真正"两个请求抢跑"的端到端复现与验证，在 `_tools/fuzz/_fuzz_replay.py`（打真后端、真并发）：
修复前它会报「并发送达产生了多张司机账单」，修复后连跑 5 轮都是"只产生一张 + 一个请求 4xx"。
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import text, update
from starlette.testclient import TestClient

from app.models import Order
from app.models.enums import OrderStatus
from tests.conftest import auth_headers


def test_conditional_claim_is_atomic_on_this_db(db_session, users) -> None:
    """条件 UPDATE 占位：第一次 1 行、第二次 0 行——这正是并发时"只让一个人赢"的依据。"""
    order = Order(
        order_no="CAS-TEST-1",
        status=OrderStatus.PENDING_DISPATCH,
        shipper_id=users["shipper"].id,
        order_date=date.today(),
    )
    db_session.add(order)
    db_session.commit()

    def claim() -> int:
        res = db_session.execute(
            update(Order)
            .where(Order.id == order.id, Order.status == OrderStatus.PENDING_DISPATCH)
            .values(status=OrderStatus.DISPATCHED)
        )
        db_session.commit()
        return res.rowcount

    assert claim() == 1, "第一次占位必须成功"
    assert claim() == 0, "第二次占位必须失败（否则并发下两个请求都会往下走）"


def _accepted_order(client: TestClient, db_session, token_disp: str, token_drv: str,
                    users: dict) -> int:
    # 司机必须是**按单计费**才会有 PIECE 账单（工资制司机送达本来就不产生按单应付）
    users["driver"].billing_mode = "piece"
    db_session.commit()
    r = client.post(
        "/api/v1/orders",
        json={
            "lines": [{"product_name_snapshot": "重复送达货", "quantity": 1, "unit_price": "50"}],
            "shipper_id": users["shipper"].id,
        },
        headers=auth_headers(token_disp),
    )
    assert r.status_code == 201, r.text
    oid = r.json()["id"]
    a = client.post(
        f"/api/v1/orders/{oid}/assign",
        json={"driver_id": users["driver"].id, "freight_fee": "60.00", "collect_cash": True},
        headers=auth_headers(token_disp),
    )
    assert a.status_code in (200, 201, 204), a.text
    k = client.post(f"/api/v1/orders/{oid}/driver-ack", headers=auth_headers(token_drv))
    assert k.status_code in (200, 201, 204), k.text
    return oid


def test_double_complete_sequential_creates_one_bill(
    client: TestClient, db_session, token_dispatcher: str, token_driver: str, users: dict
) -> None:
    oid = _accepted_order(client, db_session, token_dispatcher, token_driver, users)
    body = {"payment": "cash", "delivery_photo_urls": ["/static/uploads/delivery/t.jpg"]}

    first = client.post(f"/api/v1/orders/{oid}/complete", json=body, headers=auth_headers(token_driver))
    assert first.status_code in (200, 201, 204), first.text
    second = client.post(f"/api/v1/orders/{oid}/complete", json=body, headers=auth_headers(token_driver))
    assert second.status_code == 400, f"重复送达必须被挡住，实际 {second.status_code}：{second.text[:200]}"

    bills = client.get(f"/api/v1/driver-bills?driver_id={users['driver'].id}",
                       headers=auth_headers(token_dispatcher))
    assert bills.status_code == 200, bills.text
    rows = [b for b in bills.json() if b.get("order_id") == oid and b.get("bill_type") == "piece"]
    assert len(rows) == 1, f"同一张单生成了 {len(rows)} 条账单（钱付两次）：{rows}"

    detail = client.get(f"/api/v1/orders/{oid}", headers=auth_headers(token_dispatcher))
    # 状态枚举出参是**大写**（OrderStatus.DELIVERED），别按小写断言
    assert detail.json()["status"] == "DELIVERED", detail.text


# ---------------------------------------------------------------- 逐单核销的同一个占位
#
# 2026-09-18 又在本机实测复现了一次同族缺陷（探针 `_probe_core_flows.py` 的并发组）：
# 两个并发的逐单核销请求**都返回 200**，同一张单落了两条收款记录、两条现金流水
# （库里实测：order 656 有收款单 47/48 各 60 元）。根因与并发送达一模一样
# —— 逐单核销也只有 `with_for_update()`（SQLite 忽略），没有原子占位。
# 修法也照抄：`UPDATE orders SET paid=1 WHERE id=? AND paid=0`，改到行的人才能继续。


def test_paid_claim_is_atomic_on_this_db(db_session, users) -> None:
    """`paid=false → true` 的条件占位：第一次 1 行、第二次 0 行。"""
    order = Order(
        order_no="CAS-TEST-PAID-1",
        status=OrderStatus.PENDING_DISPATCH,
        shipper_id=users["shipper"].id,
        order_date=date.today(),
        paid=False,
    )
    db_session.add(order)
    db_session.commit()

    def claim() -> int:
        res = db_session.execute(
            update(Order).where(Order.id == order.id, Order.paid.is_(False)).values(paid=True)
        )
        db_session.commit()
        return res.rowcount

    assert claim() == 1, "第一次占位必须成功"
    assert claim() == 0, "第二次占位必须失败（否则并发下同一张单会被核销两次）"


def test_double_itemized_receipt_sequential_records_money_once(
    client: TestClient, db_session, token_dispatcher: str, token_shipper: str, users: dict
) -> None:
    """串行重复核销：第二次必须 400，且那笔钱只有**一条**收款记录（占位生效）。"""
    r = client.post(
        "/api/v1/orders",
        json={"lines": [{"product_name_snapshot": "重复核销货", "quantity": 1, "unit_price": "70"}],
              "shipper_id": users["shipper"].id},
        headers=auth_headers(token_dispatcher),
    )
    assert r.status_code == 201, r.text
    oid = int(r.json()["id"])

    cust = client.post("/api/v1/customers",
                       json={"name": "重复核销客户", "user_id": users["shipper"].id},
                       headers=auth_headers(token_dispatcher))
    assert cust.status_code in (200, 201), cust.text
    cid = int(cust.json()["id"])

    body = {"customer_id": cid, "amount": "70.00", "method": "cash", "settle_mode": "itemized",
            "order_ids": [oid], "received_at": date.today().isoformat()}
    first = client.post("/api/v1/ledger/receipts", json=body, headers=auth_headers(token_dispatcher))
    assert first.status_code in (200, 201), first.text
    second = client.post("/api/v1/ledger/receipts", json=body, headers=auth_headers(token_dispatcher))
    assert second.status_code == 400, f"重复核销必须被挡住，实际 {second.status_code}：{second.text[:200]}"

    rows = client.get(f"/api/v1/ledger/receipts?customer_id={cid}",
                      headers=auth_headers(token_dispatcher))
    assert rows.status_code == 200, rows.text
    hits = [x for x in rows.json() if oid in (x.get("order_ids") or [])]
    assert len(hits) == 1, f"同一张单落了 {len(hits)} 条收款记录（钱多记）：{hits}"
