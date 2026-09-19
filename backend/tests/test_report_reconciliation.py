"""报表口径的**闭合性**（v3.39 缺陷挖掘第二轮的战果）。

报表最容易出的错不是"数字算错"，而是**同一笔钱在两个口径里各说各的**：
营业额 200、已收 100、挂账 0 —— 差出来的 100 在报表上哪一列都不属于，
而每一列看起来都很正常。

这里钉的是一条不该被破坏的不变量：

> **营业额 = 已收 + 挂账未收**（同一窗口、同一批已送达订单）

原来的判据是两条带条件的（`cash 且已收` / `arrears 且未收`），于是
**挂账结清**（`arrears_settle`：`payment_method` 还是 arrears，但 `paid=True`）
这种组合两边都不算——钱凭空消失。
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from starlette.testclient import TestClient

from tests.conftest import auth_headers


def _today_utc() -> str:
    """报表锚点 = **业务当地日**（2026-09-19 审计 R12-M11 之后）。

    锚点原本按 UTC 取（"后端 `_now()` 是 UTC，所以窗口也得按 UTC 落"）——那是**实现细节泄漏到
    契约里**：锚点来自用户（手机传 `LocalDate.now()`，就是当地的今天），所以分桶也必须按当地日。
    不这么改的话，东八区当地 00:00~08:00 送达的单会被算进前一天，早上看日报是 0。
    """
    from app.core.business_time import business_today

    return business_today().isoformat()


def _turnover(client: TestClient, tok: str) -> dict:
    """金额字段是 Decimal（JSON 里是字符串），统一转成 Decimal 再比——别拿字符串做减法。"""
    from decimal import Decimal

    r = client.get(f"/api/v1/reports/turnover?mode=day&date={_today_utc()}", headers=auth_headers(tok))
    assert r.status_code == 200, r.text
    d = r.json()
    money_keys = ("total_amount", "collected", "arrears_total", "cost_total", "total_freight")
    return {k: (Decimal(v) if k in money_keys else v) for k, v in d.items()}


def _deliver(client: TestClient, token_shipper: str, token_dispatcher: str, token_driver: str,
             driver_id: int, *, amount: str, collect_cash: bool, payment: str | None) -> int:
    r = client.post(
        "/api/v1/orders", headers=auth_headers(token_shipper),
        json={"lines": [{"product_name_snapshot": "报表闭合探针", "quantity": 1,
                         "unit_price": amount, "line_total": amount}],
              "delivery_description": "报表闭合探针"},
    )
    assert r.status_code == 201, r.text
    oid = int(r.json()["id"])
    assert client.post(
        f"/api/v1/orders/{oid}/assign",
        headers=auth_headers(token_dispatcher),
        json={"driver_id": driver_id, "freight_fee": "30.00", "collect_cash": collect_cash},
    ).status_code == 200
    assert client.post(f"/api/v1/orders/{oid}/driver-ack", headers=auth_headers(token_driver)).status_code == 200
    body = {"delivery_photo_urls": ["/static/uploads/delivery/report.jpg"]}
    if payment:
        body["payment"] = payment
    r = client.post(f"/api/v1/orders/{oid}/complete", headers=auth_headers(token_driver), json=body)
    assert r.status_code == 200, r.text
    return oid


@pytest.mark.dispatcher
@pytest.mark.driver
@pytest.mark.integration
def test_挂账结清之后钱要从挂账挪到已收_不能凭空消失(
    client: TestClient, token_shipper: str, token_dispatcher: str, token_driver: str
) -> None:
    """核心不变量：营业额 = 已收 + 挂账。用**增量**比，避免被历史数据搅乱。"""
    from tests.test_driver_billing_api import _mk_driver  # 复用"建司机并登录"的助手

    driver_id, driver_tok = _mk_driver(client, token_dispatcher, vehicle="trailer")
    base = _turnover(client, token_dispatcher)

    _deliver(client, token_shipper, token_dispatcher, driver_tok, driver_id,
             amount="100.00", collect_cash=True, payment="cash")
    oid_arrears = _deliver(client, token_shipper, token_dispatcher, driver_tok, driver_id,
                           amount="100.00", collect_cash=False, payment="arrears")
    mid = _turnover(client, token_dispatcher)

    d_amount = mid["total_amount"] - base["total_amount"]
    d_collected = mid["collected"] - base["collected"]
    d_arrears = mid["arrears_total"] - base["arrears_total"]
    assert d_amount == 200, f"营业额增量 {d_amount}"
    assert d_collected + d_arrears == d_amount, (
        f"闭不上：已收 {d_collected} + 挂账 {d_arrears} ≠ 营业额 {d_amount}"
    )

    # 挂账单结清（arrears_settle）：钱从「挂账」挪到「已收」，合计不变
    me = client.get("/api/v1/users/me", headers=auth_headers(token_shipper)).json()
    cust = client.post("/api/v1/customers", headers=auth_headers(token_dispatcher),
                       json={"name": f"报表闭合客户-{oid_arrears}", "user_id": me["id"]})
    assert cust.status_code in (200, 201), cust.text
    r = client.post(
        "/api/v1/ledger/receipts", headers=auth_headers(token_dispatcher),
        json={"customer_id": cust.json()["id"], "amount": "100.00", "method": "arrears_settle",
              "settle_mode": "itemized", "order_ids": [oid_arrears],
              "received_at": _today_utc()},
    )
    assert r.status_code in (200, 201), r.text

    after = _turnover(client, token_dispatcher)
    e_collected = after["collected"] - mid["collected"]
    e_arrears = after["arrears_total"] - mid["arrears_total"]
    assert e_collected == 100, f"结清挂账之后「已收」应当 +100，实际 {e_collected}"
    assert e_arrears == -100, f"「挂账」应当 -100，实际 {e_arrears}"
    assert after["total_amount"] == mid["total_amount"], "结清挂账不该改变营业额"


@pytest.mark.dispatcher
@pytest.mark.driver
@pytest.mark.integration
def test_删掉的单不再算进营业额(
    client: TestClient, token_shipper: str, token_dispatcher: str, token_driver: str
) -> None:
    """隔离区（软删）的单必须从营业额里消失，否则"删了也没用"。"""
    from tests.test_driver_billing_api import _mk_driver

    driver_id, driver_tok = _mk_driver(client, token_dispatcher, vehicle="trailer")
    oid = _deliver(client, token_shipper, token_dispatcher, driver_tok, driver_id,
                   amount="77.00", collect_cash=True, payment="cash")
    before = _turnover(client, token_dispatcher)
    assert client.delete(f"/api/v1/orders/{oid}", headers=auth_headers(token_dispatcher)).status_code in (200, 204)
    after = _turnover(client, token_dispatcher)
    assert before["total_amount"] - after["total_amount"] == 77, "删掉 77 元的单之后营业额没减"
