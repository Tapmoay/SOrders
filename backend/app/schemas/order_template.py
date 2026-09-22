"""预订单（订单模板）的出参与入参。

⚠️ 两条不能省的规矩：
1. **`lines` 必须把 `None` 归一到 `[]`**（`@field_validator(mode="before")`）：
   JSON 列在 MySQL / 旧数据里可能是 NULL，而 Pydantic 的 `default_factory=list` 只兜
   "字段缺失"、不兜 None —— 少了这一条，`GET /order-templates` 会在拿到一条老记录时
   整个 500（本项目栽过同一个坑，见 `docs/PROJECT_MAP` 里的 JSON 列约定）。
2. **`price` 不在行里**（见 `models/order_template.py` 文件头第 2 条）：预设的是
   "哪几样、各多少"，金额一律在下单那一刻按商品价算。
"""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.phone import OptionalContactPhone

#: 一张预设单最多几行（与后端订单的商品行上限同一量级）。
#: 有上限不是为了省资源，而是**让用户有机会核对**：预设单是"以后会变成真订单"的东西，
#: 一次塞 200 行进去，下单时没有人会去逐行看。
MAX_LINES = 30


class OrderTemplateLine(BaseModel):
    """预设单里的一行货：**商品编号 + 数量**（+ 两个显示用快照）。"""

    product_id: int | None = None
    #: 商品名快照：预设单列表要显示"我当时选的是哪一个"（商品改名/下架后仍然看得见）。
    name: str = Field(default="", max_length=64)
    unit: str = Field(default="", max_length=16)
    #: 件数（与订单商品行的 `qty` 同一个口径）。
    qty: int = Field(default=1, ge=1, le=100_000)


class OrderTemplateCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    shipper_id: int | None = None
    origin_address: str = Field(default="", max_length=256)
    address: str = Field(default="", max_length=256)
    receiver_name: str = Field(default="", max_length=64)
    # 电话规则在 `app/core/phone.py`（空 = 没填）
    receiver_phone: OptionalContactPhone = Field(None, max_length=32)
    #: `null` = 不预设运费；`0` = 免运费（两件事，见模型文件头）
    freight_fee: str | None = Field(None, max_length=16)
    remark: str = Field(default="", max_length=256)
    lines: list[OrderTemplateLine] = Field(default_factory=list, max_length=MAX_LINES)


class OrderTemplateUpdate(BaseModel):
    """**部分更新**：只传要改的键，没传的后端不动。"""

    name: str | None = Field(None, min_length=1, max_length=64)
    shipper_id: int | None = None
    origin_address: str | None = Field(None, max_length=256)
    address: str | None = Field(None, max_length=256)
    receiver_name: str | None = Field(None, max_length=64)
    receiver_phone: OptionalContactPhone = Field(None, max_length=32)
    freight_fee: str | None = Field(None, max_length=16)
    remark: str | None = Field(None, max_length=256)
    lines: list[OrderTemplateLine] | None = Field(None, max_length=MAX_LINES)
    #: **显式清空货主**（改成"下单时再选"）。
    #: 为什么需要它：Android 的 JSON 配置是 `explicitNulls=false` —— `shipper_id: null`
    #: 会在客户端就被丢掉，于是"清空货主"这个操作**永远发不出去**，而界面看起来一切正常。
    #: 所以多给一个**客户端发得出来**的键（HTTP 直接打 `{"shipper_id": null}` 也照样认）。
    clear_shipper: bool = False


class OrderTemplateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    shipper_id: int | None = None
    #: 货主名（由端点补上；`shipper_id` 为空时也是空）
    shipper_name: str | None = None
    origin_address: str = ""
    address: str = ""
    receiver_name: str = ""
    receiver_phone: str = ""
    #: 字符串出参（两位小数）或 null（没预设）——与全项目金额出参同一套写法
    freight_fee: str | None = None
    remark: str = ""
    lines: list[OrderTemplateLine] = Field(default_factory=list)
    created_at: datetime

    @field_validator("lines", mode="before")
    @classmethod
    def _lines_never_none(cls, v: object) -> object:
        """JSON 列可能是 NULL（老库/裸 SQL）—— 归一到 `[]`，否则整个端点 500。"""
        if v is None:
            return []
        if isinstance(v, list):
            # 行里也可能缺键（历史数据），逐行给默认值，别让一条坏的把整张表打掉
            return [x if isinstance(x, dict) else {} for x in v]
        return []
