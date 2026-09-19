"""商品分类名册的入参 / 出参。"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.text import MAX_SHORT_NAME


def _clean_name(v: object) -> str:
    """分类名统一清洗：**只 strip，不截断**。

    为什么要 strip：分类名是给人看的短词，`"  饮料  "` 与 `"饮料"` 在选品页会是
    **两格内容一样的东西**；而它还是 `products.category` 的匹配键，不一致就等于分错组。

    为什么**不**在这里截断（2026-09-18 契约模糊测试抓到）：
    第一版写的是 `str(v or "").strip()[:MAX_SHORT_NAME]`，于是带一个 8000 字的分类名
    会返回 **201**、名字被**悄悄砍成前 32 个字** —— 用户以为起了个长名字，
    实际存进去的是另一串，而且**没有任何提示**。
    长度该交给字段的 `max_length`（它会回 422 + 一句中文），
    而不是在 before 校验器里把输入变成"合法但不一样"的值。
    """
    s = str(v or "").strip()
    if not s:
        raise ValueError("分类名不能为空或纯空格")
    return s


class ProductCategoryCreate(BaseModel):
    name: str = Field(..., max_length=MAX_SHORT_NAME)
    # 不传 = 排到最后（服务端算 max+1，**不是 0** —— 0 会抢在第一个前面）
    sort_order: int | None = Field(None, description="显示顺序，小的在前；不传=排到最后")

    @field_validator("name", mode="before")
    @classmethod
    def name_ok(cls, v: object) -> str:
        return _clean_name(v)


class ProductCategoryUpdate(BaseModel):
    name: str | None = Field(None, max_length=MAX_SHORT_NAME)
    sort_order: int | None = None

    @field_validator("name", mode="before")
    @classmethod
    def name_ok(cls, v: object) -> str | None:
        return None if v is None else _clean_name(v)


class ProductCategoryReorder(BaseModel):
    """整份顺序：`ids` 就是新的显示顺序（第 0 个排最前）。

    为什么用"整份顺序"而不是"把 X 上移一格"：上下移动是一次一步、要连点好几次，
    而且并发改的时候两条请求的语义会互相踩（都想插到对方前面）。
    整份提交是幂等的 —— 重复提交同一份结果相同。
    """

    ids: list[int] = Field(..., min_length=1, max_length=200)


class ProductCategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    sort_order: int = 0
    #: 这个分类下**在用**的商品数（删之前要让用户看见"有多少商品挂在这一类"）
    product_count: int = 0
