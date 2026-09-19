"""资金汇总必须**在服务端算**（2026-09-19 审计的缺陷 R5）。

## 原来的样子
「资金收支」页把 `GET /cash-flows` 拉回来的一页流水**在客户端求和**，而那个接口有 `limit`
（默认 200）。实测同一窗口：默认只拿 200 条 → 流入 ¥18,842；limit=1000 → 273 条 → 流入
¥48,905.50（页面少算 62%）。同一页的 Excel 导出反而是**在 SQL 侧全窗口求和**的（真值）——
"页面一个数、导出一个数"，而且页面上完全看不出来。

修法：新增 `GET /cash-flows/summary`，金额在数据库里算完；列表的 `limit` 只影响"看得见几行"。
这个文件钉住三件事：① 汇总等于全窗口求和；② 明细的 limit 不影响汇总；③ 汇总与列表用同一套筛选。
"""
from __future__ import annotations

from tests.conftest import auth_headers


def _mk_expense(client, h, amount: str) -> None:
    r = client.post(
        "/api/v1/expenses",
        json={"exp_date": "2026-09-19", "category": "fuel", "amount": amount, "note": "汇总探针"},
        headers=h,
    )
    assert r.status_code == 200, r.text


def test_summary_equals_full_window_ignoring_list_limit(client, token_dispatcher):
    h = auth_headers(token_dispatcher)
    for amt in ("10.00", "20.00", "30.50"):
        _mk_expense(client, h, amt)

    s = client.get("/api/v1/cash-flows/summary", headers=h)
    assert s.status_code == 200, s.text
    body = s.json()
    assert float(body["expense"]) >= 60.5
    assert body["count"] >= 3
    # 净额 = 流入 − 流出（恒等式，不能各算各的）
    assert abs(float(body["net"]) - (float(body["income"]) - float(body["expense"]))) < 0.005

    # 明细只取 1 条也不影响汇总（这正是"客户端求和"会错的地方）
    one = client.get("/api/v1/cash-flows", params={"limit": 1}, headers=h)
    assert one.status_code == 200, one.text
    assert len(one.json()) == 1
    s2 = client.get("/api/v1/cash-flows/summary", headers=h).json()
    assert s2 == body, "汇总不许受明细 limit 影响"


def test_summary_respects_date_window(client, token_dispatcher):
    h = auth_headers(token_dispatcher)
    _mk_expense(client, h, "7.00")
    inside = client.get(
        "/api/v1/cash-flows/summary", params={"date_from": "2026-09-19", "date_to": "2026-09-19"}, headers=h
    ).json()
    outside = client.get(
        "/api/v1/cash-flows/summary", params={"date_from": "2020-01-01", "date_to": "2020-01-02"}, headers=h
    ).json()
    assert float(inside["expense"]) > 0
    assert float(outside["expense"]) == 0.0 and outside["count"] == 0


def test_summary_direction_filter_is_case_insensitive(client, token_dispatcher):
    """方向筛选的大小写必须无所谓（枚举是小写 in/out，写死大写会让汇总恒为 0）。"""
    h = auth_headers(token_dispatcher)
    _mk_expense(client, h, "5.00")
    lower = client.get("/api/v1/cash-flows/summary", params={"direction": "out"}, headers=h).json()
    upper = client.get("/api/v1/cash-flows/summary", params={"direction": "OUT"}, headers=h).json()
    assert lower == upper, "大小写不同的同一个筛选必须得到同一个数"
    assert float(lower["expense"]) > 0


def test_summary_requires_dispatcher(client, token_shipper):
    r = client.get("/api/v1/cash-flows/summary", headers=auth_headers(token_shipper))
    assert r.status_code == 403, r.text
