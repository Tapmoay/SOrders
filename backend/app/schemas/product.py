import re
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _validate_hex_color(v: object) -> str | None:
    if v is None or v == "":
        return None
    s = str(v).strip()
    if not s:
        return None
    if not re.fullmatch(r"#[0-9A-Fa-f]{6}", s, flags=re.IGNORECASE):
        raise ValueError("名称颜色须为 #RRGGBB 格式，例如 #323233")
    return s.upper()


class ProductCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=256)
    default_unit_price: Decimal = Field(default=Decimal("0"))
    image_url: str | None = Field(None, max_length=512)
    name_color: str | None = Field(None, max_length=32)

    @field_validator("name_color", mode="before")
    @classmethod
    def name_color_ok(cls, v: object) -> str | None:
        return _validate_hex_color(v)


class ProductUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=256)
    default_unit_price: Decimal | None = None
    is_active: bool | None = None
    image_url: str | None = Field(None, max_length=512)
    name_color: str | None = Field(None, max_length=32)

    @field_validator("name_color", mode="before")
    @classmethod
    def name_color_ok(cls, v: object) -> str | None:
        return _validate_hex_color(v)


class ProductOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    name_color: str | None = None
    default_unit_price: Decimal
    is_active: bool
    image_url: str | None = None
