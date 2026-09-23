"""「公司付给司机多少」不该给货主看（2026-09-23 第 17 轮并行渗透抓到，动的是**出参口径**）。

## 抓到的是什么（中 · 信息泄露）

`order_response.enrich_order_out` 对货主那一支只清了 `internal_notes`，却把
`freight_visible` 置成 **True**，而 `freight_fee` / `driver_billing_mode` **原样下发** ——
实测货主读自己的单与派单员读同一张单**逐字节相同**。

而界面上这一块是**派单员专属**的（`ui/order/OrderDetailScreen.kt:971` 那个
「收款与挂账」整块在 `role == Role.DISPATCHER` 里），AI 的行格式化还会把它原样带给模型
（`ai/AiResources.kt:1004/1155`）。也就是说：**界面藏住了、接口与 AI 都没藏**。

这是**公司的成本**（货主卖货、公司付运费给司机），露给客户等于把毛利给了他。
修法：货主视角与司机视角在**同一个位置**收口 —— `freight_visible=False` 且两个字段置 None。

## 判据
同一张单、三个角色各读一次：派单员看得到、货主看不到、司机按"这一单有没有按单应付"决定。
"""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from tests.conftest import auth_headers


@pytest.mark.dispatcher
@pytest.mark.integration
def test_货主读自己的单不许带出运费与司机计费(
    client: TestClient, users, token_shipper: str, token_dispatcher: str, token_driver: str
) -> None:
    from tests.test_driver_billing_api import _mk_driver

    driver_id, driver_tok = _mk_driver(client, token_dispatcher, vehicle="trailer")
    r = client.post(
        "/api/v1/orders",
        headers=auth_headers(token_shipper),
        json={"lines": [{"product_name_snapshot": "运费口径探针", "quantity": 1, "unit_price": "500"}],
              "delivery_description": "运费口径探针"},
    )
    assert r.status_code == 201, r.text
    oid = int(r.json()["id"])
    assert client.post(
        f"/api/v1/orders/{oid}/assign",
        headers=auth_headers(token_dispatcher),
        json={"driver_id": driver_id, "freight_fee": "88.00"},
    ).status_code == 200

    ship = client.get(f"/api/v1/orders/{oid}", headers=auth_headers(token_shipper)).json()
    disp = client.get(f"/api/v1/orders/{oid}", headers=auth_headers(token_dispatcher)).json()

    assert disp["freight_fee"] is not None, "前置：派单员本来就该看得到这一单的运费"
    assert ship["freight_fee"] is None, (
        f"货主读到了「公司付给司机的运费」{ship['freight_fee']!r} —— 这是公司成本，不该给客户"
    )
    assert ship["driver_billing_mode"] is None, "货主不该知道司机的计费方式"
    assert ship["freight_visible"] is False, (
        "货主视角的 `freight_visible` 必须是 False（它原来被置成 True，与界面「派单员专属」相反）"
    )
    # ⚠️ 司机那一侧**不在这里断言**：司机读单走的是另一份出参（连 `freight_visible` 这个键都没有），
    #    它的门控 `apply_driver_view_gating` 有自己的用例（`tests/test_driver_view_gating.py`）。
    #    这条用例只管"货主这一支"—— 一次只钉一件事，失败时才知道是谁坏了。
