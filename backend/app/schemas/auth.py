"""登录 / 注册入参、token 出参。

⚠️ 历史：`SendSmsRequest` 与 `RegisterRequest` 曾于 2026-09-18 随自助注册端点一起删除。
**2026-10-11（FEAT-0017）用户要求把"注册"拿回来** —— `RegisterRequest` 重新登场，
但形状与当年不同（当年带短信验证码）。**`SendSmsRequest` 仍然不做**：短信那条路是当年
被删的真正原因（本地 `sms_reveal_code=true` 时验证码明文回显，等于没有验证）。
"""

from pydantic import BaseModel, Field, model_validator

from app.core.phone import MobilePhone
from app.models.enums import UserRole


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: UserRole
    user_id: int


class RegisterRequest(BaseModel):
    """自助注册：手机号 + 密码（可选姓名）。**默认货主**，没有任何可选的账号属性。

    ⛔ 这里**故意不声明** `role` / `is_member` / `vehicle_type` / `is_active` 等字段：
    pydantic 默认 `extra="ignore"`，所以请求体里带了它们也**不会**进到端点里 —— 这是
    "请求体带 role 也提不了权"的第一道（第二道在端点里，角色/属性全部由服务端写死）。
    真用 `extra="forbid"` 反而更糟：老客户端多带一个无关字段就被 422 挡在门外。

    手机号走 `core/phone.py` 的**唯一一份**规则（11 位数字且以 1 开头，见 `MOBILE_PATTERN`；
    App 端同一口径先拦一道）；
    密码口径照建账号那条（`schemas/user.py::UserCreate`）：6~128 位。
    """

    phone: MobilePhone = Field(..., max_length=11, description="手机号（同时是登录名）")
    password: str = Field(..., min_length=6, max_length=128)
    full_name: str = Field(
        default="",
        max_length=128,
        description="姓名，可选；留空则只显示手机号",
    )


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
