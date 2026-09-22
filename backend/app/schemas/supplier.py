"""供应商 / 厂商档案 + 应付单 + 付款的入参与出参（2026-09-22 用户要求）。

三组模型对应用户口述的三件事：**档案**（"跟客户一个量级"）、**应付单**（欠了人家多少）、
**付款**（分次付款，每一笔都是一行资金流水）。

⚠️ 三条不能省的规矩（都在别处踩过）：
1. **金额走 `MoneyInput` + `Decimal`**：金额是钱，不许用 `float`，也不许在 schema 里各写一遍
   范围检查（越界要出中文提示，见 `schemas/money.py`）。
2. **出参的 `amount` / `paid` / `unpaid` 是字符串（两位小数）**：与全项目金额出参同一套写法
   （`order_money.q2`），客户端不做四舍五入。
3. **`unpaid` 由服务端算**（`services/supplier_service.py` 一处口径）——
   出参里带着它，是为了让客户端**永远不需要自己减**（客户端各减一遍 = 又一个口径）。
"""
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.core.phone import ContactPhone, OptionalContactPhone
from app.schemas.money import MoneyInput

#: 应付款的用途分类：**建议值，不是枚举**（用户可以写别的，比如「叉车租金」）。
#: 与 `expenses.category` 同一个理由（2026-09-20 那次教训）：写死成枚举之后，
#: 用户新加一个分类会在**写库那一刻**一声不响地存不进去。
SUPPLIER_PAYABLE_CATEGORIES = ("货款", "设备采购", "运费", "尾款", "其他")


# ---------------- 供应商 / 厂商档案 ----------------
class SupplierCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    contact_name: str = Field("", max_length=32)
    # 电话：规则在 `app/core/phone.py`（去空格后 7~12 位数字，空 = 没填）。
    # ⚠️ 座机要写成 `07521234567`（不带横杠）—— 规则是"打不通的号码不许存"，
    #    带横杠的号码在拨号/导出里都不是号码，这一点与客户档案/挂账单位一致。
    phone: ContactPhone = Field("", max_length=32)
    address: str = Field("", max_length=128)
    remark: str = Field("", max_length=256)


class SupplierUpdate(BaseModel):
    """**部分更新**：只传要改的键，没传的后端不动。"""

    name: str | None = Field(None, min_length=1, max_length=64)
    contact_name: str | None = Field(None, max_length=32)
    # None = 不改这一项（可选别名会放行 None）；空串 = 清掉
    phone: OptionalContactPhone = Field(None, max_length=32)
    address: str | None = Field(None, max_length=128)
    remark: str | None = Field(None, max_length=256)


class SupplierOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    contact_name: str = ""
    phone: str = ""
    address: str = ""
    remark: str = ""
    #: 三个数**都由服务端算**（欠款的口径只有一处）：应付合计 / 已付合计 / 还欠
    payable_total: str = "0.00"
    paid_total: str = "0.00"
    unpaid_total: str = "0.00"
    #: 还欠着的单据张数（列表卡片上要显示「2 笔未结清」）
    open_payables: int = 0
    created_at: datetime


# ---------------- 应付单 ----------------
class SupplierPayableCreate(MoneyInput):
    supplier_id: int
    #: 这笔应付是什么（「10 月货款」「采购叉车」）—— 对账全靠它
    title: str = Field(..., min_length=1, max_length=64)
    category: str = Field("货款", max_length=32)
    #: 应付**总额**（>0）。已付不在这里，从流水算。
    amount: Decimal = Field(..., gt=0)
    doc_date: date
    remark: str = Field("", max_length=256)


class SupplierPayableUpdate(MoneyInput):
    title: str | None = Field(None, min_length=1, max_length=64)
    category: str | None = Field(None, max_length=32)
    #: ⚠️ 改金额：只允许改到「不小于已付」——把一张已付 500 的单改成 300，
    #:    欠款会变成负数（界面上没人读得对），而且那是把已经付过的钱说成没付。
    amount: Decimal | None = Field(None, gt=0)
    doc_date: date | None = None
    remark: str | None = Field(None, max_length=256)


class SupplierPayableOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    supplier_id: int
    supplier_name: str = ""
    title: str
    category: str = "货款"
    amount: str = "0.00"
    doc_date: date
    remark: str = ""
    #: 已付 / 还差（服务端算，见文件头第 3 条）
    paid: str = "0.00"
    unpaid: str = "0.00"
    #: 付过几次（「分 2 次付」在列表上要看得见）
    payment_count: int = 0
    created_at: datetime


# ---------------- 付款（就是一行资金流水） ----------------
class SupplierPaymentCreate(MoneyInput):
    #: 付款金额：`0 < amount <= 这张单还差的`。"超过还差"拒绝，见 `services/supplier_service.py`。
    amount: Decimal = Field(..., gt=0)
    pay_date: date
    #: 付款方式（与司机结算单同一套取值）
    channel: str = Field("cash", pattern="^(cash|transfer|wechat|bank)$")
    remark: str = Field("", max_length=256)


class SupplierPaymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    supplier_id: int
    supplier_name: str = ""
    #: 这张付款挂在哪张应付单上（**必填**：系统不允许"没有单据的付款"）
    payable_id: int
    payable_title: str = ""
    amount: str = "0.00"
    pay_date: date
    channel: str = "cash"
    remark: str = ""
    created_at: datetime
