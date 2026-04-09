from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


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
