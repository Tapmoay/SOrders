from datetime import datetime

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import UserRole


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
    created_at: datetime


class UserCreate(BaseModel):
    phone: str = Field(..., min_length=5, max_length=32)
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


class UserUpdate(BaseModel):
    phone: str | None = Field(None, min_length=5, max_length=32)
    password: str | None = Field(None, min_length=6, max_length=128)
    full_name: str | None = Field(None, max_length=128)
    role: UserRole | None = None
    is_active: bool | None = None
    is_member: bool | None = None
    vehicle_type: str | None = Field(None, max_length=16)
    billing_mode: str | None = Field(None, max_length=16)
    salary: Decimal | None = Field(None, ge=0)
