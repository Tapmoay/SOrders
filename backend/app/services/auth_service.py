import secrets
from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.security import create_access_token, hash_password, verify_password
from app.models import User
from app.models.enums import UserRole
from app.schemas.auth import RegisterRequest
from app.services.sms_code import verify_and_consume


def authenticate_user(db: Session, login_id: str, password: str) -> User | None:
    lid = login_id.strip()
    user = db.scalars(
        select(User).where(or_(User.username == lid, User.phone == lid))
    ).first()
    if user is None or not user.is_active or not verify_password(password, user.password_hash):
        return None
    return user


def create_user(db: Session, body: RegisterRequest) -> User:
    ok, err = verify_and_consume(body.phone, body.verification_code)
    if not ok:
        raise ValueError(err or "验证码校验失败")
    if db.scalars(select(User).where(User.username == body.username)).first():
        raise ValueError("用户名已被注册")
    if db.scalars(select(User).where(User.phone == body.phone)).first():
        raise ValueError("手机号已被注册")
    user = User(
        username=body.username,
        phone=body.phone,
        password_hash=hash_password(body.password),
        full_name="",
        role=UserRole.SHIPPER,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def issue_token(user: User) -> str:
    role = user.role.value if isinstance(user.role, UserRole) else str(user.role)
    return create_access_token(str(user.id), {"role": role})


def new_order_no() -> str:
    return f"SO{datetime.utcnow():%Y%m%d}{secrets.randbelow(10**6):06d}"
