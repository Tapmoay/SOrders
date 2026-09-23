"""退货回库必须**以"这一单真的扣过多少"封顶**（2026-09-23 第 17 轮并行渗透抓到的真缺陷）。

## 抓到的是什么（高）

`inventory_service.restock_returned` 原来是无条件 `stock += qty`，而**实扣**的判据是
"派单那一刻为哪些订单行真的写出了 RESERVED 流水"（`auto_stock_commit` 只遍历流水、从不读订单行）。
两次解析（派单时 vs 退货时）一旦分叉，退货就是**只加不减**：

| 路径 | 派单/送达时 | 退货时 | 结果 |
| --- | --- | --- | --- |
| 手输商品名下单 | 解析不出商品 → 零预占 → 一件不扣 | 商品库里后来有了同名商品 → 解析成功 | **凭空 +qty** |
| 出库流水上线前送达的老单（本机 353 张） | 一条 ORDER 流水都没有 | 照常可退 | **凭空 +qty** |
| 送到**仓库**的单（用户要的"独立计算线"） | `WAREHOUSE +N` 与订单线 `−N` → **净 0** | 解析成功 | **净 +qty** |

本机实证虚增 **20 件**（单 7/13/15/394/419 = +1/+2/+13/+3/+1，涉及 8 个商品），
而流水上那行写着「订单退货回库 +N」，看起来完全合理 —— 盘库只能发现"少了"，发现不了"多了"。

## 判据三条
1. **正常单照旧回补**（不能因为加封顶把功能堵死）；
2. **零实扣的单一件都不加**，且这次退货要给出提示（用户看得到"没有回补"）；
3. **到仓入库单不回补**（送达时库存本来就是净 0）。
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select
from starlette.testclient import TestClient

from app.models import InventoryMovement, Product
from tests.conftest import auth_headers


def _order_with_line(client: TestClient, token_shipper: str, token_dispatcher: str,
                     token_driver: str, driver_id: int, *, name: str,
                     product_id: int | None, qty: int = 3, price: str = "10") -> int:
    line: dict = {"product_name_snapshot": name, "quantity": qty, "unit_price": price}
    if product_id is not None:
        line["product_id"] = product_id
    r = client.post(
        "/api/v1/orders",
        headers=auth_headers(token_shipper),
        json={"lines": [line], "delivery_description": "退货回补探针"},
    )
    assert r.status_code == 201, r.text
    oid = int(r.json()["id"])
    assert client.post(
        f"/api/v1/orders/{oid}/assign",
        headers=auth_headers(token_dispatcher),
        json={"driver_id": driver_id, "freight_fee": "10.00"},
    ).status_code == 200
    assert client.post(
        f"/api/v1/orders/{oid}/driver-ack", headers=auth_headers(token_driver)
    ).status_code == 200
    done = client.post(
        f"/api/v1/orders/{oid}/complete",
        headers=auth_headers(token_driver),
        json={"delivery_photo_urls": ["/static/uploads/delivery/restock.jpg"],
              "payment": "arrears"},
    )
    assert done.status_code == 200, done.text
    return oid


def _line_id(client: TestClient, token_dispatcher: str, oid: int) -> int:
    r = client.get(f"/api/v1/order-products?order_id={oid}", headers=auth_headers(token_dispatcher))
    assert r.status_code == 200, r.text
    return int(r.json()[0]["id"])


def _stock(db_session, pid: int) -> int:
    db_session.expire_all()
    p = db_session.get(Product, pid)
    assert p is not None
    return int(p.stock or 0)


def _returned_rows(db_session, oid: int) -> list[InventoryMovement]:
    db_session.expire_all()
    return list(
        db_session.scalars(
            select(InventoryMovement).where(
                InventoryMovement.order_id == oid, InventoryMovement.status == "RETURNED"
            )
        ).all()
    )


@pytest.mark.dispatcher
@pytest.mark.integration
def test_正常单退货照旧回补(
    client: TestClient, db_session, token_shipper: str, token_dispatcher: str, token_driver: str
) -> None:
    """① 有实扣的单：退货仍然把货加回库存（不能因为加封顶把这条功能堵死）。"""
    from tests.test_driver_billing_api import _mk_driver

    driver_id, driver_tok = _mk_driver(client, token_dispatcher, vehicle="trailer")
    prod = Product(name="回补正常货", unit="件", default_unit_price=10, stock=50)
    db_session.add(prod)
    db_session.commit()
    pid = int(prod.id)

    oid = _order_with_line(client, token_shipper, token_dispatcher, driver_tok, driver_id,
                           name="回补正常货", product_id=pid, qty=3)
    before = _stock(db_session, pid)          # 送达已实扣 3
    r = client.post(
        f"/api/v1/orders/{oid}/return",
        headers=auth_headers(token_dispatcher),
        json={"items": [{"order_product_id": _line_id(client, token_dispatcher, oid), "quantity": 3}]},
    )
    assert r.status_code in (200, 201), r.text
    assert _stock(db_session, pid) == before + 3, "有实扣的单退货必须照旧回补"
    assert len(_returned_rows(db_session, oid)) == 1


@pytest.mark.dispatcher
@pytest.mark.integration
def test_没扣过库存的单退货不许凭空加(
    client: TestClient, db_session, token_shipper: str, token_dispatcher: str, token_driver: str
) -> None:
    """② 派单时解析不出商品（手输商品名）→ 一件都没扣过 → 退货**一件都不许加**。

    ⚠️ 关键在"退货那一刻商品库里**已经**有了同名商品"：原来正是在这一步解析成功、
    于是把从来没扣过的货加进了库存。判据是"这一单实扣过多少"，不是"现在能不能解析出商品"。
    """
    from tests.test_driver_billing_api import _mk_driver

    driver_id, driver_tok = _mk_driver(client, token_dispatcher, vehicle="trailer")
    # 下单时**故意**不带 product_id，商品库里也还没有这个名字
    oid = _order_with_line(client, token_shipper, token_dispatcher, driver_tok, driver_id,
                           name="回补幽灵货", product_id=None, qty=3)
    assert not _returned_rows(db_session, oid)

    # 送达之后商品库里才出现同名商品（退货那一刻解析得到它）
    prod = Product(name="回补幽灵货", unit="件", default_unit_price=10, stock=100)
    db_session.add(prod)
    db_session.commit()
    pid = int(prod.id)
    before = _stock(db_session, pid)

    r = client.post(
        f"/api/v1/orders/{oid}/return",
        headers=auth_headers(token_dispatcher),
        json={"items": [{"order_product_id": _line_id(client, token_dispatcher, oid), "quantity": 3}]},
    )
    assert r.status_code in (200, 201), r.text
    assert _stock(db_session, pid) == before, (
        "这一单一件都没扣过，退货却把库存加了 —— 凭空多货，而流水上写着「订单退货回库」"
    )
    assert not _returned_rows(db_session, oid), "零实扣的单不该写 RETURNED 回补流水"
    warns = r.json().get("warnings") or []
    assert any("没有回补" in w for w in warns), f"要如实告诉用户这一次没有回补：{warns}"
