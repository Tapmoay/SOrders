from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError
from sqlalchemy.orm import Session

from app.core.rbac import Permission, role_has_permission, user_role_key
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
    except (JWTError, ValueError, TypeError):
        raise credentials_exc from None

    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise credentials_exc

    # 权限一律以数据库当前角色为准。JWT 内 role 仅作兼容/展示；若与 DB 不一致（如派单员修改了用户角色），仍允许访问，
    # 避免刷新后 401；冒用 sub 需有效签名，无法用伪造 role 提权（各接口以 user ORM 判权）。
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

def parse_date_range(date_from: str | None, date_to: str | None):
    # 通用日期范围解析（订单/账本/库存流水等列表复用）：YYYY-MM-DD 起止，含当天。
    # 返回 (datetime | None, datetime | None)；非法格式抛 400。
    from datetime import date, datetime, time
    from fastapi import HTTPException
    df = dt = None
    if date_from:
        try:
            df = datetime.combine(date.fromisoformat(date_from), time.min)
        except ValueError:
            raise HTTPException(status_code=400, detail='date_from 格式须为 YYYY-MM-DD')
    if date_to:
        try:
            dt = datetime.combine(date.fromisoformat(date_to), time.max)
        except ValueError:
            raise HTTPException(status_code=400, detail='date_to 格式须为 YYYY-MM-DD')
    if df and dt and df > dt:
        raise HTTPException(status_code=400, detail='开始日期不能晚于结束日期')
    return df, dt