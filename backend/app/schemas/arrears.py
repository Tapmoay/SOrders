from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.core.phone import ContactPhone, OptionalContactPhone


class ArrearsUnitCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    # 挂账单位电话：规则在 `app/core/phone.py`（去空格后 7~12 位数字，空 = 没填）
    phone: ContactPhone = Field(default="", max_length=32)
    remark: str = Field(default="", max_length=256)


class ArrearsUnitUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=128)
    # None = 不改这一项（可选别名会放行 None）
    phone: OptionalContactPhone = Field(None, max_length=32)
    remark: str | None = Field(None, max_length=256)


class ArrearsUnitOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    phone: str
    remark: str
    created_at: datetime
