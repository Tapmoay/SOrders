"""传输层兜底：**明文请求不许携带凭据**（2026-09-19 外部完整检查 C-1 的修法第 5 步）。

### 为什么需要服务端这一道
客户端的加密保证只在**升级之后的**客户端上成立：老版本 App 编译进去的地址是
`http://8.145.40.22`，而且那一版的 `network_security_config` 还写着
`cleartextTrafficPermitted="true"` —— 它们**仍然在发明文**。同网段的人 ARP 欺骗就能读到
派单员的 JWT，以及登录报文里的**明文口令**（报告里"伪造 401 把用户逼回登录页"那条利用路径，
目标就是让口令在明文通道上再走一遍）。只有服务端说"我不收明文"，明文才真的不存在。

### 判据为什么不能被客户端伪造
`X-Forwarded-Proto` 由 **nginx 用连接的真实协议**（`$scheme`）**覆盖**后转发
（`proxy_set_header` 是"设置/替换"语义；`X-Forwarded-For` 必须用 `$proxy_add_x_forwarded_for`
才追加，正说明裸写法会覆盖）。实测：明文请求自己带 `X-Forwarded-Proto: https`，
nginx 日志照样记 `scheme=http`。另外后端 8000 端口对外不通（实测），没人能绕过 nginx
直接跟 uvicorn 说话。

### 为什么"没有这个头"时不拦
没有 `X-Forwarded-Proto` = 这个请求**没经过 nginx**（本机开发直连 8000、容器内调用、测试客户端）。
生产上 8000 端口对外不可达，所以这条路径不构成公开入口；而拦掉它会把本地开发与全部单测打死。

### 边界（刻意只做到这里）
只拦**携带凭据的登录端点**，不拦全站：
- 更新链路（`GET /api/v1/system/app-version`）与安装包下载**必须留在明文可达** ——
  老客户端要能下到新包，否则一开闸它们就永远升级不了（那才是真的把用户锁死）；
- 等到明文流量接近 0（`grep -c 'scheme=http' /var/log/nginx/access.log`）再考虑全站。
"""

from __future__ import annotations

from fastapi import HTTPException, Request, status

#: 更新提示里给的短链（nginx 上的 `location = /apk`，见 `deploy/nginx/`）。
#: 老 App 的登录页只有一句 toast 能显示这句话，所以链接必须**短到能念出来**。
UPDATE_URL = "http://8.145.40.22/apk"


def is_plaintext_via_proxy(request: Request) -> bool:
    """这个请求是不是"经 nginx 的明文"进来的。

    - 头存在且不是 `https` → 是（80/8080 那两个明文 server 块都会写 `http`）；
    - 头不存在 → 不是（没经过 nginx，属于本机/内部调用，见模块说明）；
    - 头是 `https` → 不是。
    """
    proto = (request.headers.get("x-forwarded-proto") or "").strip().lower()
    return bool(proto) and proto != "https"


def reject_plaintext_credentials(request: Request) -> None:
    """携带凭据的端点调它：明文一律拒绝，并**告诉用户怎么拿到新版本**。

    用 **426 Upgrade Required**：语义就是"换个更安全的传输再来"，
    而且客户端拿到非 2xx 会把 `detail` 原样显示给用户（安卓 `ApiClient.parseDetail`）。
    """
    if not is_plaintext_via_proxy(request):
        return
    raise HTTPException(
        status_code=status.HTTP_426_UPGRADE_REQUIRED,
        detail=(
            "本次更新已开启加密传输：登录信息不能再走明文，请先更新 App 再登录。"
            f"手机浏览器打开 {UPDATE_URL} 即可下载安装（原账号密码不变）。"
        ),
        headers={"Upgrade": "TLS/1.2"},
    )
