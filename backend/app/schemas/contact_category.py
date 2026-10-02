"""联系人分类名册的入参 / 出参（与地点分类同一套形状，差在**数的是联系人**）。"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.text import MAX_SHORT_NAME


def _clean_name(v: object) -> str:
    """分类名统一清洗：**只 strip，不截断**（理由与 `schemas/product_category.py` 同一份：
    截断会把 8000 字的名字悄悄砍成 32 字还回 201；长度该交给字段的 `max_length` 回 422）。"""
    s = str(v or "").strip()
    if not s:
        raise ValueError("分类名不能为空或纯空格")
    return s


class ContactCategoryCreate(BaseModel):
    name: str = Field(..., max_length=MAX_SHORT_NAME)
    # 不传 = 排到最后（服务端算 max+1，**不是 0** —— 0 会抢在第一个前面）
    sort_order: int | None = Field(None, description="显示顺序，小的在前；不传=排到最后")

    @field_validator("name", mode="before")
    @classmethod
    def name_ok(cls, v: object) -> str:
        return _clean_name(v)


class ContactCategoryUpdate(BaseModel):
    name: str | None = Field(None, max_length=MAX_SHORT_NAME)
    sort_order: int | None = None

    @field_validator("name", mode="before")
    @classmethod
    def name_ok(cls, v: object) -> str | None:
        return None if v is None else _clean_name(v)


class ContactCategoryReorder(BaseModel):
    """整份顺序：`ids` 就是新的显示顺序（第 0 个排最前）；幂等（与地点分类同一理由）。"""

    ids: list[int] = Field(..., min_length=1, max_length=200)


class ContactCategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    sort_order: int = 0
    #: 这个分类下**在用**的联系人条数（删/改之前让用户看见影响面）
    contact_count: int = 0
