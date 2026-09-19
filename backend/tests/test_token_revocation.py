"""令牌的**服务端撤销**（2026-09-19 审计的缺陷 S7）。

## 原来的样子
JWT 是自包含的，服务端**一个字都不知道**谁手里有哪些令牌：没有 `jti`、没有黑名单、
没有 `token_version`、也没有 `/auth/logout` 端点。于是：

- 用户改了密码（最自然的止损动作）→ **旧令牌照样能用满 24 小时**；
- 在别人电脑上登过、手机丢了 → 没有任何手段作废那个令牌。

现在的语义：令牌里带签发时的 `token_version`，每个请求都比一次；**改密码 / 停用账号 /
主动登出**都会把库里那一列 +1 → 那些旧令牌下一次请求就是 401。

⚠️ 兼容性：老令牌没有 `tv` claim → 按 0 处理；老库补列默认也是 0 → **升级不会踢人下线**。
"""
from __future__ import annotations

from tests.conftest import auth_headers


def test_logout_revokes_existing_tokens(client, token_shipper):
    """登出 → 同一个令牌立刻失效（服务端真的作废，不是只清本机）。"""
    h = auth_headers(token_shipper)
    assert client.get("/api/v1/users/me", headers=h).status_code == 200

    r = client.post("/api/v1/auth/logout", headers=h)
    assert r.status_code == 200, r.text

    again = client.get("/api/v1/users/me", headers=h)
    assert again.status_code == 401, "登出后旧令牌必须失效（否则'登出'只是删了本机的一份拷贝）"


def test_password_change_revokes_existing_tokens(client, users, token_dispatcher, token_shipper):
    """派单员改某人的密码 → 那个人手上的旧令牌立刻失效。"""
    sid = users["shipper"].id
    old = auth_headers(token_shipper)
    assert client.get("/api/v1/users/me", headers=old).status_code == 200

    r = client.patch(f"/api/v1/users/{sid}", json={"password": "newpass12345"},
                     headers=auth_headers(token_dispatcher))
    assert r.status_code == 200, r.text

    assert client.get("/api/v1/users/me", headers=old).status_code == 401, \
        "改密码后旧令牌必须失效（这是丢手机/密码泄漏时唯一的止损动作）"


def test_deactivating_account_revokes_existing_tokens(client, users, token_dispatcher, token_shipper):
    """停用账号 → 已经在登录中的会话立刻断（不是等 24 小时自然过期）。"""
    sid = users["shipper"].id
    old = auth_headers(token_shipper)
    assert client.get("/api/v1/users/me", headers=old).status_code == 200

    r = client.patch(f"/api/v1/users/{sid}", json={"is_active": False},
                     headers=auth_headers(token_dispatcher))
    assert r.status_code == 200, r.text

    assert client.get("/api/v1/users/me", headers=old).status_code == 401, \
        "停用后旧令牌必须立刻失效（离职/丢手机场景）"

    # 复原，别影响别的用例
    client.patch(f"/api/v1/users/{sid}", json={"is_active": True}, headers=auth_headers(token_dispatcher))


def test_other_users_tokens_are_not_affected(client, users, token_dispatcher, token_shipper):
    """撤销是**按账号**的：改货主密码不该把派单员踢下线（判据别做成一刀切）。"""
    d = auth_headers(token_dispatcher)
    assert client.get("/api/v1/users/me", headers=d).status_code == 200
    client.patch(f"/api/v1/users/{users['shipper'].id}", json={"password": "another12345"}, headers=d)
    assert client.get("/api/v1/users/me", headers=d).status_code == 200, \
        "撤销售货主的令牌不该影响派单员自己的会话"
