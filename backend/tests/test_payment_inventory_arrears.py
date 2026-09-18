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
        # 派单员代理下单必须指明货主：shipper_id 或 temp_shipper_name 二选一，
        # 否则 create_order 返回 400「代理下单请选择货主或填写临时货主姓名」。
        "temp_shipper_name": "测试货主",
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


def test_inventory_summary_below_alert_filter(client, token_dispatcher, token_shipper):
    """below_alert=true 只返回 low_stock_alert>0 且 stock<=low_stock_alert（与 Android 标红判断一致）。"""
    h = auth_headers(token_dispatcher)

    def _mk(name: str, stock: int, alert: int) -> int:
        r = client.post(
            "/api/v1/products",
            json={
                "name": name,
                "default_unit_price": "1",
                "stock": stock,
                "low_stock_alert": alert,
            },
            headers=h,
        )
        assert r.status_code == 201, r.text
        assert r.json()["stock"] == stock
        return int(r.json()["id"])

    below_id = _mk("低于报警线", 5, 10)
    equal_id = _mk("等于报警线", 10, 10)
    above_id = _mk("高于报警线", 100, 10)
    no_alert_id = _mk("未设阈值", 0, 0)

    all_rows = client.get("/api/v1/inventory/summary", headers=h)
    assert all_rows.status_code == 200, all_rows.text
    all_ids = {r["product_id"] for r in all_rows.json()}
    # 默认行为不变：四个商品都在（阈值 0 的也在）
    assert {below_id, equal_id, above_id, no_alert_id} <= all_ids

    only = client.get("/api/v1/inventory/summary", params={"below_alert": "true"}, headers=h)
    assert only.status_code == 200, only.text
    rows = only.json()
    only_ids = {r["product_id"] for r in rows}
    assert below_id in only_ids
    assert equal_id in only_ids  # 等于阈值也算达标（<=）
    assert above_id not in only_ids  # 高于阈值不算
    assert no_alert_id not in only_ids  # 阈值 0 = 不报警，不算达标
    assert only_ids <= all_ids
    # 返回的每一行都确实达标（不依赖共享库里其它商品）
    assert all(r["low_stock_alert"] > 0 and r["stock"] <= r["low_stock_alert"] for r in rows)

    # 显式 false 与默认（不传）等价
    same = client.get("/api/v1/inventory/summary", params={"below_alert": "false"}, headers=h)
    assert same.status_code == 200, same.text
    assert [r["product_id"] for r in same.json()] == [r["product_id"] for r in all_rows.json()]

    # 权限未变：货主仍 403
    denied = client.get("/api/v1/inventory/summary", headers=auth_headers(token_shipper))
    assert denied.status_code == 403


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


def _receipt(client, h, customer_id: int, amount: str, order_ids: list[int], mode: str = "itemized"):
    return client.post(
        "/api/v1/ledger/receipts",
        headers=h,
        json={"customer_id": customer_id, "amount": amount, "method": "cash",
              "settle_mode": mode, "order_ids": order_ids, "received_at": "2026-09-18"},
    )


def test_同一张单不能被逐单核销两次(client, token_dispatcher, token_shipper):
    """v3.39 探针实测的缺陷：同一张单可以核销两次 → 两条收款记录、两条现金流水。

    "逐单核销"的语义是"这张单的钱收齐了"（amount 必须等于订单合计），所以第二次必然是多记，
    账上会多出一笔**从没收到的钱**，而且两条记录看起来都完全正常。
    """
    h = auth_headers(token_dispatcher)
    # 用货主本人的账号下单，订单才会挂在它的客户档案下
    hs = auth_headers(token_shipper)
    order = client.post(
        "/api/v1/orders", headers=hs,
        json={"lines": [{"product_name_snapshot": "核销探针货", "quantity": 1,
                         "unit_price": "100.00", "line_total": "100.00"}],
              "delivery_description": "核销探针"},
    )
    assert order.status_code == 201, order.text
    oid = order.json()["id"]

    me = client.get("/api/v1/users/me", headers=hs).json()
    # 客户档案不是下单时自动建的（要派单员在「客户管理」里建/合并），所以这里显式建一条
    # 并绑到该货主的 user_id —— 逐单核销要求"订单的 shipper_id 等于客户档案的 user_id"。
    cust = client.post("/api/v1/customers", headers=h,
                       json={"name": f"核销探针客户-{oid}", "user_id": me["id"]})
    assert cust.status_code in (200, 201), cust.text
    customer_id = cust.json()["id"]

    first = _receipt(client, h, customer_id, "100.00", [oid])
    assert first.status_code in (200, 201), first.text

    again = _receipt(client, h, customer_id, "100.00", [oid])
    assert again.status_code == 400, again.text
    assert "已经收过款" in again.json()["detail"]
    assert "滚动收款" in again.json()["detail"]   # 要告诉用户补差额该怎么做

    # 证据：这张单在收款记录里只出现一次
    rows = client.get("/api/v1/ledger/receipts", headers=h).json()
    hits = [x for x in rows if oid in (x.get("order_ids") or [])]
    assert len(hits) == 1, f"同一张单出现了 {len(hits)} 条收款记录"


def test_逐单核销仍然可以滚动作补差额(client, token_dispatcher, token_shipper):
    """拦住重复核销之后，补差额这条正当需求必须还有路可走（滚动收款）。"""
    h = auth_headers(token_dispatcher)
    hs = auth_headers(token_shipper)
    order = client.post(
        "/api/v1/orders", headers=hs,
        json={"lines": [{"product_name_snapshot": "补差探针货", "quantity": 1,
                         "unit_price": "50.00", "line_total": "50.00"}],
              "delivery_description": "补差探针"},
    )
    oid = order.json()["id"]
    me = client.get("/api/v1/users/me", headers=hs).json()
    cust = client.post("/api/v1/customers", headers=h,
                       json={"name": f"补差探针客户-{oid}", "user_id": me["id"]})
    assert cust.status_code in (200, 201), cust.text
    customer_id = cust.json()["id"]

    assert _receipt(client, h, customer_id, "50.00", [oid]).status_code in (200, 201)
    # 补差额：不绑单（rolling），金额随便给 —— 这条路必须通
    extra = _receipt(client, h, customer_id, "20.00", [], mode="rolling")
    assert extra.status_code in (200, 201), extra.text
