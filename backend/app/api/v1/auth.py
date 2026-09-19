"""登录与凭据。

⚠️ **这个文件里只许有"进门"的端点，不许有"开门"的端点。**
`POST /auth/register` 与 `POST /auth/sms/send` 已于 2026-09-18 按用户要求**整体删除**
（App 侧注册入口在 v3.40 就拆掉了，接口一直公开着；本地 `sms_reveal_code=true` 时
验证码还是明文回显的，等于任何人都能自助开一个货主账号）。
账号现在**只有一条创建路径**：派单员 `POST /api/v1/users`（要 token + 权限点）。
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.auth import LoginRequest, Token
from app.services.auth_service import authenticate_user
from app.services.token_response import build_token_response

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=Token)
def login_json(body: LoginRequest, db: Session = Depends(get_db)) -> Token:
    user = authenticate_user(db, body.phone, body.password)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")
    return build_token_response(user)


@router.post("/token", response_model=Token)
def login_form(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: Session = Depends(get_db),
) -> Token:
    """OAuth2 兼容：username 字段填手机号。"""
    user = authenticate_user(db, form_data.username, form_data.password)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")
    return build_token_response(user)
