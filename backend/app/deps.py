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

    # ⚠️ **服务端撤销**（2026-09-19 审计）：令牌里的 `tv` 必须等于库里当前的 `token_version`。
    #    改密码 / 停用 / 删除 / 主动登出都会把库里的值 +1，于是那些旧令牌立刻失效 ——
    #    在这之前"改密码"对已经泄漏的令牌毫无作用，只能等满 24 小时。
    #    老令牌没有 `tv` claim → 按 0 处理；老库补列时默认也是 0 → **升级不会把所有人踢下线**。
    if int(payload.get("tv", 0) or 0) != int(getattr(user, "token_version", 0) or 0):
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


def require_any_permission(*permissions: Permission):
    """**任一**权限点即可（读侧专用）。

    ⚠️ 为什么读侧要"任一"：同一个端点常常同时服务多角色 —— GET /orders 对货主是"只看自己的"、
    对司机是"只看派给自己的"、对派单员是"看全部"。单一权限点表达不了这种**行级规则**。
    所以两件事**都在**、各管一段：
      · 权限点（这里）管"这一类角色能不能进这道门"——它现在**真的在执行**（以前只是矩阵上的声明）；
      · 端点体内的 user_role_key 过滤管"进来能看哪几行"。
    ⛔ 别把行级过滤删掉换成权限点：那是把"货主只看自己的"降级成"货主能看全部"。
    """
    def _inner(user: Annotated[User, Depends(get_current_user)]) -> User:
        uk = user_role_key(user)
        if not any(role_has_permission(uk, p) for p in permissions):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="无读取权限（请确认当前账号角色与权限；可尝试退出后重新登录）",
            )
        return user

    return _inner

CurrentUser = Annotated[User, Depends(get_current_user)]

def parse_date_range(date_from: str | None, date_to: str | None):
    # 通用日期范围解析（订单/账本/库存流水等列表复用）：YYYY-MM-DD 起止，含当天。
    # 返回 (datetime | None, datetime | None)；非法格式抛 400。
    #
    # ⛔ **它不做任何时区换算**：返回的是"当地日的零点 / 当日末刻"（naive）。而库里的时间列
    #    存的是 **UTC naive**（`core/business_time.py`）—— 所以**凡是拿它去比一个"时间戳列"
    #    （`created_at` / `delivered_at` / …）的调用方，都必须自己过 `business_range_utc(...)`**；
    #    只有比"日期列"（`order_date` / `entry_date`）才可以直接用。漏掉换算不会报错，
    #    而是**静默差 8 小时**：「查 9-21」实际取到的是北京 9-21 08:00 ~ 9-22 08:00
    #    （当天头 8 小时查不到、次日头 8 小时多进来），与审计 R12-M11 同族。
    #
    # 📋 **调用点清单（2026-09-21 逐个核过；改这里请一并复核）**
    #    ① `orders.py::_apply_delivered_window`（`delivered_*` → `orders.delivered_at`）✅ 换算
    #    ② `orders.py::list_orders` 的 `stmt` 路径（派单员+搜索词，`date_*` → `orders.created_at`）✅ 换算
    #    ③ `orders.py::list_orders` 的 `q` 路径（其余角色，`date_*` → `orders.created_at`）✅ 换算
    #    ④ `inventory.py::list_movements`（`date_*` → `inventory_movements.created_at`）✅ 换算
    #    ⑤ `shipper_ledger.py::list_settlements`（`delivered_*` → `orders.delivered_at`）✅ 换算
    #    ②③④ 是 2026-09-21 补的换算（原来三处都在直接比 UTC 列），
    #    钉住它们的判据在 `backend/tests/test_date_window_business_day.py`。
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