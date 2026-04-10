"""
Order lifecycle: create → assign → driver ack → complete; recall path; cancel pending.

Requirements Coverage:
- TC-SH-001: 正常下单流程
- TC-SH-004: 撤销订单
- TC-DR-005: 完成订单
- TC-SP-001: 单订单派单
- TC-SP-003: 撤回派单
- 状态机验证 (DOMAIN_MODEL.md)
"""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from app.models import User
from app.models.enums import OrderStatus
from tests.conftest import auth_headers


def _create_order(client: TestClient, token_shipper: str) -> int:
    r = client.post(
        "/api/v1/orders",
        headers=auth_headers(token_shipper),
        json={
            "lines": [
                {
                    "product_name_snapshot": "ItemA",
                    "quantity": 1,
                    "unit_price": "10.00",
                    "line_total": "10.00",
                }
            ],
            "delivery_description": "door",
        },
    )
    assert r.status_code == 201, r.text
    return int(r.json()["id"])


@pytest.mark.orders
@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.smoke
def test_flow_dispatch_ack_complete(
    client: TestClient,
    token_shipper: str,
    token_dispatcher: str,
    token_driver: str,
    users: dict,
) -> None:
    oid = _create_order(client, token_shipper)
    r = client.post(
        f"/api/v1/orders/{oid}/assign",
        headers=auth_headers(token_dispatcher),
        json={"driver_id": users["driver"].id},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == OrderStatus.ACCEPTED.value

    r = client.post(
        f"/api/v1/orders/{oid}/driver-ack",
        headers=auth_headers(token_driver),
    )
    assert r.status_code == 200, r.text
    assert r.json()["driver_acknowledged_at"] is not None

    r = client.post(
        f"/api/v1/orders/{oid}/complete",
        headers=auth_headers(token_driver),
        json={
            "delivery_photo_urls": ["/static/uploads/delivery/test1.jpg"],
            "driver_remark": "ok",
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == OrderStatus.DELIVERED.value

    r = client.get(
        "/api/v1/ledger/entries",
        params={"shipper_id": users["shipper"].id},
        headers=auth_headers(token_dispatcher),
    )
    assert r.status_code == 200, r.text
    entries = r.json()
    assert len(entries) >= 1
    assert any(e.get("source") == "order" for e in entries)
    assert any("自动记账" in (e.get("note") or "") for e in entries)


@pytest.mark.orders
@pytest.mark.dispatcher
@pytest.mark.integration
@pytest.mark.smoke
def test_recall_after_dispatch(
    client: TestClient,
    token_shipper: str,
    token_dispatcher: str,
    users: dict,
) -> None:
    oid = _create_order(client, token_shipper)
    r = client.post(
        f"/api/v1/orders/{oid}/assign",
        headers=auth_headers(token_dispatcher),
        json={"driver_id": users["driver"].id},
    )
    assert r.status_code == 200

    r = client.post(
        f"/api/v1/orders/{oid}/recall",
        headers=auth_headers(token_dispatcher),
        json={"reason": "customer changed address"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == OrderStatus.PENDING_DISPATCH.value
    assert body["driver_id"] is None


@pytest.mark.orders
@pytest.mark.shipper
@pytest.mark.fast
def test_delete_cancelled_order_by_shipper(client: TestClient, token_shipper: str) -> None:
    oid = _create_order(client, token_shipper)
    r = client.post(
        f"/api/v1/orders/{oid}/cancel",
        headers=auth_headers(token_shipper),
    )
    assert r.status_code == 200, r.text
    r = client.delete(f"/api/v1/orders/{oid}", headers=auth_headers(token_shipper))
    assert r.status_code == 204, r.text
    r = client.get(f"/api/v1/orders/{oid}", headers=auth_headers(token_shipper))
    assert r.status_code == 404


@pytest.mark.orders
@pytest.mark.shipper
@pytest.mark.fast
def test_cancel_pending_by_shipper(client: TestClient, token_shipper: str) -> None:
    oid = _create_order(client, token_shipper)
    r = client.post(
        f"/api/v1/orders/{oid}/cancel",
        headers=auth_headers(token_shipper),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == OrderStatus.CANCELLED.value
    assert body.get("cancelled_at") is not None


@pytest.mark.orders
@pytest.mark.dispatcher
@pytest.mark.fast
def test_dispatcher_create_order_for_shipper(
    client: TestClient, token_dispatcher: str, users: dict[str, User]
) -> None:
    sid = users["shipper"].id
    r = client.post(
        "/api/v1/orders",
        headers=auth_headers(token_dispatcher),
        json={
            "lines": [
                {
                    "product_name_snapshot": "代下单商品",
                    "quantity": 1,
                    "unit_price": "12.00",
                    "line_total": "12.00",
                }
            ],
            "delivery_description": "代下单",
            "address_detail": "测试地址",
            "shipper_id": sid,
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["shipper_id"] == sid
    assert body["status"] == OrderStatus.PENDING_DISPATCH.value


@pytest.mark.orders
@pytest.mark.dispatcher
@pytest.mark.fast
def test_dispatcher_create_order_temp_shipper_name(
    client: TestClient, token_dispatcher: str
) -> None:
    r = client.post(
        "/api/v1/orders",
        headers=auth_headers(token_dispatcher),
        json={
            "lines": [
                {
                    "product_name_snapshot": "临时单测",
                    "quantity": 1,
                    "unit_price": "12.00",
                    "line_total": "12.00",
                }
            ],
            "delivery_description": "代下单",
            "address_detail": "测试地址",
            "temp_shipper_name": "老王",
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body.get("shipper_id") is None
    assert body.get("temp_shipper_name") == "老王"
    assert body.get("shipper_name") == "老王"
    assert body["status"] == OrderStatus.PENDING_DISPATCH.value
