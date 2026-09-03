"""账本 V2（P0）：客户档案 / 司机应付明细 / 客户收款单 / 司机结算单 / 开销单 / 资金流水 / 车辆台账。"""

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import (
    CashFlowBizType,
    CashFlowDirection,
    DriverBillStatus,
    DriverBillType,
    ExpenseCategory,
    ReceiptSettleMode,
    SettlementStatus,
)


# ---------------- 客户档案 ----------------
class CustomerCreate(BaseModel):
    kind: str = "tmp"  # registered | tmp
    user_id: int | None = None
    name: str = Field(..., min_length=1, max_length=128)
    phone: str | None = Field(None, max_length=32)
    is_member: bool = False
    arrears_unit_id: int | None = None

    @model_validator(mode="after")
    def _tmp_need_phone_or_name(self) -> "CustomerCreate":
        if self.kind == "tmp" and not (self.phone or "").strip() and not self.name.strip():
            raise ValueError("散客需提供名称")
        return self


class CustomerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    kind: str
    user_id: int | None = None
    name: str
    phone: str | None = None
    is_member: bool = False
    arrears_unit_id: int | None = None
    created_at: datetime | None = None


class CustomerMergeBody(BaseModel):
    keep_id: int
    merge_ids: list[int] = Field(..., min_length=1)


# ---------------- 司机应付明细 ----------------
class DriverBillOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    driver_id: int
    bill_type: DriverBillType
    order_id: int | None = None
    month: str
    amount: Decimal
    status: DriverBillStatus
    settled_doc_id: int | None = None
    note: str = ""
    driver_name: str | None = None
    order_no: str | None = None


class DriverBillGenerateBody(BaseModel):
    driver_id: int | None = None      # 空=全部在职司机
    month: str = Field(..., description="YYYY-MM")
    bill_type: DriverBillType = DriverBillType.SALARY


# ---------------- 客户收款单 ----------------
class ReceiptItem(BaseModel):
    order_id: int


class ShipperReceiptCreate(BaseModel):
    customer_id: int = Field(..., description="customers.id（含散客）")
    amount: Decimal = Field(..., gt=0)
    method: str = Field("cash", pattern="^(cash|transfer|wechat|arrears_settle)$")
    received_at: date
    order_ids: list[int] = Field(default_factory=list, description="逐单核销绑定的订单，必填（itemized 默认）")
    settle_mode: ReceiptSettleMode = ReceiptSettleMode.ITEMIZED
    arrears_unit_id: int | None = None
    note: str = ""

    @model_validator(mode="after")
    def _itemized_needs_orders(self) -> "ShipperReceiptCreate":
        if self.settle_mode == ReceiptSettleMode.ITEMIZED and not self.order_ids:
            raise ValueError("逐单核销需绑定订单")
        return self


class ShipperReceiptOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    customer_id: int
    amount: Decimal
    method: str
    received_at: date
    order_ids: list | None = None
    settle_mode: ReceiptSettleMode
    arrears_unit_id: int | None = None
    invoiced: bool = False
    note: str = ""
    operator_id: int | None = None
    customer_name: str | None = None
    created_at: datetime | None = None


# ---------------- 司机结算单 ----------------
class DriverSettlementCreate(BaseModel):
    driver_id: int
    settle_type: DriverBillType = DriverBillType.PIECE
    month: str = Field(..., description="YYYY-MM；PIECE 按该月送达单，SALARY 按该月薪资单")
    amount: Decimal | None = Field(None, description="空=自动按范围内 OPEN 明细汇总")
    note: str = ""


class DriverSettlementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    driver_id: int
    settle_type: DriverBillType
    month: str
    period_from: date | None = None
    period_to: date | None = None
    amount: Decimal
    status: SettlementStatus
    order_ids: list | None = None
    paid_at: datetime | None = None
    method: str = ""
    operator_id: int | None = None
    note: str = ""
    driver_name: str | None = None
    created_at: datetime | None = None


class SettlementActionBody(BaseModel):
    action: str = Field(..., pattern="^(confirm|pay|cancel)$")
    method: str = Field("cash", pattern="^(cash|transfer|wechat|bank)$")
    paid_at: date | None = None


# ---------------- 开销单 ----------------
class ExpenseCreate(BaseModel):
    exp_date: date
    category: ExpenseCategory
    amount: Decimal = Field(..., gt=0)
    driver_id: int | None = None
    vehicle_id: int | None = None
    order_id: int | None = None
    note: str = ""


class ExpenseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    exp_date: date
    category: ExpenseCategory
    amount: Decimal
    driver_id: int | None = None
    vehicle_id: int | None = None
    order_id: int | None = None
    note: str = ""
    operator_id: int | None = None
    driver_name: str | None = None
    order_no: str | None = None
    created_at: datetime | None = None


# ---------------- 资金流水 ----------------
class CashFlowOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    flow_date: date
    direction: CashFlowDirection
    amount: Decimal
    party_type: str
    party_id: int | None = None
    party_name: str | None = None
    channel: str
    biz_type: CashFlowBizType
    order_id: int | None = None
    doc_id: int | None = None
    note: str = ""
    operator_id: int | None = None
    created_at: datetime | None = None


# ---------------- 车辆台账 ----------------
class VehicleCreate(BaseModel):
    plate_no: str = Field(..., min_length=1, max_length=16)
    vehicle_type: str = ""
    driver_id: int | None = None


class VehicleUpdate(BaseModel):
    plate_no: str | None = None
    vehicle_type: str | None = None
    driver_id: int | None = None
    is_active: bool | None = None


class VehicleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    plate_no: str
    vehicle_type: str
    driver_id: int | None = None
    is_active: bool = True
    driver_name: str | None = None
    created_at: datetime | None = None
