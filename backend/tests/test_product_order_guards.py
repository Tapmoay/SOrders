"""商品与订单行的**金额/引用完整性**护栏（v3.39 缺陷挖掘第一轮的战果）。

这一组测的都是"接口 200、数据落库、界面上看不出来"的东西——真实缺陷里最难发现的一类：

| 现场 | 后果 |
| --- | --- |
| 商品单价/成本可以是负数 | 下单得到负金额订单行 → 账本入账负数、营业额为负 |
| 商品名是纯空格 | 列表里一行空白，点进去才知道是什么 |
| 行金额（`line_total`）由客户端说了算 | 账本、营业额、毛利按行金额入账，而"单价×数量"是另一个数 |
| 商品编号不存在/已删除也能下单 | 成本快照按 0 记（毛利虚高）、送达时不扣库存，两样都不报错 |

判据都锚在**可观察结果**上（状态码 + 落库的值），不锚"调了哪个函数"。
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from starlette.testclient import TestClient

from tests.conftest import auth_headers


def _uniq(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:6]}"


def _mk_product(client: TestClient, tok: str, **kw) -> dict:
    body = {"name": _uniq("探针商品"), "default_unit_price": "10"}
    body.update(kw)
    r = client.post("/api/v1/products", headers=auth_headers(tok), json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _order(client: TestClient, tok: str, lines: list[dict]):
    return client.post(
        "/api/v1/orders",
        headers=auth_headers(tok),
        json={"lines": lines, "delivery_description": "护栏测试"},
    )


# ---------------------------------------------------------------- 商品：取值边界

@pytest.mark.dispatcher
@pytest.mark.fast
@pytest.mark.parametrize(
    "kw, keyword",
    [
        ({"default_unit_price": "-5"}, "greater_than_equal"),   # 负单价
        ({"cost_price": "-3"}, "greater_than_equal"),           # 负成本
        ({"name": "   "}, "空格"),                               # 纯空格名字
    ],
)
def test_商品的价格与名字不许是脏值(client: TestClient, token_dispatcher: str, kw: dict, keyword: str) -> None:
    """负单价/负成本会让订单金额变负；纯空格名字在列表里就是一行空白。"""
    body = {"name": _uniq("脏商品"), **kw}
    r = client.post("/api/v1/products", headers=auth_headers(token_dispatcher), json=body)
    assert r.status_code == 422, r.text
    assert keyword in r.text


@pytest.mark.dispatcher
@pytest.mark.fast
def test_改商品时价格也不许改成负数(client: TestClient, token_dispatcher: str) -> None:
    p = _mk_product(client, token_dispatcher)
    r = client.patch(
        f"/api/v1/products/{p['id']}", headers=auth_headers(token_dispatcher),
        json={"default_unit_price": "-1"},
    )
    assert r.status_code == 422, r.text
    after = client.get(f"/api/v1/products/{p['id']}", headers=auth_headers(token_dispatcher)).json()
    assert Decimal(after["default_unit_price"]) == Decimal("10.0000")


# ---------------------------------------------------------------- 订单行：金额口径

@pytest.mark.dispatcher
@pytest.mark.shipper
@pytest.mark.fast
def test_行金额由服务端算_客户端给了对不上的数要拒绝(
    client: TestClient, token_shipper: str, token_dispatcher: str
) -> None:
    """3 × 10.00 的单，客户端说这一行是 1.00 → 拒绝并说清差多少。"""
    p = _mk_product(client, token_dispatcher)
    r = _order(client, token_shipper, [
        {"product_id": p["id"], "product_name_snapshot": "探针货", "quantity": 3,
         "unit_price": "10.00", "line_total": "1.00"},
    ])
    assert r.status_code == 400, r.text
    assert "对不上" in r.json()["detail"]
    assert "30.00" in r.json()["detail"] and "1.00" in r.json()["detail"]


@pytest.mark.dispatcher
@pytest.mark.shipper
@pytest.mark.fast
def test_行金额的容差只够吸收四舍五入(
    client: TestClient, token_shipper: str, token_dispatcher: str
) -> None:
    """单价 3.3333 × 3 = 9.9999，客户端按分四舍五入成 10.00 —— 这不是错，要收下并统一成 10.00。"""
    p = _mk_product(client, token_dispatcher, default_unit_price="3.3333")
    r = _order(client, token_shipper, [
        {"product_id": p["id"], "product_name_snapshot": "零头货", "quantity": 3,
         "unit_price": "3.3333", "line_total": "10.00"},
    ])
    assert r.status_code == 201, r.text
    assert Decimal(r.json()["order_products"][0]["line_total"]) == Decimal("10.0000")


@pytest.mark.dispatcher
@pytest.mark.shipper
@pytest.mark.fast
def test_不填行金额时服务端自己算(client: TestClient, token_shipper: str, token_dispatcher: str) -> None:
    p = _mk_product(client, token_dispatcher)
    r = _order(client, token_shipper, [
        {"product_id": p["id"], "product_name_snapshot": "探针货", "quantity": 2, "unit_price": "12.50"},
    ])
    assert r.status_code == 201, r.text
    assert Decimal(r.json()["order_products"][0]["line_total"]) == Decimal("25.0000")


# ---------------------------------------------------------------- 订单行：商品引用

@pytest.mark.dispatcher
@pytest.mark.shipper
@pytest.mark.fast
def test_商品编号不在库里就拒绝(client: TestClient, token_shipper: str, token_dispatcher: str) -> None:
    """收下它 = 成本快照按 0 记（毛利虚高）+ 送达不扣库存，两样都不报错。"""
    r = _order(client, token_shipper, [
        {"product_id": 99999999, "product_name_snapshot": "幽灵货", "quantity": 1,
         "unit_price": "10.00", "line_total": "10.00"},
    ])
    assert r.status_code == 400, r.text
    assert "不在商品库里" in r.json()["detail"]


@pytest.mark.dispatcher
@pytest.mark.shipper
@pytest.mark.fast
def test_已删除的商品不许下单(client: TestClient, token_shipper: str, token_dispatcher: str) -> None:
    p = _mk_product(client, token_dispatcher)
    assert client.delete(f"/api/v1/products/{p['id']}", headers=auth_headers(token_dispatcher)).status_code in (200, 204)
    r = _order(client, token_shipper, [
        {"product_id": p["id"], "product_name_snapshot": "已删货", "quantity": 1,
         "unit_price": "10.00", "line_total": "10.00"},
    ])
    assert r.status_code == 400, r.text
    assert "已经删除" in r.json()["detail"]


@pytest.mark.dispatcher
@pytest.mark.shipper
@pytest.mark.fast
def test_手输的自定义商品行仍然可以下单(
    client: TestClient, token_shipper: str, token_dispatcher: str
) -> None:
    """没有 product_id 的行是正当业务（来收一趟货、商品库里没有），不能被上面两条误伤。"""
    r = _order(client, token_shipper, [
        {"product_name_snapshot": "临时收的货", "quantity": 2, "unit_price": "7.00", "line_total": "14.00"},
    ])
    assert r.status_code == 201, r.text
    assert Decimal(r.json()["order_products"][0]["line_total"]) == Decimal("14.0000")


# ---------------------------------------------------------------- 订单行：改行

@pytest.mark.dispatcher
@pytest.mark.shipper
@pytest.mark.fast
def test_改数量时行金额跟着重算(client: TestClient, token_shipper: str, token_dispatcher: str) -> None:
    p = _mk_product(client, token_dispatcher)
    r = _order(client, token_shipper, [
        {"product_id": p["id"], "product_name_snapshot": "探针货", "quantity": 1,
         "unit_price": "10.00", "line_total": "10.00"},
    ])
    oid = r.json()["id"]
    line_id = r.json()["order_products"][0]["id"]
    up = client.patch(
        f"/api/v1/order-products/{line_id}", headers=auth_headers(token_dispatcher),
        json={"quantity": 4},
    )
    assert up.status_code == 200, up.text
    assert Decimal(up.json()["line_total"]) == Decimal("40.0000")
    assert oid > 0


@pytest.mark.dispatcher
@pytest.mark.shipper
@pytest.mark.fast
def test_改行时塞一个对不上的金额也要拒绝(
    client: TestClient, token_shipper: str, token_dispatcher: str
) -> None:
    p = _mk_product(client, token_dispatcher)
    r = _order(client, token_shipper, [
        {"product_id": p["id"], "product_name_snapshot": "探针货", "quantity": 2,
         "unit_price": "10.00", "line_total": "20.00"},
    ])
    line_id = r.json()["order_products"][0]["id"]
    up = client.patch(
        f"/api/v1/order-products/{line_id}", headers=auth_headers(token_dispatcher),
        json={"line_total": "5.00"},
    )
    assert up.status_code == 400, up.text
    assert "对不上" in up.json()["detail"]
    after = client.get(f"/api/v1/order-products/{line_id}", headers=auth_headers(token_dispatcher)).json()
    assert Decimal(after["line_total"]) == Decimal("20.0000")
