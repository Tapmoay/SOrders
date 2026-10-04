from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.core.phone import ContactPhone, OptionalContactPhone
from app.schemas.money import MONEY_MAX


class ArrearsUnitCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    # 挂账单位电话：规则在 `app/core/phone.py`（去空格后 7~12 位数字，空 = 没填）
    phone: ContactPhone = Field(default="", max_length=32)
    remark: str = Field(default="", max_length=256)
    # 信用额度（FEAT-0015 第五期）：这一家最多能赊多少。None = **不限额**（⛔ 不是 0）。
    # ⚠️ 字段名 `credit_limit` 命中不了 `schemas/money.py` 的金额名正则（那里管的是 price/amount/
    #    total/balance 这一族），所以这里的范围必须自己写：⛔ 不许负额度（负额度 = 反向赊账，不存在）。
    credit_limit: Decimal | None = Field(None, ge=0, le=MONEY_MAX)


class ArrearsUnitUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=128)
    # None = 不改这一项（可选别名会放行 None）
    phone: OptionalContactPhone = Field(None, max_length=32)
    remark: str | None = Field(None, max_length=256)
    # ⚠️ 额度这一项与上面三个**不一样**：对额度来说 `null` 是一个**合法的值**
    #    （= 清掉额度、回到"不限额"），所以「没传这一项」与「传了 null」必须分开 ——
    #    端点用 `model_fields_set` 判断，⛔ 不看 None。
    credit_limit: Decimal | None = Field(None, ge=0, le=MONEY_MAX)


class ArrearsUnitOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    phone: str
    remark: str
    credit_limit: Decimal | None = None
    created_at: datetime
