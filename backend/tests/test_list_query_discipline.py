"""列表端点**入参纪律**三件（2026-09-24 第 19 轮并行渗透 C9-1/2/4）：
`%` 不许当通配符、`limit` 不许为负、反序日期窗口不许安静地返回空集。

## 为什么这三条要放在一起
它们同属"**用户照着错的结果做决定**"那一类，而且**都没有任何检查覆盖**：

| 现象 | 实测（本机） |
| --- | --- |
| `q` 里的 `%` 直接进 LIKE | `/places?q=%25` → **64 条 = 全表**；`/orders?q=%25&limit=5000` → **426 条 = 全部单**；`/users?q=%25` → **59 条 = 全部账号**；`/customers?q=%25` → **35 = 全部客户**（该端点无 limit，整表下发） |
| `limit` 没有下界 | `/inventory/movements?limit=-5` → 200 / **99 行**（SQLite 的 `LIMIT -5` = 不限量）+ `X-Result-Limit: -5`；`/operation-logs?limit=-5` → **981 行**；生产 MySQL 同请求 500 |
| 日期反了 | `/orders` → 400；`/ledger/entries`、`/cash-flows`、`/expenses` → **200 + 0 条**（界面显示「这段时间没有流水、流入 0」） |

用户看到的现象分别是"搜索没生效"、"列表莫名其妙变长了"、"这段时间没有账"——
三条都不会报错，所以只能靠判据钉住。
"""

from __future__ import annotations

import pytest

from tests.conftest import auth_headers


# --------------------------------------------------------------- ① `%` 不是通配符

@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/places",
        "/api/v1/users",
        "/api/v1/customers",
        "/api/v1/orders",
    ],
)
def test_搜索里的百分号不当通配符(client, token_dispatcher, path: str):
    """`?q=%` 必须**搜不到东西**（当字面量），而不是把整表倒出来。"""
    h = auth_headers(token_dispatcher)
    # ⚠️ 两条请求用**同一套参数**（只有 `q` 不同），且不显式传 limit：
    #    各端点的上限不同（`/customers` 是 200、`/orders` 是 5000），写死一个数会先被 422 拦掉。
    all_rows = client.get(path, headers=h)
    assert all_rows.status_code == 200, all_rows.text
    total = len(all_rows.json())

    hit = client.get(f"{path}?q=%25", headers=h)
    assert hit.status_code == 200, hit.text
    n = len(hit.json())
    assert n == 0, (
        f"{path}?q=% —— 通配符没转义：返回了 {n} 条（全表 {total} 条）。"
        "用户打一个百分号就是『不加条件』，而 /customers、/users 会整表下发"
    )


def test_下划线也是通配符(client, token_dispatcher):
    """`_` 是单字符通配符，同样要转义（`?q=_` 不许命中所有三个字的记录）。"""
    h = auth_headers(token_dispatcher)
    r = client.get("/api/v1/places?q=_", headers=h)
    assert r.status_code == 200, r.text
    assert r.json() == [], "`_` 没转义 → 它匹配任意单字符，等于模糊命中一大批"


def test_正常搜索仍然能搜到(client, token_dispatcher, db_session):
    """反向对照：转义**不许**把正常搜索一起弄坏（否则这是一次功能退化）。"""
    from app.models import Place

    h = auth_headers(token_dispatcher)
    p = Place(name="转义对照探针地点", lat=23.1, lng=113.2)
    db_session.add(p)
    db_session.commit()

    r = client.get("/api/v1/places?q=转义对照探针", headers=h)
    assert r.status_code == 200, r.text
    names = [x.get("name") for x in r.json()]
    assert "转义对照探针地点" in names, f"子串搜索被弄坏了：{names[:5]}"


# --------------------------------------------------------------- ② limit 下界

@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/inventory/movements",
        "/api/v1/operation-logs",
        "/api/v1/users",
    ],
)
def test_limit_为负必须被拒(client, token_dispatcher, path: str):
    """负 `limit` 在 SQLite 上是『不限量』、在 MySQL 上是 500 —— 两种都不该发生。"""
    h = auth_headers(token_dispatcher)
    r = client.get(f"{path}?limit=-5", headers=h)
    assert r.status_code == 422, (
        f"{path}?limit=-5 返回了 {r.status_code}：SQLite 上 `LIMIT -5` = 不限量"
        "（返回『全表减 5 行』），生产 MySQL 上直接 500"
    )
    assert "limit" in r.text or "范围" in r.text, r.text


def test_零条也不是合法的页大小(client, token_dispatcher):
    """`limit=0` → 422（否则界面会拿到空 body + `X-Truncated: 1`，永远显示"加载更多"）。"""
    h = auth_headers(token_dispatcher)
    assert client.get("/api/v1/operation-logs?limit=0", headers=h).status_code == 422


def test_正常分页仍然能翻(client, token_dispatcher):
    """反向对照：第一页 + 第二页拿得到，且响应头里的上限是**正数**。"""
    h = auth_headers(token_dispatcher)
    r = client.get("/api/v1/operation-logs?limit=1&skip=0", headers=h)
    assert r.status_code == 200, r.text
    assert r.headers.get("X-Result-Limit") == "1", r.headers


# --------------------------------------------------------------- ③ 反序日期窗口

@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/ledger/entries",
        "/api/v1/cash-flows",
        "/api/v1/expenses",
        "/api/v1/ledger/receipts",
        "/api/v1/orders",
        "/api/v1/inventory/movements",
    ],
)
def test_日期反了必须报错而不是空集(client, token_dispatcher, path: str):
    """`date_from > date_to` 一律 400 —— 不许"安静地返回 0 条"。

    这一族原来**一半 400、一半 200+0 条**：账本页与资金流水页会显示
    「这段时间没有流水、流入 0」，而用户会就此认为这段时间真的没有账
    （这两页正是"钱的三方对账"要盯的）。
    """
    h = auth_headers(token_dispatcher)
    r = client.get(f"{path}?date_from=2026-09-30&date_to=2026-09-01", headers=h)
    assert r.status_code == 400, (
        f"{path} 反序窗口返回 {r.status_code}（期望 400）—— 界面会把空集显示成"
        "「这段时间没有数据」"
    )
    assert "日期" in r.text, r.text


@pytest.mark.parametrize(
    "path",
    ["/api/v1/ledger/entries", "/api/v1/cash-flows", "/api/v1/expenses"],
)
def test_正常顺序的窗口仍然能用(client, token_dispatcher, path: str):
    """反向对照：同一天（含头含尾）与正序区间都必须照常返回。"""
    h = auth_headers(token_dispatcher)
    r = client.get(f"{path}?date_from=2026-09-01&date_to=2026-09-30", headers=h)
    assert r.status_code == 200, r.text
    same = client.get(f"{path}?date_from=2026-09-01&date_to=2026-09-01", headers=h)
    assert same.status_code == 200, same.text
