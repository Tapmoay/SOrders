"""退货申请的 `?status=` 必须是**闭集**（2026-09-24 第 27 轮；第 25 轮 09 区 ②）。

## 缺陷长什么样
两个列表端点（`/return-requests`、`/return-requests/mine`）原来把 `status` 声明成**自由字符串**，
而过滤只判 `== "pending"`：

| 请求 | 修之前 | 后果 |
|---|---|---|
| `?status=pending` | 只回待处理 | 对 |
| `?status=all` | 全回 | 对 |
| `?status=rejected` | **200 + 全部**（与 `all` 逐字相同，实测 13 条） | 模型把**全部**申请（含 done/withdrawn）报成"被驳回的"——**静默错答**，没有任何一层会报错 |

修法：类型改成 `Literal["all","pending","done","rejected","withdrawn"]`。
这一改同时修两侧：① 别的取值 FastAPI 直接 **422**；② `Literal` 会进 AI 读目录的 enum
（生成器只认 `Literal[...]`，`pattern=` 读不出来）→ 模型知道合法取值。
"""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from tests.conftest import auth_headers


@pytest.mark.dispatcher
@pytest.mark.fast
@pytest.mark.regression
def test_非法的状态取值必须被拒(client: TestClient, token_dispatcher: str) -> None:
    """`?status=` 传一个不存在的档位 → 422（**不许**静默当成"全部"）。

    ⚠️ `/mine` 那条路是**货主专属**（派单员打它回 403），所以它的非法取值由下面
    `test_货主侧同样闭集` 用货主 token 覆盖 —— 两条路都要有，因为它们是同一个 `?status=`。
    """
    h = auth_headers(token_dispatcher)
    r = client.get("/api/v1/return-requests", params={"status": "rejected_typo"}, headers=h)
    assert r.status_code == 422, (
        f"把非法的 status 当成了合法值（{r.status_code}）——"
        "修之前它会把**全部**申请当成那一档喂出去（静默错答）："
        f"{r.text[:200]}"
    )


@pytest.mark.dispatcher
@pytest.mark.fast
@pytest.mark.regression
def test_四个档位与_all_都能调(client: TestClient, token_dispatcher: str) -> None:
    """合法取值都要 200（`all` 是默认那一档，别把兼容性改坏）。"""
    h = auth_headers(token_dispatcher)
    for st in ("all", "pending", "done", "rejected", "withdrawn"):
        r = client.get("/api/v1/return-requests", params={"status": st}, headers=h)
        assert r.status_code == 200, f"status={st} 应当可用：{r.status_code} {r.text[:160]}"


@pytest.mark.dispatcher
@pytest.mark.fast
@pytest.mark.regression
def test_点名的档位只回那一档(client: TestClient, db_session, token_dispatcher: str) -> None:
    """`?status=rejected` 回的每一条都必须是 rejected（这就是"闭集"要保住的东西）。"""
    h = auth_headers(token_dispatcher)
    r = client.get("/api/v1/return-requests", params={"status": "rejected"}, headers=h)
    assert r.status_code == 200, r.text
    rows = r.json().get("items", r.json() if isinstance(r.json(), list) else [])
    other = [x.get("status") for x in rows if x.get("status") != "rejected"]
    assert not other, f"点名 rejected 却回了别的档位：{other}（原来这里回的是全部）"


@pytest.mark.auth
@pytest.mark.fast
def test_货主侧同样闭集(client: TestClient, token_shipper: str) -> None:
    """`/mine` 是同一个 `?status=` 的两条路之一，双门必须一致。"""
    r = client.get(
        "/api/v1/return-requests/mine", params={"status": "nope"}, headers=auth_headers(token_shipper)
    )
    assert r.status_code == 422, r.text
