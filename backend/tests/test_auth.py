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
def test_self_registration_is_closed(client: TestClient, db_session) -> None:
    """自助注册已整体关闭（2026-09-18 用户要求「注册接口关掉，不需要用了」）。

    判据是**效果**，不是"源码里还有没有字符串"：
    ① 两条路径都取不到（404）；
    ② 库里账号数一个没多；
    ③ 那个手机号也登不进来（没有被换个方式悄悄建号）。
    """
    from app.models import User

    before = db_session.query(User).count()
    phone = "13900000009"
    attempts = (
        ("/api/v1/auth/sms/send", {"phone": phone}),
        (
            "/api/v1/auth/register",
            {
                "username": "reguser9",
                "password": "pass12345",
                "phone": phone,
                "verification_code": "000000",
            },
        ),
    )
    for path, body in attempts:
        r = client.post(path, json=body)
        assert r.status_code == 404, f"{path} 还能调（{r.status_code}）——注册面又开了？"

    db_session.expire_all()
    assert db_session.query(User).count() == before, "注册接口没关严：库里多出了账号"
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
    assert base_ids == sorted(base_ids, reverse=True)  # 仍按 id desc
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
