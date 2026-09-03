from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class PriceRuleBatchBody(BaseModel):
    """批量调价：多批发商 × 多商品，统一一套价格逻辑。"""

    shipper_ids: list[int] = Field(default_factory=list, description="空=全部批发商")
    product_ids: list[int] = Field(default_factory=list, description="空=全部商品")
    mode: Literal["fixed", "tier", "percent"] = "fixed"
    value: Decimal | None = Field(None, ge=Decimal("0"), description="fixed=统一单价；percent=默认售价的百分比(如95=95%)")
    tier_index: int | None = Field(None, ge=0, description="tier=应用商品自身第几档批发价")


class PriceRuleBatchOut(BaseModel):
    count: int


class PriceRuleCreate(BaseModel):
    shipper_id: int
    product_id: int
    special_unit_price: Decimal = Field(..., ge=Decimal("0"))


class PriceRuleUpdate(BaseModel):
    special_unit_price: Decimal | None = Field(None, ge=Decimal("0"))
    shipper_id: int | None = None


class PriceRuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    shipper_id: int
    product_id: int
    special_unit_price: Decimal
    shipper_name: str | None = None
    product_name: str | None = None
