"""「待定价」那条路的钱必须自洽：送达之后补上运费，司机应付明细要跟着改。

## 现场（2026-09-23 第 6 轮实测复现）

真实顺序（不是并发，一个人就能做完）：

1. 派单员**忘了定价** → 司机照常送达；
2. 送达那一刻 `post_delivery_accounting` 按**当时的运费（None）**生成了一张按单应付明细
   （规则「每单 300 + 运费 5%」→ 明细 **300**）；
3. 这张单出现在「待定价」页（`GET /orders?unpriced=true` 刻意把 DELIVERED 也算进来 ——
   不这样它就永远收不到钱），派单员在那页把它定成 1000；
4. 于是：`driver_bills.amount` = **300**（结算单按它收钱），
   而绩效页 `freight_owed` / 运费结算页按 `driver_pay.pay_for_order(order)` 现算 = **350**。

**同一笔钱两个数，两个页面都不报错。** 这正是 `test_driver_money_reconciliation.py`
明令禁止的形状（"三方对账"），也是红线 §22（钱只算一处）想防的那一类。

修法：`accounting_service.resync_open_piece_bill` —— 运费变了之后，
把那张**还没结算**的应付明细按 `pay_for_order` 重算（金额只算一处）；
**已经进过结算单**的（SETTLED）则拒绝这次定价（钱已经定死，改了只会三处对不上）。
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from starlette.testclient import TestClient

from app.models import DriverBill
from app.models.enums import DriverBillStatus
from tests.conftest import auth_headers
from tests.test_driver_billing_api import _attach, _mk_driver, _mk_rule, _uniq
from tests.test_driver_money_reconciliation import _today_utc


def _deliver_unpriced(client: TestClient, token_shipper: str, token_dispatcher: str,
                      driver_id: int, driver_tok: str) -> int:
    """建单 → 派给司机（**不带运费**）→ 接单 → 送达；返回订单 id。"""
    r = client.post("/api/v1/orders", headers=auth_headers(token_shipper),
                    json={"lines": [{"product_name_snapshot": "定价探针货", "quantity": 1,
                                     "unit_price": "80.00", "line_total": "80.00"}]})
    assert r.status_code == 201, r.text
    oid = int(r.json()["id"])
    a = client.post(f"/api/v1/orders/{oid}/assign", headers=auth_headers(token_dispatcher),
                    json={"driver_id": driver_id, "collect_cash": True})
    assert a.status_code == 200, a.text
    assert client.post(f"/api/v1/orders/{oid}/driver-ack",
                       headers=auth_headers(driver_tok)).status_code == 200
    c = client.post(f"/api/v1/orders/{oid}/complete", headers=auth_headers(driver_tok),
                    json={"delivery_photo_urls": ["/static/uploads/delivery/price.jpg"],
                          "payment": "arrears"})
    assert c.status_code == 200, c.text
    return oid


def _piece_bill(db_session, oid: int) -> DriverBill | None:
    return db_session.scalars(
        select(DriverBill).where(DriverBill.order_id == oid)
    ).first()


def _settled_total(client: TestClient, token_dispatcher: str, driver_id: int) -> Decimal:
    rows = client.get(f"/api/v1/driver-bills?driver_id={driver_id}",
                      headers=auth_headers(token_dispatcher)).json()
    return sum((Decimal(b["amount"]) for b in rows
                if b.get("bill_type") == "piece" and b.get("status") == "open"), Decimal("0"))


def test_送达后补定价_司机应付明细跟着改(
    client: TestClient, db_session, token_shipper: str, token_dispatcher: str
) -> None:
    """① 送达（未定价）→ 补定价 → 明细、绩效页、结算页三处必须是**同一个数**。"""
    driver_id, driver_tok = _mk_driver(client, token_dispatcher, vehicle="trailer")
    rule = _mk_rule(client, token_dispatcher, name=_uniq("定价规则"), vehicle_type="trailer",
                    salary="0", piece_amount="300", commission_base="freight", commission_rate="5")
    assert _attach(client, token_dispatcher, driver_id, rule["id"]).status_code == 200

    oid = _deliver_unpriced(client, token_shipper, token_dispatcher, driver_id, driver_tok)
    db_session.expire_all()
    bill = _piece_bill(db_session, oid)
    assert bill is not None and bill.amount == Decimal("300.00"), (
        f"前置：送达时该按当时的运费生成明细（实际 {bill.amount if bill else None}）"
    )

    # 这张单确实在「待定价」页里（用户就是从这里点的）
    lst = client.get("/api/v1/orders?unpriced=true", headers=auth_headers(token_dispatcher))
    listed = lst.json()
    ids = [x["id"] for x in (listed if isinstance(listed, list) else listed.get("items", []))]
    assert oid in ids, "送达但未定价的单必须出现在待定价页里（否则它永远收不到钱）"

    pr = client.post(f"/api/v1/orders/{oid}/price-freight",
                     json={"freight_fee": "1000.00"}, headers=auth_headers(token_dispatcher))
    assert pr.status_code == 200, pr.text

    db_session.expire_all()
    bill = _piece_bill(db_session, oid)
    # 每单 300 + 运费 1000 的 5% = 350
    assert bill.amount == Decimal("350.00"), (
        f"明细没有跟着运费改（还是 {bill.amount}）—— 结算单按它收钱，"
        "而结算页/绩效页按新运费现算，两个数会永久分叉"
    )
    assert "运费 1000" in (bill.note or "") or "350" in (bill.note or ""), (
        f"账单上那句「怎么算出来的」也要跟着改（现在：{bill.note}）"
    )
    assert _settled_total(client, token_dispatcher, driver_id) == Decimal("350.00"), (
        "结算页那一份（按 driver_pay 现算）必须与明细一致"
    )


def test_已进结算的明细_不许再定价(
    client: TestClient, db_session, token_shipper: str, token_dispatcher: str
) -> None:
    """② 明细已经进过结算单（钱定死了）→ 补定价必须被拒，不许把账单改到结算单对不上。"""
    driver_id, driver_tok = _mk_driver(client, token_dispatcher, vehicle="trailer")
    rule = _mk_rule(client, token_dispatcher, name=_uniq("已结规则"), vehicle_type="trailer",
                    salary="0", piece_amount="300", commission_base="freight", commission_rate="5")
    assert _attach(client, token_dispatcher, driver_id, rule["id"]).status_code == 200

    oid = _deliver_unpriced(client, token_shipper, token_dispatcher, driver_id, driver_tok)
    month = _today_utc()[:7]
    created = client.post("/api/v1/driver-settlements", headers=auth_headers(token_dispatcher),
                          json={"driver_id": driver_id, "month": month, "settle_type": "piece"})
    assert created.status_code in (200, 201), created.text
    sid = created.json()["id"]
    assert client.patch(f"/api/v1/driver-settlements/{sid}",
                        headers=auth_headers(token_dispatcher),
                        json={"action": "confirm"}).status_code == 200

    db_session.expire_all()
    bill = _piece_bill(db_session, oid)
    assert bill is not None and bill.status == DriverBillStatus.SETTLED, (
        "前置：那张明细该已经进结算单了"
    )
    before = bill.amount

    pr = client.post(f"/api/v1/orders/{oid}/price-freight",
                     json={"freight_fee": "1000.00"}, headers=auth_headers(token_dispatcher))
    assert pr.status_code == 400, (
        f"明细已进结算单还允许改运费（实际 {pr.status_code}）——"
        "账单、结算单、结算页三处会对不上"
    )
    db_session.expire_all()
    bill = _piece_bill(db_session, oid)
    assert bill.amount == before, f"被拒之后金额不许动（{before} → {bill.amount}）"


def test_已送达且已定价的单_不许再改价(
    client: TestClient, db_session, token_shipper: str, token_dispatcher: str
) -> None:
    """③ 与「改司机运费」同一个口径：送达之后运费锁定，`price-freight` 不是后门。"""
    driver_id, driver_tok = _mk_driver(client, token_dispatcher, vehicle="trailer")
    rule = _mk_rule(client, token_dispatcher, name=_uniq("锁定规则"), vehicle_type="trailer",
                    salary="0", piece_amount="300", commission_base="freight", commission_rate="5")
    assert _attach(client, token_dispatcher, driver_id, rule["id"]).status_code == 200

    r = client.post("/api/v1/orders", headers=auth_headers(token_shipper),
                    json={"lines": [{"product_name_snapshot": "已定价货", "quantity": 1,
                                     "unit_price": "80.00", "line_total": "80.00"}]})
    oid = int(r.json()["id"])
    assert client.post(f"/api/v1/orders/{oid}/assign", headers=auth_headers(token_dispatcher),
                       json={"driver_id": driver_id, "freight_fee": "500.00",
                             "collect_cash": True}).status_code == 200
    assert client.post(f"/api/v1/orders/{oid}/driver-ack",
                       headers=auth_headers(driver_tok)).status_code == 200
    assert client.post(f"/api/v1/orders/{oid}/complete", headers=auth_headers(driver_tok),
                       json={"delivery_photo_urls": ["/static/uploads/delivery/lock.jpg"],
                             "payment": "arrears"}).status_code == 200

    pr = client.post(f"/api/v1/orders/{oid}/price-freight",
                     json={"freight_fee": "9999.00"}, headers=auth_headers(token_dispatcher))
    assert pr.status_code == 400, (
        f"已送达且已定价的单还能改运费（实际 {pr.status_code}）——"
        "「改司机运费」那边锁着，这里却开了同一个字段的后门"
    )
    db_session.expire_all()
    from app.models import Order

    o = db_session.get(Order, oid)
    db_session.refresh(o)
    assert Decimal(str(o.freight_fee)) == Decimal("500.00"), "被拒之后订单运费不许动"
    assert _piece_bill(db_session, oid).amount == Decimal("325.00"), (
        "明细该是 300 + 500 的 5% = 325（钱只算一处）"
    )
