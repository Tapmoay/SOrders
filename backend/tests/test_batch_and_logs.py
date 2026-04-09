"""
Batch dispatch and operation log entries (dispatch + recall).

Requirements Coverage:
- TC-SP-002: 批量派单
- TC-SP-004: 编辑订单日志
- 审计日志验证 (DOMAIN_MODEL.md §3)
"""

from __future__ import annotations

import json

import pytest
from starlette.testclient import TestClient

from app.models.enums import OperationAction, OrderStatus
from tests.conftest import auth_headers


def _mk_order(client: TestClient, token_shipper: str, name: str = "BatchItem") -> int:
    r = client.post(
        "/api/v1/orders",
        headers=auth_headers(token_shipper),
        json={
            "lines": [
                {
                    "product_name_snapshot": name,
                    "quantity": 1,
                    "unit_price": "1.00",
                    "line_total": "1.00",
                }
            ],
            "delivery_description": "batch",
        },
    )
    assert r.status_code == 201, r.text
    return int(r.json()["id"])


@pytest.mark.batch
@pytest.mark.orders
@pytest.mark.dispatcher
@pytest.mark.integration
@pytest.mark.smoke
def test_batch_assign_and_operation_logs(
    client: TestClient,
    token_shipper: str,
    token_dispatcher: str,
    users: dict,
) -> None:
    o1 = _mk_order(client, token_shipper, "A")
    o2 = _mk_order(client, token_shipper, "B")
    r = client.post(
        "/api/v1/orders/batch-assign",
        headers=auth_headers(token_dispatcher),
        json={
            "order_ids": [o1, o2],
            "driver_id": users["driver"].id,
            "internal_note": "batch note",
        },
    )
    assert r.status_code == 200, r.text
    results = r.json()["results"]
    assert len(results) == 2
    assert all(x["success"] for x in results)

    r = client.get(
        f"/api/v1/operation-logs?order_id={o1}",
        headers=auth_headers(token_dispatcher),
    )
    assert r.status_code == 200
    logs = r.json()
    actions = {x["action"] for x in logs}
    assert OperationAction.ORDER_DISPATCH.value in actions


@pytest.mark.batch
@pytest.mark.orders
@pytest.mark.dispatcher
@pytest.mark.integration
def test_recall_writes_snapshot_operation_log(
    client: TestClient,
    token_shipper: str,
    token_dispatcher: str,
    users: dict,
) -> None:
    oid = _mk_order(client, token_shipper)
    client.post(
        f"/api/v1/orders/{oid}/assign",
        headers=auth_headers(token_dispatcher),
        json={"driver_id": users["driver"].id},
    )
    r = client.post(
        f"/api/v1/orders/{oid}/recall",
        headers=auth_headers(token_dispatcher),
        json={"reason": "test recall reason"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == OrderStatus.PENDING_DISPATCH.value

    r = client.get(
        f"/api/v1/operation-logs?order_id={oid}",
        headers=auth_headers(token_dispatcher),
    )
    logs = r.json()
    recall = next(
        (x for x in logs if x["action"] == OperationAction.ORDER_RECALL.value), None
    )
    assert recall is not None
    payload = json.loads(recall["change_content"]) if recall["change_content"] else {}
    assert payload.get("reason") == "test recall reason"
    assert "order_snapshot" in payload
