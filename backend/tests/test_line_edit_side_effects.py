"""订单行变更的**账务连带**：成本快照（2026-09-19 审计的缺陷 K3）。

下单路径一直在写 `cost_price_snapshot`（`order_flow.build_order_products`），
而"派单员后来加一行 / 换商品"这两个入口**从来没写**，于是：

- 加的行成本恒为 0 → 报表把它算成"0 成本、100% 毛利"（毛利虚高），
  司机对这一行报货损时 `apply_damage_accounting` 判 cost<=0 直接跳过 → **损失永远不落账**；
- 换商品不刷新快照 → 这一行仍按**旧商品**的成本算毛利与货损
  （把 50 元成本的货按 10 元记，毛利虚增、货损少记）。

这两条都不报错、界面上也看不出来，只能靠对账发现，所以在这里钉住。
"""
from __future__ import annotations

from app.models import OrderProduct
from tests.conftest import auth_headers


def _mk_product(client, h, name: str, cost: str) -> int:
    r = client.post(
        "/api/v1/products",
        json={"name": name, "default_unit_price": "20", "cost_price": cost, "stock": 50},
        headers=h,
    )
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


def test_added_line_carries_cost_snapshot(client, db_session, users, token_dispatcher):
    """派单员加的一行必须带上**当时**的商品成本快照。"""
    h = auth_headers(token_dispatcher)
    pid = _mk_product(client, h, "成本快照探针-加行", "7.5")
    order = client.post(
        "/api/v1/orders",
        json={
            "shipper_id": users["shipper"].id,
            "lines": [{"product_name_snapshot": "手输行", "quantity": 1, "unit_price": "20"}],
            "address_detail": "成本快照探针",
        },
        headers=h,
    ).json()

    r = client.post(
        "/api/v1/order-products",
        json={
            "order_id": order["id"], "product_id": pid, "product_name_snapshot": "成本快照探针",
            "quantity": 2, "unit_price": "20", "line_total": "40",
        },
        headers=h,
    )
    assert r.status_code == 201, r.text
    db_session.expire_all()
    added = db_session.get(OrderProduct, r.json()["id"])
    assert float(added.cost_price_snapshot) == 7.5, "加行必须定格成本快照（否则毛利虚高、货损不入账）"


def test_switching_product_refreshes_cost_snapshot(client, db_session, users, token_dispatcher):
    """换商品必须同时换成本快照（否则按旧商品的成本算毛利/货损）。"""
    h = auth_headers(token_dispatcher)
    pid_a = _mk_product(client, h, "成本快照探针-A", "10")
    pid_b = _mk_product(client, h, "成本快照探针-B", "50")
    order = client.post(
        "/api/v1/orders",
        json={
            "shipper_id": users["shipper"].id,
            "lines": [{
                "product_id": pid_a, "product_name_snapshot": "成本快照探针-A",
                "quantity": 1, "unit_price": "20", "line_total": "20",
            }],
            "address_detail": "成本快照探针",
        },
        headers=h,
    ).json()
    line_id = client.get(f"/api/v1/order-products?order_id={order['id']}", headers=h).json()[0]["id"]
    db_session.expire_all()
    assert float(db_session.get(OrderProduct, line_id).cost_price_snapshot) == 10.0

    r = client.patch(
        f"/api/v1/order-products/{line_id}",
        json={"product_id": pid_b, "product_name_snapshot": "成本快照探针-B"},
        headers=h,
    )
    assert r.status_code == 200, r.text
    db_session.expire_all()
    assert float(db_session.get(OrderProduct, line_id).cost_price_snapshot) == 50.0, \
        "换商品后成本快照必须跟着换"
