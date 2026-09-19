"""登录与令牌。

⚠️ `create_user`（自助注册）已于 2026-09-18 随 `POST /auth/register` 一起删除。
建账号的唯一入口是派单员 `POST /api/v1/users`（见 `api/v1/users.py::create_user`，
那里走 `schemas/user.py` 的校验与权限点）。
"""

import secrets
from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.business_time import business_today
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
    # `tv` = 签发时的 token_version。服务端撤销就靠它：改密码/停用/登出时库里 +1，
    # 旧令牌的 tv 就对不上了（见 `deps.get_current_user`）。
    return create_access_token(
        str(user.id), {"role": role, "tv": int(getattr(user, "token_version", 0) or 0)}
    )


def bump_token_version(db: Session, user: User) -> None:
    """让这个账号**已经发出去的所有令牌**立刻失效（改密码 / 停用 / 删除 / 登出）。

    ⚠️ 必须在**同一个事务**里跟着那次改动一起提交：分两次提交会出现
    "密码已经改了、旧令牌还能用"的中间窗口。
    """
    user.token_version = int(getattr(user, "token_version", 0) or 0) + 1
    db.flush()


def new_order_no() -> str:
    """单号：`SO` + **业务当地日** + 10 位随机数。

    ⛔ 这里原来是 `datetime.utcnow()`（2026-09-19 审计，R14-9 同族）：东八区当地
    00:00~08:00 下的单，单号上的日期是**前一天**。单号是司机/货主口头对单用的标识，
    "单号上的日期和单据日期不一致"会直接变成对账时的困惑；同一时刻的报表、账单、
    单据日期却都按业务当地日 → 单号必须同源（`business_time.business_today`）。
    """
    return f"SO{business_today():%Y%m%d}{secrets.randbelow(10**10):010d}"
