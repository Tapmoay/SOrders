"""票据必须有 `exp` —— 否则「24 小时过期」只是签发函数的习惯，不是服务端策略。

（2026-09-24 第 25 轮；第 24 轮 07 区 F4 实测）

## 缺陷长什么样
`decode_token` 只做验签，没开 `require=["exp"]`。PyJWT **只在票据带了 `exp` 时才校验过期**，
所以一张**没有 `exp` 声明**的票据原来一路通过：用本机密钥签一个只有 `sub/role/tv` 的票据 →
`GET /api/v1/orders` **200**。

后果不是"少一层校验"，而是**密钥一泄就是永久票**：仓库公开过历史凭据、生产 `.env` 里也躺过默认串；
签出来的票既不过期，也没有 `iat`/`jti` 可供追溯。而这条**没有任何判据**。

修法：`jwt.decode(..., options={"require": ["exp"]})` —— 缺 `exp` 的票据抛
`MissingRequiredClaimError`，`deps.get_current_user` 一律按 401 处理（与过期同一种答复）。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from starlette.testclient import TestClient

from app.config import get_settings
from app.core.security import get_jwt_secret
from tests.conftest import auth_headers


def _forge(claims: dict) -> str:
    """用**本机同一把密钥**签一张票据（模拟"密钥泄露"之后的攻击者能做到什么）。

    ⚠️ 用**应用自己那把库**（`app.core.security` 里的 `jose.jwt`）签，不要用 PyJWT：
    这两套的 `options` 键名不一样（`require_exp` vs `require: [...]`），
    用另一套签出来的票在"选项被静默忽略"这类事故里会给出**假绿**。
    """
    from app.core import security

    settings = get_settings()
    return security.jwt.encode(claims, get_jwt_secret(), algorithm=settings.jwt_algorithm)


@pytest.mark.auth
@pytest.mark.fast
@pytest.mark.regression
def test_没有_exp的票据必须被拒(client: TestClient, users: dict) -> None:
    """缺 `exp` 的票据 → 401（原来 200）。"""
    tok = _forge({"sub": str(users["dispatcher"].id), "role": "dispatcher", "tv": 0})
    r = client.get("/api/v1/orders", params={"limit": 1}, headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 401, (
        f"一张**永不过期**的票据（没有 exp）被接受了（{r.status_code}）——"
        f"「24 小时过期」就不是服务端策略，密钥一泄就是永久票：{r.text[:160]}"
    )


@pytest.mark.auth
@pytest.mark.fast
@pytest.mark.regression
def test_过期的票据同样被拒(client: TestClient, users: dict) -> None:
    tok = _forge({
        "sub": str(users["dispatcher"].id),
        "role": "dispatcher",
        "tv": 0,
        "exp": datetime.now(timezone.utc) - timedelta(minutes=1),
    })
    r = client.get("/api/v1/orders", params={"limit": 1}, headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 401, r.text


@pytest.mark.auth
@pytest.mark.fast
@pytest.mark.regression
def test_正常登录签发的票据照旧可用(client: TestClient, token_dispatcher: str) -> None:
    """这条是**反空转**：`require=["exp"]` 不许把正常票据也拦掉（签发一直带 exp）。"""
    r = client.get("/api/v1/orders", params={"limit": 1}, headers=auth_headers(token_dispatcher))
    assert r.status_code == 200, r.text
