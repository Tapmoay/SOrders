"""设备绑定相关的出入参（FEAT-0018，2026-10-11 用户要求）。

三段形状对应契约里的三段：App 领设备签名（`DeviceRegisterIn/Out`）、派单员看一个账号
绑过哪些设备（`DeviceBindingOut`）。字段名就是契约里写死的那些
（⛔ 别在端点里另起名字 —— App 那半边照着同一份契约写，改一个字段名就是两端不一致）。
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class DeviceRegisterIn(BaseModel):
    """`POST /api/v1/devices/register` 的入参：App 本机生成的安装标识。"""

    # 这里只卡长度上下界；**形状**（字母/数字/连字符/下划线）由
    # `device_service.normalize_install_id` 的 `INSTALL_ID_RE` 判。
    # ⛔ 正则只留一份：两处都写，迟早会有一天不一致，而"哪一份算数"没人说得清。
    install_id: str = Field(..., min_length=8, max_length=64)


class DeviceRegisterOut(BaseModel):
    """发回去的签名。App 之后每个请求带 `X-Device-Id: <device_id>:<token>`。"""

    device_id: str
    token: str


class DeviceBindingOut(BaseModel):
    """派单员看到的**一台设备一行**。

    列表里**也**返回已经解冻的历史行（`active=false`）—— 用户拍板的场景是"司机换手机，
    联系派单员解冻"，解冻之后派单员还得能回查"之前那台是什么时候绑的"。
    """

    id: int
    device_id: str
    bound_at: datetime
    last_seen_at: datetime
    #: login / register / admin
    source: str
    #: true = 现在还在生效（`unbound_at` 为空）
    active: bool
    #: 这一台最早能被替换的时刻 = bound_at + `BIND_TTL_MONTHS` 个月。
    #: **算出来的**，库里不存（存一份就多一个会与 bound_at 分叉的来源）
    expires_at: datetime
