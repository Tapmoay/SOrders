import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.phone import ContactPhone, OptionalContactPhone
from app.models.enums import OrderStatus
from app.schemas.geo import GeoInput
from app.schemas.money import MoneyInput
from app.schemas.text import MAX_IMAGES, MAX_PHONE, MAX_SHORT_NAME, MAX_TEXT, Url


class OrderProductIn(MoneyInput):
    product_id: int | None = None
    product_name_snapshot: str = Field(..., min_length=1, max_length=256)
    quantity: int = Field(default=1, ge=1)
    unit_price: Decimal = Field(default=Decimal("0"), ge=0)
    line_total: Decimal = Field(default=Decimal("0"), ge=0)
    # 这一行的单位（件/箱/斤…）：选品弹窗里可以改（"数量后面是要有对应的单位的"）。
    # 留空 = 用商品库里的单位（`build_order_products` 兜底）。长度与列宽一致。
    unit: str = Field("", max_length=MAX_SHORT_NAME)


class OrderProductOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    order_id: int
    product_id: int | None
    product_name_snapshot: str
    quantity: int
    unit_price: Decimal | None = None
    line_total: Decimal | None = None
    # 下单时定格的单位；老数据为空串（客户端显示时按空处理，别编一个"件"出来）。
    #
    # ⚠️ `validation_alias` 不是装饰：模型列名是 `unit_snapshot`，出参名想叫 `unit`。
    #    `from_attributes` 只按**同名属性**取值，取不到就落默认值 —— 于是 `unit` 恒为空串、
    #    **不报任何错**，表现是"选品时明明选了 3 箱，订单详情里只剩 3"。
    #    （第一版就是这么写的，`model_validate` 实测返回 `unit=''` 才发现。）
    unit: str = Field("", validation_alias=AliasChoices("unit", "unit_snapshot"))
    damage_quantity: int = 0  # 送达货损数量（公司自担），0=无


class OrderProductCreate(MoneyInput):
    order_id: int
    product_id: int | None = None
    product_name_snapshot: str = Field(..., min_length=1, max_length=256)
    quantity: int = Field(default=1, ge=1)
    unit_price: Decimal = Field(default=Decimal("0"), ge=0)
    line_total: Decimal | None = Field(None, ge=0)
    unit: str = Field("", max_length=MAX_SHORT_NAME)


class OrderProductUpdate(MoneyInput):
    product_id: int | None = None
    product_name_snapshot: str | None = Field(None, min_length=1, max_length=256)
    quantity: int | None = Field(None, ge=1)
    unit_price: Decimal | None = Field(None, ge=0)
    line_total: Decimal | None = Field(None, ge=0)
    unit: str | None = Field(None, max_length=MAX_SHORT_NAME)


class OrderCreate(GeoInput):
    lines: list[OrderProductIn] = Field(..., min_length=1, max_length=10)
    order_date: date | None = None
    # 长度上限与**列宽**一致（`String(512)` / `String(32)`），备注类是 TEXT 用 MAX_TEXT。
    # 不加的话：本地 SQLite 照收 8000 字，生产 MySQL `Data too long`（模糊测试实测）。
    delivery_description: str = Field("", max_length=512)
    address_detail: str = Field("", max_length=512)
    address_lat: Decimal | None = None
    address_lng: Decimal | None = None
    # 联系电话：规则在 `app/core/phone.py`（去空格后 7~12 位数字，空 = 没填）。
    # 生产库这两列里真的有 `[嘿嘿] [刚刚好]` 这种值 —— 司机拿到单打不出去。
    contact_dongjia_phone: ContactPhone = Field("", max_length=MAX_PHONE)
    contact_boss_phone: ContactPhone = Field("", max_length=MAX_PHONE)
    # 收货人 / 下单人的**名称**（与上面两个电话一一对应）。上限与列宽一致（`String(64)`）——
    # 不给上限的话本地 SQLite 照收，生产 MySQL 会 `Data too long`（与备注同一类坑）。
    contact_dongjia_name: str = Field("", max_length=64)
    contact_boss_name: str = Field("", max_length=64)
    remark: str = Field("", max_length=MAX_TEXT)
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


class OrderUpdate(GeoInput):
    delivery_description: str | None = Field(None, max_length=512)
    address_detail: str | None = Field(None, max_length=512)
    address_lat: Decimal | None = None
    address_lng: Decimal | None = None
    # PATCH 语义：None = 不改这一项，所以这里用可选别名（它会放行 None）
    contact_dongjia_phone: OptionalContactPhone = Field(None, max_length=MAX_PHONE)
    contact_boss_phone: OptionalContactPhone = Field(None, max_length=MAX_PHONE)
    contact_dongjia_name: str | None = Field(None, max_length=64)
    contact_boss_name: str | None = Field(None, max_length=64)
    remark: str | None = Field(None, max_length=MAX_TEXT)
    internal_notes: str | None = Field(None, max_length=MAX_TEXT)


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
    # 导航信息来源：driver/dispatcher=到场补录；空=下单时就带坐标
    nav_source: str | None = None
    contact_dongjia_phone: str
    contact_boss_phone: str
    # 收货人 / 下单人的名称（老数据是空串 = 没记过名字，客户端按"没填"显示）
    contact_dongjia_name: str = ""
    contact_boss_name: str = ""
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
    # 这一单派单员单独定的计费参数（回显给界面，也让人看得出"这单和别人不一样"）
    driver_piece_amount: Decimal | None = None
    driver_commission_rate: Decimal | None = None
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
    deleted_at: datetime | None = None  # 软删除隔离时间（派单员可查，用户不可见）

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


class OrderFreightBody(MoneyInput):
    freight_fee: Decimal | None = Field(None, ge=0)


class OrderSplitBody(BaseModel):
    parts: list[int] = Field(..., min_length=2, max_length=5, description="各子单比例/份数（如 [1,1] 或 [150,150]，按比例拆分数量）")


class OrderAssignBody(MoneyInput):
    driver_id: int
    internal_note: str | None = Field(None, max_length=4000)
    freight_fee: Decimal | None = Field(None, ge=0)
    collect_cash: bool | None = None
    # 派单员对这一单单独定的计费参数（空 = 用司机挂着的规则里的值）
    # ⚠️ 这两个字段**故意不加 ge/le、也不进 MoneyInput 的容量检查**：越界会被 Pydantic 拦成
    #    422 + 英文结构体，而派单员/AI 要的是"这个司机没挂规则，逐单金额没有地方生效"
    #    这种能照着改的中文。范围与"能不能生效"只有一份判据：
    #    `driver_pay.override_problem`（同规则模板那一份的理由）。
    driver_piece_amount: Decimal | None = Field(None, description="这一单的司机金额（每单的钱不固定时用）")
    driver_commission_rate: Decimal | None = Field(None, description="这一单的提成比例（%）")


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
    # 送达照片：条数与单张长度都要有界（客户端相册多选也是 9 张）
    delivery_photo_urls: list[Url] = Field(default_factory=list, max_length=MAX_IMAGES)
    driver_remark: str = Field("", max_length=MAX_TEXT)
    # cash=现场收现金；arrears=挂账；None=按订单设置（勾选收取现金但未选择→挂账）
    # ⚠️ 取值限定成这两档：写死的字符串会让"收了现金"这种事实静默变成挂账
    payment: str | None = Field(None, pattern="^(cash|arrears)$")
    # 货损（选填，公司自担）：商品行级数量 + 订单备注；送达后自动记货损开销并冲回等量成本
    damage_items: list[DamageItem] = Field(default_factory=list, max_length=20)
    damage_note: str = Field("", max_length=MAX_TEXT)


class OrderRecallBody(BaseModel):
    reason: str = Field(..., min_length=1, max_length=1024)


class DeliveryPhotoUploadOut(BaseModel):
    urls: list[str]


class DriverNoteBody(BaseModel):
    note: str = Field(..., min_length=1, max_length=4000)