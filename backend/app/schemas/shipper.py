from datetime import datetime
from decimal import Decimal
from typing import Any
import json

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.phone import ContactPhone, OptionalContactPhone
from app.schemas.geo import GeoInput
from app.schemas.text import MAX_IMAGES, MAX_URL, Url


def _parse_image_urls(value: Any) -> list[str]:
    """把 image_urls 列（JSON 字符串 / 列表 / 单个 URL）解析为 URL 列表。"""
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return []
        try:
            parsed = json.loads(value)
        except ValueError:
            return [value]
        if isinstance(parsed, list):
            return [x for x in parsed if isinstance(x, str) and x.strip()]
        return []
    if isinstance(value, list):
        return [x for x in value if isinstance(x, str) and x.strip()]
    return []


class _ImageUrlsMixin(BaseModel):
    """Out 响应：image_urls 与兼容字段 image_url（= 首图）合并输出。"""

    image_urls: list[str] = []
    image_url: str | None = None

    @field_validator("image_urls", mode="before")
    @classmethod
    def _parse(cls, v: Any) -> list[str]:
        return _parse_image_urls(v)

    @model_validator(mode="before")
    @classmethod
    def _merge_legacy(cls, data: Any) -> Any:
        if isinstance(data, dict):
            raw = data.get("image_urls")
            legacy = data.get("image_url")
        else:
            raw = getattr(data, "image_urls", None)
            legacy = getattr(data, "image_url", None)
        urls = _parse_image_urls(raw)
        if legacy and legacy not in urls:
            urls.insert(0, legacy)
        if isinstance(data, dict):
            out = dict(data)
        else:
            out = {c.name: getattr(data, c.name, None) for c in data.__table__.columns}
        out["image_urls"] = urls
        out["image_url"] = urls[0] if urls else None
        return out


class AddressCreate(GeoInput):
    receiver_name: str = Field(default="", max_length=128)
    # 联系电话：规则在 `app/core/phone.py`（去空格后 7~12 位数字，空 = 没填）
    phone: ContactPhone = Field(default="", max_length=32)
    detail_address: str = Field(default="", max_length=512)
    remark: str = Field(default="", max_length=256)
    is_default: bool = False
    address_lat: Decimal | None = None
    address_lng: Decimal | None = None
    origin_address: str | None = Field(None, max_length=512)
    origin_lat: Decimal | None = None
    origin_lng: Decimal | None = None
    #: 自定义分类（"" = 未分类）：与 `LocationCreate.category` / `ContactCreate.category`
    #  **逐字同形**（`String(32)` 那一格），归属是自由文本、顺序归 `RouteCategory` 名册管。
    category: str = Field(default="", max_length=32)
    # 多图：**条数与单张长度都要有界**（列是 TEXT(JSON)，不设上限就能塞进任意多张长 URL）
    image_urls: list[Url] = Field(default_factory=list, max_length=MAX_IMAGES)
    # 旧客户端兼容：单图
    image_url: str | None = Field(None, max_length=MAX_URL)


class AddressUpdate(GeoInput):
    receiver_name: str | None = Field(None, max_length=128)
    # None = 不改这一项（可选别名会放行 None）
    phone: OptionalContactPhone = Field(None, max_length=32)
    detail_address: str | None = Field(None, max_length=512)
    remark: str | None = Field(None, max_length=256)
    is_default: bool | None = None
    address_lat: Decimal | None = None
    address_lng: Decimal | None = None
    origin_address: str | None = Field(None, max_length=512)
    origin_lat: Decimal | None = None
    origin_lng: Decimal | None = None
    #: 自定义分类：None = 不改这一项，"" = 挪回未分类（与 `LocationUpdate.category` 同一条）。
    category: str | None = Field(None, max_length=32)
    # None = 不修改；[] = 清空
    image_urls: list[Url] | None = Field(None, max_length=MAX_IMAGES)
    # 旧客户端兼容：单图
    image_url: str | None = Field(None, max_length=MAX_URL)


class AddressOut(_ImageUrlsMixin):
    model_config = ConfigDict(from_attributes=True)

    id: int
    shipper_id: int
    receiver_name: str
    phone: str
    detail_address: str
    remark: str
    is_default: bool
    address_lat: Decimal | None
    address_lng: Decimal | None
    origin_address: str | None = None
    origin_lat: Decimal | None = None
    origin_lng: Decimal | None = None
    #: 自定义分类（"" = 未分类）。下发它，列表那一栏才能按分类筛。
    category: str = ""
    created_at: datetime


class LocationCreate(GeoInput):
    name: str = Field(default="", max_length=128)
    detail_address: str = Field(default="", max_length=512)
    remark: str = Field(default="", max_length=256)
    address_lat: Decimal | None = None
    address_lng: Decimal | None = None
    #: 自定义分类（空 = 未分类）。名册里没有这个名字时**自动补进去**（顺手建分类）。
    category: str = Field(default="", max_length=32)
    #: 是不是仓库。**只有派单员**能置 true（见 api/v1/shipper.py）；货主传 true 会被忽略并提示。
    is_warehouse: bool = False
    #: 这个地点默认的联系人（收货人）。用户 2026-09-24：「**可以通过地点来绑定联系人**…
    #: 选择地点之后，自动填入对应的联系人」。
    #: ⚠️ 与线路（[AddressCreate].receiver_name / phone）**同一口径**：存快照串、不存外键；
    #:   电话走 `app/core/phone.py` 的**同一条**规则（7~12 位数字），不在这里另写一遍。
    contact_name: str = Field(default="", max_length=128)
    contact_phone: ContactPhone = Field(default="", max_length=32)
    image_urls: list[Url] = Field(default_factory=list, max_length=MAX_IMAGES)
    # 旧客户端兼容：单图
    image_url: str | None = Field(None, max_length=MAX_URL)


class LocationUpdate(GeoInput):
    name: str | None = Field(None, max_length=128)
    detail_address: str | None = Field(None, max_length=512)
    remark: str | None = Field(None, max_length=256)
    address_lat: Decimal | None = None
    address_lng: Decimal | None = None
    #: None = 不改；"" = 清成未分类
    category: str | None = Field(None, max_length=32)
    #: None = 不改（只有派单员能改）
    is_warehouse: bool | None = None
    #: None = 不改；"" = 解绑（与地址/线路那套 PATCH 语义一致）
    contact_name: str | None = Field(None, max_length=128)
    contact_phone: OptionalContactPhone = Field(None, max_length=32)
    # None = 不修改；[] = 清空
    image_urls: list[Url] | None = Field(None, max_length=MAX_IMAGES)
    # 旧客户端兼容：单图
    image_url: str | None = Field(None, max_length=MAX_URL)


class LocationOut(_ImageUrlsMixin):
    model_config = ConfigDict(from_attributes=True)

    id: int
    shipper_id: int
    name: str
    detail_address: str
    remark: str
    address_lat: Decimal | None
    address_lng: Decimal | None
    #: 自定义分类（"" = 未分类）+ 是不是仓库。两个都要下发：下单页的地址库要按分类分栏、
    #  还要在行上标出"这是我的仓"。
    category: str = ""
    is_warehouse: bool = False
    #: 这个地点绑定的联系人（收货人）：空串 = 没绑。下单页选中这个地点时按它回填收货人两栏。
    contact_name: str = ""
    contact_phone: str = ""
    created_at: datetime


class LocationImageOut(BaseModel):
    url: str


class ContactCreate(BaseModel):
    # 原来只写 `min_length=5` —— 5 位的"电话"实际上打不出去（生产库那条 `[222]` 就是这么进来的）。
    # 现在的下限由 `app/core/phone.py` 的规则给（7 位），不再另写一个更松的数字。
    # CHG-0010：**选填**了（用户原话「新建联系人的时候不需要必填手机号」）—— 默认空串，
    # `validate_contact_phone` 对空串放行；写成 NULL 还是空串由 api/v1/shipper.py 一处决定。
    phone: ContactPhone = Field(default="", max_length=32)
    display_name: str = Field(default="", max_length=128)
    #: 自定义分类（空 = 未分类）。名册里没有这个名字时**自动补进去**（顺手建分类）——
    #  FEAT-0007，与 `LocationCreate.category` 同一个口径。
    category: str = Field(default="", max_length=32)


class ContactUpdate(BaseModel):
    # None = 不改这一项（可选别名会放行 None）
    phone: OptionalContactPhone = Field(None, max_length=32)
    display_name: str | None = Field(None, max_length=128)
    #: None = 不改；"" = 清成未分类（与地点那一格同一条 PATCH 语义）
    category: str | None = Field(None, max_length=32)


class ContactOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    shipper_id: int
    phone: str
    display_name: str
    #: 自定义分类（"" = 未分类）：联系人列表左侧那一列按它分栏 —— FEAT-0007。
    category: str = ""
    created_at: datetime

    @field_validator("phone", mode="before")
    @classmethod
    def _blank_phone_out(cls, v: Any) -> Any:
        """库里"没填手机号"存的是 NULL（见 models/shipper.py）；出参一律归一成空串。

        ⛔ 不改成 `phone: str | None`：客户端的 `ContactDto.phone` 是非空 `String`，
        Gson 把 null 塞进去会得到字面量 "null"（比空串更糟，且没人会去判它）。
        """
        return "" if v is None else v
