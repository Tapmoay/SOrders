"""运费分类名册的入参 / 出参（与商品分类、开销分类同一套规矩）。"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.text import MAX_SHORT_NAME


def _clean_name(v: object) -> str:
    """分类名统一清洗：**只 strip，不截断**（截断会把用户起的长名字悄悄改掉且不报错）。"""
    s = str(v or "").strip()
    if not s:
        raise ValueError("分类名不能为空或纯空格")
    return s


class FreightCategoryCreate(BaseModel):
    name: str = Field(..., max_length=MAX_SHORT_NAME)
    #: 不传 = 排到最后（服务端算 max+1，**不是 0** —— 0 会抢在第一个前面）
    sort_order: int | None = Field(None, description="显示顺序，小的在前；不传=排到最后")

    @field_validator("name", mode="before")
    @classmethod
    def name_ok(cls, v: object) -> str:
        return _clean_name(v)


class FreightCategoryUpdate(BaseModel):
    name: str | None = Field(None, max_length=MAX_SHORT_NAME)
    sort_order: int | None = None

    @field_validator("name", mode="before")
    @classmethod
    def name_ok(cls, v: object) -> str | None:
        return None if v is None else _clean_name(v)


class FreightCategoryReorder(BaseModel):
    """整份顺序：`ids` 就是新的显示顺序（第 0 个排最前）。**必须整份提交**（见路由注释）。"""

    ids: list[int] = Field(..., min_length=1, max_length=200)


class FreightCategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    sort_order: int = 0
    #: 有几条运费价目挂在这一类（删之前要让用户看见"还有几条在用"）
    template_count: int = 0
    #: 有几份司机计费规则在这一类上定了价
    rule_count: int = 0
