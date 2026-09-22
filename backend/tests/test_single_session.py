"""同一账号不许两台手机同时登录（2026-09-22 用户要求）；**测试号段豁免**。

## 用户原话与拍板

> 「还做一个叫什么**防止两部手机同时登一个账号**，**测试账号除外** —— 只要是真实的账号的话，
>  他**不能在两部手机上同时登录**。」
> 「**也就是现在我们用的账号的形式全都自动豁免**。主要改变的就是**后面的尾号最多 9 个**。」

拍板：第二台登录时**后来者顶掉先登的**（先登那台失效）。

## 为什么必须同时钉住"两类账号"

只测"真实账号会被顶掉"是不够的 —— 一个把所有人都限制住、忘了豁免的实现在那种测试下**照样全绿**，
而后果是**开发/验收流程被自己掐死**（真机验收本来就要两台设备登同一个号对比）。
反过来，只测"测试账号不受限"也一样：那样"真实账号其实没受任何限制"也能全绿。
所以下面两边各测一遍，并且**豁免判据本身**（号段边界）单独钉一组。

## 三条容易写坏、而且坏了一点报错都没有的地方

| 写坏的方式 | 表现 |
|---|---|
| 只在**第一次**登录时撤销、或压根不撤销 | 两台手机长期同时在线，而界面上完全正常 |
| 撤销了但**忘了 commit** | 新令牌带着库里没生效的 `tv` → **刚登录就"登录已失效"**（用户自己都进不来） |
| 只 `bump_token_version`、不断长连接 | 旧那台 HTTP 全 401，**但推送照收**（外部检查 C-3 就是这条） |
| 豁免判据写成 `phone.startswith("138000000")` | `13800000001234` 这种真实号被**悄悄放行** |
| 登录**失败**也撤销 | 别人拿你手机号打错 5 次密码，就能把你从自己手机上踢下线 |
"""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from tests.conftest import auth_headers

#: 测试号段：`1380000000` + 一位尾号（1~9）
EXEMPT_PHONES = ["13800000001", "13800000002", "13800000003", "13800000009"]
#: 看着像、其实**不是**豁免账号的号（判据不许用宽前缀放过它们）
NOT_EXEMPT_PHONES = [
    "13800000000",   # 尾号 0（用户说"最多 9 个"，0 不在内）
    "13800000010",   # 尾号两位
    "13800000001234",  # 前缀相同但后面还有一串（宽 startswith 会错误放行）
    "15070334563",   # 真实派单员
    "13905063320",   # 真实司机
    "",
    None,
]

REAL_PHONE = "15900000001"  # 真实账号（不在豁免号段里）
REAL_PW = "pass12345"
REAL_NAME = "派单员"


@pytest.fixture
def real_dispatcher(db_session):
    """建一个**真实**（非豁免）派单员账号 —— 库里那些种子号全在豁免号段里，测不出限制。

    ⚠️ 先删同号再建：测试库是**文件式、跨运行保留**的（`conftest.get_db_path`），
    上一次跑挂了就会把这行留下，第二次进来直接 `UNIQUE constraint failed: users.phone`。
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


def _me(client: TestClient, token: str) -> int:
    return client.get("/api/v1/users/me", headers=auth_headers(token)).status_code


# ============================================================ ① 豁免判据本身


@pytest.mark.auth
@pytest.mark.fast
def test_豁免判据只认前缀加一位尾号() -> None:
    """纯函数钉边界：`1380000000` + **一位** 1~9，多一位少一位都不算。"""
    from app.services.auth_service import is_test_account

    for p in EXEMPT_PHONES:
        assert is_test_account(p) is True, p
    for p in NOT_EXEMPT_PHONES:
        assert is_test_account(p) is False, p
    # 两侧空格不该改变结论（登录时手机号会被 strip）
    assert is_test_account("  13800000002  ") is True


@pytest.mark.auth
@pytest.mark.fast
def test_判据只有一处实现() -> None:
    """豁免判据不许在别处再写一遍（各写一份＝某个端悄悄放行真实账号，而界面看不出来）。

    ⚠️ 判据是"**函数与常量的定义处唯一**"，**不是**"全库搜 `1380000000`" ——
    那串数字在别处也合法地出现（`config.py` 的 AI 测试号前缀、`core/phone.py` 的示例号、
    `driver_pay.py` 的注释里那个生产司机号），拿它当判据只会红得莫名其妙。
    """
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "app"
    defs: list[str] = []
    uses: list[str] = []
    for p in root.rglob("*.py"):
        text = p.read_text(encoding="utf-8")
        rel = p.relative_to(root).as_posix()
        if "def is_test_account(" in text:
            defs.append(rel)
        if "TEST_ACCOUNT_PHONE_PREFIX" in text or "TEST_ACCOUNT_TAIL_MAX" in text:
            uses.append(rel)
    assert defs == ["services/auth_service.py"], f"豁免函数被定义了多处：{defs}"
    assert uses == ["services/auth_service.py"], f"号段常量被引到了别的文件：{uses}"


# ============================================================ ② 真实账号：后来者顶掉先登的


@pytest.mark.auth
@pytest.mark.fast
def test_真实账号第二台登录后第一台的令牌立刻失效(client: TestClient, real_dispatcher) -> None:
    first = _login(client, REAL_PHONE)
    assert _me(client, first) == 200, "第一台登录后本来就该能用"

    second = _login(client, REAL_PHONE)
    assert _me(client, second) == 200, "第二台（新令牌）必须能用 —— 先 commit 再签发，不许把自己也判失效"
    assert _me(client, first) == 401, "第一台必须已经失效（后来者顶掉先登的）"


@pytest.mark.auth
@pytest.mark.fast
def test_每次登录都会把版本号推进一格(client: TestClient, real_dispatcher, db_session) -> None:
    """机制层面对账：`token_version` 是旧令牌失效的**唯一**依据，它必须真的 +1。"""
    before = int(real_dispatcher.token_version or 0)
    _login(client, REAL_PHONE)
    db_session.refresh(real_dispatcher)
    assert int(real_dispatcher.token_version or 0) == before + 1


@pytest.mark.auth
@pytest.mark.fast
def test_被顶掉那台的长连接也要求断开(client: TestClient, real_dispatcher, monkeypatch) -> None:
    """光作废令牌不够（外部检查 C-3）：已经建起来的长连接不会因此断开，照样收推送。

    所以登录时的撤销必须走 `revoke_tokens_and_sockets` —— 这里把"断开"那一步换成探针，
    断言它**真的被排进了后台任务**，而且理由是这次登录。
    """
    import app.services.auth_service as svc

    seen: list[tuple[int, str]] = []

    async def spy(user_id: int, reason: str = "") -> None:
        seen.append((user_id, reason))

    monkeypatch.setattr(svc, "revoke_user_sockets", spy)
    _login(client, REAL_PHONE)
    assert seen == [(real_dispatcher.id, "账号在另一台设备登录")], f"实际排了：{seen}"


# ============================================================ ③ 测试号段豁免


@pytest.mark.auth
@pytest.mark.fast
def test_测试号段的账号两台手机同时在线都还有效(client: TestClient, users: dict) -> None:
    """豁免账号**不许**被顶掉 —— 真机验收本来就要两台设备登同一个号。"""
    phone = users["dispatcher"].phone
    a = _login(client, phone, "pass12345")
    b = _login(client, phone, "pass12345")
    assert _me(client, a) == 200, "测试号段被顶掉了 —— 多端验收会被自己掐死"
    assert _me(client, b) == 200


@pytest.mark.auth
@pytest.mark.fast
def test_豁免账号登录时连版本号都不动(client: TestClient, users: dict, db_session) -> None:
    """豁免必须是"整条路径都不走"，不能是"撤销了再放行"（否则旧令牌已经死了）。"""
    u = users["dispatcher"]
    before = int(u.token_version or 0)
    _login(client, u.phone, "pass12345")
    db_session.refresh(u)
    assert int(u.token_version or 0) == before, "豁免账号不该被推进版本号"


# ============================================================ ④ 反滥用：失败不许踢人


@pytest.mark.auth
@pytest.mark.fast
def test_密码打错不会把已登录的那台踢下线(client: TestClient, real_dispatcher) -> None:
    """撤销只发生在**认证成功之后**。

    否则"知道你手机号"的人拿它连打几次错密码，就能把你从自己手机上踢下线 ——
    一个想防串号的功能反而变成了一条免费的骚扰/踢人通道。
    """
    tok = _login(client, REAL_PHONE)
    assert _me(client, tok) == 200

    bad = client.post("/api/v1/auth/login", json={"phone": REAL_PHONE, "password": "wrong-one"})
    assert bad.status_code == 401
    assert _me(client, tok) == 200, "别人打错密码把我踢下线了"


# ============================================================ ⑤ 与"登出"这条老语义不冲突


@pytest.mark.auth
@pytest.mark.fast
def test_登出仍然作废全部令牌_两个角色都不例外(client: TestClient, real_dispatcher) -> None:
    tok = _login(client, REAL_PHONE)
    assert client.post("/api/v1/auth/logout", headers=auth_headers(tok)).status_code == 200
    assert _me(client, tok) == 401
