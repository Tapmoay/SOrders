"""登录与令牌。

⚠️ `create_user`（自助注册）已于 2026-09-18 随 `POST /auth/register` 一起删除。
建账号的唯一入口是派单员 `POST /api/v1/users`（见 `api/v1/users.py::create_user`，
那里走 `schemas/user.py` 的校验与权限点）。
"""

import secrets
from datetime import datetime

from fastapi import BackgroundTasks
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.business_time import business_today
from app.core.security import create_access_token, verify_password
from app.core.socket_io import revoke_user_sockets
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


#: **测试账号的号段**：`13800000001`~`13800000009`（＝我们在模拟器上一直用的这批号的形式）。
#: 用户 2026-09-22 定的原话：「**也就是现在我们用的账号的形式全都自动豁免**。主要改变的就是**后面的尾号最多 9 个**」。
#:
#: ⚠️ 为什么要有一份**豁免名单**（而不是"所有账号一律单设备"）：
#: 真机验收/多端联调**必须在两台设备上同时登同一个号**（派单端要两台对比、
#: 或者一台派单员一台司机看同一条链路），一律限制等于把开发流程自己掐死。
#: 真实账号（比如派单员 `15070334563`、以及库里那些司机/货主的真号）则一律受限。
#:
#: ⚠️ **和 `settings.ai_test_phone_prefix` 是两件事，别合并**（那个的消费点是
#: `api/v1/system.py`，管的是"谁能用服务端默认 AI key"，**默认空＝整体关闭**，要 `backend/.env` 打开）：
#: 把它拿来当豁免判据的话，「打开 AI 默认 key」这个动作会**顺手放宽登录限制**，
#: 而这两件事没有任何关系 —— 那种耦合在界面上完全看不出来。
#: 这里的号段是**写死的约定**（用户给的就是固定的号形式），不随环境变化。
#:
#: ⚠️ 判据只有这一处：登录时（`api/v1/auth.py::_login`）与红线都读它，
#: 不许在别处再写一遍前缀判断 —— 各写一份的后果是"某个端把真实账号也放行了"，
#: 而这在界面上完全看不出来（两台手机都能用，谁也不报错）。
TEST_ACCOUNT_PHONE_PREFIX = "1380000000"
TEST_ACCOUNT_TAIL_MAX = 9


def is_test_account(phone: str | None) -> bool:
    """这个手机号是不是**豁免单设备限制**的测试账号。

    形式：`1380000000` + **一位**尾号（`1`~`9`）＝ 共 11 位。
    ⛔ 不接受 `13800000000`（尾号 0 不在"最多 9 个"里）也不接受 `13800000010`（尾号两位数）——
    判据故意写死成"前缀 + 一位 1~9"，比 `startswith` 严格：
    后者会把 `13800000001234` 这种也放行，等于悄悄给真实账号开了后门。
    """
    p = (phone or "").strip()
    if len(p) != len(TEST_ACCOUNT_PHONE_PREFIX) + 1 or not p.startswith(TEST_ACCOUNT_PHONE_PREFIX):
        return False
    tail = p[len(TEST_ACCOUNT_PHONE_PREFIX):]
    return tail.isdigit() and 1 <= int(tail) <= TEST_ACCOUNT_TAIL_MAX


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


def revoke_tokens_and_sockets(
    db: Session, user: User, background: BackgroundTasks, reason: str
) -> None:
    """撤销这个账号的会话：**令牌作废 + 长连接断开**（登出 / 改密码 / 停用都走这一处）。

    ⚠️ 为什么不许只调 `bump_token_version`（2026-09-19 外部完整检查 C-3）：
    令牌版本只在 **socket 握手**时校验一次（`socket_io.connect`），而 `disconnect` 是空实现、
    全后端只有 `connect`/`disconnect` 两个 socket 事件。于是"登出/停用/改密"之后：
    旧令牌打 HTTP 全 401，**但那条已经建起来的长连接继续收推送**（站内信正文、单号、账本）。
    丢手机、共用手机的场景里，这正是"登出止损"最要紧的地方 —— 而它一行都没生效。

    把两件事绑在一个函数里，是为了让"作废令牌"这个动作**不可能**漏掉断开连接：
    三个撤销点（`/auth/logout`、改密码、停用）都调这一个入口。

    `background` 用来把断开动作排到响应之后（要 await socket 推送，不能在同步端点里做）。
    """
    bump_token_version(db, user)
    background.add_task(revoke_user_sockets, user.id, reason)


def new_order_no() -> str:
    """单号：`SO` + **业务当地日** + 10 位随机数。

    ⛔ 这里原来是 `datetime.utcnow()`（2026-09-19 审计，R14-9 同族）：东八区当地
    00:00~08:00 下的单，单号上的日期是**前一天**。单号是司机/货主口头对单用的标识，
    "单号上的日期和单据日期不一致"会直接变成对账时的困惑；同一时刻的报表、账单、
    单据日期却都按业务当地日 → 单号必须同源（`business_time.business_today`）。
    """
    return f"SO{business_today():%Y%m%d}{secrets.randbelow(10**10):010d}"
