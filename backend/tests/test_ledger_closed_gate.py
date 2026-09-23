"""「这张单已经结束了，账上这笔钱不能改」——判据必须与订单侧**同一处**（2026-09-23 第 17 轮）。

## 抓到的是什么（中）

`ledger.py::_reject_if_order_closed` 的注释写着"复用订单侧那条判据"，实现却是**手写的两个状态**：

    if order.status in (OrderStatus.DELIVERED, OrderStatus.CANCELLED):   # ← 少了 RETURNED

于是**已退货**的单那一行 ORDER 账本还能改，而改完 `ledger_sync.sync_order_product_from_ledger`
会**回写订单行金额** —— 破了「同一笔钱一个数」这条不变式（账本一个数、订单行另一个数）。
修法：判据改成 `order.status not in LINE_EDITABLE_STATUSES`（与订单明细编辑**共用同一份状态清单**），
清单加新状态时这里自动跟上。
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from starlette.testclient import TestClient

from app.models import Ledger
from app.models.enums import LedgerSource
from tests.conftest import auth_headers


@pytest.mark.dispatcher
@pytest.mark.integration
def test_已退货的单不许再从账本侧改金额(
    client: TestClient, db_session, token_shipper: str, token_dispatcher: str, token_driver: str
) -> None:
    from tests.test_driver_billing_api import _mk_driver

    driver_id, driver_tok = _mk_driver(client, token_dispatcher, vehicle="trailer")
    r = client.post(
        "/api/v1/orders",
        headers=auth_headers(token_shipper),
        json={"lines": [{"product_name_snapshot": "退货门探针", "quantity": 2, "unit_price": "40"}],
              "delivery_description": "退货门探针"},
    )
    assert r.status_code == 201, r.text
    oid = int(r.json()["id"])
    assert client.post(
        f"/api/v1/orders/{oid}/assign",
        headers=auth_headers(token_dispatcher),
        json={"driver_id": driver_id, "freight_fee": "10.00"},
    ).status_code == 200
    assert client.post(
        f"/api/v1/orders/{oid}/driver-ack", headers=auth_headers(driver_tok)
    ).status_code == 200
    assert client.post(
        f"/api/v1/orders/{oid}/complete",
        headers=auth_headers(driver_tok),
        json={"delivery_photo_urls": ["/static/uploads/delivery/gate.jpg"], "payment": "arrears"},
    ).status_code == 200

    line = client.get(
        f"/api/v1/order-products?order_id={oid}", headers=auth_headers(token_dispatcher)
    ).json()[0]
    ret = client.post(
        f"/api/v1/orders/{oid}/return",
        headers=auth_headers(token_dispatcher),
        json={"items": [{"order_product_id": int(line["id"]), "quantity": 2}]},
    )
    assert ret.status_code in (200, 201), ret.text

    db_session.expire_all()
    row = db_session.scalars(
        select(Ledger).where(Ledger.order_id == oid, Ledger.source == LedgerSource.ORDER)
    ).first()
    assert row is not None, "前置：这一单该有 ORDER 账本行"
    before_amount = str(row.total)

    bad = client.patch(
        f"/api/v1/ledger/entries/{int(row.id)}",
        headers=auth_headers(token_dispatcher),
        json={"total": "1.00"},
    )
    assert bad.status_code == 400, (
        f"已退货的单不该还能从账本侧改金额（实际 {bad.status_code}）—— "
        "改完会回写订单行，同一笔钱变成两个数"
    )
    assert "已退货" in bad.json()["detail"], bad.json()["detail"]

    db_session.expire_all()
    again = db_session.get(Ledger, int(row.id))
    assert again is not None and str(again.total) == before_amount, "被拒之后账本行不许变"
