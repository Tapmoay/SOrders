from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class FreightTemplateBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    from_place: str = Field("", max_length=128)
    to_place: str = Field("", max_length=128)
    vehicle_type: str | None = Field(None, max_length=16)
    fee: Decimal = Field(Decimal("0"), ge=0)
    remark: str = Field("", max_length=2000)


class FreightTemplateCreate(FreightTemplateBase):
    pass


class FreightTemplateUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=128)
    from_place: str | None = Field(None, max_length=128)
    to_place: str | None = Field(None, max_length=128)
    vehicle_type: str | None = Field(None, max_length=16)
    fee: Decimal | None = Field(None, ge=0)
    remark: str | None = Field(None, max_length=2000)


class FreightTemplateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    from_place: str
    to_place: str
    vehicle_type: str | None
    fee: Decimal
    remark: str
    created_by: int | None
    created_at: datetime
