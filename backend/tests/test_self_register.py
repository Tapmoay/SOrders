"""自助注册（FEAT-0017，2026-10-11 用户要求：「登录界面……输入电话号码，必须是正确的形式，
然后再输入密码，就可以登录/注册一个账号了，注册，然后默认账号是货主」）。

## 这个文件为什么不放在 `test_auth.py` 里
`test_auth.py` 是**登录/RBAC** 的地盘，而注册是一个**公开写端点** —— 它自己就有一整套边界
（形状、重复、提权、明文、限流、审计）。放一起会让"注册到底该防什么"埋在登录用例中间。

⚠️ 本文件替换掉原来那条 `test_auth.py::test_self_registration_is_closed`（2026-09-18 立的
"注册已整体关闭"判据）。**那条判据没有被削弱，而是换了方向**：当年要钉的是"没人用的公开写接口
必须关掉"（App 入口 v3.40 就拆了、接口却公开着，且短信验证码本地明文回显）；
2026-10-11 用户要求在 App 登录页加注册入口 ⇒ 前提变了（有入口了、不要验证码了），
所以现在要钉的是"开了之后没人能借它提权/刷号/走明文"。

## 每一条对应一个真实后果
| 用例 | 不这样做会发生什么 |
|---|---|
| 注册成功即拿到 token | 用户注册完还得再登一次（当年 SMS 版的形状是发验证码，不是这个形状） |
| 默认角色=货主 | 自助注册出派单员 = 任何人都能管整个系统 |
| 带 `role` 被忽略 | 同上，只是攻击者主动说出来了 |
| 形状不对 422 | 建得出"带空格的账号"：建得出来、再也登不进去 |
| 重复号 400 | 500 或者更糟 —— 静默改了别人的密码 |
| 明文 426 | 密码在公网上裸奔（与登录同一条红线，见 `core/transport.py`） |
| 限流 429 | 一个人一分钟开一万个货主号 |
| 审计一行 | 出了事查不出"这个号是谁在什么时候建的" |

## ⚠️ 号码为什么都用「每用例一个」（而不是共用一个常量）
注册是**真写库**的用例，而 `client`/`db_session` 两个 fixture 都不回滚端点自己 commit 的数据
—— 与全仓绝大多数用例（只读或改后回滚）不同。所以**同一个号跑第二次必然 400**，
共用常量会让"第二次单跑这个文件"全红。限流那条连号段都随 PID 走，理由写在它自己的 docstring 里。
"""

from __future__ import annotations

import os

import pytest
from starlette.testclient import TestClient

from app.services import login_guard

#: 明文通道/加密通道（照 `test_transport_gate.py` 的写法）
PLAINTEXT = {"X-Forwarded-Proto": "http"}
TLS = {"X-Forwarded-Proto": "https"}

#: 每个用例自己的号（见模块 docstring 最后一段）
PHONE_OK = "13911110001"
PHONE_HASH = "13911110005"
PHONE_ROLE = "13911110006"
PHONE_AUDIT = "13911110007"
PHONE_PLAIN = "13911110008"
PHONE_DUP = "13911110009"
PHONE_USERNAME = "13911110003"
PHONE_GHOST = "13911110004"

PASSWORD = "reg-pass-12345"


def _reset() -> None:
    """清掉注册/登录的次数计数（照 `test_login_rate_limit.py::_reset` 的写法）。

    ⚠️ 注册计数与登录失败计数**共用 `login_fail:` 前缀家族**，所以一条 `scan_iter` 就能清干净；
    不清的话本机 Redis 上的计数会跨用例残留，表现成"偶发 429"这种最难查的假红。
    """
    login_guard.reset_for_tests()
    client = login_guard._redis()
    if client is not None:
        try:
            for k in client.scan_iter("login_fail:*"):
                client.delete(k)
        except Exception:  # noqa: BLE001
            pass


@pytest.fixture(autouse=True)
def _clean_counters():
    _reset()
    yield
    _reset()


def _register(
    client: TestClient,
    phone: str = PHONE_OK,
    password: str = PASSWORD,
    full_name: str | None = None,
    **extra,
):
    """注册一次。`extra` 用来塞"提权尝试"的字段（照原样进请求体）。"""
    body: dict = {"phone": phone, "password": password}
    if full_name is not None:
        body["full_name"] = full_name
    body.update(extra)
    return client.post("/api/v1/auth/register", json=body, headers=TLS)


@pytest.mark.auth
@pytest.mark.fast
@pytest.mark.smoke
def test_register_creates_a_shipper_and_returns_a_token(client: TestClient, db_session) -> None:
    """注册成功：默认角色=货主，属性全部服务端写死，**直接给 token**（不用再登一次）。

    ⛔ 这里逐条钉的属性（`is_active` / `is_member` / `category`）不是"顺便看一眼"：
    自助注册的人**没有**任何身份核验（手机号不必真实拥有），所以默认值就是权限边界 ——
    `is_member=True` 会让新号立刻拿到批发商专属价、`is_active=False` 会造出一个登不进去的号。
    """
    from app.models import User
    from app.models.enums import UserRole

    r = _register(client, full_name="新货主")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["role"] == "shipper", "自助注册的默认角色必须是货主"

    db_session.expire_all()
    u = db_session.query(User).filter_by(phone=PHONE_OK).first()
    assert u is not None, "注册没有真的建号"
    assert u.id == body["user_id"]
    assert u.role == UserRole.SHIPPER
    assert u.is_active is True
    assert u.is_member is False
    assert (u.category or "") == ""
    assert u.full_name == "新货主"
    assert u.username == PHONE_OK, "用户名默认与手机号同值（否则用户用手机号登不进去）"

    # 注册完**直接能用**：拿返回的 token 打一个需要登录的端点
    me = client.get(
        "/api/v1/users/me", headers={"Authorization": f"Bearer {body['access_token']}"}
    )
    assert me.status_code == 200, me.text
    assert me.json()["role"] == "shipper"

    # 而且这个号确实能登录（不是"注册送一张废令牌"）
    login = client.post("/api/v1/auth/login", json={"phone": PHONE_OK, "password": PASSWORD})
    assert login.status_code == 200, login.text


@pytest.mark.auth
@pytest.mark.fast
def test_password_is_hashed_not_stored(client: TestClient, db_session) -> None:
    """库里存的必须是哈希（`hash_password` 用 bcrypt，裸口令不该出现在任何地方）。"""
    from app.models import User

    assert _register(client, phone=PHONE_HASH).status_code == 200
    db_session.expire_all()
    u = db_session.query(User).filter_by(phone=PHONE_HASH).first()
    assert u is not None
    assert u.password_hash and u.password_hash != PASSWORD
    assert PASSWORD not in (u.password_hash or "")


@pytest.mark.auth
@pytest.mark.fast
def test_role_in_body_is_ignored(client: TestClient, db_session) -> None:
    """⛔ 提权防线：请求体里带 `role` / `is_member` / `is_active` / `vehicle_type` **一律无效**。

    这条判据的意义在于"**有人把 schema 改成可传 role**"时立刻变红 —— 那是最短的一条提权路：
    自助注册出派单员 = 任何人都能管整个系统（改账号、改价、看全部账本）。
    """
    from app.models import User
    from app.models.enums import UserRole

    r = _register(
        client,
        phone=PHONE_ROLE,
        role="dispatcher",
        is_member=True,
        is_active=False,
        vehicle_type="large",
        salary=99999,
        billing_mode="SALARY",
        driver_rule_id=1,
        downstream_ledger_enabled=False,
        category="派单员",
    )
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "shipper", "请求体带 role 竟然生效了"

    db_session.expire_all()
    u = db_session.query(User).filter_by(phone=PHONE_ROLE).first()
    assert u is not None
    assert u.role == UserRole.SHIPPER
    assert u.is_member is False, "请求体带 is_member 竟然生效了"
    assert u.is_active is True, "请求体带 is_active 竟然生效了"
    assert u.vehicle_type is None
    assert u.salary is None
    assert u.billing_mode is None
    assert (u.category or "") == ""
    # 新号拿到的令牌里写的也必须是货主（role 是从库里读的，这里只是把"哪一步漏了"指出来的那一句）
    me = client.get(
        "/api/v1/users/me", headers={"Authorization": f"Bearer {r.json()['access_token']}"}
    )
    assert me.status_code == 200, me.text
    assert me.json()["role"] == "shipper"


@pytest.mark.auth
@pytest.mark.fast
def test_bad_phone_shape_is_rejected(client: TestClient, db_session) -> None:
    """手机号形状照 `core/phone.py` 的唯一一份规则（`^1\\d{10}$` + `re.ASCII`）。

    ⛔ 全角数字那条不是凑数：Python 的 `\\d` 默认匹配任何 Unicode 十进制数字，
    少了 `re.ASCII` 时 `１３８００００００００`（全角）能通过 —— 而全角号码在拨号盘/导出里
    都不是号码。手机号同时是**登录名**，接受它等于造一个登不进去的号。
    ⚠️ 带空格那两条也一样：`validate_mobile_phone` **故意不 strip**（见 `core/phone.py` 的说明），
    pydantic 2 也不替它 strip（实测 2.12.5 保留原样）。
    """
    from app.models import User

    before = db_session.query(User).count()
    bad = (
        "1380000000",  # 10 位
        "138000000000",  # 12 位
        "23800000000",  # 不以 1 开头
        "1380000000a",  # 含字母
        " 13800000002",  # 带前导空格（账号=登录名，⛔ 不许静默 strip）
        "13800000002 ",  # 带尾随空格
        "１３８００００００００",  # 全角数字（re.ASCII 缺了就漏）
        "",  # 空
    )
    for phone in bad:
        r = _register(client, phone=phone)
        assert r.status_code == 422, f"{phone!r} 竟然被接受了（{r.status_code}）"

    db_session.expire_all()
    assert db_session.query(User).count() == before, "被拒的注册竟然建了号"


@pytest.mark.auth
@pytest.mark.fast
def test_short_password_is_rejected(client: TestClient) -> None:
    """密码口径照建账号那条（`schemas/user.py::UserCreate`）：6~128 位。"""
    assert _register(client, phone=PHONE_OK, password="12345").status_code == 422
    assert _register(client, phone=PHONE_OK, password="").status_code == 422
    assert _register(client, phone=PHONE_OK, password="x" * 129).status_code == 422


@pytest.mark.auth
@pytest.mark.fast
def test_duplicate_phone_is_a_clear_chinese_400(client: TestClient, users: dict) -> None:
    """号已被占 → **400 + 中文原话**（不是 500，也不是"注册成功"）。

    ⛔ 最危险的退化是"当成成功"：那会撞上 `username`/`phone` 唯一索引，要么 500、
    要么（更糟）在别的实现里静默改掉**别人账号的密码**。文案与派单员建号那条逐字一致。
    """
    r = _register(client, phone=users["shipper"].phone)
    assert r.status_code == 400, r.text
    assert r.json()["detail"] == "该手机号已存在"

    # 再注册一次同一个号（这一次是"自己刚建过"）也必须是 400
    assert _register(client, phone=PHONE_DUP).status_code == 200
    again = _register(client, phone=PHONE_DUP)
    assert again.status_code == 400, again.text
    assert again.json()["detail"] == "该手机号已存在"


@pytest.mark.auth
@pytest.mark.fast
def test_username_collision_is_also_blocked(client: TestClient, db_session, users: dict) -> None:
    """手机号没被占、但库里有个**别人的 username 恰好等于这个手机号** → 也要挡。

    不挡的后果很隐蔽：`authenticate_user` 按 `username == lid or phone == lid` 取**第一条**，
    于是这个手机号到底登进哪个号取决于行序 —— 一种"时好时坏"的登录。
    """
    from app.models import User

    ghost = db_session.query(User).filter_by(username=PHONE_USERNAME).first()
    if ghost is None:
        ghost = User(
            username=PHONE_USERNAME,
            phone=PHONE_GHOST,
            password_hash=users["shipper"].password_hash,
            full_name="Ghost",
            role=users["shipper"].role,
        )
        db_session.add(ghost)
        db_session.commit()

    r = _register(client, phone=PHONE_USERNAME)
    assert r.status_code == 400, r.text
    assert r.json()["detail"] == "该用户名已存在"


@pytest.mark.auth
@pytest.mark.fast
def test_plaintext_channel_is_rejected_with_426(client: TestClient, db_session) -> None:
    """⛔ 明文通道拒收凭据（与 `/auth/login` 同一条红线，见 `core/transport.py`）。

    ⚠️ 造法照 `test_transport_gate.py`：带一个 `X-Forwarded-Proto: http` 头就够
    （生产 nginx 反代时这个头必然存在）。`detail` 必须仍然告诉用户**怎么办**（去下新版 APK），
    否则用户在旧 App 上只会看到一句"登录不了"。
    """
    from app.models import User

    before = db_session.query(User).count()
    r = client.post(
        "/api/v1/auth/register",
        json={"phone": PHONE_PLAIN, "password": PASSWORD},
        headers=PLAINTEXT,
    )
    assert r.status_code == 426, r.text
    detail = r.json()["detail"]
    assert "更新" in detail and "http://8.145.40.22/apk" in detail
    assert any("\u4e00" <= ch <= "\u9fa5" for ch in detail), "426 的说明必须是中文"

    db_session.expire_all()
    assert db_session.query(User).count() == before, "明文那次竟然把号建了"
    # https 通道照常能注册（不要为了挡明文把正常路径也挡掉）
    assert _register(client, phone=PHONE_PLAIN).status_code == 200


@pytest.mark.auth
@pytest.mark.fast
def test_registration_is_rate_limited_per_ip(client: TestClient, db_session) -> None:
    """同一个来源 IP 注册太多 → 429 + 中文（防"一个人一分钟开一万个货主号"）。

    ⚠️ 阈值由 `login_guard.MAX_REGISTRATIONS_PER_IP` 决定，用例按它算次数 ——
    把阈值改小不该让这条用例假红（它不是"数字对不对"的判据，是"到底有没有这道门"的判据）。
    ⚠️ 号段按 PID 取：注册是真写库的，固定号段跑第二次会全部撞成"该手机号已存在"。
    """
    from app.models import User

    limit = login_guard.MAX_REGISTRATIONS_PER_IP
    # 号段：139 + 5 位基址 + 5 位序号（共 11 位），基址随 PID 变，避开重复
    base = 20000 + (os.getpid() % 1000) * 100
    ok = 0
    for i in range(limit):
        phone = f"139{base * 100 + i:08d}"
        assert len(phone) == 11, phone
        if _register(client, phone=phone).status_code == 200:
            ok += 1
    assert ok == limit, f"阈值以内应当全放行，实际只有 {ok}/{limit}"

    blocked_phone = f"139{(base + 1) * 100:08d}"
    blocked = _register(client, phone=blocked_phone)
    assert blocked.status_code == 429, blocked.text
    detail = blocked.json()["detail"]
    assert "注册" in detail and ("限制" in detail or "太多" in detail)
    assert any("\u4e00" <= ch <= "\u9fa5" for ch in detail), "429 的说明必须是中文"

    db_session.expire_all()
    assert (
        db_session.query(User).filter_by(phone=blocked_phone).first() is None
    ), "被限流的那次竟然还是把号建了"


@pytest.mark.auth
@pytest.mark.fast
def test_each_registration_writes_one_audit_row(client: TestClient, db_session) -> None:
    """留痕：注册成功写**一行** `USER_CREATE` 审计（⛔ 不新造审计码）。

    内容三条硬要求：① 找得到这个号；② 能看出是**自助注册**（与派单员建号区分开）；
    ③ ⛔ **绝不记密码**，连哈希也不记（审计表是给人看的，不是凭据备份）。
    """
    from app.models.operation_log import OperationLog

    before = db_session.query(OperationLog).filter_by(action="USER_CREATE").count()
    assert _register(client, phone=PHONE_AUDIT).status_code == 200
    db_session.expire_all()

    rows = (
        db_session.query(OperationLog)
        .filter_by(action="USER_CREATE")
        .order_by(OperationLog.id.desc())
        .all()
    )
    assert len(rows) == before + 1, "注册没有留痕，或多留了"
    row = rows[0]
    content = row.change_content or ""  # ⚠️ 列名是 change_content（write_log 的参数叫 change_payload）
    assert PHONE_AUDIT in content
    assert "self_register" in content, "审计里看不出这是自助注册"
    assert PASSWORD not in content, "⛔ 审计里出现了裸口令"
