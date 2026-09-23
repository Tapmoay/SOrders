"""订单出参里的「订单金额」（2026-09-24 第 24 轮 R8-1，来源第 22 轮 F7-1）。

## 缺陷长什么样
界面上那个「订单金额」一直是**客户端自己 Σ 商品行 `line_total`**
（`ui/order/OrderDetailScreen.kt`、`ui/common/OrderCard.kt`），而**后端出参里没有这个数**：
`OrderOut` 只有 `returned_amount`/`settled_amount`/`refunded_amount`/`arrears_amount` 四个钱。
AI 这一侧更糟：行整形（`AiRowShaper`）把 `order_products` 折成 `order_products_count`，
那三个金额键在 `android/.../ai/` 全包出现 **0 次**。

后果是**换了个答案**而不是"少一个字段"：用户问「这单多少钱」，模型手里只有"欠款"，
于是答成 **0 元 / 已结清**（实测 `SO202607283850318087`：行合计 293.20、
`arrears_amount` 是 `"0.00"`；本机当时 20 张 arrears=0 且 settled>0 的单都会这样）。

用户定的口径是「**人能看到的数，AI 必须也能拿到**」——所以这个数必须由后端给，
而且必须与既有的四个钱**同源**（`services/order_money.py`），否则又多一处口径。
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from starlette.testclient import TestClient

from tests.conftest import auth_headers


def _mk_order(client: TestClient, token_dispatcher: str, shipper_id: int, lines: list[dict]) -> dict:
    r = client.post(
        "/api/v1/orders",
        json={
            "shipper_id": shipper_id,
            "lines": lines,
            "address_detail": "订单金额探针",
            "delivery_description": "订单金额探针",
        },
        headers=auth_headers(token_dispatcher),
    )
    assert r.status_code == 201, r.text
    return r.json()


@pytest.mark.dispatcher
@pytest.mark.fast
@pytest.mark.regression
def test_订单出参带订单金额且等于商品行合计(
    client: TestClient, users: dict, token_dispatcher: str
) -> None:
    """`goods_amount` 必须等于各商品行 `line_total` 之和（多行、两位数单价各测一遍）。"""
    body = _mk_order(
        client,
        token_dispatcher,
        users["shipper"].id,
        [
            {"product_name_snapshot": "金额探针甲", "quantity": 3, "unit_price": "10.25"},
            {"product_name_snapshot": "金额探针乙", "quantity": 2, "unit_price": "7.40"},
        ],
    )
    oid = body["id"]
    assert body["goods_amount"] == "45.55", (
        f"订单金额应当是 3×10.25 + 2×7.40 = 45.55，实际 {body['goods_amount']}"
    )

    # 与商品行逐行对账（行合计只有一处算法：后端 order_money 读的也是这些行的 line_total）
    rows = client.get(
        "/api/v1/order-products", params={"order_id": oid}, headers=auth_headers(token_dispatcher)
    ).json()
    assert sum(Decimal(x["line_total"]) for x in rows) == Decimal("45.55"), rows

    # 详情与列表两条路都要带上（列表走 money_map 批量算，详情走 money_of —— 两条路必须同一个数）
    detail = client.get(f"/api/v1/orders/{oid}", headers=auth_headers(token_dispatcher)).json()
    assert detail["goods_amount"] == "45.55", detail
    listed = client.get(
        "/api/v1/orders", params={"q": "金额探针", "limit": 50}, headers=auth_headers(token_dispatcher)
    ).json()
    hit = [o for o in listed if o["id"] == oid]
    assert hit and hit[0]["goods_amount"] == "45.55", hit[:1]


@pytest.mark.dispatcher
@pytest.mark.fast
@pytest.mark.regression
def test_订单金额能回答这单多少钱_恒等式成立(
    client: TestClient, users: dict, token_dispatcher: str
) -> None:
    """「这单多少钱」= `goods_amount`；并且与四个钱满足那条恒等式。

    ⛔ 这条用例的存在理由：在这之前模型只能拿 `arrears_amount` 顶替 —— 一张**已结清**的单
    arrears 是 0，于是"293.20 元的一单"被答成 **0 元**（那正是第 22 轮 F7-1 实测到的形状）。
    下面同时把"已结清的单里 goods 与 arrears 不相等"这件事钉住，防止有人以为两者可以互替。
    """
    body = _mk_order(
        client,
        token_dispatcher,
        users["shipper"].id,
        [{"product_name_snapshot": "金额探针丙", "quantity": 4, "unit_price": "12.50"}],
    )
    assert body["goods_amount"] == "50.00"
    assert body["arrears_amount"] == "50.00", "还没收款 → 欠款等于订单金额（这一格本来就有）"
    # 恒等式：订单金额 − 已退 == 净已收 + 欠款
    left = Decimal(body["goods_amount"]) - Decimal(body["returned_amount"])
    right = (Decimal(body["settled_amount"]) - Decimal(body["refunded_amount"])) + Decimal(
        body["arrears_amount"]
    )
    assert left == right, f"恒等式不成立：{left} != {right}（{body}）"


@pytest.mark.dispatcher
@pytest.mark.fast
@pytest.mark.regression
def test_司机视角拿不到订单金额(client: TestClient, users: dict, token_dispatcher: str) -> None:
    """司机那条门必须连 `goods_amount` 一起剥 —— 刚剥掉的货款不能从"总额"漏回去。

    `apply_driver_view_gating` 一直把每行的 `unit_price`/`line_total` 置 None
    （"司机无需看到货主货款"）；而订单金额就是那些行之和，留着它等于换个地方又发一遍。
    """
    from app.models import Order
    from app.services.order_response import apply_driver_view_gating

    body = _mk_order(
        client,
        token_dispatcher,
        users["shipper"].id,
        [{"product_name_snapshot": "金额探针丁", "quantity": 1, "unit_price": "9.90"}],
    )
    order = Order(id=body["id"], status="DISPATCHED", driver_id=users["driver"].id,
                  driver_billing_mode_snapshot="PIECE")
    data = {
        "goods_amount": Decimal("9.90"),
        "settled_amount": Decimal("0"),
        "returned_amount": Decimal("0"),
        "refunded_amount": Decimal("0"),
        "arrears_amount": Decimal("9.90"),
        "order_products": [{"unit_price": "9.90", "line_total": "9.90"}],
        "freight_fee": Decimal("5"),
    }
    apply_driver_view_gating(data, order)
    assert data["goods_amount"] is None, "司机不该拿到订单金额（它等于刚被剥掉的那些行之和）"
    assert data["order_products"][0]["line_total"] is None
    # ⛔ 四个钱也要一起归一：`arrears_amount` 同样是货款（没收款的单它恰好等于货款全额），
    #    `settled_amount` 也能反推。⛔ 值是 0 而不是 None —— `OrderDto` 里这四个是非空 String，
    #    发 null 会让客户端反序列化失败（那个口子只留给 unit_price/line_total/freight_fee）。
    for k in ("settled_amount", "returned_amount", "refunded_amount", "arrears_amount"):
        assert data[k] == Decimal("0"), f"司机视角下 {k} 必须是 0（这一块不给他）：{data[k]}"
