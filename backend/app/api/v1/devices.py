"""设备登记端点（FEAT-0018，2026-10-11 用户要求）。

`POST /api/v1/devices/register` —— **公开**（无 token）：App 首次启动时拿本机的 install_id
换一份服务端签名，之后的每个请求都带 `X-Device-Id: <install_id>:<token>`。
契约（父会话定死，两半都照这个来）：入 `{"install_id": "<8~64 位字符串>"}`
→ 出 `{"device_id": "<install_id>", "token": "<服务端 HMAC 的十六进制>"}`。

### 这道签名到底防住了什么（⛔ 别把它说大了）
它让 `X-Device-Id` **不能随手乱填**：想冒充另一台设备，得先拿到服务端密钥算得出 HMAC。
**它挡不住**：① 一个愿意读接口的脚本（自己来这个端点领一份签名就行，这里只有来源 IP 限流）；
② 改机 / 清数据重装（那会生成一个全新的 install_id，从后端看就是一台新设备）。
所以设备侧那几条上限都是"**提高成本**"，不是"不可绕过"的证明 —— 真正挡批量刷号的是
注册那两条（同一台设备 24 小时最多开 1 个新号 + 注册专用的来源 IP 限流）。

### 为什么这个端点调 `reject_plaintext_credentials`
它是**发凭据**的端点（与登录/注册同级：明文通道上谁都能截走一份别人的设备签名，
之后照着这台设备的名义去消耗它的额度）。发布包那边 `cleartextTrafficPermitted="false"`
（`res/xml/network_security_config.xml`）、地址本来就是 `https://8.145.40.22`，
所以这道拦不会挡住任何真实客户端。

### 为什么没有 token 也不怕被刷
两道：① 这一段只是 HMAC 计算，不落库、不建号（所以它不是"公开写端点"，没有可被刷出来的数据）；
② 仍然按来源 IP 记次数（`login_guard.device_registration_block_reason`，与登录/注册的计数键
**分开**，⛔ 不共用桶 —— 共用的话刷设备端点能把正常用户锁在登录门外）。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.core.transport import reject_plaintext_credentials
from app.schemas.device import DeviceRegisterIn, DeviceRegisterOut
from app.services import login_guard
from app.services.device_service import device_token, normalize_install_id

router = APIRouter(prefix="/devices", tags=["devices"])


def _client_ip(request: Request) -> str | None:
    """来源 IP（与 `api/v1/auth.py` 同一口径；nginx 那层才是真的客户端地址）。"""
    return getattr(getattr(request, "client", None), "host", None)


@router.post("/register", response_model=DeviceRegisterOut)
def register_device(body: DeviceRegisterIn, request: Request) -> DeviceRegisterOut:
    """用 install_id 换一份设备签名。**公开端点**：不需要 token，也不建任何数据。"""
    reject_plaintext_credentials(request)
    ip = _client_ip(request)
    reason = login_guard.device_registration_block_reason(ip)
    if reason:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=reason)
    install_id = normalize_install_id(body.install_id)
    if install_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="设备标识格式不对（8~64 位字母、数字、连字符或下划线），请更新 App 后重试。",
        )
    login_guard.note_device_registration(ip)
    return DeviceRegisterOut(device_id=install_id, token=device_token(install_id))
