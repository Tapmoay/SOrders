"""
Ledger API and sync_order_product_from_ledger via POST /ledger/entries.

Requirements Coverage:
- TC-SP-006: 账本编辑
- TC-SH-005: 查看账本
- FR-SH-004: 我的账本
- FR-SP-004: 货主账本管理
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from starlette.testclient import TestClient

from app.models.enums import OrderStatus

from tests.conftest import auth_headers


def _create_minimal_order(client: TestClient, token_shipper: str) -> int:
    r = client.post(
        "/api/v1/orders",
        headers=auth_headers(token_shipper),
        json={
            "lines": [
                {
                    "product_name_snapshot": "SyncItem",
                    "quantity": 1,
                    "unit_price": "10.00",
                    "line_total": "10.00",
                }
            ],
            "delivery_description": "x",
        },
    )
    assert r.status_code == 201, r.text
    return int(r.json()["id"])


@pytest.mark.ledger
@pytest.mark.orders
@pytest.mark.dispatcher
@pytest.mark.integration
@pytest.mark.smoke
def test_ledger_entry_syncs_matching_order_product(
    client: TestClient,
    token_shipper: str,
    token_dispatcher: str,
    users: dict,
) -> None:
    oid = _create_minimal_order(client, token_shipper)
    r = client.get(f"/api/v1/orders/{oid}", headers=auth_headers(token_dispatcher))
    assert r.status_code == 200
    line = r.json()["order_products"][0]
    assert line["quantity"] == 1

    r = client.post(
        "/api/v1/ledger/entries",
        headers=auth_headers(token_dispatcher),
        json={
            "shipper_id": users["shipper"].id,
            "entry_date": str(date.today()),
            "product_name": "SyncItem",
            "quantity": 4,
            "unit_price": "15.50",
            "total": "62.00",
            "order_id": oid,
            "product_id": None,
            "source": "manual",
            "note": "",
        },
    )
    assert r.status_code == 201, r.text

    r = client.get(f"/api/v1/orders/{oid}", headers=auth_headers(token_dispatcher))
    line2 = r.json()["order_products"][0]
    # MANUAL 账本行不回写订单明细（sync_order_product_from_ledger 对 MANUAL 直接返回）
    assert line2["quantity"] == 1
    assert Decimal(line2["unit_price"]) == Decimal("10.00")


@pytest.mark.ledger
@pytest.mark.shipper
@pytest.mark.integration
def test_shipper_lists_own_ledger(
    client: TestClient,
    token_shipper: str,
    token_dispatcher: str,
    users: dict,
) -> None:
    r = client.post(
        "/api/v1/ledger/entries",
        headers=auth_headers(token_dispatcher),
        json={
            "shipper_id": users["shipper"].id,
            "entry_date": str(date.today()),
            "product_name": "L",
            "quantity": 1,
            "unit_price": "1.00",
            "total": "1.00",
            "order_id": None,
            "product_id": None,
            "source": "manual",
            "note": "",
        },
    )
    assert r.status_code == 201

    r = client.get("/api/v1/ledger/entries", headers=auth_headers(token_shipper))
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) >= 1
    assert all(e["shipper_id"] == users["shipper"].id for e in rows)


@pytest.mark.ledger
@pytest.mark.dispatcher
@pytest.mark.integration
def test_ledger_includes_order_delivery_description_and_sync_endpoint(
    client: TestClient,
    token_shipper: str,
    token_dispatcher: str,
    token_driver: str,
    users: dict,
) -> None:
    r = client.post(
        "/api/v1/orders",
        headers=auth_headers(token_shipper),
        json={
            "lines": [
                {
                    "product_name_snapshot": "SpecWidget",
                    "quantity": 2,
                    "unit_price": "5.00",
                    "line_total": "10.00",
                }
            ],
            "delivery_description": "定制机 A 型 / 红色",
        },
    )
    assert r.status_code == 201, r.text
    oid = int(r.json()["id"])

    r = client.post(
        f"/api/v1/orders/{oid}/assign",
        headers=auth_headers(token_dispatcher),
        json={"driver_id": users["driver"].id},
    )
    assert r.status_code == 200, r.text
    r = client.post(
        f"/api/v1/orders/{oid}/driver-ack",
        headers=auth_headers(token_driver),
    )
    assert r.status_code == 200, r.text
    r = client.post(
        f"/api/v1/orders/{oid}/complete",
        headers=auth_headers(token_driver),
        json={"delivery_photo_urls": ["/static/uploads/delivery/test1.jpg"], "driver_remark": "ok"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == OrderStatus.DELIVERED.value

    r = client.get(
        "/api/v1/ledger/entries",
        params={"shipper_id": users["shipper"].id},
        headers=auth_headers(token_dispatcher),
    )
    assert r.status_code == 200, r.text
    rows = r.json()
    assert len(rows) >= 1
    row0 = next(e for e in rows if e.get("product_name") == "SpecWidget")
    assert row0.get("order_delivery_description") == "定制机 A 型 / 红色"
    assert row0.get("order_id") == oid

    # 造出"这一单没有账本行"的现场：**直接从库里删**，不再走 DELETE 接口——
    # 2026-09-19 审计 R12-M3 之后，已送达订单的账本行**不允许**从接口删
    # （删了它，订单行还在、账本侧少一笔，两个口径永久差这一笔；那条守卫有自己的测试）。
    # 这里要验的是"补账接口能把缺的行补回来"，所以直接制造缺行。
    from app.database import get_db as _get_db  # noqa: F401
    from app.models import Ledger as _Ledger

    from tests.conftest import get_test_session_factory

    db = get_test_session_factory()()
    try:
        db.query(_Ledger).filter(_Ledger.order_id == oid).delete()
        db.commit()
    finally:
        db.close()

    r = client.get(
        "/api/v1/ledger/entries",
        params={"shipper_id": users["shipper"].id},
        headers=auth_headers(token_dispatcher),
    )
    assert not any(e.get("order_id") == oid for e in r.json()), "账本行没删掉，后面的补账就测不出来了"

    r = client.post(
        "/api/v1/ledger/sync-from-delivered-orders",
        headers=auth_headers(token_dispatcher),
        json={"shipper_id": users["shipper"].id},
    )
    assert r.status_code == 200, r.text
    assert r.json().get("orders_synced", 0) >= 1

    r = client.get(
        "/api/v1/ledger/entries",
        params={"shipper_id": users["shipper"].id},
        headers=auth_headers(token_dispatcher),
    )
    rows2 = r.json()
    assert any(e.get("product_name") == "SpecWidget" for e in rows2)


@pytest.mark.ledger
@pytest.mark.dispatcher
@pytest.mark.integration
def test_temp_shipper_ledger_auto_on_order_complete(
    client: TestClient,
    token_dispatcher: str,
    token_driver: str,
    users: dict,
) -> None:
    """临时货主订单在司机送达时即写入账本，无需派单员再手动同步或「创建」账本。"""
    r = client.post(
        "/api/v1/orders",
        headers=auth_headers(token_dispatcher),
        json={
            "lines": [
                {
                    "product_name_snapshot": "临时货商品",
                    "quantity": 2,
                    "unit_price": "3.50",
                    "line_total": "7.00",
                }
            ],
            "delivery_description": "代送",
            "temp_shipper_name": "张临时",
        },
    )
    assert r.status_code == 201, r.text
    oid = int(r.json()["id"])
    assert r.json().get("temp_shipper_name") == "张临时"

    r = client.post(
        f"/api/v1/orders/{oid}/assign",
        headers=auth_headers(token_dispatcher),
        json={"driver_id": users["driver"].id},
    )
    assert r.status_code == 200, r.text
    r = client.post(
        f"/api/v1/orders/{oid}/driver-ack",
        headers=auth_headers(token_driver),
    )
    assert r.status_code == 200, r.text
    r = client.post(
        f"/api/v1/orders/{oid}/complete",
        headers=auth_headers(token_driver),
        json={"delivery_photo_urls": ["/static/uploads/delivery/test1.jpg"], "driver_remark": "送达"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == OrderStatus.DELIVERED.value

    r = client.get(
        "/api/v1/ledger/entries",
        params={"temp_shipper_name": "张临时"},
        headers=auth_headers(token_dispatcher),
    )
    assert r.status_code == 200, r.text
    rows = r.json()
    assert len(rows) >= 1
    assert any(e.get("source") == "order" and e.get("product_name") == "临时货商品" for e in rows)

    r = client.get("/api/v1/ledger/temp-shipper-names", headers=auth_headers(token_dispatcher))
    assert r.status_code == 200, r.text
    assert "张临时" in r.json()
