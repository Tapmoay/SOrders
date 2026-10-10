"""账号 ↔ 设备绑定与风控（FEAT-0018，2026-10-11 用户要求）。

## 用户口径（逐字要点）
- 「一个账号大概只能绑定一个手机/一个设备（mac/设备序列号，唯一）。只不过……也不说完全只能绑定
  3 个吧，如果超过了 3 个的话，它后面想接着绑定其他手机就不能瞬间，它是有时间限制的……大概
  它如果要再次再增加一个的话，就要过 **6 个月**了」；
- 「我们的一个设备（一个唯一的设备地址）不能同时间、短时间内绑定多个账号 —— 防止有人利用这个
  漏洞批量注册一堆账号来攻击服务器」；
- 「**测试账号除外**（内部账号没有这些限制，随便登录）」；
- 同日口径更新：「一台设备也就是一部手机，它可以绑多部账号，**至少是可以绑 5 个**」；
- 追加拍板：「6 个月冷却**保留**，但**派单员在账号管理里可以手动解冻**（就在编辑当中）——
  司机换手机、手机摔坏了，联系派单员解冻即可」。

## 闸门一览（判定都在这个模块里，端点只负责把 detail 翻成状态码）
| 闸 | 阈值 | 超了回什么 |
|---|---|---|
| 账号 ↔ 设备数 | `MAX_DEVICES_PER_ACCOUNT` 台**有效**绑定 | 403 +「最早那台要到 YYYY-MM-DD 才能替换」（登录） |
| 冷却期 | 最旧那台 `bound_at` + `BIND_TTL_MONTHS` 个月**之后**才可被顶掉 | 同上（把最早可替换日期说清楚） |
| 设备 ↔ 账号数（硬上限） | `MAX_ACCOUNTS_PER_DEVICE` 个不同账号**有效**绑定 | 403 + 中文 |
| 设备 ↔ 账号数（速率） | 同一设备 24 小时内最多**新增** `MAX_NEW_ACCOUNTS_PER_DEVICE_24H` 个账号绑定 | 403 + 中文 |
| 注册（更紧的一条） | 同一设备 24 小时内最多开 `MAX_NEW_ACCOUNTS_PER_DEVICE_REGISTER_24H` 个**新号** | 429 + 中文 |

"有效绑定" = `account_devices.unbound_at IS NULL`。**解绑不删行**，所以派单员解冻之后
那一行还在（`active: false`），"这台设备什么时候绑过"永远查得到。

## 豁免
`is_test_account(user.phone)` 为真 ⇒ 上面的闸**全跳过，连行都不记**（内部测试号不参与风控，
也不该在派单员的设备列表里占位置）。判据只有 `app/services/auth_service.py::is_test_account`
一处，⛔ 这里不重写前缀判断（那条注释写明了为什么）。

## 诚实的边界（⛔ 写给下一个读这段的人，别把这些上限说成"防住了"）
1. `POST /api/v1/devices/register` 是**公开**端点，服务端对任何形状合法的 install_id 都发签名。
   所以 `X-Device-Id` 上的签名只挡**随手伪造**（改个头就冒充另一台设备），
   **挡不住**一个愿意读接口的脚本 —— 它自己来领一份签名就行（那一端另有来源 IP 限流提高成本）。
2. 它更挡不住**改机 / 清数据重装**：那会生成一个全新的 install_id，从后端看就是一台新设备。
3. 所以本模块所有上限都是**提高成本**（让"批量刷号"从一条 curl 变成一件要花时间的事），
   不是"不可绕过"的证明。真正挡批量刷号的是注册那两条（同设备 24h ≤1 个新号 + 注册 IP 限流）。
"""

from __future__ import annotations

import hashlib
import hmac
import re
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.business_time import utc_now_naive
from app.core.security import get_jwt_secret
from app.models.account_device import AccountDevice
from app.models.user import User
from app.services.auth_service import is_test_account
# ⛔ 月份加法**复用仓库里唯一那一份**（`vehicle_depreciation._add_months`：日号越界取该月最后一天，
#    1/31 + 1 月 = 2/28）。自己再写一份的话，两处的"月末"口径迟早会分叉。
from app.services.vehicle_depreciation import _add_months

#: 一个账号同时最多几台设备（**有效**绑定数）
MAX_DEVICES_PER_ACCOUNT = 3
#: 换设备的冷却期：`bound_at + BIND_TTL_MONTHS` 个月之后那台才算"失效、可被顶掉"。
#: 用户 2026-10-11：「让上一个失效……也还是 6 个月」；口径以**绑定时间**为准，不是最后活跃时间。
BIND_TTL_MONTHS = 6
#: 一台设备同时最多绑几个账号（用户 2026-10-11：「一台手机至少是可以绑 5 个」）
MAX_ACCOUNTS_PER_DEVICE = 5
#: 一台设备 24 小时内最多**新增**几个账号绑定（速率闸，防脚本；总量到 5 之前都允许）
MAX_NEW_ACCOUNTS_PER_DEVICE_24H = 2
#: 注册处：同一台设备 24 小时内最多开几个**新号**（挡批量刷号的关键那道闸）
MAX_NEW_ACCOUNTS_PER_DEVICE_REGISTER_24H = 1
#: 速率闸的窗口
DEVICE_WINDOW = timedelta(hours=24)
#: App 统一注入的请求头：`<install_id>:<token>`
DEVICE_HEADER = "X-Device-Id"
#: install_id 的形状（UUID / 十六进制串都收）：8~64 位字母、数字、连字符、下划线
INSTALL_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")

#: 解绑原因（写进 `account_devices.unbind_reason`）
UNBIND_REASON_ADMIN = "admin"
UNBIND_REASON_EXPIRED = "expired"
#: 绑定来源（写进 `account_devices.source`）
SOURCE_LOGIN = "login"
SOURCE_REGISTER = "register"


class DeviceBindingError(Exception):
    """绑定被拒。`detail` 是给用户看的中文原话，状态码由调用方决定（登录 403 / 注册 429）。"""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


# ---------------------------------------------------------------- 设备签名

def device_token(install_id: str) -> str:
    """给 install_id 签一份服务端 HMAC-SHA256（十六进制）。

    密钥复用 `core/security.get_jwt_secret()`（与 JWT 同一份配置，不新开一个 settings 字段），
    消息加 `device-v1:` 前缀做**域分离** —— 同样的密钥在两边签的东西不会互相通用。
    """
    secret = get_jwt_secret().encode("utf-8")
    return hmac.new(secret, b"device-v1:" + install_id.encode("utf-8"), hashlib.sha256).hexdigest()


def device_id_from_header(raw: str | None) -> str | None:
    """从 `X-Device-Id: <install_id>:<token>` 里取出**签名对得上**的 install_id。

    对不上（没带 / 形状不对 / 签名不对）一律返回 None，调用方的口径是「**当作没有设备信息**」，
    而不是报错：老版本 App 根本没有这个头，把"没带"当成错误会让全体老客户端登不进来；
    而伪造一个头的人拿到的结果与"没带"一样（限制少一条？⛔ 不：没带 = 不记绑定，
    但也就不会因为"这台设备"被挡 —— 见模块 docstring 第 1 条的诚实说明）。
    """
    value = (raw or "").strip()
    if ":" not in value:
        return None
    install_id, _, token = value.rpartition(":")
    install_id = install_id.strip()
    token = token.strip().lower()
    if not INSTALL_ID_RE.match(install_id) or not token:
        return None
    if not hmac.compare_digest(device_token(install_id), token):
        return None
    return install_id


def normalize_install_id(raw: str | None) -> str | None:
    """App 报上来的安装标识：形状对了才收（⛔ 返回值直接进库，长度与字符集在这里卡死）。"""
    value = (raw or "").strip()
    if not INSTALL_ID_RE.match(value):
        return None
    return value


# ---------------------------------------------------------------- 时间

def add_months(moment: datetime, months: int) -> datetime:
    """按仓库唯一那份月份加法往后推（日号越界取该月最后一天），时分秒不变。"""
    return datetime.combine(_add_months(moment.date(), months), moment.time())


def binding_expires_at(bound_at: datetime) -> datetime:
    """这台设备的"最早可替换时刻" = 绑上那天 + `BIND_TTL_MONTHS` 个月。"""
    return add_months(bound_at, BIND_TTL_MONTHS)


# ---------------------------------------------------------------- 中文话术

def _account_full_detail(expires_at: datetime) -> str:
    return (
        f"这个账号已绑 {MAX_DEVICES_PER_ACCOUNT} 台设备，最早那台要到 "
        f"{expires_at:%Y-%m-%d} 才能替换；急用请联系派单员在「账户管理 → 编辑」里解冻。"
    )


def _device_full_detail() -> str:
    return (
        f"这台设备已经绑了 {MAX_ACCOUNTS_PER_DEVICE} 个账号，不能再绑新账号了；"
        "如果是同一部手机换了号，请联系派单员处理。"
    )


def _device_too_fast_detail() -> str:
    return (
        f"这台设备 24 小时内已经绑过 {MAX_NEW_ACCOUNTS_PER_DEVICE_24H} 个账号，"
        "短时间内不能再绑新账号了，请明天再试；急用请联系派单员。"
    )


def _device_register_detail() -> str:
    return (
        "这台设备 24 小时内已经注册过一个账号了，不能接着注册；"
        "请明天再试，或让派单员在「账号管理」里建。"
    )


# ---------------------------------------------------------------- 查询

def list_bindings(db: Session, user_id: int) -> list[AccountDevice]:
    """一个账号的全部绑定（**含已解冻的历史**），新的在前。"""
    return list(
        db.scalars(
            select(AccountDevice)
            .where(AccountDevice.user_id == user_id)
            .order_by(AccountDevice.bound_at.desc(), AccountDevice.id.desc())
        )
    )


def get_binding(db: Session, user_id: int, binding_id: int) -> AccountDevice | None:
    """按 id 取一行，并**限定在这个账号名下**（端点上的 user_id 与 binding_id 必须自洽）。"""
    return db.scalars(
        select(AccountDevice).where(
            AccountDevice.id == binding_id, AccountDevice.user_id == user_id
        )
    ).first()


def _accounts_on_device(db: Session, device_id: str, *, exclude_user_id: int | None = None) -> int:
    """这台设备现在**有效**绑着几个**不同**的账号。"""
    stmt = select(func.count(func.distinct(AccountDevice.user_id))).where(
        AccountDevice.device_id == device_id,
        AccountDevice.unbound_at.is_(None),
    )
    if exclude_user_id is not None:
        stmt = stmt.where(AccountDevice.user_id != exclude_user_id)
    return int(db.execute(stmt).scalar() or 0)


def _accounts_on_device_since(
    db: Session, device_id: str, since: datetime, *, exclude_user_id: int | None = None
) -> int:
    """这台设备在 `since` 之后**新增**了几个不同的账号绑定（按 `bound_at` 数）。"""
    stmt = select(func.count(func.distinct(AccountDevice.user_id))).where(
        AccountDevice.device_id == device_id,
        AccountDevice.bound_at >= since,
    )
    if exclude_user_id is not None:
        stmt = stmt.where(AccountDevice.user_id != exclude_user_id)
    return int(db.execute(stmt).scalar() or 0)


# ---------------------------------------------------------------- 绑定

def _check_device_side(db: Session, *, device_id: str, now: datetime, user_id: int) -> None:
    """设备那一侧的两条闸（硬上限 + 24 小时速率）。"""
    if _accounts_on_device(db, device_id, exclude_user_id=user_id) >= MAX_ACCOUNTS_PER_DEVICE:
        raise DeviceBindingError(_device_full_detail())
    recent = _accounts_on_device_since(
        db, device_id, now - DEVICE_WINDOW, exclude_user_id=user_id
    )
    if recent >= MAX_NEW_ACCOUNTS_PER_DEVICE_24H:
        raise DeviceBindingError(_device_too_fast_detail())


def bind_device(
    db: Session, *, user: User, device_id: str | None, source: str
) -> AccountDevice | None:
    """把 (账号, 设备) 这一对记下来；被风控拒时抛 `DeviceBindingError`。

    返回 None 只有两种情况：**没带设备**（老版本 App / 没有签名）与**豁免的测试账号**。

    ⛔ 顺序有讲究：**先判账号侧、再判设备侧**。反过来的话，"这个账号已经满了"这种
    用户自己能理解的原因会被"这台设备太快了"盖掉 —— 后者听起来像在怀疑他，
    而真正该告诉他的是"最早那台某月某日才能换"。
    """
    if not device_id:
        return None
    if is_test_account(user.phone):
        return None
    now = utc_now_naive()
    rows = list(db.scalars(select(AccountDevice).where(AccountDevice.user_id == user.id)))
    mine = next((r for r in rows if r.device_id == device_id), None)
    if mine is not None and mine.unbound_at is None:
        # 就是本机：只刷新活跃时间，**不占**任何额度，也不改 bound_at（冷却期起点不能被动摇）
        mine.last_seen_at = now
        return mine

    active = [r for r in rows if r.unbound_at is None]
    replaced: AccountDevice | None = None
    if len(active) >= MAX_DEVICES_PER_ACCOUNT:
        replaced = min(active, key=lambda r: (r.bound_at, r.id))
        expires_at = binding_expires_at(replaced.bound_at)
        if expires_at > now:
            raise DeviceBindingError(_account_full_detail(expires_at))

    _check_device_side(db, device_id=device_id, now=now, user_id=user.id)

    if replaced is not None:
        # 用户说的"让上一个失效"：置为 expired（**不删行**，什么时候绑的还能回查）
        replaced.unbound_at = now
        replaced.unbind_reason = UNBIND_REASON_EXPIRED
    if mine is None:
        mine = AccountDevice(
            user_id=user.id, device_id=device_id, bound_at=now, last_seen_at=now, source=source
        )
        db.add(mine)
    else:
        # 复用同一对那一行（唯一约束保证只有一行）：解冻状态清掉、绑定时间更新
        mine.unbound_at = None
        mine.unbind_reason = None
        mine.bound_at = now
        mine.last_seen_at = now
        mine.source = source
    db.flush()
    return mine


def check_device_registration(db: Session, *, device_id: str | None, phone: str | None) -> None:
    """注册前的设备闸：同一台设备 24 小时内最多开 `MAX_NEW_ACCOUNTS_PER_DEVICE_REGISTER_24H` 个新号。

    这是"挡批量刷号"的关键那道（比登录那条紧）：登录那条允许 24 小时内陆续加 2 个号，
    但**注册**一条都不许多余 —— 一台设备一天最多开一个新号。
    超了抛 `DeviceBindingError`（调用方回 **429**）。没带设备 = 老版本 App，放行；
    测试号（`is_test_account`）整条跳过 —— 用户 2026-10-11：「测试账号除外」。
    """
    if not device_id:
        return
    if is_test_account(phone):
        return
    now = utc_now_naive()
    if _accounts_on_device(db, device_id) >= MAX_ACCOUNTS_PER_DEVICE:
        raise DeviceBindingError(_device_full_detail())
    recent = _accounts_on_device_since(db, device_id, now - DEVICE_WINDOW)
    if recent >= MAX_NEW_ACCOUNTS_PER_DEVICE_REGISTER_24H:
        raise DeviceBindingError(_device_register_detail())


# ---------------------------------------------------------------- 解绑（派单员）

def unbind(db: Session, *, user_id: int, binding_id: int) -> AccountDevice | None:
    """解冻一台设备（**派单员手工动作**，用户拍板："就在编辑当中"）。

    已经解冻过的行返回 None（幂等：不做动作就不写审计）。找不到也返回 None。
    """
    row = get_binding(db, user_id, binding_id)
    if row is None or row.unbound_at is not None:
        return None
    row.unbound_at = utc_now_naive()
    row.unbind_reason = UNBIND_REASON_ADMIN
    db.flush()
    return row


def unbind_all(db: Session, *, user_id: int) -> list[AccountDevice]:
    """把这个账号**所有**有效绑定一次解开（"司机换手机"最常用的一键）。返回被解开的那几行。"""
    now = utc_now_naive()
    rows = [r for r in list_bindings(db, user_id) if r.unbound_at is None]
    for row in rows:
        row.unbound_at = now
        row.unbind_reason = UNBIND_REASON_ADMIN
    if rows:
        db.flush()
    return rows
