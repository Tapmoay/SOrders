"""stats 端点：GET /stats/shipper-performance（按货主聚合订单数与订单金额）。

口径与 load_delivered_orders 一致：status=DELIVERED 且 order_date 落在 [date_from, date_to]。
无系统账号的货主按 orders.temp_shipper_name 归组；有账号货主名取 User.full_name or User.phone。
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from starlette.testclient import TestClient

from app.models.enums import OrderStatus
from tests.conftest import auth_headers


def _dec(v: object) -> Decimal:
    """JSON 里的金额可能是字符串或数字，统一按 Decimal 比较。"""
    return Decimal(str(v))


def _new_phone() -> str:
    """11 位、1 开头，随机后缀避免与其它用例/历史数据撞号。"""
    return f"1{uuid4().int % 10**10:010d}"


def _ensure_shipper(client: TestClient, h: dict[str, str], full_name: str) -> dict:
    r = client.post(
        "/api/v1/users",
        json={
            "phone": _new_phone(),
            "password": "pass12345",
            "full_name": full_name,
            "role": "shipper",
        },
        headers=h,
    )
    assert r.status_code == 201, r.text
    return r.json()


def _create_order(
    client: TestClient,
    headers: dict[str, str],
    *,
    line_total: str,
    shipper_id: int | None = None,
    temp_shipper_name: str | None = None,
) -> dict:
    payload: dict = {
        "lines": [
            {
                "product_name_snapshot": "统计商品",
                "quantity": 1,
                "unit_price": line_total,
                "line_total": line_total,
            }
        ],
        "delivery_description": "shipper-performance 测试",
        "address_detail": "统计测试地址",
    }
    if shipper_id is not None:
        payload["shipper_id"] = shipper_id
    if temp_shipper_name is not None:
        payload["temp_shipper_name"] = temp_shipper_name
    r = client.post("/api/v1/orders", json=payload, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def _deliver(
    client: TestClient,
    h_dispatcher: dict[str, str],
    h_driver: dict[str, str],
    order_id: int,
    driver_id: int,
) -> None:
    r = client.post(
        f"/api/v1/orders/{order_id}/assign",
        json={"driver_id": driver_id},
        headers=h_dispatcher,
    )
    assert r.status_code == 200, r.text
    r = client.post(f"/api/v1/orders/{order_id}/driver-ack", headers=h_driver)
    assert r.status_code == 200, r.text
    r = client.post(
        f"/api/v1/orders/{order_id}/complete",
        json={
            "delivery_photo_urls": ["/static/uploads/delivery/test1.jpg"],
            "driver_remark": "ok",
        },
        headers=h_driver,
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == OrderStatus.DELIVERED.value


def _query(client: TestClient, h: dict[str, str], day: str) -> dict:
    r = client.get(
        "/api/v1/stats/shipper-performance",
        params={"date_from": day, "date_to": day},
        headers=h,
    )
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.dispatcher
@pytest.mark.integration
def test_shipper_performance_groups_user_and_temp_shippers(
    client: TestClient, token_dispatcher: str, token_driver: str, users: dict
) -> None:
    """有账号货主按 user_id 归组、无账号货主按 temp_shipper_name 归组；按订单数降序。"""
    h = auth_headers(token_dispatcher)
    hd = auth_headers(token_driver)
    did = users["driver"].id
    tag = uuid4().hex[:8]

    shipper_a = _ensure_shipper(client, h, f"统计货主A{tag}")
    temp_name = f"统计临时货主{tag}"

    # A：2 单，各 10.00 → 20.00
    o1 = _create_order(client, h, line_total="10.00", shipper_id=shipper_a["id"])
    _deliver(client, h, hd, int(o1["id"]), did)
    o2 = _create_order(client, h, line_total="10.00", shipper_id=shipper_a["id"])
    _deliver(client, h, hd, int(o2["id"]), did)
    # 临时货主：1 单 10.00
    o3 = _create_order(client, h, line_total="10.00", temp_shipper_name=temp_name)
    _deliver(client, h, hd, int(o3["id"]), did)

    day = str(o1["order_date"])
    body = _query(client, h, day)
    assert body["period_label"] == f"{day} ~ {day}"
    rows = body["shippers"]
    assert rows

    # 全局按订单数降序
    counts = [x["order_count"] for x in rows]
    assert counts == sorted(counts, reverse=True)

    by_name = {x["shipper_name"]: x for x in rows}
    row_a = next(x for x in rows if x["shipper_id"] == shipper_a["id"])
    assert row_a["shipper_name"] == f"统计货主A{tag}"  # full_name 优先
    assert row_a["order_count"] == 2
    assert _dec(row_a["total_amount"]) == Decimal("20.00")

    row_t = by_name[temp_name]
    assert row_t["shipper_id"] is None  # 无账号货主：按 temp_shipper_name 归组，不丢单
    assert row_t["order_count"] == 1
    assert _dec(row_t["total_amount"]) == Decimal("10.00")

    # 2 单的货主排在 1 单的临时货主之前
    names = [x["shipper_name"] for x in rows]
    assert names.index(f"统计货主A{tag}") < names.index(temp_name)


@pytest.mark.dispatcher
@pytest.mark.integration
def test_shipper_performance_name_falls_back_to_phone(
    client: TestClient, token_dispatcher: str, token_driver: str, users: dict
) -> None:
    """货主姓名为空时用手机号做展示名（User.full_name or User.phone）。"""
    h = auth_headers(token_dispatcher)
    hd = auth_headers(token_driver)

    shipper_b = _ensure_shipper(client, h, "")
    assert shipper_b["full_name"] == ""

    o1 = _create_order(client, h, line_total="7.00", shipper_id=shipper_b["id"])
    _deliver(client, h, hd, int(o1["id"]), users["driver"].id)

    body = _query(client, h, str(o1["order_date"]))
    row = next(x for x in body["shippers"] if x["shipper_id"] == shipper_b["id"])
    assert row["shipper_name"] == shipper_b["phone"]
    assert row["order_count"] == 1
    assert _dec(row["total_amount"]) == Decimal("7.00")


@pytest.mark.dispatcher
def test_shipper_performance_requires_dates_and_permission(
    client: TestClient, token_dispatcher: str, token_shipper: str
) -> None:
    h = auth_headers(token_dispatcher)
    # 两个日期必填（与 driver-performance 一致）
    assert client.get("/api/v1/stats/shipper-performance", headers=h).status_code == 422
    assert (
        client.get(
            "/api/v1/stats/shipper-performance",
            params={"date_from": "2026-01-01"},
            headers=h,
        ).status_code
        == 422
    )
    # 区间内无订单 → 空列表（不是 500 / 不是缺 key）
    empty = _query(client, h, "2000-01-01")
    assert empty["shippers"] == []
    # 权限：货主无权
    denied = client.get(
        "/api/v1/stats/shipper-performance",
        params={"date_from": "2000-01-01", "date_to": "2000-01-02"},
        headers=auth_headers(token_shipper),
    )
    assert denied.status_code == 403
