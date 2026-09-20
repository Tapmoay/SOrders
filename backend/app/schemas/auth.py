"""登录入参 / token 出参。

⚠️ `SendSmsRequest` 与 `RegisterRequest` 已于 2026-09-18 随自助注册端点一起删除
（用户要求关掉注册；账号改由派单员在 `POST /api/v1/users` 创建）。
"""

from pydantic import BaseModel, Field, model_validator

from app.models.enums import UserRole


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: UserRole
    user_id: int


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
