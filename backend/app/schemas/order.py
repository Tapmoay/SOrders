import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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
    unit_price: Decimal | None = None
    line_total: Decimal | None = None
    damage_quantity: int = 0  # 送达货损数量（公司自担），0=无


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
    address_image_url: str | None = None
    created_at: datetime
    dispatched_at: datetime | None
    driver_acknowledged_at: datetime | None = None
    delivered_at: datetime | None = None
    cancelled_at: datetime | None = None
    order_products: list[OrderProductOut] = []
    driver_phone: str | None = None
    freight_fee: Decimal | None = None
    freight_visible: bool = False
    driver_billing_mode: str | None = None
    collect_cash: bool = False  # PIECE=按单计费(挂车) SALARY=固定工资
    parent_order_id: int | None = None
    driver_name: str | None = None
    shipper_name: str | None = None
    is_new_for_driver: bool = False
    expected_deliver_before: datetime | None = None
    is_exception: bool = False
    exception_reason: str = ""
    exception_resolution: str = ""
    payment_method: str = "cash"
    paid: bool = False
    arrears_unit_id: int | None = None
    arrears_unit_name: str = ""
    damage_note: str = ""  # 送达货损备注（公司自担）
    image_urls: list[str] = []  # 收货地址参考图（多图，JSON 数组）

    @field_validator("image_urls", mode="before")
    @classmethod
    def _parse_order_image_urls(cls, v: Any) -> list[str]:
        """image_urls 列（JSON 字符串/列表/None）→ URL 列表；无图时回退 address_image_url。"""
        if v is None or v == "":
            return []
        if isinstance(v, list):
            return [x for x in v if isinstance(x, str) and x]
        if isinstance(v, str):
            try:
                arr = json.loads(v)
            except Exception:
                return [v] if v else []
            return [x for x in arr if isinstance(x, str) and x] if isinstance(arr, list) else ([v] if v else [])
        return []


class OrderChargeBody(BaseModel):
    """派单员：把订单记到挂账单位名下。"""

    arrears_unit_id: int


class OrderExceptionBody(BaseModel):
    is_exception: bool = True
    exception_reason: str = Field(default="", max_length=4000)
    exception_resolution: str = Field(default="", max_length=4000)
    expected_deliver_before: datetime | None = None


class OrderFreightBody(BaseModel):
    freight_fee: Decimal | None = Field(None, ge=0)


class OrderSplitBody(BaseModel):
    parts: list[int] = Field(..., min_length=2, max_length=5, description="各子单比例/份数（如 [1,1] 或 [150,150]，按比例拆分数量）")


class OrderAssignBody(BaseModel):
    driver_id: int
    internal_note: str | None = Field(None, max_length=4000)
    freight_fee: Decimal | None = Field(None, ge=0)
    collect_cash: bool | None = None


class OrderBatchAssignBody(BaseModel):
    order_ids: list[int] = Field(..., min_length=1, max_length=100)
    driver_id: int
    internal_note: str | None = Field(None, max_length=4000)
    collect_cash: bool | None = None


class BatchAssignResultItem(BaseModel):
    order_id: int
    success: bool
    detail: str | None = None


class OrderBatchAssignOut(BaseModel):
    results: list[BatchAssignResultItem]


class DamageItem(BaseModel):
    order_product_id: int
    quantity: int = Field(..., ge=0, description="货损数量（≤该行数量，0=无货损）")


class OrderCompleteBody(BaseModel):
    delivery_photo_urls: list[str] = Field(default_factory=list)
    driver_remark: str = ""
    # cash=现场收现金；arrears=挂账；None=按订单设置（勾选收取现金但未选择→挂账）
    payment: str | None = None
    # 货损（选填，公司自担）：商品行级数量 + 订单备注；送达后自动记货损开销并冲回等量成本
    damage_items: list[DamageItem] = Field(default_factory=list)
    damage_note: str = ""


class OrderRecallBody(BaseModel):
    reason: str = Field(..., min_length=1, max_length=1024)


class DeliveryPhotoUploadOut(BaseModel):
    urls: list[str]


class DriverNoteBody(BaseModel):
    note: str = Field(..., min_length=1, max_length=4000)