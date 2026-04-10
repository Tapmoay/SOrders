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
def test_register_shipper_sms_and_login(client: TestClient) -> None:
    """注册：用户名 + 密码 + 手机号 + 验证码；测试环境 SMS_REVEAL_CODE 返回明文 code。"""
    phone = "13900000009"
    r0 = client.post("/api/v1/auth/sms/send", json={"phone": phone})
    assert r0.status_code == 200
    body = r0.json()
    assert body.get("ok") is True
    code = body.get("code")
    assert code and len(code) >= 4

    r = client.post(
        "/api/v1/auth/register",
        json={
            "username": "reguser9",
            "password": "pass12345",
            "phone": phone,
            "verification_code": code,
        },
    )
    assert r.status_code == 200
    tok = r.json()
    assert tok["token_type"] == "bearer"

    r2 = client.post(
        "/api/v1/auth/login",
        json={"username": "reguser9", "password": "pass12345"},
    )
    assert r2.status_code == 200


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
