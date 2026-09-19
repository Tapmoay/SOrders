"""第十八轮审计的回归测试：**账本口径必须与报表同一句**（R13-R6）+ 收款单去重（F9）。

| 缺陷 | 后果 |
|---|---|
| **R13-R6：隔离区（软删）订单的账本行仍被算进账本口径** | 报表侧排除了软删单（`Order.deleted_at.is_(None)`），账本侧**没有** → 同一个月两个数：本机 2026-09 账本 **101,731.75** vs 营业额 **97,131.75**（差 ¥4,600 = 隔离区账本 4,200 + 非已送达状态的历史账本行 400）。老板拿账本和营业额对账时对不上，而两个页面都不报错 |
| **F9：收款单落库存的是未去重的 `order_ids`** | `[5,5]` 能过校验（去重后只有一张单、金额也对得上），收款记录里却显示两条同样的订单 —— 对账的人会以为收了两次 |
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from io import BytesIO

from openpyxl import load_workbook

from tests.conftest import auth_headers


def _deliver(client, h_dispatcher, h_driver, order_id: int, driver_id: int, freight: str = "100") -> None:
    r = client.post(
        f"/api/v1/orders/{order_id}/assign",
        json={"driver_id": driver_id, "freight_fee": freight},
        headers=h_dispatcher,
    )
    assert r.status_code == 200, r.text
    assert client.post(f"/api/v1/orders/{order_id}/driver-ack", headers=h_driver).status_code == 200
    r = client.post(
        f"/api/v1/orders/{order_id}/complete",
        json={"delivery_photo_urls": ["/static/uploads/delivery/probe.jpg"]},
        headers=h_driver,
    )
    assert r.status_code == 200, r.text


def _order(client, h, shipper_id: int, name: str, qty: int = 1, price: str = "500") -> int:
    r = client.post(
        "/api/v1/orders",
        json={
            "shipper_id": shipper_id,
            "lines": [
                {
                    "product_name_snapshot": name,
                    "quantity": qty,
                    "unit_price": price,
                    "line_total": str(Decimal(price) * qty),
                }
            ],
            "address_detail": f"{name}探针地址",
        },
        headers=h,
    )
    assert r.status_code == 201, r.text
    return int(r.json()["id"])


def _ledger_total(client, h, shipper_id: int) -> Decimal:
    rows = client.get(f"/api/v1/ledger/accounts?kind=shipper", headers=h).json()
    hit = [r for r in rows if int(r.get("id") or 0) == shipper_id]
    return Decimal(str(hit[0]["total"])) if hit else Decimal("0")


def test_ledger_accounts_exclude_orders_in_the_recycle_bin(
    client, token_dispatcher, token_shipper, token_driver, users, db_session
):
    """订单进了回收站之后，它的那份账要从**账本口径**里消失（与营业额同源）。"""
    h = auth_headers(token_dispatcher)
    hd = auth_headers(token_driver)
    oid = _order(client, h, users["shipper"].id, "隔离区账本探针", price="500")
    _deliver(client, h, hd, oid, users["driver"].id)

    after_delivery = _ledger_total(client, h, users["shipper"].id)
    assert after_delivery >= Decimal("500"), "前提不成立：送达没有写账本行"

    r = client.delete(f"/api/v1/orders/{oid}", headers=h)
    assert r.status_code in (200, 204), r.text

    after_delete = _ledger_total(client, h, users["shipper"].id)
    assert after_delete == after_delivery - Decimal("500"), (
        f"订单已进回收站，账本口径却还是 {after_delete}（删除前 {after_delivery}）—— "
        "账本与营业额会差这一张单的钱"
    )

    # 恢复之后必须回来（隔离区是可恢复的，我们不删那些账本行）
    r = client.post(f"/api/v1/orders/{oid}/restore", headers=h)
    assert r.status_code in (200, 201), r.text
    assert _ledger_total(client, h, users["shipper"].id) == after_delivery, (
        "恢复订单之后账本口径没跟着回来（说明是「删了行」而不是「读的时候不算」）"
    )


def test_ledger_and_turnover_agree_after_deleting_an_order(
    client, token_dispatcher, token_shipper, token_driver, users
):
    """账本口径与「营业额」必须**同步**减少（同一个数，两处都变）。"""
    h = auth_headers(token_dispatcher)
    hd = auth_headers(token_driver)
    today = date.today().isoformat()

    def turnover() -> Decimal:
        r = client.get(f"/api/v1/reports/turnover?mode=day&date={today}", headers=h)
        assert r.status_code == 200, r.text
        return Decimal(str(r.json()["total_amount"]))

    def ledger() -> Decimal:
        rows = client.get("/api/v1/ledger/accounts?kind=shipper", headers=h).json()
        return sum((Decimal(str(x["total"])) for x in rows), Decimal("0"))

    oid = _order(client, h, users["shipper"].id, "账本报表对账探针", price="700")
    _deliver(client, h, hd, oid, users["driver"].id)
    t1, l1 = turnover(), ledger()

    r = client.delete(f"/api/v1/orders/{oid}", headers=h)
    assert r.status_code in (200, 204), r.text
    t2, l2 = turnover(), ledger()

    assert t2 == t1 - Decimal("700"), f"营业额没减：{t1} → {t2}"
    assert l2 == l1 - Decimal("700"), f"账本口径没减：{l1} → {l2}"
    assert t2 == t1 - Decimal("700") and l2 == l1 - Decimal("700")


def test_ledger_export_also_excludes_recycled_orders(
    client, token_dispatcher, token_shipper, token_driver, users, db_session
):
    """账本导出（xlsx）也不许带上隔离区订单的那份账。"""
    h = auth_headers(token_dispatcher)
    hd = auth_headers(token_driver)
    tag = "导出隔离区探针"
    oid = _order(client, h, users["shipper"].id, tag, price="321")
    _deliver(client, h, hd, oid, users["driver"].id)
    r = client.delete(f"/api/v1/orders/{oid}", headers=h)
    assert r.status_code in (200, 204), r.text

    from app.services.ledger_export import build_ledger_rows
    from app.models import Order

    db_session.expire_all()
    order = db_session.get(Order, oid)
    rows, _label = build_ledger_rows(
        db_session, users["shipper"].id, date(2026, 1, 1), date(2026, 12, 31)
    )
    hits = [x for x in rows if x.order_id == oid]
    assert hits == [], (
        f"账本导出里还带着隔离区订单的 {len(hits)} 行（订单 deleted_at={order.deleted_at}）"
    )


def test_auto_ledger_rows_for_undelivered_orders_are_not_counted(
    client, token_dispatcher, token_shipper, token_driver, users, db_session
):
    """漂移出来的自动账本行（`source=ORDER` 但订单**还没送达**）不许算进账本口径。

    这种行在库里真实存在（本机 2026-09 有 7 行挂在 `ACCEPTED` 的单上 ¥400，早期竞态遗留）——
    而按代码契约，自动账本行只在送达那一刻写。它算进去的话，账本就永远比营业额多这一截，
    两个页面都不报错。送达之后同一行必须**立刻算**（我们不删行，只按口径读）。
    """
    from app.models import Ledger
    from app.models.enums import LedgerSource, OrderStatus

    h = auth_headers(token_dispatcher)
    oid = _order(client, h, users["shipper"].id, "未送达漂移账探针", price="400")
    r = client.post(
        f"/api/v1/orders/{oid}/assign",
        json={"driver_id": users["driver"].id, "freight_fee": "50"},
        headers=h,
    )
    assert r.status_code == 200, r.text
    db_session.expire_all()

    before = _ledger_total(client, h, users["shipper"].id)
    drift = Ledger(
        shipper_id=users["shipper"].id,
        entry_date=date(2026, 9, 18),
        product_name="未送达漂移账探针",
        quantity=1,
        unit_price=Decimal("400"),
        total=Decimal("400"),
        order_id=oid,
        source=LedgerSource.ORDER,
        note="漂移出来的自动行",
    )
    db_session.add(drift)
    db_session.commit()

    assert _ledger_total(client, h, users["shipper"].id) == before, (
        "订单还没送达，它的自动账本行却被算进了账本口径（账本会永远比营业额多这一截）"
    )

    # 送达之后同一行立刻算进来
    hd = auth_headers(token_driver)
    assert client.post(f"/api/v1/orders/{oid}/driver-ack", headers=hd).status_code == 200
    r = client.post(
        f"/api/v1/orders/{oid}/complete",
        json={"delivery_photo_urls": ["/static/uploads/delivery/probe.jpg"]},
        headers=hd,
    )
    assert r.status_code == 200, r.text
    db_session.expire_all()
    assert db_session.get(type(drift), drift.id) is not None
    from app.models import Order

    assert db_session.get(Order, oid).status == OrderStatus.DELIVERED
    assert _ledger_total(client, h, users["shipper"].id) >= before + Decimal("400"), (
        "订单送达之后，那一行自动账本必须算进来"
    )


def test_receipt_stores_deduped_order_ids(client, token_dispatcher, token_shipper, users, db_session):
    """收款单落库的 `order_ids` 必须去重（`[5,5]` 不能让记录里出现两条同样的单）。"""
    h = auth_headers(token_dispatcher)
    hs = auth_headers(token_shipper)
    r = client.post(
        "/api/v1/orders",
        headers=hs,
        json={
            "lines": [
                {
                    "product_name_snapshot": "去重探针货",
                    "quantity": 1,
                    "unit_price": "100.00",
                    "line_total": "100.00",
                }
            ],
            "delivery_description": "去重探针",
            "address_detail": "去重探针",
        },
    )
    assert r.status_code == 201, r.text
    oid = int(r.json()["id"])
    me = client.get("/api/v1/users/me", headers=hs).json()
    cust = client.post(
        "/api/v1/customers", headers=h, json={"name": "去重探针客户", "user_id": me["id"]}
    )
    assert cust.status_code in (200, 201), cust.text

    r = client.post(
        "/api/v1/ledger/receipts",
        headers=h,
        json={
            "customer_id": cust.json()["id"],
            "amount": "100.00",
            "method": "cash",
            "settle_mode": "itemized",
            "order_ids": [oid, oid],
            "received_at": "2026-09-18",
        },
    )
    assert r.status_code in (200, 201), r.text
    body = r.json()
    assert body["order_ids"] == [oid], f"落库的 order_ids 没去重：{body['order_ids']}"
