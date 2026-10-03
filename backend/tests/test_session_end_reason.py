"""登录被作废之后，**说得出是哪一种**（2026-10-03 E2E 走查 BUG-0006）。

## 用户看到的问题（走查原话）

> 「5554 巡检中被弹回登录页，只有一句 toast『登录已失效，请重新登录』……
>  被顶号 / 被停用 / 改了密码 / 令牌过期，在用户眼里**全是同一句话**，不说原因；
>  服务端明明握着 reason 字符串。真人会以为 App 坏了或网络问题。」

## 为什么这句话值得单独一个文件

「登录已失效」是一句**指错方向**的话，而且四种情况要用户做的事**完全不同**：

| 真实原因 | 用户该做的 | 说「登录已失效」的后果 |
|---|---|---|
| 账号在另一台设备登录 | 知道是自己/同事在别处登了 | 以为 App 坏了、反复重登，**再把对方顶掉**（两台机器互相顶） |
| 账号被停用 | 去找派单员 | 反复重登，永远登不进去 |
| 改密码 | 用新密码登 | 用旧密码继续试，越试越像「账号坏了」 |
| 令牌过期（24 小时） | 重新登录就好 | 这一种用兜底句其实也说得过去 —— 但它与上面三种混在一起，前三种就再也说不清了 |

## 三条容易写坏、坏了一点报错都没有的地方

| 写坏的方式 | 表现 |
|---|---|
| 只在**下一次登录**时才写原因、或者压根不写 | 界面永远只能显示兜底句（改进等于没做） |
| 写上一次撤销的原因，**不核对是不是最近这一次** | 第三台顶掉第二台时，弹出的是关于「登出」的话 —— 说得斩钉截铁却是错的 |
| 原因落库了但**没和 `token_version` 同一个事务** | 撤销生效、原因没生效（或反过来）→ 用户看到的解释与真实原因错位 |
| 401 的正文换了，客户端仍只认那句写死的兜底 | 服务端说对了、用户还是看不到（`ApiClient.unauthorizedDetail` 那一环） |
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from jose import jwt
from starlette.testclient import TestClient

from tests.conftest import auth_headers

#: 真实（非豁免）账号：走「后来者顶掉先登的」那条路，才测得出顶号
REAL_PHONE = "15900000002"
REAL_PW = "pass12345"
REAL_NAME = "顶号测试员"


@pytest.fixture
def real_dispatcher(db_session):
    """建一个非豁免号段的派单员账号（库里种子号全在豁免号段里，顶不掉）。

    ⚠️ 先删同号再建：测试库是**文件式、跨运行保留**的（`conftest.get_db_path`），
    上一次跑挂了会把这行留下，第二次进来直接 `UNIQUE constraint failed: users.phone`。
    """
    from app.core.security import hash_password
    from app.models import User

    db_session.query(User).filter(User.phone == REAL_PHONE).delete()
    db_session.commit()

    u = User(
        username=REAL_PHONE,
        phone=REAL_PHONE,
        password_hash=hash_password(REAL_PW),
        full_name=REAL_NAME,
        role="dispatcher",  # type: ignore[arg-type]
    )
    db_session.add(u)
    db_session.commit()
    return u


def _login(client: TestClient, phone: str, password: str = REAL_PW) -> str:
    r = client.post("/api/v1/auth/login", json={"phone": phone, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _detail(client: TestClient, token: str) -> tuple[int, str]:
    """打一次 `/users/me`，取（状态码, 正文里那句中文）。"""
    r = client.get("/api/v1/users/me", headers=auth_headers(token))
    if r.status_code == 200:
        return 200, ""
    return r.status_code, str(r.json().get("detail", ""))


def _expired_token(user_id: int) -> str:
    """签一张**已过期**的票（`create_access_token` 只认配置里的有效期，签不出过期的）。

    直接用生产同一套密钥/算法签 —— 这样走的是真正的验签 + 过期判定，
    不是把 `decode_token` monkeypatch 掉（那样测的是探针，不是代码）。
    """
    from app.config import get_settings
    from app.core.security import get_jwt_secret

    s = get_settings()
    payload = {
        "sub": str(user_id),
        "exp": datetime.now(timezone.utc) - timedelta(minutes=5),
        "tv": 0,
        "role": "dispatcher",
    }
    return jwt.encode(payload, get_jwt_secret(), algorithm=s.jwt_algorithm)


# ============================================================ ① 四种原因各自说得清


@pytest.mark.auth
@pytest.mark.fast
def test_被顶号那台说得出是被另一台设备顶的(client: TestClient, real_dispatcher) -> None:
    """两台设备登同一个号：**先登那台**下一次请求 401，并且正文点名「另一台设备登录」。"""
    first = _login(client, REAL_PHONE)
    assert _detail(client, first) == (200, "")

    second = _login(client, REAL_PHONE)  # 后来者顶掉先登的
    assert _detail(client, second) == (200, "")  # 新令牌好使（撤销没把新人一起带走）

    code, detail = _detail(client, first)
    assert code == 401, f"旧令牌应当失效，实测 {code}"
    assert "账号在另一台设备登录" in detail, detail
    # ⛔ 兜底句复现就是这条用例要防的事：说了等于没说
    assert "登录已失效" not in detail, detail
    # 401 的形状（`WWW-Authenticate`）不能因为分支变多而漏掉
    r = client.get("/api/v1/users/me", headers=auth_headers(first))
    assert r.headers.get("WWW-Authenticate") == "Bearer", r.headers


@pytest.mark.auth
@pytest.mark.fast
def test_登出之后说得出是登出(client: TestClient, real_dispatcher) -> None:
    """主动登出（`POST /auth/logout`）→ 同一张令牌再用时说「登出」，不是「失效」。"""
    token = _login(client, REAL_PHONE)
    assert client.post("/api/v1/auth/logout", headers=auth_headers(token)).status_code == 200

    code, detail = _detail(client, token)
    assert code == 401
    assert "登出" in detail, detail
    assert "登录已失效" not in detail, detail


@pytest.mark.auth
@pytest.mark.fast
def test_被停用之后说得出是被停用(client: TestClient, real_dispatcher, token_dispatcher: str) -> None:
    """派单员把账号停用 → 这个账号手上的令牌立刻作废，并且告诉它「被停用」。"""
    token = _login(client, REAL_PHONE)
    r = client.patch(
        f"/api/v1/users/{real_dispatcher.id}",
        json={"is_active": False},
        headers=auth_headers(token_dispatcher),
    )
    assert r.status_code == 200, r.text

    code, detail = _detail(client, token)
    assert code == 401
    assert "已被停用" in detail, detail
    assert "登录已失效" not in detail, detail


@pytest.mark.auth
@pytest.mark.fast
def test_改密码之后说得出是改密码(client: TestClient, real_dispatcher, token_dispatcher: str) -> None:
    """改密码 → 旧令牌作废，正文说「改密码」（不是「密码错了」，也不是「失效」）。"""
    token = _login(client, REAL_PHONE)
    r = client.patch(
        f"/api/v1/users/{real_dispatcher.id}",
        json={"password": "newpass12345"},
        headers=auth_headers(token_dispatcher),
    )
    assert r.status_code == 200, r.text

    code, detail = _detail(client, token)
    assert code == 401
    assert "改密码" in detail, detail
    assert "登录已失效" not in detail, detail


@pytest.mark.auth
@pytest.mark.fast
def test_令牌过期说得出是过期(client: TestClient, real_dispatcher) -> None:
    """过期与「被顶掉」必须分开：这一种重新登录就好，不该让人怀疑账号出事。"""
    code, detail = _detail(client, _expired_token(real_dispatcher.id))
    assert code == 401
    assert "已过期" in detail, detail
    # ⛔ 过期不是「被顶号」：说成那个会把用户引到"是不是有人在别处登我号"上
    assert "另一台设备" not in detail, detail


@pytest.mark.auth
@pytest.mark.fast
def test_账号没了说得出账号没了(client: TestClient) -> None:
    """令牌的 sub 指向一个不存在的账号 → 说「不存在或已被删除」，不是「失效」。"""
    from app.core.security import create_access_token

    ghost = create_access_token("99999999", {"tv": 0, "role": "dispatcher"})
    code, detail = _detail(client, ghost)
    assert code == 401
    assert "不存在" in detail or "已被删除" in detail, detail


# ============================================================ ② 原因怎么落库（对账）


@pytest.mark.auth
@pytest.mark.fast
def test_撤销原因写进库里并且和版本号对账(db_session, real_dispatcher) -> None:
    """撤销 = 版本号 +1 **并且**把原因、时间、当时的版本号一起写下来（同一个事务里）。"""
    from starlette.background import BackgroundTasks

    from app.services.auth_service import revoke_tokens_and_sockets

    before = int(real_dispatcher.token_version or 0)
    revoke_tokens_and_sockets(db_session, real_dispatcher, BackgroundTasks(), "  账号在另一台设备登录  ")
    db_session.flush()

    assert int(real_dispatcher.token_version or 0) == before + 1
    # 前后空格清理掉（调用点写错一个空格，界面就会多出两个空格）
    assert real_dispatcher.session_revoked_reason == "账号在另一台设备登录"
    assert real_dispatcher.session_revoked_at is not None
    assert int(real_dispatcher.session_revoked_version or 0) == int(real_dispatcher.token_version or 0)


@pytest.mark.auth
@pytest.mark.fast
def test_没记下原因时只说已失效绝不编一个(client: TestClient, db_session, real_dispatcher) -> None:
    """老库 / 从没走过撤销入口的账号：版本对不上但没原因 → **只说失效**。

    ⛔ 这一条是"别为了好看而撒谎"那条底线：宁可说一句没信息量的话，
      也不能拿上一次撤销、或猜一个原因填上去。
    """
    token = _login(client, REAL_PHONE)
    real_dispatcher.token_version = int(real_dispatcher.token_version or 0) + 1  # 裸 bump，不写原因
    db_session.commit()

    code, detail = _detail(client, token)
    assert code == 401
    assert detail == "登录已失效，请重新登录", detail


@pytest.mark.auth
@pytest.mark.fast
def test_上一次撤销的原因不许解释这一次(client: TestClient, db_session, real_dispatcher) -> None:
    """原因必须**属于最近这一次**撤销：隔了一轮之后再失效，不许拿旧原因来解释。"""
    stale = _login(client, REAL_PHONE)
    _login(client, REAL_PHONE)  # 第二次登录 → 撤销第一次，记下「账号在另一台设备登录」
    assert "另一台设备登录" in _detail(client, stale)[1]

    # 之后又作废了一次，但那一轮没记下原因（老库 / 别的入口）→ 旧原因必须失效
    real_dispatcher.token_version = int(real_dispatcher.token_version or 0) + 1
    db_session.commit()

    code, detail = _detail(client, stale)
    assert code == 401
    assert detail == "登录已失效，请重新登录", detail


# ============================================================ ③ 事后查得到「谁顶了谁」


@pytest.mark.auth
@pytest.mark.fast
def test_登录记下最后登录时间(client: TestClient, db_session, real_dispatcher) -> None:
    """走查那句「事后在库里查不到谁顶了谁」：登录成功必须留下时间。"""
    from datetime import datetime as _dt

    assert real_dispatcher.last_login_at is None  # 基线：刚建号，没登过
    _login(client, REAL_PHONE)
    db_session.refresh(real_dispatcher)

    assert isinstance(real_dispatcher.last_login_at, _dt), real_dispatcher.last_login_at
    # 与撤销原因共存：登录**不许**顺手把上一次的原因清掉（那台设备还要靠它说话）
    assert real_dispatcher.session_revoked_reason in ("", "账号在另一台设备登录")

