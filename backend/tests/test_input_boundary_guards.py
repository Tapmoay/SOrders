"""输入边界护栏（2026-09-18 模糊测试挖出来的两类缺陷，各钉一条）。

## 缺陷一：月份是自由字符串 → "生成了但结不掉的幽灵工资单"
`GET /driver-bills?month=` 带 `pattern=^\\d{4}-\\d{2}$`，而 `POST /driver-bills/generate`
的 `month` 原来是自由字符串。于是 `{"month": "fuzz-xxx"}` 会造出一批月份不是月份的工资单：
任何界面按月份都查不到、结算单也永远收不进（结算按 month 取 OPEN 明细）。
实测一次模糊测试造出 70 张、合计 34.5 万。

## 缺陷二：超出数据库范围的整数 → 500
`POST /products {"stock": 10**20}` 在 `db.flush()` 抛
`OverflowError: Python int too large to convert to SQLite INTEGER` → 500。
生产 MySQL 上同样输入是 `DataError: Out of range value` → 也是 500。
现在统一映射成 400 + 中文（逐字段加边界仍是更好的做法，这条是兜底）。
"""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from tests.conftest import auth_headers


@pytest.mark.parametrize("bad_month", ["fuzz-xxx", "2026-9", "2026-13", "", "   ", "2026/09"])
def test_generate_bills_rejects_bad_month(
    client: TestClient, token_dispatcher: str, bad_month: str
) -> None:
    r = client.post(
        "/api/v1/driver-bills/generate",
        json={"month": bad_month, "bill_type": "salary"},
        headers=auth_headers(token_dispatcher),
    )
    assert r.status_code == 422, r.text
    body = r.text
    assert "月份要写成" in body, f"错误信息必须是中文且带正确写法，实际：{body}"
    # 关键：不能"先建后报错"——脏月份一条账单都不许落库
    r2 = client.get("/api/v1/driver-bills", headers=auth_headers(token_dispatcher))
    assert r2.status_code == 200
    assert [b for b in r2.json() if b["month"] == bad_month] == []


def test_generate_bills_accepts_good_month(client: TestClient, token_dispatcher: str) -> None:
    r = client.post(
        "/api/v1/driver-bills/generate",
        json={"month": "2026-08", "bill_type": "salary"},
        headers=auth_headers(token_dispatcher),
    )
    assert r.status_code == 200, r.text
    assert all(b["month"] == "2026-08" for b in r.json())


def test_create_settlement_rejects_bad_month(client: TestClient, token_dispatcher: str) -> None:
    r = client.post(
        "/api/v1/driver-settlements",
        json={"driver_id": 1, "month": "2026-9", "settle_type": "salary"},
        headers=auth_headers(token_dispatcher),
    )
    assert r.status_code == 422, r.text
    assert "月份要写成" in r.text


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("/api/v1/products", {"name": "边界-超大库存", "stock": 10**20}),
        ("/api/v1/customers", {"name": "边界-超大用户号", "user_id": 10**20}),
        ("/api/v1/expenses", {"exp_date": "2026-09-18", "category": "fuel", "amount": "10.00",
                              "driver_id": 10**20}),
        ("/api/v1/ledger/entries", {"entry_date": "2026-09-18", "product_name": "边界",
                                    "shipper_id": 10**20}),
    ],
)
def test_out_of_range_int_is_400_not_500(
    client: TestClient, token_dispatcher: str, path: str, body: dict
) -> None:
    r = client.post(path, json=body, headers=auth_headers(token_dispatcher))
    assert r.status_code == 400, f"{path} 期望 400，实际 {r.status_code}：{r.text[:300]}"
    assert "超出可保存范围" in r.text, f"错误信息要能照着改，实际：{r.text[:300]}"


# --------------------------------------------------------------------------
# 金额上界：钱列是 Numeric(12,2)/(14,4)，上限 9999999999.99。
# 本地 SQLite 原来照单全收（`salary: 1e20` 真的建出来了），生产 MySQL 才 Out of range。
# 现在两边行为一致：拒掉，且是中文。
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("/api/v1/products", {"name": "边界-超大单价", "default_unit_price": 10**20}),
        ("/api/v1/products", {"name": "边界-超大成本", "cost_price": 10**20}),
        ("/api/v1/driver-billing-rules", {"name": "边界-超大工资", "salary": 10**20}),
        ("/api/v1/driver-billing-rules", {"name": "边界-超大每单", "piece_amount": 10**20}),
        ("/api/v1/expenses", {"exp_date": "2026-09-18", "category": "fuel", "amount": 10**20}),
        ("/api/v1/freight-templates", {"name": "边界-超大运费", "fee": 10**20}),
        ("/api/v1/price-rules/batch", {"value": 10**20}),
        ("/api/v1/ledger/entries", {"entry_date": "2026-09-18", "product_name": "边界",
                                    "temp_shipper_name": "边界临时货主", "unit_price": 10**20}),
        ("/api/v1/users", {"phone": "13900001234", "password": "123321", "role": "driver",
                           "salary": 10**20}),
    ],
)
def test_money_above_storable_range_rejected(
    client: TestClient, token_dispatcher: str, path: str, body: dict
) -> None:
    r = client.post(path, json=body, headers=auth_headers(token_dispatcher))
    assert r.status_code == 422, f"{path} 期望 422，实际 {r.status_code}：{r.text[:300]}"
    assert "超出可保存范围" in r.text, f"错误信息要能照着改，实际：{r.text[:300]}"


def test_money_below_limit_still_accepted(client: TestClient, token_dispatcher: str) -> None:
    """上界只能是"存不下"的那条线，不能顺手把正常金额也拦了。"""
    r = client.post(
        "/api/v1/driver-billing-rules",
        json={"name": "边界-正常工资", "salary": "9999999999.99"},
        headers=auth_headers(token_dispatcher),
    )
    assert r.status_code == 201, r.text
    assert r.json()["salary"] == "9999999999.99"


def test_price_batch_absurd_value_changes_nothing(
    client: TestClient, token_dispatcher: str
) -> None:
    """批量调价的 1e20 被拒之后，**一条专属价都不许变**（这是"效果"而非"状态码"的断言）。"""
    before = client.get("/api/v1/price-rules", headers=auth_headers(token_dispatcher)).json()
    r = client.post(
        "/api/v1/price-rules/batch", json={"value": 10**20}, headers=auth_headers(token_dispatcher)
    )
    assert r.status_code == 422, r.text
    after = client.get("/api/v1/price-rules", headers=auth_headers(token_dispatcher)).json()
    assert before == after, "批量调价被拒之后专属价不该有任何变化"


# --------------------------------------------------------------------------
# 经纬度：坐标列是 Numeric(10,7)，本地 SQLite 会存下 1e20；更常见的是"存得下但没意义"
# 的值（lat=500）——那种坐标只有司机按导航走的时候才炸，录入时看不出来。
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("/api/v1/shipper/addresses", {"address_lat": 10**20}),
        ("/api/v1/shipper/addresses", {"address_lng": 10**20}),
        ("/api/v1/shipper/addresses", {"address_lat": "500"}),
        ("/api/v1/shipper/addresses", {"origin_lat": "-91"}),
        ("/api/v1/shipper/locations", {"address_lng": "181"}),
        ("/api/v1/orders", {"lines": [{"product_name_snapshot": "坐标", "quantity": 1,
                                      "unit_price": "1"}], "address_lat": "91"}),
    ],
)
def test_out_of_range_coordinates_rejected(
    client: TestClient, token_dispatcher: str, path: str, body: dict
) -> None:
    r = client.post(path, json=body, headers=auth_headers(token_dispatcher))
    assert r.status_code == 422, f"{path} 期望 422，实际 {r.status_code}：{r.text[:300]}"
    assert "坐标" in r.text, f"坐标的错误信息要说清是坐标，实际：{r.text[:300]}"


def test_valid_coordinates_still_accepted(client: TestClient, token_dispatcher: str) -> None:
    r = client.post(
        "/api/v1/shipper/locations",
        json={"name": "边界-天安门", "address_lat": "39.9042", "address_lng": "116.4074"},
        headers=auth_headers(token_dispatcher),
    )
    assert r.status_code == 201, r.text
    created = r.json()
    client.delete(f"/api/v1/shipper/locations/{created['id']}", headers=auth_headers(token_dispatcher))


def test_customer_kind_must_be_known(client: TestClient, token_dispatcher: str) -> None:
    """`kind` 决定客户按 user_id 还是按名称归属（accounting_service 里分流），
    未知取值原来会被静默当成散客。"""
    r = client.post(
        "/api/v1/customers", json={"name": "边界-怪kind", "kind": "whatever"}, headers=auth_headers(token_dispatcher)
    )
    assert r.status_code == 422, r.text
    ok = client.post(
        "/api/v1/customers", json={"name": "边界-正常散客", "kind": "tmp"}, headers=auth_headers(token_dispatcher)
    )
    assert ok.status_code in (200, 201), ok.text
    assert ok.json()["kind"] == "tmp"


