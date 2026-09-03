"""挂账单位 CRUD、库存出入库、订单支付/挂账接口测试（SQLite 文件库）。"""

from __future__ import annotations

from tests.conftest import auth_headers


def _mk_order(client, headers, **over) -> dict:
    payload = {
        "lines": [
            {
                "product_name_snapshot": "水泥",
                "quantity": 10,
                "unit_price": "20",
                "line_total": "200",
            }
        ],
        "address_detail": "测试地址",
    }
    payload.update(over)
    r = client.post("/api/v1/orders", json=payload, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def test_arrears_unit_crud(client, token_dispatcher, token_shipper):
    """挂账单位：货主无权；新增/查重/改/删。"""
    h = auth_headers(token_dispatcher)

    r = client.get("/api/v1/arrears-units", headers=auth_headers(token_shipper))
    assert r.status_code == 403

    r = client.post(
        "/api/v1/arrears-units",
        json={"name": "张三批发部", "phone": "13900000001", "remark": "月底结算"},
        headers=h,
    )
    assert r.status_code == 201, r.text
    uid = r.json()["id"]

    r = client.post("/api/v1/arrears-units", json={"name": "张三批发部"}, headers=h)
    assert r.status_code == 400

    r = client.get("/api/v1/arrears-units", headers=h)
    assert r.status_code == 200
    assert any(u["name"] == "张三批发部" for u in r.json())

    r = client.patch(f"/api/v1/arrears-units/{uid}", json={"remark": "改备注"}, headers=h)
    assert r.status_code == 200
    assert r.json()["remark"] == "改备注"

    r = client.delete(f"/api/v1/arrears-units/{uid}", headers=h)
    assert r.status_code == 204


def test_arrears_unit_delete_blocked_when_used(client, token_dispatcher):
    h = auth_headers(token_dispatcher)
    r = client.post("/api/v1/arrears-units", json={"name": "李四商行"}, headers=h)
    uid = r.json()["id"]

    order = _mk_order(client, h, temp_shipper_name="李四商行")
    oid = order["id"]

    r = client.post(f"/api/v1/orders/{oid}/charge", json={"arrears_unit_id": uid}, headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["payment_method"] == "arrears"
    assert body["paid"] is False
    assert body["arrears_unit_name"] == "李四商行"

    r = client.delete(f"/api/v1/arrears-units/{uid}", headers=h)
    assert r.status_code == 400


def test_inventory_flow(client, token_dispatcher, token_shipper):
    h = auth_headers(token_dispatcher)
    r = client.post(
        "/api/v1/products",
        json={"name": "库存测试商品", "default_unit_price": "15.5", "cost_price": "9.8"},
        headers=h,
    )
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    assert r.json()["stock"] == 0
    # Decimal 按 Numeric(14,4) 序列化为字符串
    assert r.json()["cost_price"] == "9.8000"

    r = client.post(
        "/api/v1/inventory/movements",
        json={"product_id": pid, "change": 100, "note": "首批入库"},
        headers=h,
    )
    assert r.status_code == 201, r.text

    r = client.post(
        "/api/v1/inventory/movements",
        json={"product_id": pid, "change": -30, "note": "销售出库"},
        headers=h,
    )
    assert r.status_code == 201, r.text

    r = client.get("/api/v1/products", headers=h)
    p = next(x for x in r.json() if x["id"] == pid)
    assert p["stock"] == 70

    r = client.post(
        "/api/v1/inventory/movements",
        json={"product_id": pid, "change": -999},
        headers=h,
    )
    assert r.status_code == 400
    assert "库存不足" in r.json()["detail"]

    r = client.get(f"/api/v1/inventory/movements?product_id={pid}", headers=h)
    assert r.status_code == 200
    assert len(r.json()) == 2

    r = client.get("/api/v1/inventory/movements", headers=auth_headers(token_shipper))
    assert r.status_code == 403


def test_order_pay_and_charge(client, token_dispatcher, token_driver):
    h = auth_headers(token_dispatcher)
    order = _mk_order(client, h)
    oid = order["id"]

    o = client.get(f"/api/v1/orders/{oid}", headers=h).json()
    assert o["payment_method"] == "cash"
    assert o["paid"] is False

    # 司机无权收款
    r = client.post(f"/api/v1/orders/{oid}/pay", headers=auth_headers(token_driver))
    assert r.status_code == 403

    # 现场收款
    r = client.post(f"/api/v1/orders/{oid}/pay", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["paid"] is True

    # 已撤销订单不可收款
    oid2 = _mk_order(client, h)["id"]
    r = client.post(f"/api/v1/orders/{oid2}/cancel", headers=h)
    assert r.status_code == 200
    r = client.post(f"/api/v1/orders/{oid2}/pay", headers=h)
    assert r.status_code == 400
