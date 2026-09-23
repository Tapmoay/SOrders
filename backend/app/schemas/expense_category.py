"""开销分类名册的入参 / 出参（与商品分类名册同一套规矩）。"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.expense_category import LINK_KINDS
from app.schemas.text import MAX_SHORT_NAME


def _clean_name(v: object) -> str:
    """分类名统一清洗：**只 strip，不截断**（截断会把用户起的长名字悄悄改掉且不报错）。"""
    s = str(v or "").strip()
    if not s:
        raise ValueError("分类名不能为空或纯空格")
    return s


def _check_link(v: object) -> str:
    s = str(v or "none").strip() or "none"
    if s not in LINK_KINDS:
        raise ValueError(f"「主要关联」只能是 {'/'.join(LINK_KINDS)} 之一")
    return s


class ExpenseCategoryCreate(BaseModel):
    name: str = Field(..., max_length=MAX_SHORT_NAME)
    # 不传 = 排到最后（服务端算 max+1，**不是 0** —— 0 会抢在第一个前面）
    sort_order: int | None = Field(None, description="显示顺序，小的在前；不传=排到最后")
    #: 卡片上突出哪一项（vehicle/driver/order/none）；不传 = none
    # ⚠️ `max_length=16` 与列宽一致（`expense_categories.link_kind` 是 `String(16)`）：
    #    取值本身由 `link_ok` 限死在 `LINK_KINDS` 里，但**声明上界**也要写 —— 本机 SQLite
    #    照收超长、生产 MySQL `Data too long`（2026-09-23 第 18 轮 `_audit_text_fields.py` 报的）。
    link_kind: str = Field("none", max_length=16, description="卡片上突出哪一项：vehicle/driver/order/none")

    @field_validator("name", mode="before")
    @classmethod
    def name_ok(cls, v: object) -> str:
        return _clean_name(v)

    @field_validator("link_kind", mode="before")
    @classmethod
    def link_ok(cls, v: object) -> str:
        return _check_link(v)


class ExpenseCategoryUpdate(BaseModel):
    name: str | None = Field(None, max_length=MAX_SHORT_NAME)
    sort_order: int | None = None
    link_kind: str | None = Field(None, max_length=16)  # 与列宽一致（说明见 Create 那处）

    @field_validator("name", mode="before")
    @classmethod
    def name_ok(cls, v: object) -> str | None:
        return None if v is None else _clean_name(v)

    @field_validator("link_kind", mode="before")
    @classmethod
    def link_ok(cls, v: object) -> str | None:
        return None if v is None else _check_link(v)


class ExpenseCategoryReorder(BaseModel):
    """整份顺序：`ids` 就是新的显示顺序（第 0 个排最前）。**必须整份提交**（见路由注释）。"""

    ids: list[int] = Field(..., min_length=1, max_length=200)


class ExpenseCategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    sort_order: int = 0
    link_kind: str = "none"
    #: 这个分类下**在用**的开销笔数（删之前要让用户看见"有多少笔挂在这一类"）
    expense_count: int = 0
