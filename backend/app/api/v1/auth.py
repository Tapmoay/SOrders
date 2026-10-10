"""登录、登出与自助注册。

## 这个文件放什么
**进门**的端点（拿凭据进门：登录、登出、注册）在这里；**开门**的端点（改别人的账号、
改权限、批量建号）一律不在这里，走 `api/v1/users.py`（要 token + 权限点）。

## "注册"这一条路的两段历史（改这里之前必须先读完）
- **2026-09-18 删除**：`POST /auth/register` 与 `POST /auth/sms/send` **整体删除**，理由是
  真的能被打：App 侧注册入口在 v3.40 就拆掉了，接口却一直公开着 —— 一个**没人用的公开写接口**
  就是纯攻击面；而且当时注册要过短信验证码，本地 `sms_reveal_code=true` 时验证码**明文回显**，
  等于任何人都能自助开一个货主号。
- **2026-10-11 拿回来（FEAT-0017，用户要求）**：用户要在 App 登录页自助注册。上面那两条理由
  现在都不成立了：① App 侧**这次连注册入口一起加**（`ui/login/LoginScreen.kt` 底部文字链），
  不再"没人用"；② 注册**不要验证码**（短信那条路仍然不做），所以没有"明文回显"这个洞。
  ⛔ 代价要看清：这个端点**公开、无需 token**，且**没有任何身份核验**（手机号不必真实拥有）。
  因此端点里必须同时做到三件事：**明文通道拒收**、**来源 IP 次数限流**、**账号属性全部服务端写死**
  （请求体带 `role`/`is_member`/`is_active` 一律无效）。三条各有单测钉着。

## 账号创建的两条路径（都不许绕过手机号规则与审计）
派单员 `POST /api/v1/users`（任意角色）＋ 自助注册 `POST /auth/register`（**只能是货主**）。
两条都写 `OperationAction.USER_CREATE`。
"""

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.user_categories import ensure_user_category
from app.core.business_time import utc_now_naive
from app.core.security import hash_password
from app.core.transport import reject_plaintext_credentials
from app.database import get_db
from app.deps import CurrentUser
from app.models import User
from app.models.enums import OperationAction, UserRole
from app.schemas.auth import LoginRequest, RegisterRequest, Token
from app.services import login_guard
from app.services.auth_service import authenticate_user, is_test_account, revoke_tokens_and_sockets
from app.services.operation_log_service import write_log
from app.services.token_response import build_token_response

router = APIRouter(prefix="/auth", tags=["auth"])


def _client_ip(request: Request) -> str | None:
    """来源 IP。生产经 nginx 反代（`UVICORN_PROXY_HEADERS` 已开），`request.client` 是真实客户端。"""
    return getattr(getattr(request, "client", None), "host", None)


def _login(
    db: Session,
    login_id: str,
    password: str,
    ip: str | None,
    request: Request,
    background_tasks: BackgroundTasks,
) -> Token:
    """两条登录端点共用：**拒明文** → 限流 → 校验 → 记账（成功清计数、失败累加）→ 撤销旧会话。

    ⚠️ 第一道是 2026-09-19 外部完整检查 C-1 的修法第 5 步（见 `core/transport.py`）：
    携带凭据的端点**不收明文**。放在最前面是为了在任何 DB/限流逻辑之前就把它挡掉。

    ⚠️ 最后那道**撤销旧会话**（2026-09-22 用户要求：「防止两部手机同时登一个账号……
    只要是真实的账号的话，他**不能在两部手机上同时登录**」）：
    非测试账号登录成功时，先把该账号**已经发出去的令牌全部作废、并把它的长连接断开**，
    再签发这一次的令牌 —— 也就是**后来者顶掉先登的**（用户拍板选的这一种）。
    被顶掉那台的表现：下一次请求 401 → 客户端 `clearSession()` → 跳登录页；
    而且它**收不到推送了**（长连接同一入口断掉，见 `revoke_tokens_and_sockets` 的说明），
    不会出现"已经下线还在收单"。

    ⛔ **顺序**：`revoke` → `commit` → `build_token_response`。
    反过来的话，新令牌带着一个**库里还没生效**的 `tv`，`deps.get_current_user` 会把它也判成失效 ——
    用户刚登录完就"登录已失效"，而日志里什么异常都没有。
    """
    reject_plaintext_credentials(request)
    reason = login_guard.block_reason(login_id, ip)
    if reason:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=reason)
    user = authenticate_user(db, login_id, password)
    if user is None:
        login_guard.note_failure(login_id, ip)
        # 不区分"用户不存在"与"密码错误"（避免账号枚举），也不提示还能试几次
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")
    login_guard.note_success(login_id)
    # ⚠️ 2026-10-03（BUG-0006）：记下「这个账号最后一次登录成功是什么时候」。
    #    走查原话：被顶号之后「事后在库里查不到谁顶了谁」—— 有了它，加上撤销原因/时间两列，
    #    一次顶号在库里留得下完整痕迹（谁在什么时候登进来、把谁顶掉了）。
    #    ⛔ 写在 commit **之前**（下面那条撤销路径同一个事务）；并且**不碰**
    #      `session_revoked_reason`：被顶掉那台还要靠这次撤销记下的原因告诉用户发生了什么，
    #      在这里清掉就等于把要说的话吃掉。
    user.last_login_at = utc_now_naive()

    if not is_test_account(user.phone):
        revoke_tokens_and_sockets(db, user, background_tasks, "账号在另一台设备登录")
        db.commit()

    return build_token_response(user)


@router.post("/logout")
def logout(
    background_tasks: BackgroundTasks,
    current: CurrentUser,
    db: Session = Depends(get_db),
) -> dict:
    """登出：**服务端**把这个账号已发出的令牌全部作废（`token_version` +1）+ 断开长连接。

    ⚠️ 为什么需要它（2026-09-19 审计）：客户端原来的"登出"只删掉本机 DataStore 里的令牌，
    服务端一个字都不知道 —— 被复制走的令牌照样能用满 24 小时。手机丢了、在别人电脑上登过，
    都没有止损手段。现在登出＝真的作废（代价是同一账号的其它设备也要重新登录，
    这是"登出"应有的语义）。

    ⚠️ 2026-09-19 外部完整检查 C-3：光作废令牌**不够** —— `tv` 只在 socket 握手时校验一次，
    已经建起来的长连接不会因此断开，照样继续收推送。所以走
    `revoke_tokens_and_sockets`（作废 + 断开是同一个入口，不可能只做一半）。
    """
    revoke_tokens_and_sockets(db, current, background_tasks, "登出")
    db.commit()
    return {"ok": True, "note": "本账号已发出的登录令牌已全部作废，请重新登录"}


@router.post("/login", response_model=Token)
def login_json(
    body: LoginRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> Token:
    return _login(db, (body.phone or "").strip(), body.password, _client_ip(request), request, background_tasks)


@router.post("/token", response_model=Token)
def login_form(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> Token:
    """OAuth2 兼容：username 字段填手机号。"""
    return _login(db, (form_data.username or "").strip(), form_data.password, _client_ip(request), request, background_tasks)


@router.post("/register", response_model=Token)
def register(
    body: RegisterRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> Token:
    """自助注册：手机号 + 密码 → 直接返回 token（注册完就进 App，不用再登一次）。

    ⚠️ 公开端点（**没有** `Depends` 鉴权，所以也没有角色门槛可写在签名里；
    这是设计：注册的人本来就还没账号）。它的安全边界全部落在下面四道，动其中任何一道
    都要先看模块 docstring 里那段"两段历史"：

    1. **拒明文**（`reject_plaintext_credentials`）——与登录同一道：注册同样是凭据，
       明文通道上收密码等于把密码送出去。⚠️ 必须是**第一句**：在任何读库/写库之前。
    2. **来源 IP 次数限流**（`login_guard.registration_block_reason`）——挡住脚本批量刷号。
    3. **手机号形状**（`RegisterRequest.phone: MobilePhone`）——`core/phone.py` 的唯一一份规则；
       ⛔ 这里**不再 strip**：账号同时是登录名，登录按字符串精确匹配，静默接受带空格的账号
       等于造一个"建得出来、再也登不进去"的号。
    4. **属性服务端写死**——请求体即使带了 `role` / `is_member` / `vehicle_type` / `is_active`
       也进不来（schema 没声明这些字段；就算声明了，下面也不会读它）。
       ⛔ 这一条是提权防线，**别改成"从 body 取默认值"**：`role` 一旦可传，任何人都能自助开派单员。

    与登录不同，这里**不撤销旧会话**（`revoke_tokens_and_sockets`）：新账号不可能有旧会话。
    `is_test_account` 那类测试号豁免与本端点无关（新号是真实手机号形状，不受影响）。
    """
    reject_plaintext_credentials(request)
    ip = _client_ip(request)
    reason = login_guard.registration_block_reason(ip)
    if reason:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=reason)

    phone = body.phone
    # 文案与派单员建号那条**逐字一致**（api/v1/users.py:166-167）：用户看到的应是同一件事，
    # 不该因为"从哪个入口建的"而换一种说法。400 而不是 500，也不是 409。
    if db.scalars(select(User).where(User.phone == phone)).first() is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="该手机号已存在")

    username = phone
    # 手机号没被占，用户名仍可能被占：库里存在 username == 这个手机号 的老号
    # （历史上 username 与 phone 可以不同）。这种号让"用手机号登录"落到两条不同记录上，
    # 必须挡掉 —— 但**不能**泄露那条记录的其它信息，所以只说名字被占。
    if db.scalars(select(User).where(User.username == username)).first() is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="该用户名已存在")

    user = User(
        username=username,
        phone=phone,
        password_hash=hash_password(body.password),
        full_name=(body.full_name or "").strip()[:128],
        role=UserRole.SHIPPER,
        is_active=True,
        is_member=False,
        category="",
    )
    db.add(user)
    db.flush()
    ensure_user_category(db, user.category)

    # 留痕：复用既有的账号动作码 `USER_CREATE`（`models/enums.py:183`，⛔ 不新造码）。
    # `operator_id` 记的是**新账号自己**：自助注册没有别人在操作，"谁建的号"与"谁的号"是同一个。
    # ⛔ 绝不记密码，连哈希也不记；并如实标明这是自助注册（审计页能分清两条建号路径）。
    write_log(
        db,
        operator_id=user.id,
        order_id=None,
        action=OperationAction.USER_CREATE,
        change_payload={
            "user_id": user.id,
            "username": user.username,
            "phone": user.phone,
            "full_name": user.full_name,
            "role": user.role.value if isinstance(user.role, UserRole) else str(user.role),
            "source": "self_register",
        },
    )
    db.commit()
    db.refresh(user)

    # 计数写在**成功之后**（理由见 login_guard 模块 docstring：失败的尝试由 400/422 自己回）。
    login_guard.note_registration(ip)
    return build_token_response(user)
