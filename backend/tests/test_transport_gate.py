# -*- coding: utf-8 -*-
"""传输层兜底：**携带凭据的端点不收明文**（2026-09-19 外部完整检查 C-1 的修法第 5 步）。

### 这条判据为什么放在服务端
客户端的加密保证只在**升级之后的**客户端上成立：老版本 App 的 base_url 编译进去就是
`http://8.145.40.22`，那一版还允许明文 —— 它们**仍然在发明文**。服务端说"我不收"，
明文才真的不存在。

### 判据的信任边界（诚实标注）
后端读 `X-Forwarded-Proto`，它由 **nginx 用连接的真实协议覆盖**后转发
（实测：明文请求自己带 `X-Forwarded-Proto: https`，nginx 日志照样记 `scheme=http`）。
所以"伪造这个头能不能绕过"**不是后端能证明的事**，它由 nginx 的 `proxy_set_header` 保证；
后端这一侧能证明的是：①头说 http → 拒；②头说 https → 放行到正常校验；
③**没有这个头**（= 没经过 nginx，本机开发直连 8000）→ 放行，否则本地开发与全部单测会被打死。
"""

from __future__ import annotations

from tests.conftest import auth_headers  # noqa: F401  (保持与其它测试一致的导入口径)

PLAINTEXT = {"X-Forwarded-Proto": "http"}
TLS = {"X-Forwarded-Proto": "https"}
BODY = {"phone": "13800000001", "password": "definitely-wrong"}


def test_plaintext_login_is_rejected_with_a_way_out(client):
    """明文登录 → 426 + 中文，并且**告诉用户怎么拿到新版本**（短链）。

    老用户被拒之后卡在登录页，而"检查更新"在登录之后的页面里 —— 所以报文必须自带出路。
    """
    r = client.post("/api/v1/auth/login", json=BODY, headers=PLAINTEXT)
    assert r.status_code == 426, f"明文登录应当被拒（实际 {r.status_code}）：{r.text[:200]}"
    detail = r.json()["detail"]
    assert "更新" in detail and "http://8.145.40.22/apk" in detail, f"报文要给可用短链：{detail}"
    assert any("\u4e00" <= ch <= "\u9fff" for ch in detail)


def test_plaintext_oauth2_form_login_is_rejected_too(client):
    """`POST /auth/token`（OAuth2 表单那条）同样携带口令，**不能漏**。"""
    r = client.post(
        "/api/v1/auth/token",
        data={"username": "13800000001", "password": "x"},
        headers=PLAINTEXT,
    )
    assert r.status_code == 426, f"表单登录也带口令（实际 {r.status_code}）：{r.text[:200]}"


def test_https_login_reaches_the_real_check(client):
    """头说 https → 放行到正常校验（口令错就是 401，不是 426）。"""
    r = client.post("/api/v1/auth/login", json=BODY, headers=TLS)
    assert r.status_code in (401, 429), f"应当走到真正的校验：{r.status_code} {r.text[:200]}"


def test_direct_connection_without_proxy_header_still_works(client):
    """**没有** `X-Forwarded-Proto` = 没经过 nginx（本机开发直连、容器内调用、测试客户端）。

    这条路径在生产上不可达（8000 端口对外不通），但拦掉它会把本地开发与全部单测打死 ——
    这个取舍写在 `app/core/transport.py` 的模块说明里。
    """
    r = client.post("/api/v1/auth/login", json=BODY)
    assert r.status_code in (401, 429), f"直连（无代理头）不该被 426 拦：{r.status_code}"


def test_other_endpoints_are_not_gated(client, token_dispatcher):
    """**只拦携带凭据的登录端点**：更新链路必须留在明文可达，否则老客户端永远升级不了。"""
    r = client.get("/api/v1/system/app-version", headers=PLAINTEXT)
    assert r.status_code == 200, f"更新清单必须明文可达（老客户端要能下到新包）：{r.status_code}"
    r2 = client.get("/api/v1/orders", headers=PLAINTEXT)
    assert r2.status_code in (200, 401, 403), f"列表端点这轮刻意不拦：{r2.status_code}"
