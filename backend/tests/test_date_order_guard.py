"""「日期反了」必须当场 400 —— 且**清单由路由表自己算**（2026-09-24 第 22 轮 F8）。

## 缺陷长什么样
同一个"日期反了"的输入，在这一族里曾经有两个答案：

| 端点 | 修之前 |
|---|---|
| `/orders`、`/inventory/movements`、`/reports/turnover`、`/ledger/accounts`、`/cash-flows`、`/expenses` | **400** |
| `/stats/*`（6 个）、`/reports/arrears-summary`、`/freight-settlement`、`/supplier-payments` | **200 + 空集** |

后果不是"少看几条"，而是**同一页上的四个格子对同一段时间给出两种结论**：报表中心把同一段
日期发给所有这些端点，于是「营业纵览」报红字、而「司机绩效 / 客户经营 / 异常与审计」显示
「没有数据」—— 用户会以为这段时间确实没生意。日期选择器"先点晚、再点早"是日常操作。

`/stats/driver-performance` 还把反序区间当**合法区间**回显（`period_label` =
`"2026-09-30 ~ 2026-09-01"`），那是"报表自己承认这段时间是反的、却照样出数"。

## 判据为什么"能红"
`test_every_dated_get_route_rejects_reversed_range` **从 `app.routes` 自己算出候选清单**
（带 `date_from`+`date_to` 两个查询参数的 GET 端点），逐个打反序：

- 修之前：9 个端点回 200 → 红；
- 修之后：全部 400 → 绿；
- 以后新加一个聚合端点忘了走 `ensure_date_order` → 它自动进清单 → 红。
  清单**不是手写的**（本项目栽过 5 次"清单手写 → 新加的没人查"），另配一条数量下限
  （候选 < 9 个说明扫描本身坏了，那时必须报错而不是安静地全绿）。
"""

from __future__ import annotations

import re
import sys
import types
import typing
from datetime import date, datetime

import pytest
from sqlalchemy import func, select
from starlette.testclient import TestClient

from tests.conftest import auth_headers, iter_api_routes

#: 反序窗口（`date_from > date_to`）：任何一端点都不许把它当合法区间。
REVERSED_FROM = "2026-09-30"
REVERSED_TO = "2026-09-01"

#: 候选端点的数量下限（修这一轮时实测 9 个；再少就说明扫描逻辑坏了）。
MIN_CANDIDATES = 9


def _annotation(field):
    """查询参数的真实类型注解。

    ⚠️ 不能读 `field.type_`（这一版 FastAPI/pydantic 组合下它对 `Annotated[date, Query(...)]`
    给不出 `date`）—— 读错的后果不是报错，而是**必填参数填了个非法值 → 端点回 422**，
    于是这条判据静默失效（我第一版就是这样：`date`/`shipper_id` 全填成了 `"x"`）。
    """
    fi = getattr(field, "field_info", None)
    ann = getattr(fi, "annotation", None)
    return ann if ann is not None else getattr(field, "type_", None)


def _type_pattern(field) -> str | None:
    """这个参数身上的**正则约束**（有就返回）。

    ⚠️ pydantic v2 把 `Query(pattern=...)` 放进 `field_info.metadata` 的
    `_PydanticGeneralMetadata` 上，**不在** `field_info.pattern`（实测：`.pattern` 恒为 None）。
    读不到它的后果：`kind` 这种 `^(turnover|…)$` 的参数会填上一个非法值 → 422 →
    这条端点永远走不到我们真正要验的判据（我第二版就栽在这里）。
    """
    fi = getattr(field, "field_info", None)
    if fi is None:
        return None
    for obj in [fi, *(getattr(fi, "metadata", None) or [])]:
        pat = getattr(obj, "pattern", None)
        if isinstance(pat, str):
            return pat
    return None


def _dummy_for(field) -> str:
    """给"日期之外的必填参数"编一个**类型正确**的值。

    目的只是让请求走到我们的判据（判据写在函数体第一句），值本身的业务含义不重要。
    """
    ann = _annotation(field)
    origin = typing.get_origin(ann)
    # ⚠️ `date | None` 这种写法（`from __future__ import annotations` 下很常见）的
    #    origin 是 `types.UnionType`，**不是** `typing.Union` —— 两个都要认。
    if origin in (typing.Union, types.UnionType):
        inner = [a for a in typing.get_args(ann) if a is not type(None)]
        ann = inner[0] if inner else str
        origin = typing.get_origin(ann)
    if origin is typing.Literal:
        vals = typing.get_args(ann)
        return str(vals[0]) if vals else "x"
    if ann in (int, float):
        return "1"
    if ann is bool:
        return "false"
    if ann in (date, datetime):
        return "2026-09-15"
    if ann is str:
        pat = _type_pattern(field)
        if pat:
            m = re.search(r"[A-Za-z0-9_\-]+", pat)
            if m:
                return m.group(0)
        return "x"
    return "x"


def _is_required(field) -> bool:
    """这个查询参数是不是必填。

    ⚠️ pydantic v2 的 `ModelField` 上**没有** `.required`（v1 才有）——要问它的 `field_info`。
    写错这里不会报"用例失败"，而是每个必填参数都漏填 → 端点回 422 → 这条判据静默失效。
    """
    fi = getattr(field, "field_info", None)
    if fi is not None and hasattr(fi, "is_required"):
        return bool(fi.is_required())
    return bool(getattr(field, "required", False))


def _candidates() -> list:
    """从路由表算出"带 date_from + date_to 的 GET 端点"（`from`/`to` 那一对另测）。

    ⚠️ 取 `fastapi_app` 而不是 `app`：后者是 `socketio.ASGIApp` 的包装，
    只有前者才拿得到路由表。

    ⚠️ 遍历要用 `iter_api_routes`（递归拍平），**不能**直接 `for r in fastapi_app.routes`：
    starlette 1.7.0（CI 装到的那个）把 `include_router` 的子路由包在 `_IncludedRouter` 里，
    它没有 `.dependant` → 这个循环会一路 `continue`，最后**扫到 0 个候选端点**，
    而那正好会被上面的下限断言拦住（CI 上就是这么红的）。见 `conftest.iter_api_routes`。
    """
    from app.main import fastapi_app

    out = []
    for r in iter_api_routes(fastapi_app):
        # 只认 FastAPI 的 APIRoute（`/docs`、`/openapi.json` 那些是 Starlette `Route`，
        # 没有 `dependant`，也没有查询参数模型）
        dep = getattr(r, "dependant", None)
        if dep is None:
            continue
        methods = getattr(r, "methods", None) or set()
        if "GET" not in methods:
            continue
        params = {f.alias or f.name: f for f in dep.query_params}
        if "date_from" in params and "date_to" in params:
            out.append(r)
    return out


def _probe(client: TestClient, r, headers: dict) -> "object":
    """对某个候选端点打一次**反序**请求（必填参数按类型补齐，好让它走到我们的判据）。"""
    path = r.path
    for f in r.dependant.path_params:
        path = path.replace("{" + f.name + "}", _dummy_for(f))
    query = {
        f.alias or f.name: _dummy_for(f)
        for f in r.dependant.query_params
        if _is_required(f) and (f.alias or f.name) not in ("date_from", "date_to")
    }
    query["date_from"] = REVERSED_FROM
    query["date_to"] = REVERSED_TO
    return client.get(path, params=query, headers=headers)


@pytest.mark.dispatcher
@pytest.mark.regression
@pytest.mark.fast
def test_every_dated_get_route_rejects_reversed_range(
    client: TestClient, token_dispatcher: str
) -> None:
    """带 `date_from`+`date_to` 的 GET 端点，一律不许把反序窗口当合法区间。"""
    headers = auth_headers(token_dispatcher)
    candidates = _candidates()
    assert len(candidates) >= MIN_CANDIDATES, (
        f"只扫到 {len(candidates)} 个候选端点（下限 {MIN_CANDIDATES}）—— "
        "扫描逻辑本身坏了，这条判据此刻证明不了任何事"
    )

    bad: list[str] = []
    for r in candidates:
        resp = _probe(client, r, headers)
        if resp.status_code != 400:
            bad.append(f"{r.path} → {resp.status_code}（{resp.text[:120]}）")

    assert not bad, (
        "这些端点把「日期反了」当成了合法区间（应当 400）——"
        "界面上表现为「这段时间没有数据」，而同一页的兄弟端点会报红字：\n  "
        + "\n  ".join(bad)
    )


@pytest.mark.dispatcher
@pytest.mark.regression
@pytest.mark.fast
def test_the_400_comes_from_the_shared_guard(
    client: TestClient, token_dispatcher: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """**反空转**：把 `ensure_date_order` 换成空实现，同一批端点必须不再 400。

    没有这一条，上面那条可能是"碰巧被别的校验拦下"而永远绿（本项目栽过：
    判据看着在跑，其实证明不了它要证明的事）。补它的代价是一次 in-process 的
    `monkeypatch` —— **不动源码**，所以也不会污染别人的检查结论。
    """
    headers = auth_headers(token_dispatcher)
    # ⚠️ 2026-09-25（阶段 4/6 的报表下沉）：端点函数在 `api/v1/reports.py`、而**闸门是在
    #    `services/reports_service.py` 里调的** —— 只换端点那个模块的属性，service 里那份
    #    `from app.core.date_window import ensure_date_order` 绑定的旧函数照样拦人
    #    （实测：只补端点模块时，这 3 个聚合端点拆了闸门仍然 400，这条反空转当场红）。
    #    所以「把这道闸门换成空实现」＝换掉**所有持有它的 app 模块**（定义处 + 每个 import 处）。
    patched: list[str] = []
    for name, mod in list(sys.modules.items()):
        if mod is None or not name.startswith("app."):
            continue
        if hasattr(mod, "ensure_date_order"):
            monkeypatch.setattr(mod, "ensure_date_order", lambda *a, **k: None, raising=False)
            patched.append(name)
    assert "app.core.date_window" in patched, (
        "闸门的定义模块没被换掉 —— 这条反空转此刻证明不了任何事"
    )
    guarded = [r for r in _candidates() if getattr(r.endpoint, "__module__", "") in patched]

    assert len(guarded) >= 7, (
        f"只有 {len(guarded)} 个端点挂着这道闸门 —— 说明这一族里剩下的是"
        "`deps.parse_date_window` / `date_window` 那两套老口径（它们本来就会 400，"
        "但这一轮真正修的就是'聚合端点没人管'这一族，数量太少就要重新对一遍）"
    )

    still_bad: list[str] = []
    for r in guarded:
        resp = _probe(client, r, headers)
        if resp.status_code != 200:
            still_bad.append(f"{r.path} → {resp.status_code}（{resp.text[:120]}）")

    assert not still_bad, (
        "拆掉闸门之后这些端点仍然不是 200 —— 那说明拦住反序窗口的**不是**这道闸门，"
        "上面那条用例是空转的：\n  " + "\n  ".join(still_bad)
    )


@pytest.mark.dispatcher
@pytest.mark.regression
@pytest.mark.fast
def test_freight_settlement_rejects_reversed_from_to(
    client: TestClient, token_dispatcher: str
) -> None:
    """结算页用的是 `from`/`to`（不是 `date_from`/`date_to`），同样要拦。

    这一页空了会被读成"确实不用付司机钱"，所以它和报表家族一个待遇。
    """
    r = client.get(
        "/api/v1/freight-settlement",
        params={"from": "2026-09-30T00:00:00", "to": "2026-09-01T00:00:00"},
        headers=auth_headers(token_dispatcher),
    )
    assert r.status_code == 400, (
        f"结算页把反序区间当成了合法区间（{r.status_code}：{r.text[:160]}）"
    )
    assert "日期" in r.json().get("detail", ""), r.text


@pytest.mark.dispatcher
@pytest.mark.regression
@pytest.mark.integration
def test_turnover_cancelled_kpi_excludes_recycle_bin(
    client: TestClient, db_session, users: dict, token_dispatcher: str
) -> None:
    """「已撤销订单」KPI 不许把**回收站里**的撤销单算进来。

    删除是"伪装删除"（行还在库里），而派单员**任意状态都能删**（含已撤销）——
    所以这一格曾经会"删了不减少"，越删与明细差得越多。
    """
    from app.models import Order
    from app.models.enums import OrderStatus

    headers = auth_headers(token_dispatcher)
    today = date.today().isoformat()

    def kpi() -> int:
        r = client.get(
            "/api/v1/reports/turnover",
            # `date` 是必填锚点（区间优先，但锚点仍要）；给今天，与 date_from/date_to 一致。
            params={"date": today, "date_from": today, "date_to": today},
            headers=headers,
        )
        assert r.status_code == 200, r.text
        return r.json()["cancelled_orders"]

    before = kpi()

    # 造一张今天撤销的单 → KPI 应当 +1
    r = client.post(
        "/api/v1/orders",
        json={
            "shipper_id": users["shipper"].id,
            "lines": [{"product_name_snapshot": "撤销KPI探针", "quantity": 1, "unit_price": "10"}],
            "address_detail": "撤销KPI探针",
            "delivery_description": "撤销KPI探针",
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    oid = r.json()["id"]
    assert client.post(f"/api/v1/orders/{oid}/cancel", headers=headers).status_code == 200

    after_cancel = kpi()
    assert after_cancel == before + 1, (
        f"撤销一张单之后 KPI 应当 {before + 1}，实际 {after_cancel}"
    )

    # 再把它丢进回收站 → KPI 必须退回去（这就是这一条要守的判据）
    deleted = client.delete(f"/api/v1/orders/{oid}", headers=headers)
    assert deleted.status_code == 204, deleted.text

    db_session.expire_all()
    alive = db_session.scalar(
        select(func.count(Order.id)).where(
            Order.status == OrderStatus.CANCELLED,
            Order.cancelled_at.isnot(None),
            Order.deleted_at.is_(None),
        )
    )
    with_bin = db_session.scalar(
        select(func.count(Order.id)).where(
            Order.status == OrderStatus.CANCELLED,
            Order.cancelled_at.isnot(None),
        )
    )
    assert with_bin > alive, (
        "库里没有'已撤销且进了回收站'的单 → 这条用例此刻证明不了过滤生效（判据会空转）"
    )

    after_delete = kpi()
    assert after_delete == before, (
        f"回收站里的撤销单被算进了 KPI：删除前 {after_cancel}、删除后 {after_delete}"
        "（应当退回 "
        f"{before}）"
    )
