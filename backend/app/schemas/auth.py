import re

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.enums import UserRole

USERNAME_RE = re.compile(r"^[a-zA-Z0-9_\u4e00-\u9fff]{3,32}$")


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: UserRole
    user_id: int


class TokenPayload(BaseModel):
    sub: str | None = None
    role: UserRole | None = None


class LoginRequest(BaseModel):
    """登录：密码必填；手机号与 username 二选一（均为登录名，通常为手机号）。"""

    password: str = Field(..., min_length=1)
    phone: str | None = Field(default=None, min_length=5, max_length=32)
    username: str | None = Field(
        default=None,
        min_length=5,
        max_length=32,
        description="与 phone 同义，任选其一",
    )

    @model_validator(mode="after")
    def _normalize_login(self) -> "LoginRequest":
        login_id = (self.phone or self.username or "").strip()
        if not login_id:
            raise ValueError("phone 或 username 必填其一")
        object.__setattr__(self, "phone", login_id)
        return self


class SendSmsRequest(BaseModel):
    """向手机号发送注册验证码（中国大陆 11 位）。"""

    phone: str = Field(..., min_length=11, max_length=11)

    @field_validator("phone")
    @classmethod
    def _phone_fmt(cls, v: str) -> str:
        p = v.strip()
        if not re.match(r"^1[3-9]\d{9}$", p):
            raise ValueError("手机号格式不正确")
        return p


class RegisterRequest(BaseModel):
    """自助注册货主；司机与派单员由管理员创建。"""

    username: str = Field(..., min_length=3, max_length=32)
    password: str = Field(..., min_length=6, max_length=128)
    phone: str = Field(..., min_length=11, max_length=11)
    verification_code: str = Field(..., min_length=4, max_length=8)

    @field_validator("verification_code")
    @classmethod
    def _strip_verification(cls, v: str) -> str:
        return v.strip()

    @field_validator("username")
    @classmethod
    def _username_fmt(cls, v: str) -> str:
        s = v.strip()
        if not USERNAME_RE.match(s):
            raise ValueError("用户名需为 3–32 位，含字母、数字、下划线或中文")
        return s

    @field_validator("phone")
    @classmethod
    def _reg_phone(cls, v: str) -> str:
        p = v.strip()
        if not re.match(r"^1[3-9]\d{9}$", p):
            raise ValueError("手机号格式不正确")
        return p
