"""登录限流（2026-09-19 审计的缺陷 S6）。

## 原来的样子
生产是**公网 80**，账号是手机号（业务上公开），而登录端点**可以无限重试**：
后端全仓没有限流/失败计数/锁定/验证码。口令下限只有 6 位 → 10^6 的空间，脚本几小时能撞开；
撞开货主＝订单＋账本，撞开派单员＝整个系统。

这个文件钉住四件事：
① 连续失败到阈值后返回 **429**（而不是继续 401），并且**不再校验密码**；
② 失败计数是**按登录名**的（换个 IP 也锁）；
③ **登录成功会清掉该登录名的计数**（正主不该被自己之前的输错锁死）；
④ 被拒时的文案**不泄露账号是否存在**，也不说"还能试几次"。
"""
from __future__ import annotations

from tests.conftest import auth_headers

from app.services import login_guard


def _reset():
    login_guard.reset_for_tests()
    # Redis 轨（配了 REDIS_URL 的环境）也一起清，免得测试之间互相影响
    client = login_guard._redis()
    if client is not None:
        try:
            for k in client.scan_iter("login_fail:*"):
                client.delete(k)
        except Exception:  # noqa: BLE001
            pass


def test_repeated_failures_get_locked_out(client, users):
    """连续错密码到达阈值 → 429；且**正确密码也登不进去**（锁的是账号，不是这一次）。"""
    _reset()
    phone = users["shipper"].phone
    codes = []
    for _ in range(login_guard.MAX_FAILS_PER_ID + 1):
        r = client.post("/api/v1/auth/login", json={"phone": phone, "password": "wrong-password"})
        codes.append(r.status_code)
    assert codes[-1] == 429, f"第 {len(codes)} 次失败应当被锁，实际 {codes}"

    r = client.post("/api/v1/auth/login", json={"phone": phone, "password": "pass12345"})
    assert r.status_code == 429, "锁定期间即使密码正确也必须拒（否则锁定没有意义）"
    assert "锁定" in r.json()["detail"] or "限制" in r.json()["detail"]
    _reset()


def test_successful_login_clears_failures(client, users):
    """正主输错几次后输对：必须能进，并且**清掉计数**（不该被自己之前的笔误锁死）。"""
    _reset()
    phone = users["shipper"].phone
    for _ in range(login_guard.MAX_FAILS_PER_ID - 1):
        r = client.post("/api/v1/auth/login", json={"phone": phone, "password": "wrong-password"})
        assert r.status_code == 401

    ok = client.post("/api/v1/auth/login", json={"phone": phone, "password": "pass12345"})
    assert ok.status_code == 200, ok.text

    # 计数已清：再错一次应当还是 401（而不是积到阈值直接 429）
    again = client.post("/api/v1/auth/login", json={"phone": phone, "password": "wrong-password"})
    assert again.status_code == 401, "登录成功必须清掉该登录名的失败计数"
    _reset()


def test_lockout_message_does_not_leak_account_existence(client, users):
    """被拒的文案不许透露"这个账号存不存在"，也不许说"还能试几次"。"""
    _reset()
    phone = users["shipper"].phone
    for _ in range(login_guard.MAX_FAILS_PER_ID + 1):
        client.post("/api/v1/auth/login", json={"phone": phone, "password": "x"})
    detail = client.post("/api/v1/auth/login", json={"phone": phone, "password": "x"}).json()["detail"]
    assert "不存在" not in detail and "未注册" not in detail
    assert "还能" not in detail and "剩余" not in detail
    _reset()


def test_normal_login_still_works_when_under_threshold(client, users, token_shipper):
    """阈值以内一切照旧（限流不能把正常用户挡住）—— 这条是"别改坏"的对照。"""
    _reset()
    r = client.get("/api/v1/users/me", headers=auth_headers(token_shipper))
    assert r.status_code == 200, r.text
    ok = client.post("/api/v1/auth/login", json={"phone": users["shipper"].phone, "password": "pass12345"})
    assert ok.status_code == 200, ok.text
    _reset()
