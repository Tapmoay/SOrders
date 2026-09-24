"""订单出参里「公司付给司机多少」这一族字段的遮蔽（2026-09-24 第 26 轮 01 区 F1）。

## 缺陷长什么样
第 17 轮把货主视角的 `freight_fee` 遮了（理由写在 `order_response.py` 的货主分支里：
他卖货给客户，运费是公司付给司机的钱，露出去了等于把毛利给客户）。但那次是
**手写点掉一个字段**：`freight_visible=False` + `freight_fee=None` + `driver_billing_mode=None`。

第 26 轮 01 区实测：同一笔钱的另外两个出口 ——
`driver_piece_amount`（这一单单独定的每单金额）与 `driver_commission_rate`（提成比例 %），
定义在 `schemas/order.py:181-182`、写入口是派单 body —— **原样下发给了货主**。
也就是说：遮了一个、漏了两个，而两个函数各写一份手写清单。

## 所以修的是机制，不是那一个字段
`order_response.DRIVER_PAY_FIELDS` 一张表 + `hide_driver_pay()` 一处实现。
本文件第 1 条用例从 `OrderOut.model_fields` **自己算**出所有"名字像钱"的字段，
逐个要求归到 `DRIVER_PAY_FIELDS` 或 `CUSTOMER_GOODS_FIELDS` ——
以后再加一个金额字段却忘了想"该不该下发"，红的是这条用例（清单自己算，
而不是等下一轮渗透在真机上发现）。
"""

from __future__ import annotations

import re

import pytest
from starlette.testclient import TestClient

from tests.conftest import auth_headers

#: "名字像钱"的字段形状。**故意写得宽**：宁可多要求一次分类，也不放走一个金额字段。
MONEY_NAME = re.compile(r"(amount|fee|price|total|rate|commission|salary|cost)", re.I)

#: 这些金额字段**人人可见**（不是成本也不是货款，例如订单商品的件数单价由 [OrderProductOut]
#: 逐行门控）。键 = 字段名，值 = 为什么它不需要在这两张表里。
VISIBLE_TO_ALL: dict[str, str] = {}


@pytest.mark.fast
@pytest.mark.regression
def test_订单出参里每个金额字段都被归过类() -> None:
    """⛔ 机制判据：`OrderOut` 上凡是"名字像钱"的字段，必须被归到两张表之一。

    这张清单**不是手写的**（从 `OrderOut.model_fields` 现算），所以新加字段一定会被看见。
    """
    from app.schemas.order import OrderOut
    from app.services.order_response import CUSTOMER_GOODS_FIELDS, DRIVER_PAY_FIELDS

    money_fields = sorted(f for f in OrderOut.model_fields if MONEY_NAME.search(f))
    assert money_fields, "一个金额字段都没扫到 —— 抽取失效了（比漏一个字段更危险）"

    classified = set(DRIVER_PAY_FIELDS) | set(CUSTOMER_GOODS_FIELDS) | set(VISIBLE_TO_ALL)
    missing = [f for f in money_fields if f not in classified]
    assert not missing, (
        "这些金额字段还没归过类（新加的？）："
        f"{missing}\n"
        "  它是「公司付给司机多少」（→ 加进 DRIVER_PAY_FIELDS，货主视角整族遮蔽）、"
        "还是「货主货款」（→ 加进 CUSTOMER_GOODS_FIELDS，司机视角遮蔽/归零）、"
        "还是两者都不是（→ 加进本文件的 VISIBLE_TO_ALL 并写明理由）？\n"
        "  ⚠️ 别直接加进 VISIBLE_TO_ALL 了事：第 17 轮就是「手写点掉一个字段」漏了另外两个。"
    )
    # 表里的字段必须真的还在出参上（防化石：字段删了/改名了，表里那条理由就该删）
    fossils = [f for f in classified if f not in OrderOut.model_fields]
    assert not fossils, f"这两张表里有已经不存在的字段（化石，理由该删）：{fossils}"
    # 两张表不许重叠（同一个字段既算成本又算货款 = 判据自相矛盾）
    both = set(DRIVER_PAY_FIELDS) & set(CUSTOMER_GOODS_FIELDS)
    assert not both, f"同一个字段同时被当成成本与货款：{sorted(both)}"


@pytest.mark.dispatcher
@pytest.mark.fast
@pytest.mark.regression
def test_货主读自己的单拿不到公司付给司机的钱(
    client: TestClient,
    users: dict,
    token_dispatcher: str,
    token_shipper: str,
    db_session,
) -> None:
    """派单时单独定的「每单金额 / 提成比例」不许随订单出参漏给货主。

    ⚠️ 本机那两列当时 **0 行非空**，所以这条缺陷在真机上没有金额实证 ——
    这正是它需要一条**用例**而不是一次手工验证的原因。

    两段：
      ① 真走一遍接口（`freight_fee` 这一格能在派单 body 里给）；
      ② `driver_piece_amount` / `driver_commission_rate` 那两格**接口不给传**
         （派单端点会 400 要求"司机名下先有计费规则"），所以直接落库后调用
         **同一个出参装配函数** —— 本轮修的就是它。
    """
    from decimal import Decimal

    from app.models import Order
    from app.services.order_response import DRIVER_PAY_FIELDS, enrich_order_out

    r = client.post(
        "/api/v1/orders",
        json={
            "shipper_id": users["shipper"].id,
            "lines": [{"product_name_snapshot": "司机成本探针", "quantity": 2, "unit_price": "30.00"}],
            "address_detail": "司机成本探针",
            "delivery_description": "司机成本探针",
        },
        headers=auth_headers(token_dispatcher),
    )
    assert r.status_code == 201, r.text
    oid = r.json()["id"]

    a = client.post(
        f"/api/v1/orders/{oid}/assign",
        json={"driver_id": users["driver"].id, "freight_fee": "20.00"},
        headers=auth_headers(token_dispatcher),
    )
    assert a.status_code == 200, a.text
    assert a.json()["freight_fee"] == "20.00", a.json()

    # ---- ① 货主：整族都不许有 ----
    sh = client.get(f"/api/v1/orders/{oid}", headers=auth_headers(token_shipper))
    assert sh.status_code == 200, sh.text
    body = sh.json()
    for f in DRIVER_PAY_FIELDS:
        assert body[f] is None, f"货主不该拿到 {f}（这是公司付给司机的钱）：{body[f]!r}"
    # 货主自己的货款照旧要给（遮的是成本，不是把他的数一起遮了）
    assert body["goods_amount"] == "60.00", body
    assert body["internal_notes"] == "", body

    # ---- ② 派单员单独定的那两格（走同一个装配函数） ----
    order = db_session.get(Order, oid)
    order.driver_piece_amount = Decimal("7.50")
    order.driver_commission_rate = Decimal("8")
    db_session.commit()

    shipper_view = enrich_order_out(order, db_session, users["shipper"])
    for f in DRIVER_PAY_FIELDS:
        assert getattr(shipper_view, f) is None, f"货主不该拿到 {f}：{getattr(shipper_view, f)!r}"
    assert shipper_view.freight_visible is False

    # 派单员自己照旧看得见（这三样是他填的、界面要回显）
    disp_view = enrich_order_out(order, db_session, users["dispatcher"])
    assert disp_view.freight_visible is True
    assert str(disp_view.freight_fee) == "20.00"
    assert str(disp_view.driver_piece_amount) == "7.50"
    assert str(disp_view.driver_commission_rate) == "8.00"  # 金额统一两位小数
