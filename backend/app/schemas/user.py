from datetime import datetime

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

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
    created_at: datetime


class UserCreate(MoneyInput):
    # 派单员建号：账号=手机号，必须 11 位（1 开头）——客户端已限制，服务端兜底
    phone: str = Field(..., pattern=r"^1\d{10}$")
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
    phone: str | None = Field(None, min_length=5, max_length=32)
    password: str | None = Field(None, min_length=6, max_length=128)
    full_name: str | None = Field(None, max_length=128)
    role: UserRole | None = None
    is_active: bool | None = None
    is_member: bool | None = None
    vehicle_type: str | None = Field(None, max_length=16)
    billing_mode: str | None = Field(None, max_length=16)
    salary: Decimal | None = Field(None, ge=0)
