"""到仓入库（用户 2026-09-19：「再开一条计算线，这条线是独立算的」）。

| 要钉住的 | 为什么必须是测试 |
|---|---|
| 送到**仓库**的单，送达时按订单商品行 +N | 这是这条线的全部价值；静默不生效在界面上看不出来（订单照样显示已送达） |
| 商品在商品管理里**找不到**的行，跳过且**报出来** | 不报的话用户以为都入库了；而"按名字瞎匹配"会把库存记到别的商品头上（更难查） |
| 同一单**只入一次** | 送达本身有状态机拦着，但补录/重放都可能再走到这里；重复入库 = 库存凭空多一倍 |
| 送到**非仓库**地点的单，一件都不加 | 这条线只该对"标记为仓库"的地点生效；判据要是坏了，等于所有送达都变成入库 |
| 扣减那条线**不受影响** | 两条线各算各的（用户明确要的"独立"）：入库不能顺手把订单的实扣也免掉 |
"""
from __future__ import annotations

from decimal import Decimal

from app.models import InventoryMovement, Product, ShipperLocation, User
from app.services.auth_service import issue_token
from tests.conftest import auth_headers

WAREHOUSE_ADDRESS = "十九轮仓库探针路 1 号"


def _make_driver(client, h, phone: str, name: str) -> tuple[int, dict]:
    r = client.post(
        "/api/v1/users",
        json={
            "phone": phone,
            "password": "pass12345",
            "full_name": name,
            "role": "driver",
            "billing_mode": "PIECE",
        },
        headers=h,
    )
    assert r.status_code == 201, r.text
    return int(r.json()["id"]), {}


def _driver_headers(db_session, driver_id: int) -> dict:
    return auth_headers(issue_token(db_session.get(User, driver_id)))


def _make_product(db_session, name: str, stock: int = 100) -> Product:
    p = Product(name=name, default_unit_price=Decimal("10"), stock=stock)
    db_session.add(p)
    db_session.flush()
    return p


def _make_warehouse(client, h, name: str, address: str) -> int:
    r = client.post(
        "/api/v1/shipper/locations",
        json={"name": name, "detail_address": address, "category": "", "is_warehouse": True},
        headers=h,
    )
    assert r.status_code == 201, r.text
    return int(r.json()["id"])


def _order_to(client, h, shipper_id: int, product: Product, address: str, qty: int = 3) -> int:
    r = client.post(
        "/api/v1/orders",
        json={
            "shipper_id": shipper_id,
            "lines": [
                {
                    "product_id": product.id,
                    "product_name_snapshot": product.name,
                    "quantity": qty,
                    "unit_price": "10",
                    "line_total": str(Decimal("10") * qty),
                }
            ],
            "address_detail": address,
        },
        headers=h,
    )
    assert r.status_code == 201, r.text
    return int(r.json()["id"])


def _deliver(client, h_dispatcher, h_driver, order_id: int, driver_id: int) -> None:
    r = client.post(
        f"/api/v1/orders/{order_id}/assign",
        json={"driver_id": driver_id, "freight_fee": "100"},
        headers=h_dispatcher,
    )
    assert r.status_code == 200, r.text
    assert client.post(f"/api/v1/orders/{order_id}/driver-ack", headers=h_driver).status_code == 200
    r = client.post(
        f"/api/v1/orders/{order_id}/complete",
        json={"delivery_photo_urls": ["/static/uploads/delivery/probe.jpg"]},
        headers=h_driver,
    )
    assert r.status_code == 200, r.text


def _stock(db_session, product_id: int) -> int:
    db_session.expire_all()
    return int(db_session.get(Product, product_id).stock or 0)


def _warehouse_rows(db_session, order_id: int) -> list[InventoryMovement]:
    from sqlalchemy import select

    db_session.expire_all()
    return list(
        db_session.scalars(
            select(InventoryMovement).where(
                InventoryMovement.order_id == order_id,
                InventoryMovement.source == "WAREHOUSE",
            )
        )
    )


def test_delivery_to_warehouse_adds_stock(client, token_dispatcher, users, db_session):
    """送到仓库的单：送达时按订单数量入库（**独立加一条流水**）。"""
    h = auth_headers(token_dispatcher)
    driver_id, _ = _make_driver(client, h, "13900010001", "入库探针司机")
    hd = _driver_headers(db_session, driver_id)
    _make_warehouse(client, h, "入库探针仓", WAREHOUSE_ADDRESS)
    prod = _make_product(db_session, "入库探针货", stock=100)
    db_session.commit()

    oid = _order_to(client, h, users["shipper"].id, prod, WAREHOUSE_ADDRESS, qty=3)
    before = _stock(db_session, prod.id)
    _deliver(client, h, hd, oid, driver_id)

    rows = _warehouse_rows(db_session, oid)
    assert len(rows) == 1, f"应该恰好一条到仓入库流水，实际 {len(rows)}"
    assert int(rows[0].change) == 3, "入库数量必须等于订单数量"
    # 这条线只加不减；订单自己那条线（实扣）**也照旧发生**（各算各的，见 services/warehouse.py）
    assert _stock(db_session, prod.id) == before + 3 - 3, (
        f"净效果应当是 +3（到仓）−3（订单实扣）＝ 不动：{before} → {_stock(db_session, prod.id)}"
    )


def test_到仓入库要扣掉货损(client, token_dispatcher, users, db_session):
    """⛔ 入库数量 = 行数量 − **货损**（2026-09-24 第 29 轮；第 25 轮 02 区 D1）。

    缺陷：原来按**整行数量**入库，于是"客户订 3 件、路上坏了 2 件"这一单会往仓库入 **3** 件 ——
    库存虚增 2，而坏掉那 2 件按仓库自己的规矩（`order_return` 的"货损不回补"）本来就不该算库存。
    两处口径直接矛盾；而且入库那条线原来跑在**货损落库之前**，就算想扣也读不到数。
    """
    from sqlalchemy import select

    from app.models import Order, OrderProduct

    h = auth_headers(token_dispatcher)
    driver_id, _ = _make_driver(client, h, "13900010009", "货损入库探针司机")
    hd = _driver_headers(db_session, driver_id)
    product = _make_product(db_session, "货损入库探针商品", stock=0)
    wh_id = _make_warehouse(client, h, "货损入库探针仓", "货损入库探针地址 9 号")
    order_id = _order_to(client, h, users["shipper"].id, product, "货损入库探针地址 9 号", qty=3)
    assert wh_id  # 仓库点存在（判据在 warehouse_for_order）

    assert client.post(
        f"/api/v1/orders/{order_id}/assign",
        json={"driver_id": driver_id, "freight_fee": "100"},
        headers=h,
    ).status_code == 200
    assert client.post(f"/api/v1/orders/{order_id}/driver-ack", headers=hd).status_code == 200

    db_session.expire_all()
    op = db_session.scalars(
        select(OrderProduct).where(OrderProduct.order_id == order_id)
    ).first()
    r = client.post(
        f"/api/v1/orders/{order_id}/complete",
        json={
            "delivery_photo_urls": ["/static/uploads/delivery/damage.jpg"],
            "damage_items": [{"order_product_id": op.id, "quantity": 2}],
            "damage_note": "路上压坏两件",
        },
        headers=hd,
    )
    assert r.status_code == 200, r.text

    rows = _warehouse_rows(db_session, order_id)
    total_in = sum(int(m.change or 0) for m in rows)
    assert total_in == 1, (
        f"订 3 件、坏 2 件 → 只该入 1 件，实际入了 {total_in} 件"
        f"（入库数量没扣货损，库存会虚增；或者货损那一步还排在入库之后）：{[(m.product_id, m.change) for m in rows]}"
    )
    assert _stock(db_session, product.id) == -2, (
        "订 3 件、坏 2 件：订单那一线扣 3、仓库这一线只入 1 → 净 −2 ——"
        "差的正是「坏了、谁都没有」的那两件（账上同时记了货损 LOSS，两处口径一致）"
    )
    db_session.expire_all()
    assert db_session.get(Order, order_id).status == "DELIVERED"


def test_delivery_to_normal_place_adds_nothing(client, token_dispatcher, users, db_session):
    """送到**非仓库**地点：这条线一件都不许加（判据坏了就等于所有送达都变入库）。"""
    h = auth_headers(token_dispatcher)
    driver_id, _ = _make_driver(client, h, "13900010002", "非仓探针司机")
    hd = _driver_headers(db_session, driver_id)
    _make_warehouse(client, h, "入库探针仓", WAREHOUSE_ADDRESS)
    prod = _make_product(db_session, "非仓探针货", stock=50)
    db_session.commit()

    oid = _order_to(client, h, users["shipper"].id, prod, "十九轮普通收货地址 9 号", qty=2)
    _deliver(client, h, hd, oid, driver_id)

    assert _warehouse_rows(db_session, oid) == [], "不是送到仓库的单不该有到仓入库流水"


def test_warehouse_inbound_is_idempotent(client, token_dispatcher, users, db_session):
    """同一单只入一次（补录/重放再走到这里时不许加第二遍）。"""
    from app.services.warehouse import auto_warehouse_inbound, warehouse_for_order

    h = auth_headers(token_dispatcher)
    driver_id, _ = _make_driver(client, h, "13900010003", "幂等探针司机")
    hd = _driver_headers(db_session, driver_id)
    _make_warehouse(client, h, "入库探针仓", WAREHOUSE_ADDRESS)
    prod = _make_product(db_session, "幂等探针货", stock=10)
    db_session.commit()

    oid = _order_to(client, h, users["shipper"].id, prod, WAREHOUSE_ADDRESS, qty=4)
    _deliver(client, h, hd, oid, driver_id)
    assert len(_warehouse_rows(db_session, oid)) == 1

    # 再走一遍这条线（模拟补录/重放）
    from app.models import Order

    order = db_session.get(Order, oid)
    assert warehouse_for_order(db_session, order) is not None
    again = auto_warehouse_inbound(db_session, order, driver_id)
    db_session.commit()
    assert again["already"] is True and again["inbound"] == 0, f"第二遍不该再入：{again}"
    assert len(_warehouse_rows(db_session, oid)) == 1, "流水也不许变两条"


def test_unknown_product_lines_are_skipped_and_reported(client, token_dispatcher, users, db_session):
    """商品在商品管理里找不到的行：**跳过并报出来**（不许静默丢、也不许按名字瞎匹配）。"""
    h = auth_headers(token_dispatcher)
    driver_id, _ = _make_driver(client, h, "13900010004", "跳过探针司机")
    hd = _driver_headers(db_session, driver_id)
    _make_warehouse(client, h, "入库探针仓", WAREHOUSE_ADDRESS)
    db_session.commit()

    r = client.post(
        "/api/v1/orders",
        json={
            "shipper_id": users["shipper"].id,
            "lines": [
                {
                    "product_name_snapshot": "库里根本没有的货",
                    "quantity": 2,
                    "unit_price": "10",
                    "line_total": "20",
                }
            ],
            "address_detail": WAREHOUSE_ADDRESS,
        },
        headers=h,
    )
    assert r.status_code == 201, r.text
    oid = int(r.json()["id"])
    _deliver(client, h, hd, oid, driver_id)

    assert _warehouse_rows(db_session, oid) == [], "解析不出商品的行不该入库"

    # 跳过这件事必须**留痕**（"没入库"是用户要知道的事实）
    from sqlalchemy import select

    from app.models import OperationLog

    db_session.expire_all()
    logs = list(
        db_session.scalars(select(OperationLog).where(OperationLog.order_id == oid))
    )
    payloads = " ".join(str(x.change_content) for x in logs)
    assert "warehouse_inbound_skipped" in payloads, f"跳过的行没被记下来：{payloads[:300]}"
