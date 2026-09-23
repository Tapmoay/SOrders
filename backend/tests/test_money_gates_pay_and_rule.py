"""「已经收过款的单」与「还挂着人的规则」：两条钱路上的闸门。

## 一、现场收款确认（2026-09-24 第 20 轮 C1-2 + D5-②）
`POST /orders/{id}/pay` 只写 `payment_method='cash' / paid=True / arrears_unit_id=None`
—— **不写收款单、不写现金流水**。而它原来**没有**"已收过款"这道门
（同文件的「改回挂账」`/charge` 有）。于是"已经核销过一部分"的单上再点一次
（`paid=True`、`payment_method` 仍是 `arrears`、`money_map` 算出已收 100 还欠 700）：

- 界面 / AI 卡片说「收款：¥800」→ 点确认 → 「已完成」；
- 库里：**一笔新进账都没有**，而 `arrears_unit_id` 被清空 → 这单从挂账单位账上消失；
- 挂账名单按 `paid=True` 把它排除 → **那 700 元没人再追**。

## 二、删计费规则（第 20 轮 C6-2）
闸门原来按 `role == DRIVER` 数"还有几个司机挂着"，而 `PATCH /users` 改角色**不会**清
`driver_rule_id` → 把司机改成货主就能把规则删掉，再改回司机 → 他照旧按这份**已删的规则**算钱
（`order_pay` 从订单快照读，规则列表里却看不见它）。判据必须按「谁还指着它」数。
"""

from __future__ import annotations

import uuid
from datetime import date

from tests.conftest import auth_headers


def _delivered_order(client, h_disp, h_driver, users, *, price: str = "800") -> int:
    r = client.post(
        "/api/v1/products",
        json={"name": "收款闸门探针货", "default_unit_price": price, "cost_price": "1", "stock": 10},
        headers=h_disp,
    )
    assert r.status_code in (200, 201), r.text
    pid = r.json()["id"]
    r = client.post(
        "/api/v1/orders",
        json={
            "shipper_id": users["shipper"].id,
            "lines": [
                {
                    "product_id": pid,
                    "product_name_snapshot": "收款闸门探针货",
                    "quantity": 1,
                    "unit_price": price,
                    "line_total": price,
                }
            ],
            "address_detail": "收款闸门探针地址",
        },
        headers=h_disp,
    )
    assert r.status_code == 201, r.text
    oid = int(r.json()["id"])
    assert client.post(
        f"/api/v1/orders/{oid}/assign",
        json={"driver_id": users["driver"].id, "freight_fee": "50"},
        headers=h_disp,
    ).status_code == 200
    assert client.post(f"/api/v1/orders/{oid}/driver-ack", headers=h_driver).status_code == 200
    assert client.post(
        f"/api/v1/orders/{oid}/complete",
        json={"delivery_photo_urls": ["/static/uploads/delivery/probe-pay-gate.jpg"]},
        headers=h_driver,
    ).status_code == 200
    return oid


def test_已经收过款的单不许再点现场收款(client, db_session, users, token_dispatcher, token_driver):
    """**这条是本轮那个"钱没人追"的确证**：`/pay` 必须有"已收过款"这道门。"""
    from app.models import Customer, Order

    h = auth_headers(token_dispatcher)
    hd = auth_headers(token_driver)
    oid = _delivered_order(client, h, hd, users)

    db_session.expire_all()
    cust = db_session.query(Customer).filter_by(user_id=users["shipper"].id).first()
    if cust is None:
        cust = Customer(name="收款闸门探针货主", user_id=users["shipper"].id, kind="registered")
        db_session.add(cust)
        db_session.commit()
    r = client.post(
        "/api/v1/ledger/receipts",
        json={
            "customer_id": int(cust.id),
            "amount": "800",          # 与 `_delivered_order(price="800")` 那张单的行小计一致
            "method": "cash",
            "received_at": date.today().isoformat(),
            "settle_mode": "itemized",
            "order_ids": [oid],
        },
        headers=h,
    )
    assert r.status_code == 200, r.text
    db_session.expire_all()
    assert db_session.get(Order, oid).paid is True, "前提不成立：核销之后这张单应当是已收"

    again = client.post(f"/api/v1/orders/{oid}/pay", headers=h)
    assert again.status_code == 400, (
        "已经收过款的单又被「现场收款确认」了一次（HTTP "
        f"{again.status_code}）—— 这条路径不写收款单也不写现金流水，只会翻标记并清空挂账单位，"
        "于是那笔钱在挂账名单上消失、却没有任何进账"
    )
    assert "已经收过款" in again.json()["detail"], again.json().get("detail")


def test_挂着人的规则改角色也不许删(client, db_session, users, token_dispatcher):
    """改一次角色就能删掉「还挂着司机」的规则（C6-2）—— 闸门要按 `driver_rule_id` 数。"""
    h = auth_headers(token_dispatcher)
    r = client.post(
        "/api/v1/driver-billing-rules",
        json={"name": f"删规则闸门探针-{uuid.uuid4().hex[:6]}", "piece_amount": "78"},
        headers=h,
    )
    assert r.status_code in (200, 201), r.text
    rid = r.json()["id"]
    assert client.post(
        "/api/v1/driver-billing-rules/attach",
        json={"driver_id": users["driver"].id, "rule_id": rid},
        headers=h,
    ).status_code == 200

    # 把司机改成货主（这一步**不会**清掉 driver_rule_id）
    r = client.patch(f"/api/v1/users/{users['driver'].id}", json={"role": "shipper"}, headers=h)
    if r.status_code != 200:
        import pytest

        pytest.skip(f"这条用例的前提是能改角色：{r.status_code} {r.text[:120]}")

    d = client.delete(f"/api/v1/driver-billing-rules/{rid}", headers=h)
    assert d.status_code == 400, (
        f"把司机改成货主之后规则被删掉了（HTTP {d.status_code}）—— "
        "改回司机他就会继续按这份**已删的规则**算钱，而规则列表里看不见它"
    )
