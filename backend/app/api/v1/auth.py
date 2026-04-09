from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.schemas.auth import LoginRequest, RegisterRequest, SendSmsRequest, Token
from app.services.auth_service import authenticate_user, create_user
from app.services.sms_code import send_code
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


@router.post("/sms/send")
def send_register_sms(body: SendSmsRequest) -> dict:
    """发送注册短信验证码（开发环境内存存储；生产需接入短信网关）。"""
    code, err = send_code(body.phone)
    if err:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=err)
    settings = get_settings()
    out: dict = {"ok": True, "expires_in": 300}
    if settings.sms_reveal_code:
        out["code"] = code
    return out


@router.post("/register", response_model=Token)
def register(body: RegisterRequest, db: Session = Depends(get_db)) -> Token:
    try:
        user = create_user(db, body)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    return build_token_response(user)
