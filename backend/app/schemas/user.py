from datetime import datetime

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.phone import MobilePhone, OptionalMobilePhone
from app.models.enums import UserRole
from app.schemas.money import MoneyInput


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    phone: str
    full_name: str
    role: UserRole
    is_active: bool
    is_member: bool = False
    vehicle_type: str | None = None
    billing_mode: str | None = None
    salary: Decimal | None = None
    # 挂着的计费规则（v3.36）：司机管理页要能一眼看出"他是按哪份规则算钱的"。
    # `pay_summary` 由 `driver_pay` 生成（规则说什么，或没挂规则时的老口径），
    # **界面不许自己拼这句话**——拼了就会和账单口径不一致。
    driver_rule_id: int | None = None
    driver_rule_name: str = ""
    pay_summary: str = ""
    # 「他按不按单拿钱」——决定派单端**要不要给这个司机显示运费框**。
    # ⛔ 与账单同一个判据（`driver_pay.snapshot_mode`，规则优先），客户端**不许**自己按
    #    车型/`billing_mode` 猜：猜错的表现是运费框不显示 → 运费为空 → 提成型的规则算成 0
    #    → 送达时 `pay.total <= 0` **连账单都不生成**（2026-09-19 全项目报告 P0-3）。
    #    None = 非司机（这个字段对他没有意义）。
    pays_per_order: bool | None = None
    # 「他**现在有没有按单的账要看**」—— 决定司机端「我的账单」那一格显不显示（2026-09-21 真机抓到）。
    # ⛔ 与上面那个是**两件事**：`pays_per_order` 面向**以后派的单**（派单端要它决定运费框），
    #    这一个面向**已经发生的钱**（当前按单 **或** 账上已有按单账单）。
    #    判据在 `services/driver_pay.has_per_order_earnings`（钱的唯一口径处），客户端不许自己算：
    #    只按 `pays_per_order` 判的后果是——被改成固定工资的司机，他那笔改规则之前攒下的
    #    按单钱（prod 实测 ¥2024）在 App 里**再也看不到**（订单卡片已经不画任何金额了）。
    #    None = 非司机或这次没查（客户端按 false 处理）。
    has_per_order_earnings: bool | None = None
    created_at: datetime


class UserCreate(MoneyInput):
    # 派单员建号：账号=手机号，必须 11 位（1 开头）——客户端已限制，服务端兜底。
    # 规则本身在 `app/core/phone.py`（原来这里写着 `pattern=r"^1\d{10}$"`，是**第二条**同义实现，
    # 已收拢到唯一实现处；`max_length=11` 与规则同宽，只是给"文本上界"审计一个可读的界）。
    phone: MobilePhone = Field(..., max_length=11)
    username: str | None = Field(None, min_length=3, max_length=32)
    password: str = Field(..., min_length=6, max_length=128)
    full_name: str = Field(default="", max_length=128)
    role: UserRole
    is_member: bool = False
    vehicle_type: str | None = Field(None, max_length=16)
    billing_mode: str | None = Field(None, max_length=16)
    salary: Decimal | None = Field(None, ge=0)

    @model_validator(mode="after")
    def _default_username(self) -> "UserCreate":
        if not self.username:
            object.__setattr__(self, "username", self.phone)
        return self


class UserUpdate(MoneyInput):
    # 改账号手机号：与建号**同一条规则**（`app/core/phone.py`），原先只有 min/max_length，
    # 也就是说建号必须 11 位、改号却可以改成任意 5~32 个字符 —— 改完就登不进来了。
    phone: OptionalMobilePhone = Field(None, max_length=11)
    password: str | None = Field(None, min_length=6, max_length=128)
    full_name: str | None = Field(None, max_length=128)
    role: UserRole | None = None
    is_active: bool | None = None
    is_member: bool | None = None
    vehicle_type: str | None = Field(None, max_length=16)
    billing_mode: str | None = Field(None, max_length=16)
    salary: Decimal | None = Field(None, ge=0)
