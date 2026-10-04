"""发票台账的入参 / 出参（FEAT-0014 税账）。

## 三条形状约定

1. **金额一律 `Decimal` 入、`Decimal` 出**：入参走 `MoneyInput`（超范围给中文 400，见
   `app/schemas/money.py`），出参也是 `Decimal` —— 两位小数的格式化只有端点层
   一处（`api/v1/invoices.py::_money`），schema 不做格式化，模型不认字符串。
2. **方向只在建票时定**：`direction` ⛔ 不在 `InvoiceUpdate` 里 —— 销项票不能改成进项票，
   要换方向就作废重开（判据两边都钉这条）。
3. **`tax_rate` 与 `tax_amount` 同生同灭**：要么都填、要么都不填（未税票）；
   只填税率时税额由服务层算（`tax_service.tax_of_amount`），填了税额就按填的算
   （票面税额与算出来的差一分钱的现实存在）。
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field

from app.schemas.money import MoneyInput


class InvoiceCreate(MoneyInput):
    """登记一张票（进项 / 销项共用）。"""

    direction: str = Field(..., pattern="^(OUTPUT|INPUT)$", description="OUTPUT=销项，INPUT=进项")
    invoice_no: str = Field("", max_length=64, description="票号；留空 = 票还没拿到")
    invoice_date: date = Field(..., description="开票日期（业务当地日期，税期按它算）")
    amount: Decimal = Field(..., gt=0, description="价税合计（元）")
    tax_rate: Decimal | None = Field(
        None, ge=0, le=100, description="税率（百分数，3.00 = 3%）；不填 = 未税，不进税汇"
    )
    tax_amount: Decimal | None = Field(None, ge=0, description="税额（元）；不填按税率现算")
    supplier_id: int | None = Field(None, description="进项票必填：谁开的票")
    customer_id: int | None = Field(None, description="销项票必填：开给谁")
    purchase_order_ids: list[int] = Field(
        default_factory=list, description="进项票必填（≥1 张）：这张票抵的是哪几车货"
    )
    ledger_ids: list[int] = Field(
        default_factory=list, description="销项票可选：这张票开的是哪几笔应收"
    )
    note: str = Field("", max_length=256)


class InvoiceUpdate(MoneyInput):
    """改一张**已登记**的票。字段全可空：没给的字段一个字不动。"""

    invoice_no: str | None = Field(None, max_length=64)
    invoice_date: date | None = None
    amount: Decimal | None = Field(None, gt=0)
    tax_rate: Decimal | None = Field(None, ge=0, le=100)
    tax_amount: Decimal | None = Field(None, ge=0)
    supplier_id: int | None = None
    customer_id: int | None = None
    purchase_order_ids: list[int] | None = None
    ledger_ids: list[int] | None = None
    note: str | None = Field(None, max_length=256)


class InvoiceBrief(BaseModel):
    """列表 / 详情共用的形状。金额是 Decimal（两位小数在端点层格式化）。"""

    id: int
    direction: str
    invoice_no: str = ""
    invoice_date: date
    amount: Decimal = Decimal("0.00")
    tax_rate: Decimal | None = None
    tax_amount: Decimal | None = None
    status: str = "REGISTERED"
    supplier_id: int | None = None
    supplier_name: str = ""
    customer_id: int | None = None
    customer_name: str = ""
    note: str = ""
    counts_in_tax: bool = True
    purchase_order_ids: list[int] = Field(default_factory=list)
    ledger_ids: list[int] = Field(default_factory=list)
    is_deleted: bool = False
    created_at: str = ""


class TaxSideOut(BaseModel):
    """税汇的一侧（销项 / 进项）。未税票单独列，不进 `tax_amount`。"""

    count: int = 0
    amount: Decimal = Decimal("0.00")
    net_amount: Decimal = Decimal("0.00")
    tax_amount: Decimal = Decimal("0.00")
    untaxed_count: int = 0
    untaxed_amount: Decimal = Decimal("0.00")


class TaxInvoiceRowOut(BaseModel):
    """税账报表里的明细行（一段窗口内的每一张票）。"""

    id: int
    direction: str
    invoice_no: str = ""
    invoice_date: date
    amount: Decimal = Decimal("0.00")
    tax_rate: Decimal | None = None
    tax_amount: Decimal | None = None
    net_amount: Decimal | None = None
    status: str = "REGISTERED"
    party_name: str = ""
    counts_in_tax: bool = True


class TaxRateBucketOut(BaseModel):
    """按税率分的一格（销项 / 进项各自看）。只统计算数的票（作废与未税不在里面）。"""

    direction: str
    tax_rate: Decimal = Decimal("0.00")
    count: int = 0
    amount: Decimal = Decimal("0.00")
    net_amount: Decimal = Decimal("0.00")
    tax_amount: Decimal = Decimal("0.00")


class TaxSummaryOut(BaseModel):
    """`GET /reports/tax-summary` 的返回体。"""

    mode: str
    anchor: date
    date_from: date
    date_to: date
    label: str
    output: TaxSideOut = Field(default_factory=TaxSideOut)
    input: TaxSideOut = Field(default_factory=TaxSideOut)
    vat_payable: Decimal = Decimal("0.00")
    by_rate: list[TaxRateBucketOut] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    invoices: list[TaxInvoiceRowOut] = Field(default_factory=list)
    voided_count: int = 0
    default_tax_rate: Decimal = Decimal("3.00")