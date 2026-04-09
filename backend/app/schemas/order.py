from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import OrderStatus


class OrderProductIn(BaseModel):
    product_id: int | None = None
    product_name_snapshot: str = Field(..., min_length=1, max_length=256)
    quantity: int = Field(default=1, ge=1)
    unit_price: Decimal = Field(default=Decimal("0"))
    line_total: Decimal = Field(default=Decimal("0"))


class OrderProductOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    order_id: int
    product_id: int | None
    product_name_snapshot: str
    quantity: int
    unit_price: Decimal
    line_total: Decimal


class OrderProductCreate(BaseModel):
    order_id: int
    product_id: int | None = None
    product_name_snapshot: str = Field(..., min_length=1, max_length=256)
    quantity: int = Field(default=1, ge=1)
    unit_price: Decimal = Field(default=Decimal("0"))
    line_total: Decimal | None = Field(default=None)


class OrderProductUpdate(BaseModel):
    product_id: int | None = None
    product_name_snapshot: str | None = Field(None, min_length=1, max_length=256)
    quantity: int | None = Field(None, ge=1)
    unit_price: Decimal | None = None
    line_total: Decimal | None = None


class OrderCreate(BaseModel):
    lines: list[OrderProductIn] = Field(..., min_length=1, max_length=10)
    order_date: date | None = None
    delivery_description: str = ""
    address_detail: str = ""
    address_lat: Decimal | None = None
    address_lng: Decimal | None = None
    contact_dongjia_phone: str = ""
    contact_boss_phone: str = ""
    remark: str = ""
    shipper_id: int | None = Field(
        default=None,
        description="派单员代下单时可指定归属货主；不指定则订单暂无货主，可后续再关联。货主本人下单勿传。",
    )
    temp_shipper_name: str | None = Field(
        default=None,
        max_length=128,
        description="派单员代下单：临时货主称呼（无登录账号）；与 shipper_id 互斥。",
    )

    @model_validator(mode="after")
    def _shipper_xor_temp(self) -> "OrderCreate":
        sid = self.shipper_id
        tn = (self.temp_shipper_name or "").strip()
        if sid is not None and tn:
            raise ValueError("不能同时指定货主账号与临时货主名称")
        if tn:
            object.__setattr__(self, "temp_shipper_name", tn)
        else:
            object.__setattr__(self, "temp_shipper_name", None)
        return self


class OrderUpdate(BaseModel):
    delivery_description: str | None = None
    address_detail: str | None = None
    address_lat: Decimal | None = None
    address_lng: Decimal | None = None
    contact_dongjia_phone: str | None = None
    contact_boss_phone: str | None = None
    remark: str | None = None
    internal_notes: str | None = None


class OrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    order_no: str
    status: OrderStatus
    shipper_id: int | None = None
    temp_shipper_name: str | None = None
    driver_id: int | None
    order_date: date
    delivery_description: str
    address_detail: str
    address_lat: Decimal | None = None
    address_lng: Decimal | None = None
    contact_dongjia_phone: str
    contact_boss_phone: str
    remark: str
    internal_notes: str
    driver_remark: str
    delivery_photo_urls: list[Any] | None
    created_at: datetime
    dispatched_at: datetime | None
    driver_acknowledged_at: datetime | None = None
    delivered_at: datetime | None = None
    order_products: list[OrderProductOut] = []
    driver_phone: str | None = None
    driver_name: str | None = None
    shipper_name: str | None = None
    is_new_for_driver: bool = False
    expected_deliver_before: datetime | None = None
    is_exception: bool = False
    exception_reason: str = ""
    exception_resolution: str = ""


class OrderExceptionBody(BaseModel):
    is_exception: bool = True
    exception_reason: str = Field(default="", max_length=4000)
    exception_resolution: str = Field(default="", max_length=4000)
    expected_deliver_before: datetime | None = None


class OrderAssignBody(BaseModel):
    driver_id: int
    internal_note: str | None = Field(None, max_length=4000)


class OrderBatchAssignBody(BaseModel):
    order_ids: list[int] = Field(..., min_length=1, max_length=100)
    driver_id: int
    internal_note: str | None = Field(None, max_length=4000)


class BatchAssignResultItem(BaseModel):
    order_id: int
    success: bool
    detail: str | None = None


class OrderBatchAssignOut(BaseModel):
    results: list[BatchAssignResultItem]


class OrderCompleteBody(BaseModel):
    delivery_photo_urls: list[str] = Field(..., min_length=1)
    driver_remark: str = ""


class OrderRecallBody(BaseModel):
    reason: str = Field(..., min_length=1, max_length=1024)


class DeliveryPhotoUploadOut(BaseModel):
    urls: list[str]


class DriverNoteBody(BaseModel):
    note: str = Field(..., min_length=1, max_length=4000)
