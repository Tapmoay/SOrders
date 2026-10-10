"""部分核销的收款：撤销→恢复**不许**把还欠着钱的订单翻成「已收款」（测试台账 TB-12 → BUG-0033）。

## 病灶（第 4 轮 · 方向 B · 金额口径连锁普查实测）

逐单核销支持**按商品核销**（只收这一单里的某几行）。这种"部分核销"的单收完仍然
paid=False、还欠着余额 —— accounting_service.py:482 的 settling 判据就是为它写的：

    settling = [oid for oid in order_ids if per_order[oid] >= money[oid].arrears]

但**撤销→恢复**这条路当时无条件把所有点名订单标成已收款（恢复分支里 o.paid = True）。
后果是那张单带着欠款变成「已收款」：

* 剩下的钱用 itemized 收不进 —— 400「订单 xxx 已经收过款了…请改用滚动收款」；
* 滚动收款又不绑单（钱进了现金流、不冲这单的欠款）；
* 于是这笔欠款**永远挂在单上**，而 /reports/arrears-summary 里那一行会直接消失。

## 改法与判据

恢复只翻「撤销那一步确实翻过」的订单（撤销写在审计 RECEIPT_CANCEL 的
orders_rolled_back 里，恢复照着这张名单翻）。找不到名单时**不翻**（宁可让用户再收一次，
也不要"欠着钱却显示已收"）。

| 判据 | 不钉住会怎样 |
|---|---|
| 部分核销的单撤销→恢复后 paid 仍是 False | 欠款消失、钱永远收不回来（TB-12） |
| 全额核销的单撤销→恢复后 paid 回到 True | 用户明明收清了，恢复后显示"还欠着"，会被重复催收 |
| 恢复只动名单里的订单 | 撤销期间被别的路收清的单被"恢复"顺手改回未收 |
"""
from __future__ import annotations

from tests.conftest import auth_headers
from tests.test_receipt_undo import RECEIPTS, _customer_for, _order_delivered

PART_LINE = "60.00"
REST_LINE = "40.00"


def _two_line_order(client, h, token_shipper, token_driver, users, tag: str):
    """一张 60 + 40 = 100 的已送达单，返回 (订单 id, 商品行列表)。"""
    hs = auth_headers(token_shipper)
    r = client.post(
        "/api/v1/orders",
        headers=hs,
        json={
            "contact_dongjia_name": "收货人乙",
            "lines": [
                {"product_name_snapshot": tag + "-甲", "quantity": 1, "unit_price": PART_LINE, "line_total": PART_LINE},
                {"product_name_snapshot": tag + "-乙", "quantity": 1, "unit_price": REST_LINE, "line_total": REST_LINE},
            ],
            "delivery_description": tag + "探针地址",
            "address_detail": tag + "探针地址",
        },
    )
    assert r.status_code == 201, r.text
    oid = int(r.json()["id"])
    assert client.post(f"/api/v1/orders/{oid}/assign", json={"driver_id": users["driver"].id}, headers=h).status_code in (200, 201)
    hd = auth_headers(token_driver)
    assert client.post(f"/api/v1/orders/{oid}/driver-ack", headers=hd).status_code == 200
    done = client.post(
        f"/api/v1/orders/{oid}/complete",
        json={"delivery_photo_urls": ["/static/uploads/delivery/probe.jpg"]},
        headers=hd,
    )
    assert done.status_code == 200, done.text
    rows = client.get(f"/api/v1/order-products?order_id={oid}", headers=h).json()
    return oid, rows


def _paid(db, oid: int):
    from app.models import Order

    o = db.get(Order, oid)
    db.refresh(o)
    return bool(o.paid), (o.payment_method or "")


def _receipt_body(cust: int, amount: str, oid: int, line_id: int):
    return {
        "customer_id": cust,
        "amount": amount,
        "method": "cash",
        "settle_mode": "itemized",
        "order_ids": [oid],
        "order_product_ids": [line_id],
        "received_at": "2026-10-10",
    }


def test_partial_receipt_restore_does_not_mark_the_order_paid(
    client, token_dispatcher, token_shipper, token_driver, users, db_session
):
    """TB-12 的正身：部分核销 → 撤销 → 恢复，paid 必须还是 False、还欠的钱还在。"""
    h = auth_headers(token_dispatcher)
    oid, rows = _two_line_order(client, h, token_shipper, token_driver, users, "TB12部分")
    assert len(rows) == 2, rows

    cust = _customer_for(client, h, token_shipper, "TB12部分")
    r = client.post(RECEIPTS, headers=h, json=_receipt_body(cust, PART_LINE, oid, rows[0]["id"]))
    assert r.status_code in (200, 201), r.text
    rid = int(r.json()["id"])

    paid, method = _paid(db_session, oid)
    assert paid is False, "部分核销之后这张单不该是已收款（它还欠着 40）"
    assert method == "arrears"

    assert client.delete(f"{RECEIPTS}/{rid}", headers=h).status_code == 204
    r2 = client.post(f"{RECEIPTS}/{rid}/restore", headers=h)
    assert r2.status_code == 200, r2.text

    paid, method = _paid(db_session, oid)
    assert paid is False, "恢复把还欠着 40 的单翻成了已收款（TB-12：这 40 永远收不回来）"
    assert method == "arrears", "payment_method 不该被改成 cash（钱没付完）"

    again = client.post(RECEIPTS, headers=h, json=_receipt_body(cust, REST_LINE, oid, rows[1]["id"]))
    assert again.status_code in (200, 201), again.text
    paid, method = _paid(db_session, oid)
    assert paid is True, "两行都收完了，这张单应该是已收款"
    assert method == "cash"


def test_full_receipt_restore_still_marks_the_order_paid(
    client, token_dispatcher, token_shipper, token_driver, users, db_session
):
    """全额核销的老行为一字不变：撤销→恢复后 paid 必须回到 True。"""
    h = auth_headers(token_dispatcher)
    oid = _order_delivered(client, h, token_shipper, token_driver, users, "TB12全额", "100.00")
    cust = _customer_for(client, h, token_shipper, "TB12全额")
    r = client.post(
        RECEIPTS,
        headers=h,
        json={"customer_id": cust, "amount": "100.00", "method": "cash", "settle_mode": "itemized",
              "order_ids": [oid], "received_at": "2026-10-10"},
    )
    assert r.status_code in (200, 201), r.text
    rid = int(r.json()["id"])
    assert _paid(db_session, oid)[0] is True

    assert client.delete(f"{RECEIPTS}/{rid}", headers=h).status_code == 204
    assert _paid(db_session, oid)[0] is False, "撤销之后应该回到未收款"
    assert client.post(f"{RECEIPTS}/{rid}/restore", headers=h).status_code == 200
    assert _paid(db_session, oid)[0] is True, "全额核销的单恢复后必须回到已收款"


def test_restore_leaves_alone_orders_the_cancel_never_touched(
    client, token_dispatcher, token_shipper, token_driver, users, db_session
):
    """撤销那一步没翻过的单（期间被别的收款收清了），恢复不许顺手改它。"""
    h = auth_headers(token_dispatcher)
    oid, rows = _two_line_order(client, h, token_shipper, token_driver, users, "TB12别动")
    cust = _customer_for(client, h, token_shipper, "TB12别动")
    r = client.post(RECEIPTS, headers=h, json=_receipt_body(cust, PART_LINE, oid, rows[0]["id"]))
    rid = int(r.json()["id"])
    assert client.delete(f"{RECEIPTS}/{rid}", headers=h).status_code == 204

    # 撤销 #1 之后这张单又欠回 100 —— 别人把它整单收清了（不再是"部分核销"）
    tail = client.post(
        RECEIPTS,
        headers=h,
        json={"customer_id": cust, "amount": "100.00", "method": "cash", "settle_mode": "itemized",
              "order_ids": [oid], "received_at": "2026-10-10"},
    )
    assert tail.status_code in (200, 201), tail.text
    assert _paid(db_session, oid)[0] is True

    # 这时候恢复 #1 必须被门③拦住（否则同一笔钱会被算两遍），而不是把这张单改回未收款
    r2 = client.post(f"{RECEIPTS}/{rid}/restore", headers=h)
    assert r2.status_code == 400, r2.text
    assert "已经是「已收款」" in r2.json()["detail"]
    assert _paid(db_session, oid)[0] is True, "被拦下之后不许动那张单"

    from app.models import ShipperReceipt

    row = db_session.get(ShipperReceipt, rid)
    db_session.refresh(row)
    assert row.is_deleted is True, "恢复被拒之后，收款单必须留在回收站里"
