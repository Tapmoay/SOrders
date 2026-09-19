import re
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.money import MoneyInput
from app.schemas.text import MAX_SHORT_NAME


def _validate_hex_color(v: object) -> str | None:
    if v is None or v == "":
        return None
    s = str(v).strip()
    if not s:
        return None
    if not re.fullmatch(r"#[0-9A-Fa-f]{6}", s, flags=re.IGNORECASE):
        raise ValueError("名称颜色须为 #RRGGBB 格式，例如 #323233")
    return s.upper()


class ProductTier(MoneyInput):
    """多档批发价条目。"""

    label: str = Field(..., min_length=1, max_length=32)
    unit_price: Decimal = Field(..., ge=Decimal("0"))


class ProductCreate(MoneyInput):
    name: str = Field(..., min_length=1, max_length=256)
    # ⚠️ 价格/成本**必须 ≥ 0**（v3.39 探针实测：原来可以建出单价 -5 的商品，
    #    下单就得到负金额的订单行 → 账本入账负数、营业额为负，全程不报错）。
    #    这里与 tier_prices 一样用 ge=0（同一个 schema 里两种风格更糟）。
    default_unit_price: Decimal = Field(default=Decimal("0"), ge=0)
    cost_price: Decimal = Field(default=Decimal("0"), ge=0)
    image_url: str | None = Field(None, max_length=512)
    name_color: str | None = Field(None, max_length=32)
    tier_prices: list[ProductTier] = Field(default_factory=list)
    stock: int | None = Field(default=None, ge=0, description="初始库存（选填，仅创建时生效）")
    unit: str | None = Field(None, max_length=32, description="商品单位，如 件/箱/斤/桶（缺省 件）")
    # 分类（如 饮料/粮油/日化）：选品页左侧导航按它分组；留空 = 「未分类」（老数据都是这一档）
    category: str | None = Field(None, max_length=MAX_SHORT_NAME, description="商品分类，选品页左侧分组用")
    low_stock_alert: int | None = Field(None, ge=0, description="库存报警阈值：库存≤该值提醒（0=不报警）")

    @field_validator("name_color", mode="before")
    @classmethod
    def name_color_ok(cls, v: object) -> str | None:
        return _validate_hex_color(v)

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, v: str) -> str:
        # min_length=1 拦不住 "   "（三个空格也是一个合法字符串）：
        # 那种商品在列表里就是一行空白，点进去才知道是什么东西（v3.39 探针实测）。
        s = v.strip()
        if not s:
            raise ValueError("商品名不能为空或纯空格")
        return s


class ProductUpdate(MoneyInput):
    name: str | None = Field(None, min_length=1, max_length=256)
    default_unit_price: Decimal | None = Field(None, ge=0)
    cost_price: Decimal | None = Field(None, ge=0)
    is_active: bool | None = None
    image_url: str | None = Field(None, max_length=512)
    name_color: str | None = Field(None, max_length=32)
    tier_prices: list[ProductTier] | None = None
    unit: str | None = Field(None, max_length=32)
    category: str | None = Field(None, max_length=MAX_SHORT_NAME)
    low_stock_alert: int | None = Field(None, ge=0)

    @field_validator("name_color", mode="before")
    @classmethod
    def name_color_ok(cls, v: object) -> str | None:
        return _validate_hex_color(v)

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, v: str | None) -> str | None:
        if v is None:
            return None
        s = v.strip()
        if not s:
            raise ValueError("商品名不能为空或纯空格")
        return s


class ProductOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    @field_validator("tier_prices", mode="before")
    @classmethod
    def tier_prices_not_none(cls, v: object) -> object:
        return [] if v is None else v

    id: int
    name: str
    name_color: str | None = None
    default_unit_price: Decimal
    cost_price: Decimal = Decimal("0")
    is_active: bool
    image_url: str | None = None
    stock: int = 0
    tier_prices: list[ProductTier] = Field(default_factory=list)
    unit: str = "件"
    category: str = ""
    low_stock_alert: int = 0
