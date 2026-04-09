from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class AddressCreate(BaseModel):
    receiver_name: str = Field(default="", max_length=128)
    phone: str = Field(default="", max_length=32)
    detail_address: str = Field(default="", max_length=512)
    remark: str = Field(default="", max_length=256)
    is_default: bool = False
    address_lat: Decimal | None = None
    address_lng: Decimal | None = None


class AddressUpdate(BaseModel):
    receiver_name: str | None = Field(None, max_length=128)
    phone: str | None = Field(None, max_length=32)
    detail_address: str | None = Field(None, max_length=512)
    remark: str | None = Field(None, max_length=256)
    is_default: bool | None = None
    address_lat: Decimal | None = None
    address_lng: Decimal | None = None


class AddressOut(BaseModel):
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
    created_at: datetime


class ContactCreate(BaseModel):
    phone: str = Field(..., min_length=5, max_length=32)
    display_name: str = Field(default="", max_length=128)


class ContactOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    shipper_id: int
    phone: str
    display_name: str
    created_at: datetime
