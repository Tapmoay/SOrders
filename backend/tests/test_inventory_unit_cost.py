"""进货时录入成本价（2026-09-19 用户要求）。

## 用户的原话与这条功能的口径
> 「成本价也是可以进行调整的，包括进货的时候也要输入成本价，
>   因为可能这个时间的进货和那个时间进货的成本价是不一样的」

所以入库（`change > 0`）可以带一个 `unit_cost`，填了就把商品的 `cost_price`
更新成它 —— 商品成本 = **最近一次进货价**。订单在下单时把当时的成本定格成
`order_products.cost_price_snapshot`，毛利按快照算，所以"卖的时候那批货的进货价"
就是它。

⚠️ **这是近似口径，不是分批成本（FIFO / 加权平均）**：100 件 ¥10 与 100 件 ¥12 之后，
商品成本是 ¥12，卖旧货那几单的毛利会偏低。要精确到批次是另一件事（要改毛利口径），
用户没有要求 —— 所以这个文件**也不假装**它是分批成本。

## 这个文件守四件事
1. 入库带 `unit_cost` → 商品成本价真的变了；
2. 入库**不带** → 成本价一个字都不动（只动库存）；
3. **出库带价 → 400**（不是"接受但静默无效"—— 那正是本项目最贵的一类坑）；
4. 成本价的变化**进操作日志**（旧价 → 新价），否则"这个月毛利怎么变了"在审计页上查不到原因。
"""
from __future__ import annotations

import json
import random

import pytest
from starlette.testclient import TestClient

from tests.conftest import auth_headers


def _uniq(prefix: str) -> str:
    return f"{prefix}-{random.randint(1000, 9999)}"


def _mk_product(client: TestClient, h: dict[str, str], cost: str = "0") -> dict:
    r = client.post(
        "/api/v1/products",
        json={
            "name": _uniq("进货价探针"),
            "default_unit_price": "20",
            "cost_price": cost,
            "unit": "件",
            "stock": 0,
            "category": _uniq("进货价分类"),
        },
        headers=h,
    )
    assert r.status_code == 201, r.text
    return r.json()


def _product(client: TestClient, h: dict[str, str], pid: int) -> dict:
    r = client.get(f"/api/v1/products/{pid}", headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def _last_inventory_log(client: TestClient, h: dict[str, str]) -> dict | None:
    """最近一条库存调整日志的 payload。

    ⚠️ 出参字段叫 **`change_content`**（字符串，里面是 JSON），不是 `change_payload`
    （那是 `write_log` 的入参名）—— 第一版就是按入参名找的，结果拿到 `{}`。
    列表按 `id desc`，所以第一条 INVENTORY_ADJUST 就是刚才那一次。
    """
    r = client.get("/api/v1/operation-logs", params={"limit": 50}, headers=h)
    assert r.status_code == 200, r.text
    for row in r.json():
        if row.get("action") != "INVENTORY_ADJUST":
            continue
        raw = row.get("change_content")
        if isinstance(raw, str) and raw.strip():
            return json.loads(raw)
        return {}
    return None


@pytest.mark.dispatcher
@pytest.mark.fast
@pytest.mark.regression
def test_入库带进货价会更新商品成本价(client: TestClient, token_dispatcher: str) -> None:
    """这条功能的**全部意义**：进货价录进去之后，商品成本价真的变了。"""
    h = auth_headers(token_dispatcher)
    p = _mk_product(client, h, cost="0")

    r = client.post(
        "/api/v1/inventory/movements",
        json={"product_id": p["id"], "change": 100, "note": "第一次进货", "unit_cost": "8.5"},
        headers=h,
    )
    assert r.status_code == 201, r.text
    assert float(_product(client, h, p["id"])["cost_price"]) == 8.5
    assert _product(client, h, p["id"])["stock"] == 100, "库存也该跟着进"


@pytest.mark.dispatcher
@pytest.mark.fast
@pytest.mark.regression
def test_入库不带进货价则成本价一个字都不动(client: TestClient, token_dispatcher: str) -> None:
    """不填只改库存 —— 盘点补录这种场景不该顺手把成本价抹成 0。"""
    h = auth_headers(token_dispatcher)
    p = _mk_product(client, h, cost="7.25")

    r = client.post(
        "/api/v1/inventory/movements",
        json={"product_id": p["id"], "change": 5, "note": "盘点补录"},
        headers=h,
    )
    assert r.status_code == 201, r.text
    assert float(_product(client, h, p["id"])["cost_price"]) == 7.25, "没填进货价却改了成本价"
    assert _product(client, h, p["id"])["stock"] == 5


@pytest.mark.dispatcher
@pytest.mark.fast
@pytest.mark.regression
def test_出库带进货价会被拒绝而不是静默无效(client: TestClient, token_dispatcher: str) -> None:
    """⛔ 出库带价必须报错：收下但不生效，正是本项目最贵的一类坑。"""
    h = auth_headers(token_dispatcher)
    p = _mk_product(client, h, cost="9")
    client.post("/api/v1/inventory/movements", json={"product_id": p["id"], "change": 10}, headers=h)

    r = client.post(
        "/api/v1/inventory/movements",
        json={"product_id": p["id"], "change": -3, "unit_cost": "5"},
        headers=h,
    )
    assert r.status_code == 400, r.text
    assert "入库" in r.json()["detail"]
    # 被拒的那次**什么都没写**：库存没动、成本没动
    assert _product(client, h, p["id"])["stock"] == 10
    assert float(_product(client, h, p["id"])["cost_price"]) == 9


@pytest.mark.dispatcher
@pytest.mark.fast
@pytest.mark.regression
def test_成本价的变化进操作日志_旧价到新价(client: TestClient, token_dispatcher: str) -> None:
    """不然"这个月毛利怎么变了"在审计页上查不到原因。"""
    h = auth_headers(token_dispatcher)
    p = _mk_product(client, h, cost="3")
    client.post(
        "/api/v1/inventory/movements",
        json={"product_id": p["id"], "change": 20, "unit_cost": "4.75"},
        headers=h,
    )
    payload = _last_inventory_log(client, h)
    assert payload is not None, "库存调整没写操作日志"
    assert payload.get("product_id") == p["id"]
    assert "cost_before" in payload and "cost_after" in payload, (
        "成本价变了却只在 payload 里记了库存 —— 审计页上看不出「这个月毛利为什么变了」"
    )
    assert float(payload["cost_before"]) == 3
    assert float(payload["cost_after"]) == 4.75


@pytest.mark.dispatcher
@pytest.mark.fast
@pytest.mark.regression
def test_进货价填成负数会被拒(client: TestClient, token_dispatcher: str) -> None:
    """成本价不可能为负（schema 层 `ge=0`）。"""
    h = auth_headers(token_dispatcher)
    p = _mk_product(client, h)
    r = client.post(
        "/api/v1/inventory/movements",
        json={"product_id": p["id"], "change": 1, "unit_cost": "-2"},
        headers=h,
    )
    assert r.status_code == 422, r.text
