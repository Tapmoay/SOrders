"""FEAT-0018 账号 ↔ 设备绑定与风控 —— 后端单测。

## 用户口径（逐字要点）
- 「一个账号大概只能绑定一个手机/一个设备（mac/设备序列号，唯一）。只不过……也不说完全只能绑定
  3 个吧，如果超过了 3 个的话，它后面想接着绑定其他手机就不能瞬间，它是有时间限制的……大概
  它如果要再次再增加一个的话，就要过 **6 个月**了」；
- 「我们的一个设备（一个唯一的设备地址）不能同时间、短时间内绑定多个账号 —— 防止有人利用这个
  漏洞批量注册一堆账号来攻击服务器」；
- 「**测试账号除外**（内部账号没有这些限制，随便登录）」；
- 同日口径更新：「一台设备也就是一部手机，它可以绑多部账号，**至少是可以绑 5 个**」；
- 追加拍板：「6 个月冷却**保留**，但**派单员在账号管理里可以手动解冻**（就在编辑当中）——
  司机换手机、手机摔坏了，联系派单员解冻即可」。

## 每一条对应一个真实后果
| 用例 | 不这样做会发生什么 |
|---|---|
| 豁免号不受限 | 内部联调号自己被风控挡住（用户明说"随便登录"） |
| 第 4 台在冷却期内被拒 + 报对日期 | 用户只看到"不行"，不知道该等多久、也不知道能找派单员 |
| 冷却到期后可替换 | 换了手机的人**永远**绑不上新机（"让上一个失效"这件事根本没发生） |
| 同设备 24h 第 3 个账号被拒 | 一台手机一小时内刷出一串号（用户点名要防的那件事） |
| 同设备第 6 个账号撞硬上限 | "至少能绑 5 个"被实现成"只能绑 1 个"（另一种方向的错） |
| 注册同设备 24h 第 2 个号被拒 | 批量刷号的主路径仍然通着 |
| 解绑后能立刻绑新设备 | 派单员"解冻"只是个摆设，司机还是得等 6 个月 |
| 解绑留审计 | 谁在什么时候放开了哪台设备，事后查不出来 |

## ⚠️ 号码与设备标识为什么每用例一个
登录/注册是**真写库**的用例，`client`/`db_session` 两个 fixture 都不回滚端点自己 commit 的数据
（与全仓绝大多数只读用例不同）—— 共用常量会让"第二次单跑这个文件"全红。

## ⚠️ 为什么这里必须自己造账号
`conftest` 那三个共用账号（13800000001/02/03）**全是测试号**（`is_test_account` 为真）——
它们恰恰是本单要**豁免**的那一类，拿它们当"普通用户"会得到"怎么绑都不拦"的假绿。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select
from starlette.testclient import TestClient

from app.core.business_time import utc_now_naive
from app.core.security import hash_password
from app.models import AccountDevice, OperationAction, OperationLog, User
from app.models.enums import UserRole
from app.services import device_service, login_guard
from app.services.auth_service import is_test_account
from tests.conftest import auth_headers

#: 加密通道（照 `test_self_register.py` 的写法；明文由 `core/transport.py` 单独挡，见那个文件的用例）
TLS = {"X-Forwarded-Proto": "https"}
PASSWORD = "dev-pass-12345"


def _reset() -> None:
    """清掉登录/注册/设备登记的次数计数（照 `test_self_register.py::_reset` 的写法）。

    ⚠️ 三类计数**共用 `login_fail:` 前缀家族**（`services/login_guard.py::_key`），所以一条
    `scan_iter` 就能清干净；不清的话本机 Redis 上的计数会跨用例残留，表现成"偶发 429"这种
    最难查的假红 —— 本文件里注册那道闸只有 1 次/24h，最容易被上一轮残留咬到。
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


# ---------------------------------------------------------------- 小工具


def _headers(install_id: str | None = None) -> dict[str, str]:
    """加密通道 + （可选）App 统一注入的那个头：`<install_id>:<服务端签名>`。"""
    head = dict(TLS)
    if install_id:
        head[device_service.DEVICE_HEADER] = f"{install_id}:{device_service.device_token(install_id)}"
    return head


def _login(client: TestClient, phone: str, install_id: str | None = None):
    return client.post(
        "/api/v1/auth/login",
        json={"phone": phone, "password": PASSWORD},
        headers=_headers(install_id),
    )


def _register(client: TestClient, phone: str, install_id: str | None = None):
    return client.post(
        "/api/v1/auth/register",
        json={"phone": phone, "password": PASSWORD},
        headers=_headers(install_id),
    )


def _mk_user(db, phone: str) -> User:
    """造一个**普通**账号（⛔ 不是 conftest 那三个测试号）。"""
    u = User(
        username=phone,
        phone=phone,
        password_hash=hash_password(PASSWORD),
        full_name="设备用例",
        role=UserRole.SHIPPER,
        is_active=True,
        is_member=False,
        category="",
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _ago(*, days: int = 0, months: int = 0) -> datetime:
    """"几天/几个月前"（月份加法的口径与 `device_service` 同一份）。"""
    base = utc_now_naive() - timedelta(days=days)
    return device_service.add_months(base, -months) if months else base


def _bind(db, user_id: int, pairs: list[tuple[str, datetime]], *, source: str = "login") -> list[AccountDevice]:
    """直接往库里放几行绑定 —— 用例要的是"三天前绑的"这种**前提**，不能靠登录去等。"""
    rows = [
        AccountDevice(
            user_id=user_id,
            device_id=device_id,
            bound_at=when,
            last_seen_at=when,
            source=source,
        )
        for device_id, when in pairs
    ]
    db.add_all(rows)
    db.commit()
    for row in rows:
        db.refresh(row)
    return rows


def _active(db, user_id: int) -> list[AccountDevice]:
    return [r for r in device_service.list_bindings(db, user_id) if r.unbound_at is None]


def _cn(text: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fa5" for ch in text)


# ---------------------------------------------------------------- ① 豁免


@pytest.mark.auth
@pytest.mark.fast
def test_test_account_ignores_every_device_limit(client: TestClient, db_session) -> None:
    """测试号（`1380000000` + 一位）：连绑 5 台都不拦，而且**连行都不记**。

    用户原话：「测试账号除外（内部账号没有这些限制，随便登录）」。
    ⛔ 后半句（不记行）同样是判据：测试号要是往 `account_devices` 里写，派单员的设备列表
    会被内部联调号占满，而且它会跟着"同设备 24h ≤2"那道闸去挡**真**用户在同一台机器上的号。

    ⚠️ `conftest` 那三个共用账号（13800000001/02/03）**本来就是测试号** —— 本文件其余用例
    必须自己造普通号（`_mk_user`）才测得出闸门，这一条反而要用真测试号。
    """
    phone = "13800000009"
    user = _mk_user(db_session, phone)
    assert is_test_account(phone), "前提：这必须是 is_test_account 认的那一类号"

    for i in range(5):
        r = _login(client, phone, f"exempt-device-{i:02d}")
        assert r.status_code == 200, r.text
    db_session.expire_all()
    assert device_service.list_bindings(db_session, user.id) == [], (
        "测试号不该在设备绑定表里留下任何一行"
    )


# ---------------------------------------------------------------- ② 账号侧：3 台 + 6 个月冷却


@pytest.mark.auth
@pytest.mark.fast
def test_fourth_device_in_cooldown_is_rejected_with_the_expiry_date(
    client: TestClient, db_session
) -> None:
    """第 4 台在冷却期内 → 403，而且**报的是最早那台的可替换日期**（用户要的那句话）。"""
    phone = "13911120001"
    user = _mk_user(db_session, phone)
    rows = _bind(
        db_session,
        user.id,
        [
            ("old-device-0001", _ago(days=40)),
            ("old-device-0002", _ago(days=20)),
            ("old-device-0003", _ago(days=5)),
        ],
    )
    expires_at = device_service.binding_expires_at(rows[0].bound_at)

    r = _login(client, phone, "brand-new-device-1")
    assert r.status_code == 403, r.text
    detail = r.json()["detail"]
    assert f"{expires_at:%Y-%m-%d}" in detail, f"话术里没有最早可替换日期：{detail}"
    assert _cn(detail) and "派单员" in detail and "解冻" in detail, detail

    db_session.expire_all()
    active = _active(db_session, user.id)
    assert len(active) == 3, "被拒的那次竟然动了绑定"
    assert all(row.device_id != "brand-new-device-1" for row in active), "被拒的设备还是绑上了"


@pytest.mark.auth
@pytest.mark.fast
def test_cooled_down_oldest_device_can_be_replaced(client: TestClient, db_session) -> None:
    """最旧那台过了 6 个月 → "让上一个失效"，新设备立刻绑上（用户原话那条路）。"""
    phone = "13911120002"
    user = _mk_user(db_session, phone)
    _bind(
        db_session,
        user.id,
        [
            ("stale-device-0001", _ago(months=7)),
            ("stale-device-0002", _ago(days=20)),
            ("stale-device-0003", _ago(days=5)),
        ],
    )

    r = _login(client, phone, "brand-new-device-2")
    assert r.status_code == 200, r.text

    db_session.expire_all()
    bindings = device_service.list_bindings(db_session, user.id)
    replaced = next(b for b in bindings if b.device_id == "stale-device-0001")
    assert replaced.unbound_at is not None, "过了冷却期的最旧那台没有被顶掉"
    assert replaced.unbind_reason == "expired", replaced.unbind_reason
    fresh = next(b for b in bindings if b.device_id == "brand-new-device-2")
    assert fresh.unbound_at is None and fresh.source == "login"
    assert len([b for b in bindings if b.unbound_at is None]) == 3, "有效绑定必须还是 3 台"


@pytest.mark.auth
@pytest.mark.fast
def test_known_device_only_refreshes_last_seen(client: TestClient, db_session) -> None:
    """本机再登录一次只刷 `last_seen_at`：**不占额度、也不动 `bound_at`**（冷却起点不能被动摇）。"""
    phone = "13911120003"
    user = _mk_user(db_session, phone)
    bound_at = _ago(days=30)
    (row,) = _bind(db_session, user.id, [("steady-device-01", bound_at)])

    assert _login(client, phone, "steady-device-01").status_code == 200
    db_session.expire_all()
    again = device_service.get_binding(db_session, user.id, row.id)
    assert again is not None and again.bound_at == bound_at, "本机登录把冷却起点往后推了"
    assert again.last_seen_at >= bound_at
    assert len(_active(db_session, user.id)) == 1, "本机登录重复记了一行"


# ---------------------------------------------------------------- ③ 设备侧：5 个硬上限 + 24h ≤2


@pytest.mark.auth
@pytest.mark.fast
def test_third_account_on_one_device_within_24h_is_rejected(client: TestClient, db_session) -> None:
    """同一台设备 24 小时内第 3 个新增账号 → 403（用户点名要防的"一台手机刷一串号"）。"""
    phones = ["13911121001", "13911121002", "13911121003"]
    for phone in phones:
        _mk_user(db_session, phone)
    device_id = "shared-phone-0001"

    assert _login(client, phones[0], device_id).status_code == 200
    assert _login(client, phones[1], device_id).status_code == 200

    r = _login(client, phones[2], device_id)
    assert r.status_code == 403, r.text
    detail = r.json()["detail"]
    assert "24 小时" in detail and _cn(detail), detail

    db_session.expire_all()
    third = db_session.query(User).filter_by(phone=phones[2]).first()
    assert third is not None and device_service.list_bindings(db_session, third.id) == []


@pytest.mark.auth
@pytest.mark.fast
def test_sixth_account_on_one_device_hits_the_hard_cap(client: TestClient, db_session) -> None:
    """一台设备最多 5 个账号（用户：「至少是可以绑 5 个」）—— 第 6 个连"慢一点"都不行。

    ⛔ 这条用例抵的是**另一个方向**的错：把上限实现成 1（只许一机一号）在"第 3 个账号被拒"
    那条用例里**看不出来**（两条都会红在那个 403 上）。
    """
    device_id = "shared-phone-0002"
    owners = [_mk_user(db_session, f"1391112200{i}") for i in range(5)]
    for owner in owners:
        # 都是两天前绑的：24 小时速率闸在这条上**不该**出声，出声的必须是硬上限
        _bind(db_session, owner.id, [(device_id, _ago(days=2))])

    late = _mk_user(db_session, "13911122999")
    r = _login(client, "13911122999", device_id)
    assert r.status_code == 403, r.text
    detail = r.json()["detail"]
    assert f"已经绑了 {device_service.MAX_ACCOUNTS_PER_DEVICE} 个账号" in detail, detail
    db_session.expire_all()
    assert device_service.list_bindings(db_session, late.id) == []


@pytest.mark.auth
@pytest.mark.fast
def test_second_registration_from_one_device_within_24h_is_429(
    client: TestClient, db_session
) -> None:
    """注册那条更紧：同一台设备 24 小时只能开**一个**新号（挡批量刷号的关键那道闸）。"""
    device_id = "register-phone-01"

    first = _register(client, "13911123001", device_id)
    assert first.status_code == 200, first.text
    db_session.expire_all()
    owner = db_session.query(User).filter_by(phone="13911123001").first()
    assert owner is not None
    rows = device_service.list_bindings(db_session, owner.id)
    assert len(rows) == 1 and rows[0].device_id == device_id and rows[0].source == "register"

    second = _register(client, "13911123002", device_id)
    assert second.status_code == 429, second.text
    detail = second.json()["detail"]
    assert "24 小时" in detail and "注册" in detail and _cn(detail), detail

    db_session.expire_all()
    assert db_session.query(User).filter_by(phone="13911123002").first() is None, (
        "被挡下的注册竟然还是把号建了"
    )


# ---------------------------------------------------------------- ④ 派单员解冻


@pytest.mark.auth
@pytest.mark.fast
def test_dispatcher_unbind_all_lets_the_new_phone_in_immediately(
    client: TestClient, db_session, token_dispatcher: str
) -> None:
    """一键解冻之后**立刻**能绑新设备 —— "司机换手机"那条路（用户拍板的手动解冻）。"""
    phone = "13911124001"
    user = _mk_user(db_session, phone)
    _bind(
        db_session,
        user.id,
        [
            ("keep-device-0001", _ago(days=40)),
            ("keep-device-0002", _ago(days=20)),
            ("keep-device-0003", _ago(days=5)),
        ],
    )
    assert _login(client, phone, "want-device-0001").status_code == 403, "前提：他现在绑不上第 4 台"

    head = auth_headers(token_dispatcher)
    listed = client.get(f"/api/v1/users/{user.id}/devices", headers=head)
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert len(body) == 3 and all(item["active"] for item in body), body
    assert all(item["expires_at"] and item["device_id"] for item in body), body

    assert client.post(f"/api/v1/users/{user.id}/devices/unbind-all", headers=head).status_code == 204

    assert _login(client, phone, "want-device-0001").status_code == 200, "解冻之后还是绑不上新设备"

    db_session.expire_all()
    bindings = device_service.list_bindings(db_session, user.id)
    active = [b for b in bindings if b.unbound_at is None]
    assert [b.device_id for b in active] == ["want-device-0001"], active
    # 解冻**不删行**：三台历史还在，而且列表里看得到（active=false）
    listed = client.get(f"/api/v1/users/{user.id}/devices", headers=head).json()
    assert len(listed) == 4 and sum(1 for item in listed if not item["active"]) == 3, listed


@pytest.mark.auth
@pytest.mark.fast
def test_single_unbind_is_idempotent_and_leaves_one_audit_line(
    client: TestClient, db_session, token_dispatcher: str, users: dict[str, User]
) -> None:
    """解冻一台：204 + 一条审计（带 device_id 与 reason=admin）；再解一次不再写审计。"""
    phone = "13911124002"
    user = _mk_user(db_session, phone)
    rows = _bind(db_session, user.id, [("audit-device-0001", _ago(days=40)), ("audit-device-0002", _ago(days=5))])
    target = rows[0]
    head = auth_headers(token_dispatcher)

    before = (
        db_session.query(OperationLog)
        .filter(OperationLog.action == OperationAction.USER_DEVICE_UNBIND)
        .count()
    )
    r = client.post(f"/api/v1/users/{user.id}/devices/{target.id}/unbind", headers=head)
    assert r.status_code == 204, r.text

    db_session.expire_all()
    logs = (
        db_session.query(OperationLog)
        .filter(OperationLog.action == OperationAction.USER_DEVICE_UNBIND)
        .order_by(OperationLog.id.desc())
        .all()
    )
    assert len(logs) == before + 1, "解冻没有留痕"
    payload = json.loads(logs[0].change_content or "{}")
    assert payload.get("device_id") == "audit-device-0001", payload
    assert payload.get("reason") == device_service.UNBIND_REASON_ADMIN, payload
    assert logs[0].operator_id == users["dispatcher"].id, "审计里的操作人不是点了这一下的派单员"

    # 幂等：同一台再解一次 —— 204、且**不**再写一条（没有发生新的事情）
    assert client.post(f"/api/v1/users/{user.id}/devices/{target.id}/unbind", headers=head).status_code == 204
    db_session.expire_all()
    assert (
        db_session.query(OperationLog)
        .filter(OperationLog.action == OperationAction.USER_DEVICE_UNBIND)
        .count()
        == before + 1
    ), "重复解冻又写了一条审计"

    # 不存在的 binding（乱猜 id）也是 204、不写审计
    assert client.post(f"/api/v1/users/{user.id}/devices/99999999/unbind", headers=head).status_code == 204


@pytest.mark.auth
@pytest.mark.fast
def test_unbind_all_audit_carries_the_count(
    client: TestClient, db_session, token_dispatcher: str
) -> None:
    """一键解冻记的是"这一次解开了几台"（`count`）—— 派单员点的是"全部"。"""
    phone = "13911124003"
    user = _mk_user(db_session, phone)
    _bind(db_session, user.id, [("count-device-0001", _ago(days=40)), ("count-device-0002", _ago(days=20))])
    head = auth_headers(token_dispatcher)

    assert client.post(f"/api/v1/users/{user.id}/devices/unbind-all", headers=head).status_code == 204

    db_session.expire_all()
    log = (
        db_session.query(OperationLog)
        .filter(OperationLog.action == OperationAction.USER_DEVICE_UNBIND)
        .order_by(OperationLog.id.desc())
        .first()
    )
    assert log is not None, "一键解冻没有留痕"
    payload = json.loads(log.change_content or "{}")
    assert payload.get("count") == 2 and payload.get("user_id") == user.id, payload
    assert payload.get("reason") == device_service.UNBIND_REASON_ADMIN, payload

    # 没有可解冻的：204 且不再写审计
    before = db_session.query(OperationLog).filter(OperationLog.action == OperationAction.USER_DEVICE_UNBIND).count()
    assert client.post(f"/api/v1/users/{user.id}/devices/unbind-all", headers=head).status_code == 204
    db_session.expire_all()
    assert (
        db_session.query(OperationLog).filter(OperationLog.action == OperationAction.USER_DEVICE_UNBIND).count()
        == before
    )


@pytest.mark.auth
@pytest.mark.fast
def test_device_endpoints_are_dispatcher_only(
    client: TestClient, db_session, token_dispatcher: str, token_shipper: str, token_driver: str
) -> None:
    """三个端点都是**签名级**角色门槛（`USER_MANAGE` 只有派单员有）—— 货主/司机一律 403。"""
    user = _mk_user(db_session, "13911125001")
    _bind(db_session, user.id, [("role-device-0001", _ago(days=3))])

    for token in (token_shipper, token_driver):
        head = auth_headers(token)
        assert client.get(f"/api/v1/users/{user.id}/devices", headers=head).status_code == 403
        assert client.post(f"/api/v1/users/{user.id}/devices/1/unbind", headers=head).status_code == 403
        assert client.post(f"/api/v1/users/{user.id}/devices/unbind-all", headers=head).status_code == 403

    db_session.expire_all()
    assert len(_active(db_session, user.id)) == 1, "被 403 挡下的请求竟然动了数据"
    assert client.get(f"/api/v1/users/{user.id}/devices", headers=auth_headers(token_dispatcher)).status_code == 200


# ---------------------------------------------------------------- ⑤ 设备登记（公开端点）


@pytest.mark.auth
@pytest.mark.fast
def test_device_register_signs_the_install_id(client: TestClient) -> None:
    """公开登记：发一份服务端 HMAC；形状不对的 install_id → 400 + 中文。"""
    device_id = "sig-check-device-1"
    r = client.post("/api/v1/devices/register", json={"install_id": device_id}, headers=TLS)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["device_id"] == device_id
    token = body["token"]
    assert len(token) == 64 and token == device_service.device_token(device_id)
    assert device_service.device_id_from_header(f"{device_id}:{token}") == device_id

    # 太短：schema 那一层就挡下来了（`Field(min_length=8)`）
    short = client.post("/api/v1/devices/register", json={"install_id": "短"}, headers=TLS)
    assert short.status_code == 422, short.text
    # 长度够、字符集不对（有空格与叹号）：端点自己挡，回**中文**说明
    bad_shape = client.post("/api/v1/devices/register", json={"install_id": "bad id with space!"}, headers=TLS)
    assert bad_shape.status_code == 400, bad_shape.text
    assert _cn(bad_shape.json()["detail"]), bad_shape.text


@pytest.mark.auth
@pytest.mark.fast
def test_forged_device_signature_is_treated_as_no_device(client: TestClient, db_session) -> None:
    """签名对不上 = **当作没有设备信息**：能登录，但**不记绑定**（契约第 2 条）。"""
    phone = "13911126001"
    user = _mk_user(db_session, phone)
    forged = {**TLS, device_service.DEVICE_HEADER: "forged-device-01:" + "0" * 64}

    assert device_service.device_id_from_header("forged-device-01:" + "0" * 64) is None
    r = client.post("/api/v1/auth/login", json={"phone": phone, "password": PASSWORD}, headers=forged)
    assert r.status_code == 200, r.text

    db_session.expire_all()
    assert device_service.list_bindings(db_session, user.id) == [], "伪造的签名竟然记了绑定"


@pytest.mark.auth
@pytest.mark.fast
def test_device_register_is_rate_limited_per_ip(client: TestClient) -> None:
    """公开端点必须有来源 IP 限流（防"一个人一分钟领一万份签名"）。"""
    limit = login_guard.MAX_DEVICE_REGISTRATIONS_PER_IP
    ok = 0
    for i in range(limit):
        r = client.post("/api/v1/devices/register", json={"install_id": f"rate-limit-dev-{i:03d}"}, headers=TLS)
        if r.status_code == 200:
            ok += 1
    assert ok == limit, f"阈值以内应当全放行，实际只有 {ok}/{limit}"

    blocked = client.post("/api/v1/devices/register", json={"install_id": "rate-limit-dev-999"}, headers=TLS)
    assert blocked.status_code == 429, blocked.text
    assert _cn(blocked.json()["detail"]), blocked.text
