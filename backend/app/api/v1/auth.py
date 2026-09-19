"""登录与凭据。

⚠️ **这个文件里只许有"进门"的端点，不许有"开门"的端点。**
`POST /auth/register` 与 `POST /auth/sms/send` 已于 2026-09-18 按用户要求**整体删除**
（App 侧注册入口在 v3.40 就拆掉了，接口一直公开着；本地 `sms_reveal_code=true` 时
验证码还是明文回显的，等于任何人都能自助开一个货主账号）。
账号现在**只有一条创建路径**：派单员 `POST /api/v1/users`（要 token + 权限点）。
"""

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.core.transport import reject_plaintext_credentials
from app.database import get_db
from app.deps import CurrentUser
from app.schemas.auth import LoginRequest, Token
from app.services import login_guard
from app.services.auth_service import authenticate_user
from app.services.token_response import build_token_response

router = APIRouter(prefix="/auth", tags=["auth"])


def _client_ip(request: Request) -> str | None:
    """来源 IP。生产经 nginx 反代（`UVICORN_PROXY_HEADERS` 已开），`request.client` 是真实客户端。"""
    return getattr(getattr(request, "client", None), "host", None)


def _login(db: Session, login_id: str, password: str, ip: str | None, request: Request) -> Token:
    """两条登录端点共用：**拒明文** → 限流 → 校验 → 记账（成功清计数、失败累加）。

    ⚠️ 第一道是 2026-09-19 外部完整检查 C-1 的修法第 5 步（见 `core/transport.py`）：
    携带凭据的端点**不收明文**。放在最前面是为了在任何 DB/限流逻辑之前就把它挡掉。
    """
    reject_plaintext_credentials(request)
    reason = login_guard.block_reason(login_id, ip)
    if reason:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=reason)
    user = authenticate_user(db, login_id, password)
    if user is None:
        login_guard.note_failure(login_id, ip)
        # 不区分"用户不存在"与"密码错误"（避免账号枚举），也不提示还能试几次
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")
    login_guard.note_success(login_id)
    return build_token_response(user)


@router.post("/logout")
def logout(
    background_tasks: BackgroundTasks,
    current: CurrentUser,
    db: Session = Depends(get_db),
) -> dict:
    """登出：**服务端**把这个账号已发出的令牌全部作废（`token_version` +1）+ 断开长连接。

    ⚠️ 为什么需要它（2026-09-19 审计）：客户端原来的"登出"只删掉本机 DataStore 里的令牌，
    服务端一个字都不知道 —— 被复制走的令牌照样能用满 24 小时。手机丢了、在别人电脑上登过，
    都没有止损手段。现在登出＝真的作废（代价是同一账号的其它设备也要重新登录，
    这是"登出"应有的语义）。

    ⚠️ 2026-09-19 外部完整检查 C-3：光作废令牌**不够** —— `tv` 只在 socket 握手时校验一次，
    已经建起来的长连接不会因此断开，照样继续收推送。所以走
    `revoke_tokens_and_sockets`（作废 + 断开是同一个入口，不可能只做一半）。
    """
    from app.services.auth_service import revoke_tokens_and_sockets

    revoke_tokens_and_sockets(db, current, background_tasks, "登出")
    db.commit()
    return {"ok": True, "note": "本账号已发出的登录令牌已全部作废，请重新登录"}


@router.post("/login", response_model=Token)
def login_json(body: LoginRequest, request: Request, db: Session = Depends(get_db)) -> Token:
    return _login(db, (body.phone or "").strip(), body.password, _client_ip(request), request)


@router.post("/token", response_model=Token)
def login_form(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    request: Request,
    db: Session = Depends(get_db),
) -> Token:
    """OAuth2 兼容：username 字段填手机号。"""
    return _login(db, (form_data.username or "").strip(), form_data.password, _client_ip(request), request)
