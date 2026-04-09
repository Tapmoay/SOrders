from datetime import datetime

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
    created_at: datetime


class UserCreate(BaseModel):
    phone: str = Field(..., min_length=5, max_length=32)
    username: str | None = Field(None, min_length=3, max_length=32)
    password: str = Field(..., min_length=6, max_length=128)
    full_name: str = Field(default="", max_length=128)
    role: UserRole

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
