from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError
from sqlalchemy.orm import Session

from app.core.rbac import Permission, normalize_role_key, role_has_permission, user_role_key
from app.core.security import decode_token
from app.database import get_db
from app.models import User
from app.models.enums import UserRole

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token")


def get_current_user(
    db: Annotated[Session, Depends(get_db)],
    token: Annotated[str, Depends(oauth2_scheme)],
) -> User:
    credentials_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="登录已失效或凭证无效，请重新登录",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_token(token)
        sub = payload.get("sub")
        if sub is None:
            raise credentials_exc
        user_id = int(sub)
        token_role = payload.get("role")
    except (JWTError, ValueError, TypeError):
        raise credentials_exc from None

    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise credentials_exc

    db_role_key = user_role_key(user)
    if token_role is not None and normalize_role_key(str(token_role)) != db_role_key:
        raise credentials_exc
    return user


def require_roles(*roles: UserRole):
    def _inner(user: Annotated[User, Depends(get_current_user)]) -> User:
        uk = user_role_key(user)
        allowed = {r.value for r in roles}
        if uk not in allowed:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="当前角色无权执行此操作")
        return user

    return _inner


def require_permission(permission: Permission):
    def _inner(user: Annotated[User, Depends(get_current_user)]) -> User:
        if not role_has_permission(user_role_key(user), permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="无操作权限（请确认当前账号角色与权限；可尝试退出后重新登录）",
            )
        return user

    return _inner


CurrentUser = Annotated[User, Depends(get_current_user)]
