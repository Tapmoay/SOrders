"""`q`（模糊搜索）必须对**所有角色**生效（2026-09-19 审计的缺陷 A3）。

## 原来的样子
`GET /orders?q=...` 只在**派单员**分支里做模糊匹配；货主/司机带 `q` 时后端**静默忽略**，
照样返回他自己的一整页订单。而 AI 的读工具会把请求里带的筛选条件**原样**写进 `filters_used`
（`AiReadService` 的"不悄悄改变语义"承诺）→ 模型以为筛过了，于是：

用户（货主）问「SO202609186557849472 这单送到哪了」→ 模型填 `q=单号` → 后端返回该货主全部订单
里最新的一批 → 工具回报 `filters_used={"q": ...}` 且**没有 ignored_filters** →
模型从一堆无关订单里挑一条回答。**答案是错的，而且看起来很像对的。**

修法：把同一个模糊匹配也用在货主/司机分支上（作用域不变：仍然只在自己的单/自己的任务里搜），
这样"声明生效的筛选条件"就真的生效了。
"""
from __future__ import annotations

from tests.conftest import auth_headers


def _mk_order(client, token_dispatcher, shipper_id: int, desc: str) -> dict:
    r = client.post(
        "/api/v1/orders",
        json={
            "shipper_id": shipper_id,
            "lines": [{"product_name_snapshot": "搜索探针", "quantity": 1, "unit_price": "10"}],
            "address_detail": desc,
            "delivery_description": desc,
        },
        headers=auth_headers(token_dispatcher),
    )
    assert r.status_code == 201, r.text
    return r.json()


def test_shipper_can_search_own_orders_by_order_no(client, users, token_dispatcher, token_shipper):
    """货主按**单号**搜索必须真的筛出那一张（原来返回全部）。"""
    a = _mk_order(client, token_dispatcher, users["shipper"].id, "搜索探针-甲")
    _mk_order(client, token_dispatcher, users["shipper"].id, "搜索探针-乙")

    h = auth_headers(token_shipper)
    r = client.get("/api/v1/orders", params={"q": a["order_no"]}, headers=h)
    assert r.status_code == 200, r.text
    rows = r.json()
    assert len(rows) == 1, f"按单号搜应只回 1 条，实际 {len(rows)} 条（q 被静默忽略了）"
    assert rows[0]["order_no"] == a["order_no"]


def test_shipper_search_miss_returns_empty_not_everything(client, users, token_dispatcher, token_shipper):
    """搜不到就必须是**空**，不能回落成"全部"（那正是 AI 答错单的机制）。"""
    _mk_order(client, token_dispatcher, users["shipper"].id, "搜索探针-丙")
    h = auth_headers(token_shipper)
    r = client.get("/api/v1/orders", params={"q": "ZZZZ_不存在_999"}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json() == [], "搜不到时不许回落成全量"


def test_driver_search_is_scoped_to_own_tasks(client, users, token_dispatcher, token_driver):
    """司机也能搜，但作用域仍是**自己的任务**（越权不在这次修复的范围内，不能被放开）。"""
    mine = _mk_order(client, token_dispatcher, users["shipper"].id, "搜索探针-司机的单")
    other = _mk_order(client, token_dispatcher, users["shipper"].id, "搜索探针-别人的单")
    h = auth_headers(token_dispatcher)
    client.post(f"/api/v1/orders/{mine['id']}/assign",
                json={"driver_id": users["driver"].id, "freight_fee": "20"}, headers=h)

    hd = auth_headers(token_driver)
    r = client.get("/api/v1/orders", params={"q": mine["order_no"]}, headers=hd)
    assert [o["id"] for o in r.json()] == [mine["id"]]
    r2 = client.get("/api/v1/orders", params={"q": other["order_no"]}, headers=hd)
    assert r2.json() == [], "司机的搜索不许越过自己的任务范围"
