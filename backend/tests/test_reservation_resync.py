"""订单商品行变更后，库存**预占**必须跟着重算（2026-09-19 审计的缺陷 K1）。

## 这个文件钉住的真实缺陷
预占（RESERVED 流水）是**派单那一刻**按当时的订单行生成的，而实扣发生在送达时、
且 `auto_stock_commit` 是**按流水**扣的（`prod.stock += m.change`），**从不读订单行**。
`_order_allows_line_edit` 又是**故意**允许"待派单/派单中/已接单"改行的。于是四种形状全部错账，
而且全程 200、没有任何报错：

| 改法 | 原来的后果 |
|---|---|
| 数量 2 → 5 | 送达只扣 2（订单写 5） |
| 加一行 | 新行没有预占 → 这件货**永远不扣库** |
| 删一行 | 流水还在 → 照扣一件不存在的货 |
| 换商品 | 扣到旧商品头上、新商品不扣 |

修法不是禁止改行（司机没出发时改数量是真实需求），而是改完按**商品逐一对账**补齐预占。
"""
from __future__ import annotations

from sqlalchemy import select

from app.models import InventoryMovement, Product
from tests.conftest import auth_headers


def _mk_product(client, h, name: str, stock: int = 100) -> int:
    r = client.post(
        "/api/v1/products",
        json={"name": name, "default_unit_price": "10", "cost_price": "4", "stock": stock},
        headers=h,
    )
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


def _mk_order(client, h_dispatcher, shipper_id: int, pid: int, qty: int) -> dict:
    r = client.post(
        "/api/v1/orders",
        json={
            "shipper_id": shipper_id,
            "lines": [{
                "product_id": pid, "product_name_snapshot": "预占探针货",
                "quantity": qty, "unit_price": "10", "line_total": str(10 * qty),
            }],
            "address_detail": "预占探针地址",
        },
        headers=h_dispatcher,
    )
    assert r.status_code == 201, r.text
    return r.json()


def _assign(client, h, order_id: int, driver_id: int, freight: str = "20") -> None:
    r = client.post(
        f"/api/v1/orders/{order_id}/assign",
        json={"driver_id": driver_id, "freight_fee": freight},
        headers=h,
    )
    assert r.status_code == 200, r.text


def _reserved(db_session, order_id: int) -> dict[int, int]:
    """该单当前**预占**：product_id → Σchange（负数）。"""
    rows = db_session.scalars(
        select(InventoryMovement).where(
            InventoryMovement.order_id == order_id,
            InventoryMovement.source == "ORDER",
            InventoryMovement.status == "RESERVED",
        )
    ).all()
    out: dict[int, int] = {}
    for m in rows:
        out[m.product_id] = out.get(m.product_id, 0) + int(m.change)
    return out


def _stock(db_session, pid: int) -> int:
    return int(db_session.get(Product, pid).stock or 0)


def test_line_quantity_change_resyncs_reservation(client, db_session, users, token_dispatcher, token_driver):
    """派单后把数量 2 改成 5 → 预占变 -5；送达实扣 5（原来是只扣 2）。"""
    h = auth_headers(token_dispatcher)
    pid = _mk_product(client, h, "预占探针-改量")
    order = _mk_order(client, h, users["shipper"].id, pid, 2)
    _assign(client, h, order["id"], users["driver"].id)
    assert _reserved(db_session, order["id"]) == {pid: -2}
    db_session.expire_all()

    line = client.get(f"/api/v1/order-products?order_id={order['id']}", headers=h).json()[0]
    r = client.patch(f"/api/v1/order-products/{line['id']}", json={"quantity": 5}, headers=h)
    assert r.status_code == 200, r.text
    db_session.expire_all()
    assert _reserved(db_session, order["id"]) == {pid: -5}, "改量后预占必须跟着变"

    stock_before = _stock(db_session, pid)
    hd = auth_headers(token_driver)
    r = client.post(f"/api/v1/orders/{order['id']}/driver-ack", headers=hd)
    assert r.status_code == 200, r.text
    r = client.post(
        f"/api/v1/orders/{order['id']}/complete",
        json={"delivery_photo_urls": ["/static/uploads/delivery/probe.jpg"]},
        headers=hd,
    )
    assert r.status_code == 200, r.text
    db_session.expire_all()
    assert _stock(db_session, pid) == stock_before - 5, "送达必须按**当前订单行**扣库，不是按旧流水"


def test_adding_line_after_assign_reserves_the_new_product(client, db_session, users, token_dispatcher):
    """派单后加一行 → 新商品也要有预占（原来永远不扣库）。"""
    h = auth_headers(token_dispatcher)
    pid1 = _mk_product(client, h, "预占探针-原行")
    pid2 = _mk_product(client, h, "预占探针-新行")
    order = _mk_order(client, h, users["shipper"].id, pid1, 1)
    _assign(client, h, order["id"], users["driver"].id)
    db_session.expire_all()

    r = client.post(
        "/api/v1/order-products",
        json={
            "order_id": order["id"], "product_id": pid2, "product_name_snapshot": "预占探针-新行",
            "quantity": 3, "unit_price": "10", "line_total": "30",
        },
        headers=h,
    )
    assert r.status_code == 201, r.text
    db_session.expire_all()
    assert _reserved(db_session, order["id"]) == {pid1: -1, pid2: -3}


def test_deleting_line_after_assign_releases_its_reservation(client, db_session, users, token_dispatcher):
    """派单后删一行 → 该商品的预占要放掉（原来会照扣一件不存在的货）。"""
    h = auth_headers(token_dispatcher)
    pid = _mk_product(client, h, "预占探针-删行")
    order = _mk_order(client, h, users["shipper"].id, pid, 4)
    _assign(client, h, order["id"], users["driver"].id)
    db_session.expire_all()

    line = client.get(f"/api/v1/order-products?order_id={order['id']}", headers=h).json()[0]
    r = client.delete(f"/api/v1/order-products/{line['id']}", headers=h)
    assert r.status_code == 204, r.text
    db_session.expire_all()
    assert sum(_reserved(db_session, order["id"]).values()) == 0


def test_switching_product_after_assign_moves_the_reservation(client, db_session, users, token_dispatcher):
    """派单后把行换成另一个商品 → 预占要从旧商品挪到新商品（原来扣错商品）。"""
    h = auth_headers(token_dispatcher)
    pid_old = _mk_product(client, h, "预占探针-旧商品")
    pid_new = _mk_product(client, h, "预占探针-新商品")
    order = _mk_order(client, h, users["shipper"].id, pid_old, 2)
    _assign(client, h, order["id"], users["driver"].id)
    db_session.expire_all()

    line = client.get(f"/api/v1/order-products?order_id={order['id']}", headers=h).json()[0]
    r = client.patch(
        f"/api/v1/order-products/{line['id']}",
        json={"product_id": pid_new, "product_name_snapshot": "预占探针-新商品"},
        headers=h,
    )
    assert r.status_code == 200, r.text
    db_session.expire_all()
    assert _reserved(db_session, order["id"]) == {pid_old: 0, pid_new: -2} or \
        _reserved(db_session, order["id"]) == {pid_new: -2}, _reserved(db_session, order["id"])
