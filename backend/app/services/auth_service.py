"""登录与令牌。

⚠️ `create_user`（自助注册）已于 2026-09-18 随 `POST /auth/register` 一起删除。
建账号的唯一入口是派单员 `POST /api/v1/users`（见 `api/v1/users.py::create_user`，
那里走 `schemas/user.py` 的校验与权限点）。
"""

import secrets
from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.security import create_access_token, verify_password
from app.models import User
from app.models.enums import UserRole


def authenticate_user(db: Session, login_id: str, password: str) -> User | None:
    lid = login_id.strip()
    user = db.scalars(
        select(User).where(or_(User.username == lid, User.phone == lid))
    ).first()
    if user is None or not user.is_active or not verify_password(password, user.password_hash):
        return None
    return user


def issue_token(user: User) -> str:
    role = user.role.value if isinstance(user.role, UserRole) else str(user.role)
    return create_access_token(str(user.id), {"role": role})


def new_order_no() -> str:
    return f"SO{datetime.utcnow():%Y%m%d}{secrets.randbelow(10**10):010d}"
