from datetime import datetime
from decimal import Decimal
from typing import Any
import json

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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
    phone: str = Field(default="", max_length=32)
    detail_address: str = Field(default="", max_length=512)
    remark: str = Field(default="", max_length=256)
    is_default: bool = False
    address_lat: Decimal | None = None
    address_lng: Decimal | None = None
    origin_address: str | None = Field(None, max_length=512)
    origin_lat: Decimal | None = None
    origin_lng: Decimal | None = None
    # 多图：**条数与单张长度都要有界**（列是 TEXT(JSON)，不设上限就能塞进任意多张长 URL）
    image_urls: list[Url] = Field(default_factory=list, max_length=MAX_IMAGES)
    # 旧客户端兼容：单图
    image_url: str | None = Field(None, max_length=MAX_URL)


class AddressUpdate(GeoInput):
    receiver_name: str | None = Field(None, max_length=128)
    phone: str | None = Field(None, max_length=32)
    detail_address: str | None = Field(None, max_length=512)
    remark: str | None = Field(None, max_length=256)
    is_default: bool | None = None
    address_lat: Decimal | None = None
    address_lng: Decimal | None = None
    origin_address: str | None = Field(None, max_length=512)
    origin_lat: Decimal | None = None
    origin_lng: Decimal | None = None
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
    created_at: datetime


class LocationCreate(GeoInput):
    name: str = Field(default="", max_length=128)
    detail_address: str = Field(default="", max_length=512)
    remark: str = Field(default="", max_length=256)
    address_lat: Decimal | None = None
    address_lng: Decimal | None = None
    image_urls: list[Url] = Field(default_factory=list, max_length=MAX_IMAGES)
    # 旧客户端兼容：单图
    image_url: str | None = Field(None, max_length=MAX_URL)


class LocationUpdate(GeoInput):
    name: str | None = Field(None, max_length=128)
    detail_address: str | None = Field(None, max_length=512)
    remark: str | None = Field(None, max_length=256)
    address_lat: Decimal | None = None
    address_lng: Decimal | None = None
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
    created_at: datetime


class LocationImageOut(BaseModel):
    url: str


class ContactCreate(BaseModel):
    phone: str = Field(..., min_length=5, max_length=32)
    display_name: str = Field(default="", max_length=128)


class ContactUpdate(BaseModel):
    phone: str | None = Field(None, min_length=5, max_length=32)
    display_name: str | None = Field(None, max_length=128)


class ContactOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    shipper_id: int
    phone: str
    display_name: str
    created_at: datetime
