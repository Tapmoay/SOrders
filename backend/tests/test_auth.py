"""
Authentication and RBAC: login, token validation, permission-denied routes.

Requirements Coverage:
- FR-SH-XXX: 货主认证
- FR-DR-XXX: 司机认证
- FR-SP-XXX: 派单员认证
- 权限矩阵验证 (DOMAIN_MODEL.md)
"""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from tests.conftest import auth_headers


@pytest.mark.auth
@pytest.mark.fast
@pytest.mark.smoke
def test_login_success(client: TestClient, users: dict) -> None:
    r = client.post(
        "/api/v1/auth/login",
        json={"phone": "13800000002", "password": "pass12345"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["token_type"] == "bearer"
    assert "access_token" in body
    assert body["user_id"] == users["shipper"].id


@pytest.mark.auth
@pytest.mark.fast
def test_login_invalid_password(client: TestClient) -> None:
    r = client.post(
        "/api/v1/auth/login",
        json={"phone": "13800000002", "password": "wrong-password"},
    )
    assert r.status_code == 401


@pytest.mark.auth
@pytest.mark.fast
def test_sms_registration_path_is_still_closed(client: TestClient, db_session) -> None:
    """**短信**那条注册路径仍然是关的（2026-09-18 删掉的原因只解除了"注册"这一半）。

    ⚠️ 这条用例 2026-10-11（FEAT-0017）被改写过：原来它叫
    `test_self_registration_is_closed`，同时钉 `/auth/register` 与 `/auth/sms/send` 两条 404。
    用户要求把注册拿回来（连 App 入口一起加），所以 `/auth/register` 那一半**移出本用例**、
    改成"注册是开的"一组正向判据（`tests/test_self_register.py`，
    其中明文/提权/限流/审计逐条钉着）。
    `/auth/sms/send` 这一半**一个字不改**：当年删它的真正理由是
    `sms_reveal_code=true` 时验证码**明文回显**，等于没有验证 —— 本次范围明确不含短信。
    """
    from app.models import User

    before = db_session.query(User).count()
    phone = "13900000009"
    r = client.post("/api/v1/auth/sms/send", json={"phone": phone})
    assert r.status_code == 404, f"/api/v1/auth/sms/send 还能调（{r.status_code}）——短信重开了？"

    db_session.expire_all()
    assert db_session.query(User).count() == before, "短信那条路竟然建了号"
    assert db_session.query(User).filter_by(phone=phone).first() is None
    assert (
        client.post(
            "/api/v1/auth/login", json={"phone": phone, "password": "pass12345"}
        ).status_code
        == 401
    )


@pytest.mark.auth
@pytest.mark.dispatcher
@pytest.mark.fast
def test_dispatcher_swap_shipper_driver_role(
    client: TestClient, token_dispatcher: str, users: dict
) -> None:
    shipper = users["shipper"]
    driver = users["driver"]
    r = client.post(
        f"/api/v1/users/{shipper.id}/swap-shipper-driver",
        headers=auth_headers(token_dispatcher),
    )
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "driver"
    r2 = client.post(
        f"/api/v1/users/{shipper.id}/swap-shipper-driver",
        headers=auth_headers(token_dispatcher),
    )
    assert r2.status_code == 200
    assert r2.json()["role"] == "shipper"
    r3 = client.post(
        f"/api/v1/users/{driver.id}/swap-shipper-driver",
        headers=auth_headers(token_dispatcher),
    )
    assert r3.status_code == 200
    assert r3.json()["role"] == "shipper"
    r4 = client.post(
        f"/api/v1/users/{driver.id}/swap-shipper-driver",
        headers=auth_headers(token_dispatcher),
    )
    assert r4.status_code == 200
    assert r4.json()["role"] == "driver"


@pytest.mark.auth
@pytest.mark.dispatcher
@pytest.mark.fast
def test_dispatcher_can_list_users(client: TestClient, token_dispatcher: str) -> None:
    r = client.get("/api/v1/users", headers=auth_headers(token_dispatcher))
    assert r.status_code == 200
    assert isinstance(r.json(), list)


@pytest.mark.auth
@pytest.mark.shipper
@pytest.mark.fast
def test_shipper_cannot_list_users(client: TestClient, token_shipper: str) -> None:
    r = client.get("/api/v1/users", headers=auth_headers(token_shipper))
    assert r.status_code == 403


@pytest.mark.auth
@pytest.mark.dispatcher
@pytest.mark.fast
def test_list_users_q_searches_name_and_phone(
    client: TestClient, token_dispatcher: str, token_shipper: str, users: dict
) -> None:
    """q 按「姓名 or 手机号」模糊搜索；不传 q / q 为空白串时行为与原来完全一致。"""
    h = auth_headers(token_dispatcher)

    base = client.get("/api/v1/users", headers=h)
    assert base.status_code == 200, base.text
    base_ids = [u["id"] for u in base.json()]
    # ⚠️ 这里**不再断言 id 倒序**：2026-09-22 起名册走**统一排序规则**
    #    ——「常用度（谁被选得多）→ 先创建的在前」，谁在前取决于**库里有没有使用记录**，
    #    而这条测试的库是共享的（别的用例可能用过其中几个账号），按 id 判必然假红。
    #    排序规则本身钉在两处：红线 `_tools/qa/_check_list_order.py`（53 项）
    #    与 `tests/test_audit_round16_counters.py`（计数由库自增）。
    #    这条测试只管它自己的题目：**不传 q / q 为空白串时行为完全一致**。
    assert users["shipper"].id in base_ids

    # .strip() 后为空 → 不筛：与不传 q 完全等价
    for params in ({}, {"q": ""}, {"q": "   "}):
        r = client.get("/api/v1/users", params=params, headers=h)
        assert r.status_code == 200, r.text
        assert [u["id"] for u in r.json()] == base_ids

    # 姓名模糊命中（且返回的每一行都确实命中姓名或手机号）
    by_name = client.get("/api/v1/users", params={"q": "Shipper"}, headers=h)
    assert by_name.status_code == 200, by_name.text
    name_rows = by_name.json()
    assert users["shipper"].id in [u["id"] for u in name_rows]
    assert all(
        "Shipper" in (u.get("full_name") or "") or "Shipper" in (u.get("phone") or "")
        for u in name_rows
    )

    # 手机号局部模糊
    by_phone = client.get("/api/v1/users", params={"q": "1380000000"}, headers=h)
    assert by_phone.status_code == 200, by_phone.text
    assert users["shipper"].id in [u["id"] for u in by_phone.json()]

    # 手机号精确定位到唯一一人
    exact = client.get("/api/v1/users", params={"q": "13800000002"}, headers=h)
    assert exact.status_code == 200, exact.text
    assert [u["id"] for u in exact.json()] == [users["shipper"].id]

    # q 与既有 role 筛选叠加（不破坏原筛选）
    combo = client.get(
        "/api/v1/users", params={"q": "1380000000", "role": "dispatcher"}, headers=h
    )
    assert combo.status_code == 200, combo.text
    combo_rows = combo.json()
    assert combo_rows
    assert all(u["role"] == "dispatcher" for u in combo_rows)
    assert users["dispatcher"].id in [u["id"] for u in combo_rows]

    # q 与既有 limit 叠加
    limited = client.get("/api/v1/users", params={"q": "1380000000", "limit": 1}, headers=h)
    assert limited.status_code == 200, limited.text
    assert len(limited.json()) == 1

    # 权限未变：货主仍不可搜索用户
    denied = client.get("/api/v1/users", params={"q": "Shipper"}, headers=auth_headers(token_shipper))
    assert denied.status_code == 403


@pytest.mark.auth
@pytest.mark.shipper
@pytest.mark.fast
@pytest.mark.regression
def test_shipper_cannot_dispatch_order(
    client: TestClient, token_shipper: str, token_driver: str
) -> None:
    r = client.post(
        "/api/v1/orders/1/assign",
        headers=auth_headers(token_shipper),
        json={"driver_id": 1},
    )
    assert r.status_code == 403


@pytest.mark.auth
@pytest.mark.fast
@pytest.mark.unit
def test_token_fake_role_claim_uses_database_role(client: TestClient, users: dict) -> None:
    """JWT 内伪造更高角色无效：/users/me 以数据库角色为准（仍须合法 sub+签名）。"""
    from app.core.security import create_access_token

    bad = create_access_token(str(users["shipper"].id), {"role": "dispatcher"})
    r = client.get("/api/v1/users/me", headers=auth_headers(bad))
    assert r.status_code == 200
    assert r.json()["role"] == "shipper"
