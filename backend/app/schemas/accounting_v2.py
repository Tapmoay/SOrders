"""账本 V2（P0）：客户档案 / 司机应付明细 / 客户收款单 / 司机结算单 / 开销单 / 资金流水 / 车辆台账。"""

import re
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.enums import (
    CashFlowBizType,
    CashFlowDirection,
    CustomerKind,
    DriverBillStatus,
    DriverBillType,
    ExpenseCategory,
    ReceiptSettleMode,
    SettlementStatus,
)
from app.schemas.money import MoneyInput

#: 归属月份只接受 `YYYY-MM`。
#:
#: ⚠️ 为什么必须校验（2026-09-18 实测）：`driver_bills` 的**列表**查询参数带着
#: `pattern=^\d{4}-\d{2}$`，而**生成**接口的 `month` 原来是一个自由字符串。
#: 于是一次 `POST /driver-bills/generate {"month": "fuzz-xxx"}` 会造出一批
#: "月份不是月份"的工资单：任何界面按月份都查不到它们，结算单也永远收不进它们
#: （结算按 month 取 OPEN 明细）——**生成了、但结不掉的幽灵工资单**。
#: 实测一次模糊测试就造出 70 张、合计 34.5 万。
MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
MONTH_TIP = "月份要写成 YYYY-MM（例如 2026-09）"


def validate_month(v: str) -> str:
    """月份格式校验：报错必须是**中文**且带正确写法（英文 422 用户看不懂）。

    ⚠️ 接收的是**原始输入**（`mode="before"`）：写成 `mode="after"` 时，`month=202609`
    这种数字会先被 Pydantic 拦成 `string_type`（英文），用户看不到下面这句中文提示。
    """
    s = str(v).strip() if v is not None else ""
    if not MONTH_RE.match(s):
        raise ValueError(MONTH_TIP)
    return s


# ---------------- 客户档案 ----------------
class CustomerCreate(MoneyInput):
    #: `registered`（有账号的货主）/ `tmp`（散客）。⚠️ 原来是自由字符串：
    #: 模糊测试把 8000 个字符塞进 kind 也是 200，而列宽是 String(12)——生产 MySQL
    #: 直接 Data too long。更要紧的是**未知取值会被当成临客**（`accounting_service`
    #: 按 kind 分流：registered→按 user_id，其余→按名称），错得无声无息。
    kind: CustomerKind = CustomerKind.TMP
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
    # v3.36：这一单是按哪份计费规则算的、两件各多少（账单页把账摆开给人看，不再只给一个总数）
    rule_id: int | None = None
    rule_name: str = ""
    piece_amount: Decimal | None = None
    commission_amount: Decimal | None = None


class DriverBillGenerateBody(BaseModel):
    driver_id: int | None = None      # 空=全部在职司机
    # 长度 7 与列宽 String(7) 一致；格式另有一份中文判据（validate_month）
    month: str = Field(..., max_length=7, description="YYYY-MM")
    bill_type: DriverBillType = DriverBillType.SALARY

    @field_validator("month", mode="before")
    @classmethod
    def _month(cls, v: str) -> str:
        return validate_month(v)


# ---------------- 客户收款单 ----------------
class ReceiptItem(BaseModel):
    order_id: int


class ShipperReceiptCreate(MoneyInput):
    customer_id: int = Field(..., description="customers.id（含散客）")
    amount: Decimal = Field(..., gt=0)
    method: str = Field("cash", pattern="^(cash|transfer|wechat|arrears_settle)$")
    received_at: date
    order_ids: list[int] = Field(default_factory=list, description="逐单核销绑定的订单，必填（itemized 默认）")
    settle_mode: ReceiptSettleMode = ReceiptSettleMode.ITEMIZED
    arrears_unit_id: int | None = None
    note: str = Field("", max_length=256)

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
class DriverSettlementCreate(MoneyInput):
    driver_id: int
    settle_type: DriverBillType = DriverBillType.PIECE
    month: str = Field(..., max_length=7, description="YYYY-MM；PIECE 按该月送达单，SALARY 按该月薪资单")
    amount: Decimal | None = Field(None, description="空=自动按范围内 OPEN 明细汇总")
    note: str = Field("", max_length=256)

    @field_validator("month", mode="before")
    @classmethod
    def _month(cls, v: str) -> str:
        return validate_month(v)


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
class ExpenseCreate(MoneyInput):
    exp_date: date
    category: ExpenseCategory
    amount: Decimal = Field(..., gt=0)
    driver_id: int | None = None
    vehicle_id: int | None = None
    order_id: int | None = None
    note: str = Field("", max_length=256)


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
    vehicle_type: str = Field("", max_length=16)
    driver_id: int | None = None


class VehicleUpdate(BaseModel):
    """改车辆：**只传要改的键**，没传的后端不动。

    ⚠️ `driver_id` 有两种含义，靠 `model_fields_set` 区分（v3.44）：
    **没传这个键** = 不动司机；**显式传 `null`** = 解绑。
    以前两种都走 `is not None`，于是"解绑"这件事根本没有表达方式。
    """

    plate_no: str | None = Field(None, max_length=16)
    vehicle_type: str | None = Field(None, max_length=16)
    driver_id: int | None = None
    is_active: bool | None = None


class VehicleDriverSet(BaseModel):
    """绑司机 / 解绑：`driver_id` **缺省或 null 都 = 解绑**。

    形状照抄 `DriverBillingRuleAttachBody`（那边 `rule_id=null` = 解挂）——
    因为客户端（安卓 `explicitNulls = false`）发不出"显式 null"，
    只能把"没带这个键"本身定义成解绑。
    """

    driver_id: int | None = None


class VehicleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    plate_no: str
    vehicle_type: str
    driver_id: int | None = None
    is_active: bool = True
    driver_name: str | None = None
    created_at: datetime | None = None
