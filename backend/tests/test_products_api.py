"""Product create/delete API smoke tests."""

import pytest
from fastapi.testclient import TestClient

from tests.conftest import auth_headers


@pytest.mark.dispatcher
def test_dispatcher_can_list_products_include_inactive(
    client: TestClient, token_dispatcher: str
) -> None:
    r = client.get(
        "/api/v1/products",
        params={"include_inactive": "true"},
        headers=auth_headers(token_dispatcher),
    )
    assert r.status_code == 200, r.text
    assert isinstance(r.json(), list)


@pytest.mark.shipper
def test_shipper_can_list_products(client: TestClient, token_shipper: str) -> None:
    r = client.get("/api/v1/products", headers=auth_headers(token_shipper))
    assert r.status_code == 200, r.text


@pytest.mark.driver
def test_driver_cannot_list_products(client: TestClient, token_driver: str) -> None:
    r = client.get("/api/v1/products", headers=auth_headers(token_driver))
    assert r.status_code == 403


@pytest.mark.dispatcher
def test_create_product_minimal(client: TestClient, token_dispatcher: str) -> None:
    r = client.post(
        "/api/v1/products",
        json={"name": "测试商品", "default_unit_price": "22", "name_color": None},
        headers=auth_headers(token_dispatcher),
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["name"] == "测试商品"
    assert body["is_active"] is True


@pytest.mark.dispatcher
def test_create_product_name_color_null_omitted(
    client: TestClient, token_dispatcher: str
) -> None:
    r = client.post(
        "/api/v1/products",
        json={"name": "仅必填", "default_unit_price": 1},
        headers=auth_headers(token_dispatcher),
    )
    assert r.status_code == 201, r.text


@pytest.mark.dispatcher
def test_create_product_float_price(client: TestClient, token_dispatcher: str) -> None:
    r = client.post(
        "/api/v1/products",
        json={"name": "浮点价", "default_unit_price": 22.5},
        headers=auth_headers(token_dispatcher),
    )
    assert r.status_code == 201, r.text


@pytest.mark.dispatcher
def test_update_product_name_color_and_active(
    client: TestClient, token_dispatcher: str
) -> None:
    """测试更新商品名称颜色和上架状态"""
    # 创建商品
    r = client.post(
        "/api/v1/products",
        json={"name": "待更新商品", "default_unit_price": 10, "name_color": "#FF0000"},
        headers=auth_headers(token_dispatcher),
    )
    assert r.status_code == 201, r.text
    product_id = r.json()["id"]

    # 更新名称颜色为另一种颜色
    r = client.patch(
        f"/api/v1/products/{product_id}",
        json={
            "name": "待更新商品",
            "default_unit_price": 10,
            "is_active": False,
            "name_color": "#00FF00",
        },
        headers=auth_headers(token_dispatcher),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["name_color"] == "#00FF00"
    assert body["is_active"] is False

    # 更新为 null 清除颜色
    r = client.patch(
        f"/api/v1/products/{product_id}",
        json={
            "name": "待更新商品",
            "default_unit_price": 10,
            "is_active": True,
            "name_color": None,
        },
        headers=auth_headers(token_dispatcher),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["name_color"] is None
    assert body["is_active"] is True
