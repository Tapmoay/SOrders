"""账号 ↔ 设备绑定（FEAT-0018，2026-10-11 用户要求）。

### 用户口径（逐字要点）
「一个账号大概只能绑定一个手机/一个设备（mac/设备序列号，唯一）……也不说完全只能绑定 3 个吧……
它是有时间限制的……大概 6 个月」；「我们的一个设备（一个唯一的设备地址）不能同时间、短时间内
绑定多个账号 —— 防止有人利用这个漏洞批量注册一堆账号来攻击服务器」；「**测试账号除外**」。

### 这张表回答什么
「这个账号历史上绑过哪些设备、什么时候绑的、现在还有效吗」。
**解绑不删行**：派单员手动解冻（司机换手机 / 手机摔了）之后，「之前那台是什么时候绑的」
必须还能回查 —— 删行等于把审计也删掉。所以一行的生命周期是：

    bound_at 写入 → （可选）unbound_at + unbind_reason 写入 → 同一对再次绑定时**复用这一行**
    （unbound_at 清空、bound_at 更新回现在）

### 生效的判据只看两个字段
`unbound_at is None` = 这一行现在是「有效绑定」；`bound_at` = 冷却期的起点（**不是**
`last_seen_at`，用户说的 6 个月是从「绑上那天」算）。到期时间 = bound_at + BIND_TTL_MONTHS，
在 `app/services/device_service.py` 里**算出来**，⛔ 不存库：存一份就多一个会与
bound_at 不一致的来源。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.business_time import utc_now_naive
from app.models.base import Base, TimestampMixin


class AccountDevice(Base, TimestampMixin):
    """一行 = 一对 (账号, 设备)。同一对只有一行（唯一约束），解绑后复用它。"""

    __tablename__ = "account_devices"
    __table_args__ = (
        UniqueConstraint("user_id", "device_id", name="uq_account_devices_user_device"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    #: App 的安装标识（install_id），8~64 位；形状与签名校验在 device_service 里
    device_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    #: 绑上这台设备的时刻（= 冷却期的起点，**不是** last_seen_at）
    bound_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now_naive)
    #: 最后一次带着这台设备出现的时刻（登录成功时刷新；不参与冷却期计算）
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now_naive)
    #: 解绑时刻（NULL = 现在还有效）
    unbound_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)
    #: 解绑原因：admin（派单员手动解冻）/ expired（满了 6 个月被新设备顶掉）
    unbind_reason: Mapped[str | None] = mapped_column(String(16), nullable=True, default=None)
    #: 这一对是怎么绑上的：login / register / admin
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="login")
