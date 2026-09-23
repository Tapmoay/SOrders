"""「挂账单位」这根指向必须与"钱收没收到"一致（2026-09-23 第 7 轮）。

## 现场（确定性复现）

`orders.paid` / `payment_method` / `arrears_unit_id` 这一组字段有**三个写入点**：
`_apply_complete_payment`（司机送达）、`pay_order`（现场收款确认）、`charge_order`（挂账）。
三者里只有 `pay_order` 会顺手清掉挂账指向，送达那条路一直没清。于是这条顺序：

1. 派单员在订单详情点「挂账」→ `paid=False, payment_method=arrears, arrears_unit_id=1`；
2. 司机按**收取现金**提交送达（这一单派单时勾了「收取现金」）→ 实测落成
   `paid=True / payment_method=cash / arrears_unit_id=1 / arrears_unit_name='观察挂账单位'`。

一个自相矛盾的单：**钱已经收到手了，却还指着某某挂账单位**。

## 真实后果（不是"数据不干净"而已）

`arrears.py::delete_unit` 数的是"所有 `arrears_unit_id` 指向它的订单"（**不看 paid**），
于是那个单位**永远删不掉**，而拦人的那句「该单位名下已有 1 笔挂账订单，无法删除」
说的是一笔**早就收了现金**的单 —— 界面上又没有"改挂账单位"的入口，用户照这句话去处理
也解不开（死结）。

## 口径

- 送达时**收到钱**（`paid=True`）→ 清掉挂账指向（与 `pay_order` 同源）；没收到钱（挂账）
  → 保持指向不动（派单员已经指定了归哪个单位，那是有效信息）。
- `delete_unit` 的判据回到它本来的意思：**还挂着账（`paid=False`）的订单才拦**；
  只是历史指向的（钱已收）不拦，但要把条数写进审计日志。
"""

from __future__ import annotations

from sqlalchemy import select, text
from starlette.testclient import TestClient

from app.models import Order
from tests.conftest import auth_headers


def _cleanup(db_session, order_ids: list[int], unit_ids: list[int]) -> None:
    """把自己造的行收掉。

    ⚠️ **必须做**（测试库按 worker 共享，端点会 commit）：这几条测试会造**已送达**的订单，
    而别的测试在断言"这个月这个司机的结算合计"之类的聚合 —— 上一轮就踩过一次
    （实测把 `test_turnover_driver_freight_matches_settlement` 的 100.00 变成 280.00）。
    删的顺序按外键：先子女表，再 orders，最后挂账单位。
    """
    for oid in order_ids:
        for table in ("cash_flows", "ledgers", "driver_bills", "inventory_movements",
                      "operation_logs", "order_products"):
            db_session.execute(text(f"delete from {table} where order_id = :o"), {"o": oid})
        db_session.execute(text("delete from orders where id = :o"), {"o": oid})
    for uid in unit_ids:
        db_session.execute(text("delete from arrears_units where id = :u"), {"u": uid})
    db_session.commit()


def _charged_order(client: TestClient, db_session, token_dispatcher: str, token_driver: str,
                   users: dict, unit_id: int) -> int:
    """建单 → 派给司机（勾了收现金）→ 接单 → **派单员先点挂账**。返回订单 id。"""
    users["driver"].billing_mode = "piece"
    db_session.commit()
    r = client.post("/api/v1/orders", json={
        "lines": [{"product_name_snapshot": "挂账指向货", "quantity": 1, "unit_price": "100.00"}],
        "shipper_id": users["shipper"].id,
    }, headers=auth_headers(token_dispatcher))
    assert r.status_code == 201, r.text
    oid = int(r.json()["id"])
    a = client.post(f"/api/v1/orders/{oid}/assign",
                    json={"driver_id": users["driver"].id, "collect_cash": True,
                          "freight_fee": "60.00"},
                    headers=auth_headers(token_dispatcher))
    assert a.status_code in (200, 201, 204), a.text
    k = client.post(f"/api/v1/orders/{oid}/driver-ack", headers=auth_headers(token_driver))
    assert k.status_code in (200, 201, 204), k.text
    c = client.post(f"/api/v1/orders/{oid}/charge", json={"arrears_unit_id": unit_id},
                    headers=auth_headers(token_dispatcher))
    assert c.status_code == 200, c.text
    return oid


def _unit(client: TestClient, token_dispatcher: str, name: str) -> int:
    r = client.post("/api/v1/arrears-units", json={"name": name},
                    headers=auth_headers(token_dispatcher))
    assert r.status_code in (200, 201), r.text
    return int(r.json()["id"])


def test_先挂账再按现金送达_必须清掉挂账指向(
    client: TestClient, db_session, token_dispatcher: str, token_driver: str, users: dict
) -> None:
    """收到现金之后还指着挂账单位 = 自相矛盾；而它会把这个单位**永久锁住**（删不掉）。"""
    unit_id = _unit(client, token_dispatcher, "指向清理单位A")
    oid = _charged_order(client, db_session, token_dispatcher, token_driver, users, unit_id)
    try:
        done = client.post(f"/api/v1/orders/{oid}/complete",
                           json={"payment": "cash",
                                 "delivery_photo_urls": ["/static/uploads/delivery/a.jpg"]},
                           headers=auth_headers(token_driver))
        assert done.status_code in (200, 201, 204), done.text

        db_session.expire_all()
        o = db_session.get(Order, oid)
        db_session.refresh(o)
        assert o.paid is True and o.payment_method == "cash", "前置：这一单该记成现场收现金"
        assert o.arrears_unit_id is None and not (o.arrears_unit_name or "").strip(), (
            f"钱已经收了，却还指着挂账单位（id={o.arrears_unit_id} name={o.arrears_unit_name!r}）—— "
            "挂账单位页会永远删不掉它，而界面上没有别的办法解开"
        )
    finally:
        _cleanup(db_session, [oid], [unit_id])


def test_挂账送达_指向保持不变(
    client: TestClient, db_session, token_dispatcher: str, token_driver: str, users: dict
) -> None:
    """反向：司机按**挂账**送达时，派单员指定的那个单位必须留着（那是有效信息）。"""
    unit_id = _unit(client, token_dispatcher, "指向保留单位B")
    oid = _charged_order(client, db_session, token_dispatcher, token_driver, users, unit_id)
    try:
        done = client.post(f"/api/v1/orders/{oid}/complete",
                           json={"payment": "arrears",
                                 "delivery_photo_urls": ["/static/uploads/delivery/b.jpg"]},
                           headers=auth_headers(token_driver))
        assert done.status_code in (200, 201, 204), done.text
        db_session.expire_all()
        o = db_session.get(Order, oid)
        db_session.refresh(o)
        assert o.paid is False and o.arrears_unit_id == unit_id, (
            "挂账送达不该把派单员指定的挂账单位清掉"
        )
    finally:
        _cleanup(db_session, [oid], [unit_id])


def test_挂账单位只在还有没收回的挂账单时才拦删除(
    client: TestClient, db_session, token_dispatcher: str, token_driver: str, users: dict
) -> None:
    """还欠着钱的单 → 拦住；钱已经收到的陈旧指向 → 不拦（否则用户被一句假话锁死）。"""
    # ① 还欠着的：必须拦
    owing_unit = _unit(client, token_dispatcher, "还有欠款的单位C")
    owing_oid = _charged_order(client, db_session, token_dispatcher, token_driver, users, owing_unit)
    # ② 已经收了钱的陈旧指向：不拦
    paid_unit = _unit(client, token_dispatcher, "只剩历史指向的单位D")
    paid_oid = _charged_order(client, db_session, token_dispatcher, token_driver, users, paid_unit)
    try:
        blocked = client.delete(f"/api/v1/arrears-units/{owing_unit}",
                                headers=auth_headers(token_dispatcher))
        assert blocked.status_code == 400, (
            f"名下还有没收回的挂账单，删单位必须被拒（实际 {blocked.status_code}）"
        )
        assert "挂账订单" in blocked.text

        done = client.post(f"/api/v1/orders/{paid_oid}/complete",
                           json={"payment": "cash",
                                 "delivery_photo_urls": ["/static/uploads/delivery/c.jpg"]},
                           headers=auth_headers(token_driver))
        assert done.status_code in (200, 201, 204), done.text
        # 手工把这根陈旧指向放回去（模拟修复之前留下的历史数据）
        db_session.execute(
            Order.__table__.update().where(Order.id == paid_oid).values(arrears_unit_id=paid_unit)
        )
        db_session.commit()
        ok_del = client.delete(f"/api/v1/arrears-units/{paid_unit}",
                               headers=auth_headers(token_dispatcher))
        assert ok_del.status_code in (200, 204), (
            "名下只剩「已经收到钱」的历史指向时，不该拦着不让删"
            f"（实际 {ok_del.status_code}：{ok_del.text[:120]}）"
        )
    finally:
        _cleanup(db_session, [owing_oid, paid_oid], [owing_unit, paid_unit])
