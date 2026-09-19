"""状态跃迁的**条件 UPDATE 占位**（CAS）：撤销 / 撤回 / 接单（2026-09-19 审计的缺陷 C1）。

## 为什么这三条也必须占位
同一批状态跃迁里，`assign_driver`（派单）与 `complete_delivery`（送达）早就有 CAS，
而这三条一直是"读状态 → 判断 → 无条件赋值"。它们的并发对象是**彼此**：

- **撤销 × 接单**：撤销把行写成 CANCELLED（并释放了库存预占），接单又把行覆盖回 ACCEPTED
  → 单子复活，但预占没了 → 送达时 `auto_stock_commit` 查不到 RESERVED 行 → **库存永远不扣**。
- **撤回 × 送达**：撤回的无条件赋值会把**已送达**的单覆盖回「待派单 + 无司机」
  → 同一张单能被再派一次、库存与货损各记两次（唯一索引只挡得住账单那一处）。
- **反复点**：司机手滑点两下接单、派单员两台设备同时点撤销，都是现实里的常态。

本机 SQLite 上 `with_for_update()` 是被忽略的（生产 MySQL 才有行锁），所以判据必须落在
"改到行的人才能继续"这个形状上 —— 下面既测**串行拒绝**，也直接测**条件 UPDATE 的原子性**。
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import update

from app.models import Order
from app.models.enums import OrderStatus
from tests.conftest import auth_headers


def _mk_order(client, token_dispatcher, shipper_id: int) -> int:
    r = client.post(
        "/api/v1/orders",
        json={
            "shipper_id": shipper_id,
            "lines": [{"product_name_snapshot": "状态跃迁探针", "quantity": 1, "unit_price": "10"}],
            "address_detail": "状态跃迁探针地址",
        },
        headers=auth_headers(token_dispatcher),
    )
    assert r.status_code == 201, r.text
    return int(r.json()["id"])


def test_ack_after_cancel_is_refused_and_does_not_resurrect(
    client, db_session, users, token_dispatcher, token_driver
):
    """已撤销的单不能再被接单复活（复活会导致库存预占已释放、永远不扣）。"""
    h = auth_headers(token_dispatcher)
    oid = _mk_order(client, token_dispatcher, users["shipper"].id)
    assert client.post(
        f"/api/v1/orders/{oid}/assign",
        json={"driver_id": users["driver"].id, "freight_fee": "20"},
        headers=h,
    ).status_code == 200

    assert client.post(f"/api/v1/orders/{oid}/cancel", headers=h).status_code == 200

    r = client.post(f"/api/v1/orders/{oid}/driver-ack", headers=auth_headers(token_driver))
    assert r.status_code == 400, r.text

    db_session.expire_all()
    fresh = db_session.get(Order, oid)
    assert fresh.status == OrderStatus.CANCELLED, "被拒的接单不许改动状态"
    assert fresh.driver_acknowledged_at is None


def test_cancel_after_ack_is_refused(client, db_session, users, token_dispatcher, token_driver):
    """已接单（在途）的单不能被这条撤销路径直接撤销（该走撤回）。"""
    h = auth_headers(token_dispatcher)
    oid = _mk_order(client, token_dispatcher, users["shipper"].id)
    client.post(f"/api/v1/orders/{oid}/assign",
                json={"driver_id": users["driver"].id, "freight_fee": "20"}, headers=h)
    assert client.post(f"/api/v1/orders/{oid}/driver-ack",
                       headers=auth_headers(token_driver)).status_code == 200

    r = client.post(f"/api/v1/orders/{oid}/cancel", headers=h)
    assert r.status_code == 400, r.text
    db_session.expire_all()
    assert db_session.get(Order, oid).status == OrderStatus.ACCEPTED


def test_cancel_after_complete_is_refused(client, db_session, users, token_dispatcher, token_driver):
    """已送达的单不能被打回（否则同一批货会被扣两次、货损重复记账）。"""
    h = auth_headers(token_dispatcher)
    hd = auth_headers(token_driver)
    oid = _mk_order(client, token_dispatcher, users["shipper"].id)
    client.post(f"/api/v1/orders/{oid}/assign",
                json={"driver_id": users["driver"].id, "freight_fee": "20"}, headers=h)
    client.post(f"/api/v1/orders/{oid}/driver-ack", headers=hd)
    assert client.post(f"/api/v1/orders/{oid}/complete",
                       json={"delivery_photo_urls": ["/static/uploads/delivery/cas.jpg"]},
                       headers=hd).status_code == 200

    assert client.post(f"/api/v1/orders/{oid}/recall", json={"reason": "探针"}, headers=h).status_code == 400
    assert client.post(f"/api/v1/orders/{oid}/cancel", headers=h).status_code == 400
    db_session.expire_all()
    assert db_session.get(Order, oid).status == OrderStatus.DELIVERED


def test_conditional_claim_is_atomic_for_cancel_transition(db_session, users) -> None:
    """`PENDING/DISPATCHED → CANCELLED` 的条件占位：第一次 1 行、第二次 0 行。

    这条直接钉住 CAS 的形状（与 `test_conditional_claim_is_atomic_on_this_db` 同源）：
    如果哪天有人把它改回"读状态再赋值"，第二次占位就会成功 → 撤销会被执行两次
    （预占释放两次、日志两条），而这里会立刻红。
    """
    order = Order(
        order_no="CAS-TEST-CANCEL-1",
        status=OrderStatus.DISPATCHED,
        shipper_id=users["shipper"].id,
        order_date=date.today(),
    )
    db_session.add(order)
    db_session.commit()

    allowed = (OrderStatus.PENDING_DISPATCH, OrderStatus.DISPATCHED)

    def claim() -> int:
        res = db_session.execute(
            update(Order)
            .where(Order.id == order.id, Order.status.in_(allowed))
            .values(status=OrderStatus.CANCELLED)
        )
        db_session.commit()
        return res.rowcount

    assert claim() == 1, "第一次占位必须成功"
    assert claim() == 0, "第二次占位必须失败（否则并发下同一张单会被撤销两次）"
