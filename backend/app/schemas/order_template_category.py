"""预订单分类名册的出参与入参（照 `schemas/product_category.py` 同一套形状）。

⚠️ `template_count` 是**出参**（"这个分类下挂着几张预设单"，删除前的判据也是它）——
它不是数据库里的列，由端点一次查完补上（⛔ 不要每个分类查一遍）。
"""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class OrderTemplateCategoryCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=32)
    #: 不传 = 排到最后（后端给 `max+1`）；传了就按它（0 会抢在第一个前面，别用 0）
    sort_order: int | None = None


class OrderTemplateCategoryUpdate(BaseModel):
    """**部分更新**：只传要改的键。改名会级联改掉挂在它下面的预设单（同事务）。"""

    name: str | None = Field(None, min_length=1, max_length=32)
    sort_order: int | None = None


class OrderTemplateCategoryReorder(BaseModel):
    """**整份顺序**一次提交：`ids[0]` 排最前（必须覆盖全部现存分类，见 `services/category_order.py`）。"""

    ids: list[int] = Field(default_factory=list)


class OrderTemplateCategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    sort_order: int
    #: 这个分类下**在用**（没进回收站）的预设单有几张。删除时它是唯一判据。
    template_count: int = 0
    created_at: datetime
