from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from jose import ExpiredSignatureError, JWTError
from sqlalchemy.orm import Session

from app.core.business_time import local_stamp
from app.core.rbac import Permission, role_has_permission, user_role_key
from app.core.security import decode_token
from app.database import get_db
from app.models import User
from app.models.enums import UserRole

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token")


def _unauthorized(detail: str) -> HTTPException:
    """统一的 401 形状。`WWW-Authenticate: Bearer` 一直带着 —— 分支再多也别漏掉它。"""
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _session_ended_detail(user: User) -> str:
    """令牌被**服务端作废**之后，把当时记下的原因说给用户（2026-10-03 E2E 走查 BUG-0006）。

    ## 为什么必须说原因
    作废的原因有四种：被别的设备顶号、主动登出、改了密码、账号被停用/删除。
    在这之前它们**在用户眼里是同一句话**（「登录已失效，请重新登录」），于是：
    被停用的司机反复重登、被顶号的货主以为 App 坏了、改了密码的人以为网络有问题。
    而服务端一直知道原因（`revoke_tokens_and_sockets` 的入参），只是没留下来。

    ## 为什么必须用 `session_revoked_version` 对账，而不是「有原因就显示」
    原因是一个**状态**，上一次撤销离现在可能已经隔了好几轮登录：用户换台手机重新登录、
    又被顶掉，库里躺着的可能还是最早那句「登出」。不过账的话，第二台设备失效时会弹出一句
    关于「登出」的话，而它其实是被第三台顶掉的 —— 那比不说原因更坏（说得斩钉截铁却是错的）。
    对账规则：`session_revoked_version == token_version` ⟺ 这条原因描述的正是**最近这一次**
    撤销（每次撤销都把版本号 +1，两者相等才说明没有更新的撤销盖在它上面）。
    """
    reason = (getattr(user, "session_revoked_reason", "") or "").strip()
    current = int(getattr(user, "token_version", 0) or 0)
    recorded = int(getattr(user, "session_revoked_version", 0) or 0)
    if not reason or recorded != current:
        return "登录已失效，请重新登录"
    revoked_at = getattr(user, "session_revoked_at", None)
    if revoked_at is None:
        return f"登录已结束：{reason}"
    return f"登录已结束：{reason}（{local_stamp(revoked_at)}）"


def get_current_user(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    token: Annotated[str, Depends(oauth2_scheme)],
) -> User:
    credentials_exc = _unauthorized("登录已失效或凭证无效，请重新登录")
    try:
        payload = decode_token(token)
        sub = payload.get("sub")
        if sub is None:
            raise credentials_exc
        user_id = int(sub)
    except ExpiredSignatureError:
        # 令牌过期（24 小时）—— 与「被顶掉 / 被停用」是两回事：这个重新登录就好，
        # 也只有它是时间到了自然发生、用户不该怀疑自己账号出了问题的。
        raise _unauthorized("登录已过期（令牌 24 小时有效），请重新登录") from None
    except (JWTError, ValueError, TypeError):
        raise credentials_exc from None

    user = db.get(User, user_id)
    if user is None:
        # 账号被删除（或令牌的 sub 指向一个已经不存在的行）。
        # ⛔ 不许退回成通用句：「登录已失效」会让人反复重登，而真实原因是这个账号已经没了。
        raise _unauthorized("这个账号不存在或已被删除，请联系派单员")
    if not user.is_active:
        raise _unauthorized("这个账号已被停用，请联系派单员")

    # ⚠️ **服务端撤销**（2026-09-19 审计）：令牌里的 `tv` 必须等于库里当前的 `token_version`。
    #    改密码 / 停用 / 删除 / 主动登出都会把库里的值 +1，于是那些旧令牌立刻失效 ——
    #    在这之前"改密码"对已经泄漏的令牌毫无作用，只能等满 24 小时。
    #    老令牌没有 `tv` claim → 按 0 处理；老库补列时默认也是 0 → **升级不会把所有人踢下线**。
    if int(payload.get("tv", 0) or 0) != int(getattr(user, "token_version", 0) or 0):
        # 版本对不上＝这个令牌已经被服务端作废。两种情形分开说：
        #   ① 撤销时记下的原因还作数（session_revoked_version == 当前版本）→ 原话告诉用户；
        #   ② 记不上（老库 / 从没撤销过 / 又被下一次登录推了一格）→ 只能说「已失效」。
        raise _unauthorized(_session_ended_detail(user))

    # 权限一律以数据库当前角色为准。JWT 内 role 仅作兼容/展示；若与 DB 不一致（如派单员修改了用户角色），仍允许访问，
    # 避免刷新后 401；冒用 sub 需有效签名，无法用伪造 role 提权（各接口以 user ORM 判权）。

    # 2026-10-08 CHG-0082：把"这次请求是谁"捎给**中间件**（`core/ai_operation.py` 的 AI 操作流水）。
    # ⚠️ `Request.state` 写进去的就是 `scope["state"]`，而中间件收到的是同一个 dict ——
    #    所以它在 `await self.app(...)` 返回之后能读到这里的值。这是中间件拿得到用户 id 的**唯一**路子
    #    （它比鉴权早、也比鉴权低一层，读不到 ORM 对象）。
    # ⛔ 只是"记下来给审计用"，**不是**授权：权限仍然只由上面这几行决定。
    request.state.user_id = user.id
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

#: **仅派单员**能进的端点（报告 §9「先把授权机制统一」）。
#:
#: 它替代的是散在端点**函数体内**的那种硬门槛：
#:
#:     if user_role_key(current) != UserRole.DISPATCHER.value:
#:         raise HTTPException(status_code=403, detail="仅派单员可操作")
#:
#: ⛔ 为什么必须有一个**具名别名**，而不是每个端点各写一遍 `Depends(require_roles(...))`：
#:   ① 写在签名上，**端点索引的授权列才看得见** —— 体内判断生成器只能标成「体内」，
#:      而那要求读的人恰好想到去翻那一列（本项目吃过「文档说没权限了、接口照样能读」的亏）；
#:   ② 「谁算派单员」只有这一处说法，改的时候不会漏；
#:   ③ 403 的文案统一成一句人话（原来那 36 处各编各的：「仅派单员可查看」/「仅派单员可操作」/…）。
#:
#: 行为与体内那句**完全一致**：非派单员一律 403（`require_roles` 比的就是 `user_role_key`）。
DispatcherUser = Annotated[User, Depends(require_roles(UserRole.DISPATCHER))]

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